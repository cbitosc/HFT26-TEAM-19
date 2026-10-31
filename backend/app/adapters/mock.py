"""Explicitly labelled MOCK adapter for UI development and tests.

Everything it returns is flagged ``is_mock`` and the model name is "MOCK"; the API and
every export must surface that flag. It is never the default.
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from .base import InferenceAdapter, InferenceRequest, InferenceResult

CANNED = [
    {
        "label": "microcontroller chip (MOCK)",
        "category": "ic_package",
        "bbox_2d": [400, 300, 620, 520],
        "marking_text": None,
        "identity_guess": None,
        "readable": False,
        "note": "mock data",
    },
    {
        "label": "40-pin header (MOCK)",
        "category": "gpio_header",
        "bbox_2d": [60, 40, 940, 120],
        "marking_text": None,
        "identity_guess": None,
        "readable": False,
        "note": "mock data",
    },
]


class MockAdapter(InferenceAdapter):
    name = "mock"
    is_mock = True

    def __init__(self, responder: Optional[Callable[[InferenceRequest], str]] = None, done_reason: Optional[str] = None):
        self._responder = responder
        self._done_reason = done_reason  # set to "length" to mimic a reply cut off at the token limit

    def analyze(self, req: InferenceRequest) -> InferenceResult:
        if self._responder:
            text = self._responder(req)
        elif req.prompt.startswith("This is a close-up crop"):
            text = json.dumps([{**CANNED[0], "label": "chip close-up (MOCK)", "bbox_2d": [0, 0, 1000, 1000]}])
        else:
            text = json.dumps(CANNED)
        extra = {"done_reason": self._done_reason} if self._done_reason else {}
        return InferenceResult(text=text, model="MOCK", adapter=self.name, is_mock=True, latency_s=0.0, extra=extra)
