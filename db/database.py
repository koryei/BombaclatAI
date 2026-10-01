import asyncio
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import aiosqlite

import config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    guild_id INTEGER,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    author_name TEXT NOT NULL,
    content TEXT NOT NULL,
    is_bot INTEGER DEFAULT 0,
    is_dm INTEGER DEFAULT 0,
    discord_message_id INTEGER,
    is_command INTEGER DEFAULT 0,
    is_attachment_only INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_channel_ts ON messages(channel_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, timestamp);

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    is_owner INTEGER DEFAULT 0,
    vibe_energy REAL DEFAULT 0.5,
    vibe_formality REAL DEFAULT 0.4,
    trust_score REAL DEFAULT 0.5,
    interaction_count INTEGER DEFAULT 0,
    first_seen REAL,
    last_seen REAL,
    notes TEXT DEFAULT '',
    message_count INTEGER DEFAULT 0,
    question_count INTEGER DEFAULT 0,
    emoji_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL,
    about_user_id INTEGER NOT NULL,
    memory_text TEXT NOT NULL,
    category TEXT DEFAULT 'fact',
    confidence REAL DEFAULT 0.6,
    guild_id INTEGER,
    is_sensitive INTEGER DEFAULT 0,
    verified_by_owner INTEGER DEFAULT 0,
    last_referenced REAL,
    source_channel_id INTEGER,
    source_is_private_dm INTEGER DEFAULT 0,
    source_message_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(about_user_id);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL,
    guild_id INTEGER,
    channel_id INTEGER,
    trigger_type TEXT,
    decision TEXT,
    reasoning TEXT,
    confidence REAL,
    message_sent TEXT,
    sent_message_id INTEGER,
    owner_feedback TEXT,
    feedback_timestamp REAL,
    dm_sent INTEGER DEFAULT 0,
    action_type TEXT DEFAULT 'text',
    reaction_emoji TEXT,
    gif_category TEXT,
    target_message_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(timestamp);

CREATE TABLE IF NOT EXISTS review_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    owner_id INTEGER NOT NULL,
    guild_id INTEGER,
    channel_id INTEGER,
    is_private_channel INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    mode TEXT NOT NULL DEFAULT 'important',
    context_json TEXT NOT NULL DEFAULT '[]',
    report_text TEXT NOT NULL DEFAULT '',
    review_channel_id INTEGER,
    review_message_id INTEGER,
    feedback TEXT,
    feedback_note TEXT,
    feedback_source TEXT,
    feedback_at REAL,
    delivered_at REAL,
    last_interaction_at REAL
);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON review_sessions(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_reviews_message ON review_sessions(review_message_id);

CREATE TABLE IF NOT EXISTS review_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    author_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    content TEXT NOT NULL,
    discord_message_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_review_messages_session ON review_messages(session_id, timestamp);

CREATE TABLE IF NOT EXISTS trigger_weights (
    trigger_type TEXT PRIMARY KEY,
    weight REAL DEFAULT 1.0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_updated REAL
);

CREATE TABLE IF NOT EXISTS bot_config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER,
    text TEXT NOT NULL,
    due_at REAL NOT NULL,
    created_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    delivered_at REAL,
    discord_message_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_at);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id, channel_id, status);

CREATE TABLE IF NOT EXISTS channel_settings (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER,
    channel_name TEXT,
    is_private_dm INTEGER DEFAULT 0,
    autonomous_enabled INTEGER DEFAULT 1,
    last_autonomous_post REAL DEFAULT 0,
    last_owner_dm REAL DEFAULT 0,
    last_autonomous_evaluation REAL DEFAULT 0,
    last_evaluated_message_id INTEGER,
    review_preview_enabled INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS curiosity_state (
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    last_attempt REAL DEFAULT 0,
    last_post REAL DEFAULT 0,
    PRIMARY KEY (user_id, channel_id)
);

CREATE TABLE IF NOT EXISTS interaction_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    event_type TEXT NOT NULL,
    channel_id INTEGER,
    guild_id INTEGER,
    batch_id TEXT,
    message_ids TEXT,
    participant_ids TEXT,
    decision_id INTEGER,
    status TEXT,
    latency_ms REAL,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON interaction_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_channel_ts ON interaction_events(channel_id, timestamp);

CREATE TABLE IF NOT EXISTS gif_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    source_channel_id INTEGER,
    source_message_id INTEGER,
    mime_type TEXT NOT NULL DEFAULT 'image/gif',
    categories TEXT NOT NULL DEFAULT '["other"]',
    description TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at REAL NOT NULL,
    last_used REAL,
    use_count INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_gif_library_enabled ON gif_library(enabled);

CREATE TABLE IF NOT EXISTS humor_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    channel_id INTEGER NOT NULL,
    target_message_id INTEGER NOT NULL,
    reviewer_id INTEGER NOT NULL,
    label TEXT NOT NULL CHECK(label IN ('good', 'bad')),
    note TEXT NOT NULL DEFAULT '',
    response_text TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(target_message_id, reviewer_id)
);
CREATE INDEX IF NOT EXISTS idx_humor_feedback_label ON humor_feedback(label, created_at);
"""


class Database:
    """Thin async wrapper around a single SQLite connection.

    SQLite only supports one writer at a time, so every statement is
    serialized behind a lock. At this scale (a friend group's chat traffic)
    that's not a real bottleneck, and it keeps the persistence layer simple
    and safe from "database is locked" errors.
    """

    def __init__(self, path: Optional[str] = None):
        # Resolve the default at instance creation time so tests and runtime
        # config overrides cannot accidentally keep using an old imported path.
        self.path = path or config.DB_PATH
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA busy_timeout=5000;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        await self._run_migrations()
        logger.info("Database connected at %s", self.path)

    async def _run_migrations(self) -> None:
        """Adds columns introduced after a database was first created, so
        upgrading the bot never requires deleting existing history/memory."""
        await self._ensure_column("messages", "discord_message_id", "INTEGER")
        await self._ensure_column("messages", "is_command", "INTEGER DEFAULT 0")
        await self._ensure_column("messages", "is_attachment_only", "INTEGER DEFAULT 0")
        await self._ensure_column("memories", "source_channel_id", "INTEGER")
        await self._ensure_column("memories", "source_is_private_dm", "INTEGER DEFAULT 0")
        await self._ensure_column("memories", "source_message_id", "INTEGER")
        await self._ensure_column("users", "message_count", "INTEGER DEFAULT 0")
        await self._ensure_column("users", "question_count", "INTEGER DEFAULT 0")
        await self._ensure_column("users", "emoji_count", "INTEGER DEFAULT 0")
        await self._ensure_column("decisions", "action_type", "TEXT DEFAULT 'text'")
        await self._ensure_column("decisions", "reaction_emoji", "TEXT")
        await self._ensure_column("decisions", "gif_category", "TEXT")
        await self._ensure_column("decisions", "target_message_id", "INTEGER")
        await self._ensure_column("channel_settings", "is_private_dm", "INTEGER DEFAULT 0")
        await self._ensure_column("channel_settings", "last_autonomous_evaluation", "REAL DEFAULT 0")
        await self._ensure_column("channel_settings", "last_evaluated_message_id", "INTEGER")
        await self._ensure_column("channel_settings", "review_preview_enabled", "INTEGER DEFAULT 0")
        assert self._conn is not None
        await self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_discord_id "
            "ON messages(discord_message_id) WHERE discord_message_id IS NOT NULL"
        )
        await self._conn.commit()

    async def _ensure_column(self, table: str, column: str, definition: str) -> None:
        assert self._conn is not None
        cursor = await self._conn.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        await cursor.close()
        existing_columns = {row[1] for row in rows}
        if column not in existing_columns:
            await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            await self._conn.commit()
            logger.info("Migrated database: added %s.%s", table, column)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run a write statement, returns the last inserted row id (if any)."""
        assert self._conn is not None, "Database not connected"
        async with self._lock:
            cursor = await self._conn.execute(sql, params)
            await self._conn.commit()
            row_id = cursor.lastrowid
            await cursor.close()
            return row_id or 0

    async def execute_count(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Run an update/delete and return affected rows for idempotent writes."""
        assert self._conn is not None, "Database not connected"
        async with self._lock:
            cursor = await self._conn.execute(sql, params)
            await self._conn.commit()
            count = cursor.rowcount
            await cursor.close()
            return count

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> Optional[aiosqlite.Row]:
        assert self._conn is not None, "Database not connected"
        async with self._lock:
            cursor = await self._conn.execute(sql, params)
            row = await cursor.fetchone()
            await cursor.close()
            return row

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        assert self._conn is not None, "Database not connected"
        async with self._lock:
            cursor = await self._conn.execute(sql, params)
            rows = await cursor.fetchall()
            await cursor.close()
            return list(rows)
