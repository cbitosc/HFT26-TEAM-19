# Coordinate contract

Every box that leaves the backend is in **original pixels after EXIF rotation** (`bbox_space = "original_px"`).

| Space | Defined by | To original |
| --- | --- | --- |
| Original | uploaded image after EXIF rotation, W x H | identity |
| Analysis image | whole image resized with one scale `s` | `p / s` |
| Crop | top-left `(ox, oy)` in original px, `c` crop px per original px | `p / c + (ox, oy)` |
| Model output | Qwen3-VL `bbox_2d`, 0-1000 normalised to the image the model was given | `p / 1000 * view size`, then the row above |
| Display (browser) | fit scale, user zoom, pan | `(p - pan) / (fit * zoom)` |

In code: `app/geometry.py` (`ImageView` describes any image given to the model; `model_box_to_original`
does the whole chain). Tests: `tests/test_geometry.py`, `tests/test_intake.py`.

**Unverified:** that Ollama returns 0-1000 normalised boxes for Qwen3-VL. Third-party integrations report
it; confirm with `scripts/smoke_vlm.py` on the target model. A value above 1000 triggers a logged
`view_pixels_fallback`.
