"""
Evrim — 8 rejimli piyasa sınıflandırıcı + rejim bazlı davranış.

Yalnızca evrim; tek başına emir açmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REGIMES = (
    "trending",
    "breakout",
    "chop",
    "high_volatility",
    "low_volatility",
    "liquidation_cascade",
    "news_shock",
    "fake_pump_dump",
)

DEFAULT_REGIME_OVERRIDES: dict[str, dict[str, float]] = {}


@dataclass
class RegimePolicy:
    regime_id: str
    stake_mult: float = 1.0
    min_score_delta: int = 0
    tp_mult: float = 1.0
    sl_mult: float = 1.0
    partial_tp_frac: float = 0.0
    veto: bool = False
    allow_enter: bool = True
    trailing_enabled: bool = False
    reentry_enabled: bool = False
    trend_side_only: bool = False
    slippage_bps_delta: float = 0.0
    component_deltas: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime_id": self.regime_id,
            "stake_mult": self.stake_mult,
            "min_score_delta": self.min_score_delta,
            "tp_mult": self.tp_mult,
            "sl_mult": self.sl_mult,
            "partial_tp_frac": self.partial_tp_frac,
            "veto": self.veto,
            "allow_enter": self.allow_enter,
            "trailing_enabled": self.trailing_enabled,
            "reentry_enabled": self.reentry_enabled,
            "notes": self.notes[:10],
        }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _policy_for(regime_id: str, profile: dict[str, Any]) -> RegimePolicy:
    overrides = dict(profile.get("regime_overrides") or {})
    try:
        from elite_trader.evrim_training import load_training_state

        for k, v in (load_training_state().get("regime_overrides") or {}).items():
            overrides.setdefault(k, {}).update(v)
    except Exception:
        pass

    base: dict[str, RegimePolicy] = {
        "trending": RegimePolicy(
            regime_id="trending",
            stake_mult=1.0,
            min_score_delta=-2,
            tp_mult=1.15,
            sl_mult=1.0,
            trailing_enabled=True,
            trend_side_only=True,
            notes=["trend_follow"],
        ),
        "breakout": RegimePolicy(
            regime_id="breakout",
            stake_mult=1.05,
            min_score_delta=-1,
            tp_mult=1.0,
            sl_mult=0.95,
            partial_tp_frac=0.5,
            reentry_enabled=True,
            notes=["breakout_fast"],
        ),
        "chop": RegimePolicy(
            regime_id="chop",
            stake_mult=0.35,
            min_score_delta=-3,
            tp_mult=0.75,
            sl_mult=0.85,
            allow_enter=True,
            veto=False,
            notes=["chop_micro_scalp"],
        ),
        "low_volatility": RegimePolicy(
            regime_id="low_volatility",
            stake_mult=0.5,
            min_score_delta=2,
            tp_mult=0.9,
            allow_enter=True,
            veto=False,
            notes=["low_vol_reduced"],
        ),
        "high_volatility": RegimePolicy(
            regime_id="high_volatility",
            stake_mult=0.75,
            min_score_delta=1,
            tp_mult=1.0,
            sl_mult=1.25,
            slippage_bps_delta=-5.0,
            notes=["high_vol_controlled"],
        ),
        "news_shock": RegimePolicy(
            regime_id="news_shock",
            stake_mult=0.65,
            min_score_delta=10,
            tp_mult=1.0,
            sl_mult=1.1,
            veto=False,
            allow_enter=True,
            notes=["news_shock_soft"],
        ),
        "liquidation_cascade": RegimePolicy(
            regime_id="liquidation_cascade",
            stake_mult=0.5,
            min_score_delta=5,
            tp_mult=0.8,
            sl_mult=1.15,
            notes=["liq_cascade_caution"],
        ),
        "fake_pump_dump": RegimePolicy(
            regime_id="fake_pump_dump",
            stake_mult=0.5,
            min_score_delta=3,
            tp_mult=0.9,
            sl_mult=1.1,
            veto=True,
            notes=["fake_pump_dump"],
        ),
    }
    pol = base.get(regime_id, RegimePolicy(regime_id="chop"))
    ov = overrides.get(regime_id) or {}
    if ov.get("stake_mult") is not None:
        pol.stake_mult = float(ov["stake_mult"])
    if ov.get("min_score_delta") is not None:
        pol.min_score_delta = int(ov["min_score_delta"])
    if ov.get("tp_mult") is not None:
        pol.tp_mult = float(ov["tp_mult"])
    if ov.get("sl_mult") is not None:
        pol.sl_mult = float(ov["sl_mult"])
    if ov.get("veto") is not None:
        pol.veto = bool(ov["veto"])
    if ov.get("allow_enter") is not None:
        pol.allow_enter = bool(ov["allow_enter"])
    return pol


def _wick_ratio(c: dict) -> float:
    o, h, l, cl = float(c.get("o", 0)), float(c.get("h", 0)), float(c.get("l", 0)), float(c.get("c", 0))
    rng = max(h - l, 1e-12)
    body = abs(cl - o)
    return max(0.0, (rng - body) / rng)


def _detect_flags(ctx: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    atr_min = float(profile.get("evrim_atr_min_pct") or 0.055)
    atr = float(ctx.get("atr_pct") or 0)
    vol_ratio = float(ctx.get("vol_ratio") or 1.0)
    spread = float(ctx.get("spread_pct") or 0.05)
    chop = bool(ctx.get("chop"))
    mtf = ctx.get("mtf") or {}
    mtf_sum = mtf.get("summary") or {}
    pa = ctx.get("pa") or {}
    vo = ctx.get("vo") or {}

    adx_chop = bool(mtf_sum.get("chop_mode")) or chop
    trend_align = str(mtf_sum.get("trend_alignment") or "")
    bb_break = bool(mtf_sum.get("bb_breakout_up") or mtf_sum.get("bb_breakout_down"))
    if not bb_break and pa.get("detected"):
        bb_break = "breakout" in pa.get("detected", [])

    fake_prob = float(pa.get("fake_breakout_prob") or 0)
    last = ctx.get("last_candle") or {}
    wick = _wick_ratio(last) if last else 0.0
    klines = ctx.get("klines_5m") or []
    if len(klines) >= 2:
        c0, c1 = float(klines[-2]["c"]), float(klines[-1]["c"])
        jump_pct = abs(c1 - c0) / max(c0, 1e-12) * 100
    else:
        jump_pct = 0.0

    news_spread = float(profile.get("evrim_regime_news_spread_pct") or 0.15)
    fake_thresh = float(profile.get("evrim_regime_fake_pump_prob") or 0.60)

    return {
        "atr": atr,
        "atr_min": atr_min,
        "vol_ratio": vol_ratio,
        "spread": spread,
        "adx_chop": adx_chop,
        "trend_align": trend_align,
        "bb_break": bb_break,
        "fake_prob": fake_prob,
        "fake_thresh": fake_thresh,
        "news_spread": news_spread,
        "wick": wick,
        "jump_pct": jump_pct,
        "liquidity_pull": bool((vo.get("signals") or {}).get("liquidity_pull", {}).get("detected")),
        "extreme_atr": atr >= atr_min * 3.5,
    }


def classify_market_regime(
    ctx: dict[str, Any],
    side: str,
    profile: dict[str, Any] | None = None,
) -> tuple[str, float, RegimePolicy]:
    """Rejim id, guven 0-1, politika."""
    prof = profile or {}
    f = _detect_flags(ctx, prof)

    shock_spread = f["spread"] >= f["news_spread"] or (
        f["extreme_atr"] and f["spread"] >= 0.10
    )
    if shock_spread:
        from elite_trader.evrim_risk_policy import (
            active_shock_label,
            activate_shock,
            has_verified_news,
            news_shock_policy,
            volatility_shock_policy,
        )

        if active_shock_label() == "news_shock":
            pol = _policy_for("news_shock", prof)
            for k, v in news_shock_policy(prof).items():
                if k == "notes":
                    pol.notes = list(v)
                elif hasattr(pol, k):
                    setattr(pol, k, v)
            return "news_shock", 0.82, pol
        if has_verified_news(ctx):
            activate_shock("news_shock", float(prof.get("evrim_news_shock_sec") or 90), prof)
            pol = _policy_for("news_shock", prof)
            for k, v in news_shock_policy(prof).items():
                if k == "notes":
                    pol.notes = list(v)
                elif hasattr(pol, k):
                    setattr(pol, k, v)
            return "news_shock", 0.85, pol
        activate_shock(
            "volatility_shock",
            float(prof.get("evrim_news_shock_sec") or 90),
            prof,
        )
        pol = _policy_for("high_volatility", prof)
        for k, v in volatility_shock_policy(prof).items():
            if k == "notes":
                pol.notes = list(v)
            elif hasattr(pol, k):
                setattr(pol, k, v)
        return "high_volatility", 0.8, pol

    if f["vol_ratio"] >= 2.5 and (f["wick"] >= 0.55 or f["jump_pct"] >= 0.35):
        return "liquidation_cascade", 0.75, _policy_for("liquidation_cascade", prof)

    if f["fake_prob"] >= f["fake_thresh"]:
        return "fake_pump_dump", f["fake_prob"], _policy_for("fake_pump_dump", prof)

    if f["adx_chop"] and not f["bb_break"]:
        from elite_trader.evrim_risk_policy import chop_policy

        pol = _policy_for("chop", prof)
        for k, v in chop_policy(prof).items():
            if k == "notes":
                pol.notes = list(v)
            elif hasattr(pol, k):
                setattr(pol, k, v)
        return "chop", 0.7, pol

    if f["atr"] < f["atr_min"] * 0.7:
        return "low_volatility", 0.8, _policy_for("low_volatility", prof)

    if f["atr"] >= f["atr_min"] * 2.0:
        return "high_volatility", 0.75, _policy_for("high_volatility", prof)

    if f["bb_break"] and f["vol_ratio"] >= 1.2:
        return "breakout", 0.72, _policy_for("breakout", prof)

    if f["trend_align"] in ("bull", "bear") and not f["adx_chop"]:
        return "trending", 0.78, _policy_for("trending", prof)

    return "chop", 0.55, _policy_for("chop", prof)


def regime_blocks_side(regime_id: str, side: str, ctx: dict[str, Any]) -> bool:
    side = str(side or "LONG").upper()
    if regime_id != "trending":
        return False
    trend = str(ctx.get("ema_trend") or "")
    if side == "LONG" and trend == "down":
        return True
    if side == "SHORT" and trend == "up":
        return True
    align = str((ctx.get("mtf") or {}).get("summary", {}).get("trend_alignment") or "")
    if side == "LONG" and align == "bear":
        return True
    if side == "SHORT" and align == "bull":
        return True
    return False


def apply_regime_adjustments(
    side: str,
    components: dict[str, float],
    regime_id: str,
    policy: RegimePolicy,
    profile: dict[str, Any],
    ctx: dict[str, Any] | None = None,
) -> RegimePolicy:
    """Bilesenlere rejim deltasi; policy dondur (ayni obje guncellenir)."""
    side = str(side or "LONG").upper()
    ctx = ctx or {}
    if regime_id == "trending" and not regime_blocks_side(regime_id, side, ctx):
        policy.component_deltas["trend_ema"] = policy.component_deltas.get("trend_ema", 0) + 2.0
    if regime_id == "breakout":
        policy.component_deltas["price_action"] = (
            policy.component_deltas.get("price_action", 0) + 1.5
        )
    caps = {
        "price_action": 25,
        "volume_delta": 20,
        "trend_ema": 15,
        "orderbook_liquidity": 10,
    }
    for k, delta in list(policy.component_deltas.items()):
        base = components.get(k, 0)
        policy.component_deltas[k] = round(
            _clamp(base + delta, 0, caps.get(k, 20)) - base, 2
        )
    return policy


def merge_regime_into_components(
    components: dict[str, float],
    policy: RegimePolicy,
) -> dict[str, float]:
    out = dict(components)
    for k, delta in policy.component_deltas.items():
        out[k] = round(_clamp(out.get(k, 0) + delta, 0, 100), 2)
    total = sum(out.values())
    if total > 100:
        scale = 100 / total
        out = {k: round(v * scale, 2) for k, v in out.items()}
    return out


def apply_regime_to_runtime(
    profile: dict[str, Any],
    policy: RegimePolicy,
) -> dict[str, Any]:
    """Islem ani TP/SL/spike override (kalici save yok)."""
    base_tp = float(profile.get("tp_stake_pct") or 0.006)
    base_sl = float(profile.get("sl_stake_pct") or 0.0025)
    slip_bps = float(profile.get("evrim_vo_slippage_stake_bps") or 25)
    slip_bps = max(5.0, slip_bps + policy.slippage_bps_delta)
    return {
        "tp_stake_pct": round(base_tp * policy.tp_mult, 5),
        "sl_stake_pct": round(base_sl * policy.sl_mult, 5),
        "spike_enabled": policy.trailing_enabled or profile.get("spike_enabled", True),
        "evrim_vo_slippage_stake_bps": slip_bps,
        "regime_partial_tp_frac": policy.partial_tp_frac,
        "regime_reentry_enabled": policy.reentry_enabled,
    }


def apply_regime_to_context(
    ctx: dict[str, Any],
    regime_id: str,
    confidence: float,
    policy: RegimePolicy,
) -> None:
    ctx["market_regime"] = regime_id
    ctx["regime_legacy"] = ctx.get("regime")
    ctx["regime"] = regime_id
    ctx["regime_policy"] = policy.to_dict()
    ctx["regime_confidence"] = round(confidence, 3)
