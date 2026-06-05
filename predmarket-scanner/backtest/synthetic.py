"""Synthetic prediction market data generator — ground truth bilinen evren.

Amaç: Network'e bağlanmadan, scanner/ranking/exit mantığının gerçekten kazananı
seçip seçmediğini test edebilmek.

Model:
  - N piyasa, her biri 1-30 gün arasında bir end_date'e sahip
  - Her piyasanın bilinen bir TRUE probability (β-dağılımdan)
  - Market price zaman içinde true prob'a doğru sürüklenir (noise + drift)
  - W cüzdan; bunların α kadarı "edge'li" (true prob'a daha yakın tahmin yapar),
    geri kalanı gürültü (random)
  - Her tick'te bazı cüzdanlar trade açar (edge'liler doğru tarafa, diğerleri rastgele)
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from markets.wallets import WalletTrade


@dataclass
class SyntheticMarket:
    market_id: str
    question: str
    category: str
    true_prob: float
    end_date: datetime
    start_date: datetime
    price_path: list[tuple[datetime, float]] = field(default_factory=list)
    resolved_yes: Optional[bool] = None  # filled after end_date


@dataclass
class SyntheticUniverse:
    markets: list[SyntheticMarket]
    trades: list[WalletTrade]
    # wallet -> true edge (model accuracy advantage)
    wallet_edge: dict[str, float] = field(default_factory=dict)


def _beta_sample(a: float, b: float) -> float:
    return random.betavariate(a, b)


def generate(
    n_markets: int = 500,
    n_wallets: int = 1000,
    pct_edge_wallets: float = 0.08,
    horizon_days: int = 100,
    ticks_per_day: int = 8,
    seed: int = 42,
) -> SyntheticUniverse:
    """100 günlük sentetik evren üret."""
    rng = random.Random(seed)
    random.seed(seed)

    now0 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end_window = now0 + timedelta(days=horizon_days)
    categories = ["crypto", "politics", "sports", "weather"]

    markets: list[SyntheticMarket] = []
    for i in range(n_markets):
        true_p = _beta_sample(2, 2)  # ~uniform on (0,1) with slight center bias
        start = now0 + timedelta(days=rng.uniform(0, horizon_days - 5))
        end = start + timedelta(days=rng.uniform(1, 30))
        if end > end_window:
            end = end_window
        markets.append(SyntheticMarket(
            market_id=f"m{i:04d}",
            question=f"Synthetic question {i}",
            category=rng.choice(categories),
            true_prob=true_p,
            end_date=end,
            start_date=start,
        ))

    # Edge wallets and noise wallets — edge wallets trade more frequently (realistic)
    n_edge = max(1, int(n_wallets * pct_edge_wallets))
    edge_wallets = {f"0xedge_{i:04d}": rng.uniform(0.08, 0.20) for i in range(n_edge)}
    noise_wallets = {f"0xnoise_{i:04d}": 0.0 for i in range(n_wallets - n_edge)}
    wallet_edge = {**edge_wallets, **noise_wallets}
    all_wallets = list(wallet_edge.keys())

    trades: list[WalletTrade] = []

    # Generate price paths AND trades simultaneously
    for m in markets:
        total_seconds = (m.end_date - m.start_date).total_seconds()
        if total_seconds <= 0:
            continue
        n_ticks = max(2, int(total_seconds / 86400 * ticks_per_day))

        # Price path: drift from random init toward true_prob; OU-style with shrinking noise
        path = []
        price = rng.uniform(0.2, 0.8)
        for k in range(n_ticks):
            t_frac = k / max(1, n_ticks - 1)
            ts = m.start_date + timedelta(seconds=t_frac * total_seconds)
            # mean-reversion toward true_prob; noise shrinks as resolution approaches
            noise_scale = 0.05 * (1 - t_frac) + 0.005
            price = 0.85 * price + 0.15 * m.true_prob + rng.gauss(0, noise_scale)
            price = max(0.02, min(0.98, price))
            path.append((ts, price))
        m.price_path = path

        # Trades at each tick: edge wallets trade more often (skill = activity proxy)
        edge_list = list(edge_wallets.keys())
        noise_list = list(noise_wallets.keys())
        for ts, price in path[:-1]:
            n_edge_traders = rng.randint(0, 2)
            n_noise_traders = rng.randint(0, 4)
            traders = ([rng.choice(edge_list) for _ in range(n_edge_traders)] +
                       [rng.choice(noise_list) for _ in range(n_noise_traders)])
            for w in traders:
                edge = wallet_edge[w]
                # Edge wallet "knows" probability is roughly true_prob ± noise
                if edge > 0:
                    perceived = m.true_prob + rng.gauss(0, max(0.01, 0.15 - edge))
                else:
                    perceived = rng.uniform(0, 1)  # noise wallet, no skill
                perceived = max(0.01, min(0.99, perceived))
                # Trade direction: if perceived > price, BUY YES; else BUY NO
                side = "YES" if perceived > price else "NO"
                trade_price = price if side == "YES" else (1 - price)
                size = rng.uniform(20, 500)
                trades.append(WalletTrade(
                    wallet=w, market_id=m.market_id, side=side,
                    price=trade_price, size_usd=size, direction="open",
                    timestamp=ts, tx_hash=f"tx_{len(trades):08d}",
                ))

        # Resolve at end
        m.resolved_yes = rng.random() < m.true_prob

        # Close trades at settle price (1.0 if won, 0.0 if lost) — synthetic settlement
        # Generate one "close" event per open for accounting purposes:
        for t in [tt for tt in trades if tt.market_id == m.market_id and tt.direction == "open"]:
            won = (t.side == "YES") == m.resolved_yes
            close_price = 1.0 if won else 0.0
            # Realized USDC = contracts * close_price; contracts = size_usd / entry_price
            contracts = t.size_usd / max(0.01, t.price)
            proceeds = contracts * close_price
            trades.append(WalletTrade(
                wallet=t.wallet, market_id=t.market_id, side=t.side,
                price=close_price, size_usd=proceeds, direction="close",
                timestamp=m.end_date, tx_hash=f"close_{t.tx_hash}",
            ))

    return SyntheticUniverse(markets=markets, trades=trades, wallet_edge=wallet_edge)
