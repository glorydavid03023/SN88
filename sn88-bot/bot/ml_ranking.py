from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import Settings
from .logging_utils import log
from .models import SubnetMetrics
from .pool_history import fetch_netuid_hourly_history
from .strategy_engine import filter_candidates
from .taostats_client import TaostatsClient


def _sleep_between_requests(settings: Settings) -> None:
    time.sleep(max(0.0, settings.ml_request_sleep_s))


def _build_frame_from_histories(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts"])
    return df


def _add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["netuid", "ts"]).reset_index(drop=True)
    g = df.groupby("netuid", group_keys=False)

    df["log_price"] = np.log(df["price"].clip(lower=1e-12))
    df["ret_1h"] = g["log_price"].diff()
    df["ret_6h"] = g["log_price"].diff(6)
    df["ret_24h_lag"] = g["log_price"].diff(24)

    df["total_alpha_est"] = (df["alpha_in_pool"] + df["alpha_staked"]).clip(lower=1e-9)
    df["alpha_pool_ratio"] = df["alpha_in_pool"] / df["total_alpha_est"]
    df["d_alpha_pool_ratio"] = g["alpha_pool_ratio"].diff()
    df["d_log_tao"] = g["total_tao"].apply(lambda s: np.log(s.clip(lower=1e-9))).diff()

    df["log_liquidity"] = np.log(df["liquidity_tao"].clip(lower=1.0))
    df["vol_24h"] = g["ret_1h"].transform(lambda s: s.rolling(24, min_periods=6).std())

    df["ts_hour"] = df["ts"].dt.floor("h")
    df["rank_ret_1h_cs"] = df.groupby("ts_hour")["ret_1h"].rank(pct=True, method="average")

    df["price_future"] = g["price"].shift(-24)
    df["return_24h"] = np.log(df["price_future"].clip(lower=1e-12) / df["price"].clip(lower=1e-12))
    df["price_up_24h"] = (df["price_future"] > df["price"]).astype(int)
    return df


def _train_and_predict(
    df_feat: pd.DataFrame,
    settings: Settings,
) -> tuple[pd.DataFrame, Any, Any]:
    import lightgbm as lgb

    feature_cols = [
        "ret_1h",
        "ret_6h",
        "ret_24h_lag",
        "d_log_tao",
        "d_alpha_pool_ratio",
        "vol_24h",
        "log_liquidity",
        "log_price",
        "alpha_pool_ratio",
        "rank_ret_1h_cs",
    ]
    train = df_feat.dropna(subset=feature_cols + ["return_24h", "price_up_24h"]).copy()
    train = train.replace([np.inf, -np.inf], np.nan).dropna(subset=feature_cols + ["return_24h", "price_up_24h"])
    train["return_24h"] = train["return_24h"].clip(-2.0, 2.0)
    if len(train) < settings.ml_min_train_rows:
        raise RuntimeError(
            f"Not enough training rows after feature build: {len(train)} "
            f"(need >= ML_MIN_TRAIN_ROWS={settings.ml_min_train_rows}). "
            "Increase ML_HISTORY_DAYS or check pool history API responses."
        )

    train_x = train[feature_cols].copy()
    train_x["netuid"] = train["netuid"].astype("category")
    y_cls = train["price_up_24h"].to_numpy(dtype=np.int32)
    y_reg = train["return_24h"].to_numpy(dtype=np.float64)

    params_common = {
        "verbosity": -1,
        "seed": settings.ml_lgbm_seed,
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "min_data_in_leaf": max(20, len(train) // 500),
    }
    clf = lgb.LGBMClassifier(n_estimators=200, **params_common)
    reg = lgb.LGBMRegressor(n_estimators=200, **params_common)
    clf.fit(train_x, y_cls, categorical_feature=["netuid"])
    reg.fit(train_x, y_reg, categorical_feature=["netuid"])

    live_idx = df_feat.groupby("netuid")["ts"].idxmax()
    live = df_feat.loc[live_idx].copy()
    live = live.dropna(subset=feature_cols)
    if live.empty:
        raise RuntimeError("No live rows with complete features for ML prediction.")

    live_x = live[feature_cols].copy()
    live_x["netuid"] = live["netuid"].astype("category")

    live["prob_up"] = clf.predict_proba(live_x)[:, 1]
    live["return_pred"] = reg.predict(live_x)
    return live, clf, reg


def _final_scores(
    live: pd.DataFrame,
    latest_by_netuid: dict[int, SubnetMetrics],
    settings: Settings,
) -> pd.DataFrame:
    rows = []
    for _, r in live.iterrows():
        uid = int(r["netuid"])
        snap = latest_by_netuid.get(uid)
        if snap is None:
            continue
        liq = max(float(snap.liquidity_tao), 1.0)
        vol = float(r.get("vol_24h") or 0.0)
        slip = 1.0 / np.sqrt(liq + 1.0)
        rows.append(
            {
                "netuid": uid,
                "prob_up": float(r["prob_up"]),
                "return_pred": float(r["return_pred"]),
                "vol_24h": vol,
                "slip": float(slip),
                "liquidity_tao": liq,
            }
        )
    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    liq_min = out["liquidity_tao"].min()
    liq_max = out["liquidity_tao"].max()
    if liq_max > liq_min:
        out["liq_norm"] = (out["liquidity_tao"] - liq_min) / (liq_max - liq_min)
    else:
        out["liq_norm"] = 0.5

    vol_max = out["vol_24h"].max()
    if vol_max > 1e-12:
        out["vol_norm"] = out["vol_24h"] / vol_max
    else:
        out["vol_norm"] = 0.0

    slip_max = out["slip"].max()
    if slip_max > 1e-12:
        out["slip_norm"] = out["slip"] / slip_max
    else:
        out["slip_norm"] = 0.0

    pos_ret = np.maximum(out["return_pred"], 0.0)
    out["edge"] = pos_ret * out["liq_norm"] * np.clip(2.0 * out["prob_up"] - 1.0, 0.0, 1.0)
    out["final_score"] = (
        out["edge"]
        - settings.ml_vol_lambda * out["vol_norm"]
        - settings.ml_slip_lambda * out["slip_norm"]
    )
    return out


def fetch_and_rank_ml(
    client: TaostatsClient,
    latest_metrics: list[SubnetMetrics],
    settings: Settings,
    log_path: Path,
) -> list[SubnetMetrics]:
    filtered = filter_candidates(latest_metrics, settings)
    latest_by_netuid = {m.netuid: m for m in latest_metrics}
    candidates = filtered
    if settings.ml_max_subnets_fetch > 0:
        candidates.sort(key=lambda m: m.liquidity_tao, reverse=True)
        candidates = candidates[: settings.ml_max_subnets_fetch]

    log(f"ML: fetching hourly pool history for {len(candidates)} subnets...", log_path)
    all_rows: list[dict[str, Any]] = []
    ok = 0
    for m in candidates:
        try:
            hist = fetch_netuid_hourly_history(
                client,
                endpoint=settings.taostats_pool_history_endpoint,
                netuid=m.netuid,
                days=settings.ml_history_days,
                max_pages=settings.ml_history_max_pages,
                page_sleep_s=settings.ml_history_page_sleep_s,
            )
            if len(hist) >= settings.ml_min_rows_per_subnet:
                all_rows.extend(hist)
                ok += 1
        except Exception as exc:
            log(f"ML: skip netuid={m.netuid} history error: {exc}", log_path)
        _sleep_between_requests(settings)

    log(f"ML: loaded history slices for {ok} subnets, {len(all_rows)} rows", log_path)
    df = _build_frame_from_histories(all_rows)
    if df.empty:
        raise RuntimeError("ML: empty dataframe after pool history fetch.")

    df_feat = _add_features(df)
    live, _, _ = _train_and_predict(df_feat, settings)
    scores = _final_scores(live, latest_by_netuid, settings)
    if scores.empty:
        raise RuntimeError("ML: no scores produced (check live feature rows).")

    gated = scores[scores["prob_up"] >= settings.ml_prob_threshold].copy()
    if len(gated) < settings.top_n:
        log(
            f"ML: prob>={settings.ml_prob_threshold} only {len(gated)} rows; relaxing gate.",
            log_path,
        )
        gated = scores.copy()

    gated = gated.sort_values("final_score", ascending=False)

    out_metrics: list[SubnetMetrics] = []
    for _, r in gated.iterrows():
        uid = int(r["netuid"])
        base = latest_by_netuid.get(uid)
        if base is None:
            continue
        if base.liquidity_tao < settings.min_liquidity_tao:
            continue
        if base.change_1h > settings.max_1h_pump:
            continue
        row = SubnetMetrics(
            netuid=base.netuid,
            name=base.name,
            alpha_price=base.alpha_price,
            change_1h=base.change_1h,
            change_1d=base.change_1d,
            change_7d=base.change_7d,
            liquidity_tao=base.liquidity_tao,
            flow_24h=base.flow_24h,
            flow_7d=base.flow_7d,
            emission=base.emission,
            drawdown=base.drawdown,
            score=float(r["final_score"]),
            ml_prob_up=float(r["prob_up"]),
            ml_return_pred=float(r["return_pred"]),
        )
        out_metrics.append(row)

    out_metrics.sort(key=lambda x: x.score, reverse=True)
    if not out_metrics:
        raise RuntimeError("ML: no subnets passed liquidity / pump filters after scoring.")

    log(f"ML: ranked {len(out_metrics)} subnets before TOP_N cap", log_path)
    return out_metrics
