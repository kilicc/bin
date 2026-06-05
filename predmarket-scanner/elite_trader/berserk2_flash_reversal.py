"""BERSERK2 — ani düşüş sonrası dönüşte LONG + yüksek TP (mean-reversion scalp)."""
from __future__ import annotations

import os
from typing import Any


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def flash_reversal_enabled(profile: dict[str, Any] | None = None) -> bool:
    if profile is not None and profile.get("berserk2_flash_reversal_enabled") is False:
        return False
    return _env_bool("BERSERK2_FLASH_REVERSAL_ENABLED", True)


def _profile_float(profile: dict[str, Any] | None, key: str, env_key: str, default: float) -> float:
    if profile:
        v = profile.get(key)
        if v is not None:
            return float(v)
    return _env_float(env_key, default)


def _flash_drop_state(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Tepe/dip/dönüş metrikleri — giriş veya panel izleme."""
    if not flash_reversal_enabled(profile) or price <= 0:
        return None

    hist = price_history.get(symbol) or price_history.get(symbol.replace("USDT", "")) or []
    min_bars = max(4, int(_env_float("BERSERK2_FLASH_MIN_BARS", 4)))
    if len(hist) < min_bars:
        return None

    lookback = max(
        min_bars,
        min(60, int(_profile_float(profile, "berserk2_flash_lookback_bars", "BERSERK2_FLASH_LOOKBACK_BARS", 24))),
    )
    window = hist[-lookback:]
    prices = [float(p.get("price") or 0) for p in window if float(p.get("price") or 0) > 0]
    if len(prices) < min_bars:
        return None

    peak_idx = max(range(len(prices)), key=lambda i: prices[i])
    peak = prices[peak_idx]
    if peak <= 0:
        return None

    post = prices[peak_idx:]
    if len(post) < 2:
        return None
    low = min(post)
    if low <= 0 or low >= peak:
        return None

    drop_pct = (peak - low) / peak * 100.0
    min_drop = _profile_float(profile, "berserk2_flash_drop_min_pct", "BERSERK2_FLASH_DROP_MIN_PCT", 0.15)
    max_drop = _profile_float(profile, "berserk2_flash_drop_max_pct", "BERSERK2_FLASH_DROP_MAX_PCT", 1.2)
    if drop_pct < min_drop * 0.72 or drop_pct > max_drop:
        return None

    bounce_pct = (price - low) / low * 100.0
    recovery_frac = (price - low) / max(peak - low, 1e-12)
    low_idx = peak_idx + post.index(low)
    bars_since_low = len(prices) - 1 - low_idx
    momentum_up = len(prices) >= 2 and prices[-1] > prices[-2]

    min_bounce = _profile_float(
        profile, "berserk2_flash_bounce_min_pct", "BERSERK2_FLASH_BOUNCE_MIN_PCT", 0.03
    )
    min_recovery = _profile_float(
        profile, "berserk2_flash_recovery_min_frac", "BERSERK2_FLASH_RECOVERY_MIN_FRAC", 0.06
    )
    max_recovery = _profile_float(
        profile, "berserk2_flash_recovery_max_frac", "BERSERK2_FLASH_RECOVERY_MAX_FRAC", 0.45
    )
    max_stale = max(
        2,
        int(_profile_float(profile, "berserk2_flash_max_bars_since_low", "BERSERK2_FLASH_MAX_BARS_SINCE_LOW", 8)),
    )
    tp_recovery = _profile_float(
        profile, "berserk2_flash_tp_recovery_frac", "BERSERK2_FLASH_TP_RECOVERY_FRAC", 0.72
    )
    target_px = low + (peak - low) * tp_recovery
    target_move_pct = (target_px - price) / price * 100.0 if price > 0 else 0.0

    return {
        "flash_peak_price": round(peak, 8),
        "flash_low_price": round(low, 8),
        "flash_drop_pct": round(drop_pct, 4),
        "flash_bounce_pct": round(bounce_pct, 4),
        "flash_recovery_frac": round(recovery_frac, 4),
        "flash_target_price": round(target_px, 8),
        "flash_target_move_pct": round(target_move_pct, 4),
        "flash_tp_recovery_frac": tp_recovery,
        "bars_since_low": bars_since_low,
        "momentum_up": momentum_up,
        "min_bounce_pct": min_bounce,
        "min_recovery_frac": min_recovery,
        "max_recovery_frac": max_recovery,
        "max_bars_since_low": max_stale,
        "min_drop_pct": min_drop,
    }


def detect_flash_drop_reversal(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Ani düşüş (flash) + dip sonrası yukarı dönüş → LONG adayı.
    price_history: sembol → [{price, time}, ...]
    """
    state = _flash_drop_state(symbol, price, price_history, profile)
    if not state:
        return None

    drop_pct = float(state["flash_drop_pct"])
    min_drop = float(state["min_drop_pct"])
    max_drop = _profile_float(profile, "berserk2_flash_drop_max_pct", "BERSERK2_FLASH_DROP_MAX_PCT", 1.2)
    if drop_pct < min_drop or drop_pct > max_drop:
        return None

    bounce_pct = float(state["flash_bounce_pct"])
    if bounce_pct < float(state["min_bounce_pct"]):
        return None

    recovery_frac = float(state["flash_recovery_frac"])
    min_recovery = float(state["min_recovery_frac"])
    max_recovery = float(state["max_recovery_frac"])
    if recovery_frac < min_recovery or recovery_frac > max_recovery:
        return None

    if int(state["bars_since_low"]) > int(state["max_bars_since_low"]):
        return None

    if not state["momentum_up"]:
        return None

    target_move_pct = float(state["flash_target_move_pct"])
    if target_move_pct <= float(state["min_bounce_pct"]):
        return None

    return {
        "flash_reversal": True,
        **{k: state[k] for k in state if k.startswith("flash_")},
    }


def scan_flash_reversal_watch(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Panel — yaklaşan dönüş kademeleri (henüz giriş olmasa da)."""
    from datetime import datetime

    state = _flash_drop_state(symbol, price, price_history, profile)
    if not state:
        return None

    drop_pct = float(state["flash_drop_pct"])
    min_drop = float(state["min_drop_pct"])
    if drop_pct < min_drop:
        return None

    if int(state["bars_since_low"]) > int(state["max_bars_since_low"]) + 2:
        return None

    bounce_pct = float(state["flash_bounce_pct"])
    recovery_frac = float(state["flash_recovery_frac"])
    min_bounce = float(state["min_bounce_pct"])
    min_recovery = float(state["min_recovery_frac"])
    max_recovery = float(state["max_recovery_frac"])
    momentum_up = bool(state["momentum_up"])

    ready = detect_flash_drop_reversal(symbol, price, price_history, profile) is not None
    if ready:
        ui_tier = "ready"
        ui_label = "Dönüş hazır · LONG"
        progress = min(100.0, recovery_frac / max_recovery * 100.0)
    elif bounce_pct >= min_bounce * 0.45 and momentum_up:
        ui_tier = "bounce"
        ui_label = "Sıçrama · onay bekleniyor"
        progress = min(95.0, (bounce_pct / min_bounce) * 55.0)
    elif bounce_pct > 0 and recovery_frac >= min_recovery * 0.35:
        ui_tier = "forming"
        ui_label = "Dip dönüşü oluşuyor"
        progress = min(80.0, recovery_frac / min_recovery * 60.0)
    elif drop_pct >= min_drop:
        ui_tier = "drop"
        ui_label = "Flash düşüş · dip izle"
        progress = min(45.0, drop_pct / max(min_drop, 0.01) * 25.0)
    else:
        return None

    if recovery_frac > max_recovery:
        return None

    score = drop_pct * 10.0 + bounce_pct * 20.0 + progress
    if ready:
        score += 500.0

    return {
        "symbol": symbol,
        "type": "LONG",
        "price": price,
        "change": bounce_pct,
        "time": datetime.utcnow().strftime("%H:%M:%S"),
        "strength": "Strong" if drop_pct >= 0.35 else "Medium" if drop_pct >= 0.2 else "Weak",
        "ui_tier": ui_tier,
        "ui_label": ui_label,
        "ui_progress_pct": round(progress, 1),
        "watch_score": round(score, 2),
        "signal_source": "FlashReversal-Watch",
        "flash_reversal_watch": True,
        **{k: state[k] for k in state if k.startswith("flash_")},
    }


def build_flash_reversal_candidate(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    profile: dict[str, Any] | None = None,
    *,
    rank: int = 9,
) -> dict[str, Any] | None:
    """LONG aday — dönüş tespiti + sinyal satırı."""
    from datetime import datetime

    det = detect_flash_drop_reversal(symbol, price, price_history, profile)
    if not det and _env_bool("BERSERK2_FLASH_EARLY_ENTRY", False):
        state = _flash_drop_state(symbol, price, price_history, profile)
        if state and state.get("momentum_up"):
            bounce_pct = float(state["flash_bounce_pct"])
            recovery_frac = float(state["flash_recovery_frac"])
            min_bounce = float(state["min_bounce_pct"])
            min_recovery = float(state["min_recovery_frac"])
            if (
                bounce_pct >= min_bounce * 0.65
                and recovery_frac >= min_recovery * 0.72
            ):
                det = {k: state[k] for k in state if k.startswith("flash_")}
                det["flash_early_entry"] = True
    if not det:
        return None

    drop = float(det["flash_drop_pct"])
    bounce = float(det["flash_bounce_pct"])
    strength = "Strong" if drop >= 0.35 else "Medium" if drop >= 0.2 else "Weak"
    return {
        "symbol": symbol,
        "type": "LONG",
        "price": price,
        "change": round(bounce, 4),
        "time": datetime.utcnow().strftime("%H:%M:%S"),
        "strength": strength,
        "signal_source": "FlashReversal-LONG",
        "berserk2_mover_rank": rank,
        "target_mode": "berserk2",
        **det,
    }


def flash_reversal_dynamic_exit(
    signal: dict[str, Any],
    profile: dict[str, Any],
    *,
    stake_usd: float,
    leverage: int,
) -> dict[str, Any]:
    """Yüksek TP — düşüşün büyük kısmını geri alma hedefi."""
    from elite_trader.mode_engines.berserk_scoring import resolve_berserk_dynamic_exit

    base = resolve_berserk_dynamic_exit(
        float(signal.get("berserk_score") or 55),
        float(signal.get("change") or 0),
        float(signal.get("spread_pct") or 0),
        profile,
    )
    stake = max(float(stake_usd), 1.0)
    lev = max(int(leverage), 1)
    move_pct = float(signal.get("flash_target_move_pct") or 0)
    if move_pct <= 0:
        drop = float(signal.get("flash_drop_pct") or 0)
        tp_rec = float(signal.get("flash_tp_recovery_frac") or 0.72)
        move_pct = drop * tp_rec * 0.85
    tp_gross_usd = round(stake * lev * (move_pct / 100.0), 4)
    min_tp_usd = float(profile.get("berserk2_net_tp_usd") or 0.5) * float(
        profile.get("berserk2_flash_tp_floor_mult") or _env_float("BERSERK2_FLASH_TP_FLOOR_MULT", 1.35)
    )
    tp_gross_usd = max(tp_gross_usd, min_tp_usd)
    tp_stake_pct = round(tp_gross_usd / stake, 6)
    base_tp = float(base.get("tp_stake_pct") or 0.0048)
    base["tp_stake_pct"] = round(max(base_tp * 1.8, tp_stake_pct), 6)
    base["flash_reversal_tp_usd"] = tp_gross_usd
    base["flash_reversal_exit"] = True
    base["spike_enabled"] = True
    base["trailing_enabled"] = False
    return base


def flash_reversal_entry_meta(
    signal: dict[str, Any],
    profile: dict[str, Any],
    *,
    stake_usd: float = 120.0,
    leverage: int = 4,
) -> dict[str, Any]:
    """Entry gate bypass meta — berserk2 scoring."""
    de = flash_reversal_dynamic_exit(
        signal, profile, stake_usd=stake_usd, leverage=leverage
    )
    return {
        "berserk_score": 58.0,
        "spread_risk_level": "none",
        "strength_stake_mult": 1.0,
        "spread_stake_mult": 1.0,
        "intel_stake_mult": 1.0,
        "slippage_stake_mult": 1.0,
        "tier_stake_mult": 1.0,
        "fee_stake_mult": 1.0,
        "combined_stake_mult": 1.0,
        "expected_net_pnl_usd": round(float(de.get("flash_reversal_tp_usd") or 0) * 0.55, 4),
        "berserk_dynamic_exit": de,
        "flash_reversal": True,
        "flash_drop_pct": signal.get("flash_drop_pct"),
        "flash_bounce_pct": signal.get("flash_bounce_pct"),
        "flash_target_price": signal.get("flash_target_price"),
        "reversal_score": round(
            float(signal.get("flash_drop_pct") or 0) * 10
            + float(signal.get("flash_bounce_pct") or 0) * 20,
            2,
        ),
        "learning_tag": "flash_reversal_long",
    }
