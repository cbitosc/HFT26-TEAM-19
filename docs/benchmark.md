# Benchmark log

Each entry says which machine, photo, settings and code version it came from. Numbers from different
entries are not comparable unless those match. The photo is `samples/board_01.png`, which looks AI-generated
(see `samples/README.md`), so these results say little about real boards.


> **Photo used in entries 1 and 2.** Both were measured on the AI-generated photo (`board_01.png`, with a Gemini mark),
> which now lives only in `backend/tests/fixtures/ai_board/` so the recorded replies in the tests still work. The numbers
> are not comparable with runs on the real boards in `samples/`. From entry 3 on, tune on `samples/ref_labelled.jpg` and
> look at the held-out boards once (`scripts/eval_boards.py`).

## 1. First real run, 31 Oct 2026

Machine: RTX 4060 laptop GPU, 8 GB. Ollama, Qwen3-VL 4B Instruct, context 8192.
Settings: temperature **0.1**, no top_p / top_k / presence penalty, max 1024 output tokens, no tiles, no close-up pass.
Truth: `samples/board_01.truth.json` (12 scored parts, approximate boxes).

| | Abliterated (`huihui_ai/qwen3-vl-abliterated:4b-instruct`) | Base (`qwen3-vl:4b-instruct`) |
| --- | --- | --- |
| Detections | 15 | 16 |
| Truth parts found (box IoU >= 0.3) | 6 / 12 | 7 / 12 |
| ...with the right category | 5 / 12 | 3 / 12 |
| Boxes touching nothing | 8 | 7 |
| Model latency | 15.1 s (model already loaded) | 20.6 s (+4.8 s load) |
| Peak GPU memory (whole GPU) | 5415 MiB | 5397 MiB |
| Coordinate convention | 0-1000 normalised, confirmed by eye | same |
| Reply cut off at token limit | **yes** | **yes** |

What the raw replies showed (`backend/tests/fixtures/board_01.*.raw.txt`):

- Both replies stopped mid-object at the 1024-token cap, and both ended in a repetition loop. The abliterated model
  wrote 8 identical "capacitor" strips stepping down one column; the base model wrote 10 "connector" blocks tiling
  the left of the board. The parser kept these as detections, which is where nearly all the false positives came from.
- The abliterated model's real boxes (main chip, two USB-C sockets, each header strip as one wide box, both DC jacks) fit closely. The base
  model's boxes were looser and several were wrong blocks.
- Neither model returned any marking. Every item said it could not read the text, which is the correct answer for this photo.
- Neither found any resistor, small capacitor or small regulator. At the 1280 px analysis size those parts are about 10 px wide.
- Two of the 12 scored parts are barcode stickers, which the prompt does not ask for, so 10 / 12 is the ceiling with the current prompt.

Latency here is mostly time spent writing the loop up to the cap. It is not a typical figure; measure again.

Changes made because of this run: recommended Qwen sampling (temperature 0.7, top_p 0.8, top_k 20), presence penalty 0.5 (changed to 1.5 after entry 2),
2048-token cap, truncation reported as a warning, repetition loops dropped and listed in `dropped`, optional tiled pass for
small parts. None of these has been measured on the laptop yet. The next entry should be `scripts/sweep_smoke.py`.

## Entry 2: first sweep (`scripts/sweep_smoke.py`, same photo, RTX 4060 laptop)

Photo `samples/board_01.png`, scored against `samples/board_01.truth.json` (12 scored parts, hand-drawn, approximate).
Sampling temperature 0.7, top_p 0.8, top_k 20, seed 3407, 2048-token cap. One photo and one seed per row, so differences of one part are noise.

| Run | Model | Tiles | Presence penalty | Found / 12 | Box + category | Cut off | Time |
|---|---|---|---|---|---|---|---|
| A | abliterated | off | 0.5 | 6 | 0.417 | yes | 38.8 s (5.5 s load) |
| B | abliterated | off | 0 | 7 | 0.417 | yes | 30.5 s |
| C | abliterated | off | 1.5 | 8 | 0.500 | no | 17.3 s |
| D | abliterated | 3x2 | 0.5 | 9 | 0.667 | yes (3 of 6 tiles) | 180.7 s |
| E | base | off | 0.5 | 5 | 0.083 | yes | 35.3 s |

- Presence penalty 1.5 (the value in the model guide) was best: the only run that finished before the token cap, the fastest, and the best score without tiles. My guess of 0.5 was wrong. 0 and 0.5 still looped.
- Run B looped in a way the first guard could not see: the same two boxes (a tall one and a short one) alternating 12 times. Added `drop_repeated_boxes`; on the stored reply it takes 32 items to 10 and keeps all 7 matches.
- Tiles raised found parts from 6 to 9 but took 180 s, produced 91 observations, and three of six tiles were still cut off. The extra items include many real small resistors and capacitors the truth file does not score, but also a box on a mounting hole, boxes on the table at the lower right, a red cable boxed as "wire", and a thin vertical stack of resistor boxes that survived the guard. The sweep cannot say how many of the 55 resistors are right.
- Base model (E): worst recall, boxes often wrong, and it reported text from the silkscreen and handwriting as chip markings ("REV 2.10", "S1", "C1", "TEST 1 VCC") on 5 parts. They stay tentative and unverified in the app, but it is the wrong behaviour. The abliterated model made no marking claims in any run.
- Still missed in every run: both barcode stickers (not in the prompt). The `board` box in C is the whole board outline, counted as a false positive by the scorer.

Changes: presence penalty default 1.5, repeated-box guard. Next round: `sweep_smoke.py` now runs C again, 1.0, and 3x2 and 2x2 tiles at 1.5.


## Entry 3: first real-board evaluation (`scripts/eval_boards.py`, RTX 4060 laptop)

Three real photos, one run each, penalty 1.5, no tiles, close-up pass on. Truth boxes are hand-drawn.

| Board | Role | Found | Box + category | False positives | Markings | Cut off | Time |
|---|---|---|---|---|---|---|---|
| ref_labelled | reference | 1 / 11 | 0.091 | 0 | 1 of 4 correct, 3 chips not found | **yes** | 35.9 s |
| test_a_closeup | held out | 3 / 4 | 0.750 | 5 | no legible print | no | 28.2 s |
| test_b_control | held out | 4 / 22 | 0.091 | 5 | 2 of 2 correct | no | 21.2 s |

- ref_labelled failed: the reply was one chip with a good marking and a second chip whose `marking_text` degenerated into a repeated
  digit string until the token cap, so everything after it was lost (`backend/tests/fixtures/ref_labelled.runaway.raw.txt`). Changes made, not yet re-measured on the laptop:
  `maxLength` on text fields in the schema, a sanitizer that discards a looping marking and keeps the box, and one retry that asks for boxes only (markings are read in the close-up pass).
- test_a_closeup: the model boxes the large chips and about four resistors but not the dozens of repeated small parts.
  The 5 "false positives" are mostly real parts the truth file does not list; the truth file only counts 4 chips.
- Both held-out photos are 500 px wide. Changes made, not yet re-measured: photos under 1024 px on the long side are enlarged before the model sees them, and tiles under 768 px are enlarged up to 4x.
- Look-alike search (`app/repeats.py`, OpenCV template matching, no model): on test_a_closeup, seeded from the model's own resistor boxes it adds only 1 box at 0.80 and 2 at 0.75 (9 at 0.70, mostly junk), because those boxes are loose.
  Seeded from one tightly drawn resistor it found 13 correct hits at 0.80 and all 10 top-row resistors at 0.70 (with about 8 junk boxes, including the banner frame). So the search is offered as a person-driven button
  ("Find more like this"), and the automatic pass is off by default (`VG_REPEATS=1` to try it). One photo, one exemplar: not a general result.

## Entry 4: after the v7 fixes (`scripts/eval_boards.py`, RTX 4060 laptop)

One run each, penalty 1.5, close-up pass on. Same truth files as entry 3.

| Board | Run | Found | Box + category | False positives | Markings | Cut off | Time |
|---|---|---|---|---|---|---|---|
| ref_labelled | no tiles | 6 / 11 (was 1 / 11) | 0.545 | 2 | **4 of 4 correct, 0 wrong** (was 1 of 4) | yes | 43.2 s |
| test_a_closeup | no tiles | 3 / 4 | 0.750 | 1 (was 5) | no legible print | no | 37.1 s |
| test_a_closeup | 2x2 tiles | 4 / 4 | 0.750 | 24 | no legible print | no | 121.1 s |

- The runaway-text fix worked on the reference board: all four chip markings were read correctly with no wrong or invented text. The reply was still cut off at the token cap, and two small "resistor" boxes sit inside the Hynix chip.
- 2x2 tiles on test_a_closeup raised the box count from 6 to 49 (4 tiles all returned, 28 boxes added, 20 cut at tile edges, 5 duplicates). The overlay shows many real passives now boxed (the row of four tan capacitors, a column of capacitors, resistors beside the large chip), but the model still gives the two rows of five small black resistors at the top only as a few tall column boxes, not one box each. The truth file counts only the 4 chips, so "24 false positives" are mostly real unlisted passives plus junk. A count by eye on `boxes.jpg` is the only way to judge parts.
- Defects seen in the tiled run, now guarded in code and tested on this output: one capacitor box on the white banner (blank-area guard) and four chips boxed under both `ic_package` and `microcontroller_module` (same-chip merge). Some tan capacitors are labelled `resistor`: a category error the pipeline cannot detect.
- Look-alike search on the tiled output (guards applied, 44 boxes) adds 0 at 0.80 and 0.75 and 3 at 0.70, because the tiles already boxed most look-alikes. It is still the way to label the rows the model skipped, when a person draws one tight example.
