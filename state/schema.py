"""Database schema DDL and migration management."""

import sqlite3

SCHEMA_VERSION = 3

CREATE_BOOKS = """
CREATE TABLE IF NOT EXISTS books (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    source_path     TEXT NOT NULL,
    source_format   TEXT NOT NULL,
    file_hash       TEXT NOT NULL,
    total_paragraphs INTEGER NOT NULL DEFAULT 0,
    total_pages     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_TRANSLATIONS = """
CREATE TABLE IF NOT EXISTS translations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    model_id        TEXT,
    source_type     TEXT NOT NULL
                    CHECK(source_type IN ('parallel','imported','previous')),
    mode            TEXT NOT NULL DEFAULT 'auto'
                    CHECK(mode IN ('auto','interactive','hybrid')),
    total_cost      DECIMAL(10,6) NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CREATE_PAGES = """
CREATE TABLE IF NOT EXISTS pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    translation_id  INTEGER NOT NULL REFERENCES translations(id) ON DELETE CASCADE,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_title   TEXT NOT NULL,
    page_number     INTEGER NOT NULL,
    original_text   TEXT NOT NULL,
    model_id        TEXT NOT NULL DEFAULT '',
    translated_text TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','translating','completed','failed')),
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    cost_usd        DECIMAL(10,6) NOT NULL DEFAULT 0,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    is_manually_edited INTEGER NOT NULL DEFAULT 0,
    edit_history    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(translation_id, chapter_title, page_number)
);
"""

CREATE_GLOSSARY = """
CREATE TABLE IF NOT EXISTS glossary (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    original_term   TEXT NOT NULL,
    translated_term TEXT,
    is_auto_detected INTEGER NOT NULL DEFAULT 0,
    context         TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(book_id, original_term)
);
"""

CREATE_SESSION_STATE = """
CREATE TABLE IF NOT EXISTS session_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id         INTEGER NOT NULL REFERENCES books(id),
    mode            TEXT NOT NULL DEFAULT 'auto',
    translation_a_id INTEGER REFERENCES translations(id),
    translation_b_id INTEGER REFERENCES translations(id),
    current_page_index INTEGER DEFAULT 0,
    system_prompt   TEXT,
    is_paused       INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ALL_DDL = [
    CREATE_BOOKS,
    CREATE_TRANSLATIONS,
    CREATE_PAGES,
    CREATE_GLOSSARY,
    CREATE_SESSION_STATE,
    CREATE_META,
]


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all tables and set schema version."""
    for ddl in ALL_DDL:
        conn.execute(ddl)
    conn.execute(
        "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Read current schema version from _meta table."""
    try:
        cursor = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
        row = cursor.fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0


def migrate(conn: sqlite3.Connection) -> None:
    """Run migrations to bring database to current schema version."""
    current = get_schema_version(conn)

    if current < 1:
        create_tables(conn)
        return

    if current < 2:
        conn.execute(CREATE_PAGES)
        try:
            conn.execute(
                "ALTER TABLE books ADD COLUMN total_pages INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?)",
            ("schema_version", "2"),
        )
        conn.commit()

    if current < 3:
        conn.execute("DROP TABLE IF EXISTS paragraphs")
        conn.execute("DROP TABLE IF EXISTS paragraphs_backup")
        # rename legacy column in session_state
        try:
            conn.execute(
                "ALTER TABLE session_state RENAME COLUMN current_paragraph_index TO current_page_index"
            )
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?)",
            ("schema_version", "3"),
        )
        conn.commit()
