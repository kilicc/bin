#!/usr/bin/env python3
"""Son canlı SL kapanışlarının kök neden özeti (read-only)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "data" / "live.db"


def main() -> None:
    if not DB.exists():
        print("live.db yok")
        return
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, question, side, entry_price, close_price, stake_usd, contracts,
                  pnl_usd, exit_reason, opened_at, closed_at, edge, rationale
           FROM positions WHERE exit_reason='SL' ORDER BY closed_at DESC LIMIT 10"""
    ).fetchall()
    conn.close()
    if not rows:
        print("SL kapanış yok.")
        return
    print("=" * 64)
    print(" CANLI SL İNCELEMESİ")
    print("=" * 64)
    for r in rows:
        stake = float(r["stake_usd"] or 1)
        pnl = float(r["pnl_usd"] or 0)
        entry = float(r["entry_price"] or 0)
        close = float(r["close_price"] or entry)
        pct = pnl / stake * 100
        q = (r["question"] or "")[:60]
        print(f"\n  #{r['id']}  {r['side']}  {q}")
        print(f"     entry {entry:.3f} → close {close:.3f}  |  PnL ${pnl:+.3f} ({pct:.1f}% stake)")
        print(f"     edge={float(r['edge'] or 0):+.2f}  |  {r['opened_at'][:16]} → {r['closed_at'][:16]}")
        reasons = []
        ql = q.lower()
        if entry > 0.35:
            reasons.append(f"pahalı giriş ({entry:.2f}>0.35) — 1¢ kayıp ≈ büyük % stake")
        if any(k in ql for k in ("bitcoin", "btc", "ethereum", "eth")) and any(
            k in ql for k in ("above", "below", "over", "under")
        ):
            reasons.append("crypto strike — whipsaw (artık VETO_LIVE_CRYPTO_STRIKE)")
        if any(k in ql for k in ("pgl", "spirit", "win", "cs2", "dota", "valorant")):
            reasons.append("esports outright — gürültü (artık VETO_LIVE_ESPORTS_OUTRIGHT)")
        if abs(pct) > 3:
            reasons.append("SL kayması: 5sn kontrol + market FOK satış hedefi aştı")
        if not reasons:
            reasons.append("fiyat ters yönde gitti; momentum/edge yeterli değildi")
        for line in reasons:
            print(f"     → {line}")
    print("\n" + "=" * 64)


if __name__ == "__main__":
    main()
