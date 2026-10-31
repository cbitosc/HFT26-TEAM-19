"""Tiled analysis for small parts.

At the 1280 px overview size a resistor on a 2752 px photo is about 10 px wide, below what the model
can see. This pass shows the model overlapping sections of the ORIGINAL photo, each at (about) full
resolution, and merges what it finds with the whole-photo pass.

* Tiles overlap by 25 %, so any part up to a quarter of a tile in size lies fully inside at least one tile.
* A box that touches an inner tile edge is cut off by the tile, not a part, and is dropped. Image borders are not edges.
* Big parts (headers, jacks) come from the whole-photo pass, which is merged first and wins.
* A tile box is a duplicate if it overlaps a kept box of the same category (IoU >= 0.5), or lies mostly inside one.
* A tile that fails (bad JSON, or any model error) is reported and skipped. The whole-photo result is never lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import prompts
from .adapters.base import AdapterError, InferenceAdapter
from PIL import Image

from .geometry import ImageView, iou
from .intake import PreparedImage
from .pipeline import DEFAULT_MAX_TOKENS, AnalysisFailed, OverviewResult, run_overview, run_pass
from .schemas import Observation

OVERLAP = 0.25
EDGE_MARGIN = 0.015  # fraction of the tile size
DUPLICATE_IOU = 0.5
CONTAINED = 0.8
MAX_TILES = 12
MIN_TILE_LONG_SIDE = 768


@dataclass(frozen=True)
class Tile:
    index: int
    box: tuple[int, int, int, int]  # original px: x1, y1, x2, y2
    inner_left: bool
    inner_top: bool
    inner_right: bool
    inner_bottom: bool


def parse_grid(spec: str | None) -> tuple[int, int] | None:
    """'off' / '' -> None. '3x2' -> (3, 2): 3 columns, 2 rows."""
    if not spec or spec.strip().lower() in {"off", "0", "no", "none"}:
        return None
    try:
        c, r = spec.lower().split("x")
        cols, rows = int(c), int(r)
    except ValueError as exc:
        raise ValueError(f"Tile grid must look like 3x2, got {spec!r}.") from exc
    if not (1 <= cols <= 6 and 1 <= rows <= 6) or cols * rows > MAX_TILES:
        raise ValueError(f"Tile grid {spec!r} is out of range. Use at most {MAX_TILES} tiles.")
    return cols, rows


def plan_tiles(width: int, height: int, cols: int, rows: int, overlap: float = OVERLAP) -> list[Tile]:
    def spans(total: int, n: int) -> list[tuple[int, int]]:
        if n == 1:
            return [(0, total)]
        size = total / (n - (n - 1) * overlap)
        step = size * (1 - overlap)
        out = []
        for i in range(n):
            a = round(i * step)
            b = total if i == n - 1 else round(a + size)
            out.append((a, min(b, total)))
        return out

    xs, ys = spans(width, cols), spans(height, rows)
    tiles = []
    for r, (y1, y2) in enumerate(ys):
        for c, (x1, x2) in enumerate(xs):
            tiles.append(Tile(len(tiles), (x1, y1, x2, y2), c > 0, r > 0, c < cols - 1, r < rows - 1))
    return tiles


def _cut_by_tile(o: Observation, t: Tile) -> bool:
    x1, y1, x2, y2 = t.box
    mx, my = EDGE_MARGIN * (x2 - x1), EDGE_MARGIN * (y2 - y1)
    b = o.bbox
    return (
        (t.inner_left and b[0] <= x1 + mx)
        or (t.inner_top and b[1] <= y1 + my)
        or (t.inner_right and b[2] >= x2 - mx)
        or (t.inner_bottom and b[3] >= y2 - my)
    )


def _inside_fraction(inner, outer) -> float:
    ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    ix2, iy2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    area = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    whole = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return area / whole if whole > 0 else 0.0


def merge(kept: list[Observation], candidates: list[Observation]) -> tuple[list[Observation], int]:
    """Add each candidate unless it duplicates a kept box of the same category. Returns (merged, n_duplicates)."""
    out = list(kept)
    dupes = 0
    for c in candidates:
        if any(
            k.category == c.category and (iou(k.bbox, c.bbox) >= DUPLICATE_IOU or _inside_fraction(c.bbox, k.bbox) >= CONTAINED)
            for k in out
        ):
            dupes += 1
            continue
        out.append(c)
    return out, dupes


def run_overview_tiled(
    prepared: PreparedImage,
    adapter: InferenceAdapter,
    *,
    image_id: str,
    grid: tuple[int, int],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    sampling: dict | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> OverviewResult:
    base = run_overview(prepared, adapter, image_id=image_id, max_tokens=max_tokens, sampling=sampling)
    ow, oh = prepared.size
    tiles = plan_tiles(ow, oh, *grid)
    long_side = max(prepared.analysis.size)
    summary = {"grid": f"{grid[0]}x{grid[1]}", "planned": len(tiles), "ok": 0, "failed": 0, "added": 0, "duplicates": 0, "cut_by_edge": 0, "stopped": False}
    warnings = list(base.warnings)
    dropped = list(base.dropped)
    latency = base.latency_s
    raw = [base.raw_text]
    attempts = base.attempts
    conventions = set(base.conventions)
    truncated = base.truncated
    merged = list(base.observations)

    for t in tiles:
        if should_stop():
            summary["stopped"] = True
            break
        x1, y1, x2, y2 = t.box
        crop = prepared.original.crop(t.box)
        cw, ch = crop.size
        big = max(cw, ch)
        if big > long_side:
            s = long_side / big
        elif big < MIN_TILE_LONG_SIDE:
            s = min(MIN_TILE_LONG_SIDE / big, 4.0)  # a tile of a small photo is enlarged for the model
        else:
            s = 1.0
        shown = crop.resize((max(1, round(cw * s)), max(1, round(ch * s))), Image.LANCZOS) if s != 1.0 else crop
        view = ImageView(shown.size[0], shown.size[1], float(x1), float(y1), shown.size[0] / cw)
        label = f"tile {t.index + 1}/{len(tiles)}"
        try:
            res = run_pass(
                shown, view, adapter,
                original_size=(ow, oh), region=(x1, y1, x2, y2), image_id=image_id,
                prompt=prompts.TILE, max_tokens=max_tokens, sampling=sampling,
            )
        except AnalysisFailed as exc:
            summary["failed"] += 1
            warnings.append(f"{label}: the model gave no usable answer, so this section was skipped")
            dropped.append(f"{label}: {exc.detail}")
            continue
        except AdapterError as exc:
            summary["failed"] += 1
            summary["stopped"] = True
            warnings.append(f"{label}: {exc.message} The remaining sections were skipped.")
            break
        summary["ok"] += 1
        latency += res.latency_s
        attempts += res.attempts
        raw.append(res.raw_text)
        conventions |= res.conventions
        truncated = truncated or res.truncated
        dropped += [f"{label}: {d}" for d in res.dropped]
        warnings += [f"{label}: {w}" for w in res.warnings]
        fresh = [o for o in res.observations if not _cut_by_tile(o, t)]
        summary["cut_by_edge"] += len(res.observations) - len(fresh)
        before = len(merged)
        merged, dupes = merge(merged, fresh)
        summary["duplicates"] += dupes
        summary["added"] += len(merged) - before

    merged = [o.model_copy(update={"id": f"obs_{i:03d}"}) for i, o in enumerate(merged)]
    from .pipeline import finish

    return finish(prepared, OverviewResult(
        observations=merged,
        dropped=dropped,
        conventions=conventions,
        model=base.model,
        adapter=base.adapter,
        is_mock=base.is_mock,
        attempts=attempts,
        latency_s=round(latency, 3),
        load_s=base.load_s,
        raw_text="\n--- tile ---\n".join(raw),
        truncated=truncated,
        warnings=warnings,
        tiles=summary,
    ))
