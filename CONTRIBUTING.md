# Contributing to Warden

Thanks for helping. This guide gets you from clone to pull request.

## Setup

```sh
git clone <repo-url> && cd Warden_Discord
uv sync                      # creates .venv with runtime + dev dependencies
cp .env.example .env         # add a test bot token and your test server ID
uv run python -m warden.devsetup   # optional: creates test channels/roles and settings
uv run python -m warden
```

## Before you open a pull request

```sh
uv run ruff check . && uv run ruff format .
uv run pytest
uv run python -m warden.docs   # if you added or changed a setting
```

CI runs all of this on Python 3.11–3.13, plus two Warden-specific checks:

- **Slash command validation** (`tests/test_commands.py`) loads every cog offline and checks
  each command against Discord's naming, length and permission rules.
- **Migration guard** (`scripts/check_migrations.py`) fails if a migration that already
  shipped was edited or removed.

## Conventions

- **One module, one cog** in `warden/cogs/`. Pure logic that doesn't need Discord objects goes
  in a top-level module (`filters.py`, `levels.py`) so it can be unit-tested.
- **Settings** are declared with `setting_group("<module>")` at the top of the cog. They
  appear in `/config` automatically.
- **Modules don't import each other.** They communicate through `bot.dispatch` events (see the
  README).
- **Every moderation action** goes through `actions.record_case`, so it gets a case number
  and a mod-log entry.
- **Schema changes** are a new string at the end of `MIGRATIONS` in `warden/db.py`, never an
  edit to an existing one.
- **Staff commands** need `@app_commands.default_permissions(...)`. The test suite enforces this.
