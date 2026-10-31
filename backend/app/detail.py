"""Second pass: re-read the marking on each chip from a high-resolution crop.

Why: at the 1280 px overview size a chip's printed text is a few pixels tall. A crop of the original
photo, scaled once to 768 px, gives the model something it can actually read.

Rules (these are code, not a request to the model):

* The overview box is kept. The crop's own box is ignored, so this pass cannot move a box or create a part.
* A marking read here is ``tentative`` and labelled as unverified. Only a reference match or the person confirms.
* If the crop says the text is not readable, a marking from the overview is dropped. The sharper view wins,
  and a model that cannot read the crop should not be believed on the blurrier one.
* A failed or unparsable crop read never fails the analysis. The part keeps what the overview gave it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from pydantic import ValidationError

from . import prompts
from .adapters.base import AdapterError, InferenceAdapter, InferenceRequest
from .geometry import pad_box
from .intake import PreparedImage, encode_jpeg, make_crop
from .parsing import ModelOutputError, _loads_lenient
from .schemas import RAW_DETECTIONS_SCHEMA, Candidate, Category, IdStatus, Observation, RawDetection

DETAIL_CATEGORIES = {Category.ic_package, Category.microcontroller_module}
MIN_SIDE_PX = 24  # original pixels; a smaller box has nothing to read
MAX_PARTS = 6  # keeps the pass to roughly a minute on a laptop GPU
PAD_FRACTION = 0.15
CROP_LONG_SIDE = 768
_OVERVIEW_READ = "Marking read by the model"
_UNREADABLE = "Marking not readable in this view"
CLOSE_UP_READ = "Marking read from a close-up by the model (unverified)"
CLOSE_UP_UNREADABLE = "Marking not readable even in a close-up. Retake with light from the side and no glare."
CLOSE_UP_CONTRADICTS = "A close-up could not read the text the first pass reported, so that text was dropped"


@dataclass
class DetailRead:
    readable: bool
    marking: str | None
    identity_guess: str | None
    note: str | None
    latency_s: float


def select_for_detail(observations: list[Observation]) -> list[Observation]:
    """Chips big enough to read, largest first, capped."""
    chosen = []
    for o in observations:
        if o.category not in DETAIL_CATEGORIES or o.source.value != "vlm":
            continue
        w, h = o.bbox[2] - o.bbox[0], o.bbox[3] - o.bbox[1]
        if min(w, h) >= MIN_SIDE_PX:
            chosen.append((w * h, o))
    chosen.sort(key=lambda t: -t[0])
    return [o for _, o in chosen[:MAX_PARTS]]


def read_detail(prepared: PreparedImage, adapter: InferenceAdapter, obs: Observation, *, max_tokens: int = 512) -> DetailRead:
    ow, oh = prepared.size
    box = pad_box(obs.bbox, PAD_FRACTION, ow, oh)
    crop, _view = make_crop(prepared, box, CROP_LONG_SIDE)
    jpeg = encode_jpeg(crop, quality=92)
    prompt = prompts.DETAIL
    latency = 0.0
    last_error = "The reply was not valid JSON."
    for attempt in (1, 2):  # one repair retry, then give up on this part
        res = adapter.analyze(
            InferenceRequest(prompt=prompt, images=[jpeg], system=prompts.SYSTEM, json_schema=RAW_DETECTIONS_SCHEMA, max_tokens=max_tokens,
                temperature=0.2, presence_penalty=0.0)  # reading characters: no penalty on repeated letters
        )
        latency += res.latency_s
        try:
            data = _loads_lenient(res.text)
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list) or not data:
                raise ModelOutputError("Expected one item in a JSON array.")
            raw = RawDetection.model_validate(data[0])
        except (ModelOutputError, ValidationError, json.JSONDecodeError) as exc:
            last_error = getattr(exc, "detail", None) or "The item had invalid fields."
            prompt = prompts.DETAIL + f"\n\nYour previous reply could not be used: {last_error} Reply with ONLY a JSON array with one item."
            continue
        marking = " ".join((raw.marking_text or "").split()) or None
        if not raw.readable:
            marking = None  # evidence rule: text the model says it could not read is not a marking
        guess = " ".join((raw.identity_guess or "").split()) or None
        return DetailRead(raw.readable and marking is not None, marking, guess if marking else None, (raw.note or "").strip() or None, latency)
    raise ModelOutputError(last_error)


def merge_detail(obs: Observation, read: DetailRead) -> Observation:
    """Apply a close-up read to an observation. Never changes the box, category or source."""
    data = obs.model_copy(deep=True)
    evidence = [e for e in data.evidence if not e.startswith((_OVERVIEW_READ, CLOSE_UP_READ))] if read.readable else list(data.evidence)
    limitations = list(data.limitations)
    if read.readable and read.marking:
        previous = data.marking_text
        if previous and previous != read.marking:
            limitations.append(f"The first pass read {previous!r}; the close-up read {read.marking!r}")
        limitations = [m for m in limitations if m != _UNREADABLE]
        evidence.append(f"{CLOSE_UP_READ}: {read.marking}")
        data.marking_text = read.marking
        data.candidates = [Candidate(identity=read.identity_guess)] if read.identity_guess else []
        data.status = IdStatus.tentative
    else:
        if data.marking_text:
            limitations.append(CLOSE_UP_CONTRADICTS)
            evidence = [e for e in evidence if not e.startswith(_OVERVIEW_READ)]
            data.marking_text = None
            data.candidates = []
            data.status = IdStatus.unknown
        if CLOSE_UP_UNREADABLE not in limitations:
            limitations.append(CLOSE_UP_UNREADABLE)
    if read.note:
        limitations.append(read.note)
    data.evidence, data.limitations = evidence, _dedupe(limitations)
    return Observation.model_validate(data.model_dump())


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def run_detail_pass(prepared, adapter, observations, *, should_stop=lambda: False, max_tokens: int = 512) -> tuple[list[Observation], dict]:
    """Returns (observations with close-up reads merged, summary). Order and ids are preserved."""
    started = time.perf_counter()
    summary = {"attempted": 0, "read": 0, "unreadable": 0, "failed": 0, "stopped": False, "latency_s": 0.0}
    by_id = {o.id: o for o in observations}
    for o in select_for_detail(observations):
        if should_stop():
            summary["stopped"] = True
            break
        summary["attempted"] += 1
        try:
            read = read_detail(prepared, adapter, o, max_tokens=max_tokens)
        except (ModelOutputError, AdapterError) as exc:
            summary["failed"] += 1
            by_id[o.id] = by_id[o.id].model_copy(
                update={"limitations": _dedupe([*o.limitations, "The close-up read failed, so only the first pass is shown"])}
            )
            if isinstance(exc, AdapterError):  # the model server is gone or out of memory: do not hammer it
                summary["stopped"] = True
                break
            continue
        summary["latency_s"] += read.latency_s
        summary["read" if read.readable else "unreadable"] += 1
        by_id[o.id] = merge_detail(by_id[o.id], read)
    summary["latency_s"] = round(summary["latency_s"], 3)
    summary["wall_s"] = round(time.perf_counter() - started, 3)
    return [by_id[o.id] for o in observations], summary
