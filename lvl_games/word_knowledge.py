"""
Shared word-knowledge store — DB-backed.

Vocabulary (NOUNS, ADJECTIVES, NUM_WORD) is imported from
question_generation.py, which loads it from SQLite at module init.

_RU_FORM_TO_EN is built automatically from those dicts at import time and is
used in update_from_level_game() to map any tested Russian surface form back
to its English concept key.

All progress is persisted in user_word_progress via save_level_game_history().
"""

import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional
from database.db_queries import save_level_game_history, get_user_word_progress, upsert_user_word_progress
from question_generation import NOUNS, ADJECTIVES, NUM_WORD

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "database" / "app.db"

_NUM_EN_MAP = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}



# ── Reverse-lookup: any Russian surface form → English concept key ────────────
# Built at import time from DB-backed NOUNS, ADJECTIVES, NUM_WORD.
_RU_FORM_TO_EN: Dict[str, str] = {}

for _adj_key, _adj_forms in ADJECTIVES.items():
    for _form_val in _adj_forms.values():
        _RU_FORM_TO_EN[_form_val.lower()] = _adj_key

for _noun_key, _noun_entry in NOUNS.items():
    for _form_key, _form_val in _noun_entry.items():
        if _form_key != "gender":
            _RU_FORM_TO_EN[_form_val.lower()] = _noun_key

for _num_key, _num_forms in NUM_WORD.items():
    _en_label = _NUM_EN_MAP.get(_num_key)
    if _en_label:
        for _form_val in _num_forms.values():
            _RU_FORM_TO_EN[_form_val.lower()] = _en_label


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
def update_from_level_game(history: List[Dict], user_id: Optional[int] = None, game_name: str = "level_game") -> Dict[str, Any]:
    """
    Persist level-game results into DB-backed user_word_progress.

    Important:
    - Applies attempts in history order.
    - This is required for the '3 correct in a row' learning rule.
    - Words never asked are left untouched.
    """
    if user_id is None:
        user_id = 1
    save_level_game_history(history, game_name=game_name)

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
    return [
        adj_key for adj_key in ADJECTIVES
        if progress.get(adj_key) is None
        or str(progress[adj_key].get("status", "")).strip().lower() != "learned"
    ]


def unknown_counts() -> List[int]:
    """
    Return game2 count keys (ints) whose English concept is not yet learned.

    A count is considered known only when its DB progress row has
    status == "learned". Missing rows are treated as unknown.
    """
    progress = load_progress_lookup()
    return [
        num_key for num_key in NUM_WORD
        if progress.get(_NUM_EN_MAP.get(num_key)) is None
        or str(progress[_NUM_EN_MAP[num_key]].get("status", "")).strip().lower() != "learned"
    ]


def noun_gender(noun_key: str) -> str:
    """
    Return the grammatical gender ("m", "f", "n") for a game2 noun_key.
    Falls back to "m" if not found.
    """
    return NOUNS.get(noun_key, {}).get("gender", "m")
