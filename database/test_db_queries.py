import sys
from pathlib import Path

# Make sure we can import from the original level/ folder and the repo root
_HERE   = Path(__file__).resolve().parent          # lvl_games/
_LEVEL  = _HERE.parent / "level"                   # level/
_ROOT   = _HERE.parent                             # repo root

for p in [str(_HERE), str(_LEVEL), str(_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import sqlite3

from database.db_queries import get_topics_with_words
from lvl_games.word_knowledge import update_from_level_game

DB_PATH = Path(__file__).resolve().parent / "app.db"
USER_ID = 1
TARGET_EN = "blue"


def print_db_path():
    print("Using DB:", DB_PATH)
    print("Exists:", DB_PATH.exists())


def list_tables():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cur.fetchall()
    conn.close()
    print("Tables:", tables)


def print_progress(label: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT
            uwp.user_id,
            w.word_id,
            w.lemma_rus,
            wt.word_eng,
            uwp.status,
            uwp.correct_streak,
            uwp.total_attempts,
            uwp.total_correct,
            uwp.last_seen_at,
            uwp.updated_at
        FROM user_word_progress uwp
        JOIN words w ON w.word_id = uwp.word_id
        JOIN word_translations wt ON wt.word_id = w.word_id
        WHERE uwp.user_id = ? AND wt.word_eng = ?
    """, (USER_ID, TARGET_EN))

    row = cur.fetchone()
    conn.close()

    print(f"{label}: {row}")


def reset_progress():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM user_word_progress
        WHERE user_id = ?
          AND word_id IN (
              SELECT w.word_id
              FROM words w
              JOIN word_translations wt ON wt.word_id = w.word_id
              WHERE wt.word_eng = ?
          )
    """, (USER_ID, TARGET_EN))

    conn.commit()
    conn.close()


def test_three_correct_in_a_row():
    print("\n=== TEST 1: three correct in a row ===")
    reset_progress()
    print_progress("Before")

    db_topics = get_topics_with_words()["topics"]

    fake_history = [
        {"direction": "ru_to_en", "shown": "синий", "correct": "blue", "ok": True},
        {"direction": "ru_to_en", "shown": "синий", "correct": "blue", "ok": True},
        {"direction": "ru_to_en", "shown": "синий", "correct": "blue", "ok": True},
    ]

    result = update_from_level_game(fake_history, db_topics, user_id=USER_ID)
    print("update_from_level_game result:", result)
    print_progress("After")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT status, correct_streak, total_attempts, total_correct
        FROM user_word_progress
        WHERE user_id = ?
          AND word_id IN (
              SELECT w.word_id
              FROM words w
              JOIN word_translations wt ON wt.word_id = w.word_id
              WHERE wt.word_eng = ?
          )
    """, (USER_ID, TARGET_EN))
    row = cur.fetchone()
    conn.close()

    assert row is not None, "Expected a progress row for 'blue'"
    assert row[0] == "learned", f"Expected status='learned', got {row[0]!r}"
    assert row[1] == 3, f"Expected correct_streak=3, got {row[1]!r}"
    assert row[2] == 3, f"Expected total_attempts=3, got {row[2]!r}"
    assert row[3] == 3, f"Expected total_correct=3, got {row[3]!r}"

    print("PASS: three correct in a row -> learned, streak 3")


def test_broken_streak():
    print("\n=== TEST 2: broken streak ===")
    reset_progress()
    print_progress("Before")

    db_topics = get_topics_with_words()["topics"]

    fake_history = [
        {"direction": "ru_to_en", "shown": "синий", "correct": "blue", "ok": True},
        {"direction": "ru_to_en", "shown": "синий", "correct": "blue", "ok": False},
        {"direction": "ru_to_en", "shown": "синий", "correct": "blue", "ok": True},
    ]

    result = update_from_level_game(fake_history, db_topics, user_id=USER_ID)
    print("update_from_level_game result:", result)
    print_progress("After")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT status, correct_streak, total_attempts, total_correct
        FROM user_word_progress
        WHERE user_id = ?
          AND word_id IN (
              SELECT w.word_id
              FROM words w
              JOIN word_translations wt ON wt.word_id = w.word_id
              WHERE wt.word_eng = ?
          )
    """, (USER_ID, TARGET_EN))
    row = cur.fetchone()
    conn.close()

    assert row is not None, "Expected a progress row for 'blue'"
    assert row[0] == "learning", f"Expected status='learning', got {row[0]!r}"
    assert row[1] == 1, f"Expected correct_streak=1, got {row[1]!r}"
    assert row[2] == 3, f"Expected total_attempts=3, got {row[2]!r}"
    assert row[3] == 2, f"Expected total_correct=2, got {row[3]!r}"

    print("PASS: correct, wrong, correct -> learning, streak 1")


if __name__ == "__main__":
    print_db_path()
    list_tables()
    test_three_correct_in_a_row()
    test_broken_streak()
    print("\nAll tests passed.")