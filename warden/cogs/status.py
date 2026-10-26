"""/status: a quick health check for admins."""

from __future__ import annotations

import os
import time
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..durations import format_duration

if TYPE_CHECKING:
    from ..bot import Warden


def _version() -> str:
    try:
        return version("warden")
    except PackageNotFoundError:
        return "dev"


def _file_size(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return "n/a"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class Status(commands.Cog):
    def __init__(self, bot: Warden) -> None:
        self.bot = bot
        self.started = time.monotonic()

    @app_commands.command(description="Show Warden's health and this server's numbers")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        bot, guild_id = self.bot, interaction.guild_id
        uptime = timedelta(seconds=int(time.monotonic() - self.started))
        cases = await bot.db.fetchone("SELECT COUNT(*) FROM cases WHERE guild_id = ?", (guild_id,))
        ranked = await bot.levels.count(guild_id)
        changed = len(await bot.settings.overrides(guild_id))

        embed = discord.Embed(title="Warden status", colour=discord.Colour.green())
        embed.add_field(name="Version", value=_version())
        embed.add_field(name="Uptime", value=format_duration(uptime))
        embed.add_field(name="Latency", value=f"{bot.latency * 1000:.0f} ms")
        embed.add_field(name="Servers", value=str(len(bot.guilds)))
        embed.add_field(name="Database", value=_file_size(bot.config.database_path))
        embed.add_field(name="Cogs loaded", value=str(len(bot.cogs)))
        embed.add_field(
            name="This server",
            value=f"{cases[0]} case(s) · {ranked} member(s) with XP · {changed} setting(s) changed",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: Warden) -> None:
    await bot.add_cog(Status(bot))
