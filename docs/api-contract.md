# API contract the frontend expects

The frontend (`frontend/src/lib/api.js`) calls these endpoints under `/api`. In dev, Vite proxies `/api` to
`http://127.0.0.1:8000`. In production the FastAPI app serves `frontend/dist` and `/api` from one origin on loopback.

**Status.** Implemented in `backend/app/main.py` and tested with the MOCK adapter (`backend/tests/test_api.py`).
Not yet run against a real model. `PATCH /api/images/{id}` is new: it is not in the original endpoint table of the plan.
Not built: `POST /api/guidance`, `/api/sessions/*`, `/report.json`, `GET /api/references/{id}`.

Error body for every non-2xx response: `{ "code": "<machine_code>", "message": "<sentence a user can act on>" }`.
The server only accepts requests whose Host header is `127.0.0.1`, `localhost` or `[::1]` (400 otherwise).

## Coordinates (the one rule that matters)

Every `bbox` is `[x1, y1, x2, y2]` in pixels of the **original image after EXIF rotation**, with `bbox_space: "original_px"`.
`width` and `height` returned by `POST /api/images` are the post-rotation dimensions. The browser draws the overlay in an
SVG whose `viewBox` is `0 0 width height`, so zoom and pan never change a coordinate. If the browser's decoded image size
differs from `width`/`height`, the UI refuses to draw boxes and says so. See `docs/coordinates.md`.

## `GET /api/health`

```json
{
  "ok": true, "adapter": "ollama", "model": "huihui_ai/qwen3-vl-abliterated:4b-instruct", "is_mock": false,
  "model_reachable": true, "model_installed": true
}
```

`ok` is true only when the model server answers and the model is installed. Otherwise `message` says what to do.

## `POST /api/images`

`multipart/form-data`, field `image` (JPEG, PNG or WebP).

```json
{
  "image_id": "img_ab12",
  "width": 4032,
  "height": 3024,
  "quality": { "ok": false, "problems": ["The photo is blurry. Hold the camera steady and refocus."] }
}
```

`quality.ok === false` makes the UI offer "Choose another photo" or "Analyze anyway". It never blocks.
The format is decided by decoding the content, never by file name. Errors: `413 too_large`, `415 unsupported_format`,
and `422` with `empty`, `not_an_image`, `too_many_pixels`, `too_small` or `decode_failed`. The original bytes are stored untouched in `data/images/`.

## `PATCH /api/images/{image_id}`

Body `{ "board_variant": "Arduino Uno R3" }`, a value from `BOARD_VARIANTS` in `backend/app/guidance.py` (kept in step with
`frontend/src/lib/labels.js`). An empty value clears it. `422 unknown_variant` for anything else, `422 unknown_field` for other keys.

```json
{ "board_variant": "Arduino Uno R3", "steps": [ /* rebuilt for the latest finished analysis, [] if none */ ] }
```

Pin names are only ever shown for a confirmed variant that has a reference.

## `POST /api/analyses`

Body `{ "image_id": "img_ab12" }`. Returns `202` with `{ "job_id": "job_01", "status": "queued" }`.
One job runs at a time. A second request while one is queued or running returns `409 busy`. Unknown `image_id` is `404 image_not_found`.

## `GET /api/analyses/{job_id}`

`status` is one of `queued`, `running`, `done`, `failed`, `cancelled`. The UI polls every 700 ms.

When `done`:

```json
{
  "status": "done",
  "model": "huihui_ai/qwen3-vl-abliterated:4b-instruct",
  "adapter": "ollama",
  "is_mock": false,
  "latency_s": 9.8,
  "attempts": 1,
  "dropped": [ "item 3 (chip): box lies outside the image" ],
  "warnings": [ "The model's reply was cut off at the length limit, so parts after the cut are missing." ],
  "tiles": null,
  "detail_pass": { "attempted": 2, "read": 1, "unreadable": 1, "failed": 0, "stopped": false, "latency_s": 11.4, "wall_s": 11.5 },
  "board_variant": "Arduino Uno R3",
  "observations": [ /* Observation, see backend/app/schemas.py. Ids are unique across analyses. */ ],
  "concerns_checked": false,
  "findings": [
    {
      "id": "f_1", "kind": "suspected",
      "title": "Darker area around the base of C2",
      "detail": "plain sentence describing what is visible",
      "verify_by": "what the person should do to check",
      "observation_ids": ["obs_005"]
    }
  ],
  "steps": [
    {
      "id": "s_1", "text": "Disconnect power.", "expect": "No LED lit.",
      "requires_measurement": false, "unit": null, "observation_ids": []
    }
  ]
}
```

`warnings` lists things the person should know about this run, such as a reply cut off at the token limit or a tile that was skipped.
`tiles` is `null` unless `VG_TILES` is set (for example `3x2`); then it reports `planned`, `ok`, `failed`, `added`, `duplicates`
and `cut_by_edge`. Items in `dropped` include any run of same-size boxes chained edge to edge that looked like a repetition loop.

`detail_pass` is `null` when `VG_DETAIL_PASS=0`. Otherwise each chip big enough to read (at most 6, largest first) is
re-read from a 768 px crop of the original photo. That pass can change `marking_text`, `candidates`, `status`
(`tentative` or `unknown` only), `evidence` and `limitations`. It never changes `bbox`, `category`, `source` or references.
A marking it reads is labelled "Marking read from a close-up by the model (unverified)". If the close-up cannot read
text the first pass reported, that text is dropped. A failed close-up never fails the analysis.

`concerns_checked` is `false` until a visual-concern pass exists, and `findings` is then `[]`. The UI says concerns were not
checked. It must not present an empty list as "nothing found".

When `failed`: `{ "status": "failed", "error": { "code": "...", "message": "..." } }`, with no observations. Codes:
`model_output_invalid` (after 2 repair retries), `model_unavailable`, `out_of_memory`, `interrupted` (server restarted
mid-job), `missing_image`, `internal`. The UI shows the message and no detections. It never substitutes a guess.

`is_mock: true` makes the UI show a persistent "Mock model" banner.

## `DELETE /api/analyses/{job_id}`

Cancels a queued or running job. Returns `204`. Cancelling a finished job is not an error and changes nothing.
A model call already in progress cannot be interrupted: its result is discarded when it returns.

## `PATCH /api/observations/{observation_id}`

Any subset of these fields. Anything else is `422 unknown_field`, so a client cannot set `status`, `source`,
`reference_ids` or a score.

```json
{
  "category": "ic_package",
  "marking_text": "ATMEGA328P",
  "identity": "ATmega328P",
  "confirmed": true,
  "bbox": [x1, y1, x2, y2]
}
```

- `marking_text` and `identity` replace the stored value. An empty string clears it. Limits: 200 and 120 characters.
- `confirmed: true` means the person ticked "I checked this against the physical part". It needs a marking or a name
  (`422 nothing_to_confirm`). Only then does the server set `status: "confirmed"` and `source: "user"`.
- Without `confirmed: true`, a marking or name gives `tentative`; with neither, `unknown`.
- Changing the marking or name drops matched references and clears `model_score`.
- `bbox` is in original pixels, is clamped to the photo and must be at least 4 px on each side (`422 invalid_box`).

Returns the full state of the analysis, because a correction can change steps:

```json
{ "observations": [ ... ], "findings": [ ... ], "concerns_checked": false, "steps": [ ... ] }
```

## `POST /api/observations/{observation_id}/similar`

Searches the whole photo for parts that look like this one (OpenCV template matching, no model call, about a second).
No body. The selected box is the example, so it works best when the box fits the part tightly.

Each match is appended to the analysis as `source: "assist"`, `status: "unknown"`, no marking and no candidates, with the category
copied from the example and evidence that says it was found by appearance and not read. Matches that overlap an existing part are skipped, so calling it again adds nothing new.
Only a person can confirm one, through `PATCH` with `confirmed: true`.

Returns the same state as `PATCH`, plus `added` (ids of the new rows) and `similar` (`exemplars`, `found`, `rejected_overlap`, `threshold`).
`404 observation_not_found` for an unknown id. The match threshold is `VG_SIMILAR_THRESHOLD` (default 0.75).

## What the UI never does

- It never shows a health percentage, a "good/bad board" verdict, or pin names for an unconfirmed variant.
- It shows `model_score` only with the words "uncalibrated estimate, not a probability".
- It renders `confirmed` only when the backend sends it. It does not upgrade a status itself.
- It does not read an empty `findings` list as "no concern" unless `concerns_checked` is true.
