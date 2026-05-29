# Team Constraints — KG Extraction Refactor

## Hard Rules (All Agents)

1. **ZERO local execution** — Do NOT run any commands (pytest, pip, uvicorn, python, npm). This is an office laptop. All verification is static only (Read, Grep, Glob).

2. **GPU-optimized for Windows + Mac** — Any code that touches hardware detection must support:
   - CUDA (Windows/Linux NVIDIA GPUs)
   - MPS (Apple Silicon Macs)
   - CPU fallback (always)

3. **The new ConvKGExtractor is pure async** — no torch, no transformers, no GPU code. It calls the LLM router API. GPU optimization applies only to any remaining modules that use local models (e.g., toxic_scorer_lazy.py, embedding providers).

4. **Cross-platform path handling** — Use `pathlib.Path` not hardcoded `/` or `\\`. The codebase runs on Windows, Mac, and Linux.
