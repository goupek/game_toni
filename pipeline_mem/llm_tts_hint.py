from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    import numpy as np
except Exception as exc:  # pragma: no cover - optional runtime dependency
    np = None
    _NUMPY_IMPORT_ERROR = exc
else:
    _NUMPY_IMPORT_ERROR = None

try:
    import requests
except Exception as exc:  # pragma: no cover - optional runtime dependency
    requests = None
    _REQUESTS_IMPORT_ERROR = exc
else:
    _REQUESTS_IMPORT_ERROR = None

try:
    import torch
except Exception as exc:  # pragma: no cover - optional runtime dependency
    torch = None
    _TORCH_IMPORT_ERROR = exc
else:
    _TORCH_IMPORT_ERROR = None

from question_generation import ADJECTIVES, NOUNS, NUM_WORD


_ROOT = Path(__file__).resolve().parent.parent

LLAMA_URL = os.getenv("BOXY_LLAMA_URL", "http://localhost:8080/v1/chat/completions")
LLAMA_MODEL = os.getenv("BOXY_LLAMA_MODEL", "gemma-4-e2b-it-q4_k_m")
LLAMA_NUM_PREDICT = int(os.getenv("BOXY_HINT_MAX_TOKENS", "160"))
LLAMA_TEMPERATURE = float(os.getenv("BOXY_HINT_TEMPERATURE", "0.3"))
LLAMA_TIMEOUT_SEC = int(os.getenv("BOXY_HINT_TIMEOUT_SEC", "45"))

SILERO_MODEL_PATH = Path(
    os.getenv("BOXY_SILERO_MODEL", str(_ROOT / "models" / "silero" / "v5_ru.pt"))
)
SILERO_SPEAKER = os.getenv("BOXY_SILERO_SPEAKER", "xenia")
SILERO_SAMPLE_RATE = int(os.getenv("BOXY_SILERO_SAMPLE_RATE", "8000"))
_SILERO_TTS_CLI = _ROOT / "pipeline_mem" / "silero_tts_cli.py"

_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_RUSSIAN_ADJECTIVE_ENDINGS = (
    "ыми",
    "ими",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ых",
    "их",
    "ую",
    "юю",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ый",
    "ий",
    "ой",
    "ым",
    "им",
    "ом",
    "ем",
)
_RUSSIAN_NOUN_ENDINGS = (
    "иями",
    "ями",
    "ами",
    "ов",
    "ев",
    "ей",
    "ом",
    "ем",
    "ой",
    "ей",
    "ью",
    "ах",
    "ях",
    "ам",
    "ям",
    "ы",
    "и",
    "а",
    "я",
    "у",
    "ю",
    "е",
    "о",
    "ь",
)


def strip_markdown(text: str) -> str:
    return re.sub(r"[*_~`#>\[\]()]", "", text)


def _normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("ё", "е")
    text = re.sub(r"[^\w\sа-яё]", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC_RE.search(text))


def _noun_display(round_data: Dict) -> str:
    noun_key = round_data.get("noun_key", "")
    noun_forms = NOUNS.get(noun_key, {})
    count = int(round_data.get("count", 1) or 1)
    if count == 1:
        return noun_forms.get("sg") or noun_forms.get("pl") or "предмет"
    return noun_forms.get("pl") or noun_forms.get("gen_pl") or noun_forms.get("sg") or "предметы"


def _fallback_hint(round_data: Dict, attempt_number: int = 0, wrong_answers: Optional[List[str]] = None) -> str:
    is_retry = attempt_number > 0 or bool(wrong_answers)
    if is_retry and round_data.get("hint_fallback_retry"):
        return str(round_data["hint_fallback_retry"])
    if round_data.get("hint_fallback"):
        return str(round_data["hint_fallback"])

    noun_text = _noun_display(round_data)
    qtype = round_data.get("qtype")

    if qtype == "count":
        if attempt_number > 0 or wrong_answers:
            return (
                f"Сосчитай {noun_text} по одному и не пропускай ни один предмет. "
                "Потом спокойно сравни результат со всеми вариантами."
            )
        return (
            f"Сначала внимательно сосчитай {noun_text} на картинке. "
            "Потом выбери вариант, который лучше всего подходит по смыслу."
        )

    if attempt_number > 0 or wrong_answers:
        return (
            f"Еще раз посмотри на {noun_text} и сравни именно их оттенок. "
            "Не спеши и выбери слово, которое точнее всего описывает цвет."
        )
    return (
        f"Внимательно посмотри на {noun_text} на картинке и сравни их цвет с вариантами. "
        "Ищи слово, которое лучше всего подходит к оттенку."
    )


def _round_payload(round_data: Dict, attempt_number: int, wrong_answers: Optional[List[str]]) -> Dict:
    custom_payload = round_data.get("hint_prompt_context")
    if isinstance(custom_payload, dict):
        payload = dict(custom_payload)
        payload.setdefault("attempt_number_current_round", attempt_number)
        payload.setdefault("wrong_attempts_count_this_round", len(wrong_answers or []))
        return payload

    noun_key = round_data.get("noun_key", "")
    payload = {
        "question_type": round_data.get("qtype", ""),
        "prompt_text_ru": round_data.get("prompt_text", ""),
        "noun_forms_ru": NOUNS.get(noun_key, {}),
        "attempt_number_current_round": attempt_number,
        "wrong_attempts_count_this_round": len(wrong_answers or []),
    }
    if round_data.get("qtype") == "color":
        payload["hint_goal_ru"] = (
            "Подскажи только способ сравнить цвет на картинке с вариантами. "
            "Не называй цвета, оттенки, цветовые семьи и похожие слова."
        )
    elif round_data.get("qtype") == "count":
        payload["hint_goal_ru"] = (
            "Подскажи только способ пересчитать предметы и проверить себя. "
            "Не называй числа и не намекай на ответ перечислением."
        )
    return payload


def _hint_goal(round_data: Dict) -> str:
    if round_data.get("hint_goal_ru"):
        return str(round_data["hint_goal_ru"])

    if round_data.get("qtype") == "color":
        return (
            "Подскажи только способ сравнить цвет на картинке с вариантами. "
            "Не называй цвета, оттенки, цветовые семьи и похожие слова."
        )
    if round_data.get("qtype") == "count":
        return (
            "Подскажи только способ пересчитать предметы и проверить себя. "
            "Не называй числа и не намекай на ответ перечислением."
        )
    return "Подскажи только следующий безопасный шаг и не раскрывай готовое решение."


def _build_hint_messages(round_data: Dict, attempt_number: int, wrong_answers: Optional[List[str]]) -> List[Dict[str, str]]:
    parts = [
        "Ты помогаешь ребенку в игре по русскому языку.",
        "Отвечай только по-русски, только кириллицей, очень коротко.",
        "Дай одну безопасную подсказку на 1-2 коротких предложения.",
        "Подсказка должна говорить только о действии: как смотреть, сравнивать, считать или проверять шаги.",
        _hint_goal(round_data),
        "Нельзя раскрывать ответ ни прямо, ни косвенно.",
        "Нельзя повторять правильный ответ, варианты ответа, запрещенные слова или похожие на них слова.",
    ]
    if round_data.get("qtype") == "color":
        parts.append(
            "Если вопрос про цвет, вообще не называй никакие цвета, оттенки, цветовые семьи, "
            "ассоциации с предметами природы и слова с тем же корнем."
        )
    if round_data.get("qtype") == "count":
        parts.append(
            "Если вопрос про количество, вообще не называй числа и не перечисляй предметы до ответа."
        )
    if round_data.get("hint_extra_rules_ru"):
        parts.append(str(round_data["hint_extra_rules_ru"]))
    parts.append("Хороший стиль: Сравни все предметы спокойно. Считай по одному слева направо.")
    system_text = " ".join(parts)
    user_text = (
        "Сформулируй безопасную подсказку для этого раунда.\n\n"
        f"{json.dumps(_round_payload(round_data, attempt_number, wrong_answers), ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]


def _iter_sse_tokens(messages: List[Dict[str, str]]):
    if requests is None:
        raise RuntimeError(f"requests import failed: {_REQUESTS_IMPORT_ERROR}")

    payload = {
        "model": LLAMA_MODEL,
        "messages": messages,
        "temperature": LLAMA_TEMPERATURE,
        "max_tokens": LLAMA_NUM_PREDICT,
        "stream": True,
        "reasoning_effort": "none",
        "cache_prompt": False,
    }

    with requests.post(
        LLAMA_URL,
        json=payload,
        stream=True,
        timeout=(10, LLAMA_TIMEOUT_SEC),
    ) as response:
        if response.status_code >= 400:
            try:
                body = response.text
            except Exception:
                body = "<unable to read response body>"
            raise RuntimeError(f"llama.cpp HTTP {response.status_code}: {body}")

        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            if raw_line.startswith(b"data: "):
                raw_line = raw_line[len(b"data: "):]
            if raw_line == b"[DONE]":
                break

            try:
                data = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if "error" in data:
                raise RuntimeError(f"llama.cpp server error: {data['error']}")

            choices = data.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            token = delta.get("content") or delta.get("text") or ""
            if token:
                yield token


def _sanitize_hint_text(text: str) -> str:
    text = strip_markdown(text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text


def _forbidden_terms(round_data: Dict) -> List[str]:
    terms = []
    extra_terms = round_data.get("forbidden_terms", [])
    if isinstance(extra_terms, str):
        terms.append(extra_terms)
    else:
        terms.extend(extra_terms)

    terms.append(round_data.get("correct", ""))
    terms.extend(round_data.get("options", []))

    if round_data.get("qtype") == "count":
        count = round_data.get("count")
        if count is not None:
            terms.append(str(count))
            number_forms = NUM_WORD.get(count, "")
            if isinstance(number_forms, dict):
                terms.extend(number_forms.values())
            elif number_forms:
                terms.append(str(number_forms))

    if round_data.get("qtype") == "color":
        adj_key = round_data.get("adj_key", "")
        forms = ADJECTIVES.get(adj_key, {})
        terms.extend(forms.values())

    return [term for term in terms if term]


def _word_stem(word: str) -> str:
    for ending in _RUSSIAN_ADJECTIVE_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def _noun_stem(word: str) -> str:
    for ending in _RUSSIAN_NOUN_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def _forbidden_color_stems(round_data: Dict) -> List[str]:
    if round_data.get("qtype") != "color":
        return []

    stems: List[str] = []
    seen = set()
    for term in _forbidden_terms(round_data):
        for word in _normalize_text(term).split():
            stem = _word_stem(word)
            if stem == word or len(stem) < 3 or stem in seen:
                continue
            seen.add(stem)
            stems.append(stem)
    return stems


def _forbidden_custom_stems(round_data: Dict) -> List[str]:
    extra_terms = round_data.get("forbidden_terms", [])
    if isinstance(extra_terms, str):
        extra_terms = [extra_terms]

    stems: List[str] = []
    seen = set()
    for term in extra_terms:
        for word in _normalize_text(str(term)).split():
            stem = _noun_stem(_word_stem(word))
            if len(stem) < 3 or stem in seen:
                continue
            seen.add(stem)
            stems.append(stem)
    return stems


def _spoils_answer(text: str, round_data: Dict) -> bool:
    normalized_plain = _normalize_text(text)
    normalized_text = f" {normalized_plain} "
    if not normalized_text:
        return True

    for term in _forbidden_terms(round_data):
        normalized_term = _normalize_text(term)
        if normalized_term and f" {normalized_term} " in normalized_text:
            return True

    for word in normalized_plain.split():
        for stem in _forbidden_color_stems(round_data):
            if word.startswith(stem):
                return True
        for stem in _forbidden_custom_stems(round_data):
            if word.startswith(stem):
                return True
    return False


def _python_has_tts_stack(python_executable: str) -> bool:
    try:
        probe = subprocess.run(
            [
                python_executable,
                "-c",
                "import numpy, torch; print('ok')",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return False
    return probe.returncode == 0 and "ok" in (probe.stdout or "")


def _find_external_tts_python() -> Optional[str]:
    candidates = []
    env_python = os.getenv("BOXY_TTS_PYTHON")
    if env_python:
        candidates.append(env_python)
    candidates.extend([sys.executable, "/usr/bin/python3", "/usr/bin/python"])

    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if not Path(candidate).exists():
            continue
        if _python_has_tts_stack(candidate):
            return candidate
    return None


class _TTSWorker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._stop = threading.Event()
        self._queue: "queue.Queue[str]" = queue.Queue(maxsize=20)
        self._model = None
        self._init_attempted = False
        self.active = threading.Event()
        self.device = torch.device("cpu") if torch is not None else None
        self.external_python: Optional[str] = None

    def stop(self):
        self._stop.set()
        try:
            self._queue.put_nowait("")
        except queue.Full:
            pass

    def is_speaking(self) -> bool:
        return self.active.is_set() or not self._queue.empty()

    def say(self, text: str):
        text = _sanitize_hint_text(text)
        if not text:
            return
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            print("[Hint TTS] Queue full, dropping hint.")

    def _lazy_init(self) -> bool:
        if self._model is not None:
            return True
        if self.external_python is not None:
            return True
        if self._init_attempted:
            return False

        self._init_attempted = True

        can_try_in_process = (
            torch is not None
            and np is not None
            and SILERO_MODEL_PATH.exists()
        )
        if can_try_in_process:
            try:
                importer = torch.package.PackageImporter(str(SILERO_MODEL_PATH))
                self._model = importer.load_pickle("tts_models", "model")
                self._model.to(self.device)
                with torch.no_grad():
                    _ = self._model.apply_tts(
                        text="Привет.",
                        speaker=SILERO_SPEAKER,
                        sample_rate=SILERO_SAMPLE_RATE,
                    )
                return True
            except Exception as exc:
                print(f"[Hint TTS] In-process Silero unavailable: {exc}")
                traceback.print_exc()
                self._model = None

        self.external_python = _find_external_tts_python()
        if self.external_python:
            print(f"[Hint TTS] Using external Python fallback: {self.external_python}")
            return True

        if torch is None:
            print(f"[Hint TTS] torch import failed: {_TORCH_IMPORT_ERROR}")
        elif np is None:
            print(f"[Hint TTS] numpy import failed: {_NUMPY_IMPORT_ERROR}")
        elif not SILERO_MODEL_PATH.exists():
            print(f"[Hint TTS] Missing Silero model: {SILERO_MODEL_PATH}")
        return False

    def _synthesize_with_external_python(self, text: str):
        if not self.external_python:
            return
        try:
            self.active.set()
            proc = subprocess.run(
                [self.external_python, str(_SILERO_TTS_CLI), text],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "").strip()
                print(f"[Hint TTS] External fallback failed: {err}")
        finally:
            self.active.clear()

    def _synthesize_and_play(self, text: str):
        if not self._lazy_init():
            return
        if not _has_cyrillic(text):
            print(f"[Hint TTS] Skipping non-Cyrillic hint: {text!r}")
            return
        if self.external_python is not None and self._model is None:
            self._synthesize_with_external_python(text)
            return

        try:
            self.active.set()
            with torch.no_grad():
                audio = self._model.apply_tts(
                    text=text,
                    speaker=SILERO_SPEAKER,
                    sample_rate=SILERO_SAMPLE_RATE,
                )

            wav = audio.detach().cpu().numpy().astype(np.float32, copy=False)
            proc = subprocess.Popen(
                ["aplay", "-q", "-r", str(SILERO_SAMPLE_RATE), "-f", "FLOAT_LE", "-c", "1", "-"],
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _, err = proc.communicate(input=wav.tobytes())
            if proc.returncode != 0:
                print(f"[Hint TTS] aplay failed: {err.decode(errors='replace').strip()}")
        except Exception as exc:
            print(f"[Hint TTS] Playback error: {exc}")
            traceback.print_exc()
        finally:
            self.active.clear()

    def run(self):
        while not self._stop.is_set():
            text = self._queue.get()
            if self._stop.is_set():
                break
            if not text:
                continue
            self._synthesize_and_play(text)


class HintEngine:
    def __init__(self):
        self._tts = _TTSWorker()
        self._tts.start()

    def stop(self):
        self._tts.stop()

    def is_speaking(self) -> bool:
        return self._tts.is_speaking()

    def speak(self, text: str):
        self._tts.say(text)

    def generate_hint(
        self,
        round_data: Dict,
        attempt_number: int = 0,
        wrong_answers: Optional[List[str]] = None,
    ) -> str:
        fallback = _fallback_hint(round_data, attempt_number=attempt_number, wrong_answers=wrong_answers)

        try:
            messages = _build_hint_messages(round_data, attempt_number, wrong_answers)
            chunks = [token for token in _iter_sse_tokens(messages)]
            hint_text = _sanitize_hint_text("".join(chunks))
            if not hint_text:
                return fallback
            if not _has_cyrillic(hint_text):
                return fallback
            if _spoils_answer(hint_text, round_data):
                print(f"[Hint] Rejected answer-spoiling hint: {hint_text!r}")
                return fallback
            return hint_text
        except Exception as exc:
            print(f"[Hint] Falling back to rule-based hint: {exc}")
            return fallback


class HintSession:
    def __init__(self, stop_audio: Optional[Callable[[], None]] = None):
        self._engine = HintEngine()
        self._stop_audio = stop_audio
        self._results: "queue.Queue[tuple[int, str]]" = queue.Queue()
        self.round_serial = 0
        self.hint_text = ""
        self.hint_loading = False

    def invalidate(self):
        self.round_serial += 1
        self.hint_text = ""
        self.hint_loading = False

    def is_speaking(self) -> bool:
        return self._engine.is_speaking()

    def speak_cached_hint(self):
        if self.hint_text and not self._engine.is_speaking():
            self._engine.speak(self.hint_text)

    def request_hint(
        self,
        round_data: Dict,
        attempt_number: int = 0,
        wrong_answers: Optional[List[str]] = None,
    ) -> bool:
        if self.hint_loading:
            return False

        if self._stop_audio:
            self._stop_audio()

        if self.hint_text:
            self.speak_cached_hint()
            return True

        self.hint_loading = True
        round_serial = self.round_serial
        threading.Thread(
            target=self._hint_worker,
            args=(round_serial, round_data, attempt_number, list(wrong_answers or [])),
            daemon=True,
        ).start()
        return True

    def _hint_worker(
        self,
        round_serial: int,
        round_data: Dict,
        attempt_number: int,
        wrong_answers: List[str],
    ):
        hint_text = self._engine.generate_hint(
            round_data,
            attempt_number=attempt_number,
            wrong_answers=wrong_answers,
        )
        self._results.put((round_serial, hint_text))

    def poll(self):
        while True:
            try:
                round_serial, hint_text = self._results.get_nowait()
            except queue.Empty:
                break

            if round_serial != self.round_serial:
                continue

            self.hint_loading = False
            self.hint_text = hint_text
            if self._stop_audio:
                self._stop_audio()
            self._engine.speak(hint_text)

    def shutdown(self):
        self._engine.stop()
