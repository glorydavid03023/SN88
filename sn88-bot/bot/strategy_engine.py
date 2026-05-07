from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
import math
from statistics import mean

from .config import Settings
from .models import SubnetMetrics


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [0.5 for _ in values]
    return [(x - lo) / (hi - lo) for x in values]


def filter_candidates(rows: list[SubnetMetrics], settings: Settings) -> list[SubnetMetrics]:
    filtered: list[SubnetMetrics] = []

    for r in rows:
        if r.netuid in settings.exclude_netuids:
            continue

        if r.liquidity_tao and r.liquidity_tao < settings.min_liquidity_tao:
            continue

        # Avoid buying a very sharp 1H pump because it often reverses.
        if r.change_1h > settings.max_1h_pump:
            continue

        # Avoid clearly weak trend.
        if r.change_7d < 0 and r.change_1d < 0:
            continue

        filtered.append(r)

    if not filtered:
        raise RuntimeError("No candidates passed filters. Lower MIN_LIQUIDITY_TAO or check input data.")

    return filtered


def score_subnets(rows: list[SubnetMetrics], settings: Settings) -> list[SubnetMetrics]:
    candidates = filter_candidates(rows, settings)

    liq_norm = _normalize([r.liquidity_tao for r in candidates])
    flow_norm = _normalize([max(r.flow_24h, r.flow_7d, 0.0) for r in candidates])
    emission_norm = _normalize([r.emission for r in candidates])

    for idx, r in enumerate(candidates):
        r.score = (
            settings.w_7d * r.change_7d
            + settings.w_1d * r.change_1d
            + settings.w_1h * r.change_1h
            + settings.w_liquidity * 10.0 * liq_norm[idx]
            + settings.w_flow * 10.0 * flow_norm[idx]
            + settings.w_emission * 10.0 * emission_norm[idx]
            - settings.w_drawdown * abs(r.drawdown)
        )

    candidates.sort(key=lambda x: x.score, reverse=True)
    return candidates


def pick_top_preordered(scored: list[SubnetMetrics], settings: Settings) -> list[SubnetMetrics]:
    """
    Take the first TOP_N rows from a list already sorted by score descending
    (for example ML-ranked subnets), respecting the SN88 API min-weight vs N bound.
    """
    n = min(settings.top_n, len(scored))
    while n > 1 and settings.min_weight > (1.0 / (n**0.7)):
        n -= 1
    return scored[:n]


def pick_top(rows: list[SubnetMetrics], settings: Settings) -> list[SubnetMetrics]:
    scored = score_subnets(rows, settings)
    return pick_top_preordered(scored, settings)


def build_weights(top_rows: list[SubnetMetrics], settings: Settings) -> dict[int, float]:
    if not top_rows:
        raise RuntimeError("No top rows to weight")

    n = len(top_rows)
    api_max_weight = 1.0 / (n**0.7) if n > 0 else settings.max_weight
    q = Decimal("0.0001")
    # Quantize max weight down to 4dp so we never exceed API's real-number bound
    # after formatting/parsing.
    api_max_weight_dec = Decimal(str(api_max_weight)).quantize(q, rounding=ROUND_DOWN)
    settings_max_weight_dec = Decimal(str(settings.max_weight)).quantize(q, rounding=ROUND_DOWN)
    effective_max_weight_dec = min(settings_max_weight_dec, api_max_weight_dec)
    if Decimal(str(settings.min_weight)) > effective_max_weight_dec:
        raise RuntimeError(
            f"MIN_WEIGHT={settings.min_weight} exceeds allowed max per-position weight "
            f"for N={n}: min(MAX_WEIGHT={settings.max_weight}, 1/N**0.7={api_max_weight:.6f})"
        )

    # If all scores are bad, use a softer score based on ranking.
    positive_scores = [max(r.score, 0.01) for r in top_rows]
    if mean(positive_scores) <= 0.02:
        raw = [settings.top_n - i for i, _ in enumerate(top_rows)]
    else:
        raw = positive_scores

    total = sum(raw)
    weights = [x / total for x in raw]

    # Apply min weight first so selected assets matter.
    weights = [max(w, settings.min_weight) for w in weights]
    total = sum(weights)
    weights = [w / total for w in weights]

    # Cap max weight and redistribute overflow.
    capped = weights[:]
    for _ in range(10):
        overflow = 0.0
        uncapped = []

        for i, w in enumerate(capped):
            if w > float(effective_max_weight_dec):
                overflow += w - float(effective_max_weight_dec)
                capped[i] = float(effective_max_weight_dec)
            else:
                uncapped.append(i)

        if overflow <= 1e-10 or not uncapped:
            break

        add_each = overflow / len(uncapped)
        for i in uncapped:
            capped[i] += add_each

    total = sum(capped)
    final = [w / total for w in capped]

    # Round to 4 decimals and ensure sum never exceeds 1.0.
    #
    # Important: the miner/API sums parsed floats and can reject even tiny epsilons
    # like 1.000000000000001 > 1. We therefore ensure the *decimal* sum is <= 1.0000
    # by rounding down and allocating any remainder to the top row.
    #
    # Additionally, to avoid float accumulation error from decimal-looking strings,
    # we intentionally target a total allocation of 0.9999 (4dp) instead of 1.0000.
    # This stays "fully allocated" but avoids strict API checks.
    target_total = Decimal("0.9999")
    weights_dict: dict[int, float] = {}
    rounded_dec: dict[int, Decimal] = {}
    for row, w in zip(top_rows, final):
        # ROUND_DOWN guarantees we don't overshoot 1.0 due to rounding up.
        d = Decimal(str(w)).quantize(q, rounding=ROUND_DOWN)
        rounded_dec[row.netuid] = min(d, effective_max_weight_dec)

    subtotal = sum(rounded_dec.values())
    if subtotal > target_total:
        # Extra safety: trim the first weight by the minimal quantum.
        first = top_rows[0].netuid
        rounded_dec[first] = (rounded_dec[first] - q).max(Decimal("0.0000"))
        subtotal = sum(rounded_dec.values())

    # Allocate remainder (if any) across subnets without exceeding max.
    remainder = (target_total - subtotal).quantize(q, rounding=ROUND_DOWN)
    if remainder > 0:
        # Give remainder to highest-score assets first, respecting cap.
        for row in top_rows:
            if remainder <= 0:
                break
            uid = row.netuid
            headroom = (effective_max_weight_dec - rounded_dec[uid]).max(Decimal("0.0000"))
            if headroom <= 0:
                continue
            add = min(headroom, remainder)
            rounded_dec[uid] = (rounded_dec[uid] + add).quantize(q, rounding=ROUND_DOWN)
            remainder = (remainder - add).quantize(q, rounding=ROUND_DOWN)

    # Convert back to floats for formatting.
    for netuid, d in rounded_dec.items():
        weights_dict[netuid] = float(d)

    return weights_dict


def build_strategy(top_rows: list[SubnetMetrics], settings: Settings) -> dict[object, float | int]:
    weights = build_weights(top_rows, settings)
    strategy: dict[object, float | int] = {"_": 0}
    for netuid, weight in weights.items():
        strategy[netuid] = weight
    return strategy


def format_strategy(strategy: dict[object, float | int]) -> str:
    if strategy.get("_") != 0:
        raise ValueError("Only Tao/Alpha strategies with {'_': 0} are supported")

    items = [(k, v) for k, v in strategy.items() if k != "_"]
    lines = ["{", '    "_": 0,']
    for idx, (netuid, weight) in enumerate(items):
        comma = "," if idx < len(items) - 1 else ""
        lines.append(f"    {int(netuid)}: {float(weight):.4f}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"
