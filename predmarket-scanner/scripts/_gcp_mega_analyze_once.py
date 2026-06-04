#!/usr/bin/env python3
"""GCP mega_9006 durum analizi — tek seferlik."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path("/opt/binancex/predmarket-scanner")
DATA = ROOT / "data/mega_9006"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def load_json(name: str):
    p = DATA / name
    if not p.is_file():
        return None
    return json.loads(p.read_text())


def main() -> None:
    api_live = api_status = {}
    try:
        api_live = json.load(urllib.request.urlopen("http://127.0.0.1:9006/api/connection/live", timeout=25))
        api_status = json.load(urllib.request.urlopen("http://127.0.0.1:9006/api/status", timeout=25))
    except Exception as e:
        print("API err", e)

    open_raw = load_json("mega_live_open.json") or []
    if isinstance(open_raw, dict):
        open_book = open_raw.get("open") or []
    else:
        open_book = open_raw if isinstance(open_raw, list) else []
    closed_raw = load_json("mega_live_closed.json")
    closed: list = []
    if isinstance(closed_raw, list):
        closed = closed_raw
    elif isinstance(closed_raw, dict):
        closed = closed_raw.get("trades") or closed_raw.get("closed") or []

    regime = load_json("mega_market_regime.json") or {}

    print("=== API ===")
    print("api_ok", api_live.get("api_ok"), "label", api_live.get("api_label"))
    print("open_positions (api)", api_live.get("open_positions"))
    print("motor", api_status.get("mega_motor_active"), "live_orders", api_status.get("live_orders"))

    print("\n=== REGIME ===")
    print(
        "regime", regime.get("regime"),
        "locked", regime.get("regime_locked"),
        "transition", regime.get("transition_active"),
        "reason", regime.get("transition_reason"),
    )

    print("\n=== OPEN BOOK (%d) ===" % len(open_book))
    total_upnl = 0.0
    sides = Counter()
    sources = Counter()
    for p in open_book:
        sym = p.get("symbol")
        side = str(p.get("side") or p.get("type") or "?").upper()
        sides[side] += 1
        upnl = float(
            p.get("unrealized_pnl")
            or p.get("uPnL")
            or p.get("upnl")
            or p.get("mark_pnl")
            or 0
        )
        total_upnl += upnl
        et = p.get("entry_time_str") or p.get("opened_at_iso") or p.get("entry_time")
        src = str(p.get("signal_source") or p.get("source") or "MEGA-LIVE")
        sources[src.split("-")[0] if src else "unknown"] += 1
        flash = bool(
            p.get("mega_flash_reversal")
            or p.get("flash_reversal")
            or p.get("mega_flash_pump")
            or p.get("flash_pump_reversal")
        )
        pct = p.get("price_change_pct") or p.get("change_pct")
        print(f"  {sym} {side} uPnL={upnl:+.2f} entry={et} flash={flash} pct={pct}")
    print("TOTAL uPnL", round(total_upnl, 2))
    print("sides", dict(sides))
    print("sources", dict(sources))

    recent = [t for t in closed if isinstance(t, dict)][-50:]
    wins = sum(1 for t in recent if float(t.get("net_pnl") or t.get("pnl") or 0) > 0)
    net = sum(float(t.get("net_pnl") or t.get("pnl") or 0) for t in recent)
    long_c = sum(1 for t in recent if str(t.get("side") or t.get("type")).upper() == "LONG")
    print("\n=== LAST %d CLOSED ===" % len(recent))
    print("W/L", wins, len(recent) - wins, "net", round(net, 2), "LONG", long_c, "SHORT", len(recent) - long_c)

    # post-deploy closes (after 16:16 UTC deploy)
    deploy_ts = 1717345013  # placeholder - use file mtime
    guard_path = ROOT / "elite_trader/mega_direction_guard.py"
    if guard_path.is_file():
        deploy_ts = guard_path.stat().st_mtime
    post = []
    for t in closed:
        if not isinstance(t, dict):
            continue
        ets = t.get("exit_time") or t.get("closed_at") or t.get("exit_time_str")
        # rough: last 15 closes
        post.append(t)
    post = post[-15:]
    post_net = sum(float(t.get("net_pnl") or t.get("pnl") or 0) for t in post)
    post_w = sum(1 for t in post if float(t.get("net_pnl") or t.get("pnl") or 0) > 0)
    print("\n=== LAST 15 CLOSES (since deploy window) ===")
    print("W/L", post_w, len(post) - post_w, "net", round(post_net, 2))

    scan_path = DATA / "mega_scan_log.jsonl"
    rejects: Counter[str] = Counter()
    opened = 0
    dir_blocks = 0
    if scan_path.is_file():
        for ln in scan_path.read_text().splitlines()[-1500:]:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            st = r.get("status")
            reason = str(r.get("reason") or "")
            if st == "opened":
                opened += 1
            elif st in ("reject", "skip"):
                rejects[reason] += 1
                if any(
                    x in reason
                    for x in (
                        "btc_bear",
                        "cluster",
                        "direction",
                        "medium_bear",
                        "alt_dip",
                        "symbol_medium",
                    )
                ):
                    dir_blocks += 1

    print("\n=== SCAN (last 1500 log lines) ===")
    print("opened", opened, "direction_related_blocks", dir_blocks)
    for k, v in rejects.most_common(18):
        print(f"  {v:4d} {k}")

    try:
        import binance_elite_pro as bep
        from elite_trader.berserk2_btc_context import get_btc_context
        from elite_trader.mega_direction_guard import (
            btc_bearish,
            cluster_allows_side,
            enabled,
        )

        bear, tag = btc_bearish(bep.price_history)
        print("\n=== DIRECTION GUARD LIVE ===")
        print("enabled", enabled())
        print("btc_bearish", bear, tag)
        print("btc_ctx", get_btc_context())
        print("cluster_long", cluster_allows_side("LONG", price_history=bep.price_history))
    except Exception as e:
        print("guard", e)

    print("\n=== ENV ===")
    envp = ROOT / "scenarios/binance_elite_mega_9006_mainnet.env"
    if envp.is_file():
        for line in envp.read_text().splitlines():
            if line.startswith(
                (
                    "MEGA_CLUSTER_",
                    "MEGA_BEAR_",
                    "MEGA_FLASH_",
                    "MEGA_DIRECTION_",
                )
            ) and "=" in line:
                print(line)


if __name__ == "__main__":
    main()
