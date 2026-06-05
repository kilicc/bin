"""Main scanner loop.

İş akışı:
  1. Aktif piyasaları çek (Polymarket)
  2. Likidite + fiyat aralığı filtresinden geçir
  3. ProbabilityEstimator ile true_prob tahmin et
  4. EdgeSignal hesapla
  5. Eşik aşan sinyalleri sırala, paper book'a gir, logla
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Optional

from rich.console import Console
from rich.table import Table

from config import settings
from markets.base import Market
from markets.polymarket import PolymarketClient
from portfolio.paper import PaperBook
from probability.base import ProbabilityEstimator

from .edge import EdgeSignal, compute_signal


@dataclass
class ScanResult:
    scanned: int
    eligible: int
    signals: list[EdgeSignal]
    errors: int


class Scanner:
    def __init__(
        self,
        estimator: ProbabilityEstimator,
        book: PaperBook,
        console: Optional[Console] = None,
    ):
        self.estimator = estimator
        self.book = book
        self.console = console or Console()

    # --- Filters -------------------------------------------------------------

    def _eligible(self, m: Market) -> bool:
        p = m.yes_price
        if p is None:
            return False
        if not (settings.min_price <= p <= settings.max_price):
            return False
        if m.volume_24h < settings.min_volume_24h:
            return False
        # Sadece binary piyasaları al — multi-outcome ileride
        if len(m.outcomes) != 2:
            return False
        return True

    # --- One pass ------------------------------------------------------------

    def scan_once(self, markets: Iterable[Market]) -> ScanResult:
        scanned = eligible = errors = 0
        signals: list[EdgeSignal] = []

        for m in markets:
            scanned += 1
            if not self._eligible(m):
                continue
            eligible += 1
            try:
                est = self.estimator.estimate(m)
                if est is None:
                    continue
                sig = compute_signal(
                    m,
                    est,
                    edge_threshold=settings.edge_threshold,
                    kelly_multiplier=settings.kelly_fraction,
                )
                if sig is not None:
                    signals.append(sig)
            except Exception as e:
                errors += 1
                self.console.print(f"[red]error[/red] {m.market_id}: {e}")

        signals.sort(key=lambda s: s.expected_value, reverse=True)
        return ScanResult(scanned=scanned, eligible=eligible, signals=signals, errors=errors)

    # --- Continuous loop -----------------------------------------------------

    def run_forever(self, fetch_limit: int = 500) -> None:
        while True:
            with PolymarketClient(base_url=settings.polymarket_base) as poly:
                markets = list(poly.iter_active_markets(page_size=100, max_pages=fetch_limit // 100))
            result = self.scan_once(markets)
            self._render(result)
            self._place_paper_orders(result.signals)
            time.sleep(settings.scan_interval_sec)

    # --- Reporting -----------------------------------------------------------

    def _render(self, result: ScanResult) -> None:
        c = self.console
        c.rule(f"scanned={result.scanned}  eligible={result.eligible}  "
               f"signals={len(result.signals)}  errors={result.errors}")
        if not result.signals:
            c.print("[dim]no signals above threshold[/dim]")
            return

        tbl = Table(show_header=True, header_style="bold")
        for col in ("side", "price", "p_true", "edge", "EV/$1", "kelly", "conf", "question"):
            tbl.add_column(col)
        for s in result.signals[:20]:
            tbl.add_row(
                s.side,
                f"{s.market_price:.3f}",
                f"{s.true_prob:.3f}",
                f"{s.edge:+.3f}",
                f"{s.expected_value:+.3f}",
                f"{s.kelly_sized:.2%}",
                f"{s.confidence:.2f}",
                (s.market.question[:60] + "…") if len(s.market.question) > 61 else s.market.question,
            )
        c.print(tbl)

    def _place_paper_orders(self, signals: list[EdgeSignal]) -> None:
        for s in signals:
            self.book.maybe_open(s)
