# VisionGuard: AI and AR-powered hardware inspection and diagnostics

**Team Rocket, TEAM-19** (registration HFEST26-7JNX4ZNV), Vasavi College of Engineering. CBIT Hacktoberfest '26.
Team leader: Prateek Gongle. Members: Ramya Nakerkanti, Sara Smrithi Reddy, Yathirajula Gunvanth Sri Sai, Advith Chennamaneni.
Problem: AI & AR-Powered Hardware Inspection and Diagnostics (Computer Vision, Edge AI & Hardware Security).

VisionGuard runs locally and offline. A vision model (Qwen3-VL 4B through Ollama) boxes the parts on a board photo and reads chip print. Rules in code decide what may be called confirmed.

## Submission checklist
- Solution overview, architecture and results: this README, [`docs/`](docs/) and [`docs/benchmark.md`](docs/benchmark.md)
- Interactive demo page (open `docs/index.html` in a browser; no server needed). Live link: add the GitHub Pages address here after enabling Pages.
- Local setup: see "Run" below. Attribution of open-source libraries and models: [`docs/ATTRIBUTION.md`](docs/ATTRIBUTION.md). Licence: MIT ([`LICENSE`](LICENSE)).
- Folder map (the brief suggests `src/`, `docs/`, `tests/`): `backend/` and `frontend/` are the source, `backend/tests/` holds the 137 tests, `scripts/` the evaluation tools, `samples/` the real-board photos with hand-drawn ground truth, `results/` the saved laptop runs.

## What it does against the brief
| Requirement | Status |
|---|---|
| Accept uploaded or live photos in a browser | Upload and quality check built. Live phone camera over USB designed, not tested. |
| Detect and label components with open-source vision | Built. No training dataset. All four chip markings on the labelled board read correctly. |
| Interactive overlays for pinouts, connections, miswirings | Boxes with evidence built. Pin diagrams and miswiring checks not built (they need a verified reference library). |
| Health summary and step-by-step guidance | Summary and rule-based steps built. Visual damage pass not built. |

- Measured results from the laptop runs: [`results/`](results/) and [`docs/benchmark.md`](docs/benchmark.md)
- Backend (FastAPI, OpenCV, SQLite), frontend (React, Vite) and scripts are below. 137 automated tests pass without a GPU.

# VisionGuard Local — core, API and UI

Local-first visual hardware inspection. This package is the **Phase 0** foundation from the implementation
plan: coordinates, image intake, validated observations, model-output parsing, inference adapters and a real
smoke test. It is meant to be copied into the existing VisionGuard repo (`backend/app/...`, `scripts/`,
`docs/`); the existing knowledge base and rule engine are untouched.

## What is verified, and where

| Item | Status |
| --- | --- |
| Geometry, intake (EXIF, limits, quality), schemas, parser, repair/fail pipeline | 34 unit tests pass in the build workspace (Python 3.13). **Synthetic images only.** |
| `smoke_vlm.py --mock` plumbing | Ran end to end; output is labelled MOCK |
| API (`backend/app/main.py`): upload, analysis jobs, corrections, board variant, static UI | 30 API tests pass with the MOCK adapter. Close-up pass and scoring add 22 more (86 in total). One real-browser run of upload, analysis, correction and steps against the running server, MOCK adapter only. |
| Ollama adapter | **Written, not run** — no GPU or Ollama in the build workspace |
| 0-1000 box convention via Ollama | **Confirmed** on the laptop (first run, `docs/benchmark.md`) |
| Abliterated vs base model | **First run done** (abliterated boxes much tighter; both looped). Re-run after the fixes is pending. |
| GPU | **RTX 4060 laptop, 8 GB**, not the RTX 5050 assumed earlier. Peak use 5.4 GB. See `docs/hardware.md` |
| Sampling, loop guard, tiled pass | Unit-tested, including on the two real raw replies. **Not yet run on the laptop.** |

## Run

```powershell
cd backend
python -m venv .venv ; .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                      # 64 tests, no GPU needed
cd ..\frontend ; npm install ; npm run build ; cd ..\backend
$env:VG_ADAPTER = "mock"                 # labelled MOCK results, to try the app without a model
python -m app                            # http://127.0.0.1:8000 (UI + API)
```

With Ollama running and the model pulled, leave `VG_ADAPTER` unset (default `ollama`). Check
`http://127.0.0.1:8000/api/health` first: it says whether the model server is reachable and the model installed.
Settings are environment variables, listed in `.env.example`. Photos and the SQLite database go in `data/` (kept out of git).

Real-model smoke test (needs the laptop):

```powershell
python scripts\smoke_vlm.py .\photos\board.jpg --model huihui_ai/qwen3-vl-abliterated:4b-instruct
```

The server listens on this computer only. It refuses another address unless `VG_ALLOW_NON_LOOPBACK=1`, because there is no login.

## Layout

```
backend/app/geometry.py    coordinate spaces and transforms
backend/app/intake.py      decode, EXIF, limits, quality, analysis copy, crops
backend/app/schemas.py     Observation + raw model schema (evidence rules enforced here)
backend/app/parsing.py     model text -> validated observations in original px
backend/app/pipeline.py    overview pass with bounded repair retries, visible failure
backend/app/main.py        FastAPI routes (docs/api-contract.md); app/__main__.py starts it
backend/app/store.py       SQLite: images, analyses, observations
backend/app/jobs.py        one background worker; cancel; failed jobs show a message
backend/app/corrections.py what a person's correction may and may not change
backend/app/detail.py      close-up pass: re-reads chip markings from a 768 px crop (marking only, never boxes)
backend/app/evaluation.py  scores detections against samples/*.truth.json
samples/                   test photo and its hand-made ground truth (see samples/README.md)
backend/app/guidance.py    steps by rule; findings are not generated yet (see below)
frontend/                  React UI (frontend/README.md)
backend/app/adapters/      ollama (default) | mock (labelled) ; featherless stays off
backend/app/prompts.py     observation-only prompts (no pin facts, no verdicts)
scripts/smoke_vlm.py       real image-inference smoke test + metrics
docs/                      hardware checklist, coordinate contract
```

## Evidence rules enforced in code

- A model-sourced observation cannot be `confirmed` without a matched reference (only a reference match or the user can).
- A marking the model says it could not read is discarded; the part stays "unknown" with no candidates.
- Candidate `reference_id` is never set by the model.
- Malformed items are dropped and reported; an unusable reply fails visibly after 2 repair retries. No invented detections.
- Model scores are always labelled `uncalibrated`.
- A person's correction can make a part `confirmed` only with "I checked this against the physical part", and only if there is a marking or a name to confirm. Changing the text drops any matched reference.
- Only the person can change `category`, `marking_text`, `identity`, `confirmed` and `bbox`. A correction cannot set `status`, `source`, `reference_ids` or a score.
- Steps contain no measurements, pin names or voltages. Findings are not generated: the API says `concerns_checked: false` and the UI says concerns were not checked, rather than showing an empty list that could be read as "nothing wrong".

## Testing on real boards (reference and held-out)

`samples/` holds three real boards. `ref_labelled.jpg` is the **reference**: its chips carry readable print (MT1379GE, MT1336E,
M12L64164A, HY29LV800BT), so it is where marking reading can be checked and where settings are tuned.
`test_a_closeup.jpg` and `test_b_control.webp` are **held out**: the settings are not tuned on them, so they show whether
something that works on the reference carries over to a different board. This is evaluation, not training. The model's
weights do not change. One command measures all three:

```powershell
python scripts\eval_boards.py
```

It runs the overview and the close-up pass (where chip text is read) on each board and prints one table plus, for each
readable chip, what the model said against what is printed: `correct`, `near` (one character off), `wrong` (text that is
not what is printed, the case to watch), `not_read`, or `chip not found`. Open each `eval_out\<board>\boxes.jpg` as well. Then:

```powershell
Compress-Archive -Path eval_out -DestinationPath eval_results.zip -Force
```

Options: `--tiles 3x2`, `--repeats` (also search for look-alikes of the small parts the model boxed; they are drawn in blue), `--presence-penalty 1.0`, `--no-detail` (faster, no markings), `--only ref_labelled`.
The two held-out photos are only 500 px wide and their truth boxes are approximate, so a difference of one part is noise.

## Labelling every repeated part

A small model lists a few of the resistors in a row and stops. Two things help, and neither is magic:

- **Tiles** (`VG_TILES=2x2` or `3x3`, or `--tiles` in the evaluation) show the model smaller sections at higher magnification. It costs one model call per tile.
- **Find more like this**: select a part, press the button, and VisionGuard searches the photo for look-alikes by appearance (OpenCV, no model call).
  Matches are labelled "found by appearance", have no marking, stay unknown, and are never confirmed unless you confirm them. Draw the box tightly around the part first; a loose box finds junk.

## Comparing settings on the laptop

`sweep_smoke.py` runs four configurations on the reference photo (boxes only, no close-ups) and prints a table:

```powershell
python scripts\sweep_smoke.py samples\ref_labelled.jpg --truth samples\ref_labelled.truth.json
```

It compares presence penalties 1.0 and 1.5 and two tiled passes (3x2 and 2x2) for small parts. The first-round runs (0, 0.5, base model) can be repeated with `--only`.
Open each `sweep_ref\<run>\boxes.jpg` as well as reading the table. A run that finds more parts but scatters boxes is not better.
Enable tiles in the app with `VG_TILES=3x2` (see `.env.example`).

## Comparing models on the laptop

```powershell
python scripts\smoke_vlm.py samples\ref_labelled.jpg --detail --model huihui_ai/qwen3-vl-abliterated:4b-instruct --out smoke_abliterated
python scripts\smoke_vlm.py samples\ref_labelled.jpg --detail --model qwen3-vl:4b-instruct --out smoke_base
python scripts\eval_detections.py samples\ref_labelled.truth.json smoke_abliterated\observations.json smoke_base\observations.json
```

The score is a rough comparison on one photo with an approximate hand-made truth, not a measured accuracy. Open each
`boxes.jpg` as well. The script flags any marking the model reports on a part the annotator could not read.

## Not built yet

Reference library and matching, visual-concern pass, pin diagrams, guidance and session/report endpoints from the plan, resume after page reload, cloud adapter (stays off).
