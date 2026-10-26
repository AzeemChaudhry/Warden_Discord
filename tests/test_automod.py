"""Automod rules end to end, with stand-ins for the Discord objects they touch."""

from types import SimpleNamespace

import pytest

from warden.cogs.automod import Automod
from warden.filters import RateTracker
from warden.settings import SettingsService


class FakeMember(SimpleNamespace):
    def get_role(self, role_id):
        return role_id if role_id in self.role_ids else None


def make_message(content, *, user_id=1, mentions=(), manage_messages=False, role_ids=()):
    author = FakeMember(
        id=user_id,
        guild_permissions=SimpleNamespace(manage_messages=manage_messages),
        role_ids=set(role_ids),
        guild=SimpleNamespace(id=100),
    )
    return SimpleNamespace(
        content=content,
        author=author,
        guild=author.guild,
        raw_mentions=list(mentions),
        raw_role_mentions=[],
    )


@pytest.fixture
async def automod(db):
    bot = SimpleNamespace(settings=SettingsService(db))
    cog = Automod.__new__(Automod)  # skip GroupCog setup; only the rule logic is under test
    cog.bot = bot
    cog.settings = bot.settings
    cog.spam, cog.joins = RateTracker(), RateTracker()
    await bot.settings.set(100, "automod.badwords", ["darn"])
    return cog


async def test_clean_message_passes(automod):
    assert await automod.find_violation(make_message("hello there")) is None


async def test_bad_word(automod):
    assert await automod.find_violation(make_message("oh darn")) == "used a blocked word"


async def test_invite_blocked_by_default(automod):
    assert "invites" in await automod.find_violation(make_message("discord.gg/abc"))


async def test_mass_mentions(automod):
    msg = make_message("hi", mentions=range(10, 16))
    assert "pinged more than 5" in await automod.find_violation(msg)


async def test_spam(automod):
    results = [await automod.find_violation(make_message("hi")) for _ in range(6)]
    assert results[:5] == [None] * 5
    assert results[5] == "sent messages too quickly"


async def test_exemptions(automod):
    assert await automod.find_violation(make_message("darn", manage_messages=True)) is None
    await automod.bot.settings.set(100, "automod.exempt_role", 55)
    assert await automod.find_violation(make_message("darn", role_ids=[55])) is None


async def test_master_switch(automod):
    await automod.bot.settings.set(100, "automod.enabled", False)
    assert await automod.find_violation(make_message("darn")) is None


@pytest.mark.parametrize(
    "strikes, expected",
    [(1, None), (2, None), (3, "timeout"), (4, "timeout"), (5, "kick"), (7, "ban"), (9, "ban")],
)
async def test_escalation_thresholds(automod, monkeypatch, strikes, expected):
    from warden.cogs import automod as automod_module

    done = []

    async def fake_record(bot, guild, action, *args, **kwargs):
        done.append(("case", action.value))

    async def fake_notify(*args, **kwargs):
        return True

    monkeypatch.setattr(automod_module, "record_case", fake_record)
    monkeypatch.setattr(automod_module, "notify_member", fake_notify)
    monkeypatch.setattr(automod_module, "bot_can_act_on", lambda m: True)

    async def ban(member, **kw):
        done.append("ban")

    async def kick(**kw):
        done.append("kick")

    async def timeout(duration, **kw):
        done.append("timeout")

    me = SimpleNamespace(id=999, __str__=lambda self: "Warden")
    guild = SimpleNamespace(id=100, me=me, ban=ban)
    member = SimpleNamespace(
        id=1,
        guild=guild,
        kick=kick,
        timeout=timeout,
        guild_permissions=SimpleNamespace(administrator=False),
    )

    await automod._escalate(member, strikes)
    if expected is None:
        assert done == []
    else:
        assert done == [expected, ("case", expected)]
