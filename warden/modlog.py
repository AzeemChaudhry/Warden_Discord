"""Moderation cases and the mod-log channel.

Every action, whether taken by a moderator or later by automod, goes through
``CaseStore.create`` and ``send_log`` so there is one history per member.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import aiosqlite
import discord

from .db import Database
from .durations import format_duration
from .settings import Setting, SettingsService, SettingType, register

log = logging.getLogger(__name__)

MODLOG_CHANNEL = register(
    Setting(
        key="modlog.channel",
        type=SettingType.CHANNEL,
        default=None,
        description="Channel where every moderation action is logged.",
    )
)


class Action(StrEnum):
    WARN = "warn"
    TIMEOUT = "timeout"
    UNTIMEOUT = "untimeout"
    KICK = "kick"
    BAN = "ban"
    UNBAN = "unban"


_ACTION_STYLE: dict[Action, tuple[str, discord.Colour]] = {
    Action.WARN: ("Warned", discord.Colour.yellow()),
    Action.TIMEOUT: ("Timed out", discord.Colour.orange()),
    Action.UNTIMEOUT: ("Timeout removed", discord.Colour.green()),
    Action.KICK: ("Kicked", discord.Colour.dark_orange()),
    Action.BAN: ("Banned", discord.Colour.red()),
    Action.UNBAN: ("Unbanned", discord.Colour.green()),
}


def action_label(action: Action) -> str:
    return _ACTION_STYLE[action][0]


@dataclass(frozen=True)
class Case:
    guild_id: int
    case_number: int
    action: Action
    target_id: int
    moderator_id: int
    reason: str | None
    duration: timedelta | None
    created_at: str

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> Case:
        seconds = row["duration_seconds"]
        return cls(
            guild_id=row["guild_id"],
            case_number=row["case_number"],
            action=Action(row["action"]),
            target_id=row["target_id"],
            moderator_id=row["moderator_id"],
            reason=row["reason"],
            duration=timedelta(seconds=seconds) if seconds is not None else None,
            created_at=row["created_at"],
        )


class CaseStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(
        self,
        guild_id: int,
        action: Action,
        target_id: int,
        moderator_id: int,
        reason: str | None,
        duration: timedelta | None = None,
    ) -> Case:
        # The subquery numbers cases per guild. aiosqlite runs statements on a
        # single connection thread, so two inserts can't race on the same number.
        cur = await self.db.execute(
            "INSERT INTO cases (guild_id, case_number, action, target_id, moderator_id,"
            " reason, duration_seconds) VALUES (?, (SELECT COALESCE(MAX(case_number), 0) + 1"
            " FROM cases WHERE guild_id = ?), ?, ?, ?, ?, ?)",
            (
                guild_id,
                guild_id,
                action.value,
                target_id,
                moderator_id,
                reason,
                int(duration.total_seconds()) if duration else None,
            ),
        )
        row = await self.db.fetchone("SELECT * FROM cases WHERE id = ?", (cur.lastrowid,))
        return Case.from_row(row)

    async def for_member(self, guild_id: int, target_id: int, limit: int = 10) -> list[Case]:
        rows = await self.db.fetchall(
            "SELECT * FROM cases WHERE guild_id = ? AND target_id = ? ORDER BY case_number DESC LIMIT ?",
            (guild_id, target_id, limit),
        )
        return [Case.from_row(r) for r in rows]

    async def count(
        self, guild_id: int, target_id: int, action: Action, since: datetime | None = None
    ) -> int:
        sql = "SELECT COUNT(*) FROM cases WHERE guild_id = ? AND target_id = ? AND action = ?"
        params: list = [guild_id, target_id, action.value]
        if since is not None:
            sql += " AND created_at >= ?"
            params.append(since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        row = await self.db.fetchone(sql, params)
        return row[0]


def case_embed(case: Case, target: discord.abc.User, moderator: discord.abc.User) -> discord.Embed:
    label, colour = _ACTION_STYLE[case.action]
    embed = discord.Embed(
        title=f"Case #{case.case_number} · {label}",
        colour=colour,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Member", value=f"{target.mention} (`{target.id}`)", inline=True)
    embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)
    if case.duration is not None:
        embed.add_field(name="Duration", value=format_duration(case.duration), inline=True)
    embed.add_field(name="Reason", value=case.reason or "*No reason given*", inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)
    return embed


async def send_log(
    settings: SettingsService,
    guild: discord.Guild,
    case: Case,
    target: discord.abc.User,
    moderator: discord.abc.User,
) -> None:
    """Post the case to the guild's mod-log channel, if one is configured."""
    channel_id = await settings.get(guild.id, MODLOG_CHANNEL)
    if channel_id is None:
        return
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        log.warning("Mod-log channel %s missing in guild %s", channel_id, guild.id)
        return
    try:
        await channel.send(embed=case_embed(case, target, moderator))
    except discord.HTTPException:
        log.warning("Couldn't post to mod-log channel %s in guild %s", channel_id, guild.id, exc_info=True)
