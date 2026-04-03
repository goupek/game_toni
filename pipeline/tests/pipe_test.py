import os
import torch
import queue
import json
import requests
import numpy as np
import sounddevice as sd
import webrtcvad
import time
import re
import soundfile as sf
import threading

from vosk import Model, KaldiRecognizer
from qwen_tts import Qwen3TTSModel   # <- your TTS import

# =========================
# CONFIG
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

VOSK_MODEL_PATH = os.path.join(BASE_DIR, "models/vosk/vosk-model-en-us-0.22-lgraph")
TTS_MODEL_PATH = os.path.join(BASE_DIR, "./Qwen3-TTS-0.6B-CustomVoice")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:1.5b-instruct"

WAKE_WORD = "hi box"

SAMPLE_RATE = 16000
BLOCK_SIZE = 8000
SILENCE_TIMEOUT = 1.0
VAD_AGGRESSIVENESS = 2

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"

# =========================
# LOAD MODELS
# =========================

print("Loading STT...")
stt_model = Model(VOSK_MODEL_PATH)
recognizer = KaldiRecognizer(stt_model, SAMPLE_RATE)

print("Loading Qwen3-TTS...")
tts_model = Qwen3TTSModel.from_pretrained(
    TTS_MODEL_PATH,
    device_map=DEVICE,
    dtype=torch.bfloat16 if "cuda" in DEVICE else torch.float32,
    attn_implementation="sdpa"
)

# =========================
# GLOBALS
# =========================

audio_queue = queue.Queue()
vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

assistant_active = False
collecting_query = False
user_query = ""
silence_start = None

# =========================
# AUDIO CALLBACK
# =========================

def audio_callback(indata, frames, time_info, status):
    audio_queue.put(bytes(indata))

# =========================
# LLM STREAM
# =========================

def stream_llm(prompt):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True
    }

    response = requests.post(OLLAMA_URL, json=payload, stream=True)

    for line in response.iter_lines():
        if line:
            data = json.loads(line)
            if "response" in data:
                yield data["response"]

# =========================
# TTS FUNCTION (REAL)
# =========================

def speak(text):
    print(f"[TTS] {text}")

    wavs, sr = tts_model.generate_custom_voice(
        text=text,
        speaker="vivian"
    )

    sd.play(wavs[0], sr)
    sd.wait()

# =========================
# SENTENCE SPLITTER
# =========================

def split_sentences(buffer):
    parts = re.split(r'(?<=[.!?])\s+', buffer)
    if len(parts) > 1:
        return parts[:-1], parts[-1]
    return [], buffer

# =========================
# MAIN LOOP
# =========================

def main():
    global assistant_active, collecting_query, user_query, silence_start

    print("Assistant is listening...")

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):

        while True:
            data = audio_queue.get()

            # VAD
            is_speech = False
            for i in range(0, len(data), 640):
                frame = data[i:i+640]
                if len(frame) == 640 and vad.is_speech(frame, SAMPLE_RATE):
                    is_speech = True
                    break

            if is_speech:
                silence_start = None

                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").lower()

                    # LOG: what STT heard (final result)
                    if text:
                        print(f"[STT] {text}")

                    if not assistant_active:
                        if WAKE_WORD in text:
                            print("[WAKE] Wake word detected!")
                            assistant_active = True
                            collecting_query = True
                            user_query = ""
                            speak("Yes?")

                    elif collecting_query:
                        user_query += text + " "

                else:
                    partial = json.loads(recognizer.PartialResult())
                    partial_text = partial.get("partial", "")
                    if partial_text:
                        print(f"\r[STT partial] {partial_text}    ", end="")

            else:
                if collecting_query:
                    if silence_start is None:
                        silence_start = time.time()

                    elif time.time() - silence_start > SILENCE_TIMEOUT:

                        user_query = user_query.strip()
                        print(f"\n[USER] {user_query}")

                        # STREAM LLM — collect full answer for logging
                        llm_buffer = ""
                        llm_full = ""
                        for token in stream_llm(user_query):
                            print(token, end="", flush=True)
                            llm_buffer += token
                            llm_full += token

                            sentences, llm_buffer = split_sentences(llm_buffer)
                            for s in sentences:
                                speak(s)

                        if llm_buffer.strip():
                            speak(llm_buffer)

                        # LOG: full LLM answer
                        print(f"\n[LLM] {llm_full.strip()}")

                        # Reset state
                        assistant_active = False
                        collecting_query = False
                        user_query = ""
                        recognizer.Reset()
                        silence_start = None

# =========================

if __name__ == "__main__":
    main()