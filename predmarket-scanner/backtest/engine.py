"""Backtest engine — sentetik (veya gerçek) tarihi veriyi scanner'a replay eder.

İş akışı:
  1. SyntheticUniverse al
  2. Tarihsel sırayla her tick'te:
     - Eligible market'leri seç
     - Estimator'ı sor (TrueProb tahmini)
     - Edge eşiği aşan sinyali Kelly ile boyutlandır
     - Pozisyon aç (fee + slippage uygulanır)
     - Açık pozisyonlar için exit_policy kontrol et
  3. Tüm market'ler çözülünce settlement P&L
  4. BacktestReport üret

Walk-forward: training period boyunca optimize, ondan sonraki test period'da metrik.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from backtest.metrics import (
    BacktestReport, Prediction, brier_score, hit_rate, log_loss, sharpe,
)
from backtest.synthetic import SyntheticMarket, SyntheticUniverse


# Estimator signature for backtest:
#   (market, current_price, history_snapshot) -> (true_prob, confidence)
BacktestEstimator = Callable[[SyntheticMarket, float, list[tuple[datetime, float]]], tuple[float, float]]


# --- Built-in estimators -----------------------------------------------------

def market_baseline(m: SyntheticMarket, price: float, history: list[tuple[datetime, float]]) -> tuple[float, float]:
    """Baseline: true = current market price. Brier'i market-implied seviyede tutar."""
    return price, 0.5


def momentum_estimator(m: SyntheticMarket, price: float, history: list[tuple[datetime, float]]) -> tuple[float, float]:
    """Son N tick eğimiyle market price'a küçük bias ekler."""
    if len(history) < 5:
        return price, 0.2
    recent = [p for _, p in history[-10:]]
    drift = (recent[-1] - recent[0])
    adj = max(-0.1, min(0.1, drift * 0.5))
    return max(0.01, min(0.99, price + adj)), 0.4


def whale_consensus_estimator_factory(
    whale_wallets: set[str],
    trades_by_market_time: dict[str, list],
    confidence: float = 0.6,
    weight: float = 0.15,
) -> BacktestEstimator:
    """Bir piyasada 'edge'li wallet'lar hangi yöne ağırlıkta girmiş — bias üret."""
    def _est(m: SyntheticMarket, price: float, history: list[tuple[datetime, float]]) -> tuple[float, float]:
        whale_trades = [t for t in trades_by_market_time.get(m.market_id, [])
                        if t.wallet in whale_wallets and t.direction == "open"
                        and (not history or t.timestamp <= history[-1][0])]
        if not whale_trades:
            return price, 0.2
        yes_size = sum(t.size_usd for t in whale_trades if t.side == "YES")
        no_size = sum(t.size_usd for t in whale_trades if t.side == "NO")
        total = yes_size + no_size
        if total <= 0:
            return price, 0.2
        whale_p = yes_size / total
        # Blend market price with whale signal
        blended = price * (1 - weight) + whale_p * weight
        return max(0.01, min(0.99, blended)), confidence
    return _est


# --- Engine ------------------------------------------------------------------

@dataclass
class BacktestConfig:
    starting_balance: float = 2_000.0
    edge_threshold: float = 0.06
    kelly_fraction: float = 0.25
    max_position_usd: float = 50.0
    fee_rate: float = 0.02
    slippage: float = 0.01
    min_confidence: float = 0.25


@dataclass
class _OpenPosition:
    market_id: str
    side: str
    entry_price: float
    contracts: float
    stake_usd: float
    predicted_p: float
    opened_at: datetime


def _kelly(p: float, price: float) -> float:
    if not (0 < price < 1):
        return 0.0
    b = (1.0 / price) - 1.0
    q = 1 - p
    return max(0.0, (p * b - q) / b)


def run_backtest(
    universe: SyntheticUniverse,
    estimator: BacktestEstimator,
    cfg: Optional[BacktestConfig] = None,
) -> BacktestReport:
    cfg = cfg or BacktestConfig()
    balance = cfg.starting_balance

    # Build chronological tick stream: each (timestamp, market, price)
    ticks = []
    for m in universe.markets:
        for ts, price in m.price_path:
            ticks.append((ts, m, price))
    ticks.sort(key=lambda x: x[0])

    open_positions: dict[str, _OpenPosition] = {}  # market_id+side -> pos
    closed_trades_pnl: list[float] = []
    predictions: list[Prediction] = []

    # Track price history per market (for estimator)
    history_by_market: dict[str, list[tuple[datetime, float]]] = {}

    for ts, market, price in ticks:
        hist = history_by_market.setdefault(market.market_id, [])
        hist.append((ts, price))

        # Eligibility
        if not (0.05 <= price <= 0.95):
            continue

        # Estimate
        try:
            p_true, conf = estimator(market, price, hist)
        except Exception:
            continue
        if conf < cfg.min_confidence:
            continue

        # Edge
        edge = p_true - price
        if abs(edge) < cfg.edge_threshold:
            continue
        if edge > 0:
            side, entry_price, prob = "YES", price, p_true
        else:
            side, entry_price, prob = "NO", 1.0 - price, 1.0 - p_true

        key = f"{market.market_id}:{side}"
        if key in open_positions:
            continue  # tek pozisyon

        # Sizing
        kf = _kelly(prob, entry_price) * cfg.kelly_fraction * conf
        if kf <= 0:
            continue
        stake = min(balance * kf, cfg.max_position_usd)
        if stake < 1.0 or stake > balance:
            continue

        fill_price = min(0.999, entry_price + cfg.slippage)
        contracts = stake / fill_price
        balance -= stake
        open_positions[key] = _OpenPosition(
            market_id=market.market_id, side=side, entry_price=fill_price,
            contracts=contracts, stake_usd=stake, predicted_p=p_true, opened_at=ts,
        )

    # Settle all open positions at market resolution
    market_by_id = {m.market_id: m for m in universe.markets}
    for key, pos in open_positions.items():
        m = market_by_id.get(pos.market_id)
        if m is None or m.resolved_yes is None:
            balance += pos.stake_usd  # not resolved, refund (rare in synthetic)
            continue
        won = (pos.side == "YES") == m.resolved_yes
        payout = pos.contracts if won else 0.0
        pnl = payout - pos.stake_usd - pos.stake_usd * cfg.fee_rate
        balance += pos.stake_usd + pnl  # restore stake + add/subtract pnl
        closed_trades_pnl.append(pnl / pos.stake_usd)  # ROI per trade
        predictions.append(Prediction(
            predicted_p=pos.predicted_p, actual_yes=m.resolved_yes,
            market_id=pos.market_id,
        ))

    n = len(closed_trades_pnl)
    if n == 0:
        return BacktestReport(
            n_trades=0, win_rate=float("nan"), total_pnl=balance - cfg.starting_balance,
            avg_pnl=float("nan"), sharpe_annual=float("nan"), brier=float("nan"),
            log_loss_=float("nan"), hit_rate_=float("nan"),
            starting_balance=cfg.starting_balance, ending_balance=balance,
        )

    wins = sum(1 for r in closed_trades_pnl if r > 0)
    return BacktestReport(
        n_trades=n,
        win_rate=wins / n,
        total_pnl=balance - cfg.starting_balance,
        avg_pnl=(balance - cfg.starting_balance) / n,
        sharpe_annual=sharpe(closed_trades_pnl, periods_per_year=252),
        brier=brier_score(predictions),
        log_loss_=log_loss(predictions),
        hit_rate_=hit_rate(predictions),
        starting_balance=cfg.starting_balance,
        ending_balance=balance,
    )
