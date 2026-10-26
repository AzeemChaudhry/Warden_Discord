"""Load every cog offline and check the slash commands Discord would receive.

Catches mistakes that otherwise only show up as a failed sync at startup.
"""

import re

import pytest

from warden.bot import EXTENSIONS, BotConfig, Warden
from warden.settings import REGISTRY

NAME = re.compile(r"^[-_\w]{1,32}$")
# Commands anyone may use; everything else must be locked behind a permission.
PUBLIC = {"rank", "leaderboard"}


@pytest.fixture
async def payloads():
    bot = Warden(BotConfig(token="unused", database_path=":memory:", dev_guild_id=None))
    await bot.db.connect()
    for ext in EXTENSIONS:
        await bot.load_extension(ext)
    yield {cmd.name: cmd.to_dict(bot.tree) for cmd in bot.tree.get_commands()}
    await bot.db.close()


def walk(command, path=""):
    path = f"{path} {command['name']}".strip()
    yield path, command
    for option in command.get("options", []):
        if option["type"] in (1, 2):  # subcommand, subcommand group
            yield from walk(option, path)


def test_expected_commands_exist(payloads):
    assert {"config", "warn", "timeout", "kick", "ban", "automod", "onboarding", "rank", "perks"} <= set(
        payloads
    )


def test_payloads_follow_discord_limits(payloads):
    assert len(payloads) <= 100
    for top in payloads.values():
        for path, command in walk(top):
            assert NAME.match(command["name"]) and command["name"] == command["name"].lower(), path
            assert 1 <= len(command["description"]) <= 100, path
            options = command.get("options", [])
            assert len(options) <= 25, path
            leaf_options = [o for o in options if o["type"] not in (1, 2)]
            required_after_optional = False
            seen_optional = False
            for option in leaf_options:
                assert NAME.match(option["name"]), f"{path} {option['name']}"
                assert 1 <= len(option["description"]) <= 100, f"{path} {option['name']}"
                if not option.get("required"):
                    seen_optional = True
                elif seen_optional:
                    required_after_optional = True
            assert not required_after_optional, f"{path}: required option after optional"


def test_staff_commands_are_permission_gated(payloads):
    for name, payload in payloads.items():
        if name in PUBLIC:
            continue
        assert payload.get("default_member_permissions"), f"/{name} is open to everyone"


def test_every_command_is_guild_only(payloads):
    for name, payload in payloads.items():
        assert payload.get("contexts") == [0] or payload.get("dm_permission") is False, name


def test_settings_are_well_formed(payloads):  # payloads fixture imports every module
    for key, setting in REGISTRY.items():
        module, _, name = key.partition(".")
        assert module and name and key == key.lower(), key
        assert setting.description, key
        assert len(key) <= 100, key  # autocomplete choice limit
