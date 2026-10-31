# Third-party attribution

Everything in this repository outside the list below was written by Team Rocket during the hackathon.
The code was built with the help of an AI assistant (Claude), which the team directed and reviewed.

## Models and runtimes (not included in the repository, downloaded by the user)
| Name | Use | Licence |
|---|---|---|
| Qwen3-VL 4B Instruct (Alibaba Qwen team) | Vision-language model that boxes parts and reads print | Apache-2.0 |
| `huihui_ai/qwen3-vl-abliterated:4b-instruct` (huihui-ai) | Variant of the same model with refusals removed, compared against the unmodified base | Same as the base model |
| Ollama | Local model server | MIT |

## Python libraries (`backend/requirements.txt`)
FastAPI (MIT), Uvicorn (BSD-3-Clause), Pydantic (MIT), Pillow (HPND), NumPy (BSD-3-Clause),
opencv-python-headless (Apache-2.0, bundles FFmpeg under LGPL), python-multipart (Apache-2.0),
httpx (BSD-3-Clause), pytest (MIT).

## Frontend (`frontend/package.json`)
React and React DOM (MIT), Vite and `@vitejs/plugin-react` (MIT),
Martian Mono and Schibsted Grotesk through Fontsource (SIL Open Font License 1.1).

## Photos
`samples/ref_labelled.jpg`, `samples/test_a_closeup.jpg` and `samples/test_b_control.webp` are photos of real boards supplied by the team.
`backend/tests/fixtures/ai_board/board_01.png` is an AI-generated image used only as a test fixture.
