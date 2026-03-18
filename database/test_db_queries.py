from db_queries import ensure_default_user, get_word_id_by_ru_en, upsert_user_word_progress
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "app.db"

user_id = ensure_default_user()
word_id = get_word_id_by_ru_en("собака", "dog")

upsert_user_word_progress(user_id, word_id, True)
upsert_user_word_progress(user_id, word_id, False)

conn = sqlite3.connect(DB_PATH)
row = conn.execute("""
    SELECT user_id, word_id, correct_streak, total_attempts, total_correct, status
    FROM user_word_progress
    WHERE user_id = ? AND word_id = ?
""", (user_id, word_id)).fetchone()
conn.close()

print(row)