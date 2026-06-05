"""Elite trader işlemlerinden örüntü madenciliği — hamle kopyası değil."""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from markets.wallets import WalletTrade


def _bucket_price(p: float) -> str:
    i = min(9, max(0, int(p * 10)))
    lo = i / 10
    hi = (i + 1) / 10
    return f"{lo:.1f}-{hi:.1f}"


def _market_theme(title: str) -> str:
    q = (title or "").lower()
    if any(k in q for k in ("bitcoin", "btc", "ethereum", "eth", "crypto", "solana")):
        return "crypto"
    if any(k in q for k in (" vs ", " vs.", "spread", "o/u", "over/under", "ufc", "nba", "nfl")):
        return "sports"
    if any(k in q for k in ("trump", "biden", "election", "president", "congress")):
        return "politics"
    return "other"


@dataclass
class ElitePatterns:
    """Öğrenilen örüntü özeti."""
    wallets_analyzed: int = 0
    trades_analyzed: int = 0
    price_bucket_wr: dict[str, float] = field(default_factory=dict)
    price_bucket_n: dict[str, int] = field(default_factory=dict)
    theme_wr: dict[str, float] = field(default_factory=dict)
    theme_n: dict[str, int] = field(default_factory=dict)
    side_yes_rate: float = 0.5
    median_stake_usd: float = 100.0
    median_hold_hours: float = 6.0
    early_close_rate: float = 0.0
    momentum_align_rate: float = 0.5
    preferred_hours_left: tuple[float, float] = (2.0, 48.0)
    max_spread_p90: float = 0.05
    avg_edge_proxy: float = 0.08
    rules_tr: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "wallets_analyzed": self.wallets_analyzed,
            "trades_analyzed": self.trades_analyzed,
            "price_bucket_wr": dict(self.price_bucket_wr),
            "theme_wr": dict(self.theme_wr),
            "side_yes_rate": self.side_yes_rate,
            "median_stake_usd": self.median_stake_usd,
            "median_hold_hours": self.median_hold_hours,
            "early_close_rate": self.early_close_rate,
            "rules_tr": list(self.rules_tr),
        }


@dataclass
class _OpenLeg:
    wallet: str
    market_id: str
    side: str
    price: float
    stake: float
    opened_at: datetime
    title: str = ""


def mine_patterns(
    trades: Iterable[WalletTrade],
    outcomes: dict[str, bool],
    *,
    market_titles: dict[str, str] | None = None,
) -> ElitePatterns:
    """Açık/kapanış eşleştirerek elite davranış örüntüleri."""
    market_titles = market_titles or {}
    opens: dict[tuple[str, str, str], _OpenLeg] = {}
    bucket_wins: dict[str, list[int]] = defaultdict(list)
    theme_wins: dict[str, list[int]] = defaultdict(list)
    stakes: list[float] = []
    hold_hours: list[float] = []
    yes_opens = 0
    total_opens = 0
    early_closes = 0
    closed_with_open = 0

    sorted_trades = sorted(trades, key=lambda t: t.timestamp)

    for t in sorted_trades:
        key = (t.wallet, t.market_id, t.side)
        if t.direction == "open":
            opens[key] = _OpenLeg(
                wallet=t.wallet,
                market_id=t.market_id,
                side=t.side,
                price=t.price,
                stake=t.size_usd,
                opened_at=t.timestamp,
                title=market_titles.get(t.market_id, ""),
            )
            total_opens += 1
            if t.side == "YES":
                yes_opens += 1
            stakes.append(t.size_usd)
            continue

        leg = opens.pop(key, None)
        if leg is None:
            continue
        closed_with_open += 1
        hours = (t.timestamp - leg.opened_at).total_seconds() / 3600.0
        hold_hours.append(max(0.01, hours))

        mid = t.market_id
        resolved = outcomes.get(mid)
        if resolved is not None and hours < 24:
            early_closes += 1

        if mid in outcomes:
            won = (leg.side == "YES") == outcomes[mid]
        else:
            # Kapatma P&L proxy
            if leg.side == "YES":
                won = t.price > leg.price
            else:
                won = t.price < leg.price

        b = _bucket_price(leg.price)
        bucket_wins[b].append(1 if won else 0)
        title = leg.title or market_titles.get(mid, "")
        th = _market_theme(title)
        theme_wins[th].append(1 if won else 0)

    ep = ElitePatterns()
    ep.trades_analyzed = len(sorted_trades)
    ep.wallets_analyzed = len({t.wallet for t in sorted_trades})

    for b, vals in bucket_wins.items():
        if len(vals) >= 5:
            ep.price_bucket_wr[b] = sum(vals) / len(vals)
            ep.price_bucket_n[b] = len(vals)

    for th, vals in theme_wins.items():
        if len(vals) >= 5:
            ep.theme_wr[th] = sum(vals) / len(vals)
            ep.theme_n[th] = len(vals)

    if total_opens:
        ep.side_yes_rate = yes_opens / total_opens
    if stakes:
        ep.median_stake_usd = float(statistics.median(stakes))
    if hold_hours:
        ep.median_hold_hours = float(statistics.median(hold_hours))
        ep.preferred_hours_left = (
            max(1.0, statistics.quantiles(hold_hours, n=4)[0]),
            min(72.0, statistics.quantiles(hold_hours, n=4)[2]),
        )
    if closed_with_open:
        ep.early_close_rate = early_closes / closed_with_open

    # Kurallar (Türkçe özet — formül motoru için)
    best_buckets = sorted(ep.price_bucket_wr.items(), key=lambda x: -x[1])[:3]
    for b, wr in best_buckets:
        ep.rules_tr.append(f"Fiyat {b} bandında elite WR≈{wr:.0%} (n={ep.price_bucket_n.get(b,0)})")
    best_themes = sorted(ep.theme_wr.items(), key=lambda x: -x[1])[:3]
    for th, wr in best_themes:
        ep.rules_tr.append(f"Tema {th}: elite WR≈{wr:.0%}")
    ep.rules_tr.append(
        f"Medyan tutma ~{ep.median_hold_hours:.1f}h; erken çıkış oranı ~{ep.early_close_rate:.0%}"
    )
    return ep
