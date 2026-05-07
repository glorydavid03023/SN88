from __future__ import annotations

import time
from typing import Any

from .taostats_client import TaostatsClient, _extract_records, _get_any, _int, _num


def _page_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def _rao_to_tao(x: Any) -> float:
    v = _num(x, 0.0)
    if v == 0.0:
        return 0.0
    if abs(v) >= 1e7:
        return v / 1e9
    return v


def _parse_history_row(rec: dict[str, Any]) -> dict[str, Any] | None:
    netuid = _int(_get_any(rec, ["netuid", "subnet", "subnet_id"]), -1)
    if netuid < 0:
        return None
    ts_raw = _get_any(rec, ["timestamp", "time", "ts"], "")
    price = _num(_get_any(rec, ["price", "last_price", "alpha_price"]), 0.0)
    if price <= 0:
        return None
    liq_tao = _rao_to_tao(_get_any(rec, ["liquidity", "liquidity_raw"], 0))
    total_tao = _rao_to_tao(_get_any(rec, ["total_tao", "protocol_provided_tao"], 0))
    alpha_in_pool = _rao_to_tao(_get_any(rec, ["alpha_in_pool", "protocol_provided_alpha"], 0))
    alpha_staked = _rao_to_tao(_get_any(rec, ["alpha_staked"], 0))
    return {
        "netuid": netuid,
        "timestamp": str(ts_raw),
        "price": float(price),
        "liquidity_tao": float(liq_tao),
        "total_tao": float(total_tao),
        "alpha_in_pool": float(alpha_in_pool),
        "alpha_staked": float(alpha_staked),
    }


def fetch_netuid_hourly_history(
    client: TaostatsClient,
    *,
    endpoint: str,
    netuid: int,
    days: int,
    max_pages: int = 12,
    page_sleep_s: float = 0.25,
) -> list[dict[str, Any]]:
    """
    Paginate Taostats pool hourly history for one subnet (newest first per page),
    then return rows sorted ascending by time for modeling.
    """
    ts_end = int(time.time())
    ts_start = ts_end - int(days * 86400)
    ep = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    collected: list[dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        if page > 1:
            _page_sleep(page_sleep_s)
        payload = client.get_json(
            ep,
            params={
                "netuid": netuid,
                "frequency": "by_hour",
                "timestamp_start": ts_start,
                "timestamp_end": ts_end,
                "order": "timestamp_desc",
                "limit": 200,
                "page": page,
            },
        )
        records = _extract_records(payload)
        if not records:
            break
        for rec in records:
            row = _parse_history_row(rec)
            if row is not None:
                collected.append(row)
        if len(records) < 200:
            break

    collected.sort(key=lambda r: r["timestamp"])
    # De-duplicate same (netuid, timestamp) keeping last occurrence
    seen: dict[tuple[int, str], dict[str, Any]] = {}
    for row in collected:
        seen[(row["netuid"], row["timestamp"])] = row
    return [seen[k] for k in sorted(seen.keys(), key=lambda x: x[1])]
