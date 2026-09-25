"""Command-line operations for local development and portable backups."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .config import Settings
from .store import Store


def main():
    parser = argparse.ArgumentParser(prog="jev-scout", description="An evidence-linked research inbox.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the local application and persistent worker.")
    serve.add_argument("--port", type=int)
    sub.add_parser("seed", help="Load the attributed public collection and lexical decisions, idempotently.")
    sub.add_parser("doctor", help="Show non-secret configuration and local installation status.")
    backup = sub.add_parser("backup", help="Create a consistent SQLite backup while the app is running.")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args()
    settings = Settings.load()
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(
            create_app(settings), host=settings.host, port=args.port or settings.port, access_log=False
        )
    elif args.command == "seed":
        from .jobs import seed_demo

        print(
            json.dumps(
                asyncio.run(seed_demo(Store(settings.database_path), settings)), ensure_ascii=False, indent=2
            )
        )
    elif args.command == "backup":
        destination = args.destination.resolve()
        if destination.exists():
            parser.error("The backup destination already exists. Choose a new filename.")
        if destination == settings.database_path.resolve():
            parser.error("Backup destination must differ from the running database.")
        Store(settings.database_path).backup(destination)
        print(f"Backup created: {destination}")
    else:
        print(json.dumps({**settings.public(), "database_exists": settings.database_path.exists()}, indent=2))


if __name__ == "__main__":
    main()
