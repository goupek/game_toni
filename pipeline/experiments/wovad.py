import json
import queue
import threading
import time
import re
from collections import deque
from dataclasses import dataclass
from typing import List, Dict, Iterable, Optional
import torch
import numpy as np
import requests
import sounddevice as sd
from vosk import Model, KaldiRecognizer

# =========================
# CONFIG
# =========================
device = "cuda:0" if torch.cuda.is_available() else "cpu"
MIC_DEVICE = 24

# Memory Optimized Vosk Model
VOSK_MODEL_PATH = "models/vosk/vosk-model-small-en-us-0.15"

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:1.5b-instruct"

MAX_ASSISTANT_WORDS = 30
OLLAMA_NUM_PREDICT = 80
OLLAMA_TEMPERATURE = 0.4

WORDS_PER_TTS_CHUNK = 8

TTS_MODEL_ID = "./Qwen3-TTS-0.6B-CustomVoice"
TTS_LANGUAGE = "English"
TTS_SPEAKER = "Ryan"
TTS_INSTRUCT = ""

VAD_SUPPORTED_RATES = [16000, 48000, 32000, 8000]

# =========================
# TEXT HELPERS
# =========================

def clamp_words(text: str, max_words: int) -> str:
    words = text.strip().split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()

# =========================
# OLLAMA STREAMING
# =========================

def ollama_chat_stream(messages: List[Dict]) -> Iterable[str]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "options": {
            "num_predict": OLLAMA_NUM_PREDICT,
            "temperature": OLLAMA_TEMPERATURE,
        },
    }
    with requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=600) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            data = json.loads(line)

            if isinstance(data.get("message"), dict):
                chunk = data["message"].get("content") or ""
            else:
                chunk = data.get("response") or ""

            if chunk:
                yield chunk

            if data.get("done"):
                break

# =========================
# CONTINUOUS AUDIO OUTPUT
# =========================

class AudioStreamer:
    def __init__(self):
        self.sr: Optional[int] = None
        self.stream: Optional[sd.OutputStream] = None
        self.lock = threading.Lock()
        self.buf = deque()     
        self.buf_len = 0       
        self.active = threading.Event()

    def _callback(self, outdata, frames, time_info, status):
        out = np.zeros((frames,), dtype=np.float32)

        with self.lock:
            need = frames
            idx = 0
            while need > 0 and self.buf:
                chunk = self.buf[0]
                take = min(need, len(chunk))
                out[idx:idx + take] = chunk[:take]
                idx += take
                need -= take
                self.buf_len -= take

                if take == len(chunk):
                    self.buf.popleft()
                else:
                    self.buf[0] = chunk[take:]

            if self.buf_len <= 0 and not self.buf:
                self.active.clear()

        outdata[:] = out.reshape(-1, 1)

    def start(self, sr: int):
        if self.stream and self.sr == sr:
            return
        self.stop()
        self.sr = sr
        self.stream = sd.OutputStream(
            samplerate=sr,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def stop(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        self.stream = None
        self.sr = None
        with self.lock:
            self.buf.clear()
            self.buf_len = 0
        self.active.clear()

    def add_audio(self, wav: np.ndarray, sr: int):
        if wav.ndim > 1:
            wav = wav[:, 0]
        wav = wav.astype(np.float32, copy=False)

        self.start(sr)
        with self.lock:
            self.buf.append(wav)
            self.buf_len += len(wav)
            self.active.set()

# =========================
# TTS WORKER
# =========================

class TTSWorker(threading.Thread):
    def __init__(self, audio_streamer: AudioStreamer):
        super().__init__(daemon=True)
        self.audio_streamer = audio_streamer
        self.q: "queue.Queue[str]" = queue.Queue(maxsize=50)
        self._stop = threading.Event()
        self._ready = False
        self._model = None

    def stop(self):
        self._stop.set()
        try:
            self.q.put_nowait("")
        except queue.Full:
            pass

    def say(self, text: str):
        text = text.strip()
        if not text:
            return
        self.q.put(text)

    def _lazy_init(self):
        if self._ready:
            return
        import torch
        from qwen_tts import Qwen3TTSModel

        try:
            torch.set_num_threads(2)
        except Exception:
            pass

        print("[TTS] Loading Qwen3-TTS...")
        self._model = Qwen3TTSModel.from_pretrained(
            TTS_MODEL_ID,
            device_map=device,
            dtype=torch.float16,  # Memory optimization
        )
        self._ready = True
        print("[TTS] Ready.")

    def run(self):
        while not self._stop.is_set():
            text = self.q.get()
            if self._stop.is_set():
                break
            if not text:
                continue

            try:
                self._lazy_init()
                tts_start_time = time.time()
                
                wavs, sr = self._model.generate_custom_voice(
                    text=text,
                    language=TTS_LANGUAGE,
                    speaker=TTS_SPEAKER,
                    instruct=TTS_INSTRUCT,
                )
                
                tts_duration = time.time() - tts_start_time
                print(f"[TIMING] TTS generated chunk in {tts_duration:.3f}s -> '{text}'")
                
                self.audio_streamer.add_audio(wavs[0], sr)
            except Exception as e:
                print(f"[TTS] Error: {e}")

# =========================
# MAIN ASSISTANT
# =========================

class VoiceAssistant:
    def __init__(self):
        self.audio_out = AudioStreamer()
        self.tts = TTSWorker(self.audio_out)
        self.tts.start()

        self.sample_rate = self._pick_input_rate()
        
        self.vosk_model = Model(VOSK_MODEL_PATH)
        self.rec_full = KaldiRecognizer(self.vosk_model, self.sample_rate)

        self.messages: List[Dict] = [
            {"role": "system",
             "content": (
                 "You are an educational voice assistant for kids. "
                 "Be friendly, clear, and concise. "
                 f"Answer in at most {MAX_ASSISTANT_WORDS} words. "
                 "If unsure, ask one short question."
             )}
        ]

    def _pick_input_rate(self) -> int:
        for sr in VAD_SUPPORTED_RATES:
            try:
                sd.check_input_settings(device=MIC_DEVICE, samplerate=sr, channels=1, dtype="int16")
                return sr
            except Exception:
                continue
        info = sd.query_devices(None, "input")
        sr = int(info["default_samplerate"])
        return sr

    def _trim_history(self, keep_last_pairs: int = 4):
        sys_msg = self.messages[:1]
        rest = self.messages[1:]
        if len(rest) > keep_last_pairs * 2:
            self.messages = sys_msg + rest[-keep_last_pairs * 2:]

    def _respond_with_llm(self, user_text: str):
        self.messages.append({"role": "user", "content": user_text})
        self._trim_history()

        assistant_full = ""
        llm_start_time = time.time()
        first_token_time = 0.0
        
        try:
            deltas = ollama_chat_stream(self.messages)
            buf = ""
            spoken = 0

            for delta in deltas:
                if first_token_time == 0.0 and delta.strip():
                    first_token_time = time.time()
                    print(f"[TIMING] LLM Time to First Token: {first_token_time - llm_start_time:.3f}s")

                assistant_full += delta
                buf += delta

                while spoken < MAX_ASSISTANT_WORDS:
                    words = buf.strip().split()
                    if len(words) < WORDS_PER_TTS_CHUNK:
                        break
                    take = min(WORDS_PER_TTS_CHUNK, MAX_ASSISTANT_WORDS - spoken)
                    chunk = " ".join(words[:take]).strip()
                    if chunk:
                        self.tts.say(chunk)
                        spoken += take
                    rem = words[take:]
                    buf = (" ".join(rem) + " ") if rem else ""

                if spoken >= MAX_ASSISTANT_WORDS:
                    break

                if re.search(r"[.!?]\s*$", buf) and buf.strip():
                    words = buf.strip().split()
                    take = min(len(words), MAX_ASSISTANT_WORDS - spoken)
                    chunk = " ".join(words[:take]).strip()
                    if chunk:
                        self.tts.say(chunk)
                        spoken += take
                    buf = ""
                    if spoken >= MAX_ASSISTANT_WORDS:
                        break

            if spoken < MAX_ASSISTANT_WORDS and buf.strip():
                words = buf.strip().split()
                take = min(len(words), MAX_ASSISTANT_WORDS - spoken)
                chunk = " ".join(words[:take]).strip()
                if chunk:
                    self.tts.say(chunk)

        except Exception as e:
            print(f"[LLM] Error: {e}")
            assistant_full = "Sorry, I had trouble answering that."
            self.tts.say(assistant_full)
            
        print(f"[TIMING] Total LLM Generation Time: {time.time() - llm_start_time:.3f}s")
        assistant_full = clamp_words(assistant_full, MAX_ASSISTANT_WORDS)
        print(f"[ASSISTANT] {assistant_full}")

        self.messages.append({"role": "assistant", "content": assistant_full})
        self._trim_history()

    def run_forever(self):
        print("==============================================")
        print("Pure Pipeline Test (5s Listen -> LLM -> TTS)")
        print(f"Input sample rate: {self.sample_rate} Hz")
        print("Press Ctrl+C to exit.")
        print("==============================================")

        try:
            while True:
                print("\n[🎙️] Listening for 5 seconds... Speak now!")
                
                # 1. Block and record exactly 5 seconds of audio
                audio_data = sd.rec(
                    int(5 * self.sample_rate), 
                    samplerate=self.sample_rate, 
                    channels=1, 
                    dtype='int16'
                )
                sd.wait() # Wait until recording is finished
                
                print("[⏳] Processing audio...")
                
                # 2. Feed the entire 5-second chunk to Vosk at once
                self.rec_full.AcceptWaveform(audio_data.tobytes())
                res = json.loads(self.rec_full.FinalResult())
                user_text = res.get("text", "").strip()
                
                # 3. If we heard something, process it
                if user_text:
                    print(f"[USER] {user_text}")
                    self._respond_with_llm(user_text)
                    
                    # 4. Wait for TTS to completely finish speaking before recording again
                    # Otherwise, it will record its own voice!
                    while not self.tts.q.empty() or self.audio_out.active.is_set():
                        time.sleep(0.1)
                    time.sleep(0.5) # A tiny buffer to let the speaker fully silence
                    
                    # Reset Vosk recognizer for the next loop
                    self.rec_full = KaldiRecognizer(self.vosk_model, self.sample_rate)
                else:
                    print("[STT] Heard nothing or silence.")
                
        except KeyboardInterrupt:
            print("\nExiting...")
        finally:
            self.tts.stop()
            self.audio_out.stop()

if __name__ == "__main__":
    VoiceAssistant().run_forever()