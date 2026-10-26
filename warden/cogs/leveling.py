"""XP per message, /rank, /leaderboard and admin XP tools.

Only messages automod lets through earn XP (``warden_message_passed``). Any
level change is dispatched as ``warden_level_changed`` for the perks module.
"""

from __future__ import annotations

import contextlib
import random
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..actions import render
from ..levels import level_for, progress_for
from ..settings import SettingType, setting_group

if TYPE_CHECKING:
    from ..bot import Warden


_define = setting_group("leveling")

ENABLED = _define("enabled", SettingType.BOOL, True, "Members earn XP for chatting.")
XP_MIN = _define("xp_min", SettingType.INT, 15, "Least XP one message can earn.", min_value=0, max_value=1000)
XP_MAX = _define("xp_max", SettingType.INT, 25, "Most XP one message can earn.", min_value=0, max_value=1000)
COOLDOWN = _define(
    "cooldown_seconds",
    SettingType.INT,
    60,
    "Seconds before the same member can earn XP again.",
    min_value=0,
    max_value=3600,
)
ANNOUNCE = _define("announce", SettingType.BOOL, True, "Post a message when someone levels up.")
ANNOUNCE_CHANNEL = _define(
    "announce_channel",
    SettingType.CHANNEL,
    None,
    "Where level-ups are posted (not set = the channel they chatted in).",
)
LEVELUP_MESSAGE = _define(
    "levelup_message",
    SettingType.STRING,
    "GG {mention}, you reached **level {level}**!",
    "Level-up text. Placeholders: {mention} {user} {level} {server}.",
)
IGNORED_CHANNELS = _define(
    "ignored_channels",
    SettingType.LIST,
    [],
    "Channels where no XP is earned: #mentions or IDs, comma-separated.",
)

# Cooldown entries older than the longest allowed cooldown are useless.
_PRUNE_AFTER = 3600
_PRUNE_AT_SIZE = 5000

BAR_SEGMENTS = 12


def progress_bar(fraction: float) -> str:
    filled = round(fraction * BAR_SEGMENTS)
    return "▰" * filled + "▱" * (BAR_SEGMENTS - filled)


class Leveling(commands.Cog):
    xp = app_commands.Group(
        name="xp",
        description="Adjust members' XP",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: Warden) -> None:
        self.bot = bot
        self.settings = bot.settings
        self._last_award: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_warden_message_passed(self, message: discord.Message) -> None:
        guild = message.guild
        if not await self.settings.get(guild.id, ENABLED):
            return
        ignored = await self.settings.get(guild.id, IGNORED_CHANNELS)
        if str(message.channel.id) in ignored or message.channel.mention in ignored:
            return

        key = (guild.id, message.author.id)
        now = time.monotonic()
        if now - self._last_award.get(key, float("-inf")) < await self.settings.get(guild.id, COOLDOWN):
            return
        self._last_award[key] = now
        if len(self._last_award) > _PRUNE_AT_SIZE:
            self._last_award = {k: t for k, t in self._last_award.items() if now - t < _PRUNE_AFTER}

        low, high = sorted(
            (await self.settings.get(guild.id, XP_MIN), await self.settings.get(guild.id, XP_MAX))
        )
        old, new = await self.bot.levels.add_xp(guild.id, message.author.id, random.randint(low, high))
        old_level, new_level = level_for(old), level_for(new)
        if new_level == old_level:
            return

        self.bot.dispatch("warden_level_changed", message.author, old_level, new_level)
        if new_level > old_level and await self.settings.get(guild.id, ANNOUNCE):
            await self._announce(message, new_level)

    async def _announce(self, message: discord.Message, level: int) -> None:
        guild = message.guild
        channel_id = await self.settings.get(guild.id, ANNOUNCE_CHANNEL)
        channel = guild.get_channel(channel_id) if channel_id else message.channel
        if not isinstance(channel, discord.abc.Messageable):
            channel = message.channel
        text = render(await self.settings.get(guild.id, LEVELUP_MESSAGE), message.author, level=level)
        with contextlib.suppress(discord.HTTPException):
            await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[message.author]))

    @app_commands.command(description="Show your level, or someone else's")
    @app_commands.guild_only()
    @app_commands.describe(member="Whose rank to show (defaults to you)")
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        member = member or interaction.user
        guild_id = interaction.guild_id
        xp = await self.bot.levels.get_xp(guild_id, member.id)
        progress = progress_for(xp)
        position = await self.bot.levels.rank(guild_id, member.id)

        colour = member.colour if member.colour.value else discord.Colour.blurple()
        embed = discord.Embed(title=member.display_name, colour=colour)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=str(progress.level))
        embed.add_field(name="Rank", value=f"#{position}" if position else "unranked")
        embed.add_field(name="Total XP", value=f"{xp:,}")
        embed.add_field(
            name="Next level",
            value=f"{progress_bar(progress.fraction)}  {progress.xp_into_level:,} / {progress.xp_needed:,} XP",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Show the most active members")
    @app_commands.guild_only()
    @app_commands.describe(page="Page number")
    async def leaderboard(
        self, interaction: discord.Interaction, page: app_commands.Range[int, 1, 1000] = 1
    ) -> None:
        per_page = 10
        guild_id = interaction.guild_id
        total = await self.bot.levels.count(guild_id)
        pages = max((total + per_page - 1) // per_page, 1)
        page = min(page, pages)
        rows = await self.bot.levels.top(guild_id, per_page, (page - 1) * per_page)
        if not rows:
            await interaction.response.send_message("Nobody has earned XP yet.", ephemeral=True)
            return

        medals = {1: ":first_place:", 2: ":second_place:", 3: ":third_place:"}
        start = (page - 1) * per_page + 1
        lines = [
            f"{medals.get(pos, f'`#{pos}`')} <@{user_id}> · level {level_for(xp)} · {xp:,} XP"
            for pos, (user_id, xp) in enumerate(rows, start=start)
        ]
        embed = discord.Embed(
            title=f"{interaction.guild.name} leaderboard",
            description="\n".join(lines),
            colour=discord.Colour.gold(),
        )
        embed.set_footer(text=f"Page {page} of {pages}")
        await interaction.response.send_message(embed=embed)

    async def _change_xp(
        self, interaction: discord.Interaction, member: discord.Member, new_total: int
    ) -> None:
        old = await self.bot.levels.get_xp(interaction.guild_id, member.id)
        await self.bot.levels.set_xp(interaction.guild_id, member.id, new_total)
        new = max(new_total, 0)
        old_level, new_level = level_for(old), level_for(new)
        if old_level != new_level:
            self.bot.dispatch("warden_level_changed", member, old_level, new_level)
        await interaction.response.send_message(
            f"{member.mention} now has **{new:,} XP** (level {new_level}).", ephemeral=True
        )

    @xp.command(name="add", description="Give or take XP (use a negative number to take)")
    @app_commands.describe(member="Who to adjust", amount="XP to add; negative removes")
    async def xp_add(self, interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        current = await self.bot.levels.get_xp(interaction.guild_id, member.id)
        await self._change_xp(interaction, member, current + amount)

    @xp.command(name="set", description="Set a member's total XP")
    @app_commands.describe(member="Who to adjust", amount="Their new total XP")
    async def xp_set(
        self, interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 0]
    ) -> None:
        await self._change_xp(interaction, member, amount)

    @xp.command(name="reset", description="Reset a member's XP to zero")
    @app_commands.describe(member="Whose XP to reset")
    async def xp_reset(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self._change_xp(interaction, member, 0)


async def setup(bot: Warden) -> None:
    await bot.add_cog(Leveling(bot))
