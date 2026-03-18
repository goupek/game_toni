from pathlib import Path
import sqlite3


def main():
    base_dir = Path(__file__).resolve().parent
    db_path = base_dir / "app.db"

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    cursor = conn.cursor()

    try:
        # user
        cursor.execute("""
            INSERT INTO users (user_name)
            VALUES (?)
        """, ("Test User",))
        user_id = cursor.lastrowid

        # topics
        cursor.execute("""
            INSERT INTO topics (topic_key, topic_name_ru)
            VALUES (?, ?)
        """, ("animals", "Животные"))
        animals_topic_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO topics (topic_key, topic_name_ru)
            VALUES (?, ?)
        """, ("colors", "Цвета"))
        colors_topic_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO topics (topic_key, topic_name_ru)
            VALUES (?, ?)
        """, ("numbers", "Числа"))
        numbers_topic_id = cursor.lastrowid

        # words
        cursor.execute("""
            INSERT INTO words (lemma_rus, pos, topic_id, level, gender)
            VALUES (?, ?, ?, ?, ?)
        """, ("собака", "noun", animals_topic_id, "A1", "fem"))
        dog_word_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO words (lemma_rus, pos, topic_id, level, gender)
            VALUES (?, ?, ?, ?, ?)
        """, ("красный", "adjective", colors_topic_id, "A1", None))
        red_word_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO words (lemma_rus, pos, topic_id, level, gender)
            VALUES (?, ?, ?, ?, ?)
        """, ("один", "number", numbers_topic_id, "A1", None))
        one_word_id = cursor.lastrowid

        # translations
        cursor.execute("""
            INSERT INTO word_translations (word_id, word_eng)
            VALUES (?, ?)
        """, (dog_word_id, "dog"))

        cursor.execute("""
            INSERT INTO word_translations (word_id, word_eng)
            VALUES (?, ?)
        """, (red_word_id, "red"))

        cursor.execute("""
            INSERT INTO word_translations (word_id, word_eng)
            VALUES (?, ?)
        """, (one_word_id, "one"))

        # word forms
        # noun: собака
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (dog_word_id, "sg", "собака"))
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (dog_word_id, "pl", "собаки"))
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (dog_word_id, "gen_pl", "собак"))

        # adjective: красный
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (red_word_id, "m", "красный"))
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (red_word_id, "f", "красная"))
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (red_word_id, "n", "красное"))
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (red_word_id, "pl", "красные"))
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (red_word_id, "gen_pl", "красных"))

        # number: один
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (one_word_id, "m", "один"))
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (one_word_id, "f", "одна"))
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (one_word_id, "n", "одно"))
        cursor.execute("""
            INSERT INTO word_forms (word_id, form_type, form_value)
            VALUES (?, ?, ?)
        """, (one_word_id, "pl", "одни"))

        # progress
        cursor.execute("""
            INSERT INTO user_word_progress (
                user_id, word_id, status, last_seen_at,
                correct_streak, total_attempts, total_correct
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
        """, (user_id, dog_word_id, "learning", 1, 2, 1))

        cursor.execute("""
            INSERT INTO user_word_progress (
                user_id, word_id, status, last_seen_at,
                correct_streak, total_attempts, total_correct
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
        """, (user_id, red_word_id, "new", 0, 0, 0))

        cursor.execute("""
            INSERT INTO user_word_progress (
                user_id, word_id, status, last_seen_at,
                correct_streak, total_attempts, total_correct
            )
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
        """, (user_id, one_word_id, "learned", 3, 3, 3))

        conn.commit()
        print("Sample data inserted successfully.")

    except Exception as e:
        conn.rollback()
        print("Failed to insert sample data.")
        print(f"Error: {e}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()