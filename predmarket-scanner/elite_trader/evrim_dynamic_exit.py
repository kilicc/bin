"""
Evrim — skor ve piyasa koşullarına göre dinamik TP/SL, partial TP ve trailing.

Yalnızca evrim; sabit profil TP/SL yerine giriş anında hesaplanır.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Kullanıcı bantları (yüzde puan → stake oranı /100)
SCORE_BANDS: list[tuple[int, int, float, float, float, float]] = [
    (65, 75, 0.25, 0.40, 0.15, 0.25),
    (75, 85, 0.40, 0.75, 0.20, 0.35),
    (85, 101, 0.75, 1.50, 0.30, 0.55),
]

REGIME_TP_MULT = {
    "trending": 1.12,
    "breakout": 1.05,
    "chop": 0.88,
    "high_volatility": 1.0,
    "low_volatility": 0.85,
    "liquidation_cascade": 0.82,
    "news_shock": 0.7,
    "fake_pump_dump": 0.9,
}

REGIME_SL_MULT = {
    "trending": 1.0,
    "breakout": 0.95,
    "chop": 1.0,
    "high_volatility": 1.22,
    "low_volatility": 0.95,
    "liquidation_cascade": 1.12,
    "news_shock": 1.0,
    "fake_pump_dump": 1.08,
}

# V2 rejim bantları (tp_lo, tp_hi, sl_lo, sl_hi — yüzde puan)
V2_REGIME_BANDS: dict[str, tuple[float, float, float, float]] = {
    "scalp": (0.25, 0.40, 0.15, 0.25),
    "momentum": (0.40, 0.75, 0.20, 0.35),
    "breakout": (0.55, 1.10, 0.22, 0.40),
    "chop": (0.20, 0.35, 0.12, 0.22),
}

REGIME_V2_STYLE: dict[str, str] = {
    "low_volatility": "scalp",
    "trending": "momentum",
    "breakout": "breakout",
    "chop": "chop",
    "high_volatility": "momentum",
    "liquidation_cascade": "breakout",
    "news_shock": "scalp",
    "fake_pump_dump": "chop",
}


def _v2_enabled(profile: dict[str, Any]) -> bool:
    return bool(
        profile.get("evrim_v2_min_final_score")
        or profile.get("role") == "v2_live_meta_adaptive_brain"
    )


def _v2_band_for_regime(regime: str) -> tuple[float, float, float, float] | None:
    style = REGIME_V2_STYLE.get(regime, "momentum")
    return V2_REGIME_BANDS.get(style)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _pct_to_stake(v: float) -> float:
    """0.25 (yüzde puan) → 0.0025 stake oranı."""
    return v / 100.0 if v >= 0.05 else v


def _band_for_score(score: float) -> tuple[float, float, float, float]:
    s = float(score)
    for lo, hi, tp_a, tp_b, sl_a, sl_b in SCORE_BANDS:
        if lo <= s < hi:
            return tp_a, tp_b, sl_a, sl_b
    if s < 65:
        return SCORE_BANDS[0][2], SCORE_BANDS[0][3], SCORE_BANDS[0][4], SCORE_BANDS[0][5]
    return SCORE_BANDS[-1][2], SCORE_BANDS[-1][3], SCORE_BANDS[-1][4], SCORE_BANDS[-1][5]


def _blend(lo: float, hi: float, t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    return lo + (hi - lo) * t


@dataclass
class DynamicExitPlan:
    tp_stake_pct: float
    sl_stake_pct: float
    tp_trigger_frac: float = 0.98
    partial_tp_frac: float = 0.5
    trailing_enabled: bool = True
    breakeven_buffer_pct: float = 0.08
    momentum_weak_exit: bool = True
    tp_stake_pct_display: float = 0.0
    sl_stake_pct_display: float = 0.0
    factor_blend: float = 0.5
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tp_stake_pct": round(self.tp_stake_pct, 5),
            "sl_stake_pct": round(self.sl_stake_pct, 5),
            "tp_trigger_frac": self.tp_trigger_frac,
            "partial_tp_frac": self.partial_tp_frac,
            "trailing_enabled": self.trailing_enabled,
            "breakeven_buffer_pct": self.breakeven_buffer_pct,
            "momentum_weak_exit": self.momentum_weak_exit,
            "tp_pct_display": round(self.tp_stake_pct_display, 3),
            "sl_pct_display": round(self.sl_stake_pct_display, 3),
            "factor_blend": round(self.factor_blend, 3),
            "notes": self.notes[:12],
        }


def _factor_blend(
    *,
    score: float,
    side: str,
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[float, list[str]]:
    """0 = bant alt sınırı, 1 = bant üst sınırı."""
    notes: list[str] = []
    t = _clamp((score - 65) / 20.0, 0.0, 1.0)

    ch = abs(float(signal.get("change") or 0))
    strength = str(signal.get("strength") or "")
    mom = _clamp(ch / 1.2, 0.0, 1.0)
    if strength == "Strong":
        mom = min(1.0, mom + 0.15)
    elif strength == "Weak":
        mom = max(0.0, mom - 0.12)
    t = _clamp(t * 0.55 + mom * 0.45, 0.0, 1.0)
    if mom >= 0.7:
        notes.append("mom_strong")

    atr_min = float(profile.get("evrim_atr_min_pct") or 0.055)
    atr = float(ctx.get("atr_pct") or atr_min)
    atr_r = _clamp(atr / max(atr_min * 2, 1e-6), 0.5, 2.0)
    if atr_r > 1.3:
        t = min(1.0, t + 0.08)
        notes.append("atr_high")
    elif atr_r < 0.75:
        t = max(0.0, t - 0.06)
        notes.append("atr_low")

    vol_ratio = float(ctx.get("vol_ratio") or 1.0)
    vo = ctx.get("vo") or {}
    rel = float(vo.get("rel_volume") or vol_ratio)
    if rel >= 1.8:
        t = min(1.0, t + 0.1)
        notes.append("vol_spike")
    elif rel >= 1.2:
        t = min(1.0, t + 0.05)

    spread = float(ctx.get("spread_pct") or 0.05)
    spread_max = float(profile.get("evrim_vo_spread_veto_pct") or 0.12)
    if spread >= spread_max * 0.7:
        t = max(0.0, t - 0.12)
        notes.append("spread_wide")

    try:
        from elite_trader.fee_economics import fee_rate_per_side

        fee_rt = fee_rate_per_side() * 2
    except Exception:
        fee_rt = 0.0008
    t = min(1.0, t + fee_rt * 50)

    slip_bps = float(vo.get("slippage_bps") or ctx.get("slippage_bps") or 0)
    if slip_bps > float(profile.get("evrim_vo_slippage_stake_bps") or 25):
        t = max(0.0, t - 0.08)
        notes.append("slippage_high")

    regime = str(ctx.get("market_regime") or ctx.get("regime") or "chop")
    if regime in ("trending", "breakout"):
        t = min(1.0, t + 0.06)
    elif regime in ("chop", "low_volatility", "news_shock"):
        t = max(0.0, t - 0.08)

    return t, notes


def compute_dynamic_exit(
    *,
    total_score: float,
    side: str,
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any] | None = None,
    stake_usd: float = 10.0,
    leverage: int = 5,
) -> DynamicExitPlan:
    """Giriş anı TP/SL stake oranları + çıkış davranış bayrakları."""
    prof = profile or {}
    if not prof.get("evrim_dynamic_exit_enabled", True):
        base_tp = float(prof.get("tp_stake_pct") or 0.006)
        base_sl = float(prof.get("sl_stake_pct") or 0.0025)
        return DynamicExitPlan(
            tp_stake_pct=base_tp,
            sl_stake_pct=base_sl,
            partial_tp_frac=0.0,
            trailing_enabled=bool(prof.get("spike_enabled", True)),
            tp_stake_pct_display=base_tp * 100,
            sl_stake_pct_display=base_sl * 100,
        )

    tp_a, tp_b, sl_a, sl_b = _band_for_score(total_score)
    regime = str(ctx.get("market_regime") or ctx.get("regime") or "chop")
    if _v2_enabled(prof):
        v2b = _v2_band_for_regime(regime)
        if v2b:
            tp_a, tp_b, sl_a, sl_b = v2b
    blend, notes = _factor_blend(
        score=total_score, side=side, signal=signal, ctx=ctx, profile=prof
    )
    if _v2_enabled(prof):
        notes.append(f"v2_{REGIME_V2_STYLE.get(regime, 'momentum')}")

    tp_disp = _blend(tp_a, tp_b, blend)
    sl_disp = _blend(sl_a, sl_b, blend)
    tp_pct = _pct_to_stake(tp_disp)
    sl_pct = _pct_to_stake(sl_disp)

    pol = ctx.get("regime_policy") or {}
    tp_pct *= float(pol.get("tp_mult") or REGIME_TP_MULT.get(regime, 1.0))
    sl_pct *= float(pol.get("sl_mult") or REGIME_SL_MULT.get(regime, 1.0))

    try:
        from elite_trader.fee_economics import round_trip_fee_usd

        fee_usd = round_trip_fee_usd(stake_usd, leverage)
        min_tp = (fee_usd * 1.15) / max(stake_usd, 1.0)
        tp_pct = max(tp_pct, min_tp)
        notes.append("fee_floor")
    except Exception:
        pass

    max_tp = _pct_to_stake(float(prof.get("evrim_dynamic_tp_cap_pct") or 1.50))
    min_tp = _pct_to_stake(float(prof.get("evrim_dynamic_tp_floor_pct") or 0.20))
    max_sl = _pct_to_stake(float(prof.get("evrim_dynamic_sl_cap_pct") or 0.55))
    min_sl = _pct_to_stake(float(prof.get("evrim_dynamic_sl_floor_pct") or 0.12))
    tp_pct = _clamp(tp_pct, min_tp, max_tp)
    sl_pct = _clamp(sl_pct, min_sl, max_sl)

    partial = float(prof.get("evrim_partial_tp_frac") or 0.5)
    trailing = bool(prof.get("evrim_trailing_enabled", True))
    if pol.get("trailing_enabled"):
        trailing = True
    if float(pol.get("partial_tp_frac") or 0) > 0:
        partial = float(pol["partial_tp_frac"])

    overrides = (prof.get("dynamic_exit_overrides") or {})
    try:
        from elite_trader.evrim_training import load_training_state

        for k, v in (load_training_state().get("dynamic_exit_overrides") or {}).items():
            overrides.setdefault(k, v)
    except Exception:
        pass
    if overrides.get("tp_mult"):
        tp_pct *= float(overrides["tp_mult"])
    if overrides.get("sl_mult"):
        sl_pct *= float(overrides["sl_mult"])

    trig = float(prof.get("tp_trigger_frac") or 0.98)
    be_buf = float(prof.get("evrim_breakeven_buffer_pct") or 0.08)

    return DynamicExitPlan(
        tp_stake_pct=round(tp_pct, 5),
        sl_stake_pct=round(sl_pct, 5),
        tp_trigger_frac=trig,
        partial_tp_frac=partial if partial > 0 else 0.5,
        trailing_enabled=trailing,
        breakeven_buffer_pct=be_buf,
        momentum_weak_exit=bool(prof.get("evrim_momentum_weak_exit", True)),
        tp_stake_pct_display=tp_disp,
        sl_stake_pct_display=sl_disp,
        factor_blend=blend,
        notes=notes,
    )


def plan_to_usd_targets(
    plan: DynamicExitPlan,
    stake_usd: float,
) -> tuple[float, float, float]:
    """(tp_usd, sl_usd, partial_tp_usd)."""
    s = max(float(stake_usd), 1.0)
    tp = s * plan.tp_stake_pct * plan.tp_trigger_frac
    sl = s * plan.sl_stake_pct
    partial = tp * plan.partial_tp_frac if plan.partial_tp_frac > 0 else 0.0
    return round(tp, 4), round(sl, 4), round(partial, 4)


def evaluate_evrim_dynamic_exit(
    pos: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
) -> str | None:
    """
    Partial TP, trailing breakeven, momentum zayıflama çıkışı.
    Paper/shadow pozisyon için kapanış nedeni.
    """
    prof = profile or {}
    plan_d = pos.get("dynamic_exit") or {}
    if not plan_d and not prof.get("evrim_dynamic_exit_enabled", True):
        return None

    unreal = float(pos.get("unrealized_pnl") or 0)
    stake = float(pos.get("stake_usd") or 1.0)
    tp_tgt = float(pos.get("tp_target_usd") or 0)
    sl_tgt = float(pos.get("sl_target_usd") or 0)
    partial_usd = float(pos.get("tp_partial_usd") or 0)
    partial_done = bool(pos.get("partial_tp_done"))
    trailing_on = bool(plan_d.get("trailing_enabled", True))
    be_buf_pct = float(plan_d.get("breakeven_buffer_pct") or 0.08)

    try:
        from elite_trader.fee_economics import round_trip_fee_usd

        lev = max(int(pos.get("leverage") or 5), 1)
        fee = round_trip_fee_usd(stake, lev)
    except Exception:
        fee = stake * 0.001

    min_profit = max(fee * 1.05, stake * 0.0008)

    # Partial: ilk TP'nin %50'si
    if partial_usd > 0 and not partial_done and unreal >= partial_usd and unreal > min_profit:
        pos["partial_tp_done"] = True
        pos["size"] = float(pos.get("size") or 0) * 0.5
        pos["stake_usd"] = stake * 0.5
        pos["tp_target_usd"] = tp_tgt
        if trailing_on:
            pos["sl_target_usd"] = max(
                float(pos.get("sl_target_usd") or 0),
                min_profit + stake * (be_buf_pct / 100.0),
            )
        return None

    # Tam TP
    if tp_tgt > 0 and unreal >= tp_tgt and unreal > 0:
        return "TP"

    # Trailing: kârda SL break-even üstü
    if trailing_on and unreal >= min_profit:
        peak = float(pos.get("max_unreal_seen") or unreal)
        be_sl = -(min_profit + stake * (be_buf_pct / 100.0))
        cur_sl = float(pos.get("dynamic_sl_usd") or sl_tgt)
        new_sl = max(cur_sl, abs(be_sl))
        pos["dynamic_sl_usd"] = new_sl
        if unreal <= -new_sl:
            return "SL-TRAIL"

    # Sabit SL
    eff_sl = float(pos.get("dynamic_sl_usd") or sl_tgt)
    if eff_sl > 0 and unreal <= -eff_sl:
        return "SL"

    # Momentum zayıflama
    if bool(plan_d.get("momentum_weak_exit", True)):
        peak = float(pos.get("max_unreal_seen") or 0)
        if peak >= min_profit * 1.5 and unreal < peak * 0.55 and unreal >= min_profit:
            return "MOMENTUM-FADE"
        hist = pos.get("price_history") or []
        if len(hist) >= 4:
            side = str(pos.get("side") or "LONG")
            p0, p1 = float(hist[-4]), float(hist[-1])
            if side == "LONG" and p1 < p0 and unreal >= min_profit:
                return "MOMENTUM-FADE"
            if side == "SHORT" and p1 > p0 and unreal >= min_profit:
                return "MOMENTUM-FADE"

    return None


def simulate_bt_exit(
    *,
    side: str,
    entry: float,
    candles: list[dict],
    start_idx: int,
    plan: DynamicExitPlan,
    stake_usd: float = 10.0,
) -> tuple[bool, bool, str]:
    """
    Backtest: (win, partial_hit, exit_tag).
    Fiyat hareketi % olarak tp/sl ile.
    """
    tp_move = plan.tp_stake_pct * plan.tp_trigger_frac
    sl_move = plan.sl_stake_pct
    partial_move = tp_move * plan.partial_tp_frac if plan.partial_tp_frac > 0 else 0.0
    partial_hit = False
    trailing_sl = sl_move
    peak_up = 0.0

    for j in range(start_idx, min(start_idx + 80, len(candles))):
        hi = float(candles[j]["h"])
        lo = float(candles[j]["l"])
        if side == "LONG":
            up = (hi - entry) / entry
            dn = (entry - lo) / entry
        else:
            up = (entry - lo) / entry
            dn = (hi - entry) / entry
        peak_up = max(peak_up, up)

        if partial_move > 0 and up >= partial_move and not partial_hit:
            partial_hit = True
            if plan.trailing_enabled:
                fee_floor = 0.0008
                trailing_sl = max(sl_move * 0.5, fee_floor)

        eff_sl = trailing_sl if (plan.trailing_enabled and partial_hit) else sl_move
        if plan.trailing_enabled and peak_up >= tp_move * 0.35:
            trailing_sl = min(trailing_sl, sl_move * 0.65)

        if up >= tp_move:
            return True, partial_hit, "TP"
        if dn >= eff_sl:
            return False, partial_hit, "SL"
        if (
            plan.momentum_weak_exit
            and partial_hit
            and peak_up >= tp_move * 0.4
            and up < peak_up * 0.5
        ):
            return True, partial_hit, "MOMENTUM-FADE"

    if partial_hit:
        return True, True, "PARTIAL-TRAIL"
    return False, partial_hit, "TIMEOUT"
