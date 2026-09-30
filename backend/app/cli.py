import argparse
import logging
from pathlib import Path

from app.access_log import configure_logging
from app.db import SessionLocal
from app.seed import seed_users

log = logging.getLogger("drd.cli")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed-users", help="create users from a JSON file").add_argument("path", type=Path)
    args = parser.parse_args(argv)

    configure_logging()
    with SessionLocal() as db:
        if args.command == "seed-users":
            created = seed_users(db, args.path)
            log.info("seeded users", extra={"fields": {"created": created}})


if __name__ == "__main__":
    main()
