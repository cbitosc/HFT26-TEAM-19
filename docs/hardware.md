# Target hardware

**Measured on the target laptop, 31 Oct 2026** (from `nvidia-smi` output sent by the user):

| Item | Measured |
| --- | --- |
| GPU | NVIDIA GeForce **RTX 4060** (the name is cut off in the output; almost certainly the Laptop GPU) |
| VRAM | **8188 MiB** (8 GB) |
| Driver / CUDA | 610.74 / CUDA 13.3 |
| Ollama server | `llama-server.exe` running under Ollama, so the model ran on the GPU |

The earlier assumption of an **RTX 5050** was wrong. Nothing in the code depends on the GPU model, but the
8 GB budget is the same, so the sizing below still holds. Still unmeasured: OS build, system RAM, free disk,
Ollama version, `ollama ps` offload percentage.

Qwen3-VL 4B Instruct, context 8192: **peak whole-GPU use 5.4 GB** in both models (see `docs/benchmark.md`),
leaving about 2.7 GB. That is enough for one model; do not load two at once (`OLLAMA_MAX_LOADED_MODELS=1`).

## Checklist for another machine

| Check | Command | Expected (assumption) | Measured |
| --- | --- | --- | --- |
| GPU name + VRAM | `nvidia-smi` | RTX 5050 Laptop, ~8 GB | |
| Driver / CUDA shown | `nvidia-smi` | recent driver | |
| VRAM used at idle | `nvidia-smi` | < 1.5 GB (browser, desktop) | |
| OS / build | `winver` | Windows 11 | |
| System RAM | Task Manager | >= 16 GB | |
| Free disk | `dir` | >= 15 GB | |
| Ollama version | `ollama --version` | >= 0.12.7 (huihui card requirement) | |
| Python / Node | `python --version`, `node --version` | 3.10+ / 18+ | |
| Model fully on GPU | `ollama ps` after a request | `100% GPU` | |

## Steps (Windows PowerShell)

```powershell
ollama pull huihui_ai/qwen3-vl-abliterated:4b-instruct
ollama pull qwen3-vl:4b-instruct          # unmodified control model
$env:OLLAMA_MAX_LOADED_MODELS = "1"; $env:OLLAMA_NUM_PARALLEL = "1"
python scripts\smoke_vlm.py .\photos\board.jpg --model huihui_ai/qwen3-vl-abliterated:4b-instruct --out smoke_abl
python scripts\smoke_vlm.py .\photos\board.jpg --model qwen3-vl:4b-instruct --out smoke_base
```

Open `smoke_*/boxes.jpg` and check that boxes sit on the right parts. If `metrics.json` lists
`view_pixels_fallback`, the model is not using the 0-1000 convention and `geometry.py` needs adjusting.

Record `metrics.json` values (load, latency, peak VRAM) in `docs/benchmark.md`, labelled with the machine
they came from. Peak VRAM is a whole-GPU `nvidia-smi` sample, not per process.

## If something fails

| Symptom | Next step |
| --- | --- |
| `ollama ps` shows CPU/GPU split | Update NVIDIA driver and Ollama; close other GPU apps; retry |
| Out of memory | Lower `--num-ctx` to 4096, then try `huihui_ai/qwen3-vl-abliterated:2b` |
| Model not found | Check the tag with `ollama list`; the pull may have failed |
| Output not JSON | Use the `-instruct` tag (unsuffixed tags may be Thinking variants) |
| Ollama will not use the GPU at all | Fall back to llama.cpp CUDA with the GGUF + mmproj files |
