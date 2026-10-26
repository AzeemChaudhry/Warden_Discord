import logging
import os
import signal
import sys

from dotenv import load_dotenv

from .bot import BotConfig, Warden


def _stop(signum: int, frame: object) -> None:
    # discord.py shuts down cleanly on KeyboardInterrupt; treat SIGTERM
    # (docker stop, systemd) the same way so the database closes properly.
    raise KeyboardInterrupt


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        sys.exit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")

    dev_guild = os.getenv("DEV_GUILD_ID", "").strip()
    config = BotConfig(
        token=token,
        database_path=os.getenv("DATABASE_PATH", "warden.db"),
        dev_guild_id=int(dev_guild) if dev_guild else None,
    )
    Warden(config).run(config.token, log_handler=None)


if __name__ == "__main__":
    main()
