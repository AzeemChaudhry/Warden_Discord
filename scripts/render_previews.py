"""Render the README illustrations in docs/assets/ as Discord-style SVGs.

    uv run python scripts/render_previews.py

The text mirrors what Warden actually sends (case embeds, automod notices,
welcome flow, rank cards), drawn in Discord's dark theme. Swap any of them for
real screenshots whenever you like; the README only references the files.

Inline markup in text: **bold**, `code`, {@mention}, {#channel}, {!warning}, {~struck}.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "assets"

FONT = "'gg sans','Noto Sans','Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "Consolas,'Liberation Mono',Menlo,monospace"
W = 760
CONTENT_X = 76
EMBED_W = 560

BG = "#313338"
HEADER_BG = "#2b2d31"
BORDER = "#1f2023"
TEXT = "#dbdee1"
WHITE = "#f2f3f5"
MUTED = "#949ba4"
EMBED_BG = "#2b2d31"
MENTION = "#c9cdfb"
LINK = "#00a8fc"
WARN = "#f0b232"

COLOURS = {
    "yellow": "#fee75c",
    "orange": "#e67e22",
    "red": "#ed4245",
    "green": "#57f287",
    "blurple": "#5865f2",
    "gold": "#f1c40f",
    "purple": "#9b59b6",
    "teal": "#1abc9c",
    "pink": "#eb459e",
}

_TOKEN = re.compile(r"(\*\*.+?\*\*|`.+?`|\{[@#!~][^}]+\})")


def rich(text: str, x: float, y: float, size: int = 15, colour: str = TEXT, weight: int = 400) -> str:
    """One line of text with inline markup turned into styled <tspan>s."""
    spans = []
    for part in _TOKEN.split(text):
        if not part:
            continue
        if part.startswith("**"):
            spans.append(f'<tspan font-weight="700" fill="{WHITE}">{escape(part[2:-2])}</tspan>')
        elif part.startswith("`"):
            spans.append(f'<tspan font-family="{MONO}" font-size="{size - 1}">{escape(part[1:-1])}</tspan>')
        elif part.startswith("{@"):
            spans.append(f'<tspan fill="{MENTION}" font-weight="500">@{escape(part[2:-1])}</tspan>')
        elif part.startswith("{#"):
            spans.append(f'<tspan fill="{MENTION}" font-weight="500">#{escape(part[2:-1])}</tspan>')
        elif part.startswith("{~"):
            spans.append(f'<tspan fill="{MUTED}" text-decoration="line-through">{escape(part[2:-1])}</tspan>')
        elif part.startswith("{!"):
            spans.append(f'<tspan fill="{WARN}">{escape(part[2:-1])}</tspan>')
        else:
            spans.append(escape(part))
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{colour}" font-weight="{weight}" '
        f'xml:space="preserve">{"".join(spans)}</text>'
    )


@dataclass
class Field:
    name: str
    value: list[str]
    inline: bool = True


@dataclass
class Scene:
    parts: list[str] = field(default_factory=list)
    y: float = 0

    def header(self, name: str, kind: str = "#") -> Scene:
        top = self.y
        if top:
            self.parts.append(f'<rect x="0" y="{top}" width="{W}" height="10" fill="{BORDER}"/>')
            top += 10
        self.parts += [
            f'<rect x="0" y="{top}" width="{W}" height="46" fill="{HEADER_BG}"/>',
            f'<rect x="0" y="{top + 46}" width="{W}" height="1" fill="{BORDER}"/>',
            f'<text x="20" y="{top + 30}" font-size="22" fill="{MUTED}">{escape(kind)}</text>',
            f'<text x="44" y="{top + 29}" font-size="16" font-weight="700" fill="{WHITE}">{escape(name)}</text>',
        ]
        self.y = top + 50
        return self

    def used(self, user: str, command: str, colour: str = "#e8a2c8") -> Scene:
        y = self.y + 26
        self.parts += [
            f'<path d="M 38 {y + 10} v -6 q 0 -6 6 -6 h 22" stroke="#4e5058" stroke-width="2" fill="none"/>',
            f'<circle cx="78" cy="{y - 2}" r="8" fill="{colour}"/>',
            f'<text x="92" y="{y + 3}" font-size="13" fill="{MUTED}"><tspan fill="{colour}" font-weight="600">'
            f'{escape(user)}</tspan> used <tspan fill="{LINK}">/{escape(command)}</tspan></text>',
        ]
        self.y = y + 2
        return self

    def message(
        self,
        author: str,
        colour: str,
        lines: list[str] = (),
        *,
        bot: bool = False,
        time: str = "Today at 21:04",
        compact_top: bool = False,
    ) -> Scene:
        top = self.y + (2 if compact_top else 16)
        name_w = len(author) * 10 + 6
        self.parts += [
            f'<circle cx="40" cy="{top + 20}" r="20" fill="{colour}"/>',
            f'<text x="40" y="{top + 27}" font-size="18" font-weight="700" fill="#fff" '
            f'text-anchor="middle">{escape(author[0].upper())}</text>',
            f'<text x="{CONTENT_X}" y="{top + 15}" font-size="16" font-weight="600" fill="{colour if bot else WHITE}">'
            f"{escape(author)}</text>",
        ]
        x = CONTENT_X + name_w
        if bot:
            self.parts += [
                f'<rect x="{x + 2}" y="{top + 2}" width="32" height="16" rx="3" fill="{COLOURS["blurple"]}"/>',
                f'<text x="{x + 18}" y="{top + 14}" font-size="10" font-weight="700" fill="#fff" '
                f'text-anchor="middle">APP</text>',
            ]
            x += 40
        self.parts.append(f'<text x="{x + 6}" y="{top + 15}" font-size="12" fill="{MUTED}">{time}</text>')
        y = top + 22
        for line in lines:
            self.parts.append(rich(line, CONTENT_X, y + 16))
            y += 22
        self.y = y
        return self

    def text(self, lines: list[str], size: int = 15, colour: str = TEXT) -> Scene:
        y = self.y
        for line in lines:
            self.parts.append(rich(line, CONTENT_X, y + 16, size=size, colour=colour))
            y += size + 7
        self.y = y
        return self

    def note(self, text: str) -> Scene:
        self.parts.append(rich(text, CONTENT_X, self.y + 17, size=12, colour=MUTED))
        self.y += 22
        return self

    def ephemeral(self) -> Scene:
        return self.note("Only you can see this  ·  Dismiss message")

    def embed(
        self,
        colour: str,
        *,
        title: str | None = None,
        description: list[str] = (),
        fields: list[Field] = (),
        footer: str | None = None,
        thumbnail: tuple[str, str] | None = None,
        progress: tuple[float, str] | None = None,
    ) -> Scene:
        x, start = CONTENT_X, self.y + 8
        inner: list[str] = []
        y = start + 12
        text_w = EMBED_W - (96 if thumbnail else 32)
        if title:
            inner.append(rich(title, x + 16, y + 14, size=15, colour=WHITE, weight=700))
            y += 26
        for line in description:
            inner.append(rich(line, x + 16, y + 14, size=14))
            y += 21
        if description:
            y += 4

        row: list[Field] = []

        def flush_row() -> None:
            nonlocal y
            if not row:
                return
            col_w = text_w / 3
            height = 0
            for i, f in enumerate(row):
                fx = x + 16 + i * col_w
                inner.append(rich(f.name, fx, y + 14, size=13, colour=WHITE, weight=700))
                for j, v in enumerate(f.value):
                    inner.append(rich(v, fx, y + 35 + j * 20, size=14))
                height = max(height, 26 + len(f.value) * 20)
            y += height + 6
            row.clear()

        for f in fields:
            if f.inline:
                row.append(f)
                if len(row) == 3:
                    flush_row()
            else:
                flush_row()
                inner.append(rich(f.name, x + 16, y + 14, size=13, colour=WHITE, weight=700))
                for j, v in enumerate(f.value):
                    inner.append(rich(v, x + 16, y + 35 + j * 20, size=14))
                y += 26 + len(f.value) * 20 + 6
        flush_row()

        if progress:
            fraction, label = progress
            bar_w = 220
            inner += [
                f'<rect x="{x + 16}" y="{y + 2}" width="{bar_w}" height="12" rx="6" fill="#1e1f22"/>',
                f'<rect x="{x + 16}" y="{y + 2}" width="{bar_w * fraction:.0f}" height="12" rx="6" fill="{colour}"/>',
                rich(label, x + 26 + bar_w, y + 13, size=13, colour=MUTED),
            ]
            y += 24

        if footer:
            inner.append(rich(footer, x + 16, y + 12, size=12, colour=MUTED))
            y += 20
        height = y - start + 10
        if thumbnail:
            height = max(height, 100)
            thumb_colour, initial = thumbnail
            cx, cy = x + EMBED_W - 48, start + 44
            inner += [
                f'<circle cx="{cx}" cy="{cy}" r="32" fill="{thumb_colour}"/>',
                f'<text x="{cx}" y="{cy + 10}" font-size="28" font-weight="700" fill="#fff" '
                f'text-anchor="middle">{escape(initial)}</text>',
            ]
        self.parts += [
            f'<rect x="{x}" y="{start}" width="{EMBED_W}" height="{height}" rx="4" fill="{EMBED_BG}"/>',
            f'<rect x="{x}" y="{start}" width="4" height="{height}" rx="2" fill="{colour}"/>',
            *inner,
        ]
        self.y = start + height
        return self

    def buttons(self, *labels: tuple[str, str]) -> Scene:
        x, y = CONTENT_X, self.y + 8
        for label, colour in labels:
            w = len(label) * 8 + 32
            self.parts += [
                f'<rect x="{x}" y="{y}" width="{w}" height="32" rx="4" fill="{colour}"/>',
                f'<text x="{x + w / 2}" y="{y + 21}" font-size="14" font-weight="600" fill="#fff" '
                f'text-anchor="middle">{escape(label)}</text>',
            ]
            x += w + 8
        self.y = y + 32
        return self

    def roles(self, title: str, roles: list[tuple[str, str]], highlight: set[str] = frozenset()) -> Scene:
        x, y = CONTENT_X, self.y + 12
        self.parts.append(rich(title, x, y + 12, size=12, colour=MUTED, weight=700))
        y += 22
        for name, colour in roles:
            w = len(name) * 7.5 + 34
            stroke = f' stroke="{COLOURS["green"]}" stroke-width="2"' if name in highlight else ""
            self.parts += [
                f'<rect x="{x}" y="{y}" width="{w}" height="24" rx="5" fill="#232428"{stroke}/>',
                f'<circle cx="{x + 13}" cy="{y + 12}" r="5" fill="{colour}"/>',
                f'<text x="{x + 24}" y="{y + 17}" font-size="13" fill="{TEXT}">{escape(name)}</text>',
            ]
            x += w + 6
        self.y = y + 24
        return self

    def space(self, px: float = 10) -> Scene:
        self.y += px
        return self

    def save(self, name: str, label: str) -> None:
        height = self.y + 20
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height:.0f}" '
            f'viewBox="0 0 {W} {height:.0f}" font-family="{FONT}" role="img" aria-label="{escape(label)}">'
            f"<title>{escape(label)}</title>"
            f'<clipPath id="r"><rect width="{W}" height="{height:.0f}" rx="12"/></clipPath>'
            f'<g clip-path="url(#r)"><rect width="{W}" height="{height:.0f}" fill="{BG}"/>'
            f"{''.join(self.parts)}</g></svg>\n"
        )
        (OUT / name).write_text(svg)
        print(f"wrote {name}")


BOT = COLOURS["blurple"]
MOD = "#e8a2c8"


def moderation() -> None:
    s = Scene().header("moderators")
    s.used("Ayesha", "timeout", MOD).message(
        "Warden",
        BOT,
        ["**Case #12** · Timed out {@spammer} for 1h", "Reason: Flooding {#general} with copypasta"],
        bot=True,
        compact_top=True,
    ).ephemeral()
    s.header("mod-log")
    s.message("Warden", BOT, bot=True)
    s.embed(
        COLOURS["yellow"],
        title="Case #11 · Warned",
        thumbnail=("#5d6af2", "S"),
        fields=[
            Field("Member", ["{@spammer}"]),
            Field("Moderator", ["{@Ayesha}"]),
            Field("Reason", ["Posting the same link in 4 channels"], inline=False),
        ],
    )
    s.embed(
        COLOURS["orange"],
        title="Case #12 · Timed out",
        thumbnail=("#5d6af2", "S"),
        fields=[
            Field("Member", ["{@spammer}"]),
            Field("Moderator", ["{@Ayesha}"]),
            Field("Duration", ["1h"]),
            Field("Reason", ["Flooding #general with copypasta"], inline=False),
        ],
    )
    s.embed(
        COLOURS["red"],
        title="Case #13 · Banned",
        thumbnail=("#3ba55c", "F"),
        fields=[
            Field("Member", ["{@free_nitro_bot}"]),
            Field("Moderator", ["{@Omar}"]),
            Field("Reason", ["Scam links in DMs to members"], inline=False),
        ],
    )
    s.header("Warden", kind="@")
    s.message(
        "Warden",
        BOT,
        ["You were timed out in **Night Owls**.", "Duration: 1h", "Reason: Flooding #general with copypasta"],
        bot=True,
    )
    s.save("moderation.svg", "Warden moderation: a /timeout reply, mod-log case embeds and the member's DM")


def automod() -> None:
    s = Scene().header("general")
    s.message("maya", "#f47fff", ["anyone up for ranked tonight?"])
    s.message("spammer", "#5d6af2", ["{~FREE NITRO for everyone, claim yours at free-nitro.gift}"])
    s.note("{!Deleted by automod}")
    s.message(
        "Warden",
        BOT,
        ["{@spammer}, your message was removed: links to free-nitro.gift aren't allowed. Strike 3."],
        bot=True,
    )
    s.note("Disappears after 10 seconds")
    s.header("mod-log")
    s.message("Warden", BOT, bot=True)
    s.embed(
        COLOURS["yellow"],
        title="Case #14 · Warned",
        thumbnail=("#5d6af2", "S"),
        fields=[
            Field("Member", ["{@spammer}"]),
            Field("Moderator", ["{@Warden}"]),
            Field("Reason", ["Automod: links to free-nitro.gift aren't allowed"], inline=False),
        ],
    )
    s.embed(
        COLOURS["orange"],
        title="Case #15 · Timed out",
        thumbnail=("#5d6af2", "S"),
        fields=[
            Field("Member", ["{@spammer}"]),
            Field("Moderator", ["{@Warden}"]),
            Field("Duration", ["1h"]),
            Field("Reason", ["Automod: reached 3 strikes"], inline=False),
        ],
    )
    s.message(
        "Warden",
        BOT,
        [
            "**Raid mode is on**: 10 members joined within 10 seconds.",
            "New members will be kicked until a moderator runs `/automod raid state:off`.",
        ],
        bot=True,
        time="Today at 21:09",
    )
    s.save(
        "automod.svg", "Warden automod: a removed scam link, strike escalation to a timeout, and a raid alert"
    )


def onboarding() -> None:
    s = Scene().header("welcome")
    s.message("Warden", BOT, ["Welcome to **Night Owls**, {@maya}! You're member #128."], bot=True)
    s.header("rules")
    s.message("Warden", BOT, bot=True)
    s.embed(
        COLOURS["blurple"],
        title="Server rules",
        description=[
            "1. Be kind. No harassment, hate speech or slurs.",
            "2. No spam, self-promotion or invite links.",
            "3. Keep it safe for work, including usernames and avatars.",
            "4. Moderators have the final say.",
        ],
        footer="Press I agree to confirm you've read the rules.",
    )
    s.buttons(("✓  I agree", "#248046"))
    s.message("Warden", BOT, ["Thanks! You now have {@Verified}. Enjoy the server."], bot=True)
    s.ephemeral()
    s.header("Warden", kind="@")
    s.message(
        "Warden",
        BOT,
        ["Hi maya, welcome to **Night Owls**! Read the rules and press **I agree** to get access."],
        bot=True,
    )
    s.save(
        "onboarding.svg",
        "Warden onboarding: welcome message, rules with an I agree button, and the welcome DM",
    )


def leveling() -> None:
    s = Scene().header("general")
    s.message("maya", "#f47fff", ["that clutch in the last round tho"])
    s.message("Warden", BOT, ["GG {@maya}, you reached **level 5**!"], bot=True)
    s.used("maya", "rank", "#f47fff").message("Warden", BOT, bot=True, compact_top=True)
    s.embed(
        COLOURS["purple"],
        title="maya",
        thumbnail=("#f47fff", "M"),
        fields=[
            Field("Level", ["5"]),
            Field("Rank", ["#3"]),
            Field("Total XP", ["1,450"]),
            Field("Next level", [], inline=False),
        ],
        progress=(300 / 475, "300 / 475 XP"),
    )
    s.used("kai", "leaderboard", "#43b581").message("Warden", BOT, bot=True, compact_top=True)
    s.embed(
        COLOURS["gold"],
        title="Night Owls leaderboard",
        description=[
            "**#1**  {@kai} · level 9 · 4,210 XP",
            "**#2**  {@noor} · level 7 · 2,640 XP",
            "**#3**  {@maya} · level 5 · 1,450 XP",
            "**#4**  {@leo} · level 4 · 980 XP",
            "**#5**  {@sam} · level 2 · 310 XP",
        ],
        footer="Page 1 of 4",
    )
    s.save("leveling.svg", "Warden leveling: a level-up message, a /rank card and the leaderboard")


def perks() -> None:
    s = Scene().header("admin")
    s.used("Ayesha", "perks list", MOD).message("Warden", BOT, bot=True, compact_top=True)
    s.embed(
        COLOURS["purple"],
        title="Level rewards",
        description=[
            "**Level 2** · {@Chatter}",
            "**Level 5** · {@Image Perms}",
            "**Level 10** · {@VIP Lounge}",
            "**Level 20** · {@Night Owl}  {!⚠ above my highest role. Move my role up}",
        ],
        footer="Lower rewards are kept",
    )
    s.ephemeral()
    s.header("general")
    s.message("Warden", BOT, ["GG {@maya}, you reached **level 5**!"], bot=True)
    s.roles(
        "MAYA'S ROLES",
        [
            ("Member", "#99aab5"),
            ("Verified", COLOURS["green"]),
            ("Chatter", COLOURS["teal"]),
            ("Image Perms", COLOURS["pink"]),
        ],
        highlight={"Image Perms"},
    )
    s.note("{@Image Perms} unlocked at level 5: lets maya post images and embeds")
    s.save("perks.svg", "Warden perks: the level rewards list and a role unlocked on level-up")


def config() -> None:
    s = Scene().header("admin")
    s.used("Ayesha", "config view module:automod", MOD).message("Warden", BOT, bot=True, compact_top=True)
    s.embed(
        COLOURS["blurple"],
        title="Warden settings",
        fields=[
            Field(
                "Automod",
                [
                    "`automod.enabled`: on",
                    "`automod.links_enabled`: on",
                    "`automod.link_allowlist`: `tenor.com, giphy.com, youtube.com`",
                    "`automod.max_mentions`: `5`",
                    "`automod.spam_messages`: `6`  within  `automod.spam_seconds`: `5`",
                    "`automod.timeout_at`: `3`  ·  `automod.kick_at`: `5`  ·  `automod.ban_at`: `7`",
                ],
                inline=False,
            )
        ],
        footer="Change one with /config set, restore its default with /config reset",
    )
    s.ephemeral()
    s.used("Ayesha", "config set key:automod.ban_at value:10", MOD).message(
        "Warden", BOT, ["`automod.ban_at` is now `10`."], bot=True, compact_top=True
    ).ephemeral()
    s.save("config.svg", "Warden settings: /config view for the automod module and a /config set reply")


def banner() -> None:
    w, h = 1280, 420
    chips = [
        "Moderation",
        "Automod",
        "Raid shield",
        "Strike escalation",
        "Onboarding",
        "Leveling",
        "Level perks",
    ]
    chip_svg, x = [], 0
    widths = [len(c) * 11 + 36 for c in chips]
    x = (w - (sum(widths) + 12 * (len(chips) - 1))) / 2
    for chip, cw in zip(chips, widths, strict=True):
        chip_svg.append(
            f'<rect x="{x:.0f}" y="300" width="{cw}" height="40" rx="20" fill="#ffffff" fill-opacity="0.08" '
            f'stroke="#ffffff" stroke-opacity="0.18"/>'
            f'<text x="{x + cw / 2:.0f}" y="326" font-size="18" fill="#e3e5ff" text-anchor="middle">{chip}</text>'
        )
        x += cw + 12
    shield = "M 0 -58 L 48 -40 L 48 4 C 48 34 28 54 0 66 C -28 54 -48 34 -48 4 L -48 -40 Z"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="{FONT}" role="img" aria-label="Warden: self-hosted moderation, automod, onboarding and leveling for Discord">
<title>Warden</title>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#1e1f3a"/><stop offset="1" stop-color="#111214"/>
  </linearGradient>
  <radialGradient id="glow" cx="0.5" cy="0.35" r="0.55">
    <stop offset="0" stop-color="#5865f2" stop-opacity="0.55"/><stop offset="1" stop-color="#5865f2" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="shield" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#8891f7"/><stop offset="1" stop-color="#4752c4"/>
  </linearGradient>
  <clipPath id="r"><rect width="{w}" height="{h}" rx="24"/></clipPath>
</defs>
<g clip-path="url(#r)">
  <rect width="{w}" height="{h}" fill="url(#bg)"/>
  <rect width="{w}" height="{h}" fill="url(#glow)"/>
  <g transform="translate(400 150)">
    <path d="{shield}" fill="url(#shield)"/>
    <path d="M -20 2 L -4 18 L 24 -14" stroke="#fff" stroke-width="10" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  </g>
  <text x="480" y="178" font-size="96" font-weight="800" fill="#ffffff" letter-spacing="-2">Warden</text>
  <text x="{w / 2}" y="258" font-size="26" fill="#b5bac1" text-anchor="middle">Self-hosted moderation, automod, onboarding and leveling for Discord</text>
  {"".join(chip_svg)}
</g>
</svg>
"""
    (OUT / "banner.svg").write_text(svg)
    print("wrote banner.svg")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for render in (banner, moderation, automod, onboarding, leveling, perks, config):
        render()
