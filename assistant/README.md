# Assistant Runtime

This directory combines the final voice pipeline with the `memory/new_mem`
runtime in one place.

- `whisper-gemma3n-silero.py`
  Final voice pipeline entrypoint.

- `memory_bridge.py`
  Full memory-aware LLM bridge for the voice pipeline. It now handles:
  - child fact auto-extraction
  - recall and archival retrieval as extra context
  - memory tool execution with `save_child_info`, `update_child_info`,
    `record_learned_word`, and `consult_russian_teacher_manual`
  - `send_message` tool delivery for the spoken reply
  - text-tool-call fallback for small Gemma models on `llama.cpp`
  - recall compression into archival memory
  - memory health reporting and JSON backup export

- `config.py`, `memory_system.py`, `memory_tools.py`, and related helpers
  Local copies of the memory runtime needed by the integrated assistant.

Notes:
- The pipeline flow stays the same at the audio level: VAD -> Whisper -> llama.cpp -> Silero TTS.
- The integrated assistant now targets `.../models/gemma/gemma-3-4b-it-q4_k_m7B`.
- Memory databases are stored inside this `assistant/` directory.
