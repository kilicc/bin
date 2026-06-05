"""CLI entry point.

Komutlar:
  python main.py scan-once --estimator heuristic           # tek geçiş, baseline
  python main.py scan-once --estimator claude --limit 50   # Claude estimator (yavaş + ücretli)
  python main.py loop --estimator heuristic                # sonsuz döngü, paper book'a yazar
  python main.py report                                    # paper portföy raporu
  python main.py resolve <market_id> --outcome yes|no      # bir piyasayı manuel kapat
"""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from config import assert_paper_mode, settings
from core.scanner import Scanner
from markets.polymarket import PolymarketClient
from portfolio.paper import PaperBook
from probability.heuristic import HeuristicEstimator
from probability.llm_claude import ClaudeEstimator
from probability.signal_estimator import SignalEstimator

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _make_estimator(name: str):
    name = name.lower()
    if name == "heuristic":
        return HeuristicEstimator()
    if name == "signal":
        return SignalEstimator()
    if name == "claude":
        return ClaudeEstimator(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    raise typer.BadParameter(f"unknown estimator: {name}")


@app.command("scan-once")
def scan_once(
    estimator: str = typer.Option("heuristic", help="heuristic|claude"),
    limit: int = typer.Option(200, help="kaç piyasa çekilsin"),
):
    """Tek geçiş tara — sinyalleri yazdır, paper book'a kaydet."""
    assert_paper_mode()
    est = _make_estimator(estimator)
    book = PaperBook()
    scanner = Scanner(estimator=est, book=book, console=console)

    with PolymarketClient(base_url=settings.polymarket_base) as poly:
        markets = list(poly.iter_active_markets(page_size=100, max_pages=max(1, limit // 100)))
    console.print(f"[dim]fetched {len(markets)} markets from polymarket[/dim]")

    result = scanner.scan_once(markets)
    scanner._render(result)
    scanner._place_paper_orders(result.signals)


@app.command("loop")
def loop(
    estimator: str = typer.Option("heuristic"),
    fetch_limit: int = typer.Option(400),
):
    """Sürekli tarayıcıyı başlat — Ctrl+C ile dur."""
    assert_paper_mode()
    est = _make_estimator(estimator)
    book = PaperBook()
    Scanner(estimator=est, book=book, console=console).run_forever(fetch_limit=fetch_limit)


@app.command("report")
def report():
    """Paper portföy P&L raporu."""
    book = PaperBook()
    r = book.report()
    tbl = Table(title="Paper Portfolio")
    tbl.add_column("metric"); tbl.add_column("value")
    for k, v in r.items():
        if isinstance(v, float):
            v = f"{v:,.2f}"
        tbl.add_row(k, str(v))
    console.print(tbl)

    open_pos = book.open_positions()
    if open_pos:
        t = Table(title=f"Open positions ({len(open_pos)})")
        for c in ("id", "venue", "market_id", "side", "entry", "stake$", "contracts"):
            t.add_column(c)
        for p in open_pos:
            t.add_row(str(p.id), p.venue, p.market_id, p.side,
                      f"{p.entry_price:.3f}", f"{p.stake_usd:.2f}",
                      f"{p.contracts:.2f}")
        console.print(t)


@app.command("resolve")
def resolve(
    market_id: str = typer.Argument(...),
    outcome: str = typer.Option(..., help="yes|no"),
):
    """Olay sonucu belli olduğunda pozisyonları kapat."""
    book = PaperBook()
    n = book.resolve(market_id, resolved_yes=(outcome.lower() == "yes"))
    console.print(f"closed {n} position(s)")


@app.command("mark")
def mark(
    market_id: str = typer.Argument(...),
    price: float = typer.Option(..., help="şu anki YES fiyatı [0,1]"),
):
    """Erken kapatma (current market price'tan)."""
    book = PaperBook()
    n = book.mark_to_market(market_id, price)
    console.print(f"marked-to-market {n} position(s)")


if __name__ == "__main__":
    app()
