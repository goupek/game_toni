import sqlite3
from collections import OrderedDict
from pathlib import Path

DB_PATH = Path(__file__).with_name("app.db")


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_topics_with_words():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            t.topic_id,
            t.topic_key,
            t.topic_name_ru,
            w.word_id,
            w.lemma_rus,
            w.pos,
            w.level,
            w.gender,
            wt.word_eng,
            wf.form_type,
            wf.form_value
        FROM topics t
        JOIN words w
            ON w.topic_id = t.topic_id
        LEFT JOIN word_translations wt
            ON wt.word_id = w.word_id
        LEFT JOIN word_forms wf
            ON wf.word_id = w.word_id
        ORDER BY t.topic_id, w.word_id, wf.form_type
    """)

    rows = cur.fetchall()
    conn.close()

    topics_by_id = OrderedDict()
    words_by_id = {}

    for row in rows:
        topic_id = row["topic_id"]
        word_id = row["word_id"]

        if topic_id not in topics_by_id:
            topics_by_id[topic_id] = {
                "id": row["topic_key"],
                "name_ru": row["topic_name_ru"],
                "words": []
            }

        if word_id not in words_by_id:
            word_entry = {
                "topic_id": topic_id,
                "ru": row["lemma_rus"],
                "en": row["word_eng"],
                "pos": row["pos"],
                "level": row["level"],
                "gender": row["gender"],
                "forms": {}
            }
            words_by_id[word_id] = word_entry
            topics_by_id[topic_id]["words"].append(word_entry)

        form_type = row["form_type"]
        form_value = row["form_value"]

        if form_type and form_value:
            words_by_id[word_id]["forms"][form_type] = form_value

    return {"topics": list(topics_by_id.values())}


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


def get_word_id_by_ru_en(ru, en):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Try lemma match first
    row = conn.execute("""
        SELECT w.word_id
        FROM words w
        JOIN word_translations wt ON wt.word_id = w.word_id
        WHERE w.lemma_rus = ? AND wt.word_eng = ?
        LIMIT 1
    """, (ru, en)).fetchone()

    if not row:
        # Fall back to inflected forms stored in word_forms
        row = conn.execute("""
            SELECT w.word_id
            FROM words w
            JOIN word_translations wt ON wt.word_id = w.word_id
            JOIN word_forms wf ON wf.word_id = w.word_id
            WHERE wf.form_value = ? AND wt.word_eng = ?
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
                status = CASE
                    WHEN (correct_streak + 1) >= 3 THEN 'learned'
                    ELSE 'learning'
                END,
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
                status = 'learning',
                last_seen_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, word_id))

    conn.commit()
    conn.close()


def save_level_game_history(history, game_name="level_game"):
    """
    Save raw game attempts into game_events.

    Does NOT update user_word_progress.
    Progress updates are handled separately in update_from_level_game().
    """
    user_id = ensure_default_user()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Ensure the game row exists
    cur.execute("SELECT game_id FROM games WHERE game_name = ?", (game_name,))
    row = cur.fetchone()

    if row:
        game_id = row[0]
    else:
        cur.execute("INSERT INTO games (game_name) VALUES (?)", (game_name,))
        game_id = cur.lastrowid

    for entry in history:
        direction = entry.get("direction", "")
        shown = (entry.get("shown") or "").strip()
        correct = (entry.get("correct") or "").strip()
        ok = bool(entry.get("ok", False))
        attempt_number = entry.get("attempt_number")
        if isinstance(attempt_number, int) and attempt_number > 0:
            db_attempt_number = attempt_number
        else:
            db_attempt_number = None

        if direction == "ru_to_en":
            ru = shown
            en = correct
        elif direction == "en_to_ru":
            ru = correct
            en = shown
        else:
            continue

        word_id = get_word_id_by_ru_en(ru, en)

        cur.execute("""
            INSERT INTO game_events (
                user_id,
                game_id,
                word_id,
                event_type,
                is_correct,
                used_hint,
                attempt_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            game_id,
            word_id,
            "level_attempt",
            1 if ok else 0,
            0,
            db_attempt_number,
        ))

    conn.commit()
    conn.close()


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


def get_game2_vocab_by_manifest(manifest):
    """
    Build NOUNS, ADJECTIVES, NUM_WORD dicts from DB for only enabled words.
    
    If a form is missing in DB, uses the base form as fallback.
    Logs warnings for any missing forms but continues loading.
    
    Args:
        manifest: dict with keys "nouns", "adjectives", "numbers" containing enabled keys.
    
    Returns:
        dict with keys "nouns", "adjectives", "numbers" containing full structures.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    result = {
        "nouns": {},
        "adjectives": {},
        "numbers": {},
    }
    
    try:
        # ── Nouns ──────────────────────────────────────────────────────
        noun_keys = manifest.get("nouns", set())
        for noun_key in noun_keys:
            row = conn.execute("""
                SELECT w.word_id, w.lemma_rus, w.gender
                FROM words w
                JOIN word_translations wt ON wt.word_id = w.word_id
                WHERE lower(wt.word_eng) = lower(?)
                    AND w.pos = 'noun'
                LIMIT 1
            """, (noun_key,)).fetchone()
            
            if not row:
                print(f"[WARN] Noun '{noun_key}' not found in DB, skipping")
                continue
            
            word_id = row["word_id"]
            base_form = row["lemma_rus"]
            
            # Get forms
            forms_rows = conn.execute(
                "SELECT form_type, form_value FROM word_forms WHERE word_id = ?",
                (word_id,),
            ).fetchall()
            
            forms_dict = {r["form_type"]: r["form_value"] for r in forms_rows}
            required_forms = {"sg", "pl", "gen_pl"}
            missing = required_forms - set(forms_dict.keys())
            
            if missing:
                print(f"[WARN] Noun '{noun_key}' missing forms {missing}, using base form as fallback")
                for form_type in missing:
                    forms_dict[form_type] = base_form
            
            result["nouns"][noun_key] = {
                "sg": forms_dict.get("sg", base_form),
                "pl": forms_dict.get("pl", base_form),
                "gen_pl": forms_dict.get("gen_pl", base_form),
                "gender": row["gender"],
            }
        
        # ── Adjectives ─────────────────────────────────────────────────
        adj_keys = manifest.get("adjectives", set())
        for adj_key in adj_keys:
            row = conn.execute("""
                SELECT w.word_id, w.lemma_rus
                FROM words w
                JOIN word_translations wt ON wt.word_id = w.word_id
                WHERE lower(wt.word_eng) = lower(?)
                    AND w.pos = 'adj'
                LIMIT 1
            """, (adj_key,)).fetchone()
            
            if not row:
                print(f"[WARN] Adjective '{adj_key}' not found in DB, skipping")
                continue
            
            word_id = row["word_id"]
            base_form = row["lemma_rus"]
            
            # Get forms
            forms_rows = conn.execute(
                "SELECT form_type, form_value FROM word_forms WHERE word_id = ?",
                (word_id,),
            ).fetchall()
            
            forms_dict = {r["form_type"]: r["form_value"] for r in forms_rows}
            required_forms = {"m", "f", "n", "pl"}
            missing = required_forms - set(forms_dict.keys())
            
            if missing:
                print(f"[WARN] Adjective '{adj_key}' missing forms {missing}, using base form as fallback")
                for form_type in missing:
                    forms_dict[form_type] = base_form
            
            result["adjectives"][adj_key] = {
                "m": forms_dict.get("m", base_form),
                "f": forms_dict.get("f", base_form),
                "n": forms_dict.get("n", base_form),
                "pl": forms_dict.get("pl", base_form),
            }
        
        # ── Numbers ────────────────────────────────────────────────────
        num_keys = manifest.get("numbers", set())
        number_en_map = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        
        for num_key in num_keys:
            en_label = number_en_map.get(num_key)
            if not en_label:
                print(f"[WARN] Number {num_key} not in supported range (1-5), skipping")
                continue
            
            row = conn.execute("""
                SELECT w.word_id, w.lemma_rus
                FROM words w
                JOIN word_translations wt ON wt.word_id = w.word_id
                WHERE lower(wt.word_eng) = lower(?)
                    AND w.pos = 'num'
                LIMIT 1
            """, (en_label,)).fetchone()
            
            if not row:
                print(f"[WARN] Number '{en_label}' (key={num_key}) not found in DB, skipping")
                continue
            
            word_id = row["word_id"]
            base_form = row["lemma_rus"]
            
            # Get forms
            forms_rows = conn.execute(
                "SELECT form_type, form_value FROM word_forms WHERE word_id = ?",
                (word_id,),
            ).fetchall()
            
            forms_dict = {r["form_type"]: r["form_value"] for r in forms_rows}
            required_forms = {"m", "f", "n"}
            missing = required_forms - set(forms_dict.keys())
            
            if missing:
                print(f"[WARN] Number {num_key} missing forms {missing}, using base form as fallback")
                for form_type in missing:
                    forms_dict[form_type] = base_form
            
            result["numbers"][num_key] = {
                "m": forms_dict.get("m", base_form),
                "f": forms_dict.get("f", base_form),
                "n": forms_dict.get("n", base_form),
            }
    
    finally:
        conn.close()
    
    return result
