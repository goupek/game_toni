import json
import queue
import threading
import time
import re
import subprocess
import traceback
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional

from transliterate import translit
import numpy as np
import requests
import sounddevice as sd
import torch
import webrtcvad
from faster_whisper import WhisperModel

torch.cuda.empty_cache()

# =========================
# CONFIGURATION
# =========================
MIC_DEVICE = 24

WAKE_WORDS = [
    "hey box",
    "okay box",
    "hi box",
    "box box",
    "привет бокс",
    "эй бокс",
]
GREETING = "Привет, чем я могу тебе помочь?"
SLEEP_PHRASES = [
    "go to sleep",
    "sleep",
    "stop listening",
    "goodbye",
    "bye",
    "иди спать",
    "пока",
]

LLAMA_URL = "http://localhost:8080/v1/chat/completions"
LLAMA_MODEL = "gemma-3-1b-it-Q4_K_M"
LLAMA_NUM_PREDICT = 80
LLAMA_TEMPERATURE = 0.5
LLAMA_TIMEOUT_SEC = 90

SILERO_MODEL_PATH = "models/silero/v5_ru.pt"
SILERO_SPEAKER = "xenia"
SILERO_SAMPLE_RATE = 8000

# Whisper config
WHISPER_MODEL_SIZE = "tiny"
WHISPER_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
WHISPER_COMPUTE = "float16" if WHISPER_DEVICE == "cuda" else "int8"
WHISPER_LANGUAGE = None  # auto-detect; filtered to en/ru in transcribe_bytes
WHISPER_SAMPLE_RATE = 16000

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
    s = re.sub(r"[^\w\sа-яё]", " ", s, flags=re.IGNORECASE)
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


def strip_markdown(text: str) -> str:
    return re.sub(r'[*_~`]', '', text)


# =========================
# LLM LOGIC (STREAMING)
# =========================
def llama_chat_stream(messages: List[Dict[str, str]]):
    payload = {
        "model": LLAMA_MODEL,
        "messages": messages,
        "temperature": LLAMA_TEMPERATURE,
        "max_tokens": LLAMA_NUM_PREDICT,
        "stream": True,
        "cache_prompt": True,
    }

    print("[LLM] Sending request to llama.cpp server...")

    with requests.post(
        LLAMA_URL,
        json=payload,
        stream=True,
        timeout=(10, LLAMA_TIMEOUT_SEC),
    ) as r:
        if r.status_code >= 400:
            try:
                body = r.text
            except Exception:
                body = "<unable to read response body>"
            print(f"[LLM] HTTP {r.status_code}")
            print(f"[LLM] Error body: {body}")
            r.raise_for_status()

        print("[LLM] Stream started, receiving tokens...")

        for line in r.iter_lines():
            if not line:
                continue

            if line.startswith(b"data: "):
                line = line[len(b"data: "):]

            if line == b"[DONE]":
                break

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                print(f"[LLM] Skipping non-JSON line: {line[:200]!r}")
                continue

            if "error" in data:
                raise RuntimeError(f"llama.cpp server error: {data['error']}")

            choices = data.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            content = delta.get("content", "")

            if content:
                yield content


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
        self.device = torch.device("cpu")

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
        try:
            self.q.put_nowait(text)
            print(f"[TTS] Queued: {text!r}")
        except queue.Full:
            print("[TTS] Queue full, dropping utterance.")

    def _lazy_init(self):
        if self._model is not None:
            return

        print(f"[TTS] Loading Silero v5 from {SILERO_MODEL_PATH}...")
        print(f"[TTS] Forced device: {self.device}")
        t0 = time.time()

        try:
            self._model = torch.package.PackageImporter(SILERO_MODEL_PATH).load_pickle("tts_models", "model")
            self._model.to(self.device)

            print(f"[TTS] Silero loaded in {time.time() - t0:.2f}s on {self.device}. Running warmup...")
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
        text = strip_markdown(text)
        text = re.sub(r"\s+", " ", text).strip()
        if text and text[-1] not in '.!?':
            text += '.'
        return text

    def _has_cyrillic(self, text: str) -> bool:
        return bool(re.search('[а-яА-ЯёЁ]', text))

    def _synthesize_and_play(self, text: str):
        self.audio_tracker.active.set()  # block mic before loading/synthesis
        self._lazy_init()
        if self._model is None:
            self.audio_tracker.active.clear()
            return

        text = self._sanitize(text)
        if not text:
            self.audio_tracker.active.clear()
            return

        text = russify_text(text)

        if not self._has_cyrillic(text):
            print(f"[TTS] Skipping non-Russian text: {text!r}")
            self.audio_tracker.active.clear()
            return

        try:
            print(f"[TTS] Synthesizing on {self.device}: {text!r}")
            t0 = time.time()

            with torch.no_grad():
                audio = self._model.apply_tts(
                    text=text,
                    speaker=SILERO_SPEAKER,
                    sample_rate=SILERO_SAMPLE_RATE,
                )

            wav = audio.detach().cpu().numpy().astype(np.float32, copy=False)
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
                best_of=1,
                temperature=0.0,
                condition_on_previous_text=False,
            )

            text = " ".join(seg.text.strip() for seg in segments).strip()
            print(f"[Whisper] detected_language={info.language} prob={info.language_probability:.3f}")
            print(f"[Whisper] detected text={text}")
            if info.language not in ("en", "ru"):
                print(f"[Whisper] Discarding — unexpected language '{info.language}'")
                return ""
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
            if is_speech:
                self.triggered = True
                self.silence = 0
                self.start_time = time.time()
                self.utt_frames = list(self.pre)  # pre-roll frames before trigger
                self.pre.clear()
                self.utt_frames.append(frame)  # add the triggering frame once
            else:
                self.pre.append(frame)
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
        self.state = State(mode="SLEEP", last_activity=time.time())
        self.audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=400)
        self.audio_tracker = AudioStateTracker()

        print(f"[CUDA] torch.cuda.is_available() = {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            try:
                print(f"[CUDA] device = {torch.cuda.get_device_name(0)}")
            except Exception:
                pass

        print(f"[Init] Whisper device: {WHISPER_DEVICE}")
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

        self.messages: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are Boxy, a friendly Russian tutor. The user speaks English or Russian. "
                    "ALWAYS reply in Russian using Cyrillic ONLY. "
                    "NEVER use Latin letters. NEVER reply in English, even if the user speaks English. "
                    "\n\n"
                    "STRICT RULES: "
                    "1. Plain Cyrillic only — no markdown, lists, emojis, or asterisks. "
                    "2. Reply in exactly 2 short sentences. No more. "
                    "3. NEVER ask questions unless the user asked one first. "
                    "4. For translation requests: give the Russian word, then one example sentence. "
                    "5. If the input is unclear or gibberish: say only 'Я не понял. Можешь повторить?' "
                    "\n\n"
                    "EXAMPLES: "
                    "User: 'how do you say apple' → 'Яблоко. Я люблю яблоки.' "
                    "User: 'hello' → 'Привет! Рад тебя слышать.' "
                    "User: gibberish → 'Я не понял. Можешь повторить?' "
                ),
            }
        ]
        self.mic_gate_until = 0.0
        print("[Init] Assistant ready.")

    def _pick_input_rate(self) -> int:
        for sr in VAD_SUPPORTED_RATES:
            try:
                sd.check_input_settings(device=MIC_DEVICE, samplerate=sr, channels=1, dtype="int16")
                return sr
            except Exception:
                continue

        info = sd.query_devices(MIC_DEVICE if MIC_DEVICE is not None else None, "input")
        sr = int(info["default_samplerate"])
        if sr not in VAD_SUPPORTED_RATES:
            raise RuntimeError(f"Mic sample rate {sr} not supported. Use one of {VAD_SUPPORTED_RATES}.")
        return sr

    def _audio_callback(self, indata, _frames, _time_info, status):
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

    def _trim_history(self, keep_last_pairs: int = 2):
        sys_msg = self.messages[:1]
        rest = self.messages[1:]
        if len(rest) > keep_last_pairs * 2:
            trimmed = rest[-keep_last_pairs * 2:]
            # Gemma requires strict user/assistant alternation starting with user
            if trimmed and trimmed[0].get("role") == "assistant":
                trimmed = trimmed[1:]
            self.messages = sys_msg + trimmed

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
        self.mic_gate_until = time.time() + 0.2

    def _transcribe(self, audio_bytes: bytes) -> str:
        text = self.whisper.transcribe_bytes(audio_bytes, self.sample_rate).strip()
        if text:
            print(f"[STT] {text}")
        return text

    def _respond_with_llm(self, user_text: str):
        user_msg = {"role": "user", "content": user_text}
        self.messages.append(user_msg)
        self._trim_history()

        print(f"[USER] {user_text}")

        full_response = ""
        current_sentence = ""
        sentence_enders = {".", "?", "!", "\n"}
        chunks_received = 0

        try:
            for chunk in llama_chat_stream(self.messages):
                full_response += chunk
                current_sentence += chunk
                chunks_received += 1

                if any(ender in chunk for ender in sentence_enders):
                    clean = strip_markdown(current_sentence).strip()
                    if clean:
                        print(f"[LLM -> TTS] {clean!r}")
                        self.tts.say(clean)
                    current_sentence = ""

            clean = strip_markdown(current_sentence).strip()
            if clean:
                print(f"[LLM -> TTS] (remainder) {clean!r}")
                self.tts.say(clean)

            assistant_text = strip_markdown(full_response).strip()
            if not assistant_text:
                raise RuntimeError("Empty response from llama.cpp server")

            print(f"[LLM] Stream finished. Chunks received: {chunks_received}")
            print(f"[ASSISTANT] {assistant_text}")

            self.messages.append({"role": "assistant", "content": assistant_text})
            self._trim_history()

        except Exception as e:
            print(f"[LLM ERROR] {e}")
            traceback.print_exc()

            if self.messages and self.messages[-1].get("role") == "user" and self.messages[-1].get("content") == user_text:
                self.messages.pop()
                self._trim_history()

            self.tts.say("Извини, у меня возникла проблема.")

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
                        print("[Idle] Timeout - going to sleep.")
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