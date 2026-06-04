"""
Evrim — price action yapı analizi (5m mumlar).

Yalnızca hybrid skor katkısı; tek başına işlem açmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PATTERN_NAMES = (
    "breakout",
    "fake_breakout",
    "liquidity_grab",
    "stop_hunt",
    "wick_rejection",
    "momentum_candle",
    "engulfing",
    "range_breakout",
    "micro_hh_hl",
    "micro_ll_lh",
    "body_expansion",
    "consecutive_pressure",
    "strong_close_long",
    "strong_close_short",
    "volume_breakout",
    "volume_breakdown",
)

DEFAULT_PA_WEIGHTS: dict[str, float] = {
    "breakout": 1.0,
    "fake_breakout": 1.0,
    "liquidity_grab": 1.0,
    "stop_hunt": 1.0,
    "wick_rejection": 1.0,
    "momentum_candle": 1.0,
    "engulfing": 1.0,
    "range_breakout": 1.0,
    "micro_hh_hl": 1.0,
    "micro_ll_lh": 1.0,
    "body_expansion": 1.0,
    "consecutive_pressure": 1.0,
    "strong_close_long": 1.0,
    "strong_close_short": 1.0,
    "volume_breakout": 1.0,
    "volume_breakdown": 1.0,
}


@dataclass
class PaAnalysis:
    patterns: dict[str, dict[str, Any]] = field(default_factory=dict)
    long_score: float = 0.0
    short_score: float = 0.0
    aligned_score: float = 0.0
    fake_breakout_prob: float = 0.0
    veto: bool = False
    stake_mult: float = 1.0
    score_penalty: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_context_dict(self) -> dict[str, Any]:
        detected = [k for k, v in self.patterns.items() if v.get("detected")]
        return {
            "patterns": self.patterns,
            "detected": detected,
            "long_score": round(self.long_score, 1),
            "short_score": round(self.short_score, 1),
            "aligned_score": round(self.aligned_score, 1),
            "fake_breakout_prob": round(self.fake_breakout_prob, 3),
            "veto": self.veto,
            "stake_mult": self.stake_mult,
            "notes": self.notes[:12],
        }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _body(c: dict) -> float:
    return abs(float(c.get("c", 0)) - float(c.get("o", 0)))


def _range(c: dict) -> float:
    return max(float(c.get("h", 0)) - float(c.get("l", 0)), 1e-12)


def _bull(c: dict) -> bool:
    return float(c.get("c", 0)) >= float(c.get("o", 0))


def _upper_wick(c: dict) -> float:
    o, h, c_ = float(c.get("o", 0)), float(c.get("h", 0)), float(c.get("c", 0))
    return h - max(o, c_)


def _lower_wick(c: dict) -> float:
    o, l, c_ = float(c.get("o", 0)), float(c.get("l", 0)), float(c.get("c", 0))
    return min(o, c_) - l


def _close_strength(c: dict, side: str) -> float:
    """0-10: güçlü kapanış (zayıf karşı fitil)."""
    rng = _range(c)
    if rng <= 0:
        return 0.0
    if side == "LONG":
        near_high = (float(c.get("h", 0)) - float(c.get("c", 0))) / rng
        return _clamp((1.0 - near_high) * 12, 0, 10)
    near_low = (float(c.get("c", 0)) - float(c.get("l", 0))) / rng
    return _clamp((1.0 - near_low) * 12, 0, 10)


def _range_bounds(candles: list[dict], lookback: int = 12) -> tuple[float, float, float]:
    window = candles[-lookback - 1 : -1] if len(candles) > lookback + 1 else candles[:-1]
    if not window:
        window = candles[:-1]
    highs = [float(x["h"]) for x in window]
    lows = [float(x["l"]) for x in window]
    if not highs:
        p = float(candles[-1]["c"])
        return p, p, p
    return max(highs), min(lows), (max(highs) + min(lows)) / 2


def _avg_body(candles: list[dict], n: int = 10) -> float:
    bodies = [_body(c) for c in candles[-n:]]
    return sum(bodies) / max(1, len(bodies))


def _micro_structure(candles: list[dict]) -> tuple[bool, bool]:
    """micro HH/HL ve micro LL/LH (son 5 swing basit)."""
    if len(candles) < 6:
        return False, False
    highs = [float(c["h"]) for c in candles[-6:]]
    lows = [float(c["l"]) for c in candles[-6:]]
    hh = highs[-1] > max(highs[:-2]) and highs[-2] >= highs[-4]
    hl = lows[-1] > lows[-3] and lows[-2] >= lows[-4]
    ll = lows[-1] < min(lows[:-2]) and lows[-2] <= lows[-4]
    lh = highs[-1] < highs[-3] and highs[-2] <= highs[-4]
    return (hh and hl), (ll and lh)


def _detect_breakout(candles: list[dict], vol_ratio: float) -> dict[str, Any]:
    rh, rl, _ = _range_bounds(candles, 12)
    last = candles[-1]
    c = float(last["c"])
    up = c > rh * 1.0002
    down = c < rl * 0.9998
    if not up and not down:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    side = "LONG" if up else "SHORT"
    sc = 6.0 + min(3.0, vol_ratio * 0.8)
    return {"detected": True, "score": _clamp(sc, 0, 10), "side_bias": side}


def _detect_fake_breakout(candles: list[dict]) -> dict[str, Any]:
    if len(candles) < 16:
        return {"detected": False, "score": 0.0, "side_bias": "neutral", "prob": 0.0}
    rh, rl, _ = _range_bounds(candles[:-4], 12)
    for i in range(-4, -1):
        c = float(candles[i]["c"])
        broke_up = c > rh
        broke_dn = c < rl
        if not broke_up and not broke_dn:
            continue
        last_c = float(candles[-1]["c"])
        reverted = (broke_up and last_c < rh) or (broke_dn and last_c > rl)
        if reverted:
            prob = 0.65
            last = candles[-1]
            if _body(last) / _range(last) < 0.35:
                prob += 0.12
            return {
                "detected": True,
                "score": 8.0,
                "side_bias": "SHORT" if broke_up else "LONG",
                "prob": _clamp(prob, 0, 1),
            }
    return {"detected": False, "score": 0.0, "side_bias": "neutral", "prob": 0.0}


def _detect_liquidity_grab(candles: list[dict]) -> dict[str, Any]:
    last = candles[-1]
    rh, rl, _ = _range_bounds(candles, 12)
    rng = _range(last)
    if rng <= 0:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    uw, lw = _upper_wick(last), _lower_wick(last)
    c, o = float(last["c"]), float(last["o"])
    if lw > rng * 0.55 and c > rl and c > o:
        return {"detected": True, "score": 7.5, "side_bias": "LONG"}
    if uw > rng * 0.55 and c < rh and c < o:
        return {"detected": True, "score": 7.5, "side_bias": "SHORT"}
    return {"detected": False, "score": 0.0, "side_bias": "neutral"}


def _detect_stop_hunt(candles: list[dict]) -> dict[str, Any]:
    last = candles[-1]
    rng = _range(last)
    if rng <= 0:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    uw, lw = _upper_wick(last), _lower_wick(last)
    body = _body(last)
    if lw > rng * 0.65 and body < rng * 0.25:
        return {"detected": True, "score": 8.5, "side_bias": "LONG"}
    if uw > rng * 0.65 and body < rng * 0.25:
        return {"detected": True, "score": 8.5, "side_bias": "SHORT"}
    return {"detected": False, "score": 0.0, "side_bias": "neutral"}


def _detect_wick_rejection(candles: list[dict]) -> dict[str, Any]:
    last = candles[-1]
    rng = _range(last)
    body = _body(last)
    if rng <= 0 or body / rng > 0.45:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    uw, lw = _upper_wick(last), _lower_wick(last)
    if uw > rng * 0.6:
        return {"detected": True, "score": 7.0, "side_bias": "SHORT"}
    if lw > rng * 0.6:
        return {"detected": True, "score": 7.0, "side_bias": "LONG"}
    return {"detected": False, "score": 0.0, "side_bias": "neutral"}


def _detect_momentum_candle(candles: list[dict]) -> dict[str, Any]:
    last = candles[-1]
    avg = _avg_body(candles, 10)
    body = _body(last)
    rng = _range(last)
    if avg <= 0 or body < avg * 1.5:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    opp_wick = _lower_wick(last) if _bull(last) else _upper_wick(last)
    if opp_wick > rng * 0.35:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    side = "LONG" if _bull(last) else "SHORT"
    return {"detected": True, "score": _clamp(body / avg * 4, 5, 10), "side_bias": side}


def _detect_engulfing(candles: list[dict]) -> dict[str, Any]:
    if len(candles) < 2:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    prev, last = candles[-2], candles[-1]
    po, pc = float(prev["o"]), float(prev["c"])
    lo, lc = float(last["o"]), float(last["c"])
    if _bull(last) and not _bull(prev) and lo <= pc and lc >= po:
        return {"detected": True, "score": 8.0, "side_bias": "LONG"}
    if not _bull(last) and _bull(prev) and lo >= pc and lc <= po:
        return {"detected": True, "score": 8.0, "side_bias": "SHORT"}
    return {"detected": False, "score": 0.0, "side_bias": "neutral"}


def _detect_range_breakout(candles: list[dict]) -> dict[str, Any]:
    if len(candles) < 15:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    window = candles[-15:-1]
    ranges = [_range(c) for c in window]
    avg_r = sum(ranges) / max(1, len(ranges))
    last_r = _range(candles[-1])
    rh, rl, _ = _range_bounds(candles, 14)
    width = (rh - rl) / max(rl, 1e-12) * 100
    if width > 0.35 or last_r < avg_r * 0.9:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    c = float(candles[-1]["c"])
    if c > rh:
        return {"detected": True, "score": 7.0, "side_bias": "LONG"}
    if c < rl:
        return {"detected": True, "score": 7.0, "side_bias": "SHORT"}
    return {"detected": False, "score": 0.0, "side_bias": "neutral"}


def _detect_body_expansion(candles: list[dict], side: str) -> dict[str, Any]:
    last = candles[-1]
    avg = _avg_body(candles, 10)
    body = _body(last)
    if avg <= 0 or body < avg * 1.4:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    bull = _bull(last)
    if side == "LONG" and bull:
        return {"detected": True, "score": 7.5, "side_bias": "LONG"}
    if side == "SHORT" and not bull:
        return {"detected": True, "score": 7.5, "side_bias": "SHORT"}
    return {"detected": False, "score": 0.0, "side_bias": "neutral"}


def _detect_consecutive_pressure(candles: list[dict]) -> dict[str, Any]:
    if len(candles) < 4:
        return {"detected": False, "score": 0.0, "side_bias": "neutral"}
    last3 = candles[-3:]
    bulls = [_bull(c) for c in last3]
    bodies = [_body(c) for c in last3]
    if all(bulls) and bodies[-1] >= bodies[-2] >= bodies[-3] * 0.9:
        return {"detected": True, "score": 7.0, "side_bias": "LONG"}
    if not any(bulls) and bodies[-1] >= bodies[-2] >= bodies[-3] * 0.9:
        return {"detected": True, "score": 7.0, "side_bias": "SHORT"}
    return {"detected": False, "score": 0.0, "side_bias": "neutral"}


def _load_pa_weights(profile: dict[str, Any] | None) -> dict[str, float]:
    weights = dict(DEFAULT_PA_WEIGHTS)
    try:
        from elite_trader.evrim_training import load_training_state

        st = load_training_state()
        for k, v in (st.get("pa_weights") or {}).items():
            weights[k] = float(v)
    except Exception:
        pass
    if profile:
        for k, v in (profile.get("pa_weights") or {}).items():
            weights[k] = float(v)
    return weights


def analyze_price_action(
    candles: list[dict],
    side: str,
    *,
    vol_ratio: float = 1.0,
    profile: dict[str, Any] | None = None,
) -> PaAnalysis:
    """Mum dizisinden PA yapıları + fake breakout olasılığı."""
    side = str(side or "LONG").upper()
    notes: list[str] = []
    patterns: dict[str, dict[str, Any]] = {}

    if len(candles) < 8:
        return PaAnalysis(notes=["insufficient_candles"])

    vol_target = float((profile or {}).get("evrim_vol_mult") or 1.8)
    weights = _load_pa_weights(profile)

    patterns["breakout"] = _detect_breakout(candles, vol_ratio)
    fake = _detect_fake_breakout(candles)
    patterns["fake_breakout"] = {
        "detected": fake.get("detected"),
        "score": fake.get("score", 0),
        "side_bias": fake.get("side_bias", "neutral"),
    }
    patterns["liquidity_grab"] = _detect_liquidity_grab(candles)
    patterns["stop_hunt"] = _detect_stop_hunt(candles)
    patterns["wick_rejection"] = _detect_wick_rejection(candles)
    patterns["momentum_candle"] = _detect_momentum_candle(candles)
    patterns["engulfing"] = _detect_engulfing(candles)
    patterns["range_breakout"] = _detect_range_breakout(candles)
    hh_hl, ll_lh = _micro_structure(candles)
    patterns["micro_hh_hl"] = {
        "detected": hh_hl,
        "score": 8.0 if hh_hl else 0.0,
        "side_bias": "LONG",
    }
    patterns["micro_ll_lh"] = {
        "detected": ll_lh,
        "score": 8.0 if ll_lh else 0.0,
        "side_bias": "SHORT",
    }
    patterns["body_expansion"] = _detect_body_expansion(candles, side)
    patterns["consecutive_pressure"] = _detect_consecutive_pressure(candles)

    sc_long = _close_strength(candles[-1], "LONG")
    sc_short = _close_strength(candles[-1], "SHORT")
    patterns["strong_close_long"] = {
        "detected": sc_long >= 6,
        "score": sc_long,
        "side_bias": "LONG",
    }
    patterns["strong_close_short"] = {
        "detected": sc_short >= 6,
        "score": sc_short,
        "side_bias": "SHORT",
    }
    bo = patterns["breakout"]
    patterns["volume_breakout"] = {
        "detected": bo.get("detected") and bo.get("side_bias") == "LONG" and vol_ratio >= vol_target,
        "score": 8.0 if bo.get("detected") and vol_ratio >= vol_target else 0.0,
        "side_bias": "LONG",
    }
    patterns["volume_breakdown"] = {
        "detected": bo.get("detected") and bo.get("side_bias") == "SHORT" and vol_ratio >= vol_target,
        "score": 8.0 if bo.get("detected") and vol_ratio >= vol_target else 0.0,
        "side_bias": "SHORT",
    }

    long_sum = short_sum = 0.0
    long_w = short_w = 0.0
    for name, p in patterns.items():
        if not p.get("detected"):
            continue
        sc = float(p.get("score") or 0) * weights.get(name, 1.0)
        bias = str(p.get("side_bias") or "neutral")
        if bias == "LONG":
            long_sum += sc
            long_w += 1
        elif bias == "SHORT":
            short_sum += sc
            short_w += 1

    long_score = _clamp(long_sum / max(1, long_w) * 10, 0, 100) if long_w else 0
    short_score = _clamp(short_sum / max(1, short_w) * 10, 0, 100) if short_w else 0
    aligned_score = long_score if side == "LONG" else short_score

    fake_prob = float(fake.get("prob") or 0.0)
    if patterns["fake_breakout"].get("detected"):
        fake_prob = max(fake_prob, 0.55)
    if patterns["breakout"].get("detected") and patterns["fake_breakout"].get("detected"):
        fake_prob = max(fake_prob, 0.72)
    if vol_ratio < vol_target * 0.75 and patterns["breakout"].get("detected"):
        fake_prob = min(1.0, fake_prob + 0.15)

    veto_thresh = float((profile or {}).get("evrim_pa_fake_veto_threshold") or 0.72)
    stake_floor = float((profile or {}).get("evrim_pa_fake_stake_mult") or 0.55)
    veto = False
    stake_mult = 1.0
    score_penalty = 0.0

    if fake_prob >= veto_thresh:
        veto = True
        notes.append(f"fake_breakout_veto_{fake_prob:.2f}")
    elif fake_prob >= 0.55:
        stake_mult = stake_floor
        score_penalty = 3.0 + (fake_prob - 0.55) * 5
        notes.append(f"fake_breakout_stake_{fake_prob:.2f}")

    for name, p in patterns.items():
        if p.get("detected") and p.get("side_bias") == side:
            notes.append(name)

    return PaAnalysis(
        patterns=patterns,
        long_score=long_score,
        short_score=short_score,
        aligned_score=aligned_score,
        fake_breakout_prob=fake_prob,
        veto=veto,
        stake_mult=stake_mult,
        score_penalty=score_penalty,
        notes=notes,
    )


def score_component(
    signal: dict[str, Any],
    side: str,
    ctx: dict[str, Any],
    profile: dict[str, Any],
    *,
    max_points: float = 25.0,
) -> tuple[float, PaAnalysis | None, list[str]]:
    """
    Hybrid price_action bileşeni (0-max_points) + PaAnalysis.
    """
    notes: list[str] = []
    if not profile.get("evrim_pa_enabled", True):
        return _legacy_momentum_pa(signal, side, ctx, max_points)

    candles = ctx.get("klines_5m") or signal.get("_pa_candles") or []
    if len(candles) < 8:
        legacy, n = _legacy_momentum_pa(signal, side, ctx, max_points)
        return legacy, None, n

    vol_ratio = float(ctx.get("vol_ratio") or 1.0)
    pa = analyze_price_action(candles, side, vol_ratio=vol_ratio, profile=profile)

    aligned = pa.aligned_score
    base = _clamp(aligned / 100.0 * 18.0, 0, 18.0)
    ch = abs(float(signal.get("change") or 0))
    strength = str(signal.get("strength") or "Medium")
    if strength == "Strong":
        base += 3
    elif strength == "Medium":
        base += 1.5
    d3 = str(ctx.get("direction_3") or "none")
    if side == "LONG" and d3 == "up":
        base += 2
    elif side == "SHORT" and d3 == "down":
        base += 2

    base -= pa.score_penalty
    score = _clamp(base, 0, max_points)
    notes.extend(pa.notes[:8])
    return score, pa, notes


def _legacy_momentum_pa(
    signal: dict[str, Any], side: str, ctx: dict[str, Any], max_points: float
) -> tuple[float, list[str]]:
    notes: list[str] = []
    ch = abs(float(signal.get("change") or 0))
    strength = str(signal.get("strength") or "Medium")
    move = ch / 100.0
    raw = min(0.35, move * 40.0)
    s = _clamp(raw / 0.35, 0, 1) * (max_points * 0.56)
    if strength == "Strong":
        s += max_points * 0.24
    elif strength == "Medium":
        s += max_points * 0.12
    d3 = str(ctx.get("direction_3") or "none")
    if side == "LONG" and d3 == "up":
        s += max_points * 0.16
        notes.append("3m_up")
    elif side == "SHORT" and d3 == "down":
        s += max_points * 0.16
        notes.append("3m_down")
    elif d3 != "none":
        s -= max_points * 0.12
    regime = str(ctx.get("regime") or "")
    if "trend" in regime:
        if (side == "LONG" and "up" in regime) or (side == "SHORT" and "down" in regime):
            s += max_points * 0.08
    return _clamp(s, 0, max_points), notes


def apply_pa_to_context(ctx: dict[str, Any], pa: PaAnalysis | None) -> None:
    if pa:
        ctx["pa"] = pa.to_context_dict()
