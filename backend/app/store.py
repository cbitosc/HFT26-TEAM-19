"""SQLite persistence (standard library). One connection per call; WAL so the worker and the
request threads do not block each other. Observations are stored as validated JSON."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .schemas import Observation

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
  id TEXT PRIMARY KEY,
  filename TEXT,
  path TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  quality TEXT NOT NULL,
  board_variant TEXT,
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
  id TEXT PRIMARY KEY,
  image_id TEXT NOT NULL REFERENCES images(id),
  status TEXT NOT NULL,
  error TEXT,
  meta TEXT,
  raw_text TEXT,
  created REAL NOT NULL,
  started REAL,
  finished REAL
);
CREATE TABLE IF NOT EXISTS observations (
  id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS obs_by_analysis ON observations(analysis_id, position);
"""


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.images_dir = self.dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "visionguard.sqlite3"
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # -- images ---------------------------------------------------------------------------

    def add_image(self, image_id: str, filename: str, data: bytes, ext: str, width: int, height: int, quality: dict) -> None:
        path = self.images_dir / f"{image_id}.{ext}"
        path.write_bytes(data)  # original bytes, untouched
        with self._conn() as c:
            c.execute(
                "INSERT INTO images (id, filename, path, width, height, quality, created) VALUES (?,?,?,?,?,?,?)",
                (image_id, filename, str(path), width, height, json.dumps(quality), time.time()),
            )

    def get_image(self, image_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        return dict(row) if row else None

    def set_board_variant(self, image_id: str, variant: Optional[str]) -> None:
        with self._conn() as c:
            c.execute("UPDATE images SET board_variant=? WHERE id=?", (variant, image_id))

    def read_image_bytes(self, image: dict) -> bytes:
        return Path(image["path"]).read_bytes()

    # -- analyses -------------------------------------------------------------------------

    def add_analysis(self, analysis_id: str, image_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO analyses (id, image_id, status, created) VALUES (?,?,?,?)",
                (analysis_id, image_id, "queued", time.time()),
            )

    def get_analysis(self, analysis_id: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["error"] = json.loads(d["error"]) if d["error"] else None
        d["meta"] = json.loads(d["meta"]) if d["meta"] else None
        return d

    def latest_done_analysis(self, image_id: str) -> Optional[str]:
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM analyses WHERE image_id=? AND status='done' ORDER BY created DESC LIMIT 1", (image_id,)
            ).fetchone()
        return row["id"] if row else None

    def active_analysis(self) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM analyses WHERE status IN ('queued','running') LIMIT 1").fetchone()
        return dict(row) if row else None

    def set_status(self, analysis_id: str, status: str, *, only_if: Optional[tuple[str, ...]] = None, **fields: Any) -> bool:
        """Update status (and optional fields). With ``only_if`` it is a compare-and-set: it returns
        False and changes nothing when the current status is not one of the allowed ones."""
        cols = ["status=?"]
        vals: list[Any] = [status]
        for key in ("error", "meta"):
            if key in fields:
                cols.append(f"{key}=?")
                vals.append(json.dumps(fields[key]) if fields[key] is not None else None)
        for key in ("raw_text", "started", "finished"):
            if key in fields:
                cols.append(f"{key}=?")
                vals.append(fields[key])
        sql = f"UPDATE analyses SET {', '.join(cols)} WHERE id=?"
        vals.append(analysis_id)
        if only_if:
            sql += f" AND status IN ({','.join('?' * len(only_if))})"
            vals.extend(only_if)
        with self._conn() as c:
            return c.execute(sql, vals).rowcount > 0

    def fail_interrupted(self) -> int:
        """Jobs left queued or running by a previous process cannot continue."""
        err = json.dumps({"code": "interrupted", "message": "The server restarted before this analysis finished. Analyze again."})
        with self._conn() as c:
            return c.execute(
                "UPDATE analyses SET status='failed', error=?, finished=? WHERE status IN ('queued','running')",
                (err, time.time()),
            ).rowcount

    # -- observations ---------------------------------------------------------------------

    def save_observations(self, analysis_id: str, observations: list[Observation]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM observations WHERE analysis_id=?", (analysis_id,))
            c.executemany(
                "INSERT INTO observations (id, analysis_id, position, data) VALUES (?,?,?,?)",
                [(o.id, analysis_id, i, o.model_dump_json()) for i, o in enumerate(observations)],
            )

    def add_observations(self, analysis_id: str, observations: list[Observation]) -> None:
        """Append rows after the existing ones without touching them."""
        with self._conn() as c:
            start = c.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM observations WHERE analysis_id=?", (analysis_id,)).fetchone()[0]
            c.executemany(
                "INSERT INTO observations (id, analysis_id, position, data) VALUES (?,?,?,?)",
                [(o.id, analysis_id, start + i, o.model_dump_json()) for i, o in enumerate(observations)],
            )

    def list_observations(self, analysis_id: str) -> list[Observation]:
        with self._conn() as c:
            rows = c.execute("SELECT data FROM observations WHERE analysis_id=? ORDER BY position", (analysis_id,)).fetchall()
        return [Observation.model_validate_json(r["data"]) for r in rows]

    def get_observation(self, observation_id: str) -> Optional[tuple[str, Observation]]:
        with self._conn() as c:
            row = c.execute("SELECT analysis_id, data FROM observations WHERE id=?", (observation_id,)).fetchone()
        if not row:
            return None
        return row["analysis_id"], Observation.model_validate_json(row["data"])

    def update_observation(self, obs: Observation) -> None:
        with self._conn() as c:
            c.execute("UPDATE observations SET data=? WHERE id=?", (obs.model_dump_json(), obs.id))
