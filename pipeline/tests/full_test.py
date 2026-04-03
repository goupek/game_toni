import queue
import json
import sys
import os
import tempfile
import numpy as np
import sounddevice as sd
import simpleaudio as sa
import webrtcvad

from vosk import Model, KaldiRecognizer
from ollama import chat
from TTS.api import TTS

# ================= CONFIG =================

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)

WAKE_WORD = "hi"
SLEEP_WORD = "bye bye"

LLM_MODEL = "qwen2.5:1.5b-instruct"
VOSK_MODEL_PATH = "models/vosk/vosk-model-en-us-0.22-lgraph"
# VOSK_MODEL_PATH = "models/vosk/vosk-model-small-multilingual-0.22"

# Multilingual TTS models
TTS_EN = "tts_models/en/ljspeech/tacotron2-DDC"
TTS_RU = "tts_models/ru/v3_1/fast_pitch"

# ==========================================

audio_q = queue.Queue()
vad = webrtcvad.Vad(2)

vosk_model = Model(VOSK_MODEL_PATH)
recognizer = KaldiRecognizer(vosk_model, SAMPLE_RATE)

tts_en = TTS(TTS_EN, progress_bar=False)
tts_ru = TTS(TTS_RU, progress_bar=False)

# ==========================================

def mic_callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    audio_q.put(bytes(indata))


# ==========================================

def detect_language(text):
    """Very simple RU/EN detector."""
    for c in text:
        if "а" <= c.lower() <= "я":
            return "ru"
    return "en"


# ==========================================

def speak(text):
    if not text.strip():
        return

    lang = detect_language(text)
    tts = tts_ru if lang == "ru" else tts_en

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
        wav_path = f.name

    tts.tts_to_file(text=text, file_path=wav_path)

    wave = sa.WaveObject.from_wave_file(wav_path)
    play = wave.play()
    play.wait_done()

    os.remove(wav_path)


# ==========================================

def listen_until_silence():
    """
    Records speech until silence detected using WebRTC VAD.
    Returns recognized text.
    """

    print("\n Listening... (stop speaking to finish)\n")

    voiced_frames = []
    silence_count = 0
    max_silence = 15  # ~0.5 sec

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=FRAME_SIZE,
        dtype="int16",
        channels=1,
        callback=mic_callback,
    ):
        while True:
            frame = audio_q.get()

            is_speech = vad.is_speech(frame, SAMPLE_RATE)

            if is_speech:
                voiced_frames.append(frame)
                silence_count = 0
            else:
                silence_count += 1

            # stop after silence
            if silence_count > max_silence and voiced_frames:
                break

    audio_data = b"".join(voiced_frames)

    recognizer.Reset()
    recognizer.AcceptWaveform(audio_data)
    result = json.loads(recognizer.Result())

    return result.get("text", "").strip()


# ==========================================

def llm_stream_and_tts(prompt):
    print("\n Assistant: ", end="", flush=True)

    buffer = ""

    stream = chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )

    for chunk in stream:
        token = chunk["message"]["content"]
        print(token, end="", flush=True)

        buffer += token

        # Speak sentence chunks
        if buffer.strip().endswith((".", "!", "?")):
            speak(buffer)
            buffer = ""

    if buffer.strip():
        speak(buffer)

    print("\n")


# ==========================================

def main():
    active = False

    print("\n Assistant Ready")
    print(f"Say '{WAKE_WORD}' to wake up")
    print(f"Say '{SLEEP_WORD}' to sleep\n")

    while True:
        try:
            text = listen_until_silence()

            if not text:
                continue

            print(f" Heard: {text}")

            # Wake mode
            if not active:
                if WAKE_WORD in text.lower():
                    active = True
                    speak("Hello! I am listening.")
                    print("Activated")
                continue

            # Sleep mode
            if SLEEP_WORD in text.lower():
                active = False
                speak("Goodbye!")
                print("Sleeping")
                continue

            # Normal conversation
            llm_stream_and_tts(text)

        except KeyboardInterrupt:
            print("\nExiting.")
            break


# ==========================================

if __name__ == "__main__":
    main()
