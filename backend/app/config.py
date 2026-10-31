"""Settings from environment variables (see .env.example). No third-party dependency."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import InferenceAdapter, MockAdapter, OllamaAdapter
from .intake import IntakeLimits

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a whole number, got {raw!r}") from exc


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a number, got {raw!r}") from exc


@dataclass
class Settings:
    adapter: str = "ollama"
    ollama_host: str = "http://127.0.0.1:11434"
    model: str = "huihui_ai/qwen3-vl-abliterated:4b-instruct"
    num_ctx: int = 8192
    keep_alive: str = "30m"
    max_tokens: int = 2048
    tiles: str = "off"
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    presence_penalty: float = 1.5
    detail_pass: bool = True
    max_upload_mb: int = 25
    max_pixels: int = 60_000_000
    analysis_long_side: int = 1280
    analysis_min_long_side: int = 1024
    repeats: bool = False
    similar_threshold: float = 0.75
    host: str = "127.0.0.1"
    port: int = 8000
    allow_non_loopback: bool = False
    data_dir: Path = field(default_factory=lambda: Path("data"))
    frontend_dist: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        here = Path(__file__).resolve().parent.parent.parent
        dist = here / "frontend" / "dist"
        return cls(
            adapter=os.environ.get("VG_ADAPTER", "ollama").strip().lower(),
            ollama_host=os.environ.get("OLLAMA_HOST", cls.ollama_host),
            model=os.environ.get("VG_MODEL", cls.model),
            num_ctx=_int("VG_NUM_CTX", cls.num_ctx),
            keep_alive=os.environ.get("VG_KEEP_ALIVE", cls.keep_alive),
            max_tokens=_int("VG_MAX_TOKENS", cls.max_tokens),
            tiles=os.environ.get("VG_TILES", "off").strip(),
            temperature=_float("VG_TEMPERATURE", cls.temperature),
            top_p=_float("VG_TOP_P", cls.top_p),
            top_k=_int("VG_TOP_K", cls.top_k),
            presence_penalty=_float("VG_PRESENCE_PENALTY", cls.presence_penalty),
            detail_pass=os.environ.get("VG_DETAIL_PASS", "1") != "0",
            max_upload_mb=_int("VG_MAX_UPLOAD_MB", cls.max_upload_mb),
            max_pixels=_int("VG_MAX_PIXELS", cls.max_pixels),
            analysis_long_side=_int("VG_ANALYSIS_LONG_SIDE", cls.analysis_long_side),
            analysis_min_long_side=_int("VG_ANALYSIS_MIN_LONG_SIDE", cls.analysis_min_long_side),
            repeats=os.environ.get("VG_REPEATS", "0") == "1",
            similar_threshold=_float("VG_SIMILAR_THRESHOLD", cls.similar_threshold),
            host=os.environ.get("VG_HOST", cls.host),
            port=_int("VG_PORT", cls.port),
            allow_non_loopback=os.environ.get("VG_ALLOW_NON_LOOPBACK", "0") == "1",
            data_dir=Path(os.environ.get("VG_DATA_DIR", str(here / "data"))),
            frontend_dist=dist if dist.is_dir() else None,
        )

    @property
    def sampling(self) -> dict:
        return {"temperature": self.temperature, "top_p": self.top_p, "top_k": self.top_k, "presence_penalty": self.presence_penalty}

    @property
    def tile_grid(self):
        from .tiles import parse_grid

        try:
            return parse_grid(self.tiles)
        except ValueError as exc:
            raise SystemExit(f"VG_TILES: {exc}") from exc

    @property
    def limits(self) -> IntakeLimits:
        return IntakeLimits(
            max_bytes=self.max_upload_mb * 1024 * 1024,
            max_pixels=self.max_pixels,
            analysis_long_side=self.analysis_long_side,
            analysis_min_long_side=self.analysis_min_long_side,
        )

    def check_bind(self) -> None:
        """Refuse to listen beyond this machine unless the operator says so explicitly."""
        if self.host not in LOOPBACK and not self.allow_non_loopback:
            raise SystemExit(
                f"Refusing to bind to {self.host}. VisionGuard listens on this computer only by default.\n"
                "Set VG_ALLOW_NON_LOOPBACK=1 to override. There is no login, so anyone on the network "
                "could upload photos and read results."
            )

    def build_adapter(self) -> InferenceAdapter:
        if self.adapter == "mock":
            return MockAdapter()
        if self.adapter == "ollama":
            return OllamaAdapter(
                model=self.model,
                host=self.ollama_host,
                num_ctx=self.num_ctx,
                keep_alive=self.keep_alive,
            )
        raise SystemExit(
            f"VG_ADAPTER={self.adapter!r} is not available. Use 'ollama' or 'mock'. "
            "The optional cloud adapter is not built."
        )
