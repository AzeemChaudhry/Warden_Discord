from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..actions import audit_reason, notify_member, record_case
from ..durations import format_duration, parse_duration
from ..modlog import Action, action_label
from ..settings import Setting, SettingType, register

if TYPE_CHECKING:
    from ..bot import Warden

log = logging.getLogger(__name__)

REQUIRE_REASON = register(
    Setting(
        key="moderation.require_reason",
        type=SettingType.BOOL,
        default=False,
        description="Reject moderation commands that don't include a reason.",
    )
)

# Discord's hard limit for timeouts.
MAX_TIMEOUT = timedelta(days=28)

Reason = app_commands.Range[str, 1, 400] | None


def hierarchy_error(moderator: discord.Member, target: discord.Member) -> str | None:
    """Return why ``moderator`` (or the bot) may not act on ``target``, or None."""
    guild = target.guild
    me = guild.me
    if target.id == moderator.id:
        return "You can't use this on yourself."
    if target.id == me.id:
        return "I can't use this on myself."
    if target.id == guild.owner_id:
        return "The server owner can't be moderated."
    if moderator.id != guild.owner_id and target.top_role >= moderator.top_role:
        return f"{target.mention}'s highest role is equal to or above yours."
    if target.top_role >= me.top_role:
        return (
            f"{target.mention}'s highest role is equal to or above mine, so Discord won't let me act on them."
        )
    return None


class Moderation(commands.Cog):
    def __init__(self, bot: Warden) -> None:
        self.bot = bot

    async def _reject(self, interaction: discord.Interaction, message: str) -> None:
        await interaction.response.send_message(message, ephemeral=True)

    async def _reason_missing(self, interaction: discord.Interaction, reason: str | None) -> bool:
        if reason is None and await self.bot.settings.get(interaction.guild_id, REQUIRE_REASON):
            await self._reject(interaction, "This server requires a reason for moderation actions.")
            return True
        return False

    async def _record(
        self,
        interaction: discord.Interaction,
        action: Action,
        target: discord.abc.User,
        reason: str | None,
        duration: timedelta | None = None,
        dm_sent: bool | None = None,
    ) -> None:
        case = await record_case(
            self.bot, interaction.guild, action, target, interaction.user, reason, duration
        )

        message = f"**Case #{case.case_number}** · {action_label(action)} {target.mention}"
        if duration is not None:
            message += f" for {format_duration(duration)}"
        if reason:
            message += f"\nReason: {reason}"
        if dm_sent is False:
            message += "\n-# They weren't notified by DM."
        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(description="Warn a member")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(member="Who to warn", reason="Why they are being warned")
    async def warn(
        self, interaction: discord.Interaction, member: discord.Member, reason: Reason = None
    ) -> None:
        if error := hierarchy_error(interaction.user, member):
            return await self._reject(interaction, error)
        if member.bot:
            return await self._reject(interaction, "Bots can't be warned.")
        if await self._reason_missing(interaction, reason):
            return
        await interaction.response.defer(ephemeral=True)
        dm_sent = await notify_member(self.bot, interaction.guild, member, Action.WARN, reason)
        await self._record(interaction, Action.WARN, member, reason, dm_sent=dm_sent)

    @app_commands.command(description="Time out a member so they can't chat or join voice")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.describe(
        member="Who to time out",
        duration="How long, e.g. 10m, 2h, 1d12h (max 28d)",
        reason="Why they are being timed out",
    )
    async def timeout(
        self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: Reason = None
    ) -> None:
        if error := hierarchy_error(interaction.user, member):
            return await self._reject(interaction, error)
        if member.guild_permissions.administrator:
            return await self._reject(interaction, "Discord doesn't allow timing out administrators.")
        try:
            length = parse_duration(duration)
        except ValueError as exc:
            return await self._reject(interaction, str(exc))
        if length > MAX_TIMEOUT:
            return await self._reject(interaction, "Timeouts can be at most 28 days.")
        if await self._reason_missing(interaction, reason):
            return

        await interaction.response.defer(ephemeral=True)
        await member.timeout(length, reason=audit_reason(interaction.user, reason))
        dm_sent = await notify_member(self.bot, interaction.guild, member, Action.TIMEOUT, reason, length)
        await self._record(interaction, Action.TIMEOUT, member, reason, length, dm_sent=dm_sent)

    @app_commands.command(description="Remove a member's timeout")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="Whose timeout to remove", reason="Why it's being removed")
    async def untimeout(
        self, interaction: discord.Interaction, member: discord.Member, reason: Reason = None
    ) -> None:
        if not member.is_timed_out():
            return await self._reject(interaction, f"{member.mention} isn't timed out.")
        if error := hierarchy_error(interaction.user, member):
            return await self._reject(interaction, error)
        await interaction.response.defer(ephemeral=True)
        await member.timeout(None, reason=audit_reason(interaction.user, reason))
        await self._record(interaction, Action.UNTIMEOUT, member, reason)

    @app_commands.command(description="Kick a member from the server")
    @app_commands.guild_only()
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    @app_commands.describe(member="Who to kick", reason="Why they are being kicked")
    async def kick(
        self, interaction: discord.Interaction, member: discord.Member, reason: Reason = None
    ) -> None:
        if error := hierarchy_error(interaction.user, member):
            return await self._reject(interaction, error)
        if await self._reason_missing(interaction, reason):
            return
        await interaction.response.defer(ephemeral=True)
        # DM first: once they're gone we may no longer share a server.
        dm_sent = await notify_member(self.bot, interaction.guild, member, Action.KICK, reason)
        await member.kick(reason=audit_reason(interaction.user, reason))
        await self._record(interaction, Action.KICK, member, reason, dm_sent=dm_sent)

    @app_commands.command(description="Ban a user, whether or not they are in the server")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.describe(
        user="Who to ban",
        reason="Why they are being banned",
        delete_days="Delete their messages from the last N days (0-7)",
    )
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: Reason = None,
        delete_days: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        guild = interaction.guild
        member = guild.get_member(user.id) or (user if isinstance(user, discord.Member) else None)
        if member is not None:
            if error := hierarchy_error(interaction.user, member):
                return await self._reject(interaction, error)
        elif user.id == interaction.user.id:
            return await self._reject(interaction, "You can't use this on yourself.")
        if await self._reason_missing(interaction, reason):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await guild.fetch_ban(user)
        except discord.NotFound:
            pass
        else:
            await interaction.followup.send(f"{user.mention} is already banned.", ephemeral=True)
            return

        dm_sent = (
            await notify_member(self.bot, guild, user, Action.BAN, reason) if member is not None else None
        )
        await guild.ban(
            user,
            reason=audit_reason(interaction.user, reason),
            delete_message_seconds=delete_days * 86400,
        )
        await self._record(interaction, Action.BAN, user, reason, dm_sent=dm_sent)

    @app_commands.command(description="Lift a ban")
    @app_commands.guild_only()
    @app_commands.default_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    @app_commands.describe(user_id="The banned user's ID", reason="Why the ban is being lifted")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: Reason = None) -> None:
        if not user_id.strip().isdigit():
            return await self._reject(interaction, "That isn't a valid user ID.")
        await interaction.response.defer(ephemeral=True)
        try:
            ban = await interaction.guild.fetch_ban(discord.Object(id=int(user_id)))
        except discord.NotFound:
            await interaction.followup.send("That user isn't banned.", ephemeral=True)
            return
        await interaction.guild.unban(ban.user, reason=audit_reason(interaction.user, reason))
        await self._record(interaction, Action.UNBAN, ban.user, reason)

    @app_commands.command(description="Show a member's moderation history")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(user="Whose history to show")
    async def cases(self, interaction: discord.Interaction, user: discord.User) -> None:
        history = await self.bot.cases.for_member(interaction.guild_id, user.id)
        if not history:
            return await self._reject(interaction, f"{user.mention} has a clean record.")
        warnings = await self.bot.cases.count(interaction.guild_id, user.id, Action.WARN)
        embed = discord.Embed(
            title=f"History for {user}",
            description=f"{warnings} warning(s) total · latest {len(history)} cases shown",
            colour=discord.Colour.blurple(),
        )
        for case in history:
            detail = case.reason or "*No reason given*"
            if case.duration is not None:
                detail = f"{format_duration(case.duration)} · {detail}"
            embed.add_field(
                name=f"#{case.case_number} · {action_label(case.action)} · {case.created_at[:10]}",
                value=f"{detail}\n-# by <@{case.moderator_id}>",
                inline=False,
            )
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: Warden) -> None:
    await bot.add_cog(Moderation(bot))
