"""Yıldızlı coinlerde brüt −%25 stake SL + BTC rejim recovery."""
from __future__ import annotations

import os
import time
from typing import Any


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def star_sl_enabled() -> bool:
    return _env_bool("MEGA_STAR_SL_ENABLED", False)


def loss_stake_frac() -> float:
    return max(0.05, min(0.50, _env_float("MEGA_STAR_SL_STAKE_FRAC", 0.25)))


def loss_floor_usd(stake_usd: float) -> float:
    return -loss_stake_frac() * max(float(stake_usd), 1.0)


def _gross_unreal(pos: dict[str, Any]) -> float:
    try:
        from elite_trader.mega_live import _mega_api_gross_unreal

        return float(_mega_api_gross_unreal(pos))
    except Exception:
        return float(pos.get("unrealized_pnl") or 0)


def _btc_recovery_ok(side: str, price_history: dict | None = None) -> tuple[bool, str]:
    side_u = str(side or "LONG").upper()
    try:
        from elite_trader.berserk2_btc_context import get_btc_context
        from elite_trader.mega_direction_guard import btc_bearish

        btc = dict(get_btc_context())
        regime = str(btc.get("btc_regime") or "unknown").lower()
        if regime == "unknown":
            return False, "btc_regime_unknown"
        bear, bear_tag = btc_bearish(price_history)
        if side_u == "LONG":
            if regime in ("trend_up", "chop") and not bear:
                return True, "btc_recovery_long"
            return False, bear_tag or "btc_no_long_recovery"
        if side_u == "SHORT":
            if regime == "trend_down" or bear:
                return True, "btc_recovery_short"
            if regime == "chop":
                return True, "btc_chop_short"
            return False, "btc_no_short_recovery"
    except Exception as exc:
        return False, f"btc_ctx_err:{exc}"[:40]
    return False, "btc_recovery_fail"


def _flash_sl(
    pos: dict[str, Any],
    gross: float,
    floor_usd: float,
) -> str | None:
    """Ani düşüş — inceleme modunda ek stake kaybı."""
    now = time.time()
    stake = max(float(pos.get("stake_usd") or 1), 1.0)
    extra_frac = max(0.03, _env_float("MEGA_STAR_SL_FLASH_EXTRA_FRAC", 0.08))
    window = max(0.5, _env_float("MEGA_STAR_SL_FLASH_WINDOW_SEC", 3.0))
    hist = pos.setdefault("_star_sl_gross_hist", [])
    hist.append((now, gross))
    pos["_star_sl_gross_hist"] = [(t, g) for t, g in hist if now - t <= window + 1.0]
    if len(pos["_star_sl_gross_hist"]) < 2:
        return None
    oldest_g = pos["_star_sl_gross_hist"][0][1]
    if gross - oldest_g <= -stake * extra_frac:
        return "SL-COIN25-FLASH"
    if gross <= floor_usd - stake * extra_frac * 0.5:
        return "SL-COIN25-FLASH"
    return None


def evaluate_star_sl(
    pos: dict[str, Any],
    *,
    price_history: dict | None = None,
    mode_id: str = "mega",
) -> str | None:
    """
    Yıldızlı sembol + brüt unreal <= −25% stake → inceleme.
    Recovery yoksa SL-COIN25-BTC; flash düşüşte SL-COIN25-FLASH.
    """
    if not star_sl_enabled():
        return None
    sym = str(pos.get("symbol") or "").upper()
    if not sym:
        return None
    try:
        from elite_trader.mega_coin_watch import is_starred

        if not is_starred(sym):
            return None
    except Exception:
        return None

    stake = max(float(pos.get("stake_usd") or 1), 1.0)
    gross = _gross_unreal(pos)
    floor = loss_floor_usd(stake)

    if gross > floor:
        pos.pop("mega_sl_review", None)
        pos.pop("_star_sl_gross_hist", None)
        pos.pop("mega_sl_review_since", None)
        return None

    if not pos.get("mega_sl_review"):
        pos["mega_sl_review"] = True
        pos["mega_sl_review_since"] = time.time()
        pos["mega_sl_review_gross"] = round(gross, 4)

    flash = _flash_sl(pos, gross, floor)
    if flash:
        pos["star_sl_exit"] = flash
        return flash

    ok, tag = _btc_recovery_ok(str(pos.get("side") or "LONG"), price_history)
    pos["star_sl_recovery_tag"] = tag
    if ok:
        return None

    pos["star_sl_exit"] = "SL-COIN25-BTC"
    return "SL-COIN25-BTC"


def evaluate_berserk_star_sl(
    *,
    unrealized_usd: float,
    stake_usd: float,
    side: str,
    symbol: str,
    pos: dict[str, Any] | None = None,
) -> str | None:
    """Berserk2 paper/live — aynı −%25 brüt kuralı."""
    if not star_sl_enabled():
        return None
    sym = str(symbol or "").upper()
    try:
        from elite_trader.mega_coin_watch import is_starred

        if not is_starred(sym):
            return None
    except Exception:
        return None
    stake = max(float(stake_usd), 1.0)
    gross = float(unrealized_usd)
    floor = loss_floor_usd(stake)
    if gross > floor:
        if pos is not None:
            pos.pop("mega_sl_review", None)
        return None
    p = pos if pos is not None else {}
    if not p.get("mega_sl_review"):
        p["mega_sl_review"] = True
        p["mega_sl_review_since"] = time.time()
    if pos is not None and p is pos:
        flash = _flash_sl(pos, gross, floor)
        if flash:
            return flash
    ok, _tag = _btc_recovery_ok(side)
    if ok:
        return None
    return "SL-COIN25-BTC"
