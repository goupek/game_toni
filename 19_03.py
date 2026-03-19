import json
import traceback
import os
import queue
import threading
import time
import re
import subprocess
from collections import deque
from dataclasses import dataclass
from typing import List, Dict, Optional

import requests
import sounddevice as sd
import webrtcvad
from vosk import Model, KaldiRecognizer

# =========================
# CONFIGURATION
# =========================
MIC_DEVICE = 24

# Set to your HDMI/speaker device, e.g. "hw:1,0" or "plughw:1,0"
# Leave as "" to use the system default
SPEAKER_DEVICE = "hw:1,0"

VOSK_MODEL_PATH = "models/vosk/vosk-model-small-en-us-0.15"

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:0.5b"

WAKE_WORDS = ["hey box", "okay box", "hi box", "box box"]
GREETING = "Hi, how can I help you?"
SLEEP_PHRASES = ["go to sleep", "sleep", "stop listening", "goodbye", "bye"]

OLLAMA_NUM_PREDICT = 150
OLLAMA_TEMPERATURE = 0.4
OLLAMA_NUM_CTX = 512

PIPER_EXEC_PATH = "piper"
PIPER_MODEL_PATH = "models/piper/en_US-lessac-medium.onnx"

FRAME_MS = 20
VAD_AGGRESSIVENESS = 2
PRE_ROLL_MS = 300
END_SILENCE_MS = 500
MAX_UTT_SLEEP_SEC = 3.0
MAX_UTT_ACTIVE_SEC = 20.0
VAD_SUPPORTED_RATES = [16000, 48000, 32000, 8000]
ACTIVE_IDLE_TIMEOUT_SEC = 60

# TTS chunking
MIN_TTS_CHARS = 40    # don't flush until we have this much text
MAX_BUFFER_CHARS = 180 # hard flush to start audio quickly

# =========================
# TEXT HELPERS
# =========================
def normalize_text(s: str) -> str:
    s = s.lower().strip()
    return re.sub(r"\s+", " ", s)

def contains_phrase(text: str, phrases: List[str]) -> bool:
    t = normalize_text(text)
    return any(p in t for p in phrases)

def clean_llm_text(text: str) -> str:
    """Strip markdown that Piper would read aloud literally."""
    return re.sub(r'[*_~`]', '', text)

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
    with requests.post(f"{OLLAMA_URL}/api/chat", json=payload, stream=True) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                data = json.loads(line)
                yield data.get("message", {}).get("content", "")

# =========================
# AUDIO STATE TRACKER
# =========================
class AudioStateTracker:
    def __init__(self):
        self.active = threading.Event()

# =========================
# PLAYBACK WORKER
# =========================
class PlaybackWorker(threading.Thread):
    """Plays WAV byte-chunks from a queue, one at a time."""

    def __init__(self, audio_tracker: AudioStateTracker):
        super().__init__(daemon=True)
        self.audio_tracker = audio_tracker
        self.q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=50)
        self._stop_evt = threading.Event()

    def stop(self):
        self._stop_evt.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass

    def run(self):
        while not self._stop_evt.is_set():
            item = self.q.get()
            if self._stop_evt.is_set():
                break
            if item is None:
                print("[Playback] Sentinel received — unmuting microphone.")
                self.audio_tracker.active.clear()
                continue
            try:
                cmd = ["aplay", "-q"]
                if SPEAKER_DEVICE:
                    cmd += ["-D", SPEAKER_DEVICE]
                cmd.append("-")
                print(f"[Playback] Playing {len(item)} bytes via: {' '.join(cmd)}")
                t0 = time.time()
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                _, err = proc.communicate(input=item)
                elapsed = (time.time() - t0) * 1000
                if proc.returncode != 0:
                    print(f"[Playback] aplay error (rc={proc.returncode}): {err.decode('utf-8', errors='replace').strip()}")
                else:
                    print(f"[Playback] Done in {elapsed:.0f}ms.")
            except Exception as e:
                print(f"[Playback Error]: {e}")

# =========================
# PERSISTENT PIPER PROCESS
# =========================
class PiperProcess:
    """
    Keeps a single Piper subprocess alive for the lifetime of the assistant.

    How it works:
      - Piper reads text lines from stdin, one per sentence.
      - For each line it writes a complete WAV file to stdout.
      - We parse the RIFF/WAV header to know exactly how many bytes to read,
        so we can pull one complete WAV per sentence without knowing its length
        in advance.
      - No subprocess.run() startup cost per sentence (~300-500ms saved each time).
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()  # guards _proc across threads

    def _start(self) -> bool:
        """Launch Piper. Returns True on success.

        The pip-installed 'piper' is a Python script. Python buffers its stdout
        by default, so WAV bytes sit in a buffer and never reach our pipe until
        the buffer fills (~8KB). We detect this and force unbuffered output with
        'python -u', which makes each WAV flush immediately after synthesis.
        """
        import sys as _sys
        try:
            with open(PIPER_EXEC_PATH, "rb") as f:
                first_line = f.readline()
            is_python_script = b"python" in first_line.lower()
        except Exception:
            is_python_script = False

        if is_python_script:
            cmd = [_sys.executable, "-u", PIPER_EXEC_PATH, "--model", PIPER_MODEL_PATH]
            print("[Piper] Detected Python wrapper — using 'python -u' for unbuffered stdout")
        else:
            cmd = [PIPER_EXEC_PATH, "--model", PIPER_MODEL_PATH]

        print(f"[Piper] Command: {cmd}")
        t0 = time.time()
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Give Piper ~200 ms to load the model, then check it's still alive
            time.sleep(0.2)
            rc = self._proc.poll()
            if rc is not None:
                err = self._proc.stderr.read().decode("utf-8", errors="replace").strip()
                print(f"[Piper] Process exited immediately (rc={rc}). stderr: {err}")
                return False
            elapsed = time.time() - t0
            print(f"[Piper] Process alive after {elapsed:.2f}s. PID={self._proc.pid}")
            return True
        except FileNotFoundError:
            print(f"[Piper Error] Executable not found: '{PIPER_EXEC_PATH}'")
            return False
        except Exception as e:
            print(f"[Piper Error] Failed to start: {e}")
            return False

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _ensure_alive(self) -> bool:
        if self._is_alive():
            return True
        return self._start()

    def _read_one_wav(self) -> Optional[bytes]:
        """
        Read one complete WAV from Piper stdout by parsing the RIFF header.

        WAV layout:
          bytes 0-3:  "RIFF"
          bytes 4-7:  chunk_size (little-endian uint32) = total_file_size - 8
          bytes 8-end: the rest of the WAV (contains "WAVE" + subchunks)

        So: total file = 8 + chunk_size bytes.
        We read the 8-byte prefix, extract chunk_size, then read chunk_size more.
        """
        stdout = self._proc.stdout
        try:
            print("[Piper] Waiting for RIFF header (8 bytes)...")
            t0 = time.time()
            prefix = stdout.read(8)
            if len(prefix) < 8:
                print(f"[Piper] ERROR: Only got {len(prefix)} bytes for header — process may have died.")
                rc = self._proc.poll()
                if rc is not None:
                    err = self._proc.stderr.read().decode("utf-8", errors="replace").strip()
                    print(f"[Piper] Process exited with rc={rc}. stderr: {err or '(empty)'}")
                return None
            if prefix[:4] != b"RIFF":
                print(f"[Piper] ERROR: Expected 'RIFF', got {prefix[:4]!r}. Full prefix: {prefix!r}")
                return None

            chunk_size = int.from_bytes(prefix[4:8], "little")
            total_bytes = 8 + chunk_size
            print(f"[Piper] RIFF header OK in {(time.time()-t0)*1000:.0f}ms — reading {total_bytes} bytes total ({chunk_size} body)...")

            t1 = time.time()
            body = stdout.read(chunk_size)
            elapsed_body = (time.time() - t1) * 1000
            elapsed_total = (time.time() - t0) * 1000

            if len(body) < chunk_size:
                print(f"[Piper] ERROR: Expected {chunk_size} body bytes, got {len(body)}.")
                return None

            print(f"[Piper] WAV ready: {total_bytes} bytes | body read: {elapsed_body:.0f}ms | total: {elapsed_total:.0f}ms")
            return prefix + body

        except Exception as e:
            print(f"[Piper] WAV read error: {e}")
            traceback.print_exc()
            return None

    def synthesize(self, text: str) -> Optional[bytes]:
        """
        Write text to Piper stdin, return the resulting WAV bytes.
        Thread-safe: only TTSWorker calls this.
        """
        with self._lock:
            if not self._ensure_alive():
                print("[Piper] ERROR: Cannot synthesize — process not alive.")
                return None
            try:
                line = text.encode("utf-8") + b"\n"
                print(f"[Piper] Writing to stdin ({len(line)} bytes): {text!r}")
                t0 = time.time()
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
                print(f"[Piper] stdin flushed in {(time.time()-t0)*1000:.0f}ms — waiting for WAV...")
                wav = self._read_one_wav()
                if wav:
                    print(f"[Piper] Synthesis complete: {len(wav)} bytes")
                else:
                    print("[Piper] Synthesis returned None — check errors above.")
                return wav
            except BrokenPipeError:
                print("[Piper] BrokenPipeError — process died. Restarting...")
                self._proc = None
                if self._start():
                    try:
                        self._proc.stdin.write(text.encode("utf-8") + b"\n")
                        self._proc.stdin.flush()
                        return self._read_one_wav()
                    except Exception as e:
                        print(f"[Piper] Retry failed: {e}")
                return None
            except Exception as e:
                print(f"[Piper] Synthesis error: {e}")
                traceback.print_exc()
                return None

    def stop(self):
        with self._lock:
            if self._proc:
                try:
                    self._proc.stdin.close()
                    self._proc.terminate()
                    self._proc.wait(timeout=2)
                except Exception:
                    pass
                self._proc = None

# =========================
# TTS WORKER
# =========================
class TTSWorker(threading.Thread):
    """
    Pulls text chunks from a queue, synthesizes via the persistent PiperProcess,
    and pushes resulting WAV bytes to PlaybackWorker.

    The critical insight for latency:
    - This thread synthesizes chunk N+1 while PlaybackWorker is playing chunk N.
    - Since they are separate threads, synthesis and playback run concurrently.
    - By the time chunk N finishes playing, chunk N+1 is already in the
      playback queue — zero gap between sentences.
    """

    def __init__(self, playback_worker: PlaybackWorker, piper: PiperProcess):
        super().__init__(daemon=True)
        self.playback_worker = playback_worker
        self.piper = piper
        # Queue holds: str (text to synthesize) or None (end-of-response sentinel)
        self.q: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=60)
        self._stop_evt = threading.Event()

    def say(self, text: str):
        """Queue a text chunk for synthesis (called from main thread)."""
        text = clean_llm_text(text.strip())
        if text:
            self.q.put(text)

    def signal_end(self):
        """Signal end-of-response (unmutes mic after all audio plays)."""
        self.q.put(None)

    def stop(self):
        self._stop_evt.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass

    def run(self):
        while not self._stop_evt.is_set():
            item = self.q.get()
            if self._stop_evt.is_set():
                break

            if item is None:
                print("[TTS] End-of-response sentinel — forwarding to playback.")
                self.playback_worker.q.put(None)
                continue

            print(f"[TTS] Dequeued chunk for synthesis: {item!r}")
            t0 = time.time()
            wav = self.piper.synthesize(item)
            elapsed = (time.time() - t0) * 1000
            if wav:
                print(f"[TTS] Pushing {len(wav)} bytes to playback queue (synth took {elapsed:.0f}ms)")
                self.playback_worker.q.put(wav)
            else:
                print(f"[TTS] Synthesis failed for chunk: {item!r} (took {elapsed:.0f}ms)")

# =========================
# SMART TTS CHUNKER
# =========================
class TTSChunker:
    """
    Accumulates LLM token stream and flushes natural-sounding chunks to TTS.

    Rules:
    - Only flush on sentence-ending punctuation (.!?) — never on commas/colons.
    - Require MIN_TTS_CHARS before flushing, so tiny fragments are merged.
    - Hard-flush at MAX_BUFFER_CHARS so the first audio starts quickly.
    """

    def __init__(self, tts: TTSWorker):
        self.tts = tts
        self._buf = ""

    def feed(self, chunk: str):
        self._buf += chunk
        self._try_flush()

    def _try_flush(self):
        # Hard flush if buffer is very long
        if len(self._buf) >= MAX_BUFFER_CHARS:
            cut = self._buf.rfind(" ")
            if cut == -1:
                cut = len(self._buf)
            self._send(self._buf[:cut].strip())
            self._buf = self._buf[cut:].lstrip()
            return

        # Normal flush: sentence boundary after minimum length
        if len(self._buf) >= MIN_TTS_CHARS:
            match = None
            for m in re.finditer(r'[.!?](?=\s|$)', self._buf):
                match = m
            if match:
                phrase = self._buf[:match.end()].strip()
                self._send(phrase)
                self._buf = self._buf[match.end():].lstrip()

    def flush_remaining(self):
        remainder = self._buf.strip()
        if remainder:
            self._send(remainder)
        self._buf = ""

    def _send(self, text: str):
        text = text.strip()
        if text:
            print(f"[Chunker] Dispatching to TTS: {text!r}")
            self.tts.say(text)

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

        # Resample fields — set by _pick_input_rate if mic only supports non-VAD rates
        self._resample_from: Optional[int] = None
        self._resample_to: Optional[int] = None

        # Boot the pipeline
        self.piper = PiperProcess()
        self.piper._start()  # warm up immediately so first response has no delay

        self.playback_worker = PlaybackWorker(self.audio_tracker)
        self.tts = TTSWorker(self.playback_worker, self.piper)

        self.playback_worker.start()
        self.tts.start()

        self.sample_rate = self._pick_input_rate()

        # VAD/Vosk always operate at vad_rate (16000 if resampling, else sample_rate)
        self.vad_rate = self._resample_to if self._resample_to else self.sample_rate
        self.frame_samples = int(self.sample_rate * FRAME_MS / 1000)
        self.frame_bytes = self.frame_samples * 2
        # VAD frame size at the target rate (used by VadVoskCapture)
        self.vad_frame_samples = int(self.vad_rate * FRAME_MS / 1000)
        self.vad_frame_bytes = self.vad_frame_samples * 2

        self.vosk_model = Model(VOSK_MODEL_PATH)
        self._make_recognizers()

        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.capture = VadVoskCapture(self.vad, self.vad_rate, FRAME_MS)

        self.messages: List[Dict] = [
            {
                "role": "system",
                "content": (
                    "You are a friendly voice assistant helping children who are learning English. "
                    "Speak clearly and use very simple, everyday vocabulary. "
                    "CRITICAL RULES: "
                    "1. Limit your total response to a maximum of 3 to 4 sentences. "
                    "2. Keep every single sentence extremely short (under 10 words). "
                    "3. DO NOT use asterisks, markdown, emojis, or special symbols. Output plain text only."
                ),
            }
        ]
        self.mic_gate_until = 0.0

    def _pick_input_rate(self) -> int:
        """
        Pick the best sample rate the mic supports from VAD_SUPPORTED_RATES.
        If none of the VAD rates work, fall back to the mic's native rate and
        configure sounddevice to downsample on the fly to 16000 Hz for VAD/Vosk.
        This fixes the crash when ALSA reports 44100 Hz as the only available rate.
        """
        for sr in VAD_SUPPORTED_RATES:
            try:
                sd.check_input_settings(device=MIC_DEVICE, samplerate=sr, channels=1, dtype="int16")
                print(f"[Mic] Using VAD-native rate: {sr} Hz")
                return sr
            except Exception:
                continue

        # None of the VAD rates worked — use native rate and resample in callback
        info = sd.query_devices(MIC_DEVICE, "input")
        native_sr = int(info["default_samplerate"])
        print(f"[Mic] No VAD-native rate available. Native rate: {native_sr} Hz — will downsample to 16000 Hz.")
        self._resample_from = native_sr
        self._resample_to = 16000
        return native_sr  # RawInputStream will open at native rate; callback resamples

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

        # Resample to VAD rate if mic native rate != VAD-supported rate
        if self._resample_from and self._resample_to:
            import array, math
            src = array.array("h", b)
            ratio = self._resample_to / self._resample_from
            out_len = int(len(src) * ratio)
            dst = array.array("h", [0] * out_len)
            for i in range(out_len):
                src_idx = i / ratio
                lo = int(src_idx)
                hi = min(lo + 1, len(src) - 1)
                frac = src_idx - lo
                dst[i] = int(src[lo] * (1 - frac) + src[hi] * frac)
            b = bytes(dst)

        if len(b) != self.vad_frame_bytes:
            return
        try:
            self.audio_q.put_nowait(b)
        except queue.Full:
            try:
                self.audio_q.get_nowait()
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
        self.tts.signal_end()

    def _respond_with_llm(self, user_text: str):
        # Mute mic immediately — don't let it hear the speaker
        self.audio_tracker.active.set()

        self.messages.append({"role": "user", "content": user_text})
        self._trim_history()
        print(f"[USER] {user_text}")

        full_response = ""
        chunker = TTSChunker(self.tts)

        try:
            for chunk in ollama_chat_stream(self.messages):
                full_response += chunk
                # Feed each token to the chunker — synthesis starts during streaming,
                # not after. The [ASSISTANT] line will print AFTER the first audio
                # has already started playing.
                chunker.feed(chunk)
            chunker.flush_remaining()
        except Exception as e:
            print(f"[LLM] Error: {e}")
            self.tts.say("Sorry, I had trouble answering that.")
        finally:
            self.tts.signal_end()

        # This prints only after the LLM stream is done — by then, chunk 1 is
        # already being played and chunk 2 is already synthesized.
        final_clean = clean_llm_text(full_response.strip())
        print(f"[ASSISTANT] {final_clean}")
        self.messages.append({"role": "assistant", "content": final_clean})
        self._trim_history()
        self.mic_gate_until = time.time() + 0.5

    def run_forever(self):
        print("==============================================")
        print("Assistant ready (persistent Piper pipeline).")
        print(f"Sample rate: {self.sample_rate} Hz | Frame: {FRAME_MS} ms")
        print(f"Speaker device: {SPEAKER_DEVICE or 'system default'}")
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
                    if (
                        self.state.mode == "ACTIVE"
                        and (time.time() - self.state.last_activity) > ACTIVE_IDLE_TIMEOUT_SEC
                    ):
                        self.tts.say("I'll wait. Say 'hey box' if you need me.")
                        self.tts.signal_end()
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
                            print(f"[STT partial] {out.partial}")
                            self._enter_active()
                            self.mic_gate_until = time.time() + 0.2
                            continue
                        if out.final and contains_phrase(out.final, WAKE_WORDS):
                            print(f"[STT] {out.final}")
                            self._enter_active()
                            self.mic_gate_until = time.time() + 0.2
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
                                print(f"[STT] {user_text}")
                                self.state.last_activity = time.time()
                                if contains_phrase(user_text, SLEEP_PHRASES):
                                    self.tts.say("Okay. Say 'hey box' if you need me.")
                                    self.tts.signal_end()
                                    self._enter_sleep()
                                else:
                                    self._respond_with_llm(user_text)
                                    self.rec_full = KaldiRecognizer(
                                        self.vosk_model, self.sample_rate
                                    )

            except KeyboardInterrupt:
                print("\nExiting...")
            finally:
                self.tts.stop()
                self.playback_worker.stop()
                self.piper.stop()

if __name__ == "__main__":
    VoiceAssistant().run_forever()