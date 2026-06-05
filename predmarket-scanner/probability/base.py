"""Probability estimator interface.

Bu projenin asıl alfa noktası burası. Bütün stratejiler aynı şekilde edge
hesaplar; farklı olan, "true probability"yi nasıl üretirsin sorusudur.

ProbabilityEstimator implementasyonların:
  - LLM-based (örnek olarak Claude estimator; baseline'dan iyi DEĞİL)
  - Heuristic (time-decay + price momentum; basit baseline)
  - Domain-specific (ileride senin yazacağın; gerçek alfa burada)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from markets.base import Market


@dataclass
class ProbabilityEstimate:
    """Bir piyasa için 'true probability' tahmini ve metadata."""
    market_id: str
    true_prob: float           # [0,1], YES tarafının olasılığı
    confidence: float = 0.5    # [0,1] — modelin kendine güveni; düşükse Kelly'yi kıs
    rationale: str = ""        # debug/log için kısa açıklama
    source: str = "unknown"    # estimator adı

    def __post_init__(self) -> None:
        # Defansif klip — modeller ara sıra (-eps) veya (1+eps) döndürür
        self.true_prob = max(0.001, min(0.999, float(self.true_prob)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


class ProbabilityEstimator(ABC):
    """Tüm tahminleyiciler bunu implement eder."""

    name: str = "base"

    @abstractmethod
    def estimate(self, market: Market) -> Optional[ProbabilityEstimate]:
        """Tahmin üret; üretemezsen None dön (filtrelenir)."""
        ...

    def supports(self, market: Market) -> bool:
        """Bu estimator bu market'i fiyatlamayı deniyor mu?"""
        return True
