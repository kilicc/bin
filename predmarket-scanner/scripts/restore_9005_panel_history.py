#!/usr/bin/env python3
"""Panelde görünen kapanmış işlemleri DB'ye yazar — env/ayar değiştirmez."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["BINANCE_ELITE_PORT"] = "9005"
os.environ["PROFILE_NAME"] = "binance_elite_8300_9005"

# Kullanıcı panelinden (2026-05-21 ~15:00–15:24) — tam satır verisi
PANEL_EXACT: list[dict] = [
    {"id": 23, "symbol": "CYSUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.4671, "exit_price": 0.4647, "size": 1601.0, "pnl_usd": -3.84, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -4.44, "net_pnl_pct": -1.78, "tax": 0.0, "final_pnl": -4.44, "exit_reason": "SL", "exit_time": "2026-05-21 15:00:29", "stake_usd": 250.0},
    {"id": 12, "symbol": "AIOTUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0717, "exit_price": 0.0715, "size": 10451.0, "pnl_usd": 2.46, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.86, "net_pnl_pct": 0.74, "tax": 0.19, "final_pnl": 1.67, "exit_reason": "TP", "exit_time": "2026-05-21 15:00:59", "stake_usd": 250.0},
    {"id": 17, "symbol": "ESPORTSUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.6858, "exit_price": 0.6833, "size": 1095.0, "pnl_usd": 2.76, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.16, "net_pnl_pct": 0.87, "tax": 0.22, "final_pnl": 1.95, "exit_reason": "TP", "exit_time": "2026-05-21 15:01:42", "stake_usd": 250.0},
    {"id": 30, "symbol": "AKEUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0003, "exit_price": 0.0003, "size": 2234803.0, "pnl_usd": -4.25, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -4.85, "net_pnl_pct": -1.94, "tax": 0.0, "final_pnl": -4.85, "exit_reason": "SL", "exit_time": "2026-05-21 15:02:57", "stake_usd": 250.0},
    {"id": 20, "symbol": "AIAUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0572, "exit_price": 0.0575, "size": 13150.0, "pnl_usd": -4.66, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -5.26, "net_pnl_pct": -2.10, "tax": 0.0, "final_pnl": -5.26, "exit_reason": "SL", "exit_time": "2026-05-21 15:03:14", "stake_usd": 250.0},
    {"id": 31, "symbol": "ONDOUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.4016, "exit_price": 0.4029, "size": 1862.0, "pnl_usd": 2.51, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.91, "net_pnl_pct": 0.76, "tax": 0.19, "final_pnl": 1.72, "exit_reason": "TP", "exit_time": "2026-05-21 15:03:23", "stake_usd": 250.0},
    {"id": 25, "symbol": "GWEIUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.1166, "exit_price": 0.1162, "size": 6429.0, "pnl_usd": 2.47, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.87, "net_pnl_pct": 0.75, "tax": 0.19, "final_pnl": 1.68, "exit_reason": "TP", "exit_time": "2026-05-21 15:03:25", "stake_usd": 250.0},
    {"id": 28, "symbol": "MEGAUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0891, "exit_price": 0.0887, "size": 8418.0, "pnl_usd": 2.98, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.38, "net_pnl_pct": 0.95, "tax": 0.24, "final_pnl": 2.14, "exit_reason": "TP", "exit_time": "2026-05-21 15:04:14", "stake_usd": 250.0},
    {"id": 26, "symbol": "币安人生USDT", "side": "LONG", "leverage": 5, "entry_price": 0.4494, "exit_price": 0.4509, "size": 1669.0, "pnl_usd": 2.51, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.91, "net_pnl_pct": 0.77, "tax": 0.19, "final_pnl": 1.72, "exit_reason": "TP", "exit_time": "2026-05-21 15:04:16", "stake_usd": 250.0},
    {"id": 35, "symbol": "MITOUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0456, "exit_price": 0.0454, "size": 16494.0, "pnl_usd": 2.97, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.37, "net_pnl_pct": 0.95, "tax": 0.24, "final_pnl": 2.13, "exit_reason": "TP", "exit_time": "2026-05-21 15:05:37", "stake_usd": 250.0},
    {"id": 29, "symbol": "AKTUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.7895, "exit_price": 0.7855, "size": 949.7, "pnl_usd": -3.83, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -4.43, "net_pnl_pct": -1.77, "tax": 0.0, "final_pnl": -4.43, "exit_reason": "SL", "exit_time": "2026-05-21 15:07:58", "stake_usd": 250.0},
    {"id": 33, "symbol": "SKYAIUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.3263, "exit_price": 0.3252, "size": 2299.0, "pnl_usd": 2.45, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.86, "net_pnl_pct": 0.74, "tax": 0.19, "final_pnl": 1.67, "exit_reason": "TP", "exit_time": "2026-05-21 15:08:26", "stake_usd": 250.0},
    {"id": 36, "symbol": "TAGUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0012, "exit_price": 0.0012, "size": 641854.0, "pnl_usd": 5.15, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 4.55, "net_pnl_pct": 1.82, "tax": 0.45, "final_pnl": 4.09, "exit_reason": "TP", "exit_time": "2026-05-21 15:08:57", "stake_usd": 250.0},
    {"id": 37, "symbol": "BANANAS31USDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0131, "exit_price": 0.0130, "size": 57509.0, "pnl_usd": 2.53, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.93, "net_pnl_pct": 0.77, "tax": 0.19, "final_pnl": 1.73, "exit_reason": "TP", "exit_time": "2026-05-21 15:09:53", "stake_usd": 250.0},
    {"id": 34, "symbol": "FIGHTUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.0056, "exit_price": 0.0056, "size": 133499.0, "pnl_usd": -3.76, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -4.36, "net_pnl_pct": -1.74, "tax": 0.0, "final_pnl": -4.36, "exit_reason": "SL", "exit_time": "2026-05-21 15:10:34", "stake_usd": 250.0},
    {"id": 24, "symbol": "DODOXUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0216, "exit_price": 0.0215, "size": 34762.0, "pnl_usd": 2.46, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.86, "net_pnl_pct": 0.74, "tax": 0.19, "final_pnl": 1.67, "exit_reason": "TP", "exit_time": "2026-05-21 15:11:26", "stake_usd": 250.0},
    {"id": 40, "symbol": "HOMEUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0230, "exit_price": 0.0229, "size": 32745.0, "pnl_usd": 2.55, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.95, "net_pnl_pct": 0.78, "tax": 0.20, "final_pnl": 1.76, "exit_reason": "TP", "exit_time": "2026-05-21 15:12:14", "stake_usd": 250.0},
    {"id": 41, "symbol": "ONDOUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.4013, "exit_price": 0.4028, "size": 1866.0, "pnl_usd": 2.73, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.13, "net_pnl_pct": 0.85, "tax": 0.21, "final_pnl": 1.92, "exit_reason": "TP", "exit_time": "2026-05-21 15:13:36", "stake_usd": 250.0},
    {"id": 42, "symbol": "AVNTUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.1542, "exit_price": 0.1551, "size": 4837.0, "pnl_usd": 4.35, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 3.75, "net_pnl_pct": 1.50, "tax": 0.38, "final_pnl": 3.38, "exit_reason": "TP", "exit_time": "2026-05-21 15:13:49", "stake_usd": 250.0},
    {"id": 8, "symbol": "XVGUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0034, "exit_price": 0.0034, "size": 219775.0, "pnl_usd": -3.78, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -4.38, "net_pnl_pct": -1.75, "tax": 0.0, "final_pnl": -4.38, "exit_reason": "SL", "exit_time": "2026-05-21 15:13:53", "stake_usd": 250.0},
    {"id": 27, "symbol": "STGUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.1663, "exit_price": 0.1671, "size": 4509.0, "pnl_usd": -3.79, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -4.39, "net_pnl_pct": -1.76, "tax": 0.0, "final_pnl": -4.39, "exit_reason": "SL", "exit_time": "2026-05-21 15:14:32", "stake_usd": 250.0},
    {"id": 38, "symbol": "ESPORTSUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.6844, "exit_price": 0.6867, "size": 1094.0, "pnl_usd": 2.48, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.88, "net_pnl_pct": 0.75, "tax": 0.19, "final_pnl": 1.69, "exit_reason": "TP", "exit_time": "2026-05-21 15:14:39", "stake_usd": 250.0},
    {"id": 45, "symbol": "MITOUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.0457, "exit_price": 0.0461, "size": 16252.0, "pnl_usd": 5.04, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 4.44, "net_pnl_pct": 1.78, "tax": 0.44, "final_pnl": 4.00, "exit_reason": "TP", "exit_time": "2026-05-21 15:15:46", "stake_usd": 250.0},
    {"id": 44, "symbol": "USELESSUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0730, "exit_price": 0.0734, "size": 10283.0, "pnl_usd": -3.93, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -4.53, "net_pnl_pct": -1.81, "tax": 0.0, "final_pnl": -4.53, "exit_reason": "SL", "exit_time": "2026-05-21 15:16:29", "stake_usd": 250.0},
    {"id": 47, "symbol": "HYPEUSDT", "side": "LONG", "leverage": 5, "entry_price": 62.0, "exit_price": 62.2538, "size": 12.06, "pnl_usd": 3.06, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.46, "net_pnl_pct": 0.98, "tax": 0.25, "final_pnl": 2.21, "exit_reason": "TP", "exit_time": "2026-05-21 15:16:36", "stake_usd": 250.0},
    {"id": 48, "symbol": "SUIUSDT", "side": "LONG", "leverage": 5, "entry_price": 1.1124, "exit_price": 1.1162, "size": 671.8, "pnl_usd": 2.58, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.98, "net_pnl_pct": 0.79, "tax": 0.20, "final_pnl": 1.78, "exit_reason": "TP", "exit_time": "2026-05-21 15:17:40", "stake_usd": 250.0},
    {"id": 39, "symbol": "MAGMAUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.2409, "exit_price": 0.2422, "size": 3114.0, "pnl_usd": -3.95, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -4.55, "net_pnl_pct": -1.82, "tax": 0.0, "final_pnl": -4.55, "exit_reason": "SL", "exit_time": "2026-05-21 15:17:45", "stake_usd": 250.0},
    {"id": 51, "symbol": "AKTUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.7925, "exit_price": 0.7955, "size": 943.0, "pnl_usd": 2.80, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.20, "net_pnl_pct": 0.88, "tax": 0.22, "final_pnl": 1.98, "exit_reason": "TP", "exit_time": "2026-05-21 15:18:04", "stake_usd": 250.0},
    {"id": 52, "symbol": "TAGUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.0012, "exit_price": 0.0012, "size": 634324.0, "pnl_usd": 2.75, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.15, "net_pnl_pct": 0.86, "tax": 0.21, "final_pnl": 1.93, "exit_reason": "TP", "exit_time": "2026-05-21 15:18:16", "stake_usd": 250.0},
    {"id": 53, "symbol": "LABUSDT", "side": "LONG", "leverage": 5, "entry_price": 4.492, "exit_price": 4.512, "size": 166.3, "pnl_usd": 3.32, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.72, "net_pnl_pct": 1.09, "tax": 0.27, "final_pnl": 2.45, "exit_reason": "TP", "exit_time": "2026-05-21 15:18:18", "stake_usd": 250.0},
    {"id": 49, "symbol": "SPACEUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.0084, "exit_price": 0.0085, "size": 88686.0, "pnl_usd": 3.02, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.41, "net_pnl_pct": 0.97, "tax": 0.24, "final_pnl": 2.17, "exit_reason": "TP", "exit_time": "2026-05-21 15:18:25", "stake_usd": 250.0},
    {"id": 54, "symbol": "SQDUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0434, "exit_price": 0.0431, "size": 17372.0, "pnl_usd": 5.46, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 4.86, "net_pnl_pct": 1.94, "tax": 0.49, "final_pnl": 4.37, "exit_reason": "TP", "exit_time": "2026-05-21 15:19:05", "stake_usd": 250.0},
    {"id": 46, "symbol": "SKYAIUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.3229, "exit_price": 0.3212, "size": 2324.0, "pnl_usd": -3.92, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": -4.52, "net_pnl_pct": -1.81, "tax": 0.0, "final_pnl": -4.52, "exit_reason": "SL", "exit_time": "2026-05-21 15:20:13", "stake_usd": 250.0},
    {"id": 56, "symbol": "HOMEUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.0231, "exit_price": 0.0232, "size": 32334.0, "pnl_usd": 4.59, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 3.99, "net_pnl_pct": 1.60, "tax": 0.40, "final_pnl": 3.59, "exit_reason": "TP", "exit_time": "2026-05-21 15:20:19", "stake_usd": 250.0},
    {"id": 57, "symbol": "BANANAS31USDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0130, "exit_price": 0.0129, "size": 58004.0, "pnl_usd": 3.54, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.94, "net_pnl_pct": 1.18, "tax": 0.29, "final_pnl": 2.64, "exit_reason": "TP", "exit_time": "2026-05-21 15:20:23", "stake_usd": 250.0},
    {"id": 50, "symbol": "AINUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.0945, "exit_price": 0.0948, "size": 7937.0, "pnl_usd": 2.47, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 1.87, "net_pnl_pct": 0.75, "tax": 0.19, "final_pnl": 1.68, "exit_reason": "TP", "exit_time": "2026-05-21 15:21:11", "stake_usd": 250.0},
    {"id": 59, "symbol": "ONDOUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.4065, "exit_price": 0.4079, "size": 1842.0, "pnl_usd": 2.61, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.01, "net_pnl_pct": 0.80, "tax": 0.20, "final_pnl": 1.80, "exit_reason": "TP", "exit_time": "2026-05-21 15:23:27", "stake_usd": 250.0},
    {"id": 43, "symbol": "ARIAUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.0463, "exit_price": 0.0465, "size": 16198.0, "pnl_usd": 3.01, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.40, "net_pnl_pct": 0.96, "tax": 0.24, "final_pnl": 2.16, "exit_reason": "TP", "exit_time": "2026-05-21 15:23:34", "stake_usd": 250.0},
    {"id": 60, "symbol": "MITOUSDT", "side": "SHORT", "leverage": 5, "entry_price": 0.0461, "exit_price": 0.0459, "size": 16336.0, "pnl_usd": 4.08, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 3.48, "net_pnl_pct": 1.39, "tax": 0.35, "final_pnl": 3.14, "exit_reason": "TP", "exit_time": "2026-05-21 15:24:01", "stake_usd": 250.0},
    {"id": 58, "symbol": "COLLECTUSDT", "side": "LONG", "leverage": 5, "entry_price": 0.0516, "exit_price": 0.0518, "size": 14537.0, "pnl_usd": 2.91, "entry_fee": 0.30, "exit_fee": 0.30, "total_fees": 0.60, "net_pnl": 2.31, "net_pnl_pct": 0.92, "tax": 0.23, "final_pnl": 2.08, "exit_reason": "TP", "exit_time": "2026-05-21 15:24:33", "stake_usd": 250.0},
]

PANEL_IDS = {int(r["id"]) for r in PANEL_EXACT}


def _parse_log_session() -> list[dict]:
    text = (ROOT / "logs" / "binance_elite_8300_9005.log").read_text(errors="replace")
    marker = "INFO:     Started server process [74281]"
    idx = text.rfind(marker)
    chunk = text[idx:] if idx >= 0 else text
    open_re = re.compile(
        r"✅ (LONG|SHORT) (\w+) @ \$([\d.]+) \| (\d+)x \| stake=\$([\d.]+)"
    )
    close_re = re.compile(r"✅ Closed #(\d+): (\w+) \| \$([-\d.]+)")
    exit_re = re.compile(r"Borsa kapanış (\w+) ([\w-]+) qty=")
    pending: dict[str, dict] = {}
    trades: list[dict] = []
    for line in chunk.splitlines():
        m = open_re.search(line)
        if m:
            pending[m.group(2)] = {
                "side": m.group(1),
                "symbol": m.group(2),
                "entry_price": float(m.group(3)),
                "leverage": int(m.group(4)),
                "stake_usd": float(m.group(5)),
            }
            continue
        m = exit_re.search(line)
        if m and m.group(1) in pending:
            pending[m.group(1)]["exit_reason"] = m.group(2)
            continue
        m = close_re.search(line)
        if m:
            sym = m.group(2)
            base = pending.pop(sym, {})
            trades.append(
                {
                    "id": int(m.group(1)),
                    "symbol": sym,
                    "final_pnl": float(m.group(3)),
                    **base,
                }
            )
    by_id: dict[int, dict] = {}
    for t in trades:
        by_id[int(t["id"])] = t
    return sorted(by_id.values(), key=lambda x: x["id"])


def main() -> None:
    from elite_pro_state import import_closed_batch, load_closed, state_db_path

    rows: list[dict] = []
    for exact in PANEL_EXACT:
        row = dict(exact)
        row["restored_from_log"] = True
        row["entry_time"] = row.get("entry_time") or row["exit_time"]
        row["duration"] = row.get("duration", 0)
        rows.append(row)

    for log_row in _parse_log_session():
        if int(log_row["id"]) in PANEL_IDS:
            continue
        log_row["restored_from_log"] = True
        log_row["exit_time"] = log_row.get("exit_time") or "2026-05-21 14:45:00"
        rows.append(log_row)

    rows.sort(key=lambda x: int(x["id"]))
    n = import_closed_batch(rows, merge=True, overwrite=True)
    loaded = load_closed()
    wins = sum(1 for r in loaded if float(r.get("final_pnl", 0)) > 0)
    print(f"DB: {state_db_path()}")
    print(f"İçe aktarıldı/güncellendi: {n} | Toplam DB: {len(loaded)}")
    print(f"Kazanç: {wins} | Kayıp: {len(loaded) - wins}")
    print(f"Final PnL toplam: ${sum(float(r.get('final_pnl', 0)) for r in loaded):.2f}")


if __name__ == "__main__":
    main()
