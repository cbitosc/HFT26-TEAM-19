"""Ollama adapter (default). Standard library only so it has no extra dependency.

Talks to a LOOPBACK Ollama by default. Uses /api/chat with base64 images, a JSON-schema
``format`` for structured output, and ``keep_alive`` so the model stays loaded.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Optional

from .base import (
    AdapterError,
    InferenceAdapter,
    InferenceRequest,
    InferenceResult,
    ModelUnavailable,
    OutOfMemory,
)

DEFAULT_HOST = "http://127.0.0.1:11434"


class OllamaAdapter(InferenceAdapter):
    name = "ollama"

    def __init__(
        self,
        model: str,
        host: str = DEFAULT_HOST,
        num_ctx: int = 8192,
        keep_alive: str = "30m",
        timeout_s: float = 300.0,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.timeout_s = timeout_s

    # -- helpers -------------------------------------------------------------------------

    def _post(self, path: str, payload: dict, timeout: Optional[float] = None) -> dict:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.host}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            low = body.lower()
            if "out of memory" in low or "cuda" in low and "memory" in low:
                raise OutOfMemory() from exc
            if exc.code == 404:
                raise AdapterError(
                    "model_not_found",
                    f"Model '{self.model}' is not installed. Run: ollama pull {self.model}",
                ) from exc
            raise AdapterError("runtime_error", f"Ollama returned HTTP {exc.code}: {body[:300]}") from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            raise ModelUnavailable() from exc

    def _get(self, path: str) -> dict:
        try:
            with urllib.request.urlopen(f"{self.host}{path}", timeout=5) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError) as exc:
            raise ModelUnavailable() from exc

    # -- interface -----------------------------------------------------------------------

    def analyze(self, req: InferenceRequest) -> InferenceResult:
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append(
            {
                "role": "user",
                "content": req.prompt,
                "images": [base64.b64encode(b).decode() for b in req.images],
            }
        )
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": req.temperature,
                "top_p": req.top_p,
                "top_k": req.top_k,
                "presence_penalty": req.presence_penalty,
                "seed": req.seed,
                "num_predict": req.max_tokens,
                "num_ctx": self.num_ctx,
            },
        }
        if req.json_schema is not None:
            payload["format"] = req.json_schema

        t0 = time.perf_counter()
        body = self._post("/api/chat", payload)
        latency = time.perf_counter() - t0

        text = (body.get("message") or {}).get("content", "")
        load_ns = body.get("load_duration")
        return InferenceResult(
            text=text,
            model=self.model,
            adapter=self.name,
            latency_s=round(latency, 3),
            load_s=round(load_ns / 1e9, 3) if isinstance(load_ns, (int, float)) else None,
            prompt_tokens=body.get("prompt_eval_count"),
            output_tokens=body.get("eval_count"),
            extra={
                "total_duration_s": round(body.get("total_duration", 0) / 1e9, 3),
                "done_reason": body.get("done_reason"),
            },
        )

    def health(self) -> dict:
        info = super().health()
        info.update({"model": self.model, "host": self.host})
        try:
            tags = self._get("/api/tags")
            names = [m.get("name") for m in tags.get("models", [])]
            info["reachable"] = True
            info["model_installed"] = any(n == self.model or n == f"{self.model}:latest" for n in names)
            ps = self._get("/api/ps").get("models", [])
            info["loaded"] = [
                {
                    "name": m.get("name"),
                    "size_vram_gb": round(m.get("size_vram", 0) / 1e9, 2),
                    "size_gb": round(m.get("size", 0) / 1e9, 2),
                }
                for m in ps
            ]
        except AdapterError as exc:
            info.update({"reachable": False, "error": exc.message})
        return info
