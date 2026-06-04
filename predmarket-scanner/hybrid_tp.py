"""Değişken TP: spike skoru → runner (%17–25 stake) veya micro katmanlar."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class HybridTpPlan:
    mode: str  # micro | runner | drought
    tp_stake_pct: float
    trigger_frac: float
    spike_score: float
    label: str


def hybrid_enabled() -> bool:
    return os.getenv("HYBRID_TP_ENABLED", "0").strip().lower() in ("1", "true", "yes")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default




def compute_spike_score(
    *,
    entry_edge: float,
    entry_price: float,
    side: str,
    true_prob: float,
    momentum: float | None,
    unrealized_pct: float,
    hours_left: float | None,
) -> float:
    score = 0.0
    e = abs(float(entry_edge or 0.0))
    score += min(0.32, e * 1.15)

    runway = abs(float(true_prob) - 0.5)
    score += min(0.22, runway * 0.9)

    ep = float(entry_price or 0.5)
    if ep < 0.52:
        score += 0.14
    elif ep < 0.62:
        score += 0.07

    if momentum is not None:
        mom = float(momentum)
        if side == "YES" and mom > 0:
            score += min(0.22, abs(mom) * 45.0)
        elif side == "NO" and mom < 0:
            score += min(0.22, abs(mom) * 45.0)

    if unrealized_pct > 0.004:
        score += min(0.12, unrealized_pct * 10.0)

    if hours_left is not None and 0 < hours_left < 8.0:
        score += 0.06

    return max(0.0, min(1.0, score))


def resolve_hybrid_tp(
    micro_tp_pct: float,
    micro_trigger_frac: float,
    *,
    spike_score: float,
    drought: bool | None = None,
) -> HybridTpPlan:
    if drought is None:
        drought = drought_active()

    if drought:
        base = _f("HYBRID_TP_FAST_BASE_PCT", 0.005)
        trig = _f("HYBRID_TP_FAST_TRIGGER_FRAC", 0.97)
        nano = _f("HYBRID_TP_FAST_NANO_PCT", 0.002)
        pct = min(float(micro_tp_pct), base, nano) if nano > 0 else min(float(micro_tp_pct), base)
        return HybridTpPlan(
            "drought",
            pct,
            trig,
            spike_score,
            f"kuraklık micro {pct * 100:.2f}%",
        )

    if not hybrid_enabled():
        return HybridTpPlan(
            "micro",
            float(micro_tp_pct),
            float(micro_trigger_frac),
            spike_score,
            "micro",
        )

    thresh = _f("HYBRID_TP_SPIKE_THRESHOLD", 0.52)
    rmin = _f("HYBRID_TP_RUNNER_MIN_PCT", 0.17)
    rmax = _f("HYBRID_TP_RUNNER_MAX_PCT", 0.25)

    if spike_score >= thresh:
        t = (spike_score - thresh) / max(0.08, 1.0 - thresh)
        pct = rmin + (rmax - rmin) * min(1.0, t)
        return HybridTpPlan(
            "runner",
            pct,
            float(micro_trigger_frac),
            spike_score,
            f"runner {pct * 100:.0f}% (spike={spike_score:.2f})",
        )

    return HybridTpPlan(
        "micro",
        float(micro_tp_pct),
        float(micro_trigger_frac),
        spike_score,
        f"micro (spike={spike_score:.2f})",
    )


def trail_should_exit(
    *,
    mode: str,
    tp_target_usd: float,
    unrealized: float,
    momentum: float | None,
    side: str,
) -> bool:
    if mode != "runner":
        return False
    if os.getenv("HYBRID_TP_TRAIL_ENABLED", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    if unrealized < tp_target_usd * 0.5:
        return False
    if momentum is None:
        return False
    mom = float(momentum)
    if side == "YES" and mom < -0.0025:
        return True
    if side == "NO" and mom > 0.0025:
        return True
    return False
