"""Validated structured observations (the contract shared by backend, API and UI)."""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Category(str, Enum):
    ic_package = "ic_package"
    microcontroller_module = "microcontroller_module"
    gpio_header = "gpio_header"
    connector = "connector"
    usb_port = "usb_port"
    capacitor = "capacitor"
    resistor = "resistor"
    led = "led"
    button = "button"
    wire = "wire"
    board = "board"
    other = "other"


class IdStatus(str, Enum):
    confirmed = "confirmed"  # marking matched a reference exactly, or the user confirmed it
    tentative = "tentative"  # category clear; identity inferred
    unknown = "unknown"  # unreadable / not identifiable


class Source(str, Enum):
    vlm = "vlm"
    user = "user"
    assist = "assist"  # optional non-VLM detector, only if measurements justify it


class Candidate(BaseModel):
    identity: str = Field(min_length=1, max_length=120)
    reference_id: Optional[str] = None  # set only by reference matching, never by the model


class Observation(BaseModel):
    id: str
    image_id: str
    frame_id: Optional[str] = None
    category: Category
    marking_text: Optional[str] = Field(default=None, max_length=200)
    candidates: list[Candidate] = Field(default_factory=list)
    bbox: tuple[float, float, float, float]
    bbox_space: Literal["original_px"] = "original_px"
    status: IdStatus = IdStatus.unknown
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)
    model_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    model_score_note: Literal["uncalibrated"] = "uncalibrated"
    source: Source = Source.vlm

    @field_validator("bbox")
    @classmethod
    def _bbox_ok(cls, v):
        if not all(math.isfinite(x) for x in v):
            raise ValueError("bbox must be finite")
        if v[2] <= v[0] or v[3] <= v[1]:
            raise ValueError("bbox must satisfy x1<x2 and y1<y2")
        return v

    @model_validator(mode="after")
    def _status_consistency(self):
        # Hard evidence rules, independent of what any model says.
        if self.status == IdStatus.confirmed and self.source == Source.vlm and not self.reference_ids:
            raise ValueError("a model-sourced observation cannot be 'confirmed' without a matched reference")
        if self.status == IdStatus.unknown and self.candidates:
            raise ValueError("an 'unknown' observation must not carry candidate identities")
        return self


# ---- what we ask the model to return (no ids, no references: the app adds those) ----------


class RawDetection(BaseModel):
    """One item of the model's JSON array. Deliberately small so a 4B model can produce it."""

    label: str = Field(min_length=1, max_length=80)
    category: Category = Category.other
    bbox_2d: list[float] = Field(min_length=4, max_length=4)
    marking_text: Optional[str] = Field(default=None, max_length=200)
    identity_guess: Optional[str] = Field(default=None, max_length=120)
    readable: bool = False  # did the model actually read the marking?
    note: Optional[str] = Field(default=None, max_length=300)

    @field_validator("category", mode="before")
    @classmethod
    def _coerce_category(cls, v):
        try:
            return Category(v)
        except ValueError:
            return Category.other


# JSON Schema passed to Ollama's `format` field to constrain output.
RAW_DETECTIONS_SCHEMA: dict = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "label": {"type": "string", "maxLength": 80},
            "category": {"type": "string", "enum": [c.value for c in Category]},
            "bbox_2d": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
            "marking_text": {"type": ["string", "null"], "maxLength": 60},
            "identity_guess": {"type": ["string", "null"], "maxLength": 80},
            "readable": {"type": "boolean"},
            "note": {"type": ["string", "null"], "maxLength": 160},
        },
        "required": ["label", "category", "bbox_2d", "readable"],
    },
}
