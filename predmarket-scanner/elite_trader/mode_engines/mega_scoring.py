"""MEGA — volatilite scalp; SL yok; $500–$1500 stake; 5x–10x kaldıraç."""
from __future__ import annotations

import os
from typing import Any

from elite_trader.mode_engines.hunter_breakout_engine import calculate_breakout_score
from elite_trader.mode_engines.hunter_scoring import (
    compute_liquidation_cascade_score,
    spread_assessment,
)
from elite_trader.mode_engines.hunter_spike_engine import evaluate_spike_opportunity

STRENGTH_STAKE_MULT = {"Weak": 0.55, "Medium": 0.78, "Strong": 1.0}


def _f(profile: dict[str, Any], key: str, default: float) -> float:
    v = profile.get(key)
    return float(v) if v is not None else default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _relative_min_move(
    symbol: str,
    change_pct: float,
    min_move: float,
    *,
    vol_tier: str,
    vol_rank: int | None,
    market_regime: str,
) -> float:
    """Sessiz piyasa — hot/warm sıralamada göreli hareket eşiği (mutlak % değil)."""
    if not _env_bool("MEGA_RELATIVE_ENTRY", True):
        return min_move
    try:
        from elite_trader.mega_volatility import row_for

        row = row_for(symbol) or {}
    except Exception:
        row = {}
    rel_ch = abs(float(row.get("change_pct") or change_pct))
    rank = int(vol_rank if vol_rank is not None else row.get("rank") or 99)
    floor = _env_float("MEGA_VOL_REL_MIN_MOVE_PCT", 0.006)
    frac = _env_float("MEGA_VOL_REL_FRAC", 0.65)
    hot_n = _env_int("MEGA_VOL_HOT_N", 10)
    regime = str(market_regime or "")
    seekish = "seek" in regime or "transition" in regime

    if vol_tier == "hot" and rank <= hot_n:
        rel_min = max(floor, rel_ch * frac)
        if seekish:
            rel_min = max(floor * 0.75, rel_min * 0.88)
        if rank <= 3:
            rel_min = min(rel_min, max(floor * 0.85, rel_ch * 0.55))
        return min(min_move, rel_min)
    if vol_tier == "warm":
        rel_min = max(floor * 1.15, rel_ch * min(0.85, frac + 0.08))
        return min(min_move, rel_min)
    return min_move


def _align_min_edge_to_move(min_edge: float, change_pct: float) -> float:
    """Vol-scan düşük momentum — edge eşiğini gözlenen hareketle hizala."""
    move_frac = abs(float(change_pct)) / 100.0
    mult = _env_float("MEGA_MOVE_EDGE_MULT", 22.0)
    floor = _env_float("MEGA_MOVE_EDGE_FLOOR", 0.0002)
    move_edge = max(floor, move_frac * mult)
    return min(min_edge, move_edge)


def mega_leverage(
    signal: dict[str, Any],
    strength: str,
    profile: dict[str, Any] | None = None,
) -> int:
    """Sistem kaldıraç — skor/güce göre; taban MEGA_LEVERAGE_MIN (varsayılan 5x)."""
    prof = profile or {}
    score = float(
        (signal.get("mega_meta") or {}).get("mega_score")
        or signal.get("mega_score")
        or 0
    )
    lev_min = _env_int("MEGA_LEVERAGE_MIN", 5)
    lev_weak = max(
        lev_min,
        _env_int("MEGA_LEVERAGE_WEAK", int(prof.get("mega_leverage_weak") or lev_min)),
    )
    lev_med = max(
        lev_min,
        _env_int("MEGA_LEVERAGE_MEDIUM", int(prof.get("mega_leverage_medium") or lev_min + 2)),
    )
    lev_strong = max(
        lev_min,
        _env_int("MEGA_LEVERAGE_STRONG", int(prof.get("mega_leverage_strong") or 10)),
    )

    s = str(strength or "Medium")
    if s == "Strong" or score >= float(prof.get("mega_strong_score") or 72):
        return max(lev_min, min(20, lev_strong))
    if s == "Medium" or score >= float(prof.get("mega_medium_score") or 58):
        return max(lev_min, min(10, lev_med))
    if score >= float(prof.get("mega_weak_score") or 52):
        return max(lev_min, min(10, lev_med))
    return max(lev_min, min(10, lev_weak))


def evaluate_mega_entry(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    *,
    edge: float,
    formula: float,
) -> tuple[bool, str, dict[str, Any]]:
    try:
        from elite_trader.mega_boot_observe import boot_observe_active

        if boot_observe_active():
            return False, "mega_boot_observe", {"boot_observe": True}
    except Exception:
        pass
    side = str(signal.get("type") or "LONG")
    try:
        from elite_trader.mega_direction_guard import mega_entry_allowed

        ok_dir, dir_tag = mega_entry_allowed(signal)
        if not ok_dir:
            return False, dir_tag or "mega_direction_block", {"market_regime": "blocked"}
    except Exception:
        pass
    try:
        from elite_trader.mega_system_score import mega_system_entry_allowed

        ok_sys, sys_tag, sys_score = mega_system_entry_allowed(signal)
        if not ok_sys:
            return (
                False,
                sys_tag or "system_score_block",
                {"system_score": sys_score, "market_regime": "blocked"},
            )
    except Exception:
        pass
    strength = str(signal.get("strength") or "Medium")
    ch = abs(float(signal.get("change") or 0))
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    min_move = _f(profile, "mega_min_move_pct", 0.08)
    min_score = _f(profile, "mega_min_score", 48)
    min_edge = _f(profile, "min_edge", 0.04)
    require_top_mover = bool(profile.get("mega_require_top_mover", True))
    sym = str(signal.get("symbol") or "")
    coin_pen: dict[str, Any] = {}
    coin_boost: dict[str, Any] = {}
    star_hints: dict[str, Any] = {}
    if sym:
        try:
            from elite_trader.mega_coin_watch import (
                apply_star_entry_hints,
                get_symbol_penalty,
            )

            coin_pen = get_symbol_penalty(sym)
            if coin_pen.get("block_entry"):
                return (
                    False,
                    str(coin_pen.get("reject_tag") or "coin_bottom_veto"),
                    {"coin_watch": coin_pen},
                )
            star_hints = apply_star_entry_hints(sym, side, signal)
            if star_hints.get("block_entry"):
                return (
                    False,
                    str(star_hints.get("reject_tag") or "star_entry_block"),
                    {"coin_watch": star_hints},
                )
            coin_boost = {
                "starred": star_hints.get("starred"),
                "stake_mult": star_hints.get("stake_mult"),
                "min_score_delta": star_hints.get("min_score_delta"),
                "behavior_playbook": star_hints.get("playbook"),
                "alignment": star_hints.get("alignment"),
            }
        except Exception:
            coin_boost = {}
            pass
    on_top_mover = False
    try:
        from elite_trader.berserk2_movers import is_top_mover

        on_top_mover = bool(sym and is_top_mover(sym))
    except Exception:
        on_top_mover = False
    if on_top_mover:
        min_move = min(
            min_move,
            _f(profile, "mega_top_mover_min_move_pct", 0.05),
        )
        min_score = max(42.0, min_score - 4.0)

    vol_tier = "off"
    vol_rank: int | None = None
    market_regime = "off"
    try:
        from elite_trader.mega_volatility import enabled as vol_scan, thresholds as vol_thresholds

        if vol_scan():
            vt = vol_thresholds(profile, sym)
            min_move = min(min_move, float(vt["min_move"]))
            min_score = min(min_score, float(vt["min_score"]))
            min_edge = float(vt["min_edge"])
            require_top_mover = bool(vt["require_top_mover"])
            vol_tier = str(vt.get("tier") or "cold")
            market_regime = str(vt.get("regime") or "normal")
            rk = vt.get("rank")
            vol_rank = int(rk) if rk is not None else None
    except Exception:
        pass

    try:
        from elite_trader.mega_market_regime import mega_sim_paper_only

        if mega_sim_paper_only():
            min_edge = min(min_edge, _env_float("MEGA_SIM_MIN_EDGE", 0.003))
            min_score = max(14.0, min_score - 8.0)
            min_move = min(min_move, _env_float("MEGA_SIM_MIN_MOVE_PCT", 0.0035))
    except Exception:
        pass

    if side == "SHORT":
        try:
            from elite_trader.mega_direction_guard import bear_short_entry_boost

            bsb = bear_short_entry_boost()
            min_score = max(12.0, min_score - float(bsb["score_delta"]))
            min_edge = min_edge * float(bsb["edge_mult"])
            min_move = min_move * float(bsb["move_mult"])
            meta_bear_short = True
        except Exception:
            meta_bear_short = False
    else:
        meta_bear_short = False

    meta: dict[str, Any] = {
        "mega_score": 0.0,
        "strength_stake_mult": STRENGTH_STAKE_MULT.get(strength, 0.78),
        "spread_stake_mult": 1.0,
        "combined_stake_mult": STRENGTH_STAKE_MULT.get(strength, 0.78),
        "breakout_score": 0.0,
        "liquidation_cascade_score": 0.0,
        "leverage": mega_leverage(signal, strength, profile),
        "vol_tier": vol_tier,
        "vol_rank": vol_rank,
        "market_regime": market_regime,
        "bear_short_boost": meta_bear_short,
    }

    if meta_bear_short:
        try:
            from elite_trader.mega_direction_guard import bear_short_entry_boost

            meta["combined_stake_mult"] = float(meta["combined_stake_mult"]) * float(
                bear_short_entry_boost()["stake_mult"]
            )
        except Exception:
            pass

    px = float(signal.get("price") or ctx.get("price") or 0)
    try:
        from elite_trader.mega_volatility import micro_price_scan_eligible

        if px > 0 and not micro_price_scan_eligible(
            px,
            change_pct=float(signal.get("change") or 0),
            vol_score=float(ctx.get("vol_score") or signal.get("vol_score") or 0),
            vol_tier=vol_tier,
            strength=strength,
        ):
            return False, "mega_micro_price", meta
    except Exception:
        pass

    try:
        abs_floor = float(os.getenv("MEGA_VOL_ABS_FLOOR_PCT", "0.018"))
    except ValueError:
        abs_floor = 0.018
    min_move = _relative_min_move(
        sym,
        ch,
        min_move,
        vol_tier=vol_tier,
        vol_rank=vol_rank,
        market_regime=market_regime,
    )
    meta["min_move_pct"] = round(min_move, 5)

    if vol_tier == "cold" and ch < abs_floor:
        return False, "mega_not_volatile", meta

    if ch < min_move:
        return False, "mega_move_too_small", meta

    spread_pct = float(ctx.get("spread_pct") or signal.get("spread_pct") or 0)
    spread_info = spread_assessment(spread_pct, profile)
    meta["spread_risk_level"] = spread_info.get("spread_risk_level")
    meta["spread_stake_mult"] = float(spread_info.get("stake_mult") or 1.0)
    if spread_info.get("veto"):
        return False, "mega_spread_veto", meta

    br = calculate_breakout_score(signal, ctx, profile)
    br_score = float(br.get("breakout_score") or 0)
    br_breakdown = br.get("breakout_score_breakdown") or {}
    liq_score, liq_parts = compute_liquidation_cascade_score(signal, ctx)
    spike = evaluate_spike_opportunity(signal, ctx, profile, liq_score=liq_score)

    meta["breakout_score"] = br_score
    meta["breakout_score_breakdown"] = br_breakdown
    meta["liquidation_cascade_score"] = liq_score
    meta["liquidation_parts"] = liq_parts
    meta["spike_meta"] = spike

    mega_score = (
        br_score * 0.42
        + liq_score * 0.28
        + min(100.0, ch * 120.0) * 0.18
        + min(100.0, max(0.0, (vr - 1.0) * 40.0)) * 0.12
    )
    if spike.get("continuation"):
        mega_score += 8.0
    if spike.get("fake_spike"):
        mega_score -= 22.0
    if vol_tier == "hot":
        mega_score += 14.0
        if vol_rank is not None and vol_rank <= 10:
            mega_score += max(0.0, (11 - int(vol_rank)) * 2.2)
    elif vol_tier == "warm":
        mega_score += 8.0
        if vol_rank is not None and vol_rank <= 20:
            mega_score += max(0.0, (21 - int(vol_rank)) * 0.6)
    min_formula = _f(profile, "min_formula_score", 0.48)
    if "seek" in str(market_regime) or "transition" in str(market_regime):
        mega_score += min(20.0, ch * 90.0)
        min_formula = min(min_formula, 0.42)
    min_edge = _align_min_edge_to_move(min_edge, ch)
    meta["min_edge"] = round(min_edge, 5)
    meta["mega_score"] = round(mega_score, 2)
    signal["mega_score"] = meta["mega_score"]

    meta["combined_stake_mult"] = (
        float(meta["strength_stake_mult"])
        * float(meta["spread_stake_mult"])
        * (1.08 if mega_score >= 72 else 1.0)
    )
    if coin_boost.get("starred"):
        meta["combined_stake_mult"] = float(meta["combined_stake_mult"]) * float(
            coin_boost.get("stake_mult") or 1.0
        )
        min_score = max(12.0, min_score + float(coin_boost.get("min_score_delta") or 0))
        meta["coin_star_playbook"] = coin_boost.get("behavior_playbook") or {}
        meta["coin_star_alignment"] = coin_boost.get("alignment") or ""
        meta["coin_open_behavior"] = star_hints.get("open_behavior") or {}
        signal["mega_coin_star"] = True
    if coin_pen.get("min_score_delta"):
        min_score = min_score + float(coin_pen.get("min_score_delta") or 0)
    meta["coin_watch_boost"] = coin_boost
    meta["coin_watch_penalty"] = coin_pen

    if edge < min_edge:
        return False, "mega_edge_low", meta
    if formula < min_formula:
        return False, "mega_formula_low", meta

    if mega_score < min_score:
        return False, "mega_score_low", meta

    min_spike_ch = _f(profile, "mega_min_spike_change_pct", 0.10)
    min_vol = _f(profile, "mega_min_vol_ratio", 1.08)
    skip_explosive = vol_tier in ("hot", "warm") and (
        ch >= max(0.010, min_move * 0.85)
        or "seek" in str(market_regime)
        or "transition" in str(market_regime)
        or (_env_bool("MEGA_RELATIVE_ENTRY", True) and vol_tier == "hot")
    )
    if not skip_explosive and ch < min_spike_ch and vr < min_vol and br_score < 55:
        return False, "mega_no_explosive_setup", meta

    if require_top_mover and not on_top_mover:
        if ch < min_move * 1.35 and br_score < 58:
            return False, "mega_not_top_mover", meta

    weak_pad = 4 if vol_tier == "hot" else 6
    if strength == "Weak" and mega_score < min_score + weak_pad:
        return False, "mega_weak_low_score", meta

    meta["leverage"] = mega_leverage(signal, strength, profile)
    meta["elite_candidate"] = is_mega_elite_signal(signal, meta=meta)
    return True, "", meta


def is_mega_elite_signal(
    signal: dict[str, Any],
    *,
    meta: dict[str, Any] | None = None,
) -> bool:
    """Çok güçlü sinyal — 4 slot doluyken ekstra $1500 / 10x açılış."""
    if not _env_bool("MEGA_ELITE_OVERRIDE", True):
        return False
    meta = meta or signal.get("mega_meta") or {}
    score = float(meta.get("mega_score") or signal.get("mega_score") or 0)
    if score < _env_float("MEGA_ELITE_MIN_SCORE", 72.0):
        return False
    vol_tier = str(meta.get("vol_tier") or signal.get("mega_vol_tier") or "")
    if vol_tier not in ("hot", "warm"):
        return False
    ch = abs(float(signal.get("change") or 0))
    if ch < _env_float("MEGA_ELITE_MIN_MOVE_PCT", 0.022):
        return False
    spike = meta.get("spike_meta") or {}
    if spike.get("fake_spike"):
        return False
    br = float(meta.get("breakout_score") or 0)
    if br < _env_float("MEGA_ELITE_MIN_BREAKOUT", 52.0):
        return False
    rank = meta.get("vol_rank")
    max_rank = _env_int("MEGA_ELITE_MAX_VOL_RANK", 6)
    strength = str(signal.get("strength") or "")
    if rank is not None and int(rank) > max_rank and strength != "Strong":
        return False
    if strength == "Weak" and score < _env_float("MEGA_ELITE_MIN_SCORE", 72.0) + 6:
        return False
    return True
