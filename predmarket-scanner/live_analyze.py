#!/usr/bin/env python3
"""Canlı portföy özeti + açık pozisyon TP/SL mesafesi (read-only)."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


def main() -> None:
    import live_clob as lc
    import live_portfolio as lp

    wallet = __import__("live_wallet", fromlist=["fetch_wallet_snapshot"]).fetch_wallet_snapshot()
    port = lp.read_live_portfolio()
    usdc = wallet.get("usdc")
    print("=" * 60)
    print(" CANLI DURUM")
    print("=" * 60)
    print(f"  USDC (CLOB):     ${usdc:.2f}" if usdc else "  USDC: —")
    st = port["stats"]
    print(f"  Realized PnL:    ${st['realized_pnl']:+.2f}  ({st['closed_trades']} kapalı)")
    wr = st.get("win_rate")
    if wr is not None:
        print(f"  WIN RATE:        {wr * 100:.1f}%  ({st.get('wins', 0)}W / {st.get('losses', 0)}L)")
    else:
        print("  WIN RATE:        — (henüz kapalı işlem yok)")
    tp_n, sl_n = st.get("tp_count", 0), st.get("sl_count", 0)
    if tp_n or sl_n:
        wts = st.get("wr_tp_sl")
        wts_s = f"{wts * 100:.1f}%" if wts is not None else "—"
        print(f"  TP / SL:         {tp_n} TP / {sl_n} SL  (TP/SL WR: {wts_s})")
    print(f"  Açık:            {st['open_trades']}")
    tp = port.get("exit_rule", {})
    print(f"  Çıkış:           {tp.get('label', '±2% stake')}")

    opens = port.get("open_positions") or []
    if not opens:
        print("\n  Açık pozisyon yok.")
    client = httpx.Client(timeout=15.0)
    for p in opens:
        mid = p["market_id"]
        side = p["side"]
        entry = float(p["entry_price"])
        stake = float(p["stake_usd"])
        contracts = float(p["contracts"])
        tp_t = float(p.get("tp_target_usd") or stake * 0.02)
        sl_t = float(p.get("sl_target_usd") or stake * 0.02)
        yes_cur = None
        try:
            r = client.get(f"{GAMMA}/markets/{mid}")
            if r.status_code == 200:
                m = r.json()
                tokens = m.get("clobTokenIds")
                if isinstance(tokens, str):
                    import json

                    tokens = json.loads(tokens)
                if tokens:
                    pr = client.get(f"{CLOB}/midpoint", params={"token_id": tokens[0]})
                    if pr.status_code == 200:
                        yes_cur = float(pr.json().get("mid", 0))
        except Exception:
            pass
        if yes_cur is not None:
            cur_side = yes_cur if side == "YES" else (1.0 - yes_cur)
            unr = contracts * (cur_side - entry)
            need_tp = tp_t - unr
            need_sl = unr + sl_t
            print(f"\n  #{p['id']} {side}  {p['question'][:55]}")
            print(f"     stake ${stake:.2f}  entry {entry:.3f}  now {cur_side:.3f}")
            print(f"     P&L ${unr:+.3f}  → TP +${tp_t:.2f} için ${need_tp:+.3f} kaldı  |  SL -${sl_t:.2f} için ${need_sl:.3f} buffer")
        else:
            print(f"\n  #{p['id']} {p['question'][:55]}  (fiyat alınamadı)")
    client.close()

    print("\n  Çıkış: TP +2% / SL -2% stake (simetrik)")
    print("  Çalıştır: ./run_live_scanner.sh")
    print("=" * 60)


if __name__ == "__main__":
    main()
