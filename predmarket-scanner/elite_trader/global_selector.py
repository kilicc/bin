"""Çok-kategori Polymarket leaderboard — global elite seçimi."""
from __future__ import annotations

from dataclasses import dataclass, field

from elite_trader.leaderboard import LeaderboardTrader, fetch_leaderboard, iter_categories


def _is_likely_bot(t: LeaderboardTrader) -> bool:
    if t.volume_usd > 5_000_000 and t.pnl_usd < t.volume_usd * 0.02:
        return True
    if t.volume_usd > 20_000_000 and t.pnl_usd < 500_000:
        return True
    return False


@dataclass
class GlobalEliteWallet:
    wallet: str
    username: str
    pnl_usd: float
    volume_usd: float
    categories: list[str] = field(default_factory=list)
    best_rank: int = 999
    rank_score: float = 0.0


def select_global_elite(
    *,
    per_category: int = 25,
    max_wallets: int = 40,
    time_period: str = "MONTH",
) -> list[GlobalEliteWallet]:
    """OVERALL + CRYPTO + POLITICS + SPORTS birleşik sıralama."""
    cats = ("OVERALL", "CRYPTO", "POLITICS", "SPORTS")
    by_wallet: dict[str, GlobalEliteWallet] = {}

    for cat in cats:
        if cat not in set(iter_categories()):
            continue
        try:
            board = fetch_leaderboard(
                category=cat, time_period=time_period, limit=per_category
            )
        except Exception:
            continue
        for t in board:
            if t.pnl_usd <= 0 or _is_likely_bot(t):
                continue
            w = t.wallet.lower()
            rank_pts = max(0, per_category - t.rank) / per_category
            pnl_pts = min(1.0, t.pnl_usd / 500_000)
            score = rank_pts * 0.4 + pnl_pts * 0.6
            if w not in by_wallet:
                by_wallet[w] = GlobalEliteWallet(
                    wallet=w,
                    username=t.username,
                    pnl_usd=t.pnl_usd,
                    volume_usd=t.volume_usd,
                    categories=[cat],
                    best_rank=t.rank,
                    rank_score=score,
                )
            else:
                g = by_wallet[w]
                g.categories.append(cat)
                g.pnl_usd = max(g.pnl_usd, t.pnl_usd)
                g.volume_usd = max(g.volume_usd, t.volume_usd)
                g.best_rank = min(g.best_rank, t.rank)
                g.rank_score = max(g.rank_score, score)

    ranked = sorted(by_wallet.values(), key=lambda x: x.rank_score, reverse=True)
    return ranked[:max_wallets]


def to_leaderboard_traders(elites: list[GlobalEliteWallet]) -> list[LeaderboardTrader]:
    return [
        LeaderboardTrader(
            rank=e.best_rank,
            wallet=e.wallet,
            username=e.username,
            volume_usd=e.volume_usd,
            pnl_usd=e.pnl_usd,
            verified=False,
        )
        for e in elites
    ]
