"""Order state reconciler — silent fill bug'a karşı.

İkinci tweet'in tavsiyesi: timeout'tan sonra fill kabul etme; her 30s
exchange state ile local state karşılaştır.

Bu repo paper-mode olduğu için pattern'i somut hale getirmek amacıyla bir
"sahte" exchange fonksiyonu tanımladık. Live entegrasyonda bunu gerçek bir
CLOB client'ıyla değiştir.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event, Thread
from typing import Callable, Iterable

from portfolio.paper import PaperBook, PaperPosition


@dataclass
class ExchangePosition:
    market_id: str
    side: str
    contracts: float
    avg_price: float


# Live entegrasyonda bunu gerçek API call'ı yapan bir fonksiyonla değiştir.
ExchangeFetcher = Callable[[], Iterable[ExchangePosition]]


def diff_positions(
    local: Iterable[PaperPosition],
    remote: Iterable[ExchangePosition],
    tol: float = 1e-3,
) -> dict:
    """Local ve remote pozisyon kümeleri arasında fark.

    Returns:
      {
        "missing_locally":  [...remote'ta var, local'de yok...],
        "missing_remotely": [...local'de var, remote'ta yok...],
        "size_mismatch":    [(local, remote, delta), ...],
      }
    """
    by_key_local = {(p.market_id, p.side): p for p in local}
    by_key_remote = {(p.market_id, p.side): p for p in remote}

    missing_locally = [
        by_key_remote[k] for k in by_key_remote.keys() - by_key_local.keys()
    ]
    missing_remotely = [
        by_key_local[k] for k in by_key_local.keys() - by_key_remote.keys()
    ]

    size_mismatch = []
    for k in by_key_local.keys() & by_key_remote.keys():
        l = by_key_local[k]
        r = by_key_remote[k]
        if abs(l.contracts - r.contracts) > tol:
            size_mismatch.append((l, r, r.contracts - l.contracts))

    return {
        "missing_locally": missing_locally,
        "missing_remotely": missing_remotely,
        "size_mismatch": size_mismatch,
    }


class Reconciler:
    """Arka planda her N saniyede bir reconcile çalıştırır."""

    def __init__(self, book: PaperBook, fetch_remote: ExchangeFetcher, interval_sec: float = 30.0):
        self.book = book
        self.fetch_remote = fetch_remote
        self.interval = interval_sec
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread:
            return
        self._thread = Thread(target=self._run, name="reconciler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as e:
                print(f"[reconciler] {e}")
            self._stop.wait(self.interval)

    def run_once(self) -> dict:
        local = self.book.open_positions()
        remote = list(self.fetch_remote())
        return diff_positions(local, remote)
