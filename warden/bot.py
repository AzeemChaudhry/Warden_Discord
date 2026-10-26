from __future__ import annotations

import logging
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from .db import Database
from .levels import LevelStore
from .modlog import CaseStore
from .settings import SettingsService

log = logging.getLogger(__name__)

EXTENSIONS = (
    "warden.cogs.config",
    "warden.cogs.moderation",
    "warden.cogs.automod",
    "warden.cogs.onboarding",
    "warden.cogs.leveling",
    "warden.cogs.perks",
    "warden.cogs.status",
)


@dataclass(frozen=True)
class BotConfig:
    token: str
    database_path: str
    dev_guild_id: int | None


class WardenTree(app_commands.CommandTree):
    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.BotMissingPermissions):
            perms = ", ".join(p.replace("_", " ") for p in error.missing_permissions)
            message = f"I'm missing the permissions I need for this: {perms}."
        elif isinstance(error, app_commands.MissingPermissions):
            message = "You don't have permission to use this command."
        elif isinstance(error, app_commands.NoPrivateMessage):
            message = "This command only works in a server."
        elif isinstance(error, app_commands.CheckFailure):
            message = str(error) or "You can't use this command here."
        elif isinstance(error, app_commands.CommandInvokeError) and isinstance(
            error.original, discord.Forbidden
        ):
            message = (
                "Discord refused that action. Check that my role is above the target's "
                "and that I have the needed permission."
            )
        else:
            name = interaction.command.qualified_name if interaction.command else "?"
            log.error("Unhandled error in /%s", name, exc_info=error)
            message = "Something went wrong running that command."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class Warden(commands.Bot):
    def __init__(self, config: BotConfig) -> None:
        # Both are privileged: switch them on under Bot -> Privileged Gateway
        # Intents in the developer portal too. members: join events and the
        # member cache (onboarding, raid mode). message_content: automod.
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            tree_cls=WardenTree,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )
        self.config = config
        self.db = Database(config.database_path)
        self.settings = SettingsService(self.db)
        self.cases = CaseStore(self.db)
        self.levels = LevelStore(self.db)

    async def setup_hook(self) -> None:
        await self.db.connect()
        for ext in EXTENSIONS:
            await self.load_extension(ext)

        if self.config.dev_guild_id:
            guild = discord.Object(id=self.config.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to dev guild %s", len(synced), self.config.dev_guild_id)
            # Remove any global copies from an earlier global sync, otherwise
            # every command shows up twice in the dev guild.
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s) in %d guilds", self.user, self.user.id, len(self.guilds))

    async def close(self) -> None:
        await super().close()
        await self.db.close()
