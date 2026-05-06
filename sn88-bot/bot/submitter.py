from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .config import Settings
from .strategy_engine import format_strategy


def validate_strategy_dict(strategy: dict[object, float | int]) -> None:
    if strategy.get("_") != 0:
        raise ValueError("Strategy must have {'_': 0} for Tao/Alpha")

    total = 0.0
    for k, v in strategy.items():
        if k == "_":
            continue
        if not isinstance(k, int):
            raise ValueError(f"Tao/Alpha subnet key must be int, got {k!r}")
        if not isinstance(v, (int, float)):
            raise ValueError(f"Weight for subnet {k} must be numeric")
        if float(v) < 0:
            raise ValueError(f"Tao/Alpha weight cannot be negative: {k}: {v}")
        total += float(v)

    if not (0.98 <= total <= 1.02):
        raise ValueError(f"Total allocation should be close to 1.0, got {total:.4f}")


def write_strategy_file(strategy: dict[object, float | int], settings: Settings) -> Path:
    validate_strategy_dict(strategy)
    text = format_strategy(strategy)
    target = settings.strategy_path
    target.parent.mkdir(parents=True, exist_ok=True)

    if settings.backup_old_strategy and target.exists():
        backup = target.with_name(target.name + ".backup")
        shutil.copy2(target, backup)

    # Atomic write in same directory.
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(target.parent), encoding="utf-8") as f:
        f.write(text)
        tmp_name = f.name

    os.replace(tmp_name, target)
    os.utime(target, None)  # important: miner detects timestamp and resubmits
    return target


def touch_strategy_file(settings: Settings) -> Path:
    target = settings.strategy_path
    if not target.exists():
        raise FileNotFoundError(f"Strategy file does not exist: {target}")
    os.utime(target, None)
    return target
