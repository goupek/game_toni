from pathlib import Path
import json
import sqlite3

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "app.db"
JSON_PATH = BASE_DIR / "lvl_games" / "vocab_db_extended.json"


def derive_adj_gen_pl(pl_form: str) -> str | None:
    """
    Derive adjective genitive plural from nominative plural.
    This is a simple rule-based fallback for the current dataset.

    Examples:
      красные -> красных
      синие   -> синих
    """
    if not pl_form:
        return None

    pl_form = pl_form.strip()

    if pl_form.endswith("ые"):
        return pl_form[:-2] + "ых"
    if pl_form.endswith("ие"):
        return pl_form[:-2] + "их"

    return None


def normalize_forms_for_insert(word: dict) -> dict:
    """
    Returns a normalized flat dict of forms to insert into word_forms.

    Rules:
    1. adjectives:
       - keep m/f/n/pl
       - also add gen_pl derived from pl if not explicitly present

    2. nouns:
       - change noun_forms to forms

    3. numerals:
       - if forms has 'all', expand it into m/f/n with the same value
         so future code can handle numerals uniformly
    """
    pos = word.get("pos")
    result = {}

    if pos == "adj":
        forms = word.get("forms", {})
        if isinstance(forms, dict):
            result.update(forms)

            if "gen_pl" not in result and "pl" in result:
                derived = derive_adj_gen_pl(result["pl"])
                if derived:
                    result["gen_pl"] = derived

    elif pos == "noun":
        noun_forms = word.get("noun_forms", {})
        if isinstance(noun_forms, dict):
            result.update(noun_forms)

    elif pos == "num":
        forms = word.get("forms", {})
        if isinstance(forms, dict):
            if "all" in forms:
                value = str(forms["all"]).strip()
                result["m"] = value
                result["f"] = value
                result["n"] = value
            else:
                result.update(forms)

    else:
        forms = word.get("forms", {})
        if isinstance(forms, dict):
            result.update(forms)

    return result


def insert_forms(cursor, word_id, forms_dict):
    if not isinstance(forms_dict, dict):
        return

    for form_type, form_value in forms_dict.items():
        if form_value is None:
            continue

        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (word_id, str(form_type), str(form_value).strip()))


with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

for topic in data["topics"]:
    topic_key = topic["id"].strip()
    topic_name_ru = topic["name_ru"].strip()

    cursor.execute("""
        INSERT INTO topics (topic_key, topic_name_ru)
        VALUES (?, ?)
    """, (topic_key, topic_name_ru))

    topic_id = cursor.lastrowid

    for word in topic["words"]:
        lemma_rus = word["ru"].strip()
        word_eng = word["en"].strip()
        pos = word["pos"].strip()
        level = word.get("level", "A1").strip().upper()
        gender = word.get("gender")

        cursor.execute("""
            INSERT INTO words (lemma_rus, pos, topic_id, level, gender)
            VALUES (?, ?, ?, ?, ?)
        """, (lemma_rus, pos, topic_id, level, gender))

        word_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO word_translations (word_id, word_eng)
            VALUES (?, ?)
        """, (word_id, word_eng))

        normalized_forms = normalize_forms_for_insert(word)
        insert_forms(cursor, word_id, normalized_forms)

conn.commit()
conn.close()

print("Extended JSON vocab imported successfully.")