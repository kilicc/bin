"""Backtest metrikleri — Brier, log-loss, hit rate, kalibrasyon, Sharpe.

Yararlı kabul kuralları:
  - Brier skoru: 0 = mükemmel; 0.25 = random binary; düşük = iyi
  - Log-loss: 0 = mükemmel; 0.693 = random; düşük = iyi
  - Hit rate: prob > 0.5 olan tahminlerin doğruluğu
  - Calibration: olasılık bucket'larında "tahmin = gerçek frekans" mı?
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Iterable, Sequence


@dataclass
class Prediction:
    predicted_p: float       # tahmin edilen P(YES)
    actual_yes: bool         # gerçek sonuç
    market_id: str = ""


def brier_score(preds: Sequence[Prediction]) -> float:
    if not preds:
        return float("nan")
    return mean((p.predicted_p - (1.0 if p.actual_yes else 0.0)) ** 2 for p in preds)


def log_loss(preds: Sequence[Prediction], eps: float = 1e-9) -> float:
    if not preds:
        return float("nan")
    total = 0.0
    for p in preds:
        q = max(eps, min(1 - eps, p.predicted_p))
        total += -(math.log(q) if p.actual_yes else math.log(1 - q))
    return total / len(preds)


def hit_rate(preds: Sequence[Prediction], threshold: float = 0.5) -> float:
    """prob > threshold ise YES tahmin sayılır."""
    if not preds:
        return float("nan")
    hits = sum(1 for p in preds if (p.predicted_p > threshold) == p.actual_yes)
    return hits / len(preds)


def calibration_curve(preds: Sequence[Prediction], n_bins: int = 10) -> list[tuple[float, float, int]]:
    """Bucket'larda (mean predicted, mean actual, count) döndürür."""
    bins: list[list[Prediction]] = [[] for _ in range(n_bins)]
    for p in preds:
        idx = min(n_bins - 1, int(p.predicted_p * n_bins))
        bins[idx].append(p)
    out = []
    for i, b in enumerate(bins):
        if not b:
            out.append(((i + 0.5) / n_bins, float("nan"), 0))
            continue
        mp = mean(x.predicted_p for x in b)
        ma = mean(1.0 if x.actual_yes else 0.0 for x in b)
        out.append((mp, ma, len(b)))
    return out


def sharpe(returns: Sequence[float], periods_per_year: int = 252) -> float:
    """Trade başına dönüş listesi → annualized Sharpe."""
    if len(returns) < 2:
        return float("nan")
    mu = mean(returns)
    sd = pstdev(returns)
    if sd <= 0:
        return float("nan")
    return (mu / sd) * math.sqrt(periods_per_year)


@dataclass
class BacktestReport:
    n_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    sharpe_annual: float
    brier: float
    log_loss_: float
    hit_rate_: float
    starting_balance: float
    ending_balance: float

    def pretty(self) -> str:
        return (
            f"trades={self.n_trades}  WR={self.win_rate:.2%}  "
            f"start=${self.starting_balance:,.0f} → end=${self.ending_balance:,.0f}  "
            f"PnL=${self.total_pnl:+,.0f}  avg=${self.avg_pnl:+.2f}  "
            f"Sharpe={self.sharpe_annual:.2f}  Brier={self.brier:.4f}  "
            f"LogLoss={self.log_loss_:.4f}  Hit={self.hit_rate_:.2%}"
        )
