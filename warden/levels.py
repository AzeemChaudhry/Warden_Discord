"""XP storage and the level curve."""

from __future__ import annotations

from dataclasses import dataclass

from .db import Database


def xp_to_next(level: int) -> int:
    """XP needed to go from ``level`` to ``level + 1``."""
    return 5 * level * level + 50 * level + 100


@dataclass(frozen=True)
class Progress:
    level: int
    xp_into_level: int
    xp_needed: int  # for the next level

    @property
    def fraction(self) -> float:
        return self.xp_into_level / self.xp_needed


def progress_for(total_xp: int) -> Progress:
    level, remaining = 0, max(total_xp, 0)
    while remaining >= (needed := xp_to_next(level)):
        remaining -= needed
        level += 1
    return Progress(level, remaining, needed)


def level_for(total_xp: int) -> int:
    return progress_for(total_xp).level


class LevelStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_xp(self, guild_id: int, user_id: int) -> int:
        row = await self.db.fetchone(
            "SELECT xp FROM levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        return row["xp"] if row else 0

    async def add_xp(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int]:
        """Add (or subtract) XP, never going below zero. Returns (old, new) totals."""
        old = await self.get_xp(guild_id, user_id)
        new = max(old + amount, 0)
        await self.set_xp(guild_id, user_id, new)
        return old, new

    async def set_xp(self, guild_id: int, user_id: int, xp: int) -> None:
        await self.db.execute(
            "INSERT INTO levels (guild_id, user_id, xp) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET xp = excluded.xp",
            (guild_id, user_id, max(xp, 0)),
        )

    async def rank(self, guild_id: int, user_id: int) -> int | None:
        """1-based leaderboard position, or None if they have no XP."""
        xp = await self.get_xp(guild_id, user_id)
        if xp == 0:
            return None
        row = await self.db.fetchone(
            "SELECT COUNT(*) FROM levels WHERE guild_id = ? AND xp > ?", (guild_id, xp)
        )
        return row[0] + 1

    async def top(self, guild_id: int, limit: int = 10, offset: int = 0) -> list[tuple[int, int]]:
        rows = await self.db.fetchall(
            "SELECT user_id, xp FROM levels WHERE guild_id = ? AND xp > 0"
            " ORDER BY xp DESC, user_id LIMIT ? OFFSET ?",
            (guild_id, limit, offset),
        )
        return [(r["user_id"], r["xp"]) for r in rows]

    async def count(self, guild_id: int) -> int:
        row = await self.db.fetchone("SELECT COUNT(*) FROM levels WHERE guild_id = ? AND xp > 0", (guild_id,))
        return row[0]

    # -- level rewards (perks) ---------------------------------------------

    async def rewards(self, guild_id: int) -> list[tuple[int, int]]:
        """All (level, role_id) rewards for a guild, lowest level first."""
        rows = await self.db.fetchall(
            "SELECT level, role_id FROM level_rewards WHERE guild_id = ? ORDER BY level, role_id",
            (guild_id,),
        )
        return [(r["level"], r["role_id"]) for r in rows]

    async def add_reward(self, guild_id: int, level: int, role_id: int) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?)",
            (guild_id, level, role_id),
        )

    async def remove_reward(self, guild_id: int, level: int, role_id: int) -> bool:
        """Returns whether a reward was actually removed."""
        cur = await self.db.execute(
            "DELETE FROM level_rewards WHERE guild_id = ? AND level = ? AND role_id = ?",
            (guild_id, level, role_id),
        )
        return cur.rowcount > 0


def reward_roles_for(level: int, rewards: list[tuple[int, int]], stack: bool) -> set[int]:
    """Role IDs a member at ``level`` should hold.

    With ``stack`` they keep every reward up to their level; without it only
    the rewards for the highest level they've reached.
    """
    earned = [(lvl, role) for lvl, role in rewards if lvl <= level]
    if not earned:
        return set()
    if stack:
        return {role for _, role in earned}
    top = max(lvl for lvl, _ in earned)
    return {role for lvl, role in earned if lvl == top}
