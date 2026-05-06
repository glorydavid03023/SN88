from __future__ import annotations

import ast
import argparse
from pathlib import Path

from .submitter import validate_strategy_dict


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate SN88 Tao/Alpha strategy file")
    parser.add_argument("path", type=Path, help="Path to strategy file")
    args = parser.parse_args()

    text = args.path.read_text(encoding="utf-8").strip()
    strategy = ast.literal_eval(text)
    validate_strategy_dict(strategy)
    total = sum(float(v) for k, v in strategy.items() if k != "_")
    print(f"OK: valid Tao/Alpha strategy. total={total:.4f}")


if __name__ == "__main__":
    main()
