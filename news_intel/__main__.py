"""python -m news_intel run | search <words> [--days 7] [--category technology] | brief | log"""
from __future__ import annotations

import argparse
import logging
import sys

from .assistant import lookup
from .briefing import make_briefing
from .config import CATEGORIES, NewsConfig, load_env_file
from .pipeline import run
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="news_intel", description="Nova's daily news desk")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="collect, analyze and save today's news once")
    search = commands.add_parser("search", help="search the news database")
    search.add_argument("words", nargs="*")
    search.add_argument("--days", type=int, default=1)
    search.add_argument("--offset-days", type=int, default=0)
    search.add_argument("--category", choices=CATEGORIES)
    commands.add_parser("brief", help="print today's briefing")
    commands.add_parser("log", help="the last runs")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env_file()
    config = NewsConfig()
    if args.command == "run":
        report = run(config, progress=lambda message: print(message, flush=True))
        print(report.line())
        for error in report.errors:
            print("  problem:", error)
        return 0
    store = Store(config.db_path)
    if args.command == "search":
        print(lookup(store, " ".join(args.words), args.category or "", args.days, args.offset_days))
    elif args.command == "brief":
        print(make_briefing(store))
    else:
        for item in store.runs():
            print(f"{item['started_at']} → {item['finished_at'] or 'running'}: collected {item['collected']}, new "
                  f"{item['added']}, analyzed {item['processed']}, failed {item['failed']}, problems {len(item['errors'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
