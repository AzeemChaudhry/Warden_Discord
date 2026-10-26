# Security policy

## Reporting a vulnerability

Please **don't open a public issue**. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) for this repository instead.
Include what you found, how to reproduce it, and what impact you think it has.

Expect an acknowledgement within a few days. Once a fix is released, you'll be credited
unless you'd rather stay anonymous.

## Scope

Examples of what counts:

- Ways for a member to run staff commands or get around permission checks
- Ways to make Warden act on members above it in the role hierarchy
- Bypasses of automod or raid mode that need a code change to fix
- Leaks of the bot token or stored server data

## Running Warden safely

- Keep `DISCORD_TOKEN` in `.env`, which is already git-ignored. If a token ever leaks,
  regenerate it in the developer portal straight away.
- Give the bot only the permissions listed in the README.
- Keep Warden's role below your admin roles and above the roles it manages.
