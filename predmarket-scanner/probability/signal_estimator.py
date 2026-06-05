"""SignalEstimator — `core/signals.py` baseline'larından gelen bias'ı
market fiyatına uygulayan ProbabilityEstimator.

Bu, tweet'in "CLOB momentum + spot distance + time-weighted + day-of-week"
tavsiyesinin uçtan uca işleyen halidir. Asıl üretim modelini bunun üzerine kur:
  - per-category override (spor için ELO, kripto için BS implied prob, vs.)
  - parametre kalibrasyonu (signals.composite_bias.weights)
"""
from __future__ import annotations

from typing import Optional

from core.signals import SignalContext, composite_bias
from markets.base import Market

from .base import ProbabilityEstimate, ProbabilityEstimator


class SignalEstimator(ProbabilityEstimator):
    name = "signal_baseline"

    def __init__(self, weights: Optional[dict[str, float]] = None):
        self.weights = weights

    def estimate(self, market: Market) -> Optional[ProbabilityEstimate]:
        p = market.yes_price
        if p is None:
            return None

        # Tick history bu repoda fetch edilmiyor (Gamma API metadata-only).
        # Live entegrasyonda CLOB websocket'inden doldur. Şimdilik boş.
        ctx = SignalContext(
            market_id=market.market_id,
            market_yes_price=p,
            end_date=market.end_date,
            underlying_spot=None,
            strike=None,
            tick_history=(),
        )
        bias = composite_bias(ctx, category=market.category, weights=self.weights)
        adjusted = max(0.01, min(0.99, p + bias))
        return ProbabilityEstimate(
            market_id=market.market_id,
            true_prob=adjusted,
            confidence=0.3,  # baseline; kalibre edilince yüksel
            rationale=f"market={p:.3f} + bias={bias:+.3f}",
            source=self.name,
        )
