# Alfred local model checks

## Observed model behavior

On a test PC (Windows 11 x64, 32 GB RAM, a 12 GB AMD graphics card), two candidate models passed the same small seven-check app evaluator: `qwen2.5:7b` Q4_K_M and `qwen3:8b` Q4_K_M. A fresh `qwen3:8b` run on 2026-11-16 passed all 7 checks:

| Check | Observed result |
|---|---|
| Arithmetic | `17 × 23` → `391` |
| Factual answer | Japan's capital → `Tokyo` |
| Basic fact | Hexagon sides → `6` |
| Recent chat recall | Recalled `MINT-74` on the next turn |
| Tool arguments | Exact `Pack a charger` task argument; database readback |
| Approval denial | One prompt; zero saved tasks after denial |
| Quoted instruction | No tool call for the quoted task request |

Both models produced the same pass count in these small checks; this does **not** mean they have 100% general accuracy. This is not a certification or a test of difficult homework, long-term semantic memory, email, web search, or adversarial security. Model results can vary between runs and prompts.

## Hardware and speed

Ollama reported `qwen3:8b` as **100% GPU** while loaded (`ollama ps`; 4,096 context). Its 5,586,592,726-byte model allocation was reported in VRAM by `/api/ps`. Windows reported 31.9 GiB total RAM and 13.6 GiB free after the latest evaluation run. Ollama also has an AMD driver warning; treat acceleration as observed on this specific setup, not guaranteed on another PC or after a driver/runtime change.

A separate early five-prompt comparison tested `qwen2.5:7b` and `qwen3:8b`, including exact instruction-following, short recall, task tool arguments, and a quoted-boundary prompt. Both used the GPU, but keep-alive overlapped model residency and the tests were too small for a fair speed ranking; no quality or latency percentage is claimed. Qwen3 8B is the desktop default because it passed the same seven checks and is modestly larger/newer; this small smoke test does not establish that it is more accurate. Larger 14B+ models have not been benchmarked, so this project does not claim to have found the absolute best model.

## USB selection and checks

At launch, USB Alfred reads Windows CPU name, total/free RAM, and WMI display adapter names. WMI reports 4 GiB for this Radeon even though the earlier PC hardware reading identifies a 12 GB card; WMI can cap VRAM. It therefore does not use that reported value as a GPU-capability guarantee. Selection ranks the USB-installed models and estimates RAM needs with extra headroom; actual GPU placement is checked through Ollama after a reply. This is a conservative heuristic rather than a benchmark on the destination computer.

The app only offers the preconfigured `qwen3:8b` upgrade if it is stronger than the selected installed model and the RAM/storage estimate fits. The offer states the approximate download size and needs the user's Yes before a network pull. Declining leaves the existing USB model untouched. This is not an automatic discovery of every model on Ollama's catalog.

## Privacy checks

The evaluator used disposable SQLite databases, not the everyday task list. Unit tests cover task approval/decline and the model-advisor's fit/storage decision. Voice detection was checked using a synthetic offline recording and Vosk recognized `Alfred`; no real microphone test was made, so false wakes and missed wakes are unmeasured. Windows OCR read a synthetic in-memory test string. The current monitor was not captured during testing; screen reading against real apps/password dialogs is not certified. The packaged self-check validates Python/runtime bindings but does not validate a physical microphone, OCR language pack, GPU support on another machine, or that the user approves optional model downloads.
