import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "app.db"

def get_words_by_topic_key(topic_key):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query = """
    SELECT
        w.word_id,
        w.lemma_rus,
        w.pos,
        w.topic_id,
        w.level,
        w.gender
    FROM words w
    JOIN topics t ON w.topic_id = t.topic_id
    WHERE t.topic_key = ?
    ORDER BY w.word_id
    """

    rows = conn.execute(query, (topic_key,)).fetchall()
    conn.close()

    return [dict(row) for row in rows]

def get_topics_with_words():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    topic_rows = conn.execute("""
        SELECT topic_id, topic_key, topic_name_ru
        FROM topics
        ORDER BY topic_id
    """).fetchall()

    out = []

    for topic in topic_rows:
        word_rows = conn.execute("""
            SELECT
                w.word_id,
                w.lemma_rus,
                w.pos,
                w.level,
                w.gender,
                wt.word_eng AS translation_en
            FROM words w
            LEFT JOIN word_translations wt
                ON w.word_id = wt.word_id
            WHERE w.topic_id = ?
            ORDER BY w.word_id
        """, (topic["topic_id"],)).fetchall()

        words = []
        for row in word_rows:
            ru = (row["lemma_rus"] or "").strip()
            en = (row["translation_en"] or "").strip()
            pos = (row["pos"] or "").strip()
            level = (row["level"] or "A1").strip().upper()

            if ru and en:
                words.append({
                    "ru": ru,
                    "en": en,
                    "pos": pos,
                    "level": level
                })

        out.append({
            "id": topic["topic_key"],
            "name_ru": topic["topic_name_ru"],
            "words": words
        })

    conn.close()
    return {"topics": out}

def get_word_id_by_ru_en(ru, en):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute("""
        SELECT w.word_id
        FROM words w
        JOIN word_translations wt ON wt.word_id = w.word_id
        WHERE w.lemma_rus = ? AND wt.word_eng = ?
        LIMIT 1
    """, (ru, en)).fetchone()

    conn.close()
    return row["word_id"] if row else None

def ensure_default_user():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute("""
        SELECT user_id
        FROM users
        ORDER BY user_id
        LIMIT 1
    """).fetchone()

    if row:
        conn.close()
        return row["user_id"]

    cursor = conn.execute("""
        INSERT INTO users (user_name)
        VALUES (?)
    """, ("Player",))
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id

def upsert_user_word_progress(user_id, word_id, was_correct):
    conn = sqlite3.connect(DB_PATH)

    if was_correct:
        conn.execute("""
            INSERT INTO user_word_progress (
                user_id, word_id, status, last_seen_at,
                correct_streak, total_attempts, total_correct
            )
            VALUES (?, ?, 'learning', CURRENT_TIMESTAMP, 1, 1, 1)
            ON CONFLICT(user_id, word_id) DO UPDATE SET
                total_attempts = total_attempts + 1,
                total_correct = total_correct + 1,
                correct_streak = correct_streak + 1,
                last_seen_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, word_id))
    else:
        conn.execute("""
            INSERT INTO user_word_progress (
                user_id, word_id, status, last_seen_at,
                correct_streak, total_attempts, total_correct
            )
            VALUES (?, ?, 'learning', CURRENT_TIMESTAMP, 0, 1, 0)
            ON CONFLICT(user_id, word_id) DO UPDATE SET
                total_attempts = total_attempts + 1,
                correct_streak = 0,
                last_seen_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, word_id))

    conn.commit()
    conn.close()

def save_level_game_history(history):
    user_id = ensure_default_user()

    for entry in history:
        direction = entry.get("direction", "")
        shown = (entry.get("shown") or "").strip()
        correct = (entry.get("correct") or "").strip()
        ok = bool(entry.get("ok", False))

        if direction == "ru_to_en":
            ru = shown
            en = correct
        elif direction == "en_to_ru":
            ru = correct
            en = shown
        else:
            continue

        word_id = get_word_id_by_ru_en(ru, en)
        if word_id is None:
            continue

        upsert_user_word_progress(user_id, word_id, ok)

def get_user_word_progress(user_id=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if user_id is None:
        user_id = ensure_default_user()

    rows = conn.execute("""
        SELECT
            w.lemma_rus,
            wt.word_eng,
            uwp.status,
            uwp.correct_streak,
            uwp.total_attempts,
            uwp.total_correct,
            uwp.last_seen_at
        FROM user_word_progress uwp
        JOIN words w ON w.word_id = uwp.word_id
        JOIN word_translations wt ON wt.word_id = w.word_id
        WHERE uwp.user_id = ?
        ORDER BY w.word_id
    """, (user_id,)).fetchall()

    conn.close()
    return [dict(row) for row in rows]
