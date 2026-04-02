import io
import wave
import json
import traceback
import tempfile
import os
import queue
import threading
import time
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Iterable, Optional
import numpy as np
import requests
import sounddevice as sd
import webrtcvad
from vosk import Model, KaldiRecognizer


# =========================
# CONFIG
# =========================
MIC_DEVICE = 24

# Vosk model folder
VOSK_MODEL_PATH = "models/vosk/vosk-model-small-en-us-0.15"

# Ollama (server must be running)
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:0.5b"

# Wake words (keep them simple)
WAKE_WORDS = ["hey box", "okay box", "hi box","box box"]
GREETING = "Hi, how can I help you?"
SLEEP_PHRASES = ["go to sleep", "sleep", "stop listening", "goodbye", "bye"]

# Short answers (CPU-friendly)
MAX_ASSISTANT_WORDS = 30
OLLAMA_NUM_PREDICT = 80
OLLAMA_TEMPERATURE = 0.4

# Micro-chunking for TTS
WORDS_PER_TTS_CHUNK = 8

# Piper TTS Configuration
PIPER_MODEL_PATH = "models/piper/en_US-lessac-medium.onnx"
TTS_OUTPUT_DIR = "audios"

# VAD settings
FRAME_MS = 20                  # must be 10/20/30ms
VAD_AGGRESSIVENESS = 2          # 0..3 (higher = more aggressive)
PRE_ROLL_MS = 300               # keep a bit before speech starts
END_SILENCE_MS = 500            # end utterance after this much silence
MAX_UTT_SLEEP_SEC = 3.0         # wake phrase utterances are short
MAX_UTT_ACTIVE_SEC = 20.0

# We require a VAD-supported rate; try these in order.
# Strongly prefer 16k for Vosk English models.
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
# OLLAMA STREAMING
# =========================

def ollama_chat_stream(messages: List[Dict]) -> Iterable[str]:
    """
    Streams small text deltas from Ollama /api/chat (NDJSON lines).
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "options": {
            "num_predict": OLLAMA_NUM_PREDICT,
            "temperature": OLLAMA_TEMPERATURE,
            "num_ctx": 512, # Kept this to save Jetson RAM
        },
    }
    with requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True, timeout=600) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            data = json.loads(line)

            # Modern format: {"message": {"role":"assistant","content":"..."}, ...}
            if isinstance(data.get("message"), dict):
                chunk = data["message"].get("content") or ""
            else:
                # Fallback older format
                chunk = data.get("response") or ""

            if chunk:
                yield chunk

            if data.get("done"):
                break


def ollama_chat_once(messages: List[Dict]) -> str:
    """
    Gets one complete response from Ollama /api/chat without streaming.
    """
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
        return (data["message"].get("content") or "").strip()

    return (data.get("response") or "").strip()


def llm_stream_to_tts_chunks(stream_iter: Iterable[str],
                            words_per_chunk: int,
                            max_words: int) -> Iterable[str]:
    """
    Convert Ollama deltas into small, speakable chunks.
    """
    buf = ""
    spoken = 0

    for delta in stream_iter:
        buf += delta

        # If we have enough words, emit chunks
        while spoken < max_words:
            words = buf.strip().split()
            if len(words) < words_per_chunk:
                break
            take = min(words_per_chunk, max_words - spoken)
            chunk = " ".join(words[:take]).strip()
            if chunk:
                yield chunk
                spoken += take
            # keep remaining
            remaining = words[take:]
            buf = (" ".join(remaining) + " ") if remaining else ""

        if spoken >= max_words:
            return

        # Sentence boundary flush (if short enough)
        if re.search(r"[.!?]\s*$", buf) and buf.strip():
            words = buf.strip().split()
            take = min(len(words), max_words - spoken)
            chunk = " ".join(words[:take]).strip()
            if chunk:
                yield chunk
                spoken += take
            buf = ""
            if spoken >= max_words:
                return

    # Flush remainder
    if spoken < max_words and buf.strip():
        words = buf.strip().split()
        take = min(len(words), max_words - spoken)
        chunk = " ".join(words[:take]).strip()
        if chunk:
            yield chunk


# =========================
# AUDIO SAVER (NO PLAYBACK)
# =========================

class AudioSaver:
    """
    Saves TTS output as .wav files instead of playing it.
    """
    def __init__(self, output_dir: str = TTS_OUTPUT_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.file_counter = 0
        self.active = threading.Event()

    def start(self, sr: int):
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def stop(self):
        self.active.clear()

    def add_audio(self, wav: np.ndarray, sr: int, text: str = "") -> str:
        if wav.ndim > 1:
            wav = wav[:, 0]

        wav = np.clip(wav.astype(np.float32, copy=False), -1.0, 1.0)
        wav_int16 = (wav * 32767.0).astype(np.int16)

        text_slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip()).strip("_")[:40]
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        with self.lock:
            self.file_counter += 1
            filename = f"tts_{timestamp}_{self.file_counter:04d}"
            if text_slug:
                filename += f"_{text_slug}"
            out_path = self.output_dir / f"{filename}.wav"

            self.active.set()
            try:
                with wave.open(str(out_path), "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sr)
                    wav_file.writeframes(wav_int16.tobytes())
            finally:
                self.active.clear()

        print(f"[TTS] Saved audio to {out_path}")
        return str(out_path)


# =========================
# TTS WORKER (PIPER TTS)
# =========================

class TTSWorker(threading.Thread):
    def __init__(self, audio_saver: AudioSaver):
        super().__init__(daemon=True)
        self.audio_saver = audio_saver
        self.q: "queue.Queue[str]" = queue.Queue(maxsize=50)
        self._stop = threading.Event()
        self._ready = False
        self._voice = None

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
        from piper.voice import PiperVoice
        print(f"[TTS] Loading Piper model from {PIPER_MODEL_PATH}...")
        self._voice = PiperVoice.load(PIPER_MODEL_PATH)
        self._ready = True
        print("[TTS] Ready.")

    def _save_pcm_bytes(self, audio_bytes: bytes, sr: int, text: str):
        wav_int16 = np.frombuffer(audio_bytes, dtype=np.int16).copy()
        wav_float32 = wav_int16.astype(np.float32) / 32768.0
        self.audio_saver.add_audio(wav_float32, sr, text=text)

    def _synthesize_and_save(self, text: str):
        self._lazy_init()
        sr = getattr(getattr(self._voice, "config", None), "sample_rate", 22050)

        # Prefer whole-utterance synthesis so each assistant reply becomes one WAV.
        if hasattr(self._voice, "synthesize"):
            print("[TTS] Using PiperVoice.synthesize for full audio")
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                    tmp_path = tmp_file.name

                with wave.open(tmp_path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sr)
                    self._voice.synthesize(text, wav_file)

                with wave.open(tmp_path, "rb") as wav_file:
                    raw = wav_file.readframes(wav_file.getnframes())
                    file_sr = wav_file.getframerate()

                self._save_pcm_bytes(raw, file_sr, text)
                return
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

        # Fallback: collect all raw PCM chunks first, then save once.
        if hasattr(self._voice, "synthesize_stream_raw"):
            print("[TTS] Using PiperVoice.synthesize_stream_raw collected into one file")
            audio_bytes = b"".join(self._voice.synthesize_stream_raw(text))
            if not audio_bytes:
                raise RuntimeError("Piper returned empty audio bytes")
            self._save_pcm_bytes(audio_bytes, sr, text)
            return

        if hasattr(self._voice, "synthesize_ids_to_raw"):
            print("[TTS] Using PiperVoice.synthesize_ids_to_raw collected into one file")
            phoneme_ids = self._voice.phonemize(text)
            audio_bytes = b"".join(self._voice.synthesize_ids_to_raw(phoneme_ids))
            if not audio_bytes:
                raise RuntimeError("Piper returned empty audio bytes")
            self._save_pcm_bytes(audio_bytes, sr, text)
            return

        raise RuntimeError("No known synthesis method found on PiperVoice")

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
        self.frame_bytes = self.frame_samples * 2  # int16

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

    def step(self,
             frame: bytes,
             rec: KaldiRecognizer,
             max_utt_sec: float,
             want_partial: bool) -> CaptureOut:
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
    mode: str  # "SLEEP" or "ACTIVE"
    last_activity: float

class VoiceAssistant:
    def __init__(self):
        self.state = State(mode="SLEEP", last_activity=time.time())
        self.audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=400)
        self.audio_out = AudioSaver()
        self.tts = TTSWorker(self.audio_out)
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
            print(status)
        if self.audio_out.active.is_set() or time.time() < self.mic_gate_until:
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

    def _handle_user_text(self, text: str):
        text = (text or "").strip()
        if not text:
            return

        print(f"[USER] {text}")
        self.state.last_activity = time.time()

        if contains_phrase(text, SLEEP_PHRASES):
            self.tts.say("Okay. Say 'hey box' if you need me.")
            self._enter_sleep()
            return

        self.messages.append({"role": "user", "content": text})
        self._trim_history()

        assistant_full = ""
        try:
            stream = ollama_chat_stream(self.messages)
            for chunk in llm_stream_to_tts_chunks(
                stream_iter=stream,
                words_per_chunk=WORDS_PER_TTS_CHUNK,
                max_words=MAX_ASSISTANT_WORDS,
            ):
                self.tts.say(chunk)

        except Exception as e:
            print(f"[LLM] Error: {e}")
            self.tts.say("Sorry, I had trouble answering that.")
            assistant_full = "Sorry, I had trouble answering that."

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
        print("Assistant running (VAD + wake + full LLM reply + saving one TTS WAV per reply).")
        print(f"Input sample rate: {self.sample_rate} Hz | Frame: {FRAME_MS} ms")
        print(f"Wake words: {WAKE_WORDS}")
        print(f"TTS output directory: {TTS_OUTPUT_DIR}")
        print("Press Ctrl+C to exit.")
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
                            frame=frame,
                            rec=self.rec_wake,
                            max_utt_sec=MAX_UTT_SLEEP_SEC,
                            want_partial=True,
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

                    else:  # ACTIVE
                        out = self.capture.step(
                            frame=frame,
                            rec=self.rec_full,
                            max_utt_sec=MAX_UTT_ACTIVE_SEC,
                            want_partial=False,
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
                self.audio_out.stop()


if __name__ == "__main__":
    VoiceAssistant().run_forever()