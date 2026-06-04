"""
Evrim — yumuşak risk politikası (hard veto → skor/stake cezası).

Yalnızca evrim. Diğer mod profillerine dokunmaz.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

MODE_ID = "evrim"

REGIME_MIN_SCORE: dict[str, float] = {
    "trending": 58,
    "breakout": 56,
    "high_volatility": 60,
    "volatility_shock": 60,
    "chop": 52,
    "news_shock": 68,
    "low_volatility": 58,
    "low_liquidity": 99,
    "liquidation_cascade": 62,
    "fake_pump_dump": 70,
}

_SPREAD_HIST: dict[str, deque[tuple[float, float]]] = {}
_SHOCK_UNTIL: float = 0.0
_SHOCK_LABEL: str = ""
_TEMP_UNIVERSE: set[str] = set()
_LAST_EXCHANGE_OPEN_TS: float = 0.0
_RECOVERY_ACTIVE: bool = False


def record_exchange_open() -> None:
    global _LAST_EXCHANGE_OPEN_TS
    _LAST_EXCHANGE_OPEN_TS = time.time()


def record_spread_sample(symbol: str, spread_pct: float) -> None:
    sym = str(symbol or "").upper()
    if not sym:
        return
    now = time.time()
    dq = _SPREAD_HIST.setdefault(sym, deque(maxlen=120))
    dq.append((now, float(spread_pct)))
    while dq and now - dq[0][0] > 30.0:
        dq.popleft()


def spread_30s_avg(symbol: str) -> float | None:
    dq = _SPREAD_HIST.get(str(symbol or "").upper())
    if not dq or len(dq) < 2:
        return None
    return sum(s for _, s in dq) / len(dq)


def has_verified_news(ctx: dict[str, Any]) -> bool:
    """RSS / havuzdan doğrulanmış başlık — placeholder değil."""
    radar = ctx.get("market_radar") or {}
    headline = str(
        radar.get("news_headline")
        or ctx.get("pool_headline")
        or ctx.get("news_headline")
        or ""
    ).strip()
    if not headline or len(headline) < 16:
        return False
    feeds = radar.get("feeds") or {}
    cn = feeds.get("crypto_news") or {}
    if isinstance(cn, dict) and cn.get("status") == "placeholder":
        return False
    if ctx.get("pool_news_sentiment") in ("bullish", "bearish"):
        return True
    sent = str(radar.get("news_sentiment") or "")
    return sent in ("bullish", "bearish")


def activate_shock(label: str, duration_sec: float, profile: dict[str, Any]) -> None:
    global _SHOCK_UNTIL, _SHOCK_LABEL
    sec = float(profile.get("evrim_news_shock_sec") or duration_sec or 90.0)
    _SHOCK_UNTIL = time.time() + sec
    _SHOCK_LABEL = label


def active_shock_label() -> str:
    if time.time() < _SHOCK_UNTIL:
        return _SHOCK_LABEL
    return ""


def dynamic_min_score(
    regime_id: str,
    profile: dict[str, Any],
    *,
    recovery_delta: int = 0,
) -> float:
    base = float(profile.get("evrim_min_total_score") or 55)
    table = dict(REGIME_MIN_SCORE)
    overrides = profile.get("evrim_regime_min_score") or {}
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            table[k] = float(v)
    reg_min = table.get(regime_id, base)
    out = min(base, reg_min) if regime_id == "chop" else reg_min
    if _RECOVERY_ACTIVE:
        out = max(48.0, out - 5.0)
    out += float(recovery_delta)
    return max(48.0, min(75.0, out))


def tp_usd_for_spread(profile: dict[str, Any]) -> float:
    from elite_trader.panel_strategy import stake_targets

    stake = float(profile.get("min_stake_usd") or 140)
    tp_usd, _ = stake_targets(stake, MODE_ID)
    return max(float(tp_usd), 0.35)


def assess_spread_risk(
    symbol: str,
    spread_pct: float,
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """
    spread_halt yalnızca aşırı durumda; normalde skor/stake/TP cezası.
    """
    record_spread_sample(symbol, spread_pct)
    tp_ref = tp_usd_for_spread(profile)
    stake = float(profile.get("min_stake_usd") or 140)
    # Spread maliyeti: stake × spread% (fiyat ölçeğinden bağımsız proxy)
    spread_cost = stake * (spread_pct / 100.0)
    spread_vs_tp = spread_cost / tp_ref if tp_ref > 0 else 9.0

    hard_tp_frac = float(profile.get("evrim_spread_hard_veto_tp_frac") or 0.55)
    avg30 = spread_30s_avg(symbol)
    spike_vs_avg = avg30 is not None and spread_pct > avg30 * 3.0 and avg30 > 0.01

    vo = ctx.get("vo") or {}
    liq_weak = bool(
        vo.get("liquidity_pull", {}).get("detected")
        or (vo.get("signals") or {}).get("liquidity_pull", {}).get("detected")
    )
    rel_vol = float(ctx.get("vol_ratio") or vo.get("rel_volume") or 1.0)
    if rel_vol < 0.85 and spread_pct > float(profile.get("evrim_vo_spread_veto_pct") or 0.12) * 1.2:
        liq_weak = True

    hard_veto = (
        spread_vs_tp >= hard_tp_frac
        or spike_vs_avg
        or (liq_weak and spread_vs_tp >= hard_tp_frac * 0.85)
    )

    out: dict[str, Any] = {
        "hard_veto": hard_veto,
        "spread_vs_tp": round(spread_vs_tp, 4),
        "spread_pct": spread_pct,
        "score_delta": 0.0,
        "stake_mult": 1.0,
        "tp_mult": 1.0,
        "prefer_limit": False,
        "reason": "spread_ok",
    }
    if hard_veto:
        out["reason"] = "spread_hard_veto"
        return out

    if spread_vs_tp >= hard_tp_frac * 0.45 or spread_pct >= float(
        profile.get("evrim_vo_spread_veto_pct") or 0.12
    ):
        out.update(
            {
                "score_delta": -8.0,
                "stake_mult": 0.55,
                "tp_mult": 1.15,
                "prefer_limit": True,
                "reason": "spread_soft_penalty",
            }
        )
    elif spread_vs_tp >= 0.25:
        out.update(
            {
                "score_delta": -4.0,
                "stake_mult": 0.75,
                "tp_mult": 1.05,
                "reason": "spread_mild_penalty",
            }
        )
    return out


def apply_radar_penalties(
    radar: Any,
    profile: dict[str, Any],
    *,
    spread_assess: dict[str, Any] | None = None,
) -> Any:
    """Radar veto → çoğunlukla skor cezası; yalnızca extreme hard veto."""
    extreme_only = bool(profile.get("evrim_radar_hard_veto_only_extreme", True))
    level = str(getattr(radar, "emergency_level", "") or "")
    veto_reason = str(getattr(radar, "veto_reason", "") or "")

    extreme_levels = frozenset({"dd_halt", "api_slow"})
    if extreme_only:
        if level in extreme_levels and getattr(radar, "block_new_entries", False):
            radar.veto = True
            radar.veto_reason = level
            return radar
        if level == "spread_halt" or veto_reason in (
            "spread_halt",
            "bull_spread_wait",
            "bear_spread_wait",
            "uncertain_news",
            "uncertain_news_no_entry",
        ):
            assess = spread_assess or {}
            if assess.get("hard_veto"):
                radar.veto = True
                radar.veto_reason = "spread_extreme"
            else:
                pen = -15 if veto_reason.startswith("uncertain") else -8
                if "bull" in veto_reason or "bear" in veto_reason:
                    pen = -8
                radar.veto = False
                radar.veto_reason = ""
                radar.long_score_delta += pen if pen < 0 else 0
                radar.short_score_delta += pen if pen < 0 else 0
                radar.min_score_delta += 0
                radar.notes.append(f"radar_penalty_{pen}")
            return radar

    if getattr(radar, "veto", False) and not extreme_only:
        pen_map = {
            "uncertain_news": -8,
            "uncertain_news_no_entry": -8,
            "bull_spread_wait": -8,
            "bear_spread_wait": -8,
        }
        pen = pen_map.get(veto_reason, -12)
        if pen <= -15:
            return radar
        radar.veto = False
        radar.veto_reason = ""
        radar.long_score_delta += pen
        radar.short_score_delta += pen
        radar.notes.append(f"radar_penalty_{pen}")
    return radar


def chop_policy(profile: dict[str, Any]) -> dict[str, Any]:
    """Chop — işlem açık, küçük stake, dar TP/SL."""
    enabled = profile.get("evrim_chop_trade_enabled", True)
    return {
        "allow_enter": enabled,
        "stake_mult": float(profile.get("evrim_chop_stake_mult") or 0.35),
        "tp_mult": float(profile.get("evrim_chop_tp_mult") or 0.75),
        "sl_mult": float(profile.get("evrim_chop_sl_mult") or 0.85),
        "min_score_delta": int(profile.get("evrim_chop_min_score_delta") or -3),
        "max_open_cap": int(profile.get("evrim_chop_max_open") or 4),
        "veto": not enabled,
        "notes": ["chop_micro_scalp"],
    }


def news_shock_policy(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "allow_enter": True,
        "veto": False,
        "stake_mult": float(profile.get("evrim_news_shock_stake_mult") or 0.65),
        "min_score_delta": int(profile.get("evrim_news_shock_min_delta") or 10),
        "tp_mult": 1.0,
        "sl_mult": 1.1,
        "notes": ["news_shock_soft"],
    }


def volatility_shock_policy(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "allow_enter": True,
        "veto": False,
        "stake_mult": float(profile.get("evrim_vol_shock_stake_mult") or 0.55),
        "min_score_delta": 2,
        "notes": ["volatility_shock_stake_cut"],
    }


def maybe_temp_universe(
    symbol: str,
    total_score: float,
    ctx: dict[str, Any],
    tradable: set[str] | frozenset[str],
    profile: dict[str, Any],
) -> bool:
    sym = str(symbol or "").upper()
    if not sym or sym in tradable or sym in _TEMP_UNIVERSE:
        return sym in tradable or sym in _TEMP_UNIVERSE
    min_sc = float(profile.get("evrim_temp_universe_min_score") or 70)
    if total_score < min_sc:
        return False
    if float(ctx.get("vol_ratio") or 0) < float(profile.get("evrim_vol_mult") or 1.8) * 0.75:
        return False
    sp = float(ctx.get("spread_pct") or 0.05)
    assess = assess_spread_risk(sym, sp, ctx, profile)
    if assess.get("hard_veto"):
        return False
    _TEMP_UNIVERSE.add(sym)
    return True


def temp_universe_symbols() -> set[str]:
    return set(_TEMP_UNIVERSE)


def log_execution_stage(
    symbol: str,
    *,
    signal_passed: bool | None = None,
    risk_passed: bool | None = None,
    execution_passed: bool | None = None,
    order_sent: bool | None = None,
    exchange_accepted: bool | None = None,
    reason: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    try:
        from elite_trader.evrim_decision_log import append_decision

        append_decision(
            {
                "kind": "execution_pipeline",
                "symbol": symbol,
                "signal_passed": signal_passed,
                "risk_passed": risk_passed,
                "execution_passed": execution_passed,
                "order_sent": order_sent,
                "exchange_accepted": exchange_accepted,
                "reason": reason[:160],
                "meta": meta or {},
            }
        )
    except Exception:
        pass


def maybe_trade_flow_recovery(profile: dict[str, Any]) -> dict[str, Any]:
    """
    Son 30 dk borsa açılan 0 → eşik gevşetme (runtime, profil dosyasına yazmaz).
    """
    global _RECOVERY_ACTIVE
    if not profile.get("evrim_flow_recovery_enabled", True):
        _RECOVERY_ACTIVE = False
        return {"active": False}

    idle_sec = time.time() - (_LAST_EXCHANGE_OPEN_TS or 0)
    if _LAST_EXCHANGE_OPEN_TS <= 0:
        idle_sec = 9999.0
    if idle_sec < 1800:
        _RECOVERY_ACTIVE = False
        return {"active": False, "idle_sec": round(idle_sec, 1)}

    _RECOVERY_ACTIVE = True
    try:
        from elite_trader.evrim_training import load_training_state, _save_training_state

        st = load_training_state()
        st["flow_recovery"] = {
            "active": True,
            "since": time.time(),
            "min_score_bonus": -5,
            "spread_soft": True,
            "radar_penalty_mode": True,
        }
        _save_training_state(st)
    except Exception:
        pass
    return {
        "active": True,
        "idle_sec": round(idle_sec, 1),
        "actions": [
            "min_score -5",
            "spread soft",
            "radar penalty",
            "test_flow_restart",
        ],
    }


def recovery_runtime_patch(profile: dict[str, Any]) -> dict[str, Any]:
    """Geçici runtime — save_profile yok."""
    if not _RECOVERY_ACTIVE:
        return {}
    return {
        "evrim_min_total_score": max(
            48, int(profile.get("evrim_min_total_score") or 55) - 5
        ),
        "evrim_spread_hard_veto_tp_frac": min(
            0.65, float(profile.get("evrim_spread_hard_veto_tp_frac") or 0.55) + 0.08
        ),
        "evrim_radar_hard_veto_only_extreme": True,
        "evrim_expectancy_min_net_usd": 0.01,
        "evrim_fee_hard_block": False,
    }
