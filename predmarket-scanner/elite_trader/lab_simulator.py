"""Counterfactual stake/leverage simulation — no position opens."""
from __future__ import annotations

import json
import os
from typing import Any

_DEFAULT_PRESETS = [
    {"label": "$500@5x", "stake_usd": 500, "leverage": 5},
    {"label": "$1000@5x", "stake_usd": 1000, "leverage": 5},
    {"label": "$500@10x", "stake_usd": 500, "leverage": 10},
    {"label": "$250@3x", "stake_usd": 250, "leverage": 3},
]


def _presets() -> list[dict[str, Any]]:
    raw = os.getenv("LAB_SIM_PRESETS", "").strip()
    if not raw:
        return list(_DEFAULT_PRESETS)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and parsed:
            return parsed
    except json.JSONDecodeError:
        pass
    return list(_DEFAULT_PRESETS)


def _fee_round_trip(stake: float, lev: int) -> float:
    notional = stake * lev
    rate = float(os.getenv("ELITE_FEE_RATE", "0.0005"))
    return notional * rate * 2


def _tp_sl_gross(stake: float, lev: int) -> tuple[float, float]:
    tp_pct = float(os.getenv("ELITE_TP_STAKE_PCT", "0.0055"))
    sl_pct = float(os.getenv("ELITE_SL_STAKE_PCT", "0.003"))
    tp_g = stake * tp_pct * lev
    sl_g = stake * sl_pct * lev
    return tp_g, sl_g


def simulate_signal(
    signal: dict[str, Any],
    price: float,
    *,
    presets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Estimate TP/SL net outcomes for preset stake/leverage combos."""
    sym = str(signal.get("symbol") or "")
    side = str(signal.get("type") or signal.get("side") or "LONG").upper()
    px = float(price or signal.get("price") or 0)
    if px <= 0:
        return {"ok": False, "error": "price required"}
    rows = []
    for p in presets or _presets():
        stake = float(p.get("stake_usd") or 500)
        lev = max(int(p.get("leverage") or 5), 1)
        fee = _fee_round_trip(stake, lev)
        tp_g, sl_g = _tp_sl_gross(stake, lev)
        margin = stake
        rows.append(
            {
                "label": p.get("label") or f"${stake:.0f}@{lev}x",
                "stake_usd": stake,
                "leverage": lev,
                "margin_usd": margin,
                "fee_est_usd": round(fee, 4),
                "tp_gross_usd": round(tp_g, 4),
                "sl_gross_usd": round(-sl_g, 4),
                "tp_net_usd": round(tp_g - fee, 4),
                "sl_net_usd": round(-sl_g - fee, 4),
            }
        )
    return {
        "ok": True,
        "symbol": sym,
        "side": side,
        "price": px,
        "presets": rows,
        "note": "Counterfactual — pozisyon açılmaz",
    }


def simulate_from_scan_cache(symbol: str | None = None) -> dict[str, Any]:
    from elite_trader.mega_live import scan_summary

    scan = scan_summary()
    events = list(scan.get("feed") or scan.get("recent") or scan.get("events") or [])
    if not events:
        return {"ok": False, "error": "no scan cache"}
    ev = events[0]
    if symbol:
        for e in events:
            if str(e.get("symbol", "")).upper() == symbol.upper():
                ev = e
                break
    sig = {
        "symbol": ev.get("symbol"),
        "type": ev.get("side") or ev.get("type"),
        "price": ev.get("price"),
    }
    price = float(ev.get("price") or 0)
    return simulate_signal(sig, price)
