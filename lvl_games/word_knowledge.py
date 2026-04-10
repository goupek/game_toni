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

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

KNOWLEDGE_FILE = Path(__file__).resolve().parent / "word_knowledge.json"

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


def ru_form_to_en(ru_word: str) -> Optional[str]:
    """Return the English concept key for any Russian surface form, or None."""
    return _RU_FORM_TO_EN.get((ru_word or "").strip().lower())


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_knowledge() -> Dict[str, Any]:
    if KNOWLEDGE_FILE.exists():
        try:
            return json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"words": {}}


def save_knowledge(data: Dict[str, Any]) -> None:
    KNOWLEDGE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Bootstrap game2 entries ───────────────────────────────────────────────────

def ensure_game2_words_present() -> Dict[str, Any]:
    """
    Add any game2 vocabulary that is missing from word_knowledge.json,
    including all grammatical forms and gender info.
    Missing entries are created with known=None (never tested).
    Returns the (possibly updated) knowledge dict.
    """
    data    = load_knowledge()
    words   = data.setdefault("words", {})
    changed = False

    for _adj_key, adj in GAME2_ADJECTIVES.items():
        en = adj["en"]
        if en not in words:
            words[en] = {
                "known":    None,
                "ru_base":  adj["ru_base"],
                "ru_forms": adj["ru_forms"],
                "topic":    adj["topic"],
                "source":   "game2",
            }
            changed = True
        else:
            # Back-fill form data if an older entry lacks it
            entry = words[en]
            if "ru_forms" not in entry:
                entry["ru_base"]  = adj["ru_base"]
                entry["ru_forms"] = adj["ru_forms"]
                changed = True

    for _noun_key, noun in GAME2_NOUNS.items():
        en = noun["en"]
        if en not in words:
            words[en] = {
                "known":    None,
                "ru_base":  noun["ru_forms"]["sg"],
                "ru_forms": noun["ru_forms"],
                "gender":   noun["gender"],
                "topic":    noun["topic"],
                "source":   "game2",
            }
            changed = True
        else:
            entry = words[en]
            if "ru_forms" not in entry:
                entry["ru_base"]  = noun["ru_forms"]["sg"]
                entry["ru_forms"] = noun["ru_forms"]
                entry["gender"]   = noun["gender"]
                changed = True

    for _count, cnt in GAME2_COUNTS.items():
        en = cnt["en"]
        if en not in words:
            words[en] = {
                "known":    None,
                "ru_base":  cnt["ru_base"],
                "ru_forms": cnt["ru_forms"],
                "topic":    cnt["topic"],
                "source":   "game2",
            }
            changed = True
        else:
            entry = words[en]
            if "ru_forms" not in entry:
                entry["ru_base"]  = cnt["ru_base"]
                entry["ru_forms"] = cnt["ru_forms"]
                changed = True

    if changed:
        save_knowledge(data)
    return data


# ── Update from level-game results ───────────────────────────────────────────

def update_from_level_game(history: List[Dict], db_topics: List[Dict]) -> Dict[str, Any]:
    """
    Persist knowledge results after the level-identification game finishes.

    Parameters
    ----------
    history   : answer records from ImprovedRussianGame.history
                Each entry: {ok, direction, shown, correct, topic_id,
                             word_level, difficulty}
                direction "ru_to_en": shown=Russian, correct=English
                direction "en_to_ru": shown=English, correct=Russian
    db_topics : list of topic dicts loaded from vocab_db_extended.json

    Behaviour
    ---------
    - Words answered CORRECTLY at least once  → known = True
    - Words answered INCORRECTLY (all attempts) → known = False
    - vocab_db words never asked              → known = False
    - game2-only entries (source="game2")       kept as-is unless also
      tested by the level game

    Reverse lookup
    --------------
    If the level game tested a Russian word that is a declined/gendered form
    of a game2 word (e.g., "красная" instead of base "красный"), the
    _RU_FORM_TO_EN table maps it back to the same English concept "red" so
    knowledge is correctly updated.
    """
    data  = load_knowledge()
    words = data.setdefault("words", {})

    # Build topic lookup from vocab_db
    ru_to_topic: Dict[str, str] = {}
    en_to_topic: Dict[str, str] = {}
    for t in db_topics:
        for w in t.get("words", []):
            if w.get("ru"):
                ru_to_topic[w["ru"]] = t["id"]
            if w.get("en"):
                en_to_topic[w["en"]] = t["id"]
            # Also index every form stored in the extended vocab
            for form_val in w.get("forms", {}).values():
                ru_to_topic[form_val] = t["id"]
            for form_val in w.get("noun_forms", {}).values():
                ru_to_topic[form_val] = t["id"]

    # Collect per-word result: en_key → {ok, ru, topic}
    word_results: Dict[str, Dict] = {}

    for entry in history:
        direction = entry.get("direction", "")
        shown     = (entry.get("shown")   or "").strip()
        correct   = (entry.get("correct") or "").strip()
        ok        = bool(entry.get("ok", False))

        if direction == "ru_to_en":
            en_key = correct
            ru_val = shown
        elif direction == "en_to_ru":
            en_key = shown
            ru_val = correct
        else:
            continue

        if not en_key:
            continue

        # If the English key looks like a Russian word (vocab_db tested a
        # non-base form as the "English" side), resolve via reverse lookup
        if en_key.lower() in _RU_FORM_TO_EN:
            en_key = _RU_FORM_TO_EN[en_key.lower()]

        # Also check if the Russian value maps to an already-known game2 concept
        if not en_key and ru_val:
            en_key = _RU_FORM_TO_EN.get(ru_val.lower(), "")

        if not en_key:
            continue

        topic_id = en_to_topic.get(en_key) or ru_to_topic.get(ru_val, "unknown")

        prev = word_results.get(en_key)
        if prev is None:
            word_results[en_key] = {"ok": ok, "ru": ru_val, "topic": topic_id}
        else:
            # known if correct at least once
            word_results[en_key]["ok"] = prev["ok"] or ok

    # Write results into the knowledge store
    for en_key, result in word_results.items():
        entry = words.get(en_key, {})
        entry["known"]  = result["ok"]
        entry["ru_base"] = entry.get("ru_base") or result["ru"]
        entry["topic"]  = entry.get("topic") or result["topic"]
        entry.setdefault("source", "vocab_db")
        words[en_key] = entry

    # Seed vocab_db words that were never asked as known=False
    for t in db_topics:
        for w in t.get("words", []):
            en_key = w.get("en", "")
            ru_val = w.get("ru", "")
            if not en_key:
                continue
            if en_key not in words:
                entry: Dict[str, Any] = {
                    "known":   False,
                    "ru_base": ru_val,
                    "topic":   t["id"],
                    "source":  "vocab_db",
                }
                # Attach form/gender metadata from extended vocab if present
                if w.get("forms"):
                    entry["ru_forms"] = w["forms"]
                if w.get("noun_forms"):
                    entry["ru_forms"] = w["noun_forms"]
                if w.get("gender"):
                    entry["gender"] = w["gender"]
                words[en_key] = entry
            else:
                # Fill in missing metadata for existing entries
                existing = words[en_key]
                if existing.get("known") is None and existing.get("source") != "game2":
                    existing["known"] = False
                if "ru_forms" not in existing:
                    if w.get("forms"):
                        existing["ru_forms"] = w["forms"]
                    elif w.get("noun_forms"):
                        existing["ru_forms"] = w["noun_forms"]
                if "gender" not in existing and w.get("gender"):
                    existing["gender"] = w["gender"]

    save_knowledge(data)
    return data


# ── Query helpers ─────────────────────────────────────────────────────────────

def is_known(en_key: str) -> bool:
    """Return True only if the word has been explicitly marked as known."""
    data  = load_knowledge()
    entry = data["words"].get(en_key)
    if entry is None:
        return False
    return entry.get("known") is True


def unknown_adj_keys() -> List[str]:
    """
    Return game2 adj_keys whose corresponding COLOR concept is NOT known.
    An unknown word is one with known=False or known=None.
    """
    data  = load_knowledge()
    words = data.get("words", {})
    result = []
    for adj_key, adj in GAME2_ADJECTIVES.items():
        entry = words.get(adj["en"])
        if entry is None or entry.get("known") is not True:
            result.append(adj_key)
    return result


def unknown_counts() -> List[int]:
    """Return count integers (1-4) whose number word is NOT known."""
    data  = load_knowledge()
    words = data.get("words", {})
    result = []
    for count, cnt in GAME2_COUNTS.items():
        entry = words.get(cnt["en"])
        if entry is None or entry.get("known") is not True:
            result.append(count)
    return result


def noun_gender(noun_key: str) -> str:
    """
    Return the grammatical gender ("m", "f", "n") for a game2 noun_key.
    Falls back to "m" if not found.
    """
    return GAME2_NOUNS.get(noun_key, {}).get("gender", "m")
