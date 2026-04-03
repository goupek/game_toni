import io
import traceback
import os
import queue
import threading
import time
import re
import subprocess
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from transliterate import translit

import torch
torch.cuda.empty_cache()
import sounddevice as sd
import webrtcvad
import numpy as np
from faster_whisper import WhisperModel

from memory_bridge import PipelineMemoryBridge

# =========================
# CONFIGURATION
# =========================
MIC_DEVICE = 24

WAKE_WORDS = ["hey box", "okay box", "hi box", "box box"]
GREETING = "Привет, чем я могу тебе помочь?"
SLEEP_PHRASES = ["go to sleep", "sleep", "stop listening", "goodbye", "bye"]

LLAMA_NUM_PREDICT = 80
LLAMA_TEMPERATURE = 0.5
LLAMA_NUM_CTX = 512
PIPELINE_LLM_MODEL = ".../models/gemma/gemma-3-4b-it-q4_k_m7B"

SILERO_MODEL_PATH = "models/silero/v5_ru.pt"
SILERO_SPEAKER = "xenia"
SILERO_SAMPLE_RATE = 8000

# Whisper config
WHISPER_MODEL_SIZE = "tiny"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE = "float16"
WHISPER_LANGUAGE = None   # set "ru" if your wake word / speech is Russian
WHISPER_SAMPLE_RATE = 16000

FRAME_MS = 20
VAD_AGGRESSIVENESS = 2
PRE_ROLL_MS = 300
END_SILENCE_MS = 500
MAX_UTT_SLEEP_SEC = 3.0
MAX_UTT_ACTIVE_SEC = 20.0
VAD_SUPPORTED_RATES = [16000, 48000, 32000, 8000]
ACTIVE_IDLE_TIMEOUT_SEC = 60
WAKE_MIC_GATE_SEC = 0.5

_ACTIONABLE_TEXT_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]")

BOXY_SYSTEM_PROMPT = (
    "You are Boxy, a warm and encouraging Russian language tutor for English speakers. "
    "The user speaks English. You ALWAYS reply in Russian only, using Cyrillic script. "
    "Never use Latin letters or transliteration in your response. "
    "\n\n"
    "YOUR PERSONALITY: "
    "Patient, playful, and enthusiastic. Celebrate every attempt. "
    "If the user tries a Russian word, praise them. "
    "If they make a mistake, correct gently: say the right version once, then move on. "
    "\n\n"
    "RESPONSE LENGTH: "
    "Always reply in 2 to 5 sentences. Never more, never less. "
    "Each sentence must be short, under 12 words. "
    "\n\n"
    "STRICT OUTPUT RULES: "
    "1. Plain Cyrillic text only. No lists, bullet points, numbers, colons, dashes, asterisks, markdown, or emojis. "
    "2. Never explain grammar rules or use linguistic terms like nominative or accusative. "
    "3. Never say a word means itself. "
    "4. Never repeat the English word back if the user said it in English. "
    "5. If you do not understand, ask one simple clarifying question in Russian. "
    "6. Never answer in English, even if the user writes in English. "
    "\n\n"
    "RESPONSE PATTERNS: "
    "For translation requests, give the Russian word, one short example, and invite repetition. "
    "For yes or no questions, answer directly first, then one example. "
    "For greetings or small talk, answer warmly and invite a short practice turn. "
    "For unclear input, say you did not understand and ask them to repeat."
)

# =========================
# TEXT HELPERS
# =========================
def normalize_text(s: str) -> str:
    s = s.lower().strip()
    return re.sub(r"\s+", " ", s)

def contains_phrase(text: str, phrases: List[str]) -> bool:
    t = normalize_text(text)
    return any(normalize_text(p) in t for p in phrases)

def russify_text(text: str) -> str:
    def replace_english(match):
        word = match.group(0)
        try:
            return translit(word, 'ru')
        except Exception:
            return word
    return re.sub(r'[a-zA-Z]+', replace_english, text)

def split_tts_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def is_actionable_user_text(text: str) -> bool:
    return bool(_ACTIONABLE_TEXT_RE.search((text or "").strip()))

# =========================
# AUDIO TRACKER
# =========================
class AudioStateTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = threading.Event()

# =========================
# TTS WORKER (Silero v5)
# =========================
class TTSWorker(threading.Thread):
    def __init__(self, audio_tracker: AudioStateTracker):
        super().__init__(daemon=True)
        self.audio_tracker = audio_tracker
        self.q: "queue.Queue[str]" = queue.Queue(maxsize=50)
        self._stop = threading.Event()
        self._model = None

        # Force Silero to CPU
        self.device = torch.device("cpu")

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

    def _lazy_init(self):
        if self._model is not None:
            return

        print(f"[TTS] Loading Silero v5 from {SILERO_MODEL_PATH}...")
        print(f"[TTS] Forced device: {self.device}")
        t0 = time.time()

        try:
            self._model = torch.package.PackageImporter(SILERO_MODEL_PATH).load_pickle("tts_models", "model")
            self._model.to(self.device)

            print(f"[TTS] Silero loaded in {time.time()-t0:.2f}s on {self.device}. Running warmup...")
            with torch.no_grad():
                _ = self._model.apply_tts(
                    text="Привет.",
                    speaker=SILERO_SPEAKER,
                    sample_rate=SILERO_SAMPLE_RATE,
                )
            print("[TTS] Warmup OK. Ready.")

        except Exception as e:
            print(f"[TTS ERROR] Failed to load Silero on CPU: {e}")
            traceback.print_exc()
            self._model = None

    def _sanitize(self, text: str) -> str:
        text = re.sub(r'[*_~`]', '', text)
        if text and text[-1] not in '.!?':
            text += '.'
        return text.strip()

    def _has_cyrillic(self, text: str) -> bool:
        return bool(re.search('[а-яА-ЯёЁ]', text))

    def _synthesize_and_play(self, text: str):
        self.audio_tracker.active.set()
        try:
            self._lazy_init()
            if self._model is None:
                return

            text = self._sanitize(text)
            if not text:
                return

            text = russify_text(text)

            if not self._has_cyrillic(text):
                print(f"[TTS] Skipping non-Russian text: {text!r}")
                return

            print(f"[TTS] Synthesizing on {self.device}: {text!r}")
            t0 = time.time()

            with torch.no_grad():
                audio = self._model.apply_tts(
                    text=text,
                    speaker=SILERO_SPEAKER,
                    sample_rate=SILERO_SAMPLE_RATE,
                )

            wav = audio.detach().cpu().numpy()
            synth_ms = (time.time() - t0) * 1000
            print(f"[TTS] Synthesis done in {synth_ms:.0f}ms")

            proc = subprocess.Popen(
                ["aplay", "-q", "-r", str(SILERO_SAMPLE_RATE), "-f", "FLOAT_LE", "-c", "1", "-"],
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _, err = proc.communicate(input=wav.tobytes())

            if proc.returncode != 0:
                print(f"[Playback ERROR] aplay: {err.decode(errors='replace').strip()}")
            else:
                print("[Playback] Done.")

        except Exception as e:
            print(f"[TTS ERROR] {e}")
            traceback.print_exc()
        finally:
            self.audio_tracker.active.clear()
            print("[TTS] Mic unmuted.")

    def run(self):
        print("[TTS] Worker thread started.")
        while not self._stop.is_set():
            text = self.q.get()
            if self._stop.is_set():
                break
            if not text:
                continue
            try:
                self._synthesize_and_play(text)
            except Exception as e:
                print(f"[TTS] Unhandled error: {e}")
                traceback.print_exc()
                
# =========================
# AUDIO HELPERS
# =========================
def pcm16_to_float32(audio_bytes: bytes) -> np.ndarray:
    return np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

def resample_audio_float32(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr:
        return audio.astype(np.float32, copy=False)
    if len(audio) == 0:
        return audio.astype(np.float32)

    duration = len(audio) / orig_sr
    new_length = int(duration * target_sr)
    if new_length <= 0:
        return np.array([], dtype=np.float32)

    old_idx = np.linspace(0, len(audio) - 1, num=len(audio))
    new_idx = np.linspace(0, len(audio) - 1, num=new_length)
    return np.interp(new_idx, old_idx, audio).astype(np.float32)

# =========================
# WHISPER STT
# =========================
class WhisperSTT:
    def __init__(self):
        print(f"[Whisper] Loading model '{WHISPER_MODEL_SIZE}' on {WHISPER_DEVICE} ({WHISPER_COMPUTE})...")
        self.model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
        print("[Whisper] Model loaded.")

    def transcribe_bytes(self, audio_bytes: bytes, sample_rate: int) -> str:
        try:
            audio = pcm16_to_float32(audio_bytes)
            audio = resample_audio_float32(audio, sample_rate, WHISPER_SAMPLE_RATE)

            segments, info = self.model.transcribe(
                audio,
                language=WHISPER_LANGUAGE,
                vad_filter=False,
                beam_size=1,
            )

            text = " ".join(seg.text.strip() for seg in segments).strip()
            print(f"[Whisper] detected_language={info.language} prob={info.language_probability:.3f}")
            print(f"[Whisper] detected text={text}")
            return text
        except Exception as e:
            print(f"[Whisper ERROR] {e}")
            traceback.print_exc()
            return ""

# =========================
# VAD & UTTERANCE CAPTURE
# =========================
@dataclass
class CaptureOut:
    final_audio: Optional[bytes] = None

class VadAudioCapture:
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
        self.utt_frames: List[bytes] = []

    def reset(self):
        self.pre.clear()
        self.triggered = False
        self.silence = 0
        self.start_time = 0.0
        self.utt_frames = []

    def step(self, frame: bytes, max_utt_sec: float) -> CaptureOut:
        if len(frame) != self.frame_bytes:
            return CaptureOut()

        is_speech = self.vad.is_speech(frame, self.sr)

        if not self.triggered:
            self.pre.append(frame)
            if is_speech:
                self.triggered = True
                self.silence = 0
                self.start_time = time.time()
                self.utt_frames = list(self.pre)
                self.pre.clear()
                self.utt_frames.append(frame)
            return CaptureOut()

        self.utt_frames.append(frame)

        if is_speech:
            self.silence = 0
        else:
            self.silence += 1

        too_long = (time.time() - self.start_time) >= max_utt_sec
        ended = (self.silence >= self.end_silence_frames) or too_long

        if ended:
            audio_bytes = b"".join(self.utt_frames)
            self.reset()
            return CaptureOut(final_audio=audio_bytes)

        return CaptureOut()

# =========================
# MAIN ASSISTANT
# =========================
@dataclass
class State:
    mode: str
    last_activity: float

class VoiceAssistant:
    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent
        self.state = State(mode="SLEEP", last_activity=time.time())
        self.audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=400)
        self.audio_tracker = AudioStateTracker()

        print(f"[CUDA] torch.cuda.is_available() = {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            try:
                 print(f"[CUDA] device = {torch.cuda.get_device_name(0)}")
            except Exception:
                pass

        if WHISPER_DEVICE == "cuda":
            print("[Init] Whisper is configured to use GPU.")
        else:
             print("[WARN] Whisper is not configured for GPU.")

        print("[Init] Silero is forced to CPU.")


        self.tts = TTSWorker(self.audio_tracker)
        self.tts.start()
        print("[Init] TTS worker started.")

        self.sample_rate = 16000
        self.frame_samples = int(self.sample_rate * FRAME_MS / 1000)
        self.frame_bytes = self.frame_samples * 2
        print(f"[Init] Mic sample rate: {self.sample_rate} Hz")

        self.whisper = WhisperSTT()

        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.capture = VadAudioCapture(self.vad, self.sample_rate, FRAME_MS)
        self.memory = PipelineMemoryBridge(
            self.base_dir,
            base_system_prompt=BOXY_SYSTEM_PROMPT,
            response_temperature=LLAMA_TEMPERATURE,
            response_max_tokens=LLAMA_NUM_PREDICT,
            model_name=PIPELINE_LLM_MODEL,
            prefer_text_tool_calls=True,
        )
        print(f"[Init] LLM model: {self.memory.model_name}")
        print(
            "[Init] Memory tool mode: "
            + ("text tool calls" if self.memory.prefer_text_tool_calls else "structured tools")
        )
        health = self.memory.get_health_report()
        print(
            f"[Init] Memory DBs: {self.base_dir} | recall={health['recall_count']} archival={health['archival_count']}"
        )
        self.mic_gate_until = 0.0
        print("[Init] Assistant ready.")

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

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            print(f"[Mic] Status: {status}")
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

    def _enter_sleep(self):
        self.state.mode = "SLEEP"
        self.state.last_activity = time.time()
        self.capture.reset()
        print("[STATE] -> SLEEP")

    def _enter_active(self):
        self.state.mode = "ACTIVE"
        self.state.last_activity = time.time()
        self.capture.reset()
        self.mic_gate_until = time.time() + WAKE_MIC_GATE_SEC
        print("[STATE] -> ACTIVE")
        self.tts.say(GREETING)

    def _transcribe(self, audio_bytes: bytes) -> str:
        text = self.whisper.transcribe_bytes(audio_bytes, self.sample_rate).strip()
        if text:
            print(f"[STT] {text}")
        return text

    def _queue_response_for_tts(self, response_text: str) -> None:
        for sentence in split_tts_sentences(response_text):
            clean = re.sub(r'[*_~`]', '', sentence.strip())
            if clean:
                print(f"[LLM -> TTS] {clean!r}")
                self.tts.say(clean)

    def _respond_with_llm(self, user_text: str):
        print(f"[USER] {user_text}")
        full_response = ""

        try:
            full_response = self.memory.generate_reply(user_text)
            if full_response:
                self._queue_response_for_tts(full_response)
            else:
                self.tts.say("Я задумалась и потеряла мысль.")

        except Exception as e:
            print(f"[LLM ERROR] {e}")
            traceback.print_exc()
            self.tts.say("Извини, у меня возникла проблема.")

        print(f"[ASSISTANT] {full_response.strip()}")
        self.mic_gate_until = time.time() + 0.5

    def run_forever(self):
        print("==============================================")
        print("Assistant running.")
        print(f"Sample rate: {self.sample_rate} Hz | Frame: {FRAME_MS} ms")
        print(f"Wake words: {WAKE_WORDS}")
        print("==============================================")

        with sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_samples,
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
        ):
            print("[Mic] Input stream open. Listening for wake word...")
            try:
                while True:
                    if self.state.mode == "ACTIVE" and (time.time() - self.state.last_activity) > ACTIVE_IDLE_TIMEOUT_SEC:
                        print("[Idle] Timeout — going to sleep.")
                        self.tts.say("Я подожду. Скажи привет бокс, если понадоблюсь.")
                        self._enter_sleep()

                    frame = self.audio_q.get()

                    if self.state.mode == "SLEEP":
                        out = self.capture.step(
                            frame=frame,
                            max_utt_sec=MAX_UTT_SLEEP_SEC,
                        )
                        if out.final_audio:
                            text = self._transcribe(out.final_audio)
                            if text and contains_phrase(text, WAKE_WORDS):
                                print(f"[Wake detected] {text}")
                                self._enter_active()
                                continue

                    else:
                        out = self.capture.step(
                            frame=frame,
                            max_utt_sec=MAX_UTT_ACTIVE_SEC,
                        )
                        if out.final_audio:
                            user_text = self._transcribe(out.final_audio)
                            if user_text:
                                if not is_actionable_user_text(user_text):
                                    print(f"[STT] Ignoring unsupported text: {user_text!r}")
                                    continue
                                self.state.last_activity = time.time()
                                if contains_phrase(user_text, SLEEP_PHRASES):
                                    self.tts.say("Хорошо. Скажи привет бокс, если понадоблюсь.")
                                    self._enter_sleep()
                                else:
                                    self._respond_with_llm(user_text)

            except KeyboardInterrupt:
                print("\nExiting...")
            finally:
                self.tts.stop()

if __name__ == "__main__":
    VoiceAssistant().run_forever()
