from pathlib import Path
import json
import sqlite3

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "database" / "app.db"
JSON_PATH = BASE_DIR / "lvl_games" / "vocab_db_extended.json"

with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

for topic in data["topics"]:
    topic_key = topic["id"]
    topic_name_ru = topic["name_ru"]

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

conn.commit()
conn.close()

print("JSON vocab imported successfully.")