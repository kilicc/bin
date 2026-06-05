"""Berserk — her N kapanışta −PnL analizi; çıkış profilini otomatik sıkılaştır."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_AUTOTUNE_INTERVAL = 3
_BATCH_SIZE = 3
_LOOKBACK_LOSS = 24


def autotune_interval() -> int:
    return _AUTOTUNE_INTERVAL


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def _is_loss(row: dict[str, Any]) -> bool:
    return _pnl(row) < -0.005


def _is_sl(reason: str | None) -> bool:
    r = str(reason or "").upper()
    return r == "SL" or r.startswith("SL-")


def _reason(row: dict[str, Any]) -> str:
    return str(row.get("exit_reason") or "").upper()


def _fee_est(row: dict[str, Any], profile: dict[str, Any]) -> float:
    tf = float(row.get("total_fees") or 0)
    if tf > 0:
        return tf
    stake = max(float(row.get("stake_usd") or 120), 1.0)
    lev = max(int(row.get("leverage") or 5), 1)
    side = float(profile.get("paper_fee_side") or 0.0004)
    return stake * side * 2.0 * lev


def _sl_thr(stake: float, profile: dict[str, Any]) -> float:
    return max(stake * float(profile.get("sl_stake_pct") or 0.0024), 0.01)


def _soft_floor(stake: float, sl_thr: float, profile: dict[str, Any]) -> float:
    pct = float(profile.get("berserk_sl_soft_stake_pct") or 0.025)
    return max(sl_thr, stake * pct)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def analyze_loss_trades(
    batch: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    lookback_loss: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Son batch + −PnL geçmişinden profil patch öner (SL, STALE, fee kaybı dahil)."""
    loss_batch = [t for t in batch if _is_loss(t)]
    loss_hist = [t for t in (lookback_loss or []) if _is_loss(t)]
    if not loss_batch and not loss_hist:
        return {
            "patterns": [],
            "patch": {},
            "loss_in_batch": 0,
            "sl_in_batch": 0,
            "batch_size": len(batch),
        }

    recover_sec = float(profile.get("berserk_sl_recover_sec") or 90)
    min_sl_age = float(profile.get("berserk_sl_min_age_sec") or 120)
    grace = float(profile.get("berserk_tp_grace_sec") or 25)
    peak_min = float(profile.get("berserk_sl_peak_hold_min_usd") or 0.06)
    stale_min = float(profile.get("berserk_stale_min_age_sec") or 45)

    patch: dict[str, float] = {}
    patterns: list[str] = []

    def bump(key: str, val: float) -> None:
        patch[key] = val

    for t in loss_batch + loss_hist[-_LOOKBACK_LOSS:]:
        dur = float(t.get("duration") or 0)
        max_u = float(t.get("max_unreal_seen") or 0)
        min_u = float(t.get("min_unreal_seen") or 0)
        pnl = _pnl(t)
        reason = _reason(t)
        stake = max(float(t.get("stake_usd") or 120), 1.0)
        sl = _sl_thr(stake, profile)
        soft = _soft_floor(stake, sl, profile)
        fee = _fee_est(t, profile)

        # Kâra geçip −PnL ile kapandı (SL, STALE, fee — hepsi)
        if max_u >= peak_min and pnl < 0:
            tag = "peak_then_sl" if _is_sl(reason) else "peak_then_loss"
            patterns.append(tag)
            bump(
                "berserk_peak_spike_pullback_frac",
                _clamp(
                    float(profile.get("berserk_peak_spike_pullback_frac") or 0.55) - 0.04,
                    0.32,
                    0.62,
                ),
            )
            bump(
                "berserk_sl_peak_hold_sec",
                _clamp(float(profile.get("berserk_sl_peak_hold_sec") or 45) + 8, 35, 95),
            )
            bump(
                "berserk_peak_spike_loss_fee_mult",
                _clamp(
                    float(profile.get("berserk_peak_spike_loss_fee_mult") or 1.5) + 0.12,
                    1.2,
                    2.6,
                ),
            )
            bump(
                "berserk_stale_peak_hold_sec",
                _clamp(float(profile.get("berserk_stale_peak_hold_sec") or 60) + 8, 45, 120),
            )

        # Erken STALE − fee ile kırmızı (#202 AIN tipi)
        if "STALE" in reason and dur > 0 and dur < stale_min and max_u >= peak_min * 0.5:
            patterns.append("stale_early_release")
            bump(
                "berserk_stale_min_age_sec",
                _clamp(stale_min + 6, 40, 75),
            )
            bump(
                "berserk_stale_peak_hold_sec",
                _clamp(float(profile.get("berserk_stale_peak_hold_sec") or 60) + 10, 50, 130),
            )

        # Fee / mikro kayıp — TP veya STALE fark etmez
        if pnl < 0 and abs(pnl) <= fee * 1.85:
            patterns.append("fee_bleed_loss")
            bump(
                "berserk_sl_recover_fee_mult",
                _clamp(float(profile.get("berserk_sl_recover_fee_mult") or 1.05) - 0.05, 0.90, 1.12),
            )
            bump(
                "berserk_peak_spike_pullback_frac",
                _clamp(
                    float(patch.get("berserk_peak_spike_pullback_frac")
                          or profile.get("berserk_peak_spike_pullback_frac") or 0.55) - 0.03,
                    0.30,
                    0.62,
                ),
            )
            bump(
                "spike_fee_mult",
                _clamp(float(profile.get("spike_fee_mult") or 1.08) - 0.02, 1.02, 1.15),
            )

        if dur > 0 and abs(dur - recover_sec) <= 10:
            patterns.append("recover_cliff")
            bump("berserk_sl_recover_sec", _clamp(recover_sec + 12, 75, 150))
            bump(
                "berserk_sl_cliff_preempt_sec",
                _clamp(float(profile.get("berserk_sl_cliff_preempt_sec") or 12) + 3, 8, 25),
            )
            bump(
                "berserk_stale_dip_min_age_sec",
                _clamp(float(profile.get("berserk_stale_dip_min_age_sec") or 50) + 4, 40, 85),
            )

        if dur > 0 and abs(dur - min_sl_age) <= 12:
            patterns.append("min_age_cliff")
            bump("berserk_sl_min_age_sec", _clamp(min_sl_age + 12, 90, 180))
            bump(
                "berserk_sl_peak_extend_age_sec",
                _clamp(float(profile.get("berserk_sl_peak_extend_age_sec") or 90) + 10, 75, 130),
            )

        if pnl < 0 and pnl > -soft * 1.25:
            patterns.append("small_loss")
            bump(
                "berserk_sl_soft_stake_pct",
                _clamp(float(profile.get("berserk_sl_soft_stake_pct") or 0.025) + 0.0025, 0.018, 0.04),
            )
            bump(
                "berserk_sl_recover_fee_mult",
                _clamp(
                    float(patch.get("berserk_sl_recover_fee_mult")
                          or profile.get("berserk_sl_recover_fee_mult") or 1.05) - 0.04,
                    0.90,
                    1.12,
                ),
            )

        if max_u < peak_min * 0.45 and dur > 0 and dur <= recover_sec + 8:
            patterns.append("never_green_boundary")
            bump("berserk_tp_grace_sec", _clamp(grace + 4, 20, 48))

        if min_u <= -sl * 0.42 and pnl > -sl * 0.95:
            patterns.append("dip_recover_miss")
            bump(
                "berserk_sl_recover_dip_frac",
                _clamp(float(profile.get("berserk_sl_recover_dip_frac") or 0.5) - 0.04, 0.32, 0.58),
            )
            bump(
                "berserk_sl_recover_min_age_sec",
                _clamp(float(profile.get("berserk_sl_recover_min_age_sec") or 10) - 2, 4, 18),
            )

        if "STALE-DIP" in reason or reason == "STALE-DIP":
            patterns.append("stale_dip_loss")
            bump(
                "berserk_sl_cliff_preempt_sec",
                _clamp(
                    float(patch.get("berserk_sl_cliff_preempt_sec")
                          or profile.get("berserk_sl_cliff_preempt_sec") or 12) + 2,
                    8,
                    28,
                ),
            )

        if "STALE-DIP" in reason and dur > 0 and abs(dur - min_sl_age) <= 8:
            patterns.append("stale_dip_cliff")
            bump("berserk_sl_min_age_sec", _clamp(min_sl_age + 15, 90, 195))
            bump(
                "berserk_sl_cliff_preempt_sec",
                _clamp(float(profile.get("berserk_sl_cliff_preempt_sec") or 12) + 5, 10, 30),
            )

        if "TP-RECOVER" in reason and pnl < 0:
            patterns.append("tp_recover_net_loss")
            bump(
                "berserk_sl_recover_fee_mult",
                _clamp(float(profile.get("berserk_sl_recover_fee_mult") or 1.02) + 0.04, 1.0, 1.15),
            )

        if "SPIKE" in reason and pnl < 0 and max_u >= peak_min:
            patterns.append("spike_net_loss")
            bump(
                "berserk_peak_spike_pullback_frac",
                _clamp(float(profile.get("berserk_peak_spike_pullback_frac") or 0.55) - 0.05, 0.30, 0.60),
            )
            bump(
                "berserk_spike_min_net_fee_mult",
                _clamp(float(profile.get("berserk_spike_min_net_fee_mult") or 1.22) + 0.05, 1.15, 1.45),
            )

        if _is_sl(reason) and pnl < -sl * 2.5:
            patterns.append("large_sl")
            bump(
                "berserk_sl_catastrophic_stake_pct",
                _clamp(float(profile.get("berserk_sl_catastrophic_stake_pct") or 0.08) - 0.01, 0.05, 0.10),
            )
            bump("berserk_tp_grace_sec", _clamp(grace + 5, 20, 50))

    if len(loss_batch) >= 2 and len(loss_batch) >= len(batch) - 1:
        patterns.append("loss_streak")
        cur = float(patch.get("berserk_sl_recover_sec") or recover_sec)
        bump("berserk_sl_recover_sec", _clamp(cur + 8, 75, 150))

    sl_in_batch = sum(1 for t in loss_batch if _is_sl(t.get("exit_reason")))
    return {
        "patterns": sorted(set(patterns)),
        "patch": patch,
        "loss_in_batch": len(loss_batch),
        "sl_in_batch": sl_in_batch,
        "batch_size": len(batch),
    }


# Geriye uyumluluk
analyze_sl_trades = analyze_loss_trades


def apply_berserk_sl_autotune(
    batch: list[dict[str, Any]],
    book_closed: list[dict[str, Any]],
    *,
    trade_n: int,
) -> dict[str, Any]:
    """Her 3 kapanışta −PnL → çıkış profili otomatik ayarı (yalnızca berserk)."""
    from elite_trader.mode_profiles import get_profile, save_profile

    profile = get_profile("berserk") or {}
    analysis = analyze_loss_trades(
        batch[-_BATCH_SIZE:],
        profile,
        lookback_loss=[c for c in book_closed if _is_loss(c)][-_LOOKBACK_LOSS:],
    )
    out: dict[str, Any] = {
        "trade_n": trade_n,
        "at": datetime.now(timezone.utc).isoformat(),
        "patterns": analysis.get("patterns") or [],
        "loss_in_batch": analysis.get("loss_in_batch", 0),
        "sl_in_batch": analysis.get("sl_in_batch", 0),
        "applied": False,
        "patch": {},
    }
    patch = analysis.get("patch") or {}
    if not patch:
        out["note"] = "no_loss_patterns"
        return out

    save_profile("berserk", patch)
    out["applied"] = True
    out["patch"] = patch
    parts = ", ".join(f"{k}={v}" for k, v in sorted(patch.items()))
    print(
        f"  🧬 Berserk −PnL autotune #{trade_n}: "
        f"{out['loss_in_batch']}/{analysis.get('batch_size')} zarar "
        f"({out['sl_in_batch']} SL) — "
        f"{','.join(out['patterns'][:5])} → {parts}"
    )
    return out
