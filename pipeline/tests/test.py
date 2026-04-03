import io
import json
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
from typing import List, Dict, Optional
from transliterate import translit

import torch
import requests
import sounddevice as sd
import webrtcvad
from vosk import Model, KaldiRecognizer

# =========================
# CONFIGURATION
# =========================
MIC_DEVICE = 24

VOSK_MODEL_PATH = "models/vosk/vosk-model-small-en-us-0.15"

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:1.5b"

WAKE_WORDS = ["hey box", "okay box", "hi box", "box box"]
GREETING = "Привет, чем я могу тебе помочь?"
SLEEP_PHRASES = ["go to sleep", "sleep", "stop listening", "goodbye", "bye"]

OLLAMA_NUM_PREDICT = 150
OLLAMA_TEMPERATURE = 0.4
OLLAMA_NUM_CTX = 512

SILERO_MODEL_PATH = "models/silero/v5_ru.pt"
SILERO_SPEAKER = "xenia"   # options: aidar, baya, kseniya, xenia, eugene
SILERO_SAMPLE_RATE = 48000

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

def russify_text(text: str) -> str:
    """
    Convert English words in text to Russian phonetic transliteration.
    Leaves already-Cyrillic words untouched.
    """
    def replace_english(match):
        word = match.group(0)
        try:
            return translit(word, 'ru')
        except Exception:
            return word

    return re.sub(r'[a-zA-Z]+', replace_english, text)

# =========================
# OLLAMA LOGIC (STREAMING)
# =========================
def ollama_chat_stream(messages: List[Dict]):
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "options": {
            "num_predict": OLLAMA_NUM_PREDICT,
            "temperature": OLLAMA_TEMPERATURE,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }
    print(f"[LLM] Sending request to Ollama ({OLLAMA_MODEL})...")
    with requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True) as r:
        r.raise_for_status()
        print("[LLM] Stream started, receiving tokens...")
        for line in r.iter_lines():
            if line:
                data = json.loads(line)
                yield data.get("message", {}).get("content", "")

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
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

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
        print(f"[TTS] Requested device: {self.device}")
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
            print(f"[TTS WARN] Failed to load Silero on {self.device}: {e}")
            traceback.print_exc()

            if self.device.type == "cuda":
                try:
                    print("[TTS WARN] Falling back to CPU...")
                    self.device = torch.device("cpu")
                    self._model = torch.package.PackageImporter(SILERO_MODEL_PATH).load_pickle("tts_models", "model")
                    self._model.to(self.device)
            

                    with torch.no_grad():
                        _ = self._model.apply_tts(
                            text="Привет.",
                            speaker=SILERO_SPEAKER,
                            sample_rate=SILERO_SAMPLE_RATE,
                        )
                    print("[TTS] CPU fallback OK. Ready.")
                except Exception as e2:
                    print(f"[TTS ERROR] CPU fallback also failed: {e2}")
                    traceback.print_exc()
                    self._model = None
            else:
                self._model = None

    def _sanitize(self, text: str) -> str:
        text = re.sub(r'[*_~`]', '', text)
        if text and text[-1] not in '.!?':
            text += '.'
        return text.strip()

    def _has_cyrillic(self, text: str) -> bool:
        return bool(re.search('[а-яА-ЯёЁ]', text))

    def _synthesize_and_play(self, text: str):
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

        try:
            self.audio_tracker.active.set()
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

        print(f"[CUDA] torch.cuda.is_available() = {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            try:
                print(f"[CUDA] device = {torch.cuda.get_device_name(0)}")
            except Exception:
                pass

        self.tts = TTSWorker(self.audio_tracker)
        self.tts.start()
        print("[Init] TTS worker started.")

        self.sample_rate = 32000
        self.frame_samples = int(self.sample_rate * FRAME_MS / 1000)
        self.frame_bytes = self.frame_samples * 2
        print(f"[Init] Mic sample rate: {self.sample_rate} Hz")

        print("[Init] Loading Vosk model...")
        self.vosk_model = Model(VOSK_MODEL_PATH)
        self._make_recognizers()
        print("[Init] Vosk model loaded.")

        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.capture = VadVoskCapture(self.vad, self.sample_rate, FRAME_MS)

        self.messages: List[Dict] = [
            {"role": "system",
             "content": (
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
                "Each sentence must be short — under 12 words. "
                "\n\n"
                "STRICT OUTPUT RULES: "
                "1. Plain Cyrillic text only. No lists, bullet points, numbers, colons, dashes, asterisks, markdown, or emojis. "
                "2. Never explain grammar rules or use linguistic terms like 'nominative' or 'accusative'. "
                "3. Never say a word 'means itself' — яблоко means apple, not яблоко. "
                "4. Never repeat the English word back — if they said 'apple', do not say 'apple' in your response. "
                "5. If you do not understand the question, ask one simple clarifying question in Russian. "
                "6. Never answer in English, even if the user writes in English. "
                "\n\n"
                "RESPONSE PATTERNS — use these templates as a guide: "
                "\n"
                "For translation requests ('how do you say X', 'what is X in Russian'): "
                "Say: 'Это слово переводится как [слово]. [Short example sentence using the word]. Попробуй повторить!' "
                "\n"
                "For yes/no questions about Russian: "
                "Give a direct short answer first, then one example. "
                "\n"
                "For greetings or small talk: "
                "Respond warmly and naturally, then invite the user to practice a word or phrase. "
                "\n"
                "For gibberish, unclear input, or random sounds: "
                "Say you did not understand and ask them to repeat in one short sentence. "
                "\n\n"
                "EXAMPLES OF GOOD RESPONSES: "
                "'Это слово переводится как яблоко. Яблоко — красный фрукт. Попробуй сказать: яблоко!' "
                "'Я не совсем понял. Можешь повторить ещё раз?' "
                "\n\n"
             )}
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

        full_response = ""
        current_sentence = ""
        sentence_enders = {".", "?", "!", "\n"}
        chunks_received = 0

        try:
            for chunk in ollama_chat_stream(self.messages):
                full_response += chunk
                current_sentence += chunk
                chunks_received += 1

                if any(ender in chunk for ender in sentence_enders):
                    clean = re.sub(r'[*_~`]', '', current_sentence.strip())
                    if clean:
                        print(f"[LLM -> TTS] {clean!r}")
                        self.tts.say(clean)
                    current_sentence = ""

            clean = re.sub(r'[*_~`]', '', current_sentence.strip())
            if clean:
                print(f"[LLM -> TTS] (remainder) {clean!r}")
                self.tts.say(clean)

            print(f"[LLM] Stream finished. Chunks received: {chunks_received}")

        except Exception as e:
            print(f"[LLM ERROR] {e}")
            traceback.print_exc()
            self.tts.say("Извини, у меня возникла проблема.")

        print(f"[ASSISTANT] {full_response.strip()}")
        self.messages.append({"role": "assistant", "content": full_response.strip()})
        self._trim_history()
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
                            rec=self.rec_wake,
                            max_utt_sec=MAX_UTT_SLEEP_SEC,
                            want_partial=True
                        )
                        if out.partial and contains_phrase(out.partial, WAKE_WORDS):
                            print(f"[STT partial] {out.partial}")
                            self._enter_active()
                            self.mic_gate_until = time.time() + 0.2
                            continue
                        if out.final and contains_phrase(out.final, WAKE_WORDS):
                            print(f"[STT final] {out.final}")
                            self._enter_active()
                            self.mic_gate_until = time.time() + 0.2
                            continue

                    else:
                        out = self.capture.step(
                            frame=frame,
                            rec=self.rec_full,
                            max_utt_sec=MAX_UTT_ACTIVE_SEC,
                            want_partial=False
                        )
                        if out.final:
                            user_text = out.final.strip()
                            if user_text:
                                print(f"[STT] {user_text}")
                                self.state.last_activity = time.time()
                                if contains_phrase(user_text, SLEEP_PHRASES):
                                    self.tts.say("Хорошо. Скажи привет бокс, если понадоблюсь.")
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