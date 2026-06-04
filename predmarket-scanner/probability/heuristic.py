"""Heuristic baseline estimator.

Bu estimator KAR ETMEZ. Amacı:
  1. Scanner'ın uçtan uca çalışması için bir baseline sağlamak.
  2. Daha sofistike modelleri kıyaslayacağın "null" baseline olmak.

Mantık:
  - Yes tarafının true_prob'unu market fiyatına eşitle (yani edge = 0 → sinyal yok)
  - Confidence: market hacmi büyüdükçe artar (kalabalık daha iyi bilir varsayımı)

Bunu kazanan bir modelle değiştirmek senin işin. Brier skoru ile kıyasla.
"""
from __future__ import annotations

import math
from typing import Optional

from markets.base import Market

from .base import ProbabilityEstimate, ProbabilityEstimator


class HeuristicEstimator(ProbabilityEstimator):
    name = "heuristic_baseline"

    def estimate(self, market: Market) -> Optional[ProbabilityEstimate]:
        p = market.yes_price
        if p is None:
            return None

        # Confidence = 1 - exp(-vol/10k); $10k hacimde ~63% güven
        vol = max(0.0, market.volume_24h)
        confidence = 1.0 - math.exp(-vol / 10_000.0)

        return ProbabilityEstimate(
            market_id=market.market_id,
            true_prob=p,
            confidence=confidence,
            rationale=f"baseline=market_price; vol24h=${vol:,.0f}",
            source=self.name,
        )
