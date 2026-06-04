#!/usr/bin/env python3
"""Elite 9005 momentum backtest — watchlist dışı USDT-M perpetual coinler."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCENARIO = ROOT / "scenarios" / "binance_elite_8300_9005.env"
OUT_PATH = ROOT / "data" / "elite_non_watchlist_bt.json"

load_dotenv(SCENARIO, override=True)
os.environ.setdefault("BN_FUT_MODE", "main")  # public klines — main fapi
os.environ["BINANCE_FUTURES_TESTNET"] = "0"
os.environ["BINANCE_FUTURES_DEMO"] = "0"
os.environ["BINANCE_AUTH_QUICK"] = "1"

MIN_EDGE = float(os.getenv("ELITE_MIN_EDGE", "0.045"))
MIN_FORMULA = float(os.getenv("ELITE_MIN_FORMULA_SCORE", "0.52"))
TP_PCT = float(os.getenv("ELITE_TP_STAKE_PCT", "0.007"))
SL_PCT = float(os.getenv("ELITE_SL_STAKE_PCT", "0.025"))
TP_TRIG = float(os.getenv("ELITE_TP_TRIGGER_FRAC", "0.85"))
MOM_THRESH = 0.12
LOOKBACK = 10
DAYS = int(os.getenv("ELITE_BT_DAYS", "7"))
INTERVAL = "1m"
MAX_COINS = int(os.getenv("ELITE_BT_MAX_COINS", "18"))

_wl = os.getenv("BINANCE_WATCHLIST", "")
WATCHLIST = {s.strip().upper() for s in _wl.split(",") if s.strip()}


def edge_from_change(change_pct: float) -> float:
    move = abs(change_pct) / 100.0
    return min(0.35, move * 40.0)


def formula_from_change(change_pct: float) -> float:
    move = abs(change_pct) / 100.0
    return MIN_FORMULA + min(0.23, move * 15.0)


def strength(change_pct: float) -> str:
    a = abs(change_pct)
    if a > 0.5:
        return "Strong"
    if a > 0.25:
        return "Medium"
    return "Weak"


def backtest_symbol(candles: list[dict]) -> dict:
    if len(candles) < LOOKBACK + 30:
        return {"trades": 0, "wins": 0, "win_rate": 0.0, "pnl_pct": 0.0, "notes": "insufficient data"}

    tp_move = TP_PCT * TP_TRIG
    sl_move = SL_PCT
    wins = losses = 0
    pnl_sum = 0.0
    i = LOOKBACK
    while i < len(candles) - 5:
        window = candles[i - LOOKBACK : i]
        price = float(candles[i]["c"])
        old = float(window[0]["c"])
        change = ((price - old) / old) * 100 if old else 0.0
        boost = 0.0
        if len(window) > 4:
            op4 = float(window[-4]["c"])
            micro = ((price - op4) / op4) * 100 if op4 else 0.0
            if abs(micro) > abs(change) * 0.35:
                boost = 0.02 * (1 if change * micro > 0 else -1)
        adj = change + boost
        if abs(adj) <= MOM_THRESH:
            i += 1
            continue
        if edge_from_change(adj) < MIN_EDGE or formula_from_change(adj) < MIN_FORMULA:
            i += 1
            continue
        if strength(adj) == "Weak":
            i += 1
            continue
        side = "LONG" if adj > 0 else "SHORT"
        entry = float(candles[i + 1]["o"])
        if entry <= 0:
            i += 1
            continue
        closed = False
        for j in range(i + 2, min(i + 120, len(candles))):
            hi = float(candles[j]["h"])
            lo = float(candles[j]["l"])
            if side == "LONG":
                up = (hi - entry) / entry
                dn = (entry - lo) / entry
                if dn >= sl_move:
                    losses += 1
                    pnl_sum -= sl_move * 100
                    closed = True
                    i = j + 1
                    break
                if up >= tp_move:
                    wins += 1
                    pnl_sum += tp_move * 100
                    closed = True
                    i = j + 1
                    break
            else:
                up = (hi - entry) / entry
                dn = (entry - lo) / entry
                if up >= sl_move:
                    losses += 1
                    pnl_sum -= sl_move * 100
                    closed = True
                    i = j + 1
                    break
                if dn >= tp_move:
                    wins += 1
                    pnl_sum += tp_move * 100
                    closed = True
                    i = j + 1
                    break
        if not closed:
            last = float(candles[min(i + 119, len(candles) - 1)]["c"])
            pnl = ((last - entry) / entry if side == "LONG" else (entry - last) / entry) * 100
            pnl_sum += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            i += 120
        if not closed:
            i += 1

    n = wins + losses
    return {
        "trades": n,
        "wins": wins,
        "win_rate": round(wins / n, 4) if n else 0.0,
        "pnl_pct": round(pnl_sum, 3),
        "notes": f"{DAYS}d {INTERVAL} elite-momentum sim",
    }


def main() -> None:
    from binance_futures_trader.client import BinanceFuturesClient, MAIN_BASE

    import binance_futures_trader.config as cfg
    import binance_futures_trader.client as bcl

    cfg.MODE = "main"
    cfg.TESTNET = False
    cfg.FUTURES_DEMO = False
    cfg.API_KEY = ""
    bcl.api_base = lambda: MAIN_BASE  # type: ignore

    client = BinanceFuturesClient()
    client.paper = True

    print(f"Watchlist ({len(WATCHLIST)}): {sorted(WATCHLIST)}")

    universe = client.list_tradeable_usdt_perpetuals()
    print(f"USDT-M perpetual (TRADING): {len(universe)}")

    vol_map: dict[str, float] = {}
    try:
        tickers = client._get("/fapi/v1/ticker/24hr")  # noqa: SLF001
        for t in tickers or []:
            sym = t.get("symbol")
            if sym and sym.endswith("USDT"):
                vol_map[sym] = float(t.get("quoteVolume") or 0)
    except Exception as e:
        print(f"24hr ticker failed: {e}")

    outside = [s for s in universe if s not in WATCHLIST]
    outside.sort(key=lambda s: vol_map.get(s, 0), reverse=True)
    candidates = outside[:MAX_COINS]

    # baseline: watchlist coins
    watch_results = []
    for sym in sorted(WATCHLIST):
        coin = sym.replace("USDT", "")
        try:
            c = client.klines_history(coin, INTERVAL, days=DAYS)
            r = backtest_symbol(c)
            r["symbol"] = sym
            watch_results.append(r)
        except Exception as ex:
            watch_results.append({"symbol": sym, "trades": 0, "notes": str(ex)})

    outside_results = []
    for sym in candidates:
        coin = sym.replace("USDT", "")
        try:
            c = client.klines_history(coin, INTERVAL, days=DAYS)
            r = backtest_symbol(c)
            r["symbol"] = sym
            r["quote_volume_24h"] = vol_map.get(sym, 0)
            outside_results.append(r)
        except Exception as ex:
            outside_results.append(
                {"symbol": sym, "trades": 0, "notes": str(ex), "quote_volume_24h": vol_map.get(sym, 0)}
            )

    not_tracked_top = [
        {"symbol": s, "quote_volume_24h": vol_map.get(s, 0)}
        for s in outside[:30]
    ]

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "scenario": SCENARIO.name,
        "watchlist_count": len(WATCHLIST),
        "universe_count": len(universe),
        "params": {
            "MIN_EDGE": MIN_EDGE,
            "MIN_FORMULA": MIN_FORMULA,
            "TP_PCT": TP_PCT,
            "SL_PCT": SL_PCT,
            "TP_TRIG": TP_TRIG,
            "DAYS": DAYS,
            "INTERVAL": INTERVAL,
        },
        "watchlist_backtest": watch_results,
        "outside_backtest": outside_results,
        "top_liquid_not_tracked": not_tracked_top,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved: {OUT_PATH}")
    print("\n=== OUTSIDE WATCHLIST (by 24h quote volume) ===")
    for r in outside_results:
        print(
            f"  {r.get('symbol','?'):14} vol=${r.get('quote_volume_24h',0)/1e6:.0f}M "
            f"trades={r.get('trades',0)} wr={r.get('win_rate',0):.1%} pnl={r.get('pnl_pct',0):+.2f}%"
        )
    print("\n=== WATCHLIST BASELINE ===")
    for r in watch_results:
        print(
            f"  {r.get('symbol','?'):14} trades={r.get('trades',0)} "
            f"wr={r.get('win_rate',0):.1%} pnl={r.get('pnl_pct',0):+.2f}%"
        )


if __name__ == "__main__":
    main()
