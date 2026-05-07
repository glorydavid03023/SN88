from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SubnetMetrics:
    netuid: int
    name: str = ""
    alpha_price: float = 0.0
    change_1h: float = 0.0
    change_1d: float = 0.0
    change_7d: float = 0.0
    liquidity_tao: float = 0.0
    flow_24h: float = 0.0
    flow_7d: float = 0.0
    emission: float = 0.0
    drawdown: float = 0.0
    score: float = 0.0
    ml_prob_up: float | None = None
    ml_return_pred: float | None = None

    def as_log_line(self) -> str:
        base = (
            f"SN{self.netuid} {self.name} score={self.score:.4f} "
            f"7D={self.change_7d:.2f} 1D={self.change_1d:.2f} 1H={self.change_1h:.2f} "
            f"liq={self.liquidity_tao:.2f} flow7d={self.flow_7d:.2f} emission={self.emission:.2f} dd={self.drawdown:.2f}"
        )
        if self.ml_prob_up is not None and self.ml_return_pred is not None:
            return base + f" ml_p_up={self.ml_prob_up:.3f} ml_ret24={self.ml_return_pred:.5f}"
        return base
