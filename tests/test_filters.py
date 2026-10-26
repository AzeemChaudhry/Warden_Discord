import pytest

from warden.filters import RateTracker, count_mentions, find_bad_word, find_blocked_link


def test_bad_words_match_whole_words_only():
    words = ["darn", "heck off"]
    assert find_bad_word("well DARN it", words) == "darn"
    assert find_bad_word("just heck off already", words) == "heck off"
    assert find_bad_word("darned socks", words) is None
    assert find_bad_word("anything", []) is None


@pytest.mark.parametrize(
    "content, expected",
    [
        ("see https://evil.example/path", "links to evil.example aren't allowed"),
        ("www.evil.example", "links to evil.example aren't allowed"),
        ("https://media.tenor.com/x.gif", None),
        ("https://TENOR.com", None),
        ("no links here, e.g. file.py", None),
        ("join discord.gg/abc123", "server invites aren't allowed"),
    ],
)
def test_links(content, expected):
    assert (
        find_blocked_link(content, block_links=True, block_invites=True, allowlist=["tenor.com"]) == expected
    )


def test_invites_without_link_filter():
    kwargs = dict(block_links=False, allowlist=[])
    assert find_blocked_link("https://example.com", block_invites=True, **kwargs) is None
    assert find_blocked_link("discord.com/invite/xyz", block_invites=True, **kwargs)
    assert find_blocked_link("discord.gg/xyz", block_invites=False, **kwargs) is None


def test_allowlist_does_not_match_lookalikes():
    assert find_blocked_link(
        "https://nottenor.com", block_links=True, block_invites=False, allowlist=["tenor.com"]
    )


def test_count_mentions():
    assert count_mentions("hi @everyone", [1, 1, 2], [9]) == 4


def test_rate_tracker_triggers_once_per_burst():
    tracker = RateTracker()
    hits = [tracker.hit("u", t, limit=3, window=5) for t in (0, 1, 2, 2.5, 3)]
    assert hits == [False, False, True, False, False]
    assert tracker.hit("u", 20, 3, 5) is False  # old events expired


def test_rate_tracker_prune():
    tracker = RateTracker()
    tracker.hit("a", 0, 5, 5)
    tracker.hit("b", 100, 5, 5)
    tracker.prune(now=101, window=10)
    assert set(tracker._events) == {"b"}
