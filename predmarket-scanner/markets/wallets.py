"""On-chain wallet activity fetcher (read-only).

Polymarket trade'leri Polygon zincirinde public. Bu modül "smart money tracking"
yapmak için gerekli iskeleti verir:

  - Subgraph query (önerilen production veri kaynağı): https://api.thegraph.com/subgraphs/name/polymarket/matic-markets
  - Veya Dune SQL (history için)
  - Veya CLOB activity endpoint (yakın anlık)

Bu repo'da SADECE veri tiplerini ve normalize edici fonksiyonları tanımlıyoruz.
Gerçek subgraph entegrasyonunu (sorgu yazma, rate-limit handling, pagination)
implement etmek senin işin — public veri olduğu için meşrudur.

UYARI: "Whale copy trading" tekniği kripto pump-dump için de kullanılır. Sadece
prediction market gibi PUBLIC TRADES + DEEP ORDER BOOK olan piyasalarda anlamlı.
Düşük likiditeli token'lara uygulanırsa front-run kurbanı olursun.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class WalletTrade:
    wallet: str
    market_id: str
    side: str                   # "YES" | "NO"
    price: float                # giriş veya çıkış fiyatı
    size_usd: float
    direction: str              # "open" | "close"
    timestamp: datetime
    tx_hash: Optional[str] = None


@dataclass
class WalletStats:
    wallet: str
    trade_count: int
    win_count: int
    loss_count: int
    total_profit_usd: float
    total_volume_usd: float

    @property
    def win_rate(self) -> float:
        resolved = self.win_count + self.loss_count
        return self.win_count / resolved if resolved else 0.0

    @property
    def roi(self) -> float:
        return self.total_profit_usd / self.total_volume_usd if self.total_volume_usd else 0.0


def aggregate_stats(trades: list[WalletTrade], outcomes: dict[str, bool]) -> dict[str, WalletStats]:
    """Trade listesi + market_id → resolved_yes haritası verildiğinde wallet'ları özetle.

    Bu fonksiyon FETCHER DEĞİL — sen subgraph/Dune'dan verileri çekip elinde
    `trades` listesi olunca buraya yolla.
    """
    agg: dict[str, WalletStats] = {}
    pos: dict[tuple[str, str, str], list[WalletTrade]] = {}  # (wallet, market, side) → trade list

    for t in trades:
        key = (t.wallet, t.market_id, t.side)
        pos.setdefault(key, []).append(t)

    for (wallet, mid, side), legs in pos.items():
        s = agg.setdefault(wallet, WalletStats(wallet=wallet, trade_count=0, win_count=0,
                                               loss_count=0, total_profit_usd=0.0,
                                               total_volume_usd=0.0))
        opens = [l for l in legs if l.direction == "open"]
        closes = [l for l in legs if l.direction == "close"]
        cost = sum(l.size_usd for l in opens)
        proceeds = sum(l.size_usd for l in closes)
        s.total_volume_usd += cost
        s.trade_count += 1

        if mid in outcomes:
            # Settled at resolution
            won = (side == "YES") == outcomes[mid]
            settle_value = sum(l.size_usd / max(1e-6, l.price) for l in opens) if won else 0.0
            pnl = (proceeds + settle_value) - cost
        else:
            pnl = proceeds - cost  # not yet settled; only realized via close

        s.total_profit_usd += pnl
        if pnl > 0:
            s.win_count += 1
        elif pnl < 0:
            s.loss_count += 1

    return agg
