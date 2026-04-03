import io
import json
import traceback
import os
import queue
import threading
import time
import re
import subprocess # <-- NEW: Added subprocess for CLI execution
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np
import requests
import sounddevice as sd
import webrtcvad
from vosk import Model, KaldiRecognizer

# =========================
# CONFIGURATION
# =========================
MIC_DEVICE = 24  # Update to your specific microphone ID

# Vosk model folder
VOSK_MODEL_PATH = "models/vosk/vosk-model-small-en-us-0.15"

# Ollama (server must be running)
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:0.5b"

# Wake words & commands
WAKE_WORDS = ["hey box", "okay box", "hi box", "box box"]
GREETING = "Hi, how can I help you?"
SLEEP_PHRASES = ["go to sleep", "sleep", "stop listening", "goodbye", "bye"]

# LLM Limits
MAX_ASSISTANT_WORDS = 30
OLLAMA_NUM_PREDICT = 80
OLLAMA_TEMPERATURE = 0.4
OLLAMA_NUM_CTX = 512 

# Piper TTS Configuration
PIPER_EXEC_PATH = "piper" # <-- NEW: Change to "./piper" if using a local downloaded binary
PIPER_MODEL_PATH = "models/piper/en_US-lessac-medium.onnx"
TTS_OUTPUT_DIR = "audios"

# VAD settings
FRAME_MS = 20                  
VAD_AGGRESSIVENESS = 2          
PRE_ROLL_MS = 300               
END_SILENCE_MS = 500            
MAX_UTT_SLEEP_SEC = 3.0         
MAX_UTT_ACTIVE_SEC = 20.0
VAD_SUPPORTED_RATES = [16000, 48000, 32000, 8000]
ACTIVE_IDLE_TIMEOUT_SEC = 60

# =========================
# TEXT HELPERS
# =========================
def normalize_text(s: str) -> str:
    s = s.lower().strip()
    return re.sub(r"\s+", " ", s)

def contains_phrase(text: str, phrases: List[str]) -> bool:
    t = normalize_text(text)
    return any(p in t for p in phrases)

def clamp_words(text: str, max_words: int) -> str:
    words = text.strip().split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()

# =========================
# OLLAMA LOGIC (NON-STREAMING)
# =========================
def ollama_chat_once(messages: List[Dict]) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": OLLAMA_NUM_PREDICT,
            "temperature": OLLAMA_TEMPERATURE,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=600)
    r.raise_for_status()
    data = r.json()
    if isinstance(data.get("message"), dict):
        return (data["message"].get("content") or "").strip()
    return (data.get("response") or "").strip()

# =========================
# AUDIO TRACKER
# =========================
class AudioStateTracker:
    def __init__(self, output_dir: str = TTS_OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.file_counter = 0
        self.active = threading.Event()

# =========================
# TTS WORKER (CLI SYNTHESIS)
# =========================
class TTSWorker(threading.Thread):
    def __init__(self, audio_tracker: AudioStateTracker):
        super().__init__(daemon=True)
        self.audio_tracker = audio_tracker
        self.q: "queue.Queue[str]" = queue.Queue(maxsize=50)
        self._stop = threading.Event()
        self._ready = False

    def stop(self):
        self._stop.set()
        try:
            self.q.put_nowait("")
        except queue.Full:
            pass

    def say(self, text: str):
        text = text.strip()
        if text:
            self.q.put(text)

    def _lazy_init(self):
        # We don't need to load a model into memory anymore, just verify the file exists
        if self._ready:
            return
        if not os.path.exists(PIPER_MODEL_PATH):
            print(f"[TTS Error] Could not find Piper model at {PIPER_MODEL_PATH}")
            return
        self._ready = True
        print("[TTS] CLI Ready.")

    def _synthesize_and_save(self, text: str):
        self._lazy_init()

        with self.audio_tracker.lock:
            self.audio_tracker.file_counter += 1
            counter = self.audio_tracker.file_counter
            
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        text_slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip()).strip("_")[:40]
        filename = f"tts_{timestamp}_{counter:04d}_{text_slug}.wav"
        out_path = self.audio_tracker.output_dir / filename

        try:
            self.audio_tracker.active.set() 
            
            # Construct the Piper CLI command
            command = [
                PIPER_EXEC_PATH,
                "--model", PIPER_MODEL_PATH,
                "--output_file", str(out_path)
            ]
            
            # Run the command and pass the text via stdin
            subprocess.run(
                command, 
                input=text.encode('utf-8'), 
                check=True,
                stdout=subprocess.DEVNULL, # Hides standard piper console output
                stderr=subprocess.PIPE     # Captures errors if it fails
            )
                
            print(f"[TTS] Successfully saved whole audio to {out_path} via CLI")
            
        except subprocess.CalledProcessError as e:
            print(f"[TTS CLI Error]: Piper command failed with exit code {e.returncode}")
            print(f"Error output: {e.stderr.decode('utf-8')}")
        except FileNotFoundError:
             print(f"[TTS Error]: Could not find the executable '{PIPER_EXEC_PATH}'. Is it installed or in your PATH?")
        except Exception as e:
            print(f"[TTS Error]: {e}")
            traceback.print_exc()
        finally:
            self.audio_tracker.active.clear()

    def run(self):
        while not self._stop.is_set():
            text = self.q.get()
            if self._stop.is_set():
                break
            if not text:
                continue
            try:
                self._synthesize_and_save(text)
            except Exception as e:
                print(f"[TTS] Error: {e}")
                traceback.print_exc()

# =========================
# VAD & VOSK CAPTURE
# =========================
@dataclass
class CaptureOut:
    partial: Optional[str] = None
    final: Optional[str] = None

class VadVoskCapture:
    def __init__(self, vad: webrtcvad.Vad, sr: int, frame_ms: int):
        self.vad = vad
        self.sr = sr
        self.frame_ms = frame_ms
        self.frame_samples = int(sr * frame_ms / 1000)
        self.frame_bytes = self.frame_samples * 2
        self.pre_roll_frames = max(1, int(PRE_ROLL_MS / frame_ms))
        self.end_silence_frames = max(1, int(END_SILENCE_MS / frame_ms))
        self.pre = deque(maxlen=self.pre_roll_frames)
        self.triggered = False
        self.silence = 0
        self.start_time = 0.0

    def reset(self):
        self.pre.clear()
        self.triggered = False
        self.silence = 0
        self.start_time = 0.0

    def step(self, frame: bytes, rec: KaldiRecognizer, max_utt_sec: float, want_partial: bool) -> CaptureOut:
        if len(frame) != self.frame_bytes:
            return CaptureOut()

        is_speech = self.vad.is_speech(frame, self.sr)

        if not self.triggered:
            self.pre.append(frame)
            if is_speech:
                self.triggered = True
                self.silence = 0
                self.start_time = time.time()
                for fr in self.pre:
                    rec.AcceptWaveform(fr)
                self.pre.clear()
                rec.AcceptWaveform(frame)
                if want_partial:
                    pres = json.loads(rec.PartialResult() or "{}")
                    p = (pres.get("partial") or "").strip()
                    return CaptureOut(partial=p or None)
            return CaptureOut()

        rec.AcceptWaveform(frame)
        if is_speech:
            self.silence = 0
        else:
            self.silence += 1

        partial = None
        if want_partial:
            pres = json.loads(rec.PartialResult() or "{}")
            partial = (pres.get("partial") or "").strip() or None

        too_long = (time.time() - self.start_time) >= max_utt_sec
        ended = (self.silence >= self.end_silence_frames) or too_long

        if ended:
            res = json.loads(rec.FinalResult() or "{}")
            text = (res.get("text") or "").strip() or None
            self.reset()
            return CaptureOut(partial=partial, final=text)

        return CaptureOut(partial=partial)

# =========================
# MAIN ASSISTANT
# =========================
@dataclass
class State:
    mode: str 
    last_activity: float

class VoiceAssistant:
    def __init__(self):
        self.state = State(mode="SLEEP", last_activity=time.time())
        self.audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=400)
        self.audio_tracker = AudioStateTracker()
        self.tts = TTSWorker(self.audio_tracker)
        self.tts.start()

        self.sample_rate = self._pick_input_rate()
        self.frame_samples = int(self.sample_rate * FRAME_MS / 1000)
        self.frame_bytes = self.frame_samples * 2

        self.vosk_model = Model(VOSK_MODEL_PATH)
        self._make_recognizers()

        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.capture = VadVoskCapture(self.vad, self.sample_rate, FRAME_MS)

        self.messages: List[Dict] = [
            {"role": "system",
             "content": (
                 "You are an educational voice assistant for kids. "
                 "Be friendly, clear, and concise. "
                 f"Answer in at most {MAX_ASSISTANT_WORDS} words. "
                 "If unsure, ask one short question."
             )}
        ]
        self.mic_gate_until = 0.0

    def _pick_input_rate(self) -> int:
        for sr in VAD_SUPPORTED_RATES:
            try:
                sd.check_input_settings(device=MIC_DEVICE, samplerate=sr, channels=1, dtype="int16")
                return sr
            except Exception:
                continue
        info = sd.query_devices(None, "input")
        sr = int(info["default_samplerate"])
        if sr not in VAD_SUPPORTED_RATES:
            raise RuntimeError(f"Mic sample rate {sr} not supported. Use one of {VAD_SUPPORTED_RATES}.")
        return sr

    def _make_recognizers(self):
        wake_grammar = json.dumps(WAKE_WORDS)
        self.rec_wake = KaldiRecognizer(self.vosk_model, self.sample_rate, wake_grammar)
        self.rec_full = KaldiRecognizer(self.vosk_model, self.sample_rate)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(status)
        if self.audio_tracker.active.is_set() or time.time() < self.mic_gate_until:
            return

        b = bytes(indata)
        if len(b) != self.frame_bytes:
            return

        try:
            self.audio_q.put_nowait(b)
        except queue.Full:
            try:
                _ = self.audio_q.get_nowait()
                self.audio_q.put_nowait(b)
            except queue.Empty:
                pass

    def _trim_history(self, keep_last_pairs: int = 4):
        sys_msg = self.messages[:1]
        rest = self.messages[1:]
        if len(rest) > keep_last_pairs * 2:
            self.messages = sys_msg + rest[-keep_last_pairs * 2:]

    def _enter_sleep(self):
        self.state.mode = "SLEEP"
        self.state.last_activity = time.time()
        self._make_recognizers()
        self.capture.reset()
        print("[STATE] -> SLEEP")

    def _enter_active(self):
        self.state.mode = "ACTIVE"
        self.state.last_activity = time.time()
        self._make_recognizers()
        self.capture.reset()
        print("[STATE] -> ACTIVE")
        self.tts.say(GREETING)

    def _respond_with_llm(self, user_text: str):
        self.messages.append({"role": "user", "content": user_text})
        self._trim_history()

        print(f"[USER] {user_text}")
        assistant_full = ""
        try:
            assistant_full = ollama_chat_once(self.messages)
            assistant_full = clamp_words(assistant_full, MAX_ASSISTANT_WORDS)
            if not assistant_full:
                assistant_full = "Sorry, I had trouble answering that."
            self.tts.say(assistant_full)
        except Exception as e:
            print(f"[LLM] Error: {e}")
            assistant_full = "Sorry, I had trouble answering that."
            self.tts.say(assistant_full)

        print(f"[ASSISTANT] {assistant_full}")
        self.messages.append({"role": "assistant", "content": assistant_full})
        self._trim_history()
        self.mic_gate_until = time.time() + 0.15

    def run_forever(self):
        print("==============================================")
        print("Assistant running (Single-File Whole Audio Mode).")
        print(f"Input sample rate: {self.sample_rate} Hz | Frame: {FRAME_MS} ms")
        print(f"Wake words: {WAKE_WORDS}")
        print("==============================================")

        with sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_samples,  
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
        ):
            try:
                while True:
                    if self.state.mode == "ACTIVE" and (time.time() - self.state.last_activity) > ACTIVE_IDLE_TIMEOUT_SEC:
                        self.tts.say("I'll wait. Say 'hey box' if you need me.")
                        self._enter_sleep()

                    frame = self.audio_q.get()

                    if self.state.mode == "SLEEP":
                        out = self.capture.step(
                            frame=frame, rec=self.rec_wake, max_utt_sec=MAX_UTT_SLEEP_SEC, want_partial=True
                        )
                        if out.partial and contains_phrase(out.partial, WAKE_WORDS):
                            print(f"[STT partial] {out.partial}\n")
                            self._enter_active()
                            self.mic_gate_until = time.time() + 0.2
                            continue
                        if out.final and contains_phrase(out.final, WAKE_WORDS):
                            print(f"[STT] {out.final}\n")
                            self._enter_active()
                            self.mic_gate_until = time.time() + 0.2
                            continue

                    else:
                        out = self.capture.step(
                            frame=frame, rec=self.rec_full, max_utt_sec=MAX_UTT_ACTIVE_SEC, want_partial=False
                        )
                        if out.final:
                            user_text = out.final.strip()
                            if user_text:
                                print(f"[STT] {user_text}\n")
                                self.state.last_activity = time.time()
                                if contains_phrase(user_text, SLEEP_PHRASES):
                                    self.tts.say("Okay. Say 'hey box' if you need me.")
                                    self._enter_sleep()
                                else:
                                    self._respond_with_llm(user_text)
                                    self.rec_full = KaldiRecognizer(self.vosk_model, self.sample_rate)

            except KeyboardInterrupt:
                print("\nExiting...")
            finally:
                self.tts.stop()

if __name__ == "__main__":
    VoiceAssistant().run_forever()