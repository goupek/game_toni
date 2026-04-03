# Pipeline Layout

This folder holds the standalone speech/LLM/TTS pipeline scripts that used to
live at the repository root.

- `whisper-gemma3n-silero.py`
  Current main pipeline script kept at the top of `pipeline/`.

- `experiments/`
  One-off or alternate pipeline variants such as Piper, VAD, Whisper, and
  Vosk combinations.

- `tests/`
  Quick test scripts and throwaway verification entrypoints.

- `archive/`
  Older dated snapshots kept for reference.

The repository root is now reserved for the main game entrypoints and a smaller
set of top-level assets.
