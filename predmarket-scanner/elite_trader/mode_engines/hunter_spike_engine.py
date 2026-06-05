"""Hunter V2 — spike opportunity detection."""
from __future__ import annotations

from typing import Any


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    v = profile.get(key)
    return float(v) if v is not None else default


def evaluate_spike_opportunity(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    *,
    liq_score: float,
) -> dict[str, Any]:
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    ch = abs(float(signal.get("change") or 0))
    news = bool(ctx.get("news_shock") or signal.get("news_shock"))
    ob = abs(float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0))
    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    range_reject = bool(signal.get("range_reject") or ctx.get("range_reject"))

    spike_type = "volume_spike"
    if liq_score >= 75:
        spike_type = "liquidation_spike"
    elif news:
        spike_type = "news_spike"
    elif ob >= 0.35:
        spike_type = "orderbook_sweep_spike"
    elif ch >= 0.40 and vr < 1.5:
        spike_type = "volatility_spike"

    min_conf = _f(profile, "hunter_spike_min_confirmation_sec", 3)
    max_conf = _f(profile, "hunter_spike_max_confirmation_sec", 8)
    signal_age = float(signal.get("signal_age_sec") or ctx.get("signal_age_sec") or 0)
    entry_delay = min_conf
    if signal_age >= min_conf:
        entry_delay = min(signal_age, max_conf)

    exhaustion = 0.0
    if ch >= 0.45 and vr < 1.15:
        exhaustion = min(100.0, 40.0 + ch * 30.0)

    fake_spike = False
    fake_spike_reason = ""
    if range_reject:
        fake_spike = True
        fake_spike_reason = "range_reject"
    elif exhaustion >= 70:
        fake_spike = True
        fake_spike_reason = "spike_exhaustion"
    elif spread > 0.14 and ch < 0.25:
        fake_spike = True
        fake_spike_reason = "spread_spike_no_follow"

    continuation = ch >= 0.22 and vr >= 1.2 and not fake_spike

    return {
        "spike_type": spike_type,
        "spike_duration": round(signal_age, 1),
        "entry_delay_sec": round(entry_delay, 1),
        "spike_exhaustion_score": round(exhaustion, 1),
        "continuation_success": continuation,
        "fake_spike_result": fake_spike,
        "fake_spike_reason": fake_spike_reason,
        "await_spike_confirmation": signal_age < min_conf,
    }
