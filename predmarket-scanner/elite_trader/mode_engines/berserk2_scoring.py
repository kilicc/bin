"""BERSERK2 — hızlı TP scalp; top10 + BTC; berserk'ten gevşek ölçekler."""
from __future__ import annotations

import os

from typing import Any

from elite_trader.berserk2_btc_context import get_btc_context
from elite_trader.berserk2_flash_reversal import flash_reversal_entry_meta
from elite_trader.berserk2_movers import is_top_mover
from elite_trader.fee_economics import round_trip_fee_usd
from elite_trader.mode_engines.berserk_scoring import (
    evaluate_berserk_entry,
    resolve_berserk_dynamic_exit,
    strength_stake_mult,
)


def berserk2_entry_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """BERSERK2'ye özel giriş ölçekleri — berserk profilini ezmez."""
    p = dict(profile)
    p["berserk_min_score"] = float(profile.get("berserk2_min_score") or profile.get("berserk_min_score") or 26)
    p["berserk_min_move_pct"] = float(
        profile.get("berserk2_min_move_pct") or profile.get("berserk_min_move_pct") or 0.03
    )
    p["berserk_normal_score"] = float(profile.get("berserk2_normal_score") or 48)
    p["berserk_aggressive_score"] = float(profile.get("berserk2_aggressive_score") or 62)
    p["max_spread_pct"] = float(profile.get("berserk2_max_spread_pct") or profile.get("max_spread_pct") or 0.11)
    p["soft_spread_start_pct"] = float(
        profile.get("berserk2_soft_spread_start_pct") or profile.get("soft_spread_start_pct") or 0.055
    )
    p["tp_stake_pct"] = float(profile.get("berserk2_tp_stake_pct") or profile.get("tp_stake_pct") or 0.0036)
    p["sl_stake_pct"] = float(profile.get("berserk2_sl_stake_pct") or profile.get("sl_stake_pct") or 0.0020)
    p["tp_trigger_frac"] = float(profile.get("berserk2_tp_trigger_frac") or profile.get("tp_trigger_frac") or 0.99)
    p["spike_min_age_sec"] = float(profile.get("berserk2_spike_min_age_sec") or profile.get("spike_min_age_sec") or 2)
    p["berserk_tp_grace_sec"] = float(
        profile.get("berserk2_tp_grace_sec") or profile.get("berserk_tp_grace_sec") or 16
    )
    p["weak_stake_multiplier"] = float(profile.get("berserk2_weak_stake_mult") or 0.55)
    skip_env = os.getenv("BERSERK2_SKIP_WEAK_VOLUME", "").strip().lower()
    if skip_env in ("0", "false", "no"):
        p["berserk2_skip_weak_volume"] = False
    elif skip_env in ("1", "true", "yes"):
        p["berserk2_skip_weak_volume"] = True
    else:
        p["berserk2_skip_weak_volume"] = bool(profile.get("berserk2_skip_weak_volume", True))
    return p


def _tp_reachable(
    stake_usd: float,
    profile: dict[str, Any],
    *,
    momentum: float,
    score: float,
    mode_id: str = "berserk2",
) -> tuple[bool, float]:
    """Ücret + vergi sonrası net kâr mümkün mü."""
    from elite_trader.fee_economics import (
        exit_min_net_usd,
        min_gross_for_final_net,
        round_trip_fee_usd,
    )

    stake = max(float(stake_usd), 1.0)
    lev = 3
    min_final = exit_min_net_usd(mode_id)
    min_gross = min_gross_for_final_net(stake, lev, min_final_usd=min_final, mode_id=mode_id)
    tp_pct = float(profile.get("tp_stake_pct") or 0.0036) * float(
        profile.get("tp_trigger_frac") or 0.99
    )
    tp_gross_plan = stake * tp_pct
    fee = round_trip_fee_usd(stake, lev) * float(profile.get("berserk2_tp_fee_mult") or 1.12)
    est_net = tp_gross_plan - fee
    if tp_gross_plan >= min_gross and est_net >= min_final * 0.85:
        return True, est_net
    if momentum >= 0.06 and score >= float(profile.get("berserk2_min_score") or 26) - 4:
        if tp_gross_plan >= min_gross * 0.92:
            return True, est_net
    return tp_gross_plan >= min_gross, est_net


def _btc_side_ok(
    side: str,
    regime: str,
    profile: dict[str, Any],
) -> tuple[bool, str, float]:
    s = str(side or "LONG").upper()
    r = str(regime or "unknown").lower()
    soft = bool(profile.get("berserk2_btc_soft_veto", True))
    if r in ("unknown", "mixed"):
        return True, "", 1.0
    if r == "chop":
        return True, "", float(profile.get("berserk2_chop_stake_mult") or 0.92)
    if s == "LONG" and r == "trend_down":
        if soft:
            return True, "berserk2_btc_long_soft", float(profile.get("berserk2_counter_trend_mult") or 0.42)
        return False, "berserk2_btc_long_vs_down", 0.0
    if s == "SHORT" and r == "trend_up":
        if soft:
            return True, "berserk2_btc_short_soft", float(profile.get("berserk2_counter_trend_mult") or 0.42)
        return False, "berserk2_btc_short_vs_up", 0.0
    if s == "LONG" and r == "trend_up":
        return True, "", float(profile.get("berserk2_with_trend_mult") or 1.12)
    if s == "SHORT" and r == "trend_down":
        return True, "", float(profile.get("berserk2_with_trend_mult") or 1.12)
    return True, "", 1.0


def _berserk2_strict_entry() -> bool:
    import os

    return os.getenv("BERSERK2_STRICT_ENTRY", "1").strip().lower() in ("1", "true", "yes")


def evaluate_berserk2_entry(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    *,
    edge: float,
    formula: float,
) -> tuple[bool, str, dict[str, Any]]:
    sym = str(signal.get("symbol") or "")
    if sym:
        try:
            from elite_trader.mega_coin_watch import get_symbol_penalty

            pen = get_symbol_penalty(sym)
            if pen.get("block_entry"):
                return False, str(pen.get("reject_tag") or "coin_bottom_veto"), {
                    "coin_watch": pen,
                }
        except Exception:
            pass
    require_top = os.getenv("BERSERK2_REQUIRE_TOP_MOVER", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if require_top and not is_top_mover(sym):
        return False, "berserk2_not_top_mover", {"berserk2_top10_only": True}

    prof = berserk2_entry_profile(profile)
    rank = int(signal.get("berserk2_mover_rank") if signal.get("berserk2_mover_rank") is not None else 19)
    strict = _berserk2_strict_entry()
    if not strict:
        if rank < 5:
            prof["berserk_min_score"] = float(prof.get("berserk_min_score") or 18) - 3
            prof["berserk_min_move_pct"] = float(prof.get("berserk_min_move_pct") or 0.008) * 0.85
        elif rank < 12:
            prof["berserk_min_score"] = float(prof.get("berserk_min_score") or 18) - 1
    elif rank >= 10:
        prof["berserk_min_score"] = float(prof.get("berserk_min_score") or 28) + 2
        prof["berserk_min_move_pct"] = float(prof.get("berserk_min_move_pct") or 0.01) * 1.08
    btc = dict(ctx.get("btc_context") or get_btc_context())
    ctx = {
        **ctx,
        "profile": prof,
        "btc_regime": btc.get("btc_regime"),
        "btc_24h_change": btc.get("btc_24h_change"),
    }
    side = str(signal.get("type") or "LONG")
    if signal.get("flash_reversal") or str(signal.get("signal_source") or "") == "FlashReversal-LONG":
        stake_base = float(prof.get("min_stake_usd") or 120)
        lev = max(int(signal.get("leverage") or 4), 1)
        meta = flash_reversal_entry_meta(signal, prof, stake_usd=stake_base, leverage=lev)
        meta["btc_regime"] = btc.get("btc_regime")
        meta["berserk2_top10"] = True
        meta["berserk2_flash_reversal"] = True
        signal["berserk_meta"] = meta
        return True, "", meta

    ok_btc, btc_tag, btc_stake = _btc_side_ok(side, str(btc.get("btc_regime") or ""), prof)
    if not ok_btc:
        return False, btc_tag, {"btc_regime": btc.get("btc_regime")}

    chop_boost = int(prof.get("berserk2_chop_score_boost") or 0)
    if str(btc.get("btc_regime") or "") == "chop" and chop_boost:
        prof = {**prof, "berserk_min_score": float(prof["berserk_min_score"]) + chop_boost}

    ok, reason, meta = evaluate_berserk_entry(signal, ctx, prof, edge=edge, formula=formula)

    ch = abs(float(signal.get("change") or 0))
    min_move = float(prof.get("berserk_min_move_pct") or 0.003)
    if not strict and not ok and reason == "berserk_min_move" and ch >= min_move * 0.95:
        prof_lo = {**prof, "berserk_min_move_pct": min(min_move, ch * 0.98)}
        ok, reason, meta = evaluate_berserk_entry(signal, ctx, prof_lo, edge=edge, formula=formula)
        if ok:
            meta["berserk2_min_move_align"] = True

    if not strict and not ok and reason in ("berserk_weak_no_volume", "berserk_weak_pressure"):
        allow_weak = prof.get("berserk2_skip_weak_volume")
        weak_env = os.getenv("BERSERK2_ALLOW_WEAK_VOLUME", "").strip().lower()
        if weak_env in ("1", "true", "yes"):
            allow_weak = True
        if allow_weak and ch >= min_move:
            ok = True
            reason = ""
            meta["berserk2_weak_override"] = True

    if not strict and not ok and reason == "berserk_expected_net_negative":
        ch = abs(float(signal.get("change") or 0))
        score = float(meta.get("berserk_score") or 0)
        mom = ch * 0.45
        stake = float(prof.get("min_stake_usd") or 120) * float(meta.get("combined_stake_mult") or 0.7)
        reachable, est = _tp_reachable(stake, prof, momentum=mom, score=score)
        if reachable:
            ok = True
            reason = ""
            meta["berserk2_tp_reach_override"] = True
            meta["expected_net_pnl_usd"] = round(est, 4)

    if not strict and not ok and reason == "berserk_score_low":
        ch = abs(float(signal.get("change") or 0))
        min_move = float(prof.get("berserk_min_move_pct") or 0.03)
        floor = float(prof.get("berserk2_pulse_min_score") or 14)
        if ch >= min_move * 1.25 and float(meta.get("berserk_score") or 0) >= floor:
            ok = True
            reason = ""
            meta["berserk2_pulse_entry"] = True

    if not ok:
        meta["btc_regime"] = btc.get("btc_regime")
        return False, reason, meta

    meta["btc_regime"] = btc.get("btc_regime")
    meta["btc_24h_change"] = btc.get("btc_24h_change")
    meta["berserk2_top10"] = True
    if btc_tag:
        meta["btc_entry_tag"] = btc_tag
    if btc_stake != 1.0:
        meta["btc_stake_mult"] = btc_stake
        meta["combined_stake_mult"] = round(
            float(meta.get("combined_stake_mult") or 1.0) * btc_stake, 4
        )

    score = float(meta.get("berserk_score") or 0)
    ch = abs(float(signal.get("change") or 0))
    momentum = float(ctx.get("micro_accel") or ch * 0.5)
    spread = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    de = resolve_berserk_dynamic_exit(score, momentum, spread, prof)
    tp_pct = float(de.get("tp_stake_pct") or prof.get("tp_stake_pct") or 0.0036)
    if momentum > 0.08 or score >= float(prof.get("berserk_aggressive_score") or 62):
        de["tp_stake_pct"] = round(tp_pct * 1.06, 6)
    meta["berserk_dynamic_exit"] = de
    try:
        from elite_trader.mega_coin_watch import get_symbol_boost, get_symbol_penalty

        boost = get_symbol_boost(sym)
        if boost.get("starred"):
            meta["combined_stake_mult"] = round(
                float(meta.get("combined_stake_mult") or 1.0)
                * float(boost.get("stake_mult") or 1.0),
                4,
            )
            meta["coin_watch_boost"] = boost
        pen = get_symbol_penalty(sym)
        if pen:
            meta["coin_watch_penalty"] = pen
    except Exception:
        pass
    signal["berserk_meta"] = meta
    return True, "", meta
