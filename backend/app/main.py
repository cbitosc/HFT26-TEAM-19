"""FastAPI app. Contract: docs/api-contract.md. Binds to loopback by default."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .adapters import InferenceAdapter
from .config import Settings
from .corrections import CorrectionError, apply_correction
from .guidance import BOARD_VARIANTS, build_findings, build_steps
from .intake import IntakeError, prepare_image
from .repeats import find_repeats
from .jobs import JobRunner
from .store import Store

log = logging.getLogger("visionguard")

EXT = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png", "WEBP": "webp", "BMP": "bmp"}
STATUS_FOR_INTAKE = {"too_large": 413, "unsupported_format": 415}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def create_app(settings: Optional[Settings] = None, adapter: Optional[InferenceAdapter] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir)
    adapter = adapter or settings.build_adapter()
    runner = JobRunner(store, adapter, settings.limits, settings.max_tokens, settings.detail_pass, settings.tile_grid, settings.sampling, settings.repeats, settings.similar_threshold)
    submit_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        n = store.fail_interrupted()
        if n:
            log.warning("marked %d interrupted analysis job(s) as failed", n)
        runner.start()
        yield
        runner.stop()

    app = FastAPI(title="VisionGuard", version="0.2.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    # Blocks DNS-rebinding: a web page cannot reach this server through another hostname.
    hosts = ["*"] if settings.allow_non_loopback else ["127.0.0.1", "localhost", "[::1]", "testserver"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.state.store, app.state.runner, app.state.settings = store, runner, settings

    # ---- errors: always {code, message} -------------------------------------------------

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else f"http_{exc.status_code}"
        return JSONResponse({"code": code, "message": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p not in ("body",))
        return JSONResponse(
            {"code": "invalid_request", "message": f"The request is not valid{': ' + where if where else ''}. {first.get('msg', '')}".strip()},
            status_code=422,
        )

    # ---- helpers ------------------------------------------------------------------------

    def need_image(image_id: str) -> dict:
        image = store.get_image(image_id)
        if not image:
            raise ApiError(404, "image_not_found", "That photo is not stored. Upload it again.")
        return image

    def need_analysis(job_id: str) -> dict:
        analysis = store.get_analysis(job_id)
        if not analysis:
            raise ApiError(404, "analysis_not_found", "That analysis does not exist. Analyze the photo again.")
        return analysis

    def state(analysis_id: str, image: dict) -> dict:
        observations = store.list_observations(analysis_id)
        findings, checked = build_findings(observations)
        return {
            "observations": [o.model_dump(mode="json") for o in observations],
            "findings": findings,
            "concerns_checked": checked,
            "steps": build_steps(observations, image["board_variant"]),
            "board_variant": image["board_variant"],
        }

    # ---- routes -------------------------------------------------------------------------

    @app.get("/api/health")
    def health():
        info: dict[str, Any] = {"ok": True, "adapter": adapter.name, "is_mock": adapter.is_mock}
        try:
            detail = adapter.health()
        except Exception:  # health must never raise
            detail = {}
        info["model"] = detail.get("model") or getattr(adapter, "model", "MOCK")
        info["model_reachable"] = detail.get("reachable", adapter.is_mock)
        info["model_installed"] = detail.get("model_installed", adapter.is_mock)
        info["ok"] = bool(info["model_reachable"] and info["model_installed"])
        if not info["ok"] and "error" in detail:
            info["message"] = detail["error"]
        elif not info["ok"]:
            info["message"] = "The model is not installed. Pull it with Ollama, then reload."
        return info

    @app.post("/api/images")
    def upload_image(image: UploadFile = File(...)):
        limit = settings.limits.max_bytes
        data = image.file.read(limit + 1)
        try:
            prepared = prepare_image(data, settings.limits)
        except IntakeError as exc:
            status = STATUS_FOR_INTAKE.get(exc.code, 422)
            raise ApiError(status, exc.code, exc.message) from exc
        image_id = f"img_{uuid.uuid4().hex[:10]}"
        w, h = prepared.size
        q = prepared.quality
        quality = {
            "ok": q.ok,
            "problems": q.problems,
            "sharpness": q.sharpness,
            "brightness": q.brightness,
        }
        store.add_image(image_id, image.filename or "", data, EXT.get(prepared.original_format, "img"), w, h, quality)
        return {"image_id": image_id, "width": w, "height": h, "quality": quality}

    @app.patch("/api/images/{image_id}")
    def patch_image(image_id: str, body: dict = Body(...)):
        image = need_image(image_id)
        if set(body) - {"board_variant"}:
            raise ApiError(422, "unknown_field", "Only board_variant can be changed on a photo.")
        variant = body.get("board_variant") or None
        if variant is not None and variant not in BOARD_VARIANTS:
            raise ApiError(422, "unknown_variant", "That board is not in the supported list. Choose one from the list.")
        store.set_board_variant(image_id, variant)
        image["board_variant"] = variant
        latest = store.latest_done_analysis(image_id)
        steps = build_steps(store.list_observations(latest), variant) if latest else []
        return {"board_variant": variant, "steps": steps}

    @app.post("/api/analyses", status_code=202)
    def start_analysis(body: dict = Body(...)):
        image = need_image(str(body.get("image_id", "")))
        with submit_lock:  # check and insert as one step so two clicks cannot both start
            if store.active_analysis():
                raise ApiError(409, "busy", "Another analysis is still running. Wait for it or cancel it.")
            job_id = f"job_{uuid.uuid4().hex[:8]}"
            store.add_analysis(job_id, image["id"])
        runner.submit(job_id)
        return {"job_id": job_id, "status": "queued"}

    @app.get("/api/analyses/{job_id}")
    def get_analysis(job_id: str):
        analysis = need_analysis(job_id)
        status = analysis["status"]
        out: dict[str, Any] = {"job_id": job_id, "status": status}
        if status == "failed":
            out["error"] = analysis["error"] or {"code": "failed", "message": "The analysis failed."}
        elif status == "done":
            meta = analysis["meta"] or {}
            image = need_image(analysis["image_id"])
            out.update(state(job_id, image))
            out.update(
                model=meta.get("model"),
                adapter=meta.get("adapter"),
                is_mock=bool(meta.get("is_mock")),
                latency_s=meta.get("latency_s"),
                attempts=meta.get("attempts"),
                dropped=meta.get("dropped", []),
                detail_pass=meta.get("detail_pass"),
                repeat_pass=meta.get("repeat_pass"),
                warnings=meta.get("warnings", []),
                tiles=meta.get("tiles"),
            )
        return out

    @app.delete("/api/analyses/{job_id}", status_code=204)
    def cancel_analysis(job_id: str):
        need_analysis(job_id)
        # Only a queued or running job can be cancelled. A running model call cannot be interrupted;
        # its result is discarded when it returns.
        store.set_status(job_id, "cancelled", only_if=("queued", "running"), finished=time.time())
        return Response(status_code=204)

    @app.patch("/api/observations/{observation_id}")
    def patch_observation(observation_id: str, body: dict = Body(...)):
        found = store.get_observation(observation_id)
        if not found:
            raise ApiError(404, "observation_not_found", "That part no longer exists. Analyze the photo again.")
        analysis_id, obs = found
        analysis = need_analysis(analysis_id)
        image = need_image(analysis["image_id"])
        try:
            updated = apply_correction(obs, body, image["width"], image["height"])
        except CorrectionError as exc:
            raise ApiError(422, exc.code, exc.message) from exc
        store.update_observation(updated)
        out = state(analysis_id, image)
        out.pop("board_variant", None)
        return out

    @app.post("/api/observations/{observation_id}/similar")
    def find_similar(observation_id: str):
        """Search the whole photo for parts that look like this one. No model call; results are suggestions."""
        found = store.get_observation(observation_id)
        if not found:
            raise ApiError(404, "observation_not_found", "That part no longer exists. Analyze the photo again.")
        analysis_id, obs = found
        analysis = need_analysis(analysis_id)
        image = need_image(analysis["image_id"])
        try:
            prepared = prepare_image(store.read_image_bytes(image), settings.limits)
        except IntakeError as exc:
            raise ApiError(422, exc.code, exc.message) from exc
        existing = store.list_observations(analysis_id)
        taken = {o.id for o in existing}
        prefix = f"sim_{uuid.uuid4().hex[:6]}"
        new, summary = find_repeats(prepared, existing, exemplars=[obs], threshold=settings.similar_threshold, id_prefix=prefix)
        new = [o for o in new if o.id not in taken]
        if new:
            store.add_observations(analysis_id, new)
        out = state(analysis_id, image)
        out.pop("board_variant", None)
        out["added"] = [o.id for o in new]
        out["similar"] = summary
        return out

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"], include_in_schema=False)
    def unknown_api(rest: str):
        raise ApiError(404, "not_found", f"There is no endpoint /api/{rest}.")

    # ---- built frontend -----------------------------------------------------------------

    dist = settings.frontend_dist
    if dist and (dist / "index.html").is_file():
        root = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(root / "index.html")

    return app


def _app_factory() -> FastAPI:  # uvicorn --factory app.main:_app_factory
    return create_app()
