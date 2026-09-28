"""CLI: python -m carbon_forecast.ingest --start 2019-01-01 --end 2026-09-27"""

import argparse
import logging
from datetime import UTC, date, datetime, timedelta

from carbon_forecast.config import load_settings, resolve
from carbon_forecast.db import connect
from carbon_forecast.ingest import SOURCES, run_ingestion


def main(argv: list[str] | None = None) -> None:
    settings = load_settings()
    yesterday = datetime.now(UTC).date() - timedelta(days=1)

    p = argparse.ArgumentParser(
        prog="python -m carbon_forecast.ingest",
        description="Fetch missing periods from the Carbon Intensity and Open-Meteo APIs "
        "into DuckDB. Re-running only requests what is not already stored.",
    )
    p.add_argument(
        "--start",
        type=date.fromisoformat,
        default=settings["start_date"],
        help="first UTC date (default: %(default)s)",
    )
    p.add_argument(
        "--end",
        type=date.fromisoformat,
        default=yesterday,
        help="last UTC date, inclusive (default: yesterday, the latest complete day)",
    )
    p.add_argument(
        "--sources", default=",".join(SOURCES), help="comma-separated subset of: %(default)s"
    )
    p.add_argument("--db", default=settings["db_path"], help="DuckDB file (default: %(default)s)")
    p.add_argument(
        "--dry-run", action="store_true", help="plan requests from what is missing, but call no API"
    )
    args = p.parse_args(argv)

    if args.end < args.start:
        p.error("--end is before --start")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with connect(resolve(args.db)) as con:
        planned = run_ingestion(
            con,
            settings,
            args.start,
            args.end,
            tuple(s.strip() for s in args.sources.split(",") if s.strip()),
            dry_run=args.dry_run,
        )
    logging.info("requests %s: %s", "planned" if args.dry_run else "made", planned)


if __name__ == "__main__":
    main()
