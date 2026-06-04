#!/usr/bin/env python3
"""9007 MEGA hesabındaki tüm açık futures pozisyonlarını kapat."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BINANCE_ELITE_PORT", "9007")
os.environ.setdefault("MEGA_INSTANCE_ID", "9007")

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> None:
    from elite_trader import mega_live as ml

    ml._mega_client = None
    mc = ml.get_mega_client()
    if not mc or mc.paper:
        print("MEGA 9007 client yok veya paper — çıkılıyor")
        return
    rows = mc.exchange_positions()
    if not rows:
        print("Borsada açık pozisyon yok")
        return
    closed = 0
    for ep in rows:
        coin = str(ep.get("coin") or "")
        sym = str(ep.get("symbol") or f"{coin}USDT")
        side = str(ep.get("side") or "LONG").upper()
        qty = mc.round_qty(coin, abs(float(ep.get("contracts") or 0)))
        if qty <= 0:
            continue
        close_side = "SHORT" if side == "LONG" else "LONG"
        try:
            mc.market_order(coin, close_side, qty, reduce_only=True)
            closed += 1
            print(f"  ✓ Kapatıldı {sym} {side} qty={qty}")
            time.sleep(0.2)
        except Exception as exc:
            print(f"  ⛔ {sym}: {exc}")
    print(f"Toplam kapatılan: {closed}")


if __name__ == "__main__":
    main()
