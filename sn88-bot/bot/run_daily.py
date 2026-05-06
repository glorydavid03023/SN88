from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_settings, validate_required_settings
from .data_cache import save_taostats_snapshot
from .logging_utils import log
from .strategy_engine import build_strategy, pick_top, format_strategy
from .submitter import write_strategy_file
from .taostats_client import TaostatsClient, load_subnets_from_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and submit SN88 Tao/Alpha strategy")
    parser.add_argument("--env", default=None, help="Path to .env file")
    parser.add_argument("--source", choices=["taostats", "csv"], default=None, help="Override SUBNET_DATA_SOURCE")
    parser.add_argument("--dry-run", action="store_true", help="Print strategy but do not write/touch strategy file")
    parser.add_argument("--save-data", action="store_true", help="Save fetched Taostats payload + normalized rows into FETCHED_DATA_DIR")
    parser.add_argument("--submit", action="store_true", help="Write/touch strategy file even if DRY_RUN=true in .env")
    args = parser.parse_args()

    settings = load_settings(args.env)
    if args.source:
        settings = settings.__class__(**{**settings.__dict__, "subnet_data_source": args.source})
    if args.dry_run:
        settings = settings.__class__(**{**settings.__dict__, "dry_run": True})
    if args.save_data:
        settings = settings.__class__(**{**settings.__dict__, "save_fetched_data": True})
    if args.submit:
        settings = settings.__class__(**{**settings.__dict__, "dry_run": False})

    validate_required_settings(settings)
    log_path = settings.logs_dir / "sn88_strategy_bot.log"

    log("Starting SN88 strategy bot", log_path)
    log(f"Data source: {settings.subnet_data_source}", log_path)
    log(f"Strategy path: {settings.strategy_path}", log_path)

    if settings.subnet_data_source == "csv":
        rows = load_subnets_from_csv(settings.csv_path)
        log(f"Loaded {len(rows)} subnet rows from CSV: {settings.csv_path}", log_path)
    else:
        client = TaostatsClient(settings)
        rows, endpoint_used, payload = client.fetch_subnets_with_payload()
        log(f"Fetched {len(rows)} subnet rows from Taostats", log_path)
        if settings.save_fetched_data:
            paths = save_taostats_snapshot(
                settings.fetched_data_dir,
                endpoint=endpoint_used,
                payload=payload,
                metrics=rows,
            )
            log(f"Saved Taostats snapshot: {paths['raw_json']}", log_path)
            log(f"Saved Taostats normalized: {paths['norm_csv']}", log_path)

    top = pick_top(rows, settings)
    strategy = build_strategy(top, settings)
    strategy_text = format_strategy(strategy)

    log("Selected subnets:", log_path)
    for row in top:
        log("  " + row.as_log_line(), log_path)

    log("Generated strategy:", log_path)
    for line in strategy_text.splitlines():
        log("  " + line, log_path)

    if settings.dry_run:
        log("DRY_RUN=true, not writing strategy file", log_path)
        return 0

    path = write_strategy_file(strategy, settings)
    log(f"Wrote and touched strategy file: {path}", log_path)
    log("Done", log_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
