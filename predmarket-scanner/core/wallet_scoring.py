"""Smart-money ranking — tweet 3'ün "47 wallet bul" mantığı + Wilson alt sınırı.

İş akışı:
  1. Son 90 günün tüm trade'lerini subgraph'tan çek (sen yazacaksın).
  2. `aggregate_stats` ile wallet özetlerini çıkar.
  3. `rank_wallets` ile filtre + Wilson alt sınırına göre sırala.

ÖNEMLİ — naive ranking neden çalışmıyor:
  - 10 trade'de %70 WR rastgele de olabilir (binom(10, 0.5) → P(≥7) = %17)
  - Sentetik 100 günlük testte: naive ranking → out-of-sample precision %0
  - Wilson lower bound: gerçek WR'ın %95 güvenle EN AZ ne olduğunu söyler
  - "100 trade, %70 WR" wallet > "10 trade, %80 WR" wallet (sample > gürültü)

Tweet 'top 20 made more than bottom 13,000' diyor; bu Pareto plausible AMA
"şu an top" ≠ "yarın da top". Wilson alt sınırı bu ayırımı yapar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from markets.wallets import WalletStats


def wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    """%95 güven aralığının alt sınırı — küçük sample'da naive WR'dan düşük olur."""
    if total <= 0:
        return 0.0
    p = wins / total
    n = total
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


@dataclass(frozen=True)
class RankingCriteria:
    min_trades: int = 100
    min_win_rate: float = 0.70
    min_volume_usd: float = 1_000.0
    min_roi: float = 0.10
    min_wilson_wr: float = 0.55   # Wilson alt sınırı eşiği — küçük sample'ı eler
    top_n: int = 50
    rank_by: str = "wilson"        # "wilson" | "profit" | "roi"


def rank_wallets(stats: Iterable[WalletStats], criteria: RankingCriteria) -> list[WalletStats]:
    pool = []
    for s in stats:
        if s.trade_count < criteria.min_trades:
            continue
        if s.win_rate < criteria.min_win_rate:
            continue
        if s.total_volume_usd < criteria.min_volume_usd:
            continue
        if s.roi < criteria.min_roi:
            continue
        # Wilson alt sınırı kontrolü
        resolved = s.win_count + s.loss_count
        if resolved > 0:
            wlb = wilson_lower_bound(s.win_count, resolved)
            if wlb < criteria.min_wilson_wr:
                continue
        pool.append(s)

    if criteria.rank_by == "wilson":
        pool.sort(
            key=lambda s: wilson_lower_bound(s.win_count, s.win_count + s.loss_count),
            reverse=True,
        )
    elif criteria.rank_by == "roi":
        pool.sort(key=lambda s: s.roi, reverse=True)
    else:
        pool.sort(key=lambda s: s.total_profit_usd, reverse=True)
    return pool[: criteria.top_n]


def pareto_concentration(stats: list[WalletStats], top_k: int = 20) -> float:
    """Top-k wallet'ın toplam kar içindeki payı. Tweet'in 'top 20 > bottom 13k' iddiası
    bu fonksiyonun çıktısının ~0.9+ olmasıyla teyit edilir.
    """
    total = sum(max(0.0, s.total_profit_usd) for s in stats)
    if total <= 0:
        return 0.0
    sorted_stats = sorted(stats, key=lambda s: s.total_profit_usd, reverse=True)
    top = sum(max(0.0, s.total_profit_usd) for s in sorted_stats[:top_k])
    return top / total
