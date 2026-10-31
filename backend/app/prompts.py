"""Prompts for the VLM. They ask for observations only, never pin facts or safety verdicts."""

SYSTEM = (
    "You are a careful electronics inspection assistant. You describe only what is visible in the "
    "photo. If text on a part is blurry, cut off or too small to read, set readable to false and leave "
    "marking_text null. Never guess part numbers and never state pinouts or voltages. "
    "Reply with JSON only."
)

OVERVIEW = (
    "Find the main visible components on this circuit board photo: ICs and chips, microcontroller "
    "modules, pin headers, connectors, USB ports, capacitors, resistors, LEDs, buttons and wires. "
    "Return a JSON array. Each item: "
    '{"label": short description, "category": one of ic_package, microcontroller_module, gpio_header, '
    "connector, usb_port, capacitor, resistor, led, button, wire, board, other, "
    '"bbox_2d": [x1, y1, x2, y2] as integers normalised 0-1000 relative to this image, '
    '"marking_text": text printed on the part or null, "identity_guess": your best guess of the part or null, '
    '"readable": true only if you could actually read the marking, "note": short caveat or null}. '
    "At most 25 items. Do not include a box that covers the whole image."
)

NO_TEXT = (
    " Do not read printed text in this pass: set marking_text to null and readable to false for every item. "
    "Printed text is read separately from close-ups."
)

DETAIL = (
    "This is a close-up crop of one part on a circuit board. Read any printed text exactly as it appears. "
    "Return a JSON array with ONE item for the main part in the crop: "
    '{"label": ..., "category": ..., "bbox_2d": [0, 0, 1000, 1000] unless the part is smaller than the crop, '
    '"marking_text": exact characters or null, "identity_guess": or null, "readable": true/false, "note": ...}. '
    "If you cannot read the marking with confidence, set readable to false and marking_text to null."
)

TILE = (
    OVERVIEW
    + " This image is one zoomed section of a larger circuit board photo. Include small parts too: "
    "resistors, small capacitors, small chips, LEDs and buttons. Skip any part that is cut off by the edge "
    "of this image. Never repeat the same part twice."
)
