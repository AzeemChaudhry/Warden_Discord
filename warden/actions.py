"""Steps shared by every moderation action, whether a moderator or automod takes it."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import discord

from .durations import format_duration
from .modlog import Action, Case, send_log
from .settings import Setting, SettingType, register

if TYPE_CHECKING:
    from .bot import Warden

DM_MEMBERS = register(
    Setting(
        key="moderation.dm_members",
        type=SettingType.BOOL,
        default=True,
        description="DM members when they are warned, timed out, kicked or banned.",
    )
)

_DM_VERBS = {
    Action.WARN: "warned in",
    Action.TIMEOUT: "timed out in",
    Action.KICK: "kicked from",
    Action.BAN: "banned from",
}


async def notify_member(
    bot: Warden,
    guild: discord.Guild,
    user: discord.abc.User,
    action: Action,
    reason: str | None,
    duration: timedelta | None = None,
) -> bool:
    """DM the member about the action. Returns whether the DM was delivered."""
    verb = _DM_VERBS.get(action)
    if verb is None or not await bot.settings.get(guild.id, DM_MEMBERS):
        return False
    lines = [f"You were {verb} **{guild.name}**."]
    if duration is not None:
        lines.append(f"Duration: {format_duration(duration)}")
    lines.append(f"Reason: {reason or 'No reason given'}")
    try:
        await user.send("\n".join(lines))
    except discord.HTTPException:
        # DMs closed or no shared server; the mod-log still has the record.
        return False
    return True


async def record_case(
    bot: Warden,
    guild: discord.Guild,
    action: Action,
    target: discord.abc.User,
    moderator: discord.abc.User,
    reason: str | None,
    duration: timedelta | None = None,
) -> Case:
    """Store the case and post it to the mod-log channel."""
    case = await bot.cases.create(
        guild_id=guild.id,
        action=action,
        target_id=target.id,
        moderator_id=moderator.id,
        reason=reason,
        duration=duration,
    )
    await send_log(bot.settings, guild, case, target, moderator)
    return case


def audit_reason(moderator: discord.abc.User, reason: str | None) -> str:
    return f"{moderator} ({moderator.id}): {reason or 'no reason given'}"


class _Placeholders(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, member: discord.Member, **extra: object) -> str:
    """Fill ``{mention}``, ``{user}``, ``{server}``, ``{count}`` and any extras.

    Unknown placeholders are left as-is instead of raising.
    """
    values = _Placeholders(
        mention=member.mention,
        user=member.display_name,
        server=member.guild.name,
        count=member.guild.member_count or "",
        **extra,
    )
    try:
        return template.format_map(values)
    except (ValueError, IndexError):
        return template  # stray braces in a custom message
