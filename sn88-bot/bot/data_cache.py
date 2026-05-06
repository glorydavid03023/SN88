from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import SubnetMetrics


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def save_taostats_snapshot(
    base_dir: Path,
    *,
    endpoint: str,
    payload: Any,
    metrics: Iterable[SubnetMetrics],
) -> dict[str, Path]:
    """
    Save raw + normalized Taostats data into the project for auditing/debugging.
    Returns paths written.
    """
    ts = _utc_stamp()
    base_dir.mkdir(parents=True, exist_ok=True)

    raw_path = base_dir / f"taostats_subnets_raw_{ts}.json"
    norm_json_path = base_dir / f"taostats_subnets_norm_{ts}.json"
    norm_csv_path = base_dir / f"taostats_subnets_norm_{ts}.csv"

    _write_json(
        raw_path,
        {
            "fetched_at_utc": ts,
            "endpoint": endpoint,
            "payload": payload,
        },
    )

    metrics_list = [asdict(m) for m in metrics]
    _write_json(
        norm_json_path,
        {
            "fetched_at_utc": ts,
            "endpoint": endpoint,
            "subnets": metrics_list,
        },
    )

    norm_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with norm_csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(SubnetMetrics.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in metrics_list:
            writer.writerow(row)

    # Keep only the latest snapshot files (delete older ones).
    keep = {raw_path.name, norm_json_path.name, norm_csv_path.name}
    for p in base_dir.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if name in keep:
            continue
        if name.startswith("taostats_subnets_raw_") and name.endswith(".json"):
            p.unlink(missing_ok=True)
        elif name.startswith("taostats_subnets_norm_") and name.endswith((".json", ".csv")):
            p.unlink(missing_ok=True)

    return {
        "raw_json": raw_path,
        "norm_json": norm_json_path,
        "norm_csv": norm_csv_path,
    }

