from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Set

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _as_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _as_set_int(name: str, default: str = "0") -> Set[int]:
    raw = os.getenv(name, default)
    out: Set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.add(int(part))
    return out


@dataclass(frozen=True)
class Settings:
    taostats_api_key: str
    investing_dir: Path
    hotkey_ss58: str
    subnet_data_source: str
    taostats_base_url: str
    taostats_subnets_endpoint: str
    csv_path: Path
    save_fetched_data: bool
    fetched_data_dir: Path

    top_n: int
    min_liquidity_tao: float
    max_weight: float
    min_weight: float
    max_1h_pump: float
    exclude_netuids: Set[int]

    w_7d: float
    w_1d: float
    w_1h: float
    w_liquidity: float
    w_flow: float
    w_emission: float
    w_drawdown: float

    dry_run: bool
    backup_old_strategy: bool

    @property
    def strategy_path(self) -> Path:
        return self.investing_dir / "Investing" / "strat" / self.hotkey_ss58

    @property
    def logs_dir(self) -> Path:
        return self.investing_dir / "logs"


def load_settings(env_file: str | None = None) -> Settings:
    if env_file:
        load_dotenv(env_file)
    else:
        load_dotenv()

    investing_dir = Path(os.getenv("INVESTING_DIR", "/root/investing")).expanduser().resolve()
    csv_path = Path(os.getenv("CSV_PATH", "./data/subnets_sample.csv")).expanduser()
    if not csv_path.is_absolute():
        # relative to current working directory
        csv_path = Path.cwd() / csv_path
    fetched_data_dir = Path(os.getenv("FETCHED_DATA_DIR", "./data/taostats")).expanduser()
    if not fetched_data_dir.is_absolute():
        fetched_data_dir = Path.cwd() / fetched_data_dir

    return Settings(
        taostats_api_key=os.getenv("TAOSTATS_API_KEY", "").strip(),
        investing_dir=investing_dir,
        hotkey_ss58=os.getenv("HOTKEY_SS58", "").strip(),
        subnet_data_source=os.getenv("SUBNET_DATA_SOURCE", "taostats").strip().lower(),
        taostats_base_url=os.getenv("TAOSTATS_BASE_URL", "https://api.taostats.io").rstrip("/"),
        taostats_subnets_endpoint=os.getenv("TAOSTATS_SUBNETS_ENDPOINT", "/api/dtao/subnet/latest/v1").strip(),
        csv_path=csv_path,
        save_fetched_data=_as_bool(os.getenv("SAVE_FETCHED_DATA"), False),
        fetched_data_dir=fetched_data_dir,
        top_n=_as_int("TOP_N", 10),
        min_liquidity_tao=_as_float("MIN_LIQUIDITY_TAO", 5000.0),
        max_weight=_as_float("MAX_WEIGHT", 0.20),
        min_weight=_as_float("MIN_WEIGHT", 0.03),
        max_1h_pump=_as_float("MAX_1H_PUMP", 35.0),
        exclude_netuids=_as_set_int("EXCLUDE_NETUIDS", "0"),
        w_7d=_as_float("W_7D", 0.45),
        w_1d=_as_float("W_1D", 0.25),
        w_1h=_as_float("W_1H", 0.10),
        w_liquidity=_as_float("W_LIQUIDITY", 0.10),
        w_flow=_as_float("W_FLOW", 0.10),
        w_emission=_as_float("W_EMISSION", 0.10),
        w_drawdown=_as_float("W_DRAWDOWN", 0.25),
        dry_run=_as_bool(os.getenv("DRY_RUN"), False),
        backup_old_strategy=_as_bool(os.getenv("BACKUP_OLD_STRATEGY"), True),
    )


def validate_required_settings(settings: Settings) -> None:
    if not settings.hotkey_ss58:
        raise ValueError("HOTKEY_SS58 is missing in .env")
    if settings.subnet_data_source == "taostats" and not settings.taostats_api_key:
        raise ValueError("TAOSTATS_API_KEY is missing in .env")
    if settings.max_weight <= 0 or settings.max_weight > 1:
        raise ValueError("MAX_WEIGHT must be between 0 and 1")
    if settings.min_weight < 0 or settings.min_weight > settings.max_weight:
        raise ValueError("MIN_WEIGHT must be >= 0 and <= MAX_WEIGHT")
