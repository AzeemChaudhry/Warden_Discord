from __future__ import annotations

import io
import json
from itertools import groupby
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..settings import (
    BACKUP_FORMAT,
    REGISTRY,
    SettingsError,
    SettingType,
    format_value,
    get_setting,
    parse_value,
    validate_stored,
)

if TYPE_CHECKING:
    from ..bot import Warden

MAX_BACKUP_BYTES = 256 * 1024


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

    @app_commands.command(name="export", description="Download this server's settings as a backup file")
    async def export(self, interaction: discord.Interaction) -> None:
        overrides = await self.bot.settings.overrides(interaction.guild_id)
        payload = {
            "format": BACKUP_FORMAT,
            "guild_id": str(interaction.guild_id),
            "exported_at": discord.utils.utcnow().isoformat(timespec="seconds"),
            "settings": dict(sorted(overrides.items())),
        }
        data = io.BytesIO(json.dumps(payload, indent=2).encode())
        await interaction.response.send_message(
            f"{len(overrides)} changed setting(s). Defaults aren't included. Restore with `/config import`.",
            file=discord.File(data, filename=f"warden-settings-{interaction.guild_id}.json"),
            ephemeral=True,
        )

    @app_commands.command(name="import", description="Restore settings from a /config export file")
    @app_commands.describe(file="A file made by /config export")
    async def import_(self, interaction: discord.Interaction, file: discord.Attachment) -> None:
        if file.size > MAX_BACKUP_BYTES:
            await interaction.response.send_message("That file is too large to be a backup.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            payload = json.loads(await file.read())
            entries = payload["settings"]
            if payload.get("format") != BACKUP_FORMAT or not isinstance(entries, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            await interaction.followup.send("That isn't a Warden settings backup.", ephemeral=True)
            return

        guild = interaction.guild
        applied, skipped = 0, []
        for key, raw in entries.items():
            try:
                setting = get_setting(key)
                value = validate_stored(setting, raw)
            except SettingsError as exc:
                skipped.append(f"`{key}`: {exc}")
                continue
            # Channel and role IDs only exist in the server they came from.
            if value is not None and setting.type is SettingType.CHANNEL and guild.get_channel(value) is None:
                skipped.append(f"`{key}`: channel not in this server")
                continue
            if value is not None and setting.type is SettingType.ROLE and guild.get_role(value) is None:
                skipped.append(f"`{key}`: role not in this server")
                continue
            await self.bot.settings.set(guild.id, setting, value)
            applied += 1

        message = f"Restored {applied} setting(s)."
        if skipped:
            shown = "\n".join(f"- {line}" for line in skipped[:15])
            more = f"\n…and {len(skipped) - 15} more" if len(skipped) > 15 else ""
            message += f" Skipped {len(skipped)}:\n{shown}{more}"
        await interaction.followup.send(message[:2000], ephemeral=True)


async def setup(bot: Warden) -> None:
    await bot.add_cog(Config(bot))
