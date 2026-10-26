"""Set up the DEV_GUILD_ID server for testing, without typing /config commands.

Creates (or reuses, matched by name) test channels and roles, then writes the
settings that point at them. Run it while the bot is stopped, because the
running bot caches settings in memory:

    python -m warden.devsetup

Warden needs Manage Channels and Manage Roles to create anything missing.
"""

from __future__ import annotations

import asyncio
import os
import sys

import discord
from dotenv import load_dotenv

# Import every module so all settings are registered before we write them.
from .cogs import automod, config, leveling, moderation, onboarding, perks  # noqa: F401
from .db import Database
from .levels import LevelStore
from .settings import SettingsService

CHANNELS = {"mod-log": "modlog.channel", "welcome": "onboarding.welcome_channel", "rules": None}
ROLES = {
    "Member": "onboarding.join_role",
    "Verified": "onboarding.verified_role",
    "Level 2": None,
    "Level 5": None,
}
PERKS = {2: "Level 2", 5: "Level 5"}
EXTRA_SETTINGS = {
    "automod.badwords": ["testword", "badphrase"],
}


async def setup_guild(guild: discord.Guild, settings: SettingsService, levels: LevelStore) -> None:
    channels: dict[str, discord.TextChannel] = {}
    for name, key in CHANNELS.items():
        channel = discord.utils.get(guild.text_channels, name=name)
        if channel is None:
            channel = await guild.create_text_channel(name, reason="Warden dev setup")
            print(f"  created #{name}")
        else:
            print(f"  found   #{name}")
        channels[name] = channel
        if key:
            await settings.set(guild.id, key, channel.id)

    roles: dict[str, discord.Role] = {}
    for name, key in ROLES.items():
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            role = await guild.create_role(name=name, reason="Warden dev setup")
            print(f"  created @{name}")
        else:
            print(f"  found   @{name}")
        if role >= guild.me.top_role:
            print(f"  ! @{name} is above Warden's role; move Warden's role higher")
        roles[name] = role
        if key:
            await settings.set(guild.id, key, role.id)

    for level, role_name in PERKS.items():
        await levels.add_reward(guild.id, level, roles[role_name].id)
    for key, value in EXTRA_SETTINGS.items():
        await settings.set(guild.id, key, value)

    print("\nSettings written:")
    values = await settings.get_all(guild.id)
    for key in sorted(values):
        print(f"  {key} = {values[key]!r}")
    print("\nPerks: " + ", ".join(f"level {lvl} → @{name}" for lvl, name in PERKS.items()))
    print(f"Next: start the bot, then run /onboarding rules channel:#{channels['rules'].name}")


async def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    guild_id = os.getenv("DEV_GUILD_ID", "").strip()
    if not token or not guild_id.isdigit():
        sys.exit("Set DISCORD_TOKEN and DEV_GUILD_ID in .env first.")

    db = Database(os.getenv("DATABASE_PATH", "warden.db"))
    await db.connect()
    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready() -> None:
        try:
            guild = client.get_guild(int(guild_id))
            if guild is None:
                print(f"Warden isn't in server {guild_id}. Invite it first.")
                return
            print(f"Setting up {guild.name}:")
            await setup_guild(guild, SettingsService(db), LevelStore(db))
        except discord.Forbidden:
            print(
                "\nDiscord refused: give Warden Manage Channels and Manage Roles, or create the "
                "channels/roles above yourself with those exact names and run this again."
            )
        finally:
            await client.close()

    try:
        await client.start(token)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
