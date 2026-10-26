"""Automod detection rules, kept free of Discord objects so they're easy to test."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Hashable, Sequence
from functools import lru_cache

_URL = re.compile(r"(?:https?://|www\.)([^\s/<>?#]+)", re.IGNORECASE)
_INVITE = re.compile(r"(?:discord(?:app)?\.com/invite|discord\.gg)/[\w-]+", re.IGNORECASE)
_EVERYONE = re.compile(r"@(?:everyone|here)\b")


@lru_cache(maxsize=256)
def _word_pattern(words: tuple[str, ...]) -> re.Pattern[str] | None:
    if not words:
        return None
    alternatives = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    # Lookarounds instead of \b so entries that start or end with symbols still match.
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def find_bad_word(content: str, words: Sequence[str]) -> str | None:
    """Return the first blocked word or phrase found in ``content``."""
    pattern = _word_pattern(tuple(words))
    if pattern is None:
        return None
    match = pattern.search(content)
    return match.group(0).lower() if match else None


def _host(raw: str) -> str:
    host = raw.lower().rsplit("@", 1)[-1].split(":", 1)[0]
    return host.removeprefix("www.").rstrip(".")


def _allowed(host: str, allowlist: Sequence[str]) -> bool:
    for domain in allowlist:
        domain = domain.lower().removeprefix("www.")
        if host == domain or host.endswith("." + domain):
            return True
    return False


def find_blocked_link(
    content: str, *, block_links: bool, block_invites: bool, allowlist: Sequence[str]
) -> str | None:
    """Return a short reason if ``content`` has a link it shouldn't, else None."""
    if block_invites and _INVITE.search(content):
        return "server invites aren't allowed"
    if block_links:
        for match in _URL.finditer(content):
            host = _host(match.group(1))
            if host.startswith("discord.gg") and not block_invites:
                continue
            if not _allowed(host, allowlist):
                return f"links to {host} aren't allowed"
    return None


def count_mentions(content: str, user_ids: Sequence[int], role_ids: Sequence[int]) -> int:
    """Distinct users and roles pinged, plus @everyone/@here attempts."""
    return len(set(user_ids)) + len(set(role_ids)) + len(_EVERYONE.findall(content))


class RateTracker:
    """Detects ``limit`` events within ``window`` seconds for a key.

    When the limit is hit the key's history is cleared, so one burst triggers
    once rather than on every following event.
    """

    def __init__(self) -> None:
        self._events: dict[Hashable, deque[float]] = {}

    def hit(self, key: Hashable, now: float, limit: int, window: float) -> bool:
        events = self._events.setdefault(key, deque())
        events.append(now)
        while events and now - events[0] > window:
            events.popleft()
        if len(events) >= limit:
            del self._events[key]
            return True
        return False

    def prune(self, now: float, window: float) -> None:
        """Drop keys with no events inside ``window``, to bound memory."""
        for key in [k for k, ev in self._events.items() if not ev or now - ev[-1] > window]:
            del self._events[key]
