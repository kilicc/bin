#!/usr/bin/env python3
"""Canlı pozisyon incelemesi + %5 stake kârda hemen kapat."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "live.scanner.env")

TP_PCT = float(os.getenv("TAKE_PROFIT_STAKE_PCT", "0.02"))
SL_PCT = float(os.getenv("STOP_LOSS_STAKE_PCT", "0.02"))
DB = Path(os.getenv("LIVE_DB_PATH", "data/live.db"))
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


def _mid(client: httpx.Client, market_id: str, side: str) -> float | None:
    r = client.get(f"{GAMMA}/markets/{market_id}", timeout=15.0)
    if r.status_code != 200:
        return None
    m = r.json()
    tokens = m.get("clobTokenIds")
    if isinstance(tokens, str):
        import json

        tokens = json.loads(tokens)
    yes = None
    if tokens:
        pr = client.get(f"{CLOB}/midpoint", params={"token_id": tokens[0]}, timeout=10.0)
        if pr.status_code == 200:
            yes = float(pr.json().get("mid", 0))
    if yes is None:
        op = m.get("outcomePrices")
        if isinstance(op, str):
            import json

            op = json.loads(op)
        if op:
            yes = float(op[0])
    if yes is None:
        return None
    return yes if side == "YES" else (1.0 - yes)


def main() -> None:
    if not DB.exists():
        print("live.db yok")
        sys.exit(1)

    os.environ.setdefault("POLYMARKET_LIVE_TRADING", "1")
    os.environ.setdefault("POLYMARKET_LIVE_CONFIRM", "I_UNDERSTAND_REAL_MONEY_LOSS")

    import momentum_scanner as ms

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    closed = conn.execute(
        """SELECT id, question, side, entry_price, close_price, stake_usd, contracts,
                  pnl_usd, exit_reason, opened_at, closed_at
           FROM positions WHERE closed_at IS NOT NULL ORDER BY closed_at DESC"""
    ).fetchall()
    opens = conn.execute(
        """SELECT id, market_id, question, side, entry_price, stake_usd, contracts,
                  edge, opened_at, outcome_token_id
           FROM positions WHERE closed_at IS NULL ORDER BY id"""
    ).fetchall()

    print("=" * 64)
    print(" CANLI İŞLEM İNCELEMESİ")
    print(f" TP: +{TP_PCT*100:.0f}% stake  |  SL: -{SL_PCT*100:.0f}% stake")
    print("=" * 64)

    if closed:
        print("\n--- Kapalı ---")
        for r in closed:
            stake = float(r["stake_usd"] or 1)
            pnl = float(r["pnl_usd"] or 0)
            pct = 100 * pnl / stake
            print(
                f"  #{r['id']} {r['exit_reason']:8s} {r['side']:3s}  "
                f"P&L ${pnl:+.3f} ({pct:+.1f}% stake)  {(r['question'] or '')[:50]}"
            )
    else:
        print("\n  Kapalı işlem yok.")

    if not opens:
        print("\n  Açık pozisyon yok.")
        conn.close()
        return

    client = httpx.Client(timeout=20.0)
    ms.POLYMARKET_LIVE_ARMED = True
    ms.DB_PATH = DB
    ms.LIVE_SIMPLE_EXIT = True
    if ms._CLOB_TRADING_CLIENT is None:
        import live_clob as lc

        ms._CLOB_TRADING_CLIENT = lc.build_trading_client()
    import live_clob as lc

    print("\n--- Açık ---")
    for r in opens:
        mid = _mid(client, str(r["market_id"]), str(r["side"]))
        entry = float(r["entry_price"])
        stake = float(r["stake_usd"])
        contracts = float(r["contracts"])
        if mid is None:
            print(f"  #{r['id']} {r['side']}  fiyat alınamadı  {(r['question'] or '')[:50]}")
            continue
        unr = contracts * (mid - entry)
        pct = 100 * unr / max(stake, 0.01)
        target = stake * TP_PCT
        flag = "✓ TP HEDEF" if unr >= target else "bekle"
        print(
            f"  #{r['id']} {r['side']}  entry={entry:.3f} now={mid:.3f}  "
            f"P&L ${unr:+.3f} ({pct:+.1f}% stake)  hedef +${target:.3f}  [{flag}]"
        )
        print(f"       {(r['question'] or '')[:58]}")

        tok = r["outcome_token_id"]
        if tok:
            cb = lc.get_conditional_balance(ms._CLOB_TRADING_CLIENT, str(tok))
            if cb is not None:
                print(f"       CLOB outcome bakiye: {cb:.4g} pay (DB: {contracts:.4g})")

        if unr >= target:
            print(f"  → Kapatılıyor (≥{TP_PCT*100:.0f}% kâr)...")
            cb = lc.get_conditional_balance(ms._CLOB_TRADING_CLIENT, str(tok)) if tok else 0.0
            if cb is not None and cb < float(contracts) * 0.5:
                print(
                    "  ⚠ CLOB pay bakiyesi 0 — pozisyon muhtemelen zaten satılmış. "
                    "Polymarket → Trades kontrol edin; live.db manuel senkron gerekebilir."
                )
            else:
                pnl = ms.close_position(conn, int(r["id"]), mid, None, exit_reason="TP")
                if pnl:
                    print(f"  💰 Kapatıldı #{r['id']}  PnL=${pnl:+.3f}")
                else:
                    print(f"  ✗ CLOB satış başarısız — DB güncellenmedi")

    client.close()
    conn.close()
    print("\n" + "=" * 64)


if __name__ == "__main__":
    main()
