"""Şelale / aktif rejimde incelemedeki pozisyonları kapatıp slot aç."""
from __future__ import annotations

import os
from typing import Any


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def swap_enabled() -> bool:
    return _env_bool("MEGA_SLOT_SWAP_ENABLED", True)


def market_accelerating(price_history: dict | None = None) -> tuple[bool, str]:
    """BTC şelale veya MEGA active rejim."""
    if _env_bool("MEGA_SLOT_SWAP_CASCADE_ONLY", False):
        try:
            from elite_trader.btc_flash_cascade import cascade_snapshot

            casc = cascade_snapshot(price_history) or {}
            if casc.get("active"):
                return True, str(casc.get("phase_label") or "cascade")
        except Exception:
            pass
        return False, ""
    try:
        from elite_trader.btc_flash_cascade import cascade_snapshot

        casc = cascade_snapshot(price_history) or {}
        if casc.get("active"):
            return True, str(casc.get("phase_label") or "cascade")
    except Exception:
        pass
    try:
        from elite_trader.mega_market_regime import snapshot as regime_snapshot

        r = regime_snapshot() or {}
        if str(r.get("regime") or "").lower() == "active":
            return True, "market_active"
    except Exception:
        pass
    return False, ""


def pick_swap_victim(positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """İncelemedeki en zayıf pozisyon."""
    candidates = [p for p in positions if p.get("mega_sl_review")]
    if not candidates:
        return None

    def _gross(p: dict[str, Any]) -> float:
        try:
            from elite_trader.mega_live import _mega_api_gross_unreal

            return float(_mega_api_gross_unreal(p))
        except Exception:
            return float(p.get("unrealized_pnl") or 0)

    return min(
        candidates,
        key=lambda p: (
            _gross(p),
            -float(p.get("mega_sl_review_since") or 0),
        ),
    )


def maybe_swap_for_entry(
    signal: dict[str, Any] | None,
    *,
    price_history: dict | None = None,
    close_fn: Any = None,
    positions: list[dict[str, Any]] | None = None,
    slots_remaining: int = 0,
) -> bool:
    """
    Slot dolu + hızlanan piyasa → incelemedeki pozisyonu kapat.
    Returns True if a swap close was attempted.
    """
    if not swap_enabled() or slots_remaining > 0:
        return False
    if signal is None:
        return False
    accel, tag = market_accelerating(price_history)
    if not accel:
        return False
    if positions is None:
        try:
            from elite_trader import mega_live as ml

            positions = list(ml._mega_positions)
            slots_remaining = ml._mega_slots_remaining()
        except Exception:
            return False
    if slots_remaining > 0:
        return False
    victim = pick_swap_victim(positions)
    if not victim:
        return False
    pid = int(victim.get("id") or 0)
    if pid <= 0:
        return False
    reason = f"SWAP-FREE-SLOT:{tag}"
    victim["slot_swap"] = True
    if close_fn is not None:
        return bool(close_fn(pid, reason))
    try:
        from elite_trader.mega_live import close_mega_position

        return bool(close_mega_position(pid, reason))
    except Exception:
        return False
