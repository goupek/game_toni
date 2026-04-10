from pathlib import Path
import sqlite3
import json
import argparse

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "app.db"
SCHEMA_PATH = BASE_DIR / "database" / "schema.sql"
JSON_PATH = BASE_DIR / "lvl_games" / "vocab_db_extended.json"


def connect_db():
    return sqlite3.connect(DB_PATH)


def reset_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Deleted existing database: {DB_PATH}")


def init_schema(conn):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.commit()
    print("Schema initialized.")


def ensure_default_user(conn, user_name="Player 1"):
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_name = ?", (user_name,))
    row = cur.fetchone()

    if row:
        print(f"Default user already exists: {user_name} (user_id={row[0]})")
        return row[0]

    cur.execute(
        "INSERT INTO users (user_name) VALUES (?)",
        (user_name,)
    )
    conn.commit()
    user_id = cur.lastrowid
    print(f"Created default user: {user_name} (user_id={user_id})")
    return user_id


def ensure_level_game(conn):
    cur = conn.cursor()
    cur.execute("SELECT game_id FROM games WHERE game_name = ?", ("level_game",))
    row = cur.fetchone()

    if row:
        print(f"Game already exists: level_game (game_id={row[0]})")
        return row[0]

    cur.execute("INSERT INTO games (game_name) VALUES (?)", ("level_game",))
    conn.commit()
    game_id = cur.lastrowid
    print(f"Created game: level_game (game_id={game_id})")
    return game_id


def derive_adj_gen_pl(pl_form: str):
    if not pl_form:
        return None

    pl_form = pl_form.strip()
    if pl_form.endswith("ые"):
        return pl_form[:-2] + "ых"
    if pl_form.endswith("ие"):
        return pl_form[:-2] + "их"
    return None


def normalize_forms_for_insert(word: dict) -> dict:
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


def insert_forms(cur, word_id, forms_dict):
    if not isinstance(forms_dict, dict):
        return

    for form_type, form_value in forms_dict.items():
        if form_value is None:
            continue

        cur.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (word_id, str(form_type), str(form_value).strip()))


def import_extended_vocab(conn):
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    cur = conn.cursor()

    for topic in data["topics"]:
        topic_key = topic["id"].strip()
        topic_name_ru = topic["name_ru"].strip()

        cur.execute("""
            INSERT INTO topics (topic_key, topic_name_ru)
            VALUES (?, ?)
        """, (topic_key, topic_name_ru))

        topic_id = cur.lastrowid

        for word in topic["words"]:
            lemma_rus = word["ru"].strip()
            word_eng = word["en"].strip()
            pos = word["pos"].strip()
            level = word.get("level", "A1").strip().upper()
            gender = word.get("gender")

            cur.execute("""
                INSERT INTO words (lemma_rus, pos, topic_id, level, gender)
                VALUES (?, ?, ?, ?, ?)
            """, (lemma_rus, pos, topic_id, level, gender))

            word_id = cur.lastrowid

            cur.execute("""
                INSERT INTO word_translations (word_id, word_eng)
                VALUES (?, ?)
            """, (word_id, word_eng))

            normalized_forms = normalize_forms_for_insert(word)
            insert_forms(cur, word_id, normalized_forms)

    conn.commit()
    print("Extended vocab imported.")


def print_summary(conn):
    cur = conn.cursor()

    for table in ["users", "topics", "words", "word_translations", "word_forms", "games"]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"{table}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Initialize and populate app.db")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing app.db before recreating it"
    )
    parser.add_argument(
        "--user",
        default="Player 1",
        help="Default username to create"
    )
    args = parser.parse_args()

    if args.reset:
        reset_db()

    conn = connect_db()

    try:
        init_schema(conn)
        ensure_default_user(conn, args.user)
        ensure_level_game(conn)
        import_extended_vocab(conn)
        print_summary(conn)
        print(f"\nDatabase ready: {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()