"""Automod: filters every message and join, and escalates repeat offenders.

Messages that pass are re-dispatched as ``warden_message_passed`` and joins
that pass raid checks as ``warden_member_admitted``, so leveling and onboarding
never act on spam or raid accounts.
"""

from __future__ import annotations

import contextlib
import logging
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..actions import audit_reason, notify_member, record_case
from ..filters import RateTracker, count_mentions, find_bad_word, find_blocked_link
from ..modlog import MODLOG_CHANNEL, Action
from ..settings import SettingType, setting_group

if TYPE_CHECKING:
    from ..bot import Warden

log = logging.getLogger(__name__)


_define = setting_group("automod")

ENABLED = _define("enabled", SettingType.BOOL, True, "Master switch for every automod rule.")
EXEMPT_ROLE = _define(
    "exempt_role",
    SettingType.ROLE,
    None,
    "Members with this role skip automod. Members with Manage Messages always do.",
)
BADWORDS_ENABLED = _define(
    "badwords_enabled", SettingType.BOOL, True, "Delete messages containing a blocked word."
)
BADWORDS = _define(
    "badwords", SettingType.LIST, [], "Blocked words or phrases, comma-separated. Also see /automod words."
)
LINKS_ENABLED = _define(
    "links_enabled", SettingType.BOOL, False, "Delete messages with links not on the allowlist."
)
LINK_ALLOWLIST = _define(
    "link_allowlist",
    SettingType.LIST,
    ["tenor.com", "giphy.com"],
    "Domains allowed when the link filter is on, comma-separated.",
)
BLOCK_INVITES = _define("block_invites", SettingType.BOOL, True, "Delete Discord server invites.")
SPAM_ENABLED = _define(
    "spam_enabled", SettingType.BOOL, True, "Strike members who send messages too quickly."
)
SPAM_MESSAGES = _define(
    "spam_messages", SettingType.INT, 6, "Messages that count as spam...", min_value=2, max_value=50
)
SPAM_SECONDS = _define(
    "spam_seconds", SettingType.INT, 5, "...within this many seconds.", min_value=1, max_value=120
)
MAX_MENTIONS = _define(
    "max_mentions",
    SettingType.INT,
    5,
    "Most users/roles one message may ping (0 = no limit).",
    min_value=0,
    max_value=100,
)
RAID_MODE = _define(
    "raid_mode", SettingType.BOOL, False, "While on, new members are kicked on join. Use /automod raid."
)
RAID_JOINS = _define(
    "raid_joins",
    SettingType.INT,
    10,
    "Joins that switch raid mode on automatically (0 = never)...",
    min_value=0,
    max_value=500,
)
RAID_SECONDS = _define(
    "raid_seconds", SettingType.INT, 10, "...within this many seconds.", min_value=1, max_value=600
)
STRIKE_WINDOW = _define(
    "strike_window_days",
    SettingType.INT,
    30,
    "Only warnings from the last N days count as strikes (0 = all time).",
    min_value=0,
    max_value=3650,
)
TIMEOUT_AT = _define(
    "timeout_at", SettingType.INT, 3, "Strikes before a timeout (0 = never).", min_value=0, max_value=100
)
TIMEOUT_MINUTES = _define(
    "timeout_minutes", SettingType.INT, 60, "Length of an automatic timeout.", min_value=1, max_value=40320
)
KICK_AT = _define(
    "kick_at", SettingType.INT, 5, "Strikes before a kick (0 = never).", min_value=0, max_value=100
)
BAN_AT = _define(
    "ban_at", SettingType.INT, 7, "Strikes before a ban (0 = never).", min_value=0, max_value=100
)


def bot_can_act_on(member: discord.Member) -> bool:
    guild = member.guild
    return member.id != guild.owner_id and member.top_role < guild.me.top_role


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Automod(commands.GroupCog, group_name="automod", group_description="Automod controls"):
    words = app_commands.Group(name="words", description="Manage the blocked word list")

    def __init__(self, bot: Warden) -> None:
        self.bot = bot
        self.settings = bot.settings
        self.spam = RateTracker()
        self.joins = RateTracker()
        super().__init__()

    async def cog_load(self) -> None:
        self.prune_trackers.start()

    async def cog_unload(self) -> None:
        self.prune_trackers.cancel()

    @tasks.loop(minutes=10)
    async def prune_trackers(self) -> None:
        now = time.monotonic()
        self.spam.prune(now, 600)
        self.joins.prune(now, 600)

    # -- message filters ---------------------------------------------------

    async def _is_exempt(self, member: discord.Member) -> bool:
        if member.guild_permissions.manage_messages:
            return True
        role_id = await self.settings.get(member.guild.id, EXEMPT_ROLE)
        return role_id is not None and member.get_role(role_id) is not None

    async def find_violation(self, message: discord.Message) -> str | None:
        """Return why ``message`` breaks a rule, or None if it's fine."""
        gid = message.guild.id
        if not await self.settings.get(gid, ENABLED) or await self._is_exempt(message.author):
            return None

        content = message.content
        if await self.settings.get(gid, BADWORDS_ENABLED) and find_bad_word(
            content, await self.settings.get(gid, BADWORDS)
        ):
            return "used a blocked word"

        reason = find_blocked_link(
            content,
            block_links=await self.settings.get(gid, LINKS_ENABLED),
            block_invites=await self.settings.get(gid, BLOCK_INVITES),
            allowlist=await self.settings.get(gid, LINK_ALLOWLIST),
        )
        if reason:
            return reason

        limit = await self.settings.get(gid, MAX_MENTIONS)
        if limit and count_mentions(content, message.raw_mentions, message.raw_role_mentions) > limit:
            return f"pinged more than {limit} users or roles"

        if await self.settings.get(gid, SPAM_ENABLED) and self.spam.hit(
            (gid, message.author.id),
            time.monotonic(),
            await self.settings.get(gid, SPAM_MESSAGES),
            await self.settings.get(gid, SPAM_SECONDS),
        ):
            return "sent messages too quickly"
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        reason = await self.find_violation(message)
        if reason is None:
            self.bot.dispatch("warden_message_passed", message)
            return
        with contextlib.suppress(discord.HTTPException):
            await message.delete()
        await self.strike(message.author, f"Automod: {reason}", message.channel)

    async def strike(
        self,
        member: discord.Member,
        reason: str,
        channel: discord.abc.Messageable | None = None,
    ) -> None:
        """Warn ``member`` and escalate if they've passed a strike threshold."""
        guild = member.guild
        me = guild.me
        await record_case(self.bot, guild, Action.WARN, member, me, reason)
        await notify_member(self.bot, guild, member, Action.WARN, reason)

        days = await self.settings.get(guild.id, STRIKE_WINDOW)
        since = discord.utils.utcnow() - timedelta(days=days) if days else None
        strikes = await self.bot.cases.count(guild.id, member.id, Action.WARN, since)

        if channel is not None:
            with contextlib.suppress(discord.HTTPException):
                await channel.send(
                    f"{member.mention}, your message was removed: {reason.removeprefix('Automod: ')}. "
                    f"Strike {strikes}.",
                    delete_after=10,
                )

        await self._escalate(member, strikes)

    async def _escalate(self, member: discord.Member, strikes: int) -> None:
        guild = member.guild
        me = guild.me
        ban_at, kick_at, timeout_at = (
            await self.settings.get(guild.id, BAN_AT),
            await self.settings.get(guild.id, KICK_AT),
            await self.settings.get(guild.id, TIMEOUT_AT),
        )
        if ban_at and strikes >= ban_at:
            action = Action.BAN
        elif kick_at and strikes >= kick_at:
            action = Action.KICK
        elif timeout_at and strikes >= timeout_at:
            action = Action.TIMEOUT
        else:
            return

        if not bot_can_act_on(member):
            log.info("Can't escalate %s in %s: role hierarchy", member.id, guild.id)
            return

        reason = f"Automod: reached {strikes} strikes"
        duration = None
        try:
            if action is Action.BAN:
                await notify_member(self.bot, guild, member, action, reason)
                await guild.ban(member, reason=audit_reason(me, reason), delete_message_seconds=3600)
            elif action is Action.KICK:
                await notify_member(self.bot, guild, member, action, reason)
                await member.kick(reason=audit_reason(me, reason))
            else:
                if member.guild_permissions.administrator:
                    return
                duration = timedelta(minutes=await self.settings.get(guild.id, TIMEOUT_MINUTES))
                await member.timeout(duration, reason=audit_reason(me, reason))
                await notify_member(self.bot, guild, member, action, reason, duration)
        except discord.HTTPException:
            log.warning("Escalation to %s failed for %s in %s", action, member.id, guild.id, exc_info=True)
            return
        await record_case(self.bot, guild, action, member, me, reason, duration)

    # -- raids -------------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        if member.bot:
            self.bot.dispatch("warden_member_admitted", member)
            return

        raid = await self.settings.get(guild.id, RAID_MODE)
        if not raid:
            joins = await self.settings.get(guild.id, RAID_JOINS)
            if joins and self.joins.hit(
                guild.id, time.monotonic(), joins, await self.settings.get(guild.id, RAID_SECONDS)
            ):
                raid = True
                await self.settings.set(guild.id, RAID_MODE, True)
                await self._alert(
                    guild,
                    f":rotating_light: **Raid mode is on**: {joins} members joined within "
                    f"{await self.settings.get(guild.id, RAID_SECONDS)} seconds. New members will be kicked "
                    "until a moderator runs `/automod raid state:off`.",
                )

        if not raid:
            self.bot.dispatch("warden_member_admitted", member)
            return

        with contextlib.suppress(discord.HTTPException):
            await member.send(
                f"**{guild.name}** isn't accepting new members right now. Please try again later."
            )
        try:
            await member.kick(reason="Raid mode is on")
        except discord.HTTPException:
            log.warning("Raid mode couldn't kick %s in %s", member.id, guild.id)

    async def _alert(self, guild: discord.Guild, text: str) -> None:
        channel_id = await self.settings.get(guild.id, MODLOG_CHANNEL)
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.abc.Messageable):
            with contextlib.suppress(discord.HTTPException):
                await channel.send(text)

    # -- commands ----------------------------------------------------------

    @app_commands.command(name="raid", description="Turn raid mode on or off")
    @app_commands.describe(state="on: kick everyone who joins. off: back to normal.")
    async def raid(self, interaction: discord.Interaction, state: Literal["on", "off"]) -> None:
        enabled = state == "on"
        await self.settings.set(interaction.guild_id, RAID_MODE, enabled)
        await self._alert(
            interaction.guild,
            f"{':rotating_light:' if enabled else ':white_check_mark:'} Raid mode turned **{state}** by {interaction.user.mention}.",
        )
        await interaction.response.send_message(f"Raid mode is now **{state}**.", ephemeral=True)

    @words.command(name="add", description="Block words or phrases")
    @app_commands.describe(words="One or more, separated by commas")
    async def words_add(self, interaction: discord.Interaction, words: str) -> None:
        current = await self.settings.get(interaction.guild_id, BADWORDS)
        new = [w.strip().lower() for w in words.split(",") if w.strip()]
        merged = list(dict.fromkeys([*current, *new]))
        await self.settings.set(interaction.guild_id, BADWORDS, merged)
        await interaction.response.send_message(
            f"Added {len(merged) - len(current)} word(s). {len(merged)} blocked in total.", ephemeral=True
        )

    @words.command(name="remove", description="Unblock words or phrases")
    @app_commands.describe(words="One or more, separated by commas")
    async def words_remove(self, interaction: discord.Interaction, words: str) -> None:
        current = await self.settings.get(interaction.guild_id, BADWORDS)
        drop = {w.strip().lower() for w in words.split(",")}
        kept = [w for w in current if w not in drop]
        await self.settings.set(interaction.guild_id, BADWORDS, kept)
        await interaction.response.send_message(
            f"Removed {len(current) - len(kept)} word(s). {len(kept)} blocked in total.", ephemeral=True
        )

    @words.command(name="list", description="Show the blocked words")
    async def words_list(self, interaction: discord.Interaction) -> None:
        current = await self.settings.get(interaction.guild_id, BADWORDS)
        if not current:
            await interaction.response.send_message("No words are blocked.", ephemeral=True)
            return
        text = ", ".join(f"||{w}||" for w in current)
        await interaction.response.send_message(
            f"**Blocked ({len(current)}):** {text[:1900]}", ephemeral=True
        )


async def setup(bot: Warden) -> None:
    await bot.add_cog(Automod(bot))
