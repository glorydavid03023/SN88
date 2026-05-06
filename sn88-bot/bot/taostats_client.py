from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

import requests

from .config import Settings
from .models import SubnetMetrics

# Taostats docs show API requests use an Authorization header.
# The exact subnet-list endpoint can change, so this bot lets you configure
# TAOSTATS_SUBNETS_ENDPOINT and also tries common known endpoint shapes.
FALLBACK_SUBNET_ENDPOINTS = [
    "/api/dtao/subnet/latest/v1",
    "/api/dtao/subnets/latest/v1",
    "/api/subnet/latest/v1",
    "/api/subnets/latest/v1",
    "/api/subnet/v1",
]


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("%", "").strip()
    if text == "":
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _tao(value: Any, default: float = 0.0) -> float:
    """
    Convert Taostats numeric fields into TAO units.

    Some endpoints return integer-like quantities in rao (1e9 rao = 1 TAO),
    while others return already-scaled floats. Heuristic:
    - if magnitude looks like rao, divide by 1e9
    - otherwise return as float
    """
    x = _num(value, default=default)
    if x == 0:
        return x
    # If it's huge, it's almost certainly rao.
    if abs(x) >= 1e7:
        return x / 1e9
    return x


def _max_drawdown_pct(prices: Any) -> float:
    """
    Compute max drawdown (%) from a 7-day price series if provided.
    Accepts common shapes: [p1,p2,...] or [{...,'price':p}, ...].
    """
    if not prices:
        return 0.0
    series: list[float] = []
    if isinstance(prices, list):
        for item in prices:
            if isinstance(item, (int, float, str)):
                series.append(_num(item, default=0.0))
            elif isinstance(item, dict):
                series.append(_num(_get_any(item, ["price", "p", "value", "close", "last_price"]), default=0.0))
    series = [x for x in series if x > 0]
    if len(series) < 2:
        return 0.0
    peak = series[0]
    mdd = 0.0
    for x in series[1:]:
        if x > peak:
            peak = x
        dd = (peak - x) / peak * 100.0
        if dd > mdd:
            mdd = dd
    return float(mdd)


def _int(value: Any, default: int = -1) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return default


def _get_any(record: dict[str, Any], aliases: Iterable[str], default: Any = None) -> Any:
    # direct keys first
    for key in aliases:
        if key in record:
            return record[key]

    # case-insensitive fallback
    lower_map = {str(k).lower(): v for k, v in record.items()}
    for key in aliases:
        lk = key.lower()
        if lk in lower_map:
            return lower_map[lk]

    return default


def _has_any_key(record: dict[str, Any], aliases: Iterable[str]) -> bool:
    """True if any alias key exists (case-insensitive) in the record."""
    if not record:
        return False
    lower_keys = {str(k).lower() for k in record.keys()}
    for key in aliases:
        if key in record:
            return True
        if key.lower() in lower_keys:
            return True
    return False


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    """Extract list of dict rows from common API response shapes."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("subnets", "data", "results", "items", "records", "response"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = _extract_records(value)
            if nested:
                return nested

    # Last resort: find first list of dicts anywhere one level deep
    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
        if isinstance(value, dict):
            nested = _extract_records(value)
            if nested:
                return nested

    return []


def normalize_subnet_record(record: dict[str, Any]) -> SubnetMetrics | None:
    netuid = _int(_get_any(record, ["netuid", "subnet", "subnet_id", "id", "uid"]))
    if netuid < 0:
        return None

    name = str(_get_any(record, ["name", "subnet_name", "title", "symbol"], ""))

    # Some Taostats endpoints return chain config / metagraph-ish rows that contain netuid
    # but *not* the market metrics we need (price/changes/liquidity/flows/etc).
    # If none of the expected metric keys exist, skip this row so the caller can try
    # other endpoints (or force TAOSTATS_SUBNETS_ENDPOINT in .env).
    # Require at least one *market* metric key (not just generic chain keys like "emission").
    metric_key_groups: list[list[str]] = [
        ["alpha_price", "price", "price_tao", "alpha_price_tao", "last_price"],
        ["change_1h", "price_change_1h", "trend_1h", "price_change_1_hour", "1h", "one_hour", "1H"],
        ["change_1d", "change_24h", "price_change_24h", "trend_24h", "price_change_1_day", "24h", "24H", "1d", "1D"],
        ["change_7d", "change_1w", "price_change_1w", "trend_1w", "price_change_1_week", "7d", "7D", "1w", "1W"],
        ["liquidity_tao", "liquidity", "pool_liquidity", "subnet_liquidity", "total_liquidity"],
        ["flow_24h", "tao_flow_24h", "net_flow_24h", "net_volume", "volume_24h", "tao_volume_24_hr"],
        ["flow_7d", "tao_flow_7d", "net_flow_7d", "volume_7d"],
        ["drawdown", "max_drawdown", "drawdown_7d", "drawdown_30d"],
    ]
    if not any(_has_any_key(record, group) for group in metric_key_groups):
        # If name exists, keep it; but without any metric keys this is not usable.
        return None

    # Change aliases intentionally include Taostats UI column names.
    return SubnetMetrics(
        netuid=netuid,
        name=name,
        alpha_price=_num(_get_any(record, ["alpha_price", "price", "last_price", "price_tao", "alpha_price_tao"])),
        change_1h=_num(_get_any(record, ["change_1h", "price_change_1h", "price_change_1_hour", "trend_1h", "1h", "one_hour", "1H"])),
        change_1d=_num(_get_any(record, ["change_1d", "change_24h", "price_change_24h", "price_change_1_day", "trend_24h", "24h", "24H", "1d", "1D"])),
        change_7d=_num(_get_any(record, ["change_7d", "change_1w", "price_change_1w", "price_change_1_week", "trend_1w", "7d", "7D", "1w", "1W"])),
        liquidity_tao=_tao(_get_any(record, ["liquidity_tao", "liquidity", "pool_liquidity", "subnet_liquidity", "total_liquidity", "user_provided_tao", "protocol_provided_tao"])),
        flow_24h=_tao(_get_any(record, ["flow_24h", "tao_flow_24h", "net_flow_24h", "net_volume", "volume_24h", "tao_volume_24_hr"])),
        flow_7d=_num(_get_any(record, ["flow_7d", "tao_flow_7d", "net_flow_7d", "volume_7d"])),
        emission=_num(_get_any(record, ["emission", "emission_pct", "emission_percent", "emission_percentage"])),
        drawdown=_num(_get_any(record, ["drawdown", "max_drawdown", "drawdown_7d", "drawdown_30d"]), default=_max_drawdown_pct(_get_any(record, ["seven_day_prices"], default=None))),
    )


class TaostatsClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json",
            "authorization": settings.taostats_api_key,
        })
        self._last_endpoint_used: str | None = None
        self._last_payload: Any | None = None

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.settings.taostats_base_url}{endpoint}"
        resp = self.session.get(url, params=params or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def fetch_subnets(self) -> list[SubnetMetrics]:
        metrics, _, _ = self.fetch_subnets_with_payload()
        return metrics

    def fetch_subnets_with_payload(self) -> tuple[list[SubnetMetrics], str, Any]:
        endpoints = []
        if self.settings.taostats_subnets_endpoint:
            endpoints.append(self.settings.taostats_subnets_endpoint)
        endpoints.extend([e for e in FALLBACK_SUBNET_ENDPOINTS if e not in endpoints])

        last_error: str | None = None
        best_error: str | None = None
        for endpoint in endpoints:
            try:
                payload = self.get_json(endpoint, params={"limit": 200})
                records = _extract_records(payload)
                metrics = []
                for record in records:
                    item = normalize_subnet_record(record)
                    if item is not None:
                        metrics.append(item)
                if metrics:
                    self._last_endpoint_used = endpoint
                    self._last_payload = payload
                    return metrics, endpoint, payload
                if records:
                    sample_keys = list(records[0].keys())[:40] if isinstance(records[0], dict) else []
                    best_error = (
                        f"Endpoint {endpoint} returned rows, but none contained market metrics "
                        f"(price/changes/liquidity/flows/drawdown). Sample keys: {sample_keys}. "
                        f"Payload preview: {json.dumps(payload)[:500]}"
                    )
                    # If Taostats returned a valid 200 + rows, but the schema is the wrong dataset,
                    # further fallbacks are unlikely to help—raise a clear error immediately.
                    raise RuntimeError(best_error)
                else:
                    last_error = f"Endpoint {endpoint} returned no subnet rows. Payload preview: {json.dumps(payload)[:500]}"
            except Exception as exc:
                # Preserve a useful "wrong dataset" message if we already have one.
                if best_error is None:
                    last_error = f"Endpoint {endpoint} failed: {exc}"

        raise RuntimeError(
            "Could not fetch subnet data from Taostats. "
            "Set TAOSTATS_SUBNETS_ENDPOINT in .env to the endpoint from your Taostats API docs/account. "
            f"Last error: {best_error or last_error}"
        )


def load_subnets_from_csv(path: Path) -> list[SubnetMetrics]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    out: list[SubnetMetrics] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item = normalize_subnet_record(row)
            if item is not None:
                out.append(item)
    return out
