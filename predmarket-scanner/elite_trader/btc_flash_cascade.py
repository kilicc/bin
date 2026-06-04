"""BTC ani şelale — 1m wick, hacim/kitap onayı, doğrudan BTC + beta alt SHORT."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

_BTC_SYMS = frozenset({"BTCUSDT", "BTC"})
_lock_phase: str = "idle"
_lock_updated: float = 0.0

# Beta: düşük = BTC ile daha senkron (önce taranır)
_BETA_TIER: dict[str, int] = {
    "ETHUSDT": 0,
    "SOLUSDT": 0,
    "BNBUSDT": 0,
    "XRPUSDT": 1,
    "DOGEUSDT": 1,
    "LINKUSDT": 1,
    "ADAUSDT": 1,
    "AVAXUSDT": 2,
    "APTUSDT": 3,
    "ARBUSDT": 3,
    "OPUSDT": 3,
    "SUIUSDT": 2,
}


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return _env_bool("MEGA_BTC_CASCADE_ENABLED", True)


def _norm(sym: str) -> str:
    s = str(sym or "").upper().strip()
    return s if s.endswith("USDT") else f"{s}USDT"


def beta_tier(symbol: str) -> int:
    return _BETA_TIER.get(_norm(symbol), 2)


def sort_cascade_symbols(symbols: list[str], btc_state: dict[str, Any] | None = None) -> list[str]:
    """Şelalede yüksek beta önce; recovery'de düşük beta önce SHORT riski azaltır."""
    phase = str((btc_state or {}).get("phase") or "")
    reverse = phase in ("recovery", "capitulation")

    def key(s: str) -> tuple:
        su = _norm(s)
        if su in _BTC_SYMS:
            return (0, 0, su)
        t = beta_tier(su)
        return (1, -t if reverse else t, su)

    return sorted(symbols, key=key)


def _btc_prices(price_history: dict[str, list]) -> list[float]:
    for sym in _BTC_SYMS:
        hist = price_history.get(sym) or price_history.get(sym.replace("USDT", "")) or []
        out = [float(h.get("price") or 0) for h in hist if float(h.get("price") or 0) > 0]
        if len(out) >= 4:
            return out
    return []


def _cascade_from_1m_klines(kl: list[dict[str, Any]], cur: float) -> dict[str, Any] | None:
    if len(kl) < 8:
        return None
    include_forming = _env_bool("MEGA_BTC_CASCADE_INCLUDE_FORMING", True)
    completed = kl[:-1] if len(kl) > 1 else kl
    lb = max(6, min(24, _env_int("MEGA_BTC_CASCADE_KLINE_LOOKBACK", 14)))
    window = (kl[-lb:] if include_forming else completed[-lb:])
    if include_forming and window:
        last = dict(window[-1])
        last["c"] = cur if cur > 0 else last.get("c")
        last["h"] = max(float(last.get("h") or 0), cur)
        last["l"] = min(float(last.get("l") or 0), cur) if float(last.get("l") or 0) > 0 else cur
        window[-1] = last
    highs = [float(k.get("h") or 0) for k in window]
    lows = [float(k.get("l") or 0) for k in window]
    if not highs or not lows:
        return None
    peak = max(highs)
    low = min(lows)
    if peak <= 0 or low <= 0 or low >= peak:
        return None

    drop_pct = (peak - low) / peak * 100.0
    min_drop = _env_float("MEGA_BTC_CASCADE_MIN_DROP_PCT", 0.22)
    max_drop = _env_float("MEGA_BTC_CASCADE_MAX_DROP_PCT", 3.5)
    if drop_pct < min_drop or drop_pct > max_drop:
        return None

    recovery_frac = (cur - low) / max(peak - low, 1e-12)
    bounce_pct = (cur - low) / low * 100.0 if low > 0 else 0.0
    last_c = cur if cur > 0 else float(window[-1].get("c") or 0)
    prev_c = float(window[-2].get("c") or last_c) if len(window) >= 2 else last_c
    mom_down = last_c < prev_c
    mom_up = last_c > prev_c

    cap_recovery = _env_float("MEGA_BTC_CASCADE_CAPITULATION_RECOVERY", 0.08)
    rec_recovery = _env_float("MEGA_BTC_CASCADE_RECOVERY_FRAC", 0.22)

    if recovery_frac >= rec_recovery:
        phase = "recovery"
    elif recovery_frac >= cap_recovery and mom_up:
        phase = "capitulation"
    elif mom_down or recovery_frac < cap_recovery:
        phase = "cascade_down"
    else:
        phase = "cascade_down"

    return {
        "btc_cascade": True,
        "phase": phase,
        "source": "1m_klines",
        "btc_peak": round(peak, 4),
        "btc_low": round(low, 4),
        "btc_drop_pct": round(drop_pct, 4),
        "btc_recovery_frac": round(recovery_frac, 4),
        "btc_bounce_pct": round(bounce_pct, 4),
        "momentum_down": mom_down,
        "momentum_up": mom_up,
        "updated_at": time.time(),
    }


def _cascade_from_ticks(
    price_history: dict[str, list],
    cur: float,
) -> dict[str, Any] | None:
    prices = _btc_prices(price_history)
    if len(prices) < 4:
        return None
    lookback = max(8, min(120, _env_int("MEGA_BTC_CASCADE_TICK_LOOKBACK", 48)))
    window = prices[-lookback:]
    peak_idx = max(range(len(window)), key=lambda i: window[i])
    peak = window[peak_idx]
    post = window[peak_idx:]
    if len(post) < 2:
        return None
    low = min(post)
    if low <= 0 or low >= peak:
        return None

    drop_pct = (peak - low) / peak * 100.0
    min_drop = _env_float("MEGA_BTC_CASCADE_MIN_DROP_PCT", 0.22)
    max_drop = _env_float("MEGA_BTC_CASCADE_MAX_DROP_PCT", 3.5)
    if drop_pct < min_drop or drop_pct > max_drop:
        return None

    recovery_frac = (cur - low) / max(peak - low, 1e-12)
    bounce_pct = (cur - low) / low * 100.0 if low > 0 else 0.0
    mom_down = len(window) >= 2 and window[-1] < window[-2]
    mom_up = len(window) >= 2 and window[-1] > window[-2]

    cap_recovery = _env_float("MEGA_BTC_CASCADE_CAPITULATION_RECOVERY", 0.08)
    rec_recovery = _env_float("MEGA_BTC_CASCADE_RECOVERY_FRAC", 0.22)

    if recovery_frac >= rec_recovery:
        phase = "recovery"
    elif recovery_frac >= cap_recovery and mom_up:
        phase = "capitulation"
    else:
        phase = "cascade_down"

    return {
        "btc_cascade": True,
        "phase": phase,
        "source": "ticks",
        "btc_peak": round(peak, 4),
        "btc_low": round(low, 4),
        "btc_drop_pct": round(drop_pct, 4),
        "btc_recovery_frac": round(recovery_frac, 4),
        "btc_bounce_pct": round(bounce_pct, 4),
        "momentum_down": mom_down,
        "momentum_up": mom_up,
        "updated_at": time.time(),
    }


def _attach_context_metrics(state: dict[str, Any]) -> dict[str, Any]:
    try:
        from elite_trader.berserk2_btc_context import get_btc_context

        ctx = get_btc_context()
        state["btc_vol_ratio"] = ctx.get("btc_vol_ratio")
        state["btc_vol_spike"] = bool(ctx.get("btc_vol_spike"))
        state["btc_book_imbalance"] = ctx.get("btc_book_imbalance")
        state["btc_regime"] = ctx.get("btc_regime")
        wick = ctx.get("btc_1m_wick_drop_pct")
        if wick is not None and float(state.get("btc_drop_pct") or 0) < float(wick):
            state["btc_drop_pct"] = float(wick)
    except Exception:
        pass
    return state


def cascade_volume_confirmed(state: dict[str, Any] | None) -> bool:
    if not _env_bool("MEGA_BTC_CASCADE_REQUIRE_VOL", True):
        return True
    if not state:
        return False
    if state.get("btc_vol_spike"):
        return True
    try:
        from elite_trader.berserk2_btc_context import get_btc_context

        ctx = get_btc_context()
        if ctx.get("btc_vol_spike"):
            return True
        ratio = float(ctx.get("btc_vol_ratio") or state.get("btc_vol_ratio") or 0)
        return ratio >= _env_float("MEGA_BTC_VOL_SPIKE_RATIO", 1.55)
    except Exception:
        return True


def cascade_book_confirms_short(state: dict[str, Any] | None) -> bool:
    if not _env_bool("MEGA_BTC_CASCADE_REQUIRE_BOOK", True):
        return True
    imb = float((state or {}).get("btc_book_imbalance") or 0)
    if imb == 0:
        try:
            from elite_trader.berserk2_btc_context import get_btc_context

            imb = float(get_btc_context().get("btc_book_imbalance") or 0)
        except Exception:
            return True
    thr = _env_float("MEGA_BTC_CASCADE_SHORT_BOOK_IMB_BPS", -1.5)
    return imb <= thr


def cascade_book_confirms_long(state: dict[str, Any] | None) -> bool:
    if not _env_bool("MEGA_BTC_CASCADE_REQUIRE_BOOK", True):
        return True
    imb = float((state or {}).get("btc_book_imbalance") or 0)
    if imb == 0:
        try:
            from elite_trader.berserk2_btc_context import get_btc_context

            imb = float(get_btc_context().get("btc_book_imbalance") or 0)
        except Exception:
            return True
    thr = _env_float("MEGA_BTC_CASCADE_LONG_BOOK_IMB_BPS", 0.8)
    return imb >= thr


def detect_btc_cascade(
    price_history: dict[str, list],
    *,
    price: float | None = None,
) -> dict[str, Any] | None:
    if not enabled():
        return None

    cur = 0.0
    if price is not None and price > 0:
        cur = float(price)
    else:
        try:
            import binance_elite_pro as bep

            cur = float(bep._price_cache.get("BTCUSDT") or bep._price_cache.get("BTC") or 0)
        except Exception:
            pass
    if cur <= 0:
        prices = _btc_prices(price_history)
        if prices:
            cur = prices[-1]
    if cur <= 0:
        return None

    st: dict[str, Any] | None = None
    if _env_bool("MEGA_BTC_CASCADE_TICKS_FIRST", True):
        st = _cascade_from_ticks(price_history, cur)
    try:
        from elite_trader.berserk2_btc_context import get_btc_klines_cached

        kl = get_btc_klines_cached()
        if kl:
            st_kl = _cascade_from_1m_klines(kl, cur)
            if st_kl:
                if not st or float(st_kl.get("btc_drop_pct") or 0) >= float(
                    st.get("btc_drop_pct") or 0
                ):
                    st = st_kl
    except Exception:
        pass
    if not st:
        st = _cascade_from_ticks(price_history, cur)
    if not st:
        return None
    out = _attach_context_metrics(st)
    _remember_phase(out)
    return out


def _remember_phase(state: dict[str, Any] | None) -> str:
    global _lock_phase, _lock_updated
    if state:
        _lock_phase = str(state.get("phase") or "idle")
        _lock_updated = float(state.get("updated_at") or time.time())
        return _lock_phase
    return _lock_phase


def btc_cascade_phase(price_history: dict[str, list] | None = None) -> str:
    if price_history is None:
        try:
            import binance_elite_pro as bep

            price_history = getattr(bep, "price_history", {}) or {}
        except Exception:
            price_history = {}
    st = detect_btc_cascade(price_history)
    if st:
        return _remember_phase(st)
    if time.time() - _lock_updated < _env_float("MEGA_BTC_CASCADE_PHASE_TTL_SEC", 45.0):
        return _lock_phase
    return "idle"


def bounce_favors_long(
    price_history: dict[str, list] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    BTC dipten dönüş / toparlanma — tarama LONG, fade-bounce SHORT kapalı.
    Capitulation + momentum_up veya erken recovery_frac ile aktif.
    """
    if not enabled() or not _env_bool("MEGA_BOUNCE_FAVOR_LONG", False):
        return False, {}
    if price_history is None:
        try:
            import binance_elite_pro as bep

            price_history = getattr(bep, "price_history", {}) or {}
        except Exception:
            price_history = {}
    st = detect_btc_cascade(price_history)
    if not st:
        return False, {}
    phase = str(st.get("phase") or "")
    rec = float(st.get("btc_recovery_frac") or 0)
    min_rec = _env_float("MEGA_BTC_CASCADE_LONG_MIN_RECOVERY", 0.04)
    mom_up = bool(st.get("momentum_up"))
    if phase in ("capitulation", "recovery") and mom_up and rec >= min_rec:
        return True, st
    if (
        phase == "cascade_down"
        and mom_up
        and rec >= _env_float("MEGA_BTC_CASCADE_LATE_SHORT_RECOVERY", 0.10)
    ):
        return True, st
    return False, st


def cascade_blocks_late_short(
    price_history: dict[str, list] | None = None,
) -> tuple[bool, str]:
    """Toparlanma / erken bounce — geç SHORT (ekrandaki zararlı kısa pozisyonlar)."""
    if not enabled():
        return False, ""
    if price_history is None:
        try:
            import binance_elite_pro as bep

            price_history = getattr(bep, "price_history", {}) or {}
        except Exception:
            return False, ""
    st = detect_btc_cascade(price_history)
    if not st:
        return False, ""
    phase = str(st.get("phase") or "")
    rec = float(st.get("btc_recovery_frac") or 0)
    if phase in ("recovery", "capitulation"):
        return True, f"btc_cascade_late_short_{phase}"
    bounce_thr = _env_float("MEGA_BTC_CASCADE_LATE_SHORT_RECOVERY", 0.10)
    if phase == "cascade_down" and rec >= bounce_thr and st.get("momentum_up"):
        return True, "btc_cascade_early_bounce"
    return False, ""


def _signal_time() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def build_cascade_direct_btc_short(
    price: float,
    btc_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Doğrudan BTCUSDT SHORT — şelale düşüşü."""
    if not _env_bool("MEGA_BTC_CASCADE_DIRECT_BTC", True):
        return None
    if str(btc_state.get("phase")) != "cascade_down":
        return None
    if not cascade_volume_confirmed(btc_state):
        return None
    if not cascade_book_confirms_short(btc_state):
        return None
    drop = float(btc_state.get("btc_drop_pct") or 0)
    if drop < _env_float("MEGA_BTC_CASCADE_MIN_DROP_PCT", 0.22):
        return None
    return {
        "symbol": "BTCUSDT",
        "type": "SHORT",
        "price": price,
        "change": round(-drop, 4),
        "time": _signal_time(),
        "strength": "Strong" if drop >= 0.45 else "Medium",
        "signal_source": "MegaBtcCascade-BTC-SHORT",
        "target_mode": "mega",
        "mega_btc_cascade": True,
        "mega_btc_cascade_short": True,
        "mega_btc_cascade_direct": True,
        "btc_cascade_phase": "cascade_down",
        "btc_drop_pct": drop,
    }


def build_cascade_direct_btc_long(
    price: float,
    btc_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Doğrudan BTCUSDT LONG — dip / capitulation."""
    if not _env_bool("MEGA_BTC_CASCADE_DIRECT_BTC", True):
        return None
    phase = str(btc_state.get("phase") or "")
    if phase not in ("capitulation", "cascade_down"):
        return None
    rec = float(btc_state.get("btc_recovery_frac") or 0)
    if rec < _env_float("MEGA_BTC_CASCADE_LONG_MIN_RECOVERY", 0.04):
        return None
    if not cascade_book_confirms_long(btc_state):
        return None
    bounce = float(btc_state.get("btc_bounce_pct") or 0)
    return {
        "symbol": "BTCUSDT",
        "type": "LONG",
        "price": price,
        "change": round(bounce, 4),
        "time": _signal_time(),
        "strength": "Strong" if bounce >= 0.12 else "Medium",
        "signal_source": "MegaBtcCascade-BTC-LONG",
        "target_mode": "mega",
        "mega_btc_cascade": True,
        "mega_btc_cascade_long": True,
        "mega_btc_cascade_direct": True,
        "btc_cascade_phase": phase,
        "btc_drop_pct": btc_state.get("btc_drop_pct"),
    }


def build_cascade_follow_short(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    btc_state: dict[str, Any],
) -> dict[str, Any] | None:
    if str(btc_state.get("phase")) != "cascade_down":
        return None
    sym = _norm(symbol)
    if sym in _BTC_SYMS:
        return None
    if not cascade_volume_confirmed(btc_state):
        return None

    hist = price_history.get(sym) or price_history.get(sym.replace("USDT", "")) or []
    if len(hist) < 3:
        return None
    prices = [float(h.get("price") or 0) for h in hist[-8:] if float(h.get("price") or 0) > 0]
    if len(prices) < 3:
        return None
    lb = max(2, min(5, _env_int("MEGA_BTC_CASCADE_ALT_MOM_BARS", 3)))
    old = prices[-1 - min(lb, len(prices) - 1)]
    if old <= 0:
        return None
    change = (price - old) / old * 100.0
    min_mom = _env_float("MEGA_BTC_CASCADE_SHORT_MIN_ALT_MOMENTUM", -2.5)
    max_mom = _env_float("MEGA_BTC_CASCADE_SHORT_MAX_ALT_MOMENTUM", 0.15)
    if change > max_mom or change < min_mom:
        return None
    if prices[-1] >= prices[-2] and change > 0:
        return None

    drop = float(btc_state.get("btc_drop_pct") or 0)
    return {
        "symbol": sym,
        "type": "SHORT",
        "price": price,
        "change": round(change, 4),
        "time": _signal_time(),
        "strength": "Strong" if drop >= 0.55 else "Medium",
        "signal_source": "MegaBtcCascade-SHORT",
        "target_mode": "mega",
        "mega_btc_cascade": True,
        "mega_btc_cascade_short": True,
        "btc_cascade_phase": "cascade_down",
        "btc_drop_pct": drop,
        "beta_tier": beta_tier(sym),
    }


def build_cascade_capitulation_long(
    price_history: dict[str, list],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    st = detect_btc_cascade(price_history)
    if not st or str(st.get("phase")) not in ("capitulation", "cascade_down"):
        return None
    if float(st.get("btc_recovery_frac") or 0) < _env_float(
        "MEGA_BTC_CASCADE_LONG_MIN_RECOVERY", 0.04
    ):
        return None

    try:
        import binance_elite_pro as bep

        px = float(bep._price_cache.get("BTCUSDT") or bep._price_cache.get("BTC") or 0)
    except Exception:
        px = 0.0
    prices = _btc_prices(price_history)
    if px <= 0 and prices:
        px = prices[-1]
    if px <= 0:
        return None

    direct = build_cascade_direct_btc_long(px, st)
    if direct:
        return direct

    prof = dict(profile or {})
    prof["berserk2_flash_drop_max_pct"] = _env_float(
        "MEGA_BTC_CASCADE_FLASH_MAX_DROP_PCT", 3.5
    )
    from elite_trader.berserk2_flash_reversal import build_flash_reversal_candidate

    cand = build_flash_reversal_candidate("BTCUSDT", px, price_history, prof, rank=0)
    if not cand:
        return None
    cand["signal_source"] = "MegaBtcCascade-LONG"
    cand["target_mode"] = "mega"
    cand["mega_btc_cascade"] = True
    cand["mega_btc_cascade_long"] = True
    cand["btc_cascade_phase"] = st.get("phase")
    return cand


def cascade_snapshot(price_history: dict[str, list] | None = None) -> dict[str, Any]:
    if price_history is None:
        try:
            import binance_elite_pro as bep

            price_history = getattr(bep, "price_history", {}) or {}
        except Exception:
            price_history = {}
    st = detect_btc_cascade(price_history) or {}
    phase = str(st.get("phase") or btc_cascade_phase(price_history))
    labels = {
        "idle": "Yok",
        "cascade_down": "Şelale ↓ (SHORT)",
        "capitulation": "Dip (LONG)",
        "recovery": "Toparlanma",
    }
    return {
        "enabled": enabled(),
        "phase": phase,
        "phase_label": labels.get(phase, phase),
        "drop_pct": st.get("btc_drop_pct"),
        "recovery_frac": st.get("btc_recovery_frac"),
        "bounce_pct": st.get("btc_bounce_pct"),
        "source": st.get("source"),
        "vol_spike": st.get("btc_vol_spike"),
        "vol_ratio": st.get("btc_vol_ratio"),
        "book_imbalance": st.get("btc_book_imbalance"),
        "btc_regime": st.get("btc_regime"),
    }
