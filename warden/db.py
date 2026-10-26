"""SQLite access and schema migrations."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import aiosqlite

log = logging.getLogger(__name__)

# Each entry is one migration. Append new ones; never edit or reorder old ones.
# The index + 1 is stored in PRAGMA user_version.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE guild_settings (
        guild_id INTEGER NOT NULL,
        key      TEXT    NOT NULL,
        value    TEXT    NOT NULL,  -- JSON-encoded
        PRIMARY KEY (guild_id, key)
    );

    CREATE TABLE cases (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id         INTEGER NOT NULL,
        case_number      INTEGER NOT NULL,
        action           TEXT    NOT NULL,
        target_id        INTEGER NOT NULL,
        moderator_id     INTEGER NOT NULL,
        reason           TEXT,
        duration_seconds INTEGER,
        created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
        UNIQUE (guild_id, case_number)
    );

    CREATE INDEX idx_cases_target ON cases (guild_id, target_id);
    """,
    """
    CREATE TABLE levels (
        guild_id INTEGER NOT NULL,
        user_id  INTEGER NOT NULL,
        xp       INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    );

    CREATE INDEX idx_levels_rank ON levels (guild_id, xp DESC);

    CREATE TABLE level_rewards (
        guild_id INTEGER NOT NULL,
        level    INTEGER NOT NULL,
        role_id  INTEGER NOT NULL,
        PRIMARY KEY (guild_id, level, role_id)
    );
    """,
]


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            await self._conn.execute("PRAGMA journal_mode = WAL")
        await self._migrate()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _migrate(self) -> None:
        async with self.conn.execute("PRAGMA user_version") as cur:
            row = await cur.fetchone()
        current = row[0]
        for version, script in enumerate(MIGRATIONS[current:], start=current + 1):
            log.info("Applying database migration %d", version)
            await self.conn.executescript(script)
            await self.conn.execute(f"PRAGMA user_version = {version}")
            await self.conn.commit()

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Cursor:
        """Run a write statement and commit. The cursor carries ``lastrowid`` and ``rowcount``."""
        cur = await self.conn.execute(sql, tuple(params))
        await self.conn.commit()
        return cur

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return list(await cur.fetchall())
