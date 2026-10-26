from __future__ import annotations

from itertools import groupby
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..settings import REGISTRY, SettingsError, SettingType, format_value, get_setting, parse_value

if TYPE_CHECKING:
    from ..bot import Warden


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class Config(
    commands.GroupCog,
    group_name="config",
    group_description="View and change Warden's settings for this server",
):
    def __init__(self, bot: Warden) -> None:
        self.bot = bot
        super().__init__()

    async def key_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        current = current.lower()
        return [app_commands.Choice(name=key, value=key) for key in sorted(REGISTRY) if current in key][:25]

    async def module_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        modules = sorted({key.split(".", 1)[0] for key in REGISTRY})
        return [app_commands.Choice(name=m, value=m) for m in modules if current.lower() in m][:25]

    @app_commands.command(name="view", description="Show settings and their current values")
    @app_commands.describe(module="Only show one module's settings, e.g. automod")
    @app_commands.autocomplete(module=module_autocomplete)
    async def view(self, interaction: discord.Interaction, module: str | None = None) -> None:
        values = await self.bot.settings.get_all(interaction.guild_id)
        keys = sorted(k for k in REGISTRY if module is None or k.split(".", 1)[0] == module)
        if not keys:
            await interaction.response.send_message(f"There's no `{module}` module.", ephemeral=True)
            return

        # Discord caps fields at 1024 chars, 25 fields per embed, and 6000 chars
        # across all embeds in one message, so each embed is its own message.
        embeds = [discord.Embed(title="Warden settings", colour=discord.Colour.blurple())]
        size = 0
        for name, group in groupby(keys, key=lambda k: k.split(".", 1)[0]):
            chunks, chunk = [], ""
            for key in group:
                line = (
                    f"`{key}`: {format_value(REGISTRY[key], values[key])}\n-# {REGISTRY[key].description}\n"
                )
                if len(chunk) + len(line) > 1024:
                    chunks.append(chunk)
                    chunk = ""
                chunk += line
            chunks.append(chunk)
            for i, text in enumerate(chunks):
                title = name.title() if i == 0 else f"{name.title()} (cont.)"
                if size + len(text) + len(title) > 5500 or len(embeds[-1].fields) == 25:
                    embeds.append(discord.Embed(colour=discord.Colour.blurple()))
                    size = 0
                embeds[-1].add_field(name=title, value=text, inline=False)
                size += len(text) + len(title)
        embeds[-1].set_footer(text="Change one with /config set, restore its default with /config reset")
        await interaction.response.send_message(embed=embeds[0], ephemeral=True)
        for embed in embeds[1:]:
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="set", description="Change a setting")
    @app_commands.describe(
        key="The setting to change",
        value="New value: true/false, a number, a #channel, a @role, or none",
    )
    @app_commands.autocomplete(key=key_autocomplete)
    async def set_(self, interaction: discord.Interaction, key: str, value: str) -> None:
        guild = interaction.guild
        try:
            setting = get_setting(key)
            parsed = parse_value(setting, value)
        except SettingsError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        note = ""
        if parsed is not None and setting.type is SettingType.CHANNEL:
            channel = guild.get_channel(parsed)
            if not isinstance(channel, discord.abc.Messageable):
                await interaction.response.send_message(
                    "I can't find a text channel with that ID here.", ephemeral=True
                )
                return
            perms = channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                note = f"\n:warning: I need View Channel, Send Messages and Embed Links in {channel.mention}."
        elif parsed is not None and setting.type is SettingType.ROLE:
            if guild.get_role(parsed) is None:
                await interaction.response.send_message(
                    "I can't find a role with that ID here.", ephemeral=True
                )
                return

        await self.bot.settings.set(guild.id, key, parsed)
        await interaction.response.send_message(
            f"`{key}` is now {format_value(setting, parsed)}.{note}", ephemeral=True
        )

    @app_commands.command(name="reset", description="Restore a setting to its default")
    @app_commands.describe(key="The setting to reset")
    @app_commands.autocomplete(key=key_autocomplete)
    async def reset(self, interaction: discord.Interaction, key: str) -> None:
        try:
            setting = get_setting(key)
        except SettingsError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self.bot.settings.reset(interaction.guild_id, key)
        await interaction.response.send_message(
            f"`{key}` is back to its default: {format_value(setting, setting.default)}.", ephemeral=True
        )


async def setup(bot: Warden) -> None:
    await bot.add_cog(Config(bot))
