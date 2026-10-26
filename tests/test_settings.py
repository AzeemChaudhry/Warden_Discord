import json

import pytest

from warden import modlog  # noqa: F401  registers modlog.channel
from warden.cogs import moderation  # noqa: F401  registers moderation.*
from warden.settings import (
    REGISTRY,
    Setting,
    SettingsError,
    SettingsService,
    SettingType,
    get_setting,
    parse_value,
    validate_stored,
)

FLAG = Setting("test.flag", SettingType.BOOL, False, "")
LIMIT = Setting("test.limit", SettingType.INT, 5, "", min_value=1, max_value=10)
CHANNEL = Setting("test.channel", SettingType.CHANNEL, None, "")


@pytest.mark.parametrize("raw, expected", [("on", True), ("TRUE", True), ("no", False), ("0", False)])
def test_parse_bool(raw, expected):
    assert parse_value(FLAG, raw) is expected


def test_parse_bool_rejects_garbage():
    with pytest.raises(SettingsError):
        parse_value(FLAG, "maybe")


def test_parse_int_bounds():
    assert parse_value(LIMIT, " 7 ") == 7
    with pytest.raises(SettingsError):
        parse_value(LIMIT, "0")
    with pytest.raises(SettingsError):
        parse_value(LIMIT, "11")


@pytest.mark.parametrize("raw", ["<#123456789012345678>", "123456789012345678"])
def test_parse_channel(raw):
    assert parse_value(CHANNEL, raw) == 123456789012345678


def test_parse_role_mention():
    role = Setting("test.role", SettingType.ROLE, None, "")
    assert parse_value(role, "<@&123456789012345678>") == 123456789012345678


def test_parse_channel_clear_and_invalid():
    assert parse_value(CHANNEL, "none") is None
    with pytest.raises(SettingsError):
        parse_value(CHANNEL, "#general")


async def test_service_defaults_set_reset(db):
    service = SettingsService(db)
    key = "modlog.channel"
    assert await service.get(1, key) is None

    await service.set(1, key, 42)
    assert await service.get(1, key) == 42
    assert await service.get(2, key) is None  # per guild

    # A fresh service (no cache) reads the stored value back from the DB.
    assert await SettingsService(db).get(1, key) == 42

    await service.reset(1, key)
    assert await service.get(1, key) is None
    assert await SettingsService(db).get(1, key) is None


async def test_service_rejects_unknown_key(db):
    with pytest.raises(SettingsError):
        await SettingsService(db).set(1, "nope.missing", 1)


async def test_get_all_covers_registry(db):
    values = await SettingsService(db).get_all(1)
    assert set(values) == set(REGISTRY)


def test_parse_list():
    words = Setting("test.words", SettingType.LIST, [], "")
    assert parse_value(words, " Foo, bar ,,foo ") == ["foo", "bar"]
    assert parse_value(words, "none") == []


def test_string_newlines():
    text = Setting("test.text", SettingType.STRING, "", "")
    assert parse_value(text, r"line one\nline two") == "line one\nline two"


def test_reregistering_replaces():
    from warden.settings import register

    first = register(Setting("test.reload", SettingType.INT, 1, "old"))
    second = register(Setting("test.reload", SettingType.INT, 2, "new"))
    assert REGISTRY["test.reload"] is second and first is not second
    del REGISTRY["test.reload"]


@pytest.mark.parametrize(
    "setting, raw, expected",
    [
        (FLAG, True, True),
        (LIMIT, 7, 7),
        (CHANNEL, 123456789012345678, 123456789012345678),
        (CHANNEL, "123456789012345678", 123456789012345678),
        (CHANNEL, None, None),
        (Setting("test.words", SettingType.LIST, [], ""), [" Foo", "bar", "foo", ""], ["foo", "bar"]),
    ],
)
def test_validate_stored_accepts(setting, raw, expected):
    assert validate_stored(setting, raw) == expected


@pytest.mark.parametrize(
    "setting, raw",
    [
        (FLAG, "yes"),  # backups hold real JSON booleans
        (LIMIT, True),  # bool is an int subclass; don't let it through
        (LIMIT, 11),
        (CHANNEL, "general"),
        (Setting("test.words", SettingType.LIST, [], ""), "a, b"),
    ],
)
def test_validate_stored_rejects(setting, raw):
    with pytest.raises(SettingsError):
        validate_stored(setting, raw)


async def test_overrides_and_backup_round_trip(db):
    source = SettingsService(db)
    assert await source.overrides(1) == {}
    await source.set(1, "modlog.channel", 555555555555555555)
    await source.set(1, "moderation.require_reason", True)

    overrides = await source.overrides(1)
    assert overrides == {"modlog.channel": 555555555555555555, "moderation.require_reason": True}

    # Same path /config import takes: JSON text in, validated values out.
    restored = json.loads(json.dumps(overrides))
    target = SettingsService(db)
    for key, raw in restored.items():
        await target.set(2, key, validate_stored(get_setting(key), raw))
    assert await target.overrides(2) == overrides
