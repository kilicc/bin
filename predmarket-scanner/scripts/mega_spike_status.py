#!/usr/bin/env python3
"""Açık MEGA pozisyonları — net spike eşiği mesafesi (canlı snapshot)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MIN_NET = float(os.getenv("MEGA_MIN_CLOSE_NET_USD", "10"))


def _gross_for_min_net(pos: dict, stake: float, lev: int, floor: float) -> float:
    from elite_trader.fee_economics import estimate_close_pnl

    ef = float(pos.get("entry_fee") or 0) or None
    for g in range(5, 120):
        net = float(
            estimate_close_pnl(float(g), stake, lev, entry_fee=ef, pos=pos).get(
                "final_pnl"
            )
            or 0
        )
        if net >= floor:
            return float(g)
    return float("nan")


def main() -> None:
    port = os.getenv("BINANCE_ELITE_PORT", "9006")
    url = f"http://127.0.0.1:{port}/api/paper/mega/snapshot?light=1"
    with urllib.request.urlopen(url, timeout=8) as resp:
        data = json.load(resp)
    hb_url = f"http://127.0.0.1:{port}/api/heartbeat"
    with urllib.request.urlopen(hb_url, timeout=5) as resp:
        hb = json.load(resp)
    mega = hb.get("mega") or {}
    print(f"MEGA açık: {len(data.get('open') or [])} | cache_age_ms: {mega.get('cache_age_ms')}")
    print(f"position_interval_ms: {hb.get('position_interval_ms')} | tick_ms: {hb.get('position_tick_ms')}")
    print(f"min_net_close: ${MIN_NET:.2f}\n")
    from elite_trader.fee_economics import estimate_close_pnl, fast_scalp_min_gross_usd

    for p in data.get("open") or []:
        stake = float(p.get("stake_usd") or 0)
        lev = max(int(p.get("leverage") or 1), 1)
        unreal = float(p.get("unrealized_pnl") or 0)
        max_u = float(p.get("max_unreal_seen") or 0)
        flash = fast_scalp_min_gross_usd(stake, lev, mode_id="mega")
        need = _gross_for_min_net(p, stake, lev, MIN_NET)
        ef = float(p.get("entry_fee") or 0) or None
        net_now = float(
            estimate_close_pnl(unreal, stake, lev, entry_fee=ef, pos=p).get("final_pnl")
            or 0
        )
        net_peak = (
            float(
                estimate_close_pnl(max_u, stake, lev, entry_fee=ef, pos=p).get(
                    "final_pnl"
                )
                or 0
            )
            if max_u > 0
            else 0.0
        )
        gap = need - unreal if unreal < need else 0.0
        sym = str(p.get("symbol") or "").replace("USDT", "")
        print(
            f"{sym:8} {str(p.get('side') or ''):5} {lev}x ${stake:,.0f} | "
            f"uPnL {unreal:+6.2f} max {max_u:6.2f} | "
            f"net {net_now:+6.2f} peak_net {net_peak:+6.2f} | "
            f"need_gross ${need:.1f} gap ${gap:.1f} flash ${flash:.2f}"
        )


if __name__ == "__main__":
    main()
