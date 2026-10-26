"""Parse and format human durations like ``10m`` or ``1h30m``."""

from __future__ import annotations

import re
from datetime import timedelta

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_PART = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)


def parse_duration(text: str) -> timedelta:
    """Parse ``"90s"``, ``"10m"``, ``"1h30m"``, ``"2d"`` and similar.

    A bare number is treated as minutes. Raises ``ValueError`` on bad input.
    """
    cleaned = text.strip().lower().replace(" ", "")
    if not cleaned:
        raise ValueError("Duration is empty.")
    if cleaned.isdigit():
        return timedelta(minutes=int(cleaned))

    total = 0
    pos = 0
    for match in _PART.finditer(cleaned):
        if match.start() != pos:
            break
        total += int(match.group(1)) * _UNITS[match.group(2)]
        pos = match.end()
    if pos != len(cleaned) or total == 0:
        raise ValueError(f"Couldn't read `{text}` as a duration. Try `10m`, `2h` or `1d12h`.")
    return timedelta(seconds=total)


def format_duration(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    parts = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{name}")
    return " ".join(parts) or "0s"
