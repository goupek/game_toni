# toni_llm

## Voice Assistant: g4-e2b-boxy_streaming.py

Russian language tutor voice assistant using Whisper STT, Gemma 4 E2B LLM, and Silero TTS.

### Start llama.cpp server

```bash
./llama.cpp/build/bin/llama-server \
  -m ~/toni_llm/models/gemma/gemma-4-E2B-it-Q4_K_M.gguf \
  -ngl 80 -c 1024 --port 8080 \
  --reasoning off
```

### Run the assistant

```bash
python g4-e2b-boxy_streaming.py
```
