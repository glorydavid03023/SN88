from __future__ import annotations

import argparse
import sys

from .config import load_settings, validate_required_settings
from .logging_utils import log
from .submitter import touch_strategy_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Touch current SN88 strategy file to resubmit")
    parser.add_argument("--env", default=None, help="Path to .env file")
    args = parser.parse_args()

    settings = load_settings(args.env)
    validate_required_settings(settings)
    log_path = settings.logs_dir / "sn88_strategy_bot.log"

    path = touch_strategy_file(settings)
    log(f"Touched strategy file for resubmission: {path}", log_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
