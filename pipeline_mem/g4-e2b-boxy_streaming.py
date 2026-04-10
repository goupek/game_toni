import json
import os
import queue
import sys
import threading
import time
import re
import subprocess
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from transliterate import translit
import numpy as np
import requests
import sounddevice as sd
import torch
import webrtcvad
from faster_whisper import WhisperModel

torch.cuda.empty_cache()

# =========================
# MEMORY SYSTEM SETUP
# Imported from ../memory/new_mem — no extra dependencies needed in this dir.
# =========================
_MEM_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'memory', 'new_mem')
if _MEM_SRC not in sys.path:
    sys.path.insert(0, _MEM_SRC)

MEMORY_AVAILABLE = False
try:
    from memory_system import Memory, RecallMemory, ArchivalMemory
    from context_manager import ContextManager, InteractionContext
    from personality_system import PersonalityEngine
    MEMORY_AVAILABLE = True
    print("[Memory] Memory system loaded.")
except ImportError as _e:
    print(f"[Memory] Memory system unavailable: {_e}. Running without memory.")

# Persist DB files alongside the other memory data so all pipeline variants share them.
MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'memory', 'data')

# =========================
# CONFIGURATION
# =========================
def _parse_device_hint(value: Optional[str]):
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return int(value) if value.lstrip("-").isdigit() else value


MIC_DEVICE = _parse_device_hint(os.getenv("BOXY_MIC_DEVICE"))
LEGACY_MIC_DEVICE = 26  # historical fallback for older Jetson audio setups

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
LLAMA_MODEL = "gemma-4-e2b-it-q4_k_m"
LLAMA_NUM_PREDICT = 512
LLAMA_TEMPERATURE = 0.5
LLAMA_TIMEOUT_SEC = 90

SILERO_MODEL_PATH = "./models/silero/v5_ru.pt"
SILERO_SPEAKER = "xenia"
SILERO_SAMPLE_RATE = 8000

# Whisper config
WHISPER_MODEL_SIZE = "tiny"
WHISPER_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
WHISPER_COMPUTE = "float16" if WHISPER_DEVICE == "cuda" else "int8"
WHISPER_LANGUAGE = None
WHISPER_SAMPLE_RATE = 16000

FRAME_MS = 20
VAD_AGGRESSIVENESS = 2
PRE_ROLL_MS = 300
END_SILENCE_MS = 500
MAX_UTT_SLEEP_SEC = 3.0
MAX_UTT_ACTIVE_SEC = 20.0
VAD_SUPPORTED_RATES = [16000, 48000, 32000, 8000]
ACTIVE_IDLE_TIMEOUT_SEC = 60

# Memory tunables
RECALL_MEMORY_LIMIT = 40   # compress to archival after this many stored turns
RAG_RECALL_K    = 2        # recall hits to inject as context
RAG_ARCHIVAL_K  = 2        # archival hits to inject as context

# =========================
# TEXT HELPERS
# =========================
def normalize_text(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\sа-яё]", " ", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s)


def contains_phrase(text: str, phrases: List[str]) -> bool:
    t = normalize_text(text)
    t_nospace = t.replace(" ", "")
    for p in phrases:
        p_norm = normalize_text(p)
        if p_norm in t or p_norm.replace(" ", "") in t_nospace:
            return True
    return False


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
# MEMORY HELPERS
# RAG retrieval runs BEFORE the LLM call (read-only → does not bust KV-cache prefix).
# Memory writes happen AFTER the response in a daemon thread.
# The system prompt is rebuilt only when core memory actually changes (dirty flag),
# which keeps the KV-cache prefix stable across turns where nothing new was learned.
# =========================

# ── last-seen persistence (cross-session ContextManager) ──────────────────
_LAST_SEEN_FILE = None  # set after MEMORY_DIR is known; see _init_last_seen()


def _init_last_seen():
    global _LAST_SEEN_FILE
    _LAST_SEEN_FILE = os.path.join(MEMORY_DIR, "boxy_last_seen.json")


def load_last_seen() -> Optional[datetime]:
    """Return timestamp of the last interaction, or None on first run."""
    if not _LAST_SEEN_FILE:
        return None
    try:
        with open(_LAST_SEEN_FILE) as f:
            ts = json.load(f).get("last_seen")
        return datetime.fromisoformat(ts) if ts else None
    except Exception:
        return None


def save_last_seen():
    """Persist the current time as the last-seen timestamp."""
    if not _LAST_SEEN_FILE:
        return
    try:
        with open(_LAST_SEEN_FILE, 'w') as f:
            json.dump({"last_seen": datetime.now().isoformat()}, f)
    except Exception:
        pass


# ── learned-word detection ─────────────────────────────────────────────────
# Detect translation requests from the user and extract the taught word from
# the assistant's response.  Saves to the learned_words core block AND to
# archival memory (importance 9) so they survive recall compression.

_TRANS_REQUEST_RE = re.compile(
    r'\b(?:how do you say|how to say|what is|translate|what does|'
    r'что значит|как сказать|как будет|как по-русски)\s+([^?.,!]{2,40})',
    re.IGNORECASE,
)
# First Cyrillic "word" at the start of the response (translation answer pattern)
_FIRST_CYRILLIC_RE = re.compile(r'^([А-ЯЁа-яё][а-яёА-ЯЁ]+)')


def _detect_learned_words(user_text: str, assistant_text: str, core_mem, archival_mem) -> bool:
    """
    If the user asked for a translation and the assistant replied with a Russian
    word, save it to:
      1. core_mem 'learned_words' block  (always in context)
      2. archival_mem with importance=9  (survives recall compression)

    Returns True if a new word was saved.
    """
    m = _TRANS_REQUEST_RE.search(user_text)
    if not m:
        return False
    english_hint = m.group(1).strip().rstrip(".,!?").lower()

    # Extract the first Cyrillic word from the assistant response
    ru_match = _FIRST_CYRILLIC_RE.match(assistant_text.strip())
    if not ru_match:
        return False
    russian_word = ru_match.group(1)

    entry = f"{russian_word} ({english_hint})"

    # 1. Core memory learned_words block
    saved_to_core = False
    if core_mem:
        learned_block = core_mem.get_block("learned_words")
        if learned_block:
            lines = [ln.strip() for ln in learned_block.value.splitlines() if ln.strip()]
            if entry not in lines:
                lines.append(entry)
                # Cap at 80 lines — drop oldest
                if len(lines) > 80:
                    lines = lines[-80:]
                new_val = "\n".join(lines)
                if len(new_val) <= learned_block.limit:
                    learned_block.value = new_val
                    from datetime import datetime as _dt
                    learned_block.metadata["last_modified"] = _dt.now().isoformat()
                    core_mem.save()
                    saved_to_core = True
                    print(f"[Memory] Learned word saved to core: {entry}")

    # 2. Archival memory (high importance so it outlasts recall compression)
    if archival_mem:
        archival_mem.insert("vocabulary", entry, importance=9)
        print(f"[Memory] Learned word archived: {entry}")

    return saved_to_core


# ── personal-fact archival (direct insert when auto_extract saves something) ─
def _archive_personal_fact(fact: str, archival_mem):
    """Save an extracted personal fact to archival with importance=7."""
    if archival_mem:
        try:
            archival_mem.insert("personal_fact", fact, importance=7)
        except Exception:
            pass


_NAME_RE      = re.compile(r'\bmy name is\s+([A-Za-z]+)', re.IGNORECASE)
_CALL_ME_RE   = re.compile(r'\bcall me\s+([A-Za-z]+)\b', re.IGNORECASE)
_LOVE_RE      = re.compile(r'\b(i love|i like|my favou?rite)\s+([^,.!?\n]{3,50})', re.IGNORECASE)
_DONT_LIKE_RE = re.compile(r"\bi don'?t like\s+([^,.!?\n]{3,40})", re.IGNORECASE)
_HAVE_RE      = re.compile(r'\bi have (?:a |an )?([A-Za-z]+(?: [A-Za-z]+)?)\b', re.IGNORECASE)
_FAMILY_RE    = re.compile(
    r'\bmy (mom|mother|dad|father|sister|brother|grandma|grandpa)\s+(?:is\s+)?([^,.!?\n]{2,40})',
    re.IGNORECASE,
)
_AGE_RE       = re.compile(r"\bI'?m\s+(\d{1,2})\s*years?\s*old\b", re.IGNORECASE)
_REMEMBER_RE  = re.compile(
    r"what do you remember|what'?s? my name|do you remember me|remember about me|"
    r"what do you know about me|tell me what you know",
    re.IGNORECASE,
)


def _expand_query(query: str) -> str:
    if _REMEMBER_RE.search(query):
        return query + " name interests likes pets family"
    return query


def auto_extract_facts(user_input: str, core_mem) -> List[str]:
    """
    Extract personal facts from user text using regex and write them to the
    core memory 'human' block.
    Returns list of newly saved fact strings (empty if nothing changed).
    Called AFTER the LLM response so the KV-cache prefix is not invalidated
    on the same turn the fact is first written.
    """
    block = core_mem.get_block("human")
    if not block:
        return []

    new_facts: List[str] = []
    queued = []

    m = _NAME_RE.search(user_input)
    if m:
        name = m.group(1).capitalize()
        if name.lower() not in {"a", "an", "the", "my", "your", "not"} and name not in block.value:
            success, _ = block.replace_line_by_key("User's name:", f"User's name: {name}.")
            if success:
                new_facts.append(f"User's name: {name}.")
                print(f"[Memory] Auto-saved name: {name}")

    m = _CALL_ME_RE.search(user_input)
    if m:
        name = m.group(1).capitalize()
        if name.lower() not in {"a", "an", "the", "my", "your", "not"} and name not in block.value:
            success, _ = block.replace_line_by_key("User's name:", f"User's name: {name}.")
            if success:
                new_facts.append(f"User's name: {name}.")
                print(f"[Memory] Auto-saved name (call me): {name}")

    for m in _LOVE_RE.finditer(user_input):
        interest = m.group(2).strip().rstrip(".,!?")
        entry = f"User likes: {interest}."
        if entry not in block.value:
            queued.append(entry)

    for m in _DONT_LIKE_RE.finditer(user_input):
        dislike = m.group(1).strip().rstrip(".,!?")
        entry = f"User dislikes: {dislike}."
        if entry not in block.value:
            queued.append(entry)

    m = _HAVE_RE.search(user_input)
    if m:
        thing = m.group(1)
        entry = f"User has: {thing}."
        if entry not in block.value:
            queued.append(entry)

    for m in _FAMILY_RE.finditer(user_input):
        role = m.group(1).lower()
        desc = m.group(2).strip().rstrip(".,!?")
        entry = f"User family: {role} — {desc}."
        if entry not in block.value:
            queued.append(entry)

    m = _AGE_RE.search(user_input)
    if m:
        age = m.group(1)
        entry = f"User age: {age} years."
        if entry not in block.value:
            queued.append(entry)

    for fact in queued:
        success, _ = block.append(f"\n{fact}")
        if success:
            new_facts.append(fact)
            print(f"[Memory] Auto-saved: {fact}")

    if new_facts:
        core_mem.save()

    return new_facts


def retrieve_relevant_context(user_input: str, recall_mem, archival_mem) -> str:
    """
    Fast text-based RAG: SQLite LIKE search on recall + archival memory.
    No embeddings — near-instant.  Returns compact string or "" if nothing found.
    This string is prepended to the user message (not the system prompt) so the
    system-prompt KV-cache prefix stays intact.
    """
    try:
        expanded = _expand_query(user_input)
        hits  = recall_mem.search(expanded, limit=RAG_RECALL_K)
        facts = archival_mem.search(expanded, limit=RAG_ARCHIVAL_K)
        if not hits and not facts:
            return ""
        parts = []
        if hits:
            parts.append("[RECENT CONTEXT]")
            for h in hits:
                parts.append(f"  {h['role']}: {h['content'][:60]}")
        if facts:
            parts.append("[KNOWN FACTS]")
            for f in facts:
                parts.append(f"  - {f['content'][:60]}")
        return "\n".join(parts)
    except Exception as e:
        print(f"[Memory] RAG error: {e}")
        return ""


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
        "reasoning_effort": "none",
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
            token = ""
            if "content" in delta:
                token = delta["content"]
            elif "reasoning_content" in delta:
                # skip reasoning tokens — not for TTS
                continue
            elif "text" in delta:
                token = delta["text"]
            if token:
                yield token


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
        self.state = State(mode="SLEEP", last_activity=time.time())
        self.audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=400)
        self.audio_tracker = AudioStateTracker()

        # ── Memory system ──────────────────────────────────────────────────
        self.core_mem     = None
        self.recall_mem   = None
        self.archival_mem = None
        self.ctx_mgr      = None
        self.personality  = None
        # _mem_dirty: set True by async thread when core memory changes;
        # causes system prompt to be rebuilt on the NEXT turn (not the current
        # one) so the KV-cache prefix stays valid for the current response.
        self._mem_dirty   = False
        self._mem_lock    = threading.Lock()

        if MEMORY_AVAILABLE:
            try:
                os.makedirs(MEMORY_DIR, exist_ok=True)
                _init_last_seen()

                self.core_mem     = Memory(db_path=os.path.join(MEMORY_DIR, "boxy_core.db"))
                self.recall_mem   = RecallMemory(
                    db_path=os.path.join(MEMORY_DIR, "boxy_recall.db"),
                    use_semantic=False,   # text search — no embedding latency
                )
                self.archival_mem = ArchivalMemory(
                    db_path=os.path.join(MEMORY_DIR, "boxy_archival.db"),
                    use_semantic=False,
                )

                # ContextManager: seed with persisted last_interaction so the
                # time-since-last-chat hint is correct across sessions.
                self.ctx_mgr = ContextManager()
                last_seen = load_last_seen()
                if last_seen:
                    self.ctx_mgr.update_interaction(
                        InteractionContext(last_interaction=last_seen)
                    )

                # PersonalityEngine: loads personality.json from MEMORY_DIR if present.
                import os as _os
                _personality_file = _os.path.join(MEMORY_DIR, "boxy_personality.json")
                try:
                    import json as _json
                    with open(_personality_file) as _f:
                        _pdata = _json.load(_f)
                    from personality_system import PersonalityProfile
                    self.personality = PersonalityEngine(PersonalityProfile(**_pdata))
                    print("[Memory] Personality profile loaded.")
                except (FileNotFoundError, Exception):
                    self.personality = PersonalityEngine()  # default: humor=50 honesty=90 sass=20

                print("[Memory] Memory system initialized.")
            except Exception as e:
                print(f"[Memory] Init error: {e}. Running without memory.")
                self.core_mem = self.recall_mem = self.archival_mem = self.ctx_mgr = None
                self.personality = None

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

        self.mic_device, self.sample_rate = self._pick_input_device_and_rate()
        self.frame_samples = int(self.sample_rate * FRAME_MS / 1000)
        self.frame_bytes = self.frame_samples * 2
        print(f"[Init] Mic device: {self._describe_input_device(self.mic_device)}")
        print(f"[Init] Mic sample rate: {self.sample_rate} Hz")

        self.whisper = WhisperSTT()

        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.capture = VadAudioCapture(self.vad, self.sample_rate, FRAME_MS)

        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt()}
        ]
        self.mic_gate_until = 0.0
        print("[Init] Assistant ready.")

    # ── System prompt ──────────────────────────────────────────────────────
    # The system prompt includes the fixed personality rules + compact core
    # memory (known user facts + learned words).  It is rebuilt only when
    # core memory changes (dirty flag), so llama.cpp's KV-cache can reuse the
    # prefix on turns where nothing new was learned.
    # RAG context is NOT put here — it goes in the user message instead so
    # the cache prefix is not busted on every single turn.
    def _build_system_prompt(self) -> str:
        base = (
            "LANGUAGE RULE: You must ALWAYS respond in Russian using Cyrillic script only. "
            "This rule is absolute. It does not matter what language the user speaks. "
            "You allowed to use other languages ONLY when asked for translation. "
            "Every response must be 100% Russian Cyrillic unless translation is asked. "
            "\n\n"
            "You are Boxy, a friendly Russian tutor. "
            "Reply in 2-3 short sentences. No markdown, no lists, no emojis. "
            "For translation requests: give the Russian word and one example sentence. "
            "If unclear: ask one short question in Russian. "
            "\n\n"
            "REMINDER: Respond in Russian Cyrillic only, regardless of input language."
        )

        if self.core_mem:
            # Persona block — who Boxy is (editable via core memory DB)
            persona_block = self.core_mem.get_block("persona")
            if persona_block and persona_block.value.strip():
                base += f"\n\n[PERSONA]\n{persona_block.value.strip()}"

            # Human block — known facts about this specific user
            human_block = self.core_mem.get_block("human")
            if human_block and human_block.value.strip():
                base += f"\n\n[USER INFO]\n{human_block.value.strip()}"

            # Learned words — keep last 20 to stay compact
            learned_block = self.core_mem.get_block("learned_words")
            if learned_block and learned_block.value.strip():
                lines = [ln.strip() for ln in learned_block.value.splitlines() if ln.strip()]
                if lines:
                    base += "\n\n[LEARNED WORDS]\n" + ", ".join(lines[-20:])

        # NOTE: PersonalityEngine and ContextManager are intentionally excluded
        # from the system prompt. Both add tokens (which the thinking model
        # Gemma 4 E2B must process before generating any content), while
        # providing minimal practical value for a voice tutor:
        #   - Personality percentages are decorative and add ~15 tokens per turn.
        #   - "We last spoke X minutes ago" changes every minute, increases prompt
        #     length, and busts the KV-cache prefix whenever the system prompt is
        #     rebuilt. The tutor persona is already fully defined above.

        return base

    def _describe_input_device(self, device) -> str:
        if device is None:
            return "system default"
        try:
            info = sd.query_devices(device, "input")
            suffix = f" (id={device})" if isinstance(device, int) else ""
            return f"{info['name']}{suffix}"
        except Exception:
            return f"{device!r}"

    def _default_input_device(self):
        try:
            default_device = sd.default.device
        except Exception:
            return None

        if isinstance(default_device, (tuple, list)):
            default_input = default_device[0] if default_device else None
        else:
            default_input = default_device

        if isinstance(default_input, int) and default_input < 0:
            return None
        return default_input

    def _iter_input_device_candidates(self):
        seen = set()
        candidates = []

        def add(device):
            key = (type(device).__name__, device)
            if device is None and key in seen:
                return
            if key in seen:
                return
            seen.add(key)
            candidates.append(device)

        add(MIC_DEVICE)
        add(self._default_input_device())
        add(None)
        add(LEGACY_MIC_DEVICE)

        try:
            for idx, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) > 0:
                    add(idx)
        except Exception as e:
            print(f"[Mic] Could not enumerate audio devices: {e}")

        return candidates

    def _pick_input_device_and_rate(self) -> Tuple[object, int]:
        errors = []

        for device in self._iter_input_device_candidates():
            label = self._describe_input_device(device)
            for sr in VAD_SUPPORTED_RATES:
                try:
                    sd.check_input_settings(
                        device=device,
                        samplerate=sr,
                        channels=1,
                        dtype="int16",
                    )
                    print(f"[Mic] Selected input device {label} @ {sr} Hz")
                    return device, sr
                except Exception as e:
                    errors.append(f"{label} @ {sr} Hz -> {e}")

        tried = "\n".join(f"  - {item}" for item in errors[-12:])
        raise RuntimeError(
            "No usable microphone input device was found. "
            f"Tried {len(errors)} device/rate combinations:\n{tried}"
        )

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
        if not text:
            return ""
        # Discard Whisper hallucinations — repetitive noise produces very long output
        if len(text) > 300:
            print(f"[STT] Discarding likely hallucination ({len(text)} chars)")
            return ""
        print(f"[STT] {text}")
        return text

    def _respond_with_llm(self, user_text: str):
        # ── Step 1: rebuild system prompt if memory changed since last turn ──
        # This is the ONLY place we touch messages[0]; async thread only sets
        # the flag, never modifies messages directly (thread-safety).
        with self._mem_lock:
            dirty = self._mem_dirty
            self._mem_dirty = False
        if dirty:
            self.messages[0] = {"role": "system", "content": self._build_system_prompt()}
            print("[Memory] System prompt refreshed with updated core memory.")

        # ── Update ContextManager timestamp (cross-session time hint) ─────
        if self.ctx_mgr:
            self.ctx_mgr.update_interaction(
                InteractionContext(last_interaction=datetime.now())
            )
        # save_last_seen() moved to async thread — no need to block the LLM call

        # ── Step 2: RAG — fast read-only SQLite text search ───────────────
        # Injected as a prefix on the user message so the system-prompt
        # KV-cache prefix is not affected.
        # Skip entirely when recall is empty (new session) to avoid overhead.
        user_content = user_text
        if self.recall_mem and self.archival_mem and self.recall_mem.get_count() > 0:
            rag = retrieve_relevant_context(user_text, self.recall_mem, self.archival_mem)
            if rag:
                user_content = f"{rag}\n\n{user_text}"

        user_msg = {"role": "user", "content": user_content}
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
                print(full_response)
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

            # ── Step 3: async memory writes (does not block next turn) ────
            if self.recall_mem:
                threading.Thread(
                    target=self._async_memory_ops,
                    args=(user_text, assistant_text),
                    daemon=True,
                ).start()

        except Exception as e:
            print(f"[LLM ERROR] {e}")
            traceback.print_exc()

            if self.messages and self.messages[-1].get("role") == "user" and self.messages[-1].get("content") == user_content:
                self.messages.pop()
                self._trim_history()

            self.tts.say("Извини, у меня возникла проблема.")

        self.mic_gate_until = time.time() + 0.5

    def _async_memory_ops(self, user_text: str, assistant_text: str):
        """
        Runs in a daemon thread after each successful LLM turn.

        Order:
        1. auto_extract_facts  — regex-based personal facts → core memory + archival
        2. _detect_learned_words — translation detection → learned_words block + archival
        3. recall insert       — stores the full turn for future RAG
        4. compression         — moves old recall into archival when over limit

        Sets _mem_dirty when core memory changes so the next turn rebuilds
        the system prompt (keeping the KV-cache prefix valid this turn).
        """
        try:
            core_dirty = False

            # 1. Personal fact extraction — writes to core_mem 'human' block
            if self.core_mem:
                new_facts = auto_extract_facts(user_text, self.core_mem)
                if new_facts:
                    core_dirty = True
                    # Also archive each fact so it survives recall compression
                    for fact in new_facts:
                        _archive_personal_fact(fact, self.archival_mem)

            # 2. Learned-word detection — writes to 'learned_words' block + archival
            if self.core_mem:
                word_saved = _detect_learned_words(
                    user_text, assistant_text, self.core_mem, self.archival_mem
                )
                if word_saved:
                    core_dirty = True

            if core_dirty:
                with self._mem_lock:
                    self._mem_dirty = True

            # 3. Store turn in recall (defer_embedding=True → no blocking encode)
            self.recall_mem.insert("user",      user_text,      defer_embedding=True)
            self.recall_mem.insert("assistant", assistant_text, defer_embedding=True)

            # 3b. Persist last-seen timestamp (async — no need to block LLM turns)
            save_last_seen()

            # 4. Compress old recall into archival when over limit
            if self.recall_mem.get_count() > RECALL_MEMORY_LIMIT and self.archival_mem:
                keep = max(10, RECALL_MEMORY_LIMIT - 15)
                n = self.recall_mem.compress_old_memories(
                    lambda text: text[:300],   # simple truncation — no extra LLM call
                    self.archival_mem,
                    keep_recent=keep,
                )
                if n > 0:
                    print(f"[Memory] Compressed {n} old recall entries into archival.")

        except Exception as e:
            print(f"[Memory] Async ops error: {e}")
            traceback.print_exc()

    def run_forever(self):
        print("==============================================")
        print("Assistant running.")
        print(f"Input device: {self._describe_input_device(self.mic_device)}")
        print(f"Sample rate: {self.sample_rate} Hz | Frame: {FRAME_MS} ms")
        print(f"Wake words: {WAKE_WORDS}")
        print(f"Memory: {'enabled' if self.core_mem else 'disabled'}")
        print("==============================================")

        with sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_samples,
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
            device=self.mic_device,
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
