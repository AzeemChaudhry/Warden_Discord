"""Per-guild settings.

Every module declares the settings it reads by calling ``register`` at import
time. Values are stored per guild in the ``guild_settings`` table and edited
through ``/config``; anything not explicitly set falls back to its default.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .db import Database


class SettingType(Enum):
    BOOL = "bool"
    INT = "int"
    STRING = "string"
    CHANNEL = "channel"
    ROLE = "role"
    LIST = "list"  # comma-separated strings, stored lowercased


@dataclass(frozen=True)
class Setting:
    key: str
    type: SettingType
    default: Any
    description: str
    min_value: int | None = None
    max_value: int | None = None


class SettingsError(ValueError):
    """Raised when a key is unknown or a value fails validation."""


REGISTRY: dict[str, Setting] = {}


def register(setting: Setting) -> Setting:
    # Overwrites on purpose: discord.py re-executes a cog's module each time the
    # extension is (re)loaded, so the same settings register again. Keys are
    # namespaced per module by ``setting_group``, which keeps them from colliding.
    REGISTRY[setting.key] = setting
    return setting


def setting_group(module: str):
    """Return a ``define`` helper that registers settings under ``module.``.

    >>> define = setting_group("leveling")
    >>> COOLDOWN = define("cooldown_seconds", SettingType.INT, 60, "...", min_value=0)
    """

    def define(
        key: str,
        type_: SettingType,
        default: Any,
        description: str,
        *,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> Setting:
        return register(Setting(f"{module}.{key}", type_, default, description, min_value, max_value))

    return define


def get_setting(key: str | Setting) -> Setting:
    if isinstance(key, Setting):
        return key
    try:
        return REGISTRY[key]
    except KeyError:
        raise SettingsError(f"Unknown setting `{key}`.") from None


_CLEAR_WORDS = {"none", "off", "clear", "unset"}
_TRUE_WORDS = {"true", "on", "yes", "enable", "enabled", "1"}
_FALSE_WORDS = {"false", "off", "no", "disable", "disabled", "0"}
_SNOWFLAKE = re.compile(r"^<?[#@]?&?(\d{15,25})>?$")


def parse_value(setting: Setting, raw: str) -> Any:
    """Convert user input from ``/config set`` into a stored value.

    Channel and role settings accept a mention or a raw ID and return the ID;
    callers are responsible for checking that it exists in the guild.
    """
    text = raw.strip()
    lowered = text.lower()

    if setting.type is SettingType.BOOL:
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        raise SettingsError(f"`{setting.key}` must be true or false.")

    if setting.type is SettingType.INT:
        try:
            value = int(text)
        except ValueError:
            raise SettingsError(f"`{setting.key}` must be a whole number.") from None
        if setting.min_value is not None and value < setting.min_value:
            raise SettingsError(f"`{setting.key}` must be at least {setting.min_value}.")
        if setting.max_value is not None and value > setting.max_value:
            raise SettingsError(f"`{setting.key}` must be at most {setting.max_value}.")
        return value

    if setting.type in (SettingType.CHANNEL, SettingType.ROLE):
        if lowered in _CLEAR_WORDS:
            return None
        match = _SNOWFLAKE.match(text)
        if not match:
            kind = "channel" if setting.type is SettingType.CHANNEL else "role"
            raise SettingsError(f"`{setting.key}` must be a {kind} mention or ID, or `none`.")
        return int(match.group(1))

    if setting.type is SettingType.LIST:
        if lowered in _CLEAR_WORDS:
            return []
        items = [item.strip().lower() for item in text.split(",")]
        return list(dict.fromkeys(item for item in items if item))

    if lowered in _CLEAR_WORDS:
        return None
    # Slash command options are single-line, so let people type \n.
    return text.replace("\\n", "\n")


def format_value(setting: Setting, value: Any) -> str:
    if value is None:
        return "*not set*"
    if setting.type is SettingType.CHANNEL:
        return f"<#{value}>"
    if setting.type is SettingType.ROLE:
        return f"<@&{value}>"
    if setting.type is SettingType.BOOL:
        return "on" if value else "off"
    if setting.type is SettingType.LIST:
        if not value:
            return "*empty*"
        shown = ", ".join(value)
        return f"`{shown[:150]}…` ({len(value)} items)" if len(shown) > 150 else f"`{shown}`"
    if isinstance(value, str) and len(value) > 150:
        return f"`{value[:150]}…`"
    return f"`{value}`"


BACKUP_FORMAT = 1
_MAX_TEXT = 2000


def validate_stored(setting: Setting, value: Any) -> Any:
    """Check a value read from a backup file and return it in stored form.

    Unlike ``parse_value`` this takes JSON values (bools, numbers, lists), not
    command input. Raises ``SettingsError`` if the value doesn't fit the setting.
    """
    kind = setting.type
    if value is None and kind in (SettingType.STRING, SettingType.CHANNEL, SettingType.ROLE):
        return None
    if kind is SettingType.BOOL and isinstance(value, bool):
        return value
    if kind is SettingType.INT and isinstance(value, int) and not isinstance(value, bool):
        if setting.min_value is not None and value < setting.min_value:
            raise SettingsError(f"below the minimum of {setting.min_value}")
        if setting.max_value is not None and value > setting.max_value:
            raise SettingsError(f"above the maximum of {setting.max_value}")
        return value
    if kind is SettingType.STRING and isinstance(value, str) and len(value) <= _MAX_TEXT:
        return value
    if kind in (SettingType.CHANNEL, SettingType.ROLE):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    if kind is SettingType.LIST and isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(dict.fromkeys(v.strip().lower() for v in value if v.strip()))
    raise SettingsError(f"expected {kind.value}, got {type(value).__name__}")


def _copy(value: Any) -> Any:
    # List defaults are shared objects; hand out copies so callers can't mutate them.
    return list(value) if isinstance(value, list) else value


class SettingsService:
    """Reads and writes guild settings, caching each guild after first load."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: dict[int, dict[str, Any]] = {}

    async def _load(self, guild_id: int) -> dict[str, Any]:
        cached = self._cache.get(guild_id)
        if cached is not None:
            return cached
        rows = await self.db.fetchall("SELECT key, value FROM guild_settings WHERE guild_id = ?", (guild_id,))
        stored = {row["key"]: json.loads(row["value"]) for row in rows}
        self._cache[guild_id] = stored
        return stored

    async def get(self, guild_id: int, key: str | Setting) -> Any:
        setting = get_setting(key)
        stored = await self._load(guild_id)
        return _copy(stored.get(setting.key, setting.default))

    async def get_all(self, guild_id: int) -> dict[str, Any]:
        stored = await self._load(guild_id)
        return {key: _copy(stored.get(key, s.default)) for key, s in REGISTRY.items()}

    async def overrides(self, guild_id: int) -> dict[str, Any]:
        """Only the settings this guild changed from their defaults."""
        stored = await self._load(guild_id)
        return {key: _copy(value) for key, value in stored.items() if key in REGISTRY}

    async def set(self, guild_id: int, key: str | Setting, value: Any) -> None:
        key = get_setting(key).key
        await self.db.execute(
            "INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, key) DO UPDATE SET value = excluded.value",
            (guild_id, key, json.dumps(value)),
        )
        (await self._load(guild_id))[key] = value

    async def reset(self, guild_id: int, key: str | Setting) -> None:
        key = get_setting(key).key
        await self.db.execute("DELETE FROM guild_settings WHERE guild_id = ? AND key = ?", (guild_id, key))
        (await self._load(guild_id)).pop(key, None)
