"""Inference adapter interface. Keeps the model runtime swappable and testable."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class AdapterError(RuntimeError):
    """Base error. ``code`` drives the recovery message shown to the user."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ModelUnavailable(AdapterError):
    def __init__(self, message: str = "The local model server is not reachable. Start Ollama and retry."):
        super().__init__("model_unavailable", message)


class OutOfMemory(AdapterError):
    def __init__(self, message: str = "The GPU ran out of memory. Retrying with a smaller image or the 2B model may help."):
        super().__init__("out_of_memory", message)


@dataclass
class InferenceRequest:
    prompt: str
    images: list[bytes]  # JPEG/PNG bytes
    system: Optional[str] = None
    json_schema: Optional[dict] = None
    max_tokens: int = 2048
    # Qwen3-VL Instruct recommended sampling (temperature 0.7, top_p 0.8, top_k 20). Near-greedy
    # settings (0.1) made both models loop on the first real photo. presence_penalty 1.5 is the value
    # in the model guide. The sweep on the sample photo tried 0, 0.5 and 1.5: 0 and 0.5 still looped and
    # were cut off at the token limit, 1.5 finished in 17 s with the best score. One photo, one seed.
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    presence_penalty: float = 1.5
    seed: int = 3407


@dataclass
class InferenceResult:
    text: str
    model: str
    adapter: str  # "ollama" | "mock" | "featherless"
    is_mock: bool = False
    latency_s: float = 0.0
    load_s: Optional[float] = None
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    extra: dict = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        """The runtime stopped at the token limit, so the reply ends mid-way."""
        return self.extra.get("done_reason") == "length"


class InferenceAdapter(ABC):
    name: str = "base"
    is_mock: bool = False

    @abstractmethod
    def analyze(self, req: InferenceRequest) -> InferenceResult: ...

    def health(self) -> dict:
        return {"adapter": self.name, "mock": self.is_mock}
