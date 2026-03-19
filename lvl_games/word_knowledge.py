"""
Shared word-knowledge store.

word_knowledge.json lives in the same folder as this module.

Schema
------
{
  "words": {
    "<en_key>": {
      "known":      true | false | null,   # null = never tested
      "ru_base":    "<masculine / base Russian form>",
      "ru_forms":   { "m": …, "f": …, "n": …, "pl": … }  (adj)
                  | { "sg": …, "pl": …, "gen_pl": … }      (noun)
                  | { "m": …, "f": …, "n": … }             (num 1-2)
                  | { "all": … }                            (num 3+)
      "gender":     "m"|"f"|"n"|"pl"|"indecl"  (nouns only)
      "topic":      "<topic id>",
      "source":     "vocab_db" | "game2"
    },
    …
  }
}

Known rules
-----------
- true  : kid answered the word correctly at least once in the level game
- false : kid answered incorrectly, or word present in vocab_db but never asked
- null  : word added by game2 startup but has NOT been tested by the level game

Grammatical forms
-----------------
The GAME2_* dicts below mirror the NOUNS / ADJECTIVES / NUM_WORD tables in
question_generation.py so that every Russian surface form produced by game2
can be reverse-looked-up to its English concept key.

_RU_FORM_TO_EN is built automatically from those dicts at import time and is
used in update_from_level_game() to map any tested Russian form back to the
right concept even if the form is not the masculine base stored in vocab_db.
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from database.db_queries import save_level_game_history, get_user_word_progress, upsert_user_word_progress

KNOWLEDGE_FILE = Path(__file__).resolve().parent / "word_knowledge.json"
BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "database" / "app.db"

# ── Canonical game2 adjective vocabulary ─────────────────────────────────────
# adj_key → { en, topic, ru_base, ru_forms{m,f,n,pl} }
# Mirrors ADJECTIVES dict in question_generation.py
GAME2_ADJECTIVES: Dict[str, Dict[str, Any]] = {
    "red": {
        "en": "red",        "topic": "colors",
        "ru_base": "красный",
        "ru_forms": {"m": "красный",    "f": "красная",    "n": "красное",    "pl": "красные"},
    },
    "blue": {
        "en": "blue",       "topic": "colors",
        "ru_base": "синий",
        "ru_forms": {"m": "синий",      "f": "синяя",      "n": "синее",      "pl": "синие"},
    },
    "light_blue": {
        "en": "light blue", "topic": "colors",
        "ru_base": "голубой",
        "ru_forms": {"m": "голубой",    "f": "голубая",    "n": "голубое",    "pl": "голубые"},
    },
    "green": {
        "en": "green",      "topic": "colors",
        "ru_base": "зелёный",
        "ru_forms": {"m": "зелёный",    "f": "зелёная",    "n": "зелёное",    "pl": "зелёные"},
    },
    "white": {
        "en": "white",      "topic": "colors",
        "ru_base": "белый",
        "ru_forms": {"m": "белый",      "f": "белая",      "n": "белое",      "pl": "белые"},
    },
    "yellow": {
        "en": "yellow",     "topic": "colors",
        "ru_base": "жёлтый",
        "ru_forms": {"m": "жёлтый",     "f": "жёлтая",     "n": "жёлтое",     "pl": "жёлтые"},
    },
    "purple": {
        "en": "purple",     "topic": "colors",
        "ru_base": "фиолетовый",
        "ru_forms": {"m": "фиолетовый", "f": "фиолетовая", "n": "фиолетовое", "pl": "фиолетовые"},
    },
    "pink": {
        "en": "pink",       "topic": "colors",
        "ru_base": "розовый",
        "ru_forms": {"m": "розовый",    "f": "розовая",    "n": "розовое",    "pl": "розовые"},
    },
    "grey": {
        "en": "grey",       "topic": "colors",
        "ru_base": "серый",
        "ru_forms": {"m": "серый",      "f": "серая",      "n": "серое",      "pl": "серые"},
    },
    "brown": {
        "en": "brown",      "topic": "colors",
        "ru_base": "коричневый",
        "ru_forms": {"m": "коричневый", "f": "коричневая", "n": "коричневое", "pl": "коричневые"},
    },
}

# ── Canonical game2 noun vocabulary ──────────────────────────────────────────
# noun_key → { en, topic, gender, ru_forms{sg,pl,gen_pl} }
# Mirrors NOUNS dict in question_generation.py
GAME2_NOUNS: Dict[str, Dict[str, Any]] = {
    "dog": {
        "en": "dog",  "topic": "animals",   "gender": "f",
        "ru_forms": {"sg": "собака", "pl": "собаки", "gen_pl": "собак"},
    },
    "cat": {
        "en": "cat",  "topic": "animals",   "gender": "f",
        "ru_forms": {"sg": "кошка",  "pl": "кошки",  "gen_pl": "кошек"},
    },
    "car": {
        "en": "car",  "topic": "transport", "gender": "f",
        "ru_forms": {"sg": "машина", "pl": "машины", "gen_pl": "машин"},
    },
    "ball": {
        "en": "ball", "topic": "toys",      "gender": "m",
        "ru_forms": {"sg": "мяч",    "pl": "мячи",   "gen_pl": "мячей"},
    },
}

# ── Canonical game2 number vocabulary ────────────────────────────────────────
# count (int) → { en, topic, ru_base, ru_forms }
# Mirrors NUM_WORD dict in question_generation.py
GAME2_COUNTS: Dict[int, Dict[str, Any]] = {
    1: {
        "en": "one",   "topic": "numbers", "ru_base": "один",
        "ru_forms": {"m": "один",    "f": "одна",    "n": "одно"},
    },
    2: {
        "en": "two",   "topic": "numbers", "ru_base": "два",
        "ru_forms": {"m": "два",     "f": "две",     "n": "два"},
    },
    3: {
        "en": "three", "topic": "numbers", "ru_base": "три",
        "ru_forms": {"all": "три"},
    },
    4: {
        "en": "four",  "topic": "numbers", "ru_base": "четыре",
        "ru_forms": {"all": "четыре"},
    },
}

# ── Reverse-lookup: any Russian surface form → English concept key ────────────
# Built at import time from all GAME2_* tables.
_RU_FORM_TO_EN: Dict[str, str] = {}

for _adj_data in GAME2_ADJECTIVES.values():
    for _form_val in _adj_data["ru_forms"].values():
        _RU_FORM_TO_EN[_form_val.lower()] = _adj_data["en"]

for _noun_data in GAME2_NOUNS.values():
    for _form_val in _noun_data["ru_forms"].values():
        _RU_FORM_TO_EN[_form_val.lower()] = _noun_data["en"]

for _count_data in GAME2_COUNTS.values():
    for _form_val in _count_data["ru_forms"].values():
        _RU_FORM_TO_EN[_form_val.lower()] = _count_data["en"]


def load_progress_lookup() -> Dict[str, Dict[str, Any]]:
    rows = get_user_word_progress()
    out: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        en = (row.get("word_eng") or "").strip()
        if en:
            out[en] = row

    return out


def ru_form_to_en(ru_word: str) -> Optional[str]:
    """Return the English concept key for any Russian surface form, or None."""
    return _RU_FORM_TO_EN.get((ru_word or "").strip().lower())

# ── Update from level-game results ───────────────────────────────────────────
def update_from_level_game(history: List[Dict], db_topics: List[Dict], user_id: Optional[int] = None) -> Dict[str, Any]:
    if user_id is None:
        user_id = 1
    """
    Persist level-game results into DB-backed user_word_progress.

    Important:
    - Applies attempts in history order.
    - This is required for the '3 correct in a row' learning rule.
    - Words never asked are left untouched.
    """
    save_level_game_history(history)

    # Build EN -> word_id lookup from DB
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT w.word_id, wt.word_eng
        FROM words w
        JOIN word_translations wt ON wt.word_id = w.word_id
    """)
    en_to_word_id: Dict[str, int] = {}
    for word_id, word_eng in cur.fetchall():
        if word_eng:
            en_to_word_id[word_eng.strip()] = word_id
    conn.close()

    updated_attempts = 0
    skipped_entries = []

    for entry in history:
        direction = (entry.get("direction") or "").strip()
        shown = (entry.get("shown") or "").strip()
        correct = (entry.get("correct") or "").strip()
        ok = bool(entry.get("ok", False))

        # Resolve the English key for the target concept
        if direction == "ru_to_en":
            en_key = correct
        elif direction == "en_to_ru":
            en_key = shown
        else:
            skipped_entries.append({
                "reason": "unknown_direction",
                "entry": entry,
            })
            continue

        if not en_key:
            # fallback: if somehow Russian leaked through, try reverse map
            en_key = _RU_FORM_TO_EN.get(correct.lower()) or _RU_FORM_TO_EN.get(shown.lower(), "")

        word_id = en_to_word_id.get(en_key)
        if not word_id:
            skipped_entries.append({
                "reason": "word_not_found",
                "en_key": en_key,
                "entry": entry,
            })
            continue

        upsert_user_word_progress(user_id, word_id, ok)
        updated_attempts += 1

    return {
        "updated_attempts": updated_attempts,
        "skipped_entries": skipped_entries,
    }

# ── Query helpers ─────────────────────────────────────────────────────────────


def unknown_adj_keys() -> List[str]:
    """
    Return game2 adj_keys whose corresponding color concept is not yet learned.

    A word is considered known only when its DB progress row has status == "learned".
    Missing rows are treated as unknown.
    """
    progress = load_progress_lookup()
    result: List[str] = []

    for adj_key, adj in GAME2_ADJECTIVES.items():
        row = progress.get(adj["en"])

        if row is None or str(row.get("status", "")).strip().lower() != "learned":
            result.append(adj_key)

    return result


def unknown_counts() -> List[str]:
    """
    Return game2 count keys whose English concept is not yet learned.

    A count is considered known only when its DB progress row has
    status == "learned". Missing rows are treated as unknown.
    """
    progress = load_progress_lookup()
    result: List[str] = []

    for count_key, count_data in GAME2_COUNTS.items():
        row = progress.get(count_data["en"])

        if row is None or str(row.get("status", "")).strip().lower() != "learned":
            result.append(count_key)

    return result


def noun_gender(noun_key: str) -> str:
    """
    Return the grammatical gender ("m", "f", "n") for a game2 noun_key.
    Falls back to "m" if not found.
    """
    return GAME2_NOUNS.get(noun_key, {}).get("gender", "m")
