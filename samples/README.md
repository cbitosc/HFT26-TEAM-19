# Sample photos

Three real boards. Truth files (`*.truth.json`) list the parts with boxes in original pixels and, where the print is
legible, the marking. They were drawn by eye by Claude on an enlarged copy and checked on an overlay, so they are
approximate (a few percent; more on the small photos). Parts marked `ambiguous` may be matched but are never counted as
missed (empty footprints, clusters of tiny passives, stickers the prompt does not ask for, unpopulated pad rows).
Review the boxes before you trust any score.

| File | Size | Role | What it is |
|---|---|---|---|
| `ref_labelled.jpg` | 2576 x 1932 | reference | Underside of a DVD-drive style board (2003 revision), sharp and evenly lit. Four chips have readable print: MT1379GE, MT1336E, M12L64164A (ESMT), HY29LV800BT (Hynix). Two chips (U3, U4) are not legible. Tune settings here. |
| `test_a_closeup.jpg` | 500 x 500 | held out | Close-up of a dense hard-drive style board, inside a white and blue banner (the board is roughly x 45-455, y 97-403). Two QFP chips, a SOIC-8, tantalum capacitors, resistor arrays. Chip print is not legible. |
| `test_b_control.webp` | 500 x 333 | held out | Through-hole control board: two relays (Schneider), terminal blocks, DC jack, DIP-8 ICs, TO-220 parts, electrolytics, axial resistors. Only the relay brand is legible. |

The held-out photos are low resolution. At 500 px a resistor is a few pixels wide, so expect small parts to be missed
there whatever the model does.

`scripts/eval_boards.py` runs all three and keeps the roles apart: tune on the reference, look at the held-out boards once.
This is evaluation. It does not train or change the model.

The earlier AI-generated photo (it carries a Gemini mark) is kept only as a test fixture in
`backend/tests/fixtures/ai_board/`, because the recorded model replies in the tests were made on it. Do not use it to
claim the system works on real hardware.

To add your own board: put the photo here, write a `.truth.json` with the same shape (`image`, `width`, `height`,
`role`, `parts`), and check the boxes on an overlay.
