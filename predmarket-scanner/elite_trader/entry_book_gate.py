"""Giriş öncesi bookTicker — spread + fiyat kayması + anlık uPnL maliyeti."""
from __future__ import annotations

import os
from typing import Any

from elite_trader.exchange_fill_truth import _book_ticker


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def entry_book_gate_enabled() -> bool:
    return _env_bool("ELITE_ENTRY_BOOK_GATE", True)


def entry_book_gate(
    client: Any,
    *,
    symbol: str,
    side: str,
    stake_usd: float,
    leverage: int,
    signal_price: float | None = None,
    mode_id: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Market giriş öncesi son kontrol.
    LONG → ask'tan alınır; uPnL mark'a göre ≈ -(spread/2)*notional ile başlar.
    """
    if client is None or getattr(client, "paper", True):
        return True, "paper", {}
    if not entry_book_gate_enabled():
        return True, "disabled", {}

    book = _book_ticker(symbol, client=client, max_age_ms=350)
    if not book:
        return False, "bookTicker yok — market giriş yok", {}

    bid = float(book["bid"])
    ask = float(book["ask"])
    mid = float(book["mid"])
    if bid <= 0 or ask <= 0 or mid <= 0:
        return False, "book geçersiz", {}

    side_u = str(side or "LONG").upper()
    stake = max(float(stake_usd), 1.0)
    lev = max(int(leverage), 1)
    notional = stake * lev
    spread_pct = (ask - bid) / mid * 100.0
    half_spread_usd = notional * (ask - bid) / mid / 2.0

    if side_u == "LONG":
        entry_px = ask
        mark_upnl_est = (mid - ask) / mid * notional
        if signal_price and signal_price > 0:
            move_bps = (mid - float(signal_price)) / float(signal_price) * 10_000.0
            drift_bps = (ask - float(signal_price)) / float(signal_price) * 10_000.0
        else:
            move_bps = 0.0
            drift_bps = (ask - mid) / mid * 10_000.0
    else:
        entry_px = bid
        mark_upnl_est = (bid - mid) / mid * notional
        if signal_price and signal_price > 0:
            move_bps = (float(signal_price) - mid) / float(signal_price) * 10_000.0
            drift_bps = (float(signal_price) - bid) / float(signal_price) * 10_000.0
        else:
            move_bps = 0.0
            drift_bps = (mid - bid) / mid * 10_000.0

    max_spread = _env_float("ELITE_ENTRY_MAX_SPREAD_PCT", 0.10)
    try:
        from elite_trader.mode_profiles import get_profile

        prof = get_profile(mode_id) if mode_id else {}
        max_spread = float(
            prof.get("berserk2_max_spread_pct")
            or prof.get("max_spread_pct")
            or max_spread
        )
    except Exception:
        pass

    max_drift_bps = _env_float("ELITE_ENTRY_MAX_DRIFT_BPS", 14.0)
    max_move_bps = _env_float("ELITE_ENTRY_MAX_MOVE_BPS", 10.0)
    max_instant_loss = _env_float("ELITE_ENTRY_MAX_INSTANT_LOSS_USD", 0.32)
    max_neg_upnl = _env_float("ELITE_ENTRY_MAX_NEGATIVE_UPNL_USD", max_instant_loss)

    meta: dict[str, Any] = {
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "entry_px_est": entry_px,
        "spread_pct": round(spread_pct, 4),
        "half_spread_usd": round(half_spread_usd, 4),
        "instant_upnl_est": round(mark_upnl_est, 4),
        "drift_bps": round(drift_bps, 2),
        "move_bps": round(move_bps, 2),
        "signal_price": signal_price,
    }

    if spread_pct > max_spread:
        return (
            False,
            f"spread {spread_pct:.3f}% > max {max_spread:.2f}%",
            meta,
        )

    if move_bps > max_move_bps:
        return (
            False,
            f"momentum tükendi move={move_bps:.1f}bps > {max_move_bps:.0f}bps "
            f"(sinyal={signal_price} mid={mid:.6g})",
            meta,
        )

    if abs(drift_bps) > max_drift_bps:
        return (
            False,
            f"fiyat kayması {drift_bps:.1f}bps > {max_drift_bps:.0f}bps "
            f"(sinyal={signal_price} book={entry_px:.6g})",
            meta,
        )

    if mark_upnl_est < -max_neg_upnl:
        return (
            False,
            f"giriş spread kaybı ${mark_upnl_est:.2f} > ${max_neg_upnl:.2f}",
            meta,
        )

    try:
        from elite_trader.fee_economics import round_trip_fee_usd, tp_sl_gross_triggers

        tp_gross, _sl, _net, _rt = tp_sl_gross_triggers(stake, lev, mode_id)
        min_edge = _env_float("ELITE_ENTRY_MIN_EDGE_AFTER_SPREAD", 0.40)
        if tp_gross < half_spread_usd + round_trip_fee_usd(stake, lev) * 0.55 + min_edge:
            return (
                False,
                f"TP brüt ${tp_gross:.2f} spread+fee sonrası yetersiz "
                f"(spread≈${half_spread_usd:.2f})",
                meta,
            )
    except Exception:
        pass

    return True, "ok", meta
