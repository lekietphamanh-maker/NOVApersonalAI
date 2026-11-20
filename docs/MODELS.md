# Models on this PC: GPU, versions, comparing, fine-tuning

## Is the model really on the GPU?

**SETTINGS → This PC** shows live CPU, RAM, GPU and graphics memory (Windows' performance counters) and, for each
loaded model, what Ollama itself reports (`/api/ps`): its size and how much of it is in graphics memory → "runs on GPU",
"CPU" or "75% GPU / 25% CPU". Nothing is assumed. **Load model** / **Unload** load it now or free the graphics memory.

**AMD Radeon RX 6600 XT (gfx1032, 8 GB) on Windows:** Ollama's AMD ROCm support on Windows doesn't include gfx1032,
and the `HSA_OVERRIDE_GFX_VERSION` trick from Linux doesn't apply on Windows. The route is **Vulkan**: current Ollama
releases enable it by default when its Vulkan backend is installed; with an older Ollama set the user environment
variable `OLLAMA_VULKAN=1` and restart Ollama. Then check the line in SETTINGS → This PC. If it still says CPU, Ollama's
server log (`%LOCALAPPDATA%\Ollama\server.log`) names the GPUs it found. Ollama falls back to the CPU by itself.

What fits in 8 GB: 4B models (qwen3:4b, gemma3:4b) fit whole with Nova's 8192-token context; 7–8B models
(qwen3:8b, qwen2.5-coder:7b) at Q4 are about 5–6 GB and fit with a modest context, or split between GPU and CPU.
Nova uses 8192 tokens rather than 4096 because its instructions and tool list alone take about 3,700 tokens; a
4096 context would cut the conversation down to almost nothing.

## Custom versions (SETTINGS → Model → Custom versions)

Pick an installed model, give the version a name, its own instructions (system prompt), temperature and context.
Nova asks Ollama to make `nova-<name>` from it (`/api/create`); the original isn't changed, and only `nova-` versions
can be deleted there. Choose the version under **Which model** to use it.

**Compare two models**: Nova's seven quick checks (`evaluate.py`: arithmetic, facts, recall, tool arguments, approval,
quoted instructions) on both, one after the other. It's a smoke test, not a benchmark.

## Fine-tuning (LoRA / PEFT)

Training a LoRA isn't practical on this PC: PyTorch has no ROCm build for gfx1032 on Windows, and CPU training of a
4B model takes days. Train where there is an NVIDIA GPU (Google Colab, Kaggle, a rented GPU) with Hugging Face PEFT,
then bring the adapter to Ollama with a Modelfile:

```
FROM qwen3:4b
ADAPTER ./my-lora          # a safetensors LoRA trained on the same base model
SYSTEM "You are Nova…"
PARAMETER temperature 0.6
```

`ollama create nova-mylora -f Modelfile`, then compare it with the base in Settings. Keep the base model: the adapter
is a separate version.

**Not included:** tools that remove a model's safety refusals ("abliteration"). Fewer refusals doesn't make a model
smarter, and Nova's safeguards are part of what makes it safe to leave running on your PC.
