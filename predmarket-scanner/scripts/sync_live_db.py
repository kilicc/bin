#!/usr/bin/env python3
"""live.db açık pozisyonları CLOB token bakiyesiyle eşitle — zincirde yoksa SYNC_SELL."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)
load_dotenv(ROOT / "live.scanner.env", override=True)

import live_clob as lc
import momentum_scanner as ms

DB = Path(os.getenv("LIVE_DB_PATH", "data/live.db"))
if not DB.is_absolute():
    DB = ROOT / DB


def _mid_price(client, token_id: str, fallback: float) -> float:
    """Outcome token order book mid — satılan token fiyatı."""
    try:
        ob = client.get_order_book(token_id)
        bids = getattr(ob, "bids", None) or (ob.get("bids") if isinstance(ob, dict) else [])
        asks = getattr(ob, "asks", None) or (ob.get("asks") if isinstance(ob, dict) else [])
        best_bid = float(bids[0].price if hasattr(bids[0], "price") else bids[0]["price"]) if bids else None
        best_ask = float(asks[0].price if hasattr(asks[0], "price") else asks[0]["price"]) if asks else None
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        if best_bid is not None:
            return best_bid
        if best_ask is not None:
            return best_ask
    except Exception:
        pass
    return fallback


def main() -> int:
    ms.POLYMARKET_LIVE_ARMED = True
    ms._CLOB_TRADING_CLIENT = lc.build_trading_client()
    if ms._CLOB_TRADING_CLIENT is None:
        print("CLOB client yok — .env / POLYMARKET_PRIVATE_KEY kontrol edin.")
        return 1

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, side, entry_price, contracts, outcome_token_id, question "
        "FROM positions WHERE closed_at IS NULL ORDER BY id"
    ).fetchall()

    if not rows:
        print("live.db: açık pozisyon yok — zaten eşit.")
        return 0

    print(f"live.db: {len(rows)} açık pozisyon — CLOB ile kontrol…")
    closed = 0
    for row in rows:
        pid = int(row["id"])
        tok = row["outcome_token_id"]
        contracts = float(row["contracts"])
        side = row["side"]
        entry = float(row["entry_price"])
        q = (row["question"] or "")[:50]

        bal = lc.get_conditional_balance(ms._CLOB_TRADING_CLIENT, str(tok)) if tok else 0.0
        bal_s = "?" if bal is None else f"{bal:.4f}"
        print(f"  #{pid} {q}  CLOB bal={bal_s}  contracts={contracts}")

        if bal is not None and bal >= max(0.01, contracts * 0.02):
            print(f"    → atlandı (zincirde hâlâ token var)")
            continue

        px = _mid_price(ms._CLOB_TRADING_CLIENT, str(tok), entry) if tok else entry
        pnl = ms.close_position(conn, pid, px, None, "SYNC_SELL")
        if pnl is not None:
            closed += 1
            print(f"    → SYNC_SELL kapatıldı  close≈{px:.3f}  PnL=${pnl:+.2f}")
        else:
            print(f"    → kapatılamadı (close_position None)")

    open_n = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE closed_at IS NULL"
    ).fetchone()[0]
    print(f"\nTamam: {closed} kapatıldı, kalan açık: {open_n}")
    conn.close()
    return 0 if open_n == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
