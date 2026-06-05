"""Whale copy tracking — followed wallet'lar yeni pozisyon açtıkça sinyal üret.

Tweet 3'ün "10 trade/gün, mostly skipped" iddiası: tracker yeni entries'i
yakalar, **consensus** ve **market filter**'dan geçirir, eşik üstünü tetikler.

Bu modül state-machine:
  - watch_list = ranked top-N wallet adresleri
  - last_seen_block = polling cursor
  - new_entries(period) → yeni "open" trade'leri döndürür
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Optional

from markets.wallets import WalletTrade


# Üretimde bunu subgraph polling fonksiyonuyla doldur.
TradeFetcher = Callable[[Iterable[str], datetime], Iterable[WalletTrade]]


@dataclass
class WhaleEntry:
    wallet: str
    market_id: str
    side: str
    price: float
    size_usd: float
    seen_at: datetime
    raw: WalletTrade


@dataclass
class WhaleTracker:
    watch_list: set[str]
    fetcher: TradeFetcher
    lookback: timedelta = timedelta(minutes=5)
    seen: set[str] = field(default_factory=set)        # tx_hash dedupe

    def poll(self, now: Optional[datetime] = None) -> list[WhaleEntry]:
        now = now or datetime.now(timezone.utc)
        since = now - self.lookback
        out: list[WhaleEntry] = []
        for t in self.fetcher(self.watch_list, since):
            if t.direction != "open":
                continue
            if t.tx_hash and t.tx_hash in self.seen:
                continue
            if t.tx_hash:
                self.seen.add(t.tx_hash)
            out.append(WhaleEntry(
                wallet=t.wallet, market_id=t.market_id, side=t.side,
                price=t.price, size_usd=t.size_usd, seen_at=t.timestamp, raw=t,
            ))
        return out
