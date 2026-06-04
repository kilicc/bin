"""Forward paper-mode whale tracker.

Curated whale watchlist'i okur, data-api'den her N saniyede yeni trade'leri çeker,
whale yeni pozisyon açtığında paper book'a kopya açar, whale çıkış yaptığında
kapatır. SQLite'da durum saklar. Kesintilerden sonra devam edebilir.

Çalıştır:
  python whale_tracker_runner.py            # sonsuz döngü, Ctrl+C ile dur
  python whale_tracker_runner.py --once     # bir geçiş, sonra çık
  python whale_tracker_runner.py --report   # paper book raporu yazdır
"""
from __future__ import annotations

import argparse
import os
import pickle
import signal
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from markets.polymarket_data_api import PolymarketDataAPI
from markets.wallets import WalletTrade


ROOT = Path(__file__).parent
DATA = ROOT / "data"
WATCHLIST = DATA / "whale_watchlist_curated.pkl"
DB_PATH = DATA / "paper_whale_tracker.db"
STATE_PATH = DATA / "tracker_state.pkl"

POLL_INTERVAL_SEC = 60
LOOKBACK_INITIAL = timedelta(hours=1)
PER_WALLET_MAX_PAGES = 2
PER_WALLET_SLEEP = 0.30


SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    whale TEXT NOT NULL,
    market_id TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_size_usd REAL NOT NULL,
    opened_at TEXT NOT NULL,
    open_tx TEXT,
    closed_at TEXT,
    close_price REAL,
    close_size_usd REAL,
    close_tx TEXT,
    pnl_usd REAL,
    UNIQUE(open_tx)
);
CREATE INDEX IF NOT EXISTS idx_open ON paper_positions(whale, market_id, side, closed_at);
CREATE INDEX IF NOT EXISTS idx_closed ON paper_positions(closed_at);
"""


class TrackerState:
    """Restart'tan sonra devam etmek için son işlenmiş tx_hash'leri tutar."""

    def __init__(self):
        self.seen_open_tx: set[str] = set()
        self.seen_close_tx: set[str] = set()
        self.last_poll_ts: dict[str, datetime] = {}  # wallet → last poll cutoff

    @classmethod
    def load(cls) -> "TrackerState":
        if STATE_PATH.exists():
            try:
                with open(STATE_PATH, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        STATE_PATH.write_bytes(pickle.dumps(self))


def open_paper_position(conn, wt: WalletTrade) -> bool:
    try:
        conn.execute(
            "INSERT OR IGNORE INTO paper_positions "
            "(whale, market_id, side, entry_price, entry_size_usd, opened_at, open_tx) "
            "VALUES (?,?,?,?,?,?,?)",
            (wt.wallet, wt.market_id, wt.side, wt.price, wt.size_usd,
             wt.timestamp.isoformat(), wt.tx_hash),
        )
        conn.commit()
        return conn.total_changes > 0
    except sqlite3.Error as e:
        print(f"[db] open error: {e}")
        return False


def close_paper_position(conn, wt: WalletTrade) -> bool:
    cur = conn.execute(
        "SELECT id, entry_size_usd FROM paper_positions "
        "WHERE whale=? AND market_id=? AND side=? AND closed_at IS NULL "
        "ORDER BY opened_at LIMIT 1",
        (wt.wallet, wt.market_id, wt.side),
    )
    row = cur.fetchone()
    if not row:
        return False
    pos_id, entry_size = row
    pnl = wt.size_usd - entry_size
    conn.execute(
        "UPDATE paper_positions SET closed_at=?, close_price=?, close_size_usd=?, "
        "close_tx=?, pnl_usd=? WHERE id=?",
        (wt.timestamp.isoformat(), wt.price, wt.size_usd, wt.tx_hash, pnl, pos_id),
    )
    conn.commit()
    return True


def poll_once(conn, state: TrackerState, whales: list[str], api: PolymarketDataAPI):
    """Her whale için son trade'leri çek, paper book'u güncelle."""
    new_opens = 0
    new_closes = 0
    errors = 0
    now = datetime.now(timezone.utc)

    for whale in whales:
        last = state.last_poll_ts.get(whale)
        since = last - timedelta(minutes=5) if last else now - LOOKBACK_INITIAL
        try:
            trades = list(api.iter_recent_trades(
                since=since, user=whale, max_pages=PER_WALLET_MAX_PAGES,
            ))
        except Exception as e:
            errors += 1
            print(f"[poll] {whale[:14]}... {e}")
            continue
        state.last_poll_ts[whale] = now

        for wt in trades:
            if not wt.tx_hash:
                continue
            if wt.direction == "open" and wt.tx_hash not in state.seen_open_tx:
                state.seen_open_tx.add(wt.tx_hash)
                if open_paper_position(conn, wt):
                    new_opens += 1
                    print(f"  OPEN  {wt.wallet[:14]}...  {wt.side}  "
                          f"{wt.market_id[:12]}... @ {wt.price:.3f}  ${wt.size_usd:.2f}")
            elif wt.direction == "close" and wt.tx_hash not in state.seen_close_tx:
                state.seen_close_tx.add(wt.tx_hash)
                if close_paper_position(conn, wt):
                    new_closes += 1
                    print(f"  CLOSE {wt.wallet[:14]}...  {wt.side}  "
                          f"{wt.market_id[:12]}... @ {wt.price:.3f}  ${wt.size_usd:.2f}")
        time.sleep(PER_WALLET_SLEEP)

    state.save()
    return new_opens, new_closes, errors


def print_report(conn):
    print("\n" + "=" * 70)
    print(" PAPER WHALE TRACKER RAPORU")
    print("=" * 70)
    cur = conn.execute("SELECT COUNT(*) FROM paper_positions WHERE closed_at IS NULL")
    open_n = cur.fetchone()[0]
    cur = conn.execute(
        "SELECT COUNT(*), "
        " COALESCE(SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END), 0), "
        " COALESCE(SUM(pnl_usd), 0) "
        "FROM paper_positions WHERE closed_at IS NOT NULL"
    )
    closed_n, wins, total_pnl = cur.fetchone()
    wr = wins / closed_n if closed_n else 0.0
    avg = total_pnl / closed_n if closed_n else 0.0
    print(f"  Açık pozisyon:        {open_n}")
    print(f"  Kapanmış pozisyon:    {closed_n}")
    print(f"  Win / Loss:           {wins} / {closed_n - wins}")
    print(f"  Win rate:             {wr:.2%}")
    print(f"  Total close-PnL:      ${total_pnl:+,.2f}")
    print(f"  Avg per closed trade: ${avg:+.2f}")
    print()

    # Per whale
    cur = conn.execute(
        "SELECT whale, COUNT(*), "
        " SUM(CASE WHEN closed_at IS NOT NULL THEN 1 ELSE 0 END), "
        " COALESCE(SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END), 0), "
        " COALESCE(SUM(pnl_usd), 0) "
        "FROM paper_positions GROUP BY whale ORDER BY 5 DESC"
    )
    rows = cur.fetchall()
    if rows:
        print(f"  Per-whale:")
        print(f"  {'wallet':<44}  {'open':>5}  {'cls':>5}  {'win':>5}  {'PnL':>10}")
        for whale, total, closed, w, pnl in rows:
            print(f"  {whale:<44}  {total-closed:>5}  {closed:>5}  {w:>5}  ${pnl:>+8,.2f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--watchlist", default=str(WATCHLIST))
    args = parser.parse_args()

    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    if args.report:
        print_report(conn)
        return

    if not Path(args.watchlist).exists():
        print(f"[X] Watchlist bulunamadı: {args.watchlist}")
        print("    Önce: python rank_quality.py")
        sys.exit(1)
    whales = list(pickle.load(open(args.watchlist, "rb")))
    print(f"Watchlist: {len(whales)} cüzdan")

    state = TrackerState.load()
    print(f"State: {len(state.seen_open_tx)} open, {len(state.seen_close_tx)} close tx görülmüş")

    stopped = False
    def _stop(*a):
        nonlocal stopped
        stopped = True
        print("\n[Ctrl+C] durduruluyor, son state kaydedilecek...")
    signal.signal(signal.SIGINT, _stop)

    iteration = 0
    with PolymarketDataAPI() as api:
        while not stopped:
            iteration += 1
            t0 = time.time()
            print(f"\n[{datetime.now(timezone.utc).isoformat()}] poll #{iteration}")
            opens, closes, errs = poll_once(conn, state, whales, api)
            print(f"  → +{opens} open, +{closes} close, {errs} errors  "
                  f"({time.time()-t0:.1f}s)")
            if iteration % 10 == 0:
                print_report(conn)
            if args.once:
                break
            for _ in range(POLL_INTERVAL_SEC):
                if stopped:
                    break
                time.sleep(1)

    print_report(conn)
    conn.close()


if __name__ == "__main__":
    main()
