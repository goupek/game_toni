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