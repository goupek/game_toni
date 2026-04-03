# Assistant Runtime

This directory combines the final voice pipeline with the `memory/new_mem`
runtime in one place.

- `whisper-gemma3n-silero.py`
  Final pipeline entrypoint with minimal memory integration.

- `memory_bridge.py`
  Small adapter that adds:
  - child fact auto-extraction
  - recall and archival retrieval as extra system context
  - saving user and assistant turns into memory

- `config.py`, `memory_system.py`, `memory_tools.py`, and related helpers
  Local copies of the memory runtime needed by the integrated assistant.

Notes:
- The pipeline flow itself stays the same: VAD -> Whisper -> llama.cpp stream -> Silero TTS.
- The LLM default now targets `gemma-3-1b-it` from `config.py`.
- Memory databases are stored inside this `assistant/` directory.
