import json
import os
import queue
import re
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
import sounddevice as sd
import webrtcvad
from vosk import KaldiRecognizer, Model


# =========================
# CONFIG
# =========================
MIC_DEVICE = 24
USE_EXPLICIT_MIC_DEVICE = False  # original code used default input device

# Vosk model folder
VOSK_MODEL_PATH = "models/vosk/vosk-model-small-en-us-0.15"

# Ollama (server must be running)
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:0.5b"

# Wake words (keep them simple)
WAKE_WORDS = ["hey box", "okay box", "hi box", "box box"]
GREETING = "Hi, how can I help you?"
SLEEP_PHRASES = ["go to sleep", "sleep", "stop listening", "goodbye", "bye"]

# Short answers (CPU-friendly)
MAX_ASSISTANT_WORDS = 30
OLLAMA_NUM_PREDICT = 80
OLLAMA_TEMPERATURE = 0.4

# Piper TTS Configuration
PIPER_MODEL_PATH = "models/piper/en_US-lessac-medium.onnx"
AUDIO_OUTPUT_DIR = "audios"

# VAD settings
FRAME_MS = 20                  # must be 10/20/30ms
VAD_AGGRESSIVENESS = 2         # 0..3 (higher = more aggressive)
PRE_ROLL_MS = 300              # keep a bit before speech starts
END_SILENCE_MS = 500           # end utterance after this much silence
MAX_UTT_SLEEP_SEC = 3.0        # wake phrase utterances are short
MAX_UTT_ACTIVE_SEC = 20.0

# We require a VAD-supported rate; try these in order.
VAD_SUPPORTED_RATES = [16000, 48000, 32000, 8000]

# Auto sleep after inactivity in ACTIVE mode
ACTIVE_IDLE_TIMEOUT_SEC = 60


# =========================
# TEXT HELPERS
# =========================

def normalize_text(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def contains_phrase(text: str, phrases: List[str]) -> bool:
    t = normalize_text(text)
    return any(p in t for p in phrases)


def clamp_words(text: str, max_words: int) -> str:
    words = text.strip().split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()


# =========================
# OLLAMA (NON-STREAMING)
# =========================

def ollama_chat_once(messages: List[Dict]) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": OLLAMA_NUM_PREDICT,
            "temperature": OLLAMA_TEMPERATURE,
            "num_ctx": 512,
        },
    }

    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=600)
    r.raise_for_status()
    data = r.json()

    if isinstance(data.get("message"), dict):
        text = data["message"].get("content") or ""
    else:
        text = data.get("response") or ""

    return text.strip()


# =========================
# TTS WORKER (SAVE FULL WAV)
# =========================

class TTSWorker(threading.Thread):
    def __init__(self, output_dir: str):
        super().__init__(daemon=True)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.q: "queue.Queue[str]" = queue.Queue(maxsize=50)
        self._stop_event = threading.Event()
        self._ready = False
        self._voice = None
        self._counter = 0

    def stop(self):
        self._stop_event.set()
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

        from piper.voice import PiperVoice

        model_path = Path(PIPER_MODEL_PATH)
        config_path = Path(f"{PIPER_MODEL_PATH}.json")

        print(f"[TTS] Loading Piper model from {model_path.resolve()}...", flush=True)
        if not model_path.exists():
            raise FileNotFoundError(f"Piper model not found: {model_path}")
        if not config_path.exists():
            raise FileNotFoundError(f"Piper config not found: {config_path}")

        self._voice = PiperVoice.load(str(model_path))
        if not hasattr(self._voice, "synthesize_wav"):
            raise AttributeError(
                "Your installed PiperVoice does not have synthesize_wav(). "
                "Please upgrade piper-tts or use a matching version."
            )

        self._ready = True
        sample_rate = getattr(getattr(self._voice, "config", None), "sample_rate", "unknown")
        print(f"[TTS] Ready. sample_rate={sample_rate}", flush=True)

    def _next_path(self) -> Path:
        self._counter += 1
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.output_dir / f"tts_{stamp}_{self._counter:03d}.wav"

    def _save_text_as_wav(self, text: str):
        self._lazy_init()
        out_path = self._next_path()
        print(f"[TTS] Synthesizing to {out_path} ...", flush=True)

        with open(out_path, "wb") as raw_f:
            import wave
            with wave.open(raw_f, "wb") as wav_file:
                self._voice.synthesize_wav(text, wav_file)

        size_bytes = out_path.stat().st_size
        print(f"[TTS] Saved {out_path} ({size_bytes} bytes)", flush=True)

        try:
            import wave
            with wave.open(str(out_path), "rb") as wav_file:
                channels = wav_file.getnchannels()
                rate = wav_file.getframerate()
                frames = wav_file.getnframes()
                duration = frames / float(rate) if rate else 0.0
            print(
                f"[TTS] WAV info: channels={channels}, rate={rate}, frames={frames}, seconds={duration:.2f}",
                flush=True,
            )
        except Exception:
            print("[TTS] Warning: could not inspect saved wav", flush=True)
            traceback.print_exc()

    def run(self):
        while not self._stop_event.is_set():
            text = self.q.get()
            if self._stop_event.is_set():
                break
            if not text:
                continue

            try:
                self._save_text_as_wav(text)
            except Exception as e:
                print(f"[TTS] Error: {e}", flush=True)
                traceback.print_exc()


# =========================
# VAD-GATED VOSK UTTERANCE CAPTURE
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
        self.frame_bytes = self.frame_samples * 2  # int16 mono

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

    def step(
        self,
        frame: bytes,
        rec: KaldiRecognizer,
        max_utt_sec: float,
        want_partial: bool,
    ) -> CaptureOut:
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
    mode: str  # "SLEEP" or "ACTIVE"
    last_activity: float


class VoiceAssistant:
    def __init__(self):
        self.state = State(mode="SLEEP", last_activity=time.time())
        self.audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=400)
        self.tts = TTSWorker(AUDIO_OUTPUT_DIR)
        self.tts.start()

        self.sample_rate = self._pick_input_rate()
        self.frame_samples = int(self.sample_rate * FRAME_MS / 1000)
        self.frame_bytes = self.frame_samples * 2

        print(f"[INIT] Using input sample rate: {self.sample_rate}", flush=True)
        try:
            print(f"[MIC] Default input device info: {sd.query_devices(None, "input")}", flush=True)
        except Exception:
            pass
        self.vosk_model = Model(VOSK_MODEL_PATH)
        self._make_recognizers()

        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.capture = VadVoskCapture(self.vad, self.sample_rate, FRAME_MS)

        self.messages: List[Dict] = [
            {
                "role": "system",
                "content": (
                    "You are an educational voice assistant for kids. "
                    "Be friendly, clear, and concise. "
                    f"Answer in at most {MAX_ASSISTANT_WORDS} words. "
                    "If unsure, ask one short question."
                ),
            }
        ]

    def _pick_input_rate(self) -> int:
        for sr in VAD_SUPPORTED_RATES:
            try:
                sd.check_input_settings(device=MIC_DEVICE, samplerate=sr, channels=1, dtype="int16")
                return sr
            except Exception:
                continue

        info = sd.query_devices(MIC_DEVICE, "input")
        sr = int(info["default_samplerate"])
        if sr not in VAD_SUPPORTED_RATES:
            raise RuntimeError(
                f"Mic sample rate {sr} not supported by WebRTC VAD. "
                f"Use one of {VAD_SUPPORTED_RATES}."
            )
        return sr

    def _make_recognizers(self):
        wake_grammar = json.dumps(WAKE_WORDS)
        self.rec_wake = KaldiRecognizer(self.vosk_model, self.sample_rate, wake_grammar)
        self.rec_full = KaldiRecognizer(self.vosk_model, self.sample_rate)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"[MIC] {status}", flush=True)

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
        print("[STATE] -> SLEEP", flush=True)

    def _enter_active(self):
        self.state.mode = "ACTIVE"
        self.state.last_activity = time.time()
        self._make_recognizers()
        self.capture.reset()
        print("[STATE] -> ACTIVE", flush=True)
        self.tts.say(GREETING)

    def _respond_with_llm(self, user_text: str):
        self.messages.append({"role": "user", "content": user_text})
        self._trim_history()

        print(f"[USER] {user_text}", flush=True)

        try:
            assistant_full = ollama_chat_once(self.messages)
            assistant_full = clamp_words(assistant_full, MAX_ASSISTANT_WORDS)
            if not assistant_full:
                assistant_full = "Sorry, I could not generate a response."
        except Exception as e:
            print(f"[LLM] Error: {e}", flush=True)
            traceback.print_exc()
            assistant_full = "Sorry, I had trouble answering that."

        print(f"[ASSISTANT] {assistant_full}", flush=True)
        self.messages.append({"role": "assistant", "content": assistant_full})
        self._trim_history()
        self.tts.say(assistant_full)

    def run_forever(self):
        print("==============================================", flush=True)
        print("Assistant running (VAD + wake + full LLM + Piper synthesize_wav).", flush=True)
        print(f"Input sample rate: {self.sample_rate} Hz | Frame: {FRAME_MS} ms", flush=True)
        print(f"Wake words: {WAKE_WORDS}", flush=True)
        print("Audio will be saved to ./audios/", flush=True)
        print("Press Ctrl+C to exit.", flush=True)
        print("==============================================", flush=True)

        stream_kwargs = dict(
            samplerate=self.sample_rate,
            blocksize=self.frame_samples,
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
        )
        if USE_EXPLICIT_MIC_DEVICE:
            stream_kwargs["device"] = MIC_DEVICE
            print(f"[MIC] Using explicit input device: {MIC_DEVICE}", flush=True)
        else:
            print("[MIC] Using default input device", flush=True)

        with sd.RawInputStream(**stream_kwargs):
            try:
                while True:
                    if self.state.mode == "ACTIVE" and (time.time() - self.state.last_activity) > ACTIVE_IDLE_TIMEOUT_SEC:
                        self.tts.say("I'll wait. Say hey box if you need me.")
                        self._enter_sleep()

                    frame = self.audio_q.get()

                    if self.state.mode == "SLEEP":
                        out = self.capture.step(
                            frame=frame,
                            rec=self.rec_wake,
                            max_utt_sec=MAX_UTT_SLEEP_SEC,
                            want_partial=True,
                        )
                        if out.partial and contains_phrase(out.partial, WAKE_WORDS):
                            print(f"[STT partial] {out.partial}", flush=True)
                            self._enter_active()
                            continue
                        if out.final and contains_phrase(out.final, WAKE_WORDS):
                            print(f"[STT] {out.final}", flush=True)
                            self._enter_active()
                            continue

                    else:
                        out = self.capture.step(
                            frame=frame,
                            rec=self.rec_full,
                            max_utt_sec=MAX_UTT_ACTIVE_SEC,
                            want_partial=False,
                        )
                        if out.final:
                            user_text = out.final.strip()
                            if user_text:
                                print(f"[STT] {user_text}", flush=True)
                                self.state.last_activity = time.time()
                                if contains_phrase(user_text, SLEEP_PHRASES):
                                    self.tts.say("Okay. Say hey box if you need me.")
                                    self._enter_sleep()
                                else:
                                    self._respond_with_llm(user_text)
                                    self.rec_full = KaldiRecognizer(self.vosk_model, self.sample_rate)

            except KeyboardInterrupt:
                print("\nExiting...", flush=True)
            finally:
                self.tts.stop()


if __name__ == "__main__":
    os.makedirs(AUDIO_OUTPUT_DIR, exist_ok=True)
    VoiceAssistant().run_forever()
