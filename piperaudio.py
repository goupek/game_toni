import json
import traceback
import os
import queue
import threading
import time
import re
import subprocess
import numpy as np
from collections import deque
from dataclasses import dataclass
from typing import List, Dict, Optional

import requests
import sounddevice as sd
import webrtcvad

from faster_whisper import WhisperModel

# =========================
# CONFIGURATION
# =========================
MIC_DEVICE = 24  # Update to your specific microphone ID on the Jetson

# --- GPU / Whisper STT Configuration ---
# Model size options: "tiny", "base", "small", "medium", "large-v2", "large-v3"
# For Jetson Orin with limited VRAM, "small" or "base" is recommended.
# Set device="cuda" to use GPU, device="cpu" to fall back to CPU.
WHISPER_MODEL_SIZE = "tiny"
WHISPER_DEVICE     = "cuda"          # "cuda" | "cpu"
WHISPER_COMPUTE    = "int8"       # "float16" for GPU, "int8" for CPU
WHISPER_LANGUAGE   = "en"            # Primary expected language (helps accuracy)

# Ollama (server must be running; it uses GPU automatically if configured)
OLLAMA_URL   = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:0.5b"

# Wake words & commands
WAKE_WORDS    = ["hey box", "okay box", "hi box", "box box", "Брузер"]
# GREETING      = "Hi, how can I help you?"
GREETING      = "Привет, чем я могу тебе помочь?"
SLEEP_PHRASES = ["go to sleep", "sleep", "stop listening", "goodbye", "bye"]

# LLM Limits
MAX_ASSISTANT_WORDS = 150
OLLAMA_NUM_PREDICT  = 80
OLLAMA_TEMPERATURE  = 0.4
OLLAMA_NUM_CTX      = 512

# Piper TTS Configuration
PIPER_EXEC_PATH  = "piper"
PIPER_MODEL_PATH = "models/piper/ru_RU-irina-medium.onnx"

# VAD settings
FRAME_MS              = 20
VAD_AGGRESSIVENESS    = 2
PRE_ROLL_MS           = 300
END_SILENCE_MS        = 600       # slightly longer to avoid cutting Whisper off
MAX_UTT_SLEEP_SEC     = 3.0
MAX_UTT_ACTIVE_SEC    = 20.0
VAD_SUPPORTED_RATES   = [16000, 48000, 32000, 8000]
WHISPER_INTERNAL_RATE = 16000     # Whisper always needs 16 kHz
ACTIVE_IDLE_TIMEOUT_SEC = 60

# =========================
# TEXT HELPERS
# =========================
def normalize_text(s: str) -> str:
    s = s.lower().strip()
    return re.sub(r"\s+", " ", s)

def contains_phrase(text: str, phrases: List[str]) -> bool:
    t = normalize_text(text)
    return t in WAKE_WORDS

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
    def __init__(self):
        self.lock  = threading.Lock()
        self.active = threading.Event()

# =========================
# TTS WORKER (STREAM DIRECT TO APLAY)
# =========================
class TTSWorker(threading.Thread):
    def __init__(self, audio_tracker: AudioStateTracker):
        super().__init__(daemon=True)
        self.audio_tracker = audio_tracker
        self.q: "queue.Queue[str]" = queue.Queue(maxsize=50)
        self._stop  = threading.Event()
        self._ready = False
        self._model = None # Silero TTS
        self._sr = 48000 # Silero TTS
        self._speaker = "xenia"  # options: aidar, baya, kseniya, xenia, eugene

    def stop(self):
        self._stop.set()
        try:
            self.q.put_nowait("")
        except queue.Full:
            pass

    def say(self, text: str):
        text = text.strip()
        if text:
            print(f"[TTS] Queued: {text!r}")
            self.q.put(text)


    # def _lazy_init(self):
    #     if self._ready:
    #         return
    #     if not os.path.exists(PIPER_MODEL_PATH):
    #         print(f"[TTS Error] Could not find Piper model at {PIPER_MODEL_PATH}")
    #         return
    #     self._ready = True
    #     print("[TTS] CLI Ready.")

    def _lazy_init(self):
        if self._model is not None:
            return
        print("[TTS] Loading Silero v5...")
        import torch
        local_file = "models/silero/v5_ru.pt"
        device = torch.device("cpu")  # keep CPU, save GPU for LLM+STT
        self._model = torch.package.PackageImporter(local_file).load_pickle("tts_models", "model")
        self._model.to(device)
        print("[TTS] Silero v5 ready.")

    """Synthesize function for Silero TTS"""
    def _synthesize_and_play(self, text: str):
            self._lazy_init()
            try:
                self.audio_tracker.active.set()
                print(f"[TTS] Synthesizing: {text!r}")
                import torch
                audio = self._model.apply_tts(
                    text=text,
                    speaker=self._speaker,
                    sample_rate=self._sr
                )
                # audio is a torch tensor, convert to numpy
                wav = audio.numpy()
                proc = subprocess.Popen(
                    ["aplay", "-q", "-r", str(self._sr), "-f", "FLOAT_LE", "-c", "1", "-"],
                    stdin=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                proc.communicate(input=wav.tobytes())
            except Exception as e:
                print(f"[TTS ERROR] {e}")
                traceback.print_exc()
            finally:
                self.audio_tracker.active.clear()
                print("[TTS] Mic unmuted.")

    """Synthesize function for piper CLI"""
    # def _synthesize_and_play(self, text: str):
    #     self._lazy_init()
    #     try:
    #         self.audio_tracker.active.set()
    #         print("[TTS] Synthesizing and playing instantly...")

    #         aplay_process = subprocess.Popen(
    #             ["aplay", "-q", "-"],
    #             stdin=subprocess.PIPE,
    #             stderr=subprocess.DEVNULL
    #         )
    #         piper_process = subprocess.Popen(
    #             [PIPER_EXEC_PATH, "--model", PIPER_MODEL_PATH],
    #             stdin=subprocess.PIPE,
    #             stdout=aplay_process.stdin,
    #             stderr=subprocess.PIPE
    #         )
    #         _, stderr_data = piper_process.communicate(input=text.encode("utf-8"))
    #         aplay_process.stdin.close()
    #         aplay_process.wait()

    #         if piper_process.returncode != 0:
    #             print(f"[TTS CLI Error]: {stderr_data.decode('utf-8')}")
    #         else:
    #             print("[TTS] Finished speaking.")
    #     except FileNotFoundError:
    #         print(f"[TTS Error]: Could not find '{PIPER_EXEC_PATH}' or 'aplay'.")
    #     except Exception as e:
    #         print(f"[TTS Error]: {e}")
    #         traceback.print_exc()
    #     finally:
    #         self.audio_tracker.active.clear()

    def run(self):
        while not self._stop.is_set():
            text = self.q.get()
            if self._stop.is_set():
                break
            if not text:
                continue
            try:
                self._synthesize_and_play(text)
            except Exception as e:
                print(f"[TTS] Error: {e}")
                traceback.print_exc()

# =========================
# GPU-ACCELERATED WHISPER STT
# =========================
class WhisperSTT:
    """
    Wraps faster-whisper on CUDA.
    Call transcribe(pcm_int16_bytes, sample_rate) → str
    """
    def __init__(self):
        print(f"[Whisper] Loading model '{WHISPER_MODEL_SIZE}' on {WHISPER_DEVICE} ({WHISPER_COMPUTE})…")
        self.model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
        print("[Whisper] Model loaded.")

    def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        # Convert raw int16 PCM → float32 normalised [-1, 1] at 16 kHz
        audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Resample to 16 kHz if the mic runs at a different rate
        if sample_rate != WHISPER_INTERNAL_RATE:
            ratio   = WHISPER_INTERNAL_RATE / sample_rate
            new_len = int(len(audio_np) * ratio)
            audio_np = np.interp(
                np.linspace(0, len(audio_np) - 1, new_len),
                np.arange(len(audio_np)),
                audio_np,
            ).astype(np.float32)

        segments, _ = self.model.transcribe(
            audio_np,
            # language=WHISPER_LANGUAGE,
            beam_size=3,
            vad_filter=False,                # Whisper's built-in VAD filter
            vad_parameters={"min_silence_duration_ms": 300},
        )
        return " ".join(s.text for s in segments).strip()

# =========================
# VAD-BASED AUDIO CAPTURE
# Collects raw PCM frames while speech is detected,
# then hands the whole utterance to Whisper.
# =========================
class VadCapture:
    """
    Accumulates audio frames using WebRTC-VAD.
    Returns a complete utterance (raw bytes) when silence is detected.
    """
    def __init__(self, vad: webrtcvad.Vad, sr: int, frame_ms: int):
        self.vad              = vad
        self.sr               = sr
        self.frame_ms         = frame_ms
        self.frame_samples    = int(sr * frame_ms / 1000)
        self.frame_bytes      = self.frame_samples * 2
        self.pre_roll_frames  = max(1, int(PRE_ROLL_MS / frame_ms))
        self.end_silence_frm  = max(1, int(END_SILENCE_MS / frame_ms))
        self.pre              = deque(maxlen=self.pre_roll_frames)
        self.triggered        = False
        self.silence          = 0
        self.start_time       = 0.0
        self.buf: List[bytes] = []

    def reset(self):
        self.pre.clear()
        self.triggered = False
        self.silence   = 0
        self.start_time = 0.0
        self.buf       = []

    def feed(self, frame: bytes, max_utt_sec: float) -> Optional[bytes]:
        """
        Feed one VAD frame.
        Returns the complete utterance as raw PCM bytes when done, else None.
        """
        if len(frame) != self.frame_bytes:
            return None

        is_speech = self.vad.is_speech(frame, self.sr)

        if not self.triggered:
            self.pre.append(frame)
            if is_speech:
                self.triggered  = True
                self.silence    = 0
                self.start_time = time.time()
                self.buf        = list(self.pre) + [frame]
                self.pre.clear()
            return None

        self.buf.append(frame)
        if is_speech:
            self.silence = 0
        else:
            self.silence += 1

        too_long = (time.time() - self.start_time) >= max_utt_sec
        ended    = (self.silence >= self.end_silence_frm) or too_long

        if ended:
            result = b"".join(self.buf)
            self.reset()
            return result

        return None

# =========================
# MAIN ASSISTANT
# =========================
@dataclass
class State:
    mode: str
    last_activity: float

class VoiceAssistant:
    def __init__(self):
        self.state         = State(mode="SLEEP", last_activity=time.time())
        self.audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=400)
        self.audio_tracker = AudioStateTracker()
        self.tts           = TTSWorker(self.audio_tracker)
        self.tts.start()

        self.sample_rate   = 32000
        self.frame_samples = int(self.sample_rate * FRAME_MS / 1000)
        self.frame_bytes   = self.frame_samples * 2

        # GPU STT
        self.whisper = WhisperSTT()

        # VAD
        self.vad     = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.capture = VadCapture(self.vad, self.sample_rate, FRAME_MS)

        self.messages: List[Dict] = [
            {"role": "system",
             "content": (
                 "You are an educational voice assistant for kids. "
                 "Always respond in Russian. "
                 "Be friendly, clear, and concise. "
                 f"Answer in at most {MAX_ASSISTANT_WORDS} words. "
                 "If unsure, ask one short question in Russian."
             )}
        ]
        self.mic_gate_until = 0.0

    # ------------------------------------------------------------------
    def _pick_input_rate(self) -> int:
        for sr in VAD_SUPPORTED_RATES:
            try:
                sd.check_input_settings(device=MIC_DEVICE, samplerate=sr, channels=1, dtype="int16")
                return sr
            except Exception:
                continue
        info = sd.query_devices(None, "input")
        sr   = int(info["default_samplerate"])
        if sr not in VAD_SUPPORTED_RATES:
            raise RuntimeError(f"Mic sample rate {sr} not supported. Use one of {VAD_SUPPORTED_RATES}.")
        return sr

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
        rest    = self.messages[1:]
        if len(rest) > keep_last_pairs * 2:
            self.messages = sys_msg + rest[-keep_last_pairs * 2:]

    def _enter_sleep(self):
        self.state.mode = "SLEEP"
        self.state.last_activity = time.time()
        self.capture.reset()
        print("[STATE] -> SLEEP")

    def _enter_active(self):
        self.state.mode = "ACTIVE"
        self.state.last_activity = time.time()
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
                assistant_full = "Извини, не смог ответить."
            self.tts.say(assistant_full)
        except Exception as e:
            print(f"[LLM] Error: {e}")
            assistant_full = "Извини, не смог ответить."
            self.tts.say(assistant_full)

        print(f"[ASSISTANT] {assistant_full}")
        self.messages.append({"role": "assistant", "content": assistant_full})
        self._trim_history()
        self.mic_gate_until = time.time() + 0.15

    # ------------------------------------------------------------------
    def _transcribe_utterance(self, pcm_bytes: bytes) -> str:
        """Run Whisper on collected audio. Runs on GPU."""
        try:
            text = self.whisper.transcribe(pcm_bytes, self.sample_rate)
            return text
        except Exception as e:
            print(f"[Whisper] Transcription error: {e}")
            traceback.print_exc()
            return ""

    # ------------------------------------------------------------------
    def run_forever(self):
        print("==============================================")
        print("Assistant running (Whisper GPU + Piper TTS).")
        print(f"Input sample rate : {self.sample_rate} Hz | Frame: {FRAME_MS} ms")
        print(f"Wake words        : {WAKE_WORDS}")
        print(f"STT device        : {WHISPER_DEVICE} | compute: {WHISPER_COMPUTE}")
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
                    # Auto-sleep after idle timeout
                    if (self.state.mode == "ACTIVE" and
                            (time.time() - self.state.last_activity) > ACTIVE_IDLE_TIMEOUT_SEC):
                        self.tts.say("Я подожду. Скажи 'hey box', если понадоблюсь.")
                        self._enter_sleep()

                    frame = self.audio_q.get()

                    # ---- SLEEP mode: listen only for wake word ----
                    if self.state.mode == "SLEEP":
                        pcm = self.capture.feed(frame, MAX_UTT_SLEEP_SEC)
                        if pcm is not None:
                            text = self._transcribe_utterance(pcm)
                            print(f"[STT-wake] {text.lower().strip('.!?, ').capitalize()!r}")
                            if text.lower().strip('.!?, ').capitalize() in WAKE_WORDS:
                                print("WAKE WOD FOUND")
                                self._enter_active()
                                self.mic_gate_until = time.time() + 0.2

                    # ---- ACTIVE mode: capture full utterance ----
                    else:
                        pcm = self.capture.feed(frame, MAX_UTT_ACTIVE_SEC)
                        if pcm is not None:
                            text = self._transcribe_utterance(pcm).strip()
                            if text:
                                print(f"[STT] {text!r}")
                                self.state.last_activity = time.time()
                                if contains_phrase(text, SLEEP_PHRASES):
                                    self.tts.say("Хорошо. Скажи 'hey box', если понадоблюсь.")
                                    self._enter_sleep()
                                else:
                                    self._respond_with_llm(text)

            except KeyboardInterrupt:
                print("\nExiting…")
            finally:
                self.tts.stop()


if __name__ == "__main__":
    VoiceAssistant().run_forever()