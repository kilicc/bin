"""Parameter sweep — sinyal ağırlıkları ve eşikler için grid search.

UYARI: Aynı dataset'te hem optimize hem rapor → in-sample overfitting.
Doğru kullanım walk-forward: train_period'da optimize, test_period'da metrik.
`run_walk_forward` bunu yapar.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from backtest.engine import (
    BacktestConfig, BacktestEstimator, BacktestReport,
    market_baseline, momentum_estimator, run_backtest,
)
from backtest.synthetic import SyntheticUniverse


@dataclass
class GridPoint:
    edge_threshold: float
    kelly_fraction: float
    min_confidence: float
    report: BacktestReport

    def score(self) -> float:
        """Optimizasyon hedefi: yüksek Sharpe ama trade count ve PnL'i dikkate al."""
        r = self.report
        if r.n_trades < 10:
            return -1e9
        # Bileşik skor: Sharpe + PnL/$1000 normalize
        s = r.sharpe_annual if r.sharpe_annual == r.sharpe_annual else 0.0
        return s + (r.total_pnl / 1000.0)


def grid_search(
    universe: SyntheticUniverse,
    estimator: BacktestEstimator,
    edge_thresholds: Iterable[float] = (0.03, 0.05, 0.07, 0.10),
    kelly_fractions: Iterable[float] = (0.10, 0.25, 0.50),
    min_confidences: Iterable[float] = (0.20, 0.30, 0.40, 0.50),
    base_cfg: BacktestConfig | None = None,
) -> list[GridPoint]:
    base = base_cfg or BacktestConfig()
    results: list[GridPoint] = []
    for et, kf, mc in itertools.product(edge_thresholds, kelly_fractions, min_confidences):
        cfg = replace(base, edge_threshold=et, kelly_fraction=kf, min_confidence=mc)
        rep = run_backtest(universe, estimator, cfg)
        results.append(GridPoint(et, kf, mc, rep))
    results.sort(key=lambda g: g.score(), reverse=True)
    return results
