"""Berserk-only exit tuning — SL azalt, dip sonrası TP/spike öncelikli."""
from __future__ import annotations

from typing import Any

from elite_trader.fee_economics import round_trip_fee_usd


def _profile(mode_id: str) -> dict[str, Any]:
    from elite_trader.panel_strategy import mode_catalog

    return mode_catalog().get(mode_id) or {}


def _age_sec(opened_at: str | None) -> float:
    from elite_trader.panel_strategy import position_age_seconds

    return position_age_seconds({"opened_at_iso": opened_at})


def _fee_floor(stake_usd: float, leverage: int, profile: dict[str, Any]) -> float:
    mult = float(profile.get("spike_fee_mult") or 1.08)
    return round_trip_fee_usd(stake_usd, max(int(leverage), 1)) * mult / 2.0


def berserk_grace_sec(profile: dict[str, Any] | None = None) -> float:
    p = profile or _profile("berserk")
    grace = float(
        p.get("berserk2_tp_grace_sec") or p.get("berserk_tp_grace_sec") or 0
    )
    if grace <= 0:
        grace = max(
            float(p.get("min_hold_before_sl_sec") or 0),
            float(p.get("spike_min_age_sec") or 4) + 4.0,
        )
    return max(0.0, grace)


def berserk_sl_blocked_by_grace(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    sl_target_usd: float,
    profile: dict[str, Any] | None = None,
) -> bool:
    if unrealized_usd > -float(sl_target_usd):
        return False
    grace = berserk_grace_sec(profile)
    if grace <= 0:
        return False
    return _age_sec(opened_at) < grace


def _soft_sl_floor_usd(stake: float, sl_thr: float, profile: dict[str, Any]) -> float:
    pct = float(profile.get("berserk_sl_soft_stake_pct") or 0.02)
    return max(sl_thr, stake * pct)


def _effective_min_sl_age(
    age: float, max_unreal_seen: float, profile: dict[str, Any]
) -> float:
    base = float(profile.get("berserk_sl_min_age_sec") or 90)
    peak_min = float(profile.get("berserk_sl_peak_hold_min_usd") or 0.06)
    if float(max_unreal_seen) >= peak_min:
        ext = float(profile.get("berserk_sl_peak_extend_age_sec") or 75)
        return max(base, ext)
    return base


def _min_net_gross_usd(
    stake_usd: float,
    leverage: int,
    mode_id: str = "berserk",
) -> float:
    """Fee+vergi sonrası net+ için minimum brüt unrealized."""
    try:
        from elite_trader.fee_economics import min_gross_for_final_net

        return min_gross_for_final_net(
            stake_usd, max(int(leverage), 1), mode_id=mode_id
        )
    except Exception:
        fee = _fee_floor(stake_usd, leverage, _profile(mode_id))
        return max(fee * 2.0, 0.08)


def berserk_peak_spike_before_sl(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    sl_target_usd: float,
    stake_usd: float,
    max_unreal_seen: float,
    leverage: int = 5,
    profile: dict[str, Any] | None = None,
    mode_id: str = "berserk",
) -> str | None:
    """Kâra geçmiş pozisyon geri çekilince küçük kârla kapat (SL/STALE yerine)."""
    p = profile or _profile(mode_id)
    if not p.get("berserk_sl_to_tp_enabled", True):
        return None
    peak_min = float(p.get("berserk_sl_peak_hold_min_usd") or 0.06)
    peak = float(max_unreal_seen)
    if peak < peak_min or tp_target_usd <= 0:
        return None
    fee = _fee_floor(stake_usd, leverage, p)
    min_gross = _min_net_gross_usd(stake_usd, leverage, mode_id)
    tp_frac = float(p.get("berserk_peak_spike_min_tp_frac") or 0.08)
    peak_was_real = peak >= max(min_gross * 0.92, fee * 0.85, tp_target_usd * tp_frac)
    if not peak_was_real:
        return None
    if unrealized_usd >= tp_target_usd * 0.90:
        return None
    unreal = float(unrealized_usd)
    # Tepe yakınında anında kilitle — geri çekilmeyi bekleme
    instant_mult = float(p.get("berserk_instant_scalp_mult") or 1.03)
    instant_age = float(p.get("berserk_instant_scalp_min_age_sec") or 0.5)
    if _age_sec(opened_at) >= instant_age and unreal >= min_gross * instant_mult:
        if unreal >= peak * float(p.get("berserk_instant_scalp_peak_frac") or 0.94):
            return "SPIKE-FLASH"
    if unreal >= min_gross:
        pullback = float(p.get("berserk_peak_spike_pullback_frac") or 0.88)
        trail = max(min_gross, peak * pullback)
        if unreal <= trail and unreal >= min_gross * 0.98:
            return "SPIKE-PEAK"
        if unreal >= min_gross and unreal <= peak * 0.94:
            return "SPIKE-PEAK"
    return None


def berserk_sl_recovery_reason(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    sl_target_usd: float,
    stake_usd: float,
    min_unreal_seen: float,
    leverage: int = 5,
    profile: dict[str, Any] | None = None,
) -> str | None:
    """Dibe vurup fee üstüne çıkınca SL yerine TP-RECOVER."""
    p = profile or _profile("berserk")
    if not p.get("berserk_sl_to_tp_enabled", True):
        return None
    age = _age_sec(opened_at)
    min_age = float(p.get("berserk_sl_recover_min_age_sec") or 10)
    if age < min_age:
        return None
    dip_frac = float(p.get("berserk_sl_recover_dip_frac") or 0.50)
    sl_thr = float(sl_target_usd)
    if sl_thr <= 0:
        return None
    if float(min_unreal_seen) > -sl_thr * dip_frac:
        return None
    from elite_trader.fee_economics import round_trip_fee_usd

    mult = max(1.05, float(p.get("berserk_sl_recover_fee_mult") or 1.02))
    be = round_trip_fee_usd(stake_usd, max(int(leverage), 1)) * mult
    if unrealized_usd >= be:
        return "TP-RECOVER"
    return None


def berserk_stale_dip_exit(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    sl_target_usd: float,
    stake_usd: float,
    min_unreal_seen: float,
    leverage: int = 5,
    mode_id: str = "berserk",
    profile: dict[str, Any] | None = None,
) -> str | None:
    """Recovery/min-age cliff öncesi küçük zararda SL yerine STALE-DIP."""
    p = profile or _profile(mode_id)
    if p.get("berserk2_stale_dip_enabled") is False:
        return None
    age = _age_sec(opened_at)
    recover_sec = float(p.get("berserk_sl_recover_sec") or 75)
    min_sl_age = float(p.get("berserk_sl_min_age_sec") or 90)
    cliff_preempt = float(p.get("berserk_sl_cliff_preempt_sec") or 12)
    sl_thr = max(float(sl_target_usd), 0.01)
    stake = max(float(stake_usd), 1.0)
    unreal = float(unrealized_usd)
    soft = _soft_sl_floor_usd(stake, sl_thr, p)
    fee = _fee_floor(stake, leverage, p)
    min_gross = _min_net_gross_usd(stake, leverage, mode_id)
    min_age = float(p.get("berserk_stale_dip_min_age_sec") or 50)

    def _dip_ok(unreal: float) -> bool:
        """Fee öldürme bölgesinde kapatma — TP/SPIKE-QUICK bekle."""
        if unreal >= min_gross:
            return False
        if unreal > 0:
            return False
        return True

    # Cliff guard — yalnızca küçük zarar (büyük STALE-DIP engeli)
    cliff_loss_cap = max(fee * 2.5, sl_thr * 1.15)
    for cliff_at in (recover_sec, min_sl_age):
        if cliff_at <= 0:
            continue
        if age >= max(min_age, cliff_at - cliff_preempt) and age < cliff_at + 4:
            if unreal >= -cliff_loss_cap and unreal >= -fee * 2.2 and _dip_ok(unreal):
                return "STALE-DIP"

    if unreal > -soft:
        return None
    if age < recover_sec:
        return None
    if age < min_age:
        return None
    if float(min_unreal_seen) <= -sl_thr * 0.45 and unreal >= fee * 0.85:
        if unreal >= -cliff_loss_cap and _dip_ok(unreal):
            return "STALE-DIP"
    if unreal >= -fee * 1.5 and age >= min_age + 15:
        if unreal >= -cliff_loss_cap and _dip_ok(unreal):
            return "STALE-DIP"
    return None


def berserk_stale_reason(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    stake_usd: float,
    min_unreal_seen: float,
    max_unreal_seen: float,
    leverage: int = 5,
    mode_id: str = "berserk",
    profile: dict[str, Any] | None = None,
) -> str:
    """
    Berserk STALE — erken STALE-RELEASE engeli; yeşil görmüş pozisyon TP/spike bekler.
    (#202 AIN: +$0.70 peak, 9sn STALE → fee ile -$0.02)
    """
    p = profile or _profile(mode_id)
    if not p.get("stale_enabled", True):
        return ""
    age = _age_sec(opened_at)
    min_age = float(p.get("berserk_stale_min_age_sec") or 45)
    if age < min_age:
        return ""
    if unrealized_usd >= tp_target_usd * 0.995:
        return ""
    fee = _fee_floor(stake_usd, leverage, p)
    peak = float(max_unreal_seen)
    peak_hold = float(p.get("berserk_stale_peak_hold_sec") or 60)
    if peak >= max(fee, tp_target_usd * 0.08) and age < peak_hold:
        return ""
    min_tp = max(fee * 0.95, tp_target_usd * 0.35, stake_usd * 0.0012)
    try:
        from elite_trader.fee_economics import min_gross_for_final_net

        min_net_gross = min_gross_for_final_net(
            stake_usd, leverage, mode_id=mode_id
        )
        min_tp = max(min_tp, min_net_gross)
    except Exception:
        pass
    if float(unrealized_usd) < min_tp:
        return ""
    sl_thr = max(float(stake_usd) * float(p.get("sl_stake_pct") or 0.0024), 0.01)
    loss_thr = -max(sl_thr * 0.5, fee * 2)
    if float(min_unreal_seen) <= loss_thr and float(unrealized_usd) >= min_tp and age >= 30:
        return "STALE-RECOVER"
    if float(unrealized_usd) >= min_tp:
        return "STALE-RELEASE"
    return ""


def berserk_sl_exit_allowed(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    sl_target_usd: float,
    stake_usd: float,
    max_unreal_seen: float,
    profile: dict[str, Any] | None = None,
) -> bool:
    """
    Berserk planlı SL — 45sn'de saat gibi toplu SL (cliff) engellendi.
    Önce bekleme penceresi, sonra yalnızca anlamlı kayıp veya felaket.
    """
    p = profile or _profile("berserk")
    if p.get("berserk2_sl_enabled") is False or p.get("berserk_sl_enabled") is False:
        return False
    sl_thr = max(float(sl_target_usd), 0.01)
    stake = max(float(stake_usd), 1.0)
    unreal = float(unrealized_usd)
    age = _age_sec(opened_at)

    grace = berserk_grace_sec(p)
    recover_sec = float(p.get("berserk_sl_recover_sec") or 75)
    catastrophic_pct = float(p.get("berserk_sl_catastrophic_stake_pct") or 0.08)
    catastrophic_usd = stake * catastrophic_pct
    soft_floor = _soft_sl_floor_usd(stake, sl_thr, p)
    min_sl_age = _effective_min_sl_age(age, max_unreal_seen, p)

    def _catastrophic() -> bool:
        return unreal <= -catastrophic_usd

    # Grace: SL yok
    if age < grace:
        return False

    # Recovery: yalnızca felaket
    if age < recover_sec:
        return _catastrophic()

    # Min yaş dolmadan yalnızca felaket SL (hard bypass kaldırıldı — #196 SUPER 75sn)
    if age < min_sl_age:
        return _catastrophic()

    # Küçük zarar — SL yok (STALE-DIP / TP-RECOVER beklesin)
    if unreal > -soft_floor:
        return False

    peak_min = float(p.get("berserk_sl_peak_hold_min_usd") or 0.06)
    peak_hard = float(p.get("berserk_sl_peak_hard_mult") or 2.8)
    peak_hold_sec = float(p.get("berserk_sl_peak_hold_sec") or 45)
    if float(max_unreal_seen) >= peak_min and age < peak_hold_sec:
        if unreal > -sl_thr * peak_hard:
            return False

    hard_mult = float(p.get("berserk_sl_hard_mult") or 8.0)
    if unreal <= -sl_thr * hard_mult:
        return True

    return unreal <= -soft_floor


def evaluate_berserk_exit_addons(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    sl_target_usd: float,
    stake_usd: float,
    min_unreal_seen: float,
    max_unreal_seen: float,
    leverage: int = 5,
    mode_id: str = "berserk",
    profile: dict[str, Any] | None = None,
    pos: dict[str, Any] | None = None,
    client: Any | None = None,
) -> str | None:
    """Spike/TP sonrası, SL öncesi Berserk ek çıkışları."""
    p = profile or _profile(mode_id)
    peak = berserk_peak_spike_before_sl(
        opened_at=opened_at,
        unrealized_usd=unrealized_usd,
        tp_target_usd=tp_target_usd,
        sl_target_usd=sl_target_usd,
        stake_usd=stake_usd,
        max_unreal_seen=max_unreal_seen,
        leverage=leverage,
        profile=p,
        mode_id=mode_id,
    )
    if peak:
        return peak
    recover = berserk_sl_recovery_reason(
        opened_at=opened_at,
        unrealized_usd=unrealized_usd,
        sl_target_usd=sl_target_usd,
        stake_usd=stake_usd,
        min_unreal_seen=min_unreal_seen,
        leverage=leverage,
        profile=p,
    )
    if recover:
        return recover
    stale_dip = berserk_stale_dip_exit(
        opened_at=opened_at,
        unrealized_usd=unrealized_usd,
        sl_target_usd=sl_target_usd,
        stake_usd=stake_usd,
        min_unreal_seen=min_unreal_seen,
        leverage=leverage,
        mode_id=mode_id,
        profile=p,
    )
    if stale_dip:
        return stale_dip
    if pos is not None:
        try:
            from elite_trader.position_rescue import tp_timer_exit_reason

            timer = tp_timer_exit_reason(pos, mode_id=mode_id, client=client)
            if timer:
                return timer
        except Exception:
            pass
    return None
