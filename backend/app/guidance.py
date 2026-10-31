"""Findings and steps built by rules from the observations. No model is involved here.

Phase 1 limits, stated plainly:

* **Findings.** No visual-concern pass exists yet, so ``concerns_checked`` is False and the list is
  empty. The UI must not read an empty list as "nothing wrong". It says concerns were not checked.
* **Steps.** Only inspection steps that need no reference data: unpower, identify the board, take
  close-ups, compare printed text. There are no measurement steps and no pin or voltage statements
  until a reference library can back them.
"""

from __future__ import annotations

from .schemas import Category, IdStatus, Observation

# Keep in step with BOARD_VARIANTS in frontend/src/lib/labels.js.
BOARD_VARIANTS = (
    "Raspberry Pi 40-pin header board",
    "Arduino Uno R3",
    "ESP32 DevKit V1 (30-pin)",
    "Other or unsupported board",
)
CHIP_CATEGORIES = {Category.ic_package, Category.microcontroller_module}
MAX_STEPS = 20


def build_findings(observations: list[Observation]) -> tuple[list[dict], bool]:
    return [], False


def build_steps(observations: list[Observation], board_variant: str | None) -> list[dict]:
    steps: list[dict] = []

    def add(text: str, expect: str, ids: list[str] | None = None) -> None:
        steps.append(
            {
                "id": f"s_{len(steps) + 1}",
                "text": text,
                "expect": expect,
                "requires_measurement": False,
                "unit": None,
                "observation_ids": ids or [],
            }
        )

    add("Disconnect power and unplug everything from the board before you handle it.", "Nothing plugged in and no LED lit.")

    if board_variant and not board_variant.lower().startswith("other"):
        add(
            f"Check that the name printed on the board matches {board_variant}.",
            "The printed name or model matches. If it does not, change the board variant in Findings.",
        )
    else:
        add(
            "Find the name or model printed on the board and set the board variant in Findings.",
            "A name near an edge or under the chips. Pin names stay hidden until you confirm it.",
        )

    for o in observations:
        if o.category in CHIP_CATEGORIES and o.status == IdStatus.unknown:
            add("Take a close-up photo of this chip with light from the side, then analyze that photo.", "The printed text is sharp and free of glare.", [o.id])
    for o in observations:
        if o.status == IdStatus.tentative and o.marking_text:
            add(
                "Read the printed text on this part with a magnifier or the camera zoomed in. Correct the part if it differs.",
                f"The part reads {o.marking_text}.",
                [o.id],
            )
    return steps[:MAX_STEPS]
