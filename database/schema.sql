PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    role TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS topics (
    topic_id TEXT PRIMARY KEY,
    topic_name_ru TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS words (
    word_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma_rus TEXT NOT NULL,
    pos TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    level TEXT CHECK (level IN ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')),
    gender TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
        ON DELETE RESTRICT
        ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS word_translations (
    translation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    word_eng TEXT NOT NULL,

    FOREIGN KEY (word_id) REFERENCES words(word_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS word_forms (
    form_id INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id INTEGER NOT NULL,
    form_type TEXT NOT NULL,
    form_value TEXT NOT NULL,

    FOREIGN KEY (word_id) REFERENCES words(word_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS user_word_progress (
    user_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,

    status TEXT NOT NULL DEFAULT 'new' CHECK (
        status IN ('new', 'learning', 'learned')
    ),
    last_seen_at TIMESTAMP,
    correct_streak INTEGER NOT NULL DEFAULT 0 CHECK (correct_streak >= 0),
    total_attempts INTEGER NOT NULL DEFAULT 0 CHECK (total_attempts >= 0),
    total_correct INTEGER NOT NULL DEFAULT 0 CHECK (
        total_correct >= 0 AND total_correct <= total_attempts
    ),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (user_id, word_id),

    FOREIGN KEY (user_id) REFERENCES users(user_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (word_id) REFERENCES words(word_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS games (
    game_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS game_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,

    user_id INTEGER NOT NULL,
    game_id INTEGER NOT NULL,
    word_id INTEGER,

    event_type TEXT NOT NULL,
    is_correct INTEGER CHECK (is_correct IN (0, 1) OR is_correct IS NULL),
    used_hint INTEGER CHECK (used_hint IN (0, 1) OR used_hint IS NULL),
    attempt_number INTEGER CHECK (attempt_number IS NULL OR attempt_number > 0),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(user_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (game_id) REFERENCES games(game_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (word_id) REFERENCES words(word_id)
        ON DELETE SET NULL
        ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_words_lemma_rus
ON words(lemma_rus);

CREATE INDEX IF NOT EXISTS idx_words_topic_pos
ON words(topic_id, pos);

CREATE INDEX IF NOT EXISTS idx_word_translations_word_id
ON word_translations(word_id);

CREATE INDEX IF NOT EXISTS idx_word_forms_word_id_form_type
ON word_forms(word_id, form_type);

CREATE INDEX IF NOT EXISTS idx_word_forms_form_value
ON word_forms(form_value);

CREATE INDEX IF NOT EXISTS idx_user_word_progress_user_status
ON user_word_progress(user_id, status);

CREATE INDEX IF NOT EXISTS idx_user_word_progress_user_updated
ON user_word_progress(user_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_user_word_progress_word_id
ON user_word_progress(word_id);

CREATE INDEX IF NOT EXISTS idx_game_events_user_created
ON game_events(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_game_events_word_created
ON game_events(word_id, created_at);

CREATE INDEX IF NOT EXISTS idx_game_events_game_created
ON game_events(game_id, created_at);