"""Fail if a pull request edits or removes a database migration that already shipped.

Migrations already applied to someone's database never run again, so editing
one silently leaves existing installs on the old schema. New changes must be
appended as a new migration.

    python scripts/check_migrations.py origin/main
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

DB_FILE = "warden/db.py"


def migrations_from_source(source: str) -> list[str]:
    # Parsed, not imported: the base branch's code is never executed.
    for node in ast.walk(ast.parse(source)):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == "MIGRATIONS" for t in targets):
            return [m.strip() for m in ast.literal_eval(node.value)]
    raise SystemExit(f"MIGRATIONS not found in {DB_FILE}")


def main(base_ref: str) -> int:
    try:
        base_source = subprocess.run(
            ["git", "show", f"{base_ref}:{DB_FILE}"], check=True, capture_output=True, text=True
        ).stdout
    except subprocess.CalledProcessError:
        print(f"{DB_FILE} doesn't exist on {base_ref}; nothing to compare.")
        return 0

    base = migrations_from_source(base_source)
    head = migrations_from_source(Path(DB_FILE).read_text())

    if len(head) < len(base):
        print(
            f"::error file={DB_FILE}::Migrations were removed ({len(base)} on {base_ref}, {len(head)} now)."
        )
        return 1
    for number, (old, new) in enumerate(zip(base, head, strict=False), start=1):
        if old != new:
            print(
                f"::error file={DB_FILE}::Migration {number} was changed after it shipped. "
                "Revert it and append a new migration instead."
            )
            return 1
    print(f"OK: {len(base)} existing migration(s) untouched, {len(head) - len(base)} new.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "origin/main"))
