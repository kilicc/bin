"""Paralel evrenler — canlıdan bağımsız paper kitaplar (aynı piyasa taraması)."""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from elite_trader.capital_allocator import compute_stake
from elite_trader.mode_registry import is_berserk_family
from elite_trader.panel_strategy import (
    evaluate_position_exit,
    is_live_binance_motor,
    DEFAULT_ACTIVE_FUTURES_MODE,
    mode_catalog,
    mode_order,
    parallel_mode_ids,
    position_age_seconds,
    stake_targets,
)

_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "parallel_universes.json"

_STRENGTH_RANK = {"Weak": 1, "Medium": 2, "Strong": 3}

# Bellek içi durum önbelleği — her sinyal için disk I/O'yu önler
_state_cache: dict[str, Any] | None = None
_state_dirty: bool = False
_state_last_save: float = 0.0
_state_lock = threading.RLock()
_STATE_FLUSH_INTERVAL: float = 5.0  # 5 saniyede bir diske yaz

# binance_elite_pro tarafından bağlanır (canlı kodu değişmez)
_edge_fn: Callable[[float], float] | None = None
_formula_fn: Callable[[float], float] | None = None
_kelly_fn: Callable[[float, str], float] | None = None
_risk_fn: Callable[..., tuple[bool, str, str]] | None = None
_min_edge: float = 0.048
_min_formula: float = 0.52
_session_start: float = 5000.0
_stake_bounds_fn: Callable[[], tuple[float, float]] | None = None
_max_open_fn: Callable[[], int] | None = None
_wr_fn: Callable[[], float | None] | None = None
_leverage_fn: Callable[[str, int], int] | None = None
_tradable: set[str] | None = None
_scan_universe: set[str] | None = None
_paper_reject_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


def _record_paper_reject(mode_id: str, reason: str) -> None:
    key = str(reason or "unknown")[:48]
    _paper_reject_stats[str(mode_id)][key] += 1


def _reject_entry(
    mode_id: str,
    signal: dict[str, Any],
    reason: str,
    execution_path: str,
) -> None:
    """Unified reject: stats + ring buffer + decision log."""
    _record_paper_reject(mode_id, reason)
    try:
        from elite_trader.mode_reject_buffer import append_reject, build_reject_row

        append_reject(mode_id, build_reject_row(mode_id, signal, reason, execution_path=execution_path))
    except Exception:
        pass
    _log_decision(mode_id, signal, False, reason, execution_path)
    if mode_id == "evrim" and execution_path == "live":
        try:
            from elite_trader.evrim_live_decisions import record_decision

            v2 = signal.get("evrim_v2") or {}
            record_decision(
                symbol=str(signal.get("symbol") or ""),
                side=str(signal.get("type") or ""),
                allowed=False,
                reason=reason,
                final_score=v2.get("final_score") or signal.get("final_score"),
                expected_net_pnl=v2.get("expected_net_pnl") or signal.get("expected_net_pnl"),
                order_route="BINANCE_FUTURES_LIVE_ENGINE",
            )
        except Exception:
            pass


def _try_minimum_data_exploration(
    mode_id: str,
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    normal_reason: str,
) -> tuple[str, str, dict[str, Any]]:
    mid = str(mode_id or "")
    if mid == "hunter":
        from elite_trader.hunter_paper_exploration import try_hunter_exploration

        return try_hunter_exploration(signal, ctx, profile, normal_reason)
    if mid == "chop_master":
        from elite_trader.chop_paper_exploration import try_chop_exploration

        return try_chop_exploration(signal, ctx, profile, normal_reason)
    if mid == "sentinel":
        from elite_trader.sentinel_paper_exploration import try_sentinel_exploration

        return try_sentinel_exploration(signal, ctx, profile, normal_reason)
    return "reject", normal_reason, {}


def paper_reject_stats() -> dict[str, dict[str, int]]:
    return {mid: dict(stats) for mid, stats in _paper_reject_stats.items()}


def paper_reject_summary() -> dict[str, Any]:
    try:
        from elite_trader.evrim_motor_diag import summarize_reject_stats

        summarize = summarize_reject_stats
    except Exception:

        def summarize(raw: dict[str, int] | None) -> dict[str, Any]:
            top = sorted((raw or {}).items(), key=lambda x: -x[1])[:6]
            return {
                "total": sum((raw or {}).values()),
                "top_txt": ", ".join(f"{k}:{v}" for k, v in top[:5]) if top else "",
            }

    out: dict[str, Any] = {}
    for mid in all_mode_ids():
        raw = dict(_paper_reject_stats.get(mid) or {})
        if not raw:
            continue
        out[mid] = summarize(raw)
    return out


def reset_paper_reject_stats() -> None:
    _paper_reject_stats.clear()


def configure(
    *,
    edge_fn: Callable[[float], float],
    formula_fn: Callable[[float], float],
    kelly_fn: Callable[[float, str], float],
    risk_fn: Callable[..., tuple[bool, str, str]] | None = None,
    min_edge: float,
    min_formula: float,
    session_start: float,
    stake_bounds_fn: Callable[[], tuple[float, float]],
    max_open_fn: Callable[[], int],
    wr_fn: Callable[[], float | None],
    leverage_fn: Callable[[str, int], int],
    tradable_symbols: set[str] | None = None,
    scan_universe: set[str] | None = None,
) -> None:
    global _edge_fn, _formula_fn, _kelly_fn, _risk_fn
    global _min_edge, _min_formula, _session_start
    global _stake_bounds_fn, _max_open_fn, _wr_fn, _leverage_fn, _tradable, _scan_universe
    _edge_fn = edge_fn
    _formula_fn = formula_fn
    _kelly_fn = kelly_fn
    _risk_fn = risk_fn
    _min_edge = min_edge
    _min_formula = min_formula
    _session_start = session_start
    _stake_bounds_fn = stake_bounds_fn
    _max_open_fn = max_open_fn
    _wr_fn = wr_fn
    _leverage_fn = leverage_fn
    _tradable = tradable_symbols
    _scan_universe = scan_universe


def all_mode_ids() -> tuple[str, ...]:
    return tuple(mode_order())


def paper_mode_ids() -> tuple[str, ...]:
    """Paper — ELITE_ENABLED_MODES ∩ (canlı motor hariç)."""
    from elite_trader.panel_strategy import live_only_execution

    if live_only_execution():
        return ()
    from elite_trader.mode_registry import enabled_mode_ids
    from elite_trader.panel_strategy import is_live_binance_motor

    return tuple(
        m for m in enabled_mode_ids() if not is_live_binance_motor(m)
    )


def _empty_book(session_start: float | None = None) -> dict[str, Any]:
    ss = float(session_start or _session_start)
    return {
        "open": [],
        "closed": [],
        "next_id": 1,
        "session_start": ss,
    }


def _default_state() -> dict[str, Any]:
    cap = float(_session_start)
    by_mode = {mid: cap for mid in all_mode_ids()}
    u = {mid: _empty_book(cap) for mid in all_mode_ids()}
    return {
        "version": 2,
        "starting_capital": cap,
        "starting_capital_by_mode": by_mode,
        "universes": u,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _mode_session_start(st: dict[str, Any], mode_id: str) -> float:
    by = st.get("starting_capital_by_mode") or {}
    if mode_id in by and float(by[mode_id]) > 0:
        return float(by[mode_id])
    book = (st.get("universes") or {}).get(mode_id) or {}
    if book.get("session_start"):
        return float(book["session_start"])
    return float(st.get("starting_capital") or _session_start)


def _migrate_state(st: dict[str, Any]) -> bool:
    """sentinel kitabı, mod başına session_start; eski tek starting_capital."""
    dirty = False
    u = st.setdefault("universes", {})
    cap = float(st.get("starting_capital") or _session_start)
    by = dict(st.get("starting_capital_by_mode") or {})
    for mid in all_mode_ids():
        if mid not in u:
            u[mid] = _empty_book(by.get(mid) or cap)
            dirty = True
        else:
            u[mid].setdefault("open", [])
            u[mid].setdefault("closed", [])
            u[mid].setdefault("next_id", 1)
            if not u[mid].get("session_start"):
                u[mid]["session_start"] = float(by.get(mid) or cap)
                dirty = True
        if mid not in by:
            by[mid] = float(u[mid].get("session_start") or cap)
            dirty = True
    st["starting_capital_by_mode"] = by
    if st.get("version", 1) < 2:
        st["version"] = 2
        dirty = True
    return dirty


def _load() -> dict[str, Any]:
    global _state_cache
    if _state_cache is not None:
        return _state_cache
    if not _STATE_PATH.is_file():
        _state_cache = _default_state()
        return _state_cache
    try:
        st = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        st = _default_state()
    if st.get("starting_capital", 0) <= 0:
        st["starting_capital"] = _session_start
    if _migrate_state(st):
        _state_cache = st
        _flush_if_needed(force=True)
    _state_cache = st
    return _state_cache


def _save(st: dict[str, Any]) -> None:
    global _state_cache, _state_dirty
    _state_cache = st
    _state_dirty = True
    _flush_if_needed()


def _flush_if_needed(force: bool = False) -> None:
    global _state_dirty, _state_last_save
    now = time.time()
    if not _state_dirty:
        return
    if not force and now - _state_last_save < _STATE_FLUSH_INTERVAL:
        return
    if _state_cache is None:
        return
    try:
        _state_cache["updated_at"] = datetime.now(timezone.utc).isoformat()
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(
            json.dumps(_state_cache, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _state_dirty = False
        _state_last_save = now
    except Exception:
        pass


def flush_state() -> None:
    """Dışarıdan zorla diske yaz (bot kapanmadan önce çağrılır)."""
    _flush_if_needed(force=True)


def _mode_entry(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "min_edge": m.get("min_edge"),
        "min_formula_score": m.get("min_formula_score"),
        "min_edge_mult": float(m.get("entry_min_edge_mult", 1.0)),
        "min_formula_mult": float(m.get("entry_min_formula_mult", 1.0)),
        "min_strength": str(m.get("entry_min_strength", "Medium")),
        "stake_mult": float(m.get("entry_stake_mult", 1.0)),
        "max_open": int(m.get("max_open") or m.get("entry_max_open") or 0),
        "min_stake_usd": m.get("min_stake_usd"),
        "max_stake_usd": m.get("max_stake_usd"),
        "active_capital_pct": m.get("active_capital_pct"),
        "skip_cautious": bool(m.get("entry_skip_cautious", False)),
        "block_weak": bool(m.get("entry_block_weak", True)),
    }


def _strength_ok(strength: str, minimum: str) -> bool:
    return _STRENGTH_RANK.get(strength, 0) >= _STRENGTH_RANK.get(minimum, 2)


def _berserk2_deployable(equity: float, open_stakes: list[float]) -> float:
    buf = max(5.0, float(os.getenv("BERSERK2_OPEN_MARGIN_BUFFER_USD", "30") or 30))
    return max(0.0, float(equity) - sum(open_stakes) - buf)


def _berserk2_require_top_mover() -> bool:
    return os.getenv("BERSERK2_REQUIRE_TOP_MOVER", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _universe_equity(book: dict[str, Any], session_start: float) -> float:
    realized = sum(
        float(c.get("final_pnl") or c.get("net_pnl") or 0)
        for c in book.get("closed", [])
    )
    unreal = sum(float(p.get("unrealized_pnl") or 0) for p in book.get("open", []))
    return session_start + realized + unreal


def _entry_allowed(
    mode_id: str,
    signal: dict[str, Any],
    *,
    execution_path: str = "paper",
) -> tuple[bool, str]:
    if not _edge_fn or not _formula_fn:
        return False, "engine not configured"
    m = mode_catalog().get(mode_id) or {}
    ep = _mode_entry(m)
    sym = str(signal.get("symbol") or "")
    if execution_path == "live" or is_live_binance_motor(mode_id):
        if _tradable and sym and sym not in _tradable:
            _reject_entry(mode_id, signal, "not in universe", execution_path)
            return False, "not in universe"
    elif _scan_universe is not None and sym and sym not in _scan_universe:
        if mode_id == "berserk2" and _berserk2_require_top_mover():
            from elite_trader.berserk2_movers import is_top_mover

            if not is_top_mover(sym):
                _reject_entry(mode_id, signal, "not in universe", execution_path)
                return False, "not in universe"
        elif mode_id != "berserk2":
            _reject_entry(mode_id, signal, "not in universe", execution_path)
            return False, "not in universe"
    if mode_id == "berserk2":
        from elite_trader.berserk2_cooldown import check_cooldown

        cool_min = float(m.get("market_cooldown_min") or 0.006)
        ok_cd, remaining, cd_reject = check_cooldown(sym, cool_min)
        signal["cooldown_reject"] = cd_reject
        signal["cooldown_remaining_sec"] = round(remaining, 1)
        if not ok_cd:
            _log_decision(mode_id, signal, False, "cooldown", execution_path)
            return False, "cooldown"
    elif mode_id == "berserk":
        from elite_trader.berserk_cooldown import check_cooldown

        cool_min = float(m.get("market_cooldown_min") or 0.02)
        ok_cd, remaining, cd_reject = check_cooldown(sym, cool_min)
        signal["cooldown_reject"] = cd_reject
        signal["cooldown_remaining_sec"] = round(remaining, 1)
        if not ok_cd:
            _log_decision(mode_id, signal, False, "cooldown", execution_path)
            return False, "cooldown"
    if mode_id == "berserk2" and _berserk2_require_top_mover():
        from elite_trader.berserk2_movers import is_top_mover

        if not is_top_mover(sym):
            _reject_entry(mode_id, signal, "berserk2_not_top_mover", execution_path)
            return False, "berserk2_not_top_mover"
    if mode_id == "hunter":
        from elite_trader.hunter_cooldown import (
            check_cooldown,
            check_fakeout_guard,
        )

        ok_fg, fg_rem = check_fakeout_guard(sym)
        signal["fakeout_guard_active"] = not ok_fg
        if not ok_fg:
            signal["fakeout_guard_remaining_sec"] = round(fg_rem, 1)
            _log_decision(mode_id, signal, False, "fakeout_guard", execution_path)
            return False, "fakeout_guard"
        cool_min = float(m.get("market_cooldown_min") or 0.8)
        ok_cd, remaining, cd_reject = check_cooldown(sym, cool_min)
        signal["cooldown_reject"] = cd_reject
        signal["cooldown_remaining_sec"] = round(remaining, 1)
        if not ok_cd:
            _log_decision(mode_id, signal, False, "cooldown", execution_path)
            return False, "cooldown"
    if mode_id == "sentinel":
        from elite_trader.sentinel_cooldown import check_cooldown

        cool_min = float(m.get("market_cooldown_min") or 3.0)
        ok_cd, remaining, cd_reject = check_cooldown(sym, cool_min)
        signal["cooldown_reject"] = cd_reject
        signal["cooldown_remaining_sec"] = round(remaining, 1)
        if not ok_cd:
            _log_decision(mode_id, signal, False, "cooldown", execution_path)
            return False, "cooldown"
    if mode_id == "chop_master":
        from elite_trader.chop_cooldown import check_cooldown

        cool_min = float(m.get("market_cooldown_min") or 0.4)
        ok_cd, remaining, cd_reject = check_cooldown(sym, cool_min)
        signal["cooldown_reject"] = cd_reject
        signal["cooldown_remaining_sec"] = round(remaining, 1)
        if not ok_cd:
            _log_decision(mode_id, signal, False, "cooldown", execution_path)
            return False, "cooldown"
    strength = str(signal.get("strength") or "Medium")
    if ep["block_weak"] and strength == "Weak" and mode_id != "hunter":
        if mode_id == "sentinel":
            _reject_entry(mode_id, signal, "sentinel_weak_observation", execution_path)
            return False, "sentinel_weak_observation"
        _reject_entry(mode_id, signal, "weak signal", execution_path)
        return False, "weak signal"
    if mode_id == "hunter" and strength == "Weak":
        pass
    elif not _strength_ok(strength, ep["min_strength"]):
        _reject_entry(mode_id, signal, "strength", execution_path)
        return False, "strength"
    ch = float(signal.get("change") or 0)
    side = str(signal.get("type") or "LONG")
    edge = _edge_fn(ch)
    fs = _formula_fn(ch)

    use_hybrid = False
    if mode_id == "evrim":
        try:
            from elite_trader.evrim_training import is_live_training_enabled

            use_hybrid = is_live_training_enabled(m)
        except Exception:
            use_hybrid = bool(m.get("evrim_live_training", True))

    skip_edge_formula = (
        mode_id == "berserk2" and m.get("berserk2_skip_edge_formula", True)
    ) or (mode_id == "mega" and m.get("mega_skip_edge_formula", True))
    if not (mode_id == "evrim" and use_hybrid):
        if skip_edge_formula:
            pass
        elif not (mode_id == "hunter" and strength == "Weak"):
            if ep["min_edge"] is not None:
                if edge < float(ep["min_edge"]):
                    _reject_entry(mode_id, signal, "edge", execution_path)
                    return False, "edge"
            elif edge < _min_edge * ep["min_edge_mult"]:
                _reject_entry(mode_id, signal, "edge", execution_path)
                return False, "edge"
            if ep["min_formula_score"] is not None:
                if fs < float(ep["min_formula_score"]):
                    _reject_entry(mode_id, signal, "formula", execution_path)
                    return False, "formula"
            elif fs < _min_formula * ep["min_formula_mult"]:
                _reject_entry(mode_id, signal, "formula", execution_path)
                return False, "formula"

    if mode_id == "evrim":
        try:
            from elite_trader.evrim_opportunity import evrim_entry_gate

            ok_opp, opp_reason = evrim_entry_gate(
                mode_id, signal, m, execution_path=execution_path
            )
            if not ok_opp:
                _reject_entry(mode_id, signal, opp_reason, execution_path)
                return False, opp_reason
        except Exception:
            _reject_entry(mode_id, signal, "evrim_filter", execution_path)
            return False, "evrim_filter"
    skip_risk = (
        mode_id == "berserk2" and m.get("berserk2_skip_risk_gate", True)
    ) or (mode_id == "mega" and m.get("mega_skip_risk_gate", True))
    if _risk_fn and not skip_risk:
        veto_n = m.get("sl_em_veto_count")
        cool = m.get("sl_em_cooldown_min")
        ok, reason, tier = _risk_fn(
            sym,
            side,
            strength,
            ch,
            fs,
            veto_count=int(veto_n) if veto_n is not None else None,
            cooldown_min=int(cool) if cool is not None else None,
            skip_cautious=bool(ep["skip_cautious"]),
            cautious_min_strength=str(ep["min_strength"]),
        )
        if not ok:
            _log_decision(mode_id, signal, False, reason or "risk", execution_path)
            return False, reason or "risk"
        if ep["skip_cautious"] and tier == "cautious":
            _log_decision(mode_id, signal, False, "cautious", execution_path)
            return False, "cautious"
    if mode_id != "evrim":
        try:
            from elite_trader.mode_engines import evaluate_entry

            ctx = {
                "regime": signal.get("market_regime"),
                "spread_pct": signal.get("spread_pct"),
                "spread_policy": m.get("spread_policy"),
                "vol_ratio": signal.get("vol_ratio"),
                "adx": signal.get("adx"),
                "news_shock": signal.get("news_shock"),
                "trend_bias": signal.get("trend_bias"),
            }
            if is_berserk_family(mode_id):
                ctx["profile"] = m
                ctx["edge"] = edge
                ctx["formula_score"] = fs
                ctx["flow_bias"] = signal.get("pool_flow_bias")
                ctx["news_sentiment"] = signal.get("pool_news_sentiment")
                ctx["cross_exchange_delta"] = signal.get("pool_cross_px_delta_pct")
                ctx["orderbook_pressure"] = signal.get("orderbook_pressure")
                ctx["slippage_estimate"] = signal.get("slippage_estimate")
                ctx["vol_ratio"] = signal.get("vol_ratio")
                if mode_id == "berserk2":
                    from elite_trader.berserk2_btc_context import get_btc_context

                    ctx["btc_context"] = get_btc_context()
            if mode_id == "hunter":
                ctx["profile"] = m
                ctx["edge"] = edge
                ctx["formula_score"] = fs
                ctx["flow_bias"] = signal.get("pool_flow_bias")
                ctx["news_sentiment"] = signal.get("pool_news_sentiment")
                ctx["cross_exchange_delta"] = signal.get("pool_cross_px_delta_pct")
                ctx["liquidation_proxy"] = signal.get("liquidation_proxy")
                ctx["orderbook_pressure"] = signal.get("orderbook_pressure")
            if mode_id == "mega":
                ctx["profile"] = m
                ctx["edge"] = edge
                ctx["formula_score"] = fs
                ctx["flow_bias"] = signal.get("pool_flow_bias")
                ctx["news_sentiment"] = signal.get("pool_news_sentiment")
                ctx["liquidation_proxy"] = signal.get("liquidation_proxy")
                ctx["orderbook_pressure"] = signal.get("orderbook_pressure")
                ctx["vol_ratio"] = signal.get("vol_ratio")
                ctx["spread_pct"] = signal.get("spread_pct")
            if mode_id == "sentinel":
                ctx["profile"] = m
                ctx["edge"] = edge
                ctx["formula_score"] = fs
                ctx["change_pct"] = ch
                ctx["trend_bias"] = signal.get("trend_bias")
                ctx["adx"] = signal.get("adx")
                ctx["vol_ratio"] = signal.get("vol_ratio")
                ctx["atr_pct"] = signal.get("atr_pct")
                ctx["spread_pct"] = signal.get("spread_pct")
            if mode_id == "chop_master":
                ctx["profile"] = m
                ctx["edge"] = edge
                ctx["formula_score"] = fs
                ctx["adx"] = signal.get("adx")
                ctx["atr_pct"] = signal.get("atr_pct")
                ctx["vol_ratio"] = signal.get("vol_ratio")
                ctx["spread_pct"] = signal.get("spread_pct")
                ctx["orderbook_pressure"] = signal.get("orderbook_pressure")
                ctx["flow_bias"] = signal.get("pool_flow_bias")
                ctx["range_width_pct"] = signal.get("range_width_pct")
                ctx["rsi7"] = signal.get("rsi7")
                ctx["hunter_breakout_score"] = signal.get("breakout_score")
                ctx["liquidation_proxy"] = signal.get("liquidation_proxy")
            ok_m, m_reason = evaluate_entry(mode_id, signal, ctx)
            if not ok_m:
                if (
                    execution_path == "paper"
                    and mode_id in ("hunter", "chop_master", "sentinel")
                    and not is_live_binance_motor(mode_id)
                ):
                    try:
                        from elite_trader.mode_minimum_data import assess_minimum_data

                        st_md = _load()
                        book_md = (st_md.get("universes") or {}).get(mode_id) or {}
                        md = assess_minimum_data(mode_id, book_md)
                        if md.get("active"):
                            action, exp_reason, _meta = _try_minimum_data_exploration(
                                mode_id, signal, ctx, m, m_reason
                            )
                            signal["minimum_data_mode_active"] = md.get("active")
                            signal["minimum_data_reason"] = md.get("reason")
                            if action == "allow":
                                signal["minimum_data_trade_or_observation"] = "exploration_trade"
                                _log_decision(mode_id, signal, True, exp_reason, execution_path)
                                return True, exp_reason
                            if action == "observation":
                                signal["minimum_data_trade_or_observation"] = "observation"
                                _reject_entry(mode_id, signal, exp_reason, execution_path)
                                return False, exp_reason
                    except Exception:
                        pass
                _reject_entry(mode_id, signal, m_reason, execution_path)
                return False, m_reason
            if is_berserk_family(mode_id):
                from elite_trader.berserk_reentry import evaluate_reentry

                ok_re, re_reason, re_meta = evaluate_reentry(
                    sym,
                    str(signal.get("type") or "LONG"),
                    signal,
                    ctx,
                    m,
                )
                bm = signal.get("berserk_meta") or {}
                bm.update(re_meta)
                signal["berserk_meta"] = bm
                if not ok_re:
                    _log_decision(mode_id, signal, False, re_reason, execution_path)
                    return False, re_reason
        except Exception:
            pass
    if is_berserk_family(mode_id):
        try:
            import os

            from elite_trader.fee_economics import entry_gate

            m = mode_catalog().get(mode_id) or {}
            require = m.get("entry_require_net_tp")
            env_on = os.getenv("ELITE_ENTRY_REQUIRE_NET_TP", "1").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            if require is False or not env_on:
                pass
            elif env_on:
                meta = signal.get("berserk_meta") or {}
                mult = float(
                    meta.get("combined_stake_mult")
                    or meta.get("btc_stake_mult")
                    or 0.85
                )
                est_stake = max(
                    float(m.get("min_stake_usd") or 120) * mult,
                    float(m.get("min_stake_usd") or 120) * 0.55,
                )
                lev = 3
                if _leverage_fn:
                    try:
                        lev = max(
                            1,
                            int(
                                _leverage_fn(
                                    ch,
                                    str(signal.get("type") or "LONG"),
                                    str(signal.get("strength") or "Medium"),
                                )
                            ),
                        )
                    except Exception:
                        pass
                ok_e, e_reason = entry_gate(est_stake, lev, mode_id=mode_id)
                if not ok_e:
                    _reject_entry(mode_id, signal, e_reason, execution_path)
                    return False, e_reason
        except Exception:
            pass
    _log_decision(mode_id, signal, True, "", execution_path)
    return True, ""


def _hunter_decision_extra(
    mode_id: str, signal: dict[str, Any], reason: str
) -> dict[str, Any]:
    meta = signal.get("hunter_meta") or {}
    return {
        "mode_id": mode_id,
        "timestamp": time.time(),
        "change_pct": float(signal.get("change") or 0),
        "strength": signal.get("strength"),
        "vol_ratio": float(signal.get("vol_ratio") or 0),
        "liquidation_proxy": float(signal.get("liquidation_proxy") or 0),
        "breakout_score": meta.get("breakout_score") or signal.get("breakout_score"),
        "breakout_score_breakdown": meta.get("breakout_score_breakdown"),
        "fake_breakout_risk": meta.get("fake_breakout_risk")
        or signal.get("fake_breakout_risk"),
        "fake_breakout_reason": meta.get("fake_breakout_reason"),
        "liquidation_cascade_score": meta.get("liquidation_cascade_score"),
        "spike_type": meta.get("spike_type"),
        "entry_delay_sec": meta.get("entry_delay_sec"),
        "explosive_opportunity": meta.get("explosive_opportunity"),
        "spread_pct": float(signal.get("spread_pct") or meta.get("spread_pct") or 0),
        "spread_risk_level": meta.get("spread_risk_level")
        or signal.get("spread_risk_level"),
        "market_regime": signal.get("market_regime"),
        "reason": reason,
    }


def _chop_decision_extra(
    mode_id: str, signal: dict[str, Any], reason: str
) -> dict[str, Any]:
    meta = signal.get("chop_meta") or {}
    return {
        "mode_id": mode_id,
        "timestamp": time.time(),
        "change_pct": float(signal.get("change") or 0),
        "strength": signal.get("strength"),
        "chop_score": meta.get("chop_score"),
        "chop_reason": meta.get("chop_reason"),
        "range_quality": meta.get("range_quality"),
        "mean_reversion_probability": meta.get("mean_reversion_probability"),
        "mean_reversion_score": meta.get("mean_reversion_score"),
        "failed_breakout_detected": meta.get("failed_breakout_detected"),
        "reversal_score": meta.get("reversal_score"),
        "trend_guard_active": meta.get("trend_guard_active"),
        "trend_guard_reason": meta.get("trend_guard_reason"),
        "spread_pct": float(signal.get("spread_pct") or meta.get("spread_pct") or 0),
        "spread_risk_level": meta.get("spread_risk_level"),
        "range_width_pct": meta.get("range_width_pct"),
        "reason": reason,
    }


def _log_decision(
    mode_id: str,
    signal: dict[str, Any],
    allowed: bool,
    reason: str,
    execution_path: str,
) -> None:
    try:
        from elite_trader.evrim_cross_strategy_lab import record_mode_decision

        record_mode_decision(mode_id, signal, allowed, reason, execution_path)
    except Exception:
        pass
    # Paper redleri — Hunter + Sentinel + Chop + Evrim (data lake)
    if execution_path == "paper" and not allowed:
        if mode_id not in ("hunter", "sentinel", "chop_master", "evrim"):
            return
    try:
        from elite_trader.data_lake.ingest import ingest_decision

        extra = None
        if mode_id == "hunter":
            extra = _hunter_decision_extra(mode_id, signal, reason)
        elif mode_id == "chop_master":
            extra = _chop_decision_extra(mode_id, signal, reason)
        elif mode_id == "sentinel":
            meta = signal.get("sentinel_meta") or {}
            extra = {
                "mode_id": mode_id,
                "change_pct": float(signal.get("change") or 0),
                "strength": signal.get("strength"),
                "formula_score": signal.get("formula_score"),
                "edge": signal.get("edge"),
                "sentinel_quality_score": meta.get("sentinel_quality_score"),
                "sentinel_execution_quality_score": meta.get(
                    "sentinel_execution_quality_score"
                ),
                "spread_pct": meta.get("spread_pct") or signal.get("spread_pct"),
                "market_regime": signal.get("market_regime"),
                "reason": reason,
            }
        elif mode_id == "evrim":
            learn = signal.get("evrim_learning") or {}
            v2 = signal.get("evrim_v2") or {}
            extra = {
                "mode_id": mode_id,
                "learning_active": learn.get("learning_active", False),
                "learning_blocks_trading": False,
                "trading_continues_during_learning": True,
                "active_config_version": learn.get("active_config_version"),
                "candidate_config_version": learn.get("candidate_config_version"),
                "pending_approval": learn.get("pending_approval", False),
                "risk_mode_during_learning": learn.get("risk_mode_during_learning"),
                "learning_task_type": learn.get("learning_task_type"),
                "final_score": (v2.get("meta") or {}).get("final_score"),
                "risk_level": (v2.get("risk") or {}).get("risk_level"),
                "reason": reason,
            }
        ingest_decision(
            mode_id,
            symbol=str(signal.get("symbol") or ""),
            side=str(signal.get("type") or ""),
            allowed=allowed,
            reason=reason,
            execution_path=execution_path,
            signal_passed=True,
            risk_passed=allowed or reason not in ("edge", "formula", "risk"),
            extra=extra,
        )
        if mode_id == "evrim":
            try:
                from elite_trader.evrim_decision_log import append_decision

                v2 = signal.get("evrim_v2") or {}
                meta = (v2.get("meta") if isinstance(v2, dict) else None) or signal.get("evrim_meta") or {}
                append_decision(
                    {
                        "mode_id": mode_id,
                        "symbol": str(signal.get("symbol") or ""),
                        "side": str(signal.get("type") or ""),
                        "entered": allowed,
                        "allowed": allowed,
                        "reason": reason,
                        "reason_skip": reason if not allowed else "",
                        "execution_path": execution_path,
                        "final_score": meta.get("final_score"),
                        "meta_tier": meta.get("meta_tier"),
                        "total_score": meta.get("final_score") or (signal.get("evrim_hybrid") or {}).get("total_score"),
                    }
                )
            except Exception:
                pass
            from elite_trader.evrim_meta_learning import on_decision_recorded

            on_decision_recorded()
    except Exception:
        pass


def _open_shadow(
    mode_id: str,
    signal: dict[str, Any],
    price: float,
    book: dict[str, Any],
) -> None:
    if price <= 0 or not _kelly_fn or not _stake_bounds_fn or not _leverage_fn:
        return
    m = mode_catalog().get(mode_id) or {}
    ep = _mode_entry(m)
    sym = signal["symbol"]
    side = signal["type"]
    if any(p["symbol"] == sym for p in book["open"]):
        return
    max_open = ep["max_open"] or (_max_open_fn() if _max_open_fn else 14)
    st0 = _load()
    session_start = _mode_session_start(st0, mode_id)
    equity = _universe_equity(book, session_start)
    try:
        from elite_trader.paper_book import effective_paper_equity

        equity = effective_paper_equity(equity, mode_id)
    except Exception:
        pass
    open_stakes = [float(p["stake_usd"]) for p in book["open"]]
    if mode_id == "berserk2":
        try:
            from elite_trader.capital_slots import (
                effective_max_open,
                plan_stake,
                slot_allocator_enabled,
            )

            if slot_allocator_enabled("berserk2"):
                deploy = _berserk2_deployable(equity, open_stakes)
                max_open = effective_max_open(
                    deploy,
                    profile_cap=max_open,
                    mode_id="berserk2",
                    dynamic=True,
                )
        except Exception:
            pass
    if len(book["open"]) >= max_open:
        return

    ch = float(signal.get("change") or 0)
    kelly = _kelly_fn(ch, side)
    min_s, max_s = _stake_bounds_fn()
    min_stake_source = "global_env"
    if is_berserk_family(mode_id):
        from elite_trader.mode_engines.berserk_scoring import resolve_min_stake, strength_stake_mult

        paper_route = not is_live_binance_motor(mode_id)
        strength = str(signal.get("strength") or "Medium")
        min_s, min_stake_source = resolve_min_stake(
            m,
            paper=paper_route,
            env_min=min_s,
            strength_mult=strength_stake_mult(strength, m),
        )
    elif ep.get("min_stake_usd") is not None:
        min_s = max(min_s, float(ep["min_stake_usd"]))
        min_stake_source = "mode_profile"
    if ep.get("max_stake_usd") is not None:
        max_s = float(ep["max_stake_usd"])
    wr = _wr_fn() if _wr_fn else None
    active_pct = (
        float(ep["active_capital_pct"])
        if ep.get("active_capital_pct") is not None
        else None
    )
    stake_mult = float(ep["stake_mult"])
    if is_berserk_family(mode_id):
        meta = signal.get("berserk_meta") or {}
        stake_mult *= float(meta.get("combined_stake_mult") or 1.0)
    if mode_id == "hunter":
        meta = signal.get("hunter_meta") or {}
        stake_mult *= float(meta.get("combined_stake_mult") or 1.0)
    if mode_id == "mega":
        meta = signal.get("mega_meta") or {}
        stake_mult *= float(meta.get("combined_stake_mult") or 1.0)
    if mode_id == "chop_master":
        meta = signal.get("chop_meta") or {}
        stake_mult *= float(meta.get("combined_stake_mult") or 1.0)
    if mode_id == "sentinel":
        meta = signal.get("sentinel_meta") or {}
        sm = float(meta.get("sentinel_stake_mult") or 0)
        if sm > 0:
            stake_mult = sm
    if mode_id == "evrim":
        hybrid = signal.get("evrim_hybrid") or {}
        tier_mult = float(hybrid.get("stake_mult") or 1.0)
        if tier_mult > 0:
            stake_mult *= tier_mult
        risk = signal.get("evrim_risk") or {}
        rm = float(risk.get("risk_stake_mult") or 0)
        if rm > 0:
            stake_mult *= rm
    stake = compute_stake(
        equity,
        open_stakes,
        kelly_stake=kelly * stake_mult,
        max_open=max_open,
        min_stake=min_s,
        max_stake=max_s,
        win_rate=wr,
        active_capital_pct_override=active_pct,
    )
    if mode_id == "berserk2":
        try:
            from elite_trader.capital_slots import plan_stake, slot_allocator_enabled

            if slot_allocator_enabled("berserk2"):
                deploy = _berserk2_deployable(equity, open_stakes)
                slot_stake = plan_stake(
                    deploy,
                    len(book["open"]),
                    mode_id="berserk2",
                    max_open=max_open,
                    profile_cap=max_open,
                )
                if slot_stake > 0:
                    stake = slot_stake * stake_mult
        except Exception:
            pass
    if stake <= 0 and mode_id == "berserk2":
        try:
            from elite_trader.paper_book import berserk2_paper_fallback_stake

            fb = berserk2_paper_fallback_stake(
                min_stake=min_s,
                max_stake=max_s,
                open_count=len(book["open"]),
                max_open=max_open,
            )
            if fb and fb > 0:
                stake = float(fb)
        except Exception:
            pass
    if stake <= 0:
        return

    strength = str(signal.get("strength") or "Medium")
    if mode_id == "mega":
        from elite_trader.mode_engines.mega_scoring import mega_leverage

        lev = mega_leverage(signal, strength, m)
    else:
        lev = _leverage_fn(strength, 2 if strength == "Strong" else 1)
    size = stake * lev / price
    dynamic_exit: dict[str, Any] = {}
    if mode_id == "evrim":
        try:
            from elite_trader.mode_profiles import get_profile

            prof = get_profile(mode_id) or m
            de = signal.get("evrim_dynamic_exit") or (
                (signal.get("evrim_hybrid") or {}).get("dynamic_exit")
            )
            if de:
                from elite_trader.evrim_dynamic_exit import (
                    DynamicExitPlan,
                    plan_to_usd_targets,
                )

                plan = DynamicExitPlan(
                    tp_stake_pct=float(de.get("tp_stake_pct") or 0.006),
                    sl_stake_pct=float(de.get("sl_stake_pct") or 0.0025),
                    tp_trigger_frac=float(de.get("tp_trigger_frac") or 0.98),
                    partial_tp_frac=float(de.get("partial_tp_frac") or 0.5),
                    trailing_enabled=bool(de.get("trailing_enabled", True)),
                    breakeven_buffer_pct=float(de.get("breakeven_buffer_pct") or 0.08),
                    momentum_weak_exit=bool(de.get("momentum_weak_exit", True)),
                )
                tp_usd, sl_usd, partial_usd = plan_to_usd_targets(plan, stake)
                dynamic_exit = de
            elif prof.get("evrim_dynamic_exit_enabled", True):
                from elite_trader.evrim_opportunity import _load_state
                from elite_trader.evrim_dynamic_exit import (
                    compute_dynamic_exit,
                    plan_to_usd_targets,
                )

                ctx = (_load_state().get("last_opportunity_ctx") or {})
                hybrid = signal.get("evrim_hybrid") or {}
                plan = compute_dynamic_exit(
                    total_score=float(hybrid.get("total_score") or 70),
                    side=side,
                    signal=signal,
                    ctx=ctx,
                    profile=prof,
                    stake_usd=stake,
                    leverage=lev,
                )
                tp_usd, sl_usd, partial_usd = plan_to_usd_targets(plan, stake)
                dynamic_exit = plan.to_dict()
            else:
                tp_usd, sl_usd = stake_targets(stake, mode_id)
                partial_usd = 0.0
        except Exception:
            tp_usd, sl_usd = stake_targets(stake, mode_id)
            partial_usd = 0.0
    elif mode_id == "hunter":
        meta = signal.get("hunter_meta") or {}
        de = meta.get("dynamic_exit") or {}
        tp_pct = float(de.get("tp_stake_pct") or m.get("tp_stake_pct") or 0.0095)
        sl_pct = float(de.get("sl_stake_pct") or m.get("sl_stake_pct") or 0.0042)
        trig = float(de.get("tp_trigger_frac") or m.get("tp_trigger_frac") or 1.0)
        tp_usd = stake * tp_pct * trig
        sl_usd = stake * sl_pct
        p_frac = float(de.get("partial_tp_frac") or 0)
        partial_usd = stake * tp_pct * p_frac if p_frac > 0 else 0.0
        dynamic_exit = de
    elif is_berserk_family(mode_id):
        meta = signal.get("berserk_meta") or {}
        de = meta.get("berserk_dynamic_exit") or {}
        tp_pct = float(de.get("tp_stake_pct") or m.get("tp_stake_pct") or 0.0042)
        sl_pct = float(de.get("sl_stake_pct") or m.get("sl_stake_pct") or 0.0024)
        trig = float(de.get("tp_trigger_frac") or m.get("tp_trigger_frac") or 0.99)
        tp_usd = stake * tp_pct * trig
        sl_usd = stake * sl_pct
        partial_usd = 0.0
        dynamic_exit = de
    elif mode_id == "chop_master":
        meta = signal.get("chop_meta") or {}
        de = meta.get("dynamic_exit") or {}
        tp_pct = float(de.get("tp_stake_pct") or m.get("tp_stake_pct") or 0.0028)
        sl_pct = float(de.get("sl_stake_pct") or m.get("sl_stake_pct") or 0.0018)
        trig = float(de.get("tp_trigger_frac") or m.get("tp_trigger_frac") or 0.99)
        tp_usd = stake * tp_pct * trig
        sl_usd = stake * sl_pct
        p_frac = float(de.get("partial_tp_frac") or 0.50)
        partial_usd = stake * tp_pct * p_frac if p_frac > 0 else 0.0
        dynamic_exit = de
    elif mode_id == "sentinel":
        meta = signal.get("sentinel_meta") or {}
        de = meta.get("sentinel_dynamic_exit") or {}
        tp_pct = float(de.get("tp_stake_pct") or m.get("tp_stake_pct") or 0.0095)
        sl_pct = float(de.get("sl_stake_pct") or m.get("sl_stake_pct") or 0.0042)
        trig = float(de.get("tp_trigger_frac") or m.get("tp_trigger_frac") or 1.02)
        tp_usd = stake * tp_pct * trig
        sl_usd = stake * sl_pct
        p_frac = float(de.get("partial_tp_frac") or 0.4)
        partial_usd = stake * tp_pct * p_frac if p_frac > 0 else 0.0
        dynamic_exit = de
    else:
        tp_usd, sl_usd = stake_targets(stake, mode_id)
        partial_usd = 0.0
    if side == "LONG":
        tp_p = price + tp_usd / size if size > 0 else price
        sl_p = price - sl_usd / size if size > 0 else price
    else:
        tp_p = price - tp_usd / size if size > 0 else price
        sl_p = price + sl_usd / size if size > 0 else price

    entry_fee = size * price * 0.0004
    pid = int(book["next_id"])
    book["next_id"] = pid + 1
    opened_iso = datetime.now(timezone.utc).isoformat()
    row: dict[str, Any] = {
        "id": pid,
        "universe_id": mode_id,
        "symbol": sym,
        "side": side,
        "entry_price": price,
        "current_price": price,
        "size": size,
        "leverage": lev,
        "stake_usd": stake,
        "position_value": size * price,
        "unrealized_pnl": 0.0,
        "pnl_pct": 0.0,
        "entry_time": time.time(),
        "entry_time_str": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "opened_at_iso": opened_iso,
        "tp_target": tp_p,
        "sl_target": sl_p,
        "tp_target_usd": tp_usd,
        "sl_target_usd": sl_usd,
        "price_history": [price],
        "time_history": [opened_iso],
        "entry_fee": entry_fee,
        "total_fees": entry_fee,
        "edge": _edge_fn(ch) if _edge_fn else 0,
        "formula_score": _formula_fn(ch) if _formula_fn else 0,
        "signal_source": f"Parallel-{mode_id}",
        "signal_strength": strength,
        "panel_mode": mode_id,
        "execution_mode_at_open": mode_id,
        "on_exchange": False,
        "min_unreal_seen": 0.0,
        "max_unreal_seen": 0.0,
        "partial_tp_done": False,
        "tp_partial_usd": partial_usd if mode_id in ("evrim", "hunter", "sentinel") else 0.0,
        "dynamic_exit": dynamic_exit,
        "dynamic_sl_usd": sl_usd,
    }
    try:
        from elite_trader.fee_economics import apply_net_targets_to_position

        apply_net_targets_to_position(row, mode_id)
    except Exception:
        pass
    if mode_id == "evrim":
        try:
            from elite_trader.evrim_opportunity import _load_state

            ctx = (_load_state().get("last_opportunity_ctx") or {})
            row["market_regime"] = ctx.get("market_regime") or ctx.get("regime")
            row["entry_context"] = {
                "vol_ratio": ctx.get("vol_ratio"),
                "atr_pct": ctx.get("atr_pct"),
                "spread_pct": ctx.get("spread_pct"),
                "hybrid_score": ctx.get("hybrid_score"),
                "hybrid_tier": ctx.get("hybrid_tier"),
                "hybrid_components": ctx.get("hybrid_components"),
                "expected_net_pnl_usd": ctx.get("expected_net_pnl_usd"),
            }
            hybrid = signal.get("evrim_hybrid") or {}
            if hybrid:
                row["hybrid_score"] = hybrid.get("total_score")
                row["hybrid_tier"] = hybrid.get("tier")
            try:
                from elite_trader.evrim_trade_learning import build_learning_snapshot

                row["learning_snapshot"] = build_learning_snapshot(
                    signal=signal,
                    ctx=ctx,
                    entry_reason=str(signal.get("evrim_entry_reason") or "hybrid"),
                )
            except Exception:
                pass
        except Exception:
            pass
    if is_berserk_family(mode_id):
        meta = signal.get("berserk_meta") or {}
        row["berserk_score"] = meta.get("berserk_score")
        row["spread_risk_level"] = meta.get("spread_risk_level") or signal.get(
            "spread_risk_level"
        )
        row["min_stake_source"] = min_stake_source
        row["expected_net_pnl"] = meta.get("expected_net_pnl_usd")
        row["combined_stake_mult"] = meta.get("combined_stake_mult")
        row["learning_tag"] = meta.get("learning_tag") or signal.get("learning_tag")
        row["berserk_meta"] = meta
        row["dynamic_exit"] = meta.get("berserk_dynamic_exit") or dynamic_exit
        row["slippage_damage_score"] = meta.get("slippage_damage_score")
    if mode_id == "hunter":
        meta = signal.get("hunter_meta") or {}
        row["breakout_score"] = meta.get("breakout_score")
        row["fake_breakout_risk"] = meta.get("fake_breakout_risk")
        row["spread_risk_level"] = meta.get("spread_risk_level") or signal.get(
            "spread_risk_level"
        )
        row["liquidation_cascade_score"] = meta.get("liquidation_cascade_score")
        row["explosive_opportunity"] = meta.get("explosive_opportunity")
        row["explosive_liquidation_opportunity"] = meta.get(
            "explosive_liquidation_opportunity"
        )
        row["spike_type"] = meta.get("spike_type")
        row["entry_delay_sec"] = meta.get("entry_delay_sec")
        row["combined_stake_mult"] = meta.get("combined_stake_mult")
        row["hunter_meta"] = meta
        row["change"] = ch
        if dynamic_exit.get("trailing_enabled"):
            row["trailing_enabled"] = True
    if mode_id == "chop_master":
        meta = signal.get("chop_meta") or {}
        row["chop_score"] = meta.get("chop_score")
        row["mean_reversion_score"] = meta.get("mean_reversion_score")
        row["range_width_pct"] = meta.get("range_width_pct")
        row["failed_breakout_detected"] = meta.get("failed_breakout_detected")
        row["reversal_score"] = meta.get("reversal_score")
        row["spread_risk_level"] = meta.get("spread_risk_level") or signal.get(
            "spread_risk_level"
        )
        row["combined_stake_mult"] = meta.get("combined_stake_mult")
        row["expected_net_pnl"] = meta.get("expected_net_pnl_usd")
        row["chop_meta"] = meta
        row["change"] = ch
        if dynamic_exit.get("partial_tp_frac"):
            row["partial_tp_frac"] = dynamic_exit.get("partial_tp_frac")
    if mode_id == "sentinel":
        meta = signal.get("sentinel_meta") or {}
        row["sentinel_meta"] = meta
        row["sentinel_quality_score"] = meta.get("sentinel_quality_score")
        row["sentinel_execution_quality_score"] = meta.get(
            "sentinel_execution_quality_score"
        )
        row["sentinel_safe_market_score"] = meta.get("sentinel_safe_market_score")
        row["spread_risk_level"] = meta.get("spread_risk_level")
        row["sentinel_signal_tags"] = meta.get("sentinel_signal_tags")
        row["change"] = ch
        if dynamic_exit.get("trailing_enabled"):
            row["trailing_enabled"] = True
    book["open"].append(row)
    try:
        from elite_trader.mode_minimum_data import touch_paper_trade

        touch_paper_trade(mode_id)
    except Exception:
        pass
    if mode_id == "evrim":
        try:
            from elite_trader.evrim_exploration import touch_trade

            touch_trade()
        except Exception:
            pass
    try:
        from elite_trader.data_lake.ingest import ingest_paper_trade

        ingest_paper_trade(mode_id, row, closing=False)
    except Exception:
        pass


def _close_shadow(
    mode_id: str,
    pos: dict[str, Any],
    exit_reason: str,
    book: dict[str, Any],
) -> None:
    from elite_trader.fee_economics import (
        estimate_close_from_position,
        exit_min_net_usd,
        exit_slippage_buffer_usd,
    )

    exit_price = float(pos.get("current_price") or pos.get("entry_price") or 0)
    pnl = float(pos.get("unrealized_pnl") or 0)
    econ = estimate_close_from_position(pos)
    floor = exit_min_net_usd(mode_id) + exit_slippage_buffer_usd(mode_id)
    if float(econ["final_pnl"]) <= 0.0 or float(econ["final_pnl"]) < floor:
        return
    exit_fee = float(econ.get("total_fees") or 0) - float(pos.get("entry_fee") or 0)
    exit_fee = max(0.0, exit_fee)
    total_fees = float(econ.get("total_fees") or 0)
    net_pnl = float(econ.get("net_pnl") or 0)
    tax = float(econ.get("tax") or 0)
    final_pnl = float(econ.get("final_pnl") or 0)
    closed = {
        "id": pos["id"],
        "universe_id": mode_id,
        "symbol": pos["symbol"],
        "side": pos["side"],
        "entry_price": pos["entry_price"],
        "exit_price": exit_price,
        "size": pos["size"],
        "leverage": pos["leverage"],
        "stake_usd": pos["stake_usd"],
        "pnl_usd": pnl,
        "pnl_pct": (pnl / pos["stake_usd"]) * 100 if pos["stake_usd"] else 0,
        "entry_fee": pos.get("entry_fee", 0),
        "exit_fee": round(exit_fee, 4),
        "total_fees": round(total_fees, 4),
        "net_pnl": round(net_pnl, 4),
        "net_pnl_pct": (net_pnl / pos["stake_usd"]) * 100 if pos["stake_usd"] else 0,
        "tax": round(tax, 4),
        "final_pnl": round(final_pnl, 4),
        "exit_reason": exit_reason,
        "entry_time": pos.get("entry_time_str"),
        "exit_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "duration": time.time() - float(pos.get("entry_time") or time.time()),
        "signal_strength": pos.get("signal_strength"),
        "formula_score": pos.get("formula_score"),
        "edge": pos.get("edge"),
        "panel_mode": mode_id,
        "execution_mode_at_close": mode_id,
        "signal_source": pos.get("signal_source"),
        "market_regime": pos.get("market_regime"),
        "learning_snapshot": pos.get("learning_snapshot"),
        "entry_context": pos.get("entry_context"),
        "opened_at_iso": pos.get("opened_at_iso"),
        "max_unreal_seen": float(pos.get("max_unreal_seen") or 0),
        "min_unreal_seen": float(pos.get("min_unreal_seen") or 0),
        "hybrid_score": pos.get("hybrid_score"),
    }
    if is_berserk_family(mode_id):
        closed["spread_risk_level"] = pos.get("spread_risk_level")
        closed["min_stake_source"] = pos.get("min_stake_source")
        closed["berserk_score"] = pos.get("berserk_score")
        closed["learning_tag"] = pos.get("learning_tag")
        closed["slippage_damage_score"] = pos.get("slippage_damage_score")
    if mode_id == "hunter":
        closed["breakout_score"] = pos.get("breakout_score")
        closed["fake_breakout_risk"] = pos.get("fake_breakout_risk")
        closed["spread_risk_level"] = pos.get("spread_risk_level")
        closed["liquidation_cascade_score"] = pos.get("liquidation_cascade_score")
        closed["explosive_opportunity"] = pos.get("explosive_opportunity")
        closed["explosive_liquidation_opportunity"] = pos.get(
            "explosive_liquidation_opportunity"
        )
        closed["spike_type"] = pos.get("spike_type")
        closed["entry_delay_sec"] = pos.get("entry_delay_sec")
        closed["change"] = pos.get("change")
    if mode_id == "chop_master":
        closed["chop_score"] = pos.get("chop_score")
        closed["mean_reversion_score"] = pos.get("mean_reversion_score")
        closed["range_width_pct"] = pos.get("range_width_pct")
        closed["failed_breakout_detected"] = pos.get("failed_breakout_detected")
        closed["reversal_score"] = pos.get("reversal_score")
        closed["spread_risk_level"] = pos.get("spread_risk_level")
        closed["trend_guard_active"] = (pos.get("chop_meta") or {}).get(
            "trend_guard_active"
        )
        closed["change"] = pos.get("change")
    if mode_id == "sentinel":
        closed["sentinel_meta"] = pos.get("sentinel_meta")
        closed["sentinel_quality_score"] = pos.get("sentinel_quality_score")
        closed["sentinel_execution_quality_score"] = pos.get(
            "sentinel_execution_quality_score"
        )
        closed["spread_risk_level"] = pos.get("spread_risk_level")
    book["closed"].append(closed)
    book["open"] = [p for p in book["open"] if p["id"] != pos["id"]]
    if len(book["closed"]) > 800:
        book["closed"] = book["closed"][-800:]
    try:
        _close_fx_queue.put_nowait(
            (mode_id, dict(closed), list(book["closed"][-120:]))
        )
    except Exception:
        pass


def _tick_book(
    mode_id: str, book: dict[str, Any], prices: dict[str, float], *, check_exits: bool = True
) -> bool:
    changed = False
    for pos in list(book["open"]):
        sym = pos["symbol"]
        # prices "BTC" formatında, sym "BTCUSDT" formatında olabilir
        coin_key = sym.replace("USDT", "")
        px = float(prices.get(coin_key) or prices.get(sym) or pos.get("current_price") or 0)
        if px <= 0:
            continue
        pos["current_price"] = px
        if pos["side"] == "LONG":
            pos["unrealized_pnl"] = (px - pos["entry_price"]) * pos["size"]
        else:
            pos["unrealized_pnl"] = (pos["entry_price"] - px) * pos["size"]
        pos["pnl_pct"] = (pos["unrealized_pnl"] / pos["stake_usd"]) * 100
        unreal = float(pos["unrealized_pnl"])
        pos["min_unreal_seen"] = min(float(pos.get("min_unreal_seen", unreal)), unreal)
        pos["max_unreal_seen"] = max(float(pos.get("max_unreal_seen", unreal)), unreal)
        if not check_exits:
            continue
        stake = float(pos["stake_usd"])
        opened_at = pos.get("opened_at_iso")
        reason = None
        if mode_id == "evrim" and pos.get("dynamic_exit"):
            try:
                from elite_trader.evrim_dynamic_exit import evaluate_evrim_dynamic_exit
                from elite_trader.mode_profiles import get_profile

                reason = evaluate_evrim_dynamic_exit(
                    pos, profile=get_profile(mode_id) or {}
                )
            except Exception:
                reason = None
        if mode_id == "hunter" and pos.get("dynamic_exit") and not reason:
            de = pos.get("dynamic_exit") or {}
            partial_usd = float(pos.get("tp_partial_usd") or 0)
            sl_ref = float(pos.get("dynamic_sl_usd") or pos.get("sl_target_usd") or 0)
            tp_ref = float(pos.get("tp_target_usd") or 0)
            if (
                not pos.get("partial_tp_done")
                and partial_usd > 0
                and unreal >= partial_usd
            ):
                pos["partial_tp_done"] = True
                frac = float(de.get("partial_tp_frac") or 0.4)
                reduce = max(0.05, 1.0 - frac)
                pos["size"] = float(pos["size"]) * reduce
                pos["stake_usd"] = stake * reduce
                pos["dynamic_sl_usd"] = max(
                    sl_ref * 0.85 if sl_ref else stake * reduce * 0.0042,
                    stake * reduce * float(de.get("sl_stake_pct") or 0.0042),
                )
                if tp_ref:
                    pos["tp_target_usd"] = tp_ref * 1.15
            elif de.get("trailing_enabled") and float(pos.get("max_unreal_seen") or 0) > stake * 0.004:
                trail = float(pos.get("max_unreal_seen") or unreal) * 0.55
                if unreal < trail and unreal > 0:
                    reason = "HUNTER_TRAIL"
        if mode_id == "sentinel" and pos.get("dynamic_exit") and not reason:
            de = pos.get("dynamic_exit") or {}
            partial_usd = float(pos.get("tp_partial_usd") or 0)
            sl_ref = float(pos.get("dynamic_sl_usd") or pos.get("sl_target_usd") or 0)
            tp_ref = float(pos.get("tp_target_usd") or 0)
            if (
                not pos.get("partial_tp_done")
                and partial_usd > 0
                and unreal >= partial_usd
            ):
                pos["partial_tp_done"] = True
                frac = float(de.get("partial_tp_frac") or 0.4)
                reduce = max(0.05, 1.0 - frac)
                pos["size"] = float(pos["size"]) * reduce
                pos["stake_usd"] = stake * reduce
                pos["dynamic_sl_usd"] = max(
                    sl_ref * 0.85 if sl_ref else stake * reduce * 0.0042,
                    stake * reduce * float(de.get("sl_stake_pct") or 0.0042),
                )
                if tp_ref:
                    pos["tp_target_usd"] = tp_ref * 1.12
            elif de.get("trailing_enabled") and float(pos.get("max_unreal_seen") or 0) > stake * 0.004:
                trail = float(pos.get("max_unreal_seen") or unreal) * 0.55
                if unreal < trail and unreal > 0:
                    reason = "SENTINEL_TRAIL"
        if not reason:
            tp_tgt, sl_tgt = stake_targets(stake, mode_id)
            if pos.get("tp_target_usd"):
                tp_tgt = float(pos["tp_target_usd"])
            if pos.get("dynamic_sl_usd"):
                sl_tgt = float(pos["dynamic_sl_usd"])
            elif pos.get("sl_target_usd"):
                sl_tgt = float(pos["sl_target_usd"])
            reason = evaluate_position_exit(
                opened_at=opened_at,
                unrealized_usd=unreal,
                tp_target_usd=tp_tgt,
                sl_target_usd=sl_tgt,
                stake_usd=stake,
                min_unreal_seen=float(pos.get("min_unreal_seen", unreal)),
                max_unreal_seen=float(pos.get("max_unreal_seen", unreal)),
                mode_id=mode_id,
                leverage=int(pos.get("leverage") or 5),
                entry_fee=float(pos.get("entry_fee") or 0) or None,
            )
        if reason:
            _close_shadow(mode_id, pos, reason, book)
            changed = True
    return changed


def entry_gate_for_mode(
    mode_id: str, signal: dict[str, Any]
) -> tuple[bool, str]:
    """Mod profil giriş filtresi (paper ile aynı mantık)."""
    from elite_trader.panel_strategy import is_live_binance_motor

    if mode_id == "mega":
        try:
            from elite_trader.mega_live import mega_live_orders_enabled, mega_sim_enabled

            if mega_sim_enabled() and not mega_live_orders_enabled():
                return _entry_allowed(mode_id, signal, execution_path="paper")
        except Exception:
            pass
    path = "live" if is_live_binance_motor(mode_id) else "paper"
    return _entry_allowed(mode_id, signal, execution_path=path)


def on_market_signal_for_mode(
    mode_id: str, signal: dict[str, Any], price: float
) -> None:
    """Tek mod — paper kitap (aktif Binance motoru hariç)."""
    from elite_trader.panel_strategy import live_only_execution

    if price <= 0 or is_live_binance_motor(mode_id) or live_only_execution():
        return
    st = _load()
    book = st["universes"].get(mode_id)
    if not book:
        return
    ok, reason = _entry_allowed(mode_id, signal, execution_path="paper")
    if not ok:
        return
    before = len(book["open"])
    _open_shadow(mode_id, signal, price, book)
    if len(book["open"]) > before:
        _save(st)


def on_market_signal(
    signal: dict[str, Any],
    price: float,
    *,
    deadline: float | None = None,
) -> None:
    """Ham momentum — tüm modlar paper (aktif Binance motoru hariç)."""
    from elite_trader.panel_strategy import live_only_execution

    if live_only_execution() or price <= 0:
        return
    mode_budget = _paper_mode_budget_sec()
    st = _load()
    dirty = False
    for mid in paper_mode_ids():
        if deadline is not None and time.time() >= deadline:
            break
        if is_live_binance_motor(mid):
            continue
        mode_deadline = (
            min(deadline, time.time() + mode_budget)
            if deadline is not None
            else None
        )
        if mode_deadline is not None and time.time() >= mode_deadline:
            break
        book = st["universes"][mid]
        ok, reason = _entry_allowed(mid, signal, execution_path="paper")
        if not ok:
            continue
        before = len(book["open"])
        _open_shadow(mid, signal, price, book)
        if len(book["open"]) > before:
            dirty = True
    if dirty:
        _save(st)
        cb = _on_paper_open_cb
        if cb:
            try:
                cb()
            except Exception:
                pass


# ── Paper sinyal kuyruğu (motor hot path bloklanmaz) ─────────────────────
_paper_pending_lock = threading.Lock()
_paper_pending: dict[str, tuple[dict[str, Any], float]] = {}
_paper_signal_wake = threading.Event()
_paper_worker_stop = threading.Event()
_paper_worker_thread: threading.Thread | None = None
_paper_signals_enqueued: int = 0
_paper_signals_processed: int = 0
_paper_signals_timed_out: int = 0
_on_paper_open_cb: Callable[[], None] | None = None

# Kapanış yan etkileri (DB, öğrenme) — pozisyon fiyat hot path bloklanmaz
_close_fx_queue: queue.SimpleQueue = queue.SimpleQueue()
_close_fx_stop = threading.Event()
_close_fx_thread: threading.Thread | None = None


def _run_close_side_effects(
    mode_id: str, closed: dict[str, Any], book_closed: list[dict[str, Any]] | None = None
) -> None:
    hist = book_closed or []
    if mode_id == "berserk2":
        try:
            from elite_trader.berserk2_cooldown import record_close
            from elite_trader.berserk_fee_survival import record_trade_close
            from elite_trader.berserk_reentry import record_close_result

            record_close(closed.get("symbol"))
            record_trade_close(closed)
            record_close_result(
                str(closed.get("symbol") or ""),
                str(closed.get("side") or "LONG"),
                exit_reason=str(closed.get("exit_reason") or ""),
                pnl=float(closed.get("final_pnl") or 0),
                profile=mode_catalog().get(mode_id) or {},
            )
        except Exception:
            pass
    elif mode_id == "berserk":
        try:
            from elite_trader.berserk_cooldown import record_close
            from elite_trader.berserk_fee_survival import record_trade_close
            from elite_trader.berserk_learning import on_berserk_trade_closed
            from elite_trader.berserk_reentry import record_close_result

            record_close(closed.get("symbol"))
            record_trade_close(closed)
            record_close_result(
                str(closed.get("symbol") or ""),
                str(closed.get("side") or "LONG"),
                exit_reason=str(closed.get("exit_reason") or ""),
                pnl=float(closed.get("final_pnl") or 0),
                profile=mode_catalog().get("berserk") or {},
            )
            on_berserk_trade_closed(closed, hist)
        except Exception:
            pass
    if mode_id == "hunter":
        try:
            from elite_trader.hunter_cooldown import record_close
            from elite_trader.hunter_learning import on_hunter_trade_closed

            fake = "fake" in str(closed.get("exit_reason") or "").lower()
            row = dict(closed)
            row["fake_breakout_result"] = fake
            record_close(closed.get("symbol"), fake_breakout=fake)
            on_hunter_trade_closed(row, hist)
        except Exception:
            pass
    if mode_id == "chop_master":
        try:
            from elite_trader.chop_cooldown import record_close
            from elite_trader.chop_learning import on_chop_trade_closed

            record_close(closed.get("symbol"))
            on_chop_trade_closed(closed, hist)
        except Exception:
            pass
    if mode_id == "sentinel":
        try:
            from elite_trader.sentinel_cooldown import record_close
            from elite_trader.sentinel_learning import on_trade_closed

            record_close(closed.get("symbol"))
            on_trade_closed(hist)
        except Exception:
            pass
    try:
        from elite_trader.data_lake.ingest import ingest_paper_trade

        ingest_paper_trade(mode_id, closed, closing=True)
    except Exception:
        pass
    try:
        from elite_trader.evrim_cross_mode_learner import observe_mode_trade_closed

        observe_mode_trade_closed(mode_id, closed)
    except Exception:
        pass


def _close_fx_worker() -> None:
    while not _close_fx_stop.is_set():
        try:
            item = _close_fx_queue.get(timeout=0.12)
        except Exception:
            continue
        try:
            if len(item) == 3:
                mode_id, closed, hist = item
            else:
                mode_id, closed = item
                hist = []
            _run_close_side_effects(mode_id, closed, hist)
        except Exception:
            pass


def start_close_fx_worker() -> None:
    global _close_fx_thread
    if _close_fx_thread and _close_fx_thread.is_alive():
        return
    _close_fx_stop.clear()
    _close_fx_thread = threading.Thread(
        target=_close_fx_worker, name="paper-close-fx", daemon=True
    )
    _close_fx_thread.start()


def stop_close_fx_worker() -> None:
    _close_fx_stop.set()
    if _close_fx_thread and _close_fx_thread.is_alive():
        _close_fx_thread.join(timeout=2.0)


def _paper_signal_budget_sec() -> float:
    try:
        ms = float(os.getenv("ELITE_PAPER_SIGNAL_BUDGET_MS", "150"))
    except ValueError:
        ms = 150.0
    return max(0.05, min(0.5, ms / 1000.0))


def _paper_mode_budget_sec() -> float:
    try:
        ms = float(os.getenv("ELITE_PAPER_MODE_BUDGET_MS", "35"))
    except ValueError:
        ms = 35.0
    return max(0.01, min(0.2, ms / 1000.0))


def set_paper_open_callback(cb: Callable[[], None] | None) -> None:
    global _on_paper_open_cb
    _on_paper_open_cb = cb


def enqueue_market_signal(signal: dict[str, Any], price: float) -> None:
    """Motor → paper: anında döner; giriş kapıları arka plan worker'da."""
    from elite_trader.panel_strategy import live_only_execution

    if live_only_execution() or price <= 0:
        return
    sym = str(signal.get("symbol") or "")
    direction = str(signal.get("type") or "LONG")
    key = f"{sym}:{direction}"
    global _paper_signals_enqueued
    with _paper_pending_lock:
        _paper_pending[key] = (dict(signal), float(price))
        _paper_signals_enqueued += 1
    _paper_signal_wake.set()


def _paper_signal_worker() -> None:
    global _paper_signals_processed, _paper_signals_timed_out, _paper_pending
    while not _paper_worker_stop.is_set():
        if not _paper_signal_wake.wait(timeout=0.05):
            continue
        _paper_signal_wake.clear()
        batch: dict[str, tuple[dict[str, Any], float]] = {}
        with _paper_pending_lock:
            if _paper_pending:
                batch = dict(_paper_pending)
                _paper_pending.clear()
        for _key, (sig, px) in batch.items():
            if _paper_worker_stop.is_set():
                break
            deadline = time.time() + _paper_signal_budget_sec()
            try:
                on_market_signal(sig, px, deadline=deadline)
                _paper_signals_processed += 1
                if time.time() > deadline:
                    _paper_signals_timed_out += 1
            except Exception:
                pass


def start_paper_signal_worker() -> None:
    global _paper_worker_thread
    from elite_trader.panel_strategy import live_only_execution

    if live_only_execution():
        return
    start_close_fx_worker()
    if _paper_worker_thread and _paper_worker_thread.is_alive():
        return
    _paper_worker_stop.clear()
    _paper_worker_thread = threading.Thread(
        target=_paper_signal_worker, name="paper-signal", daemon=True
    )
    _paper_worker_thread.start()


def stop_paper_signal_worker() -> None:
    _paper_worker_stop.set()
    _paper_signal_wake.set()
    if _paper_worker_thread and _paper_worker_thread.is_alive():
        _paper_worker_thread.join(timeout=2.0)
    stop_close_fx_worker()


def paper_signal_stats() -> dict[str, Any]:
    with _paper_pending_lock:
        pending = len(_paper_pending)
    alive = bool(_paper_worker_thread and _paper_worker_thread.is_alive())
    return {
        "pending": pending,
        "enqueued": _paper_signals_enqueued,
        "processed": _paper_signals_processed,
        "timed_out": _paper_signals_timed_out,
        "worker_alive": alive,
    }


def tick_prices(prices: dict[str, float], *, check_exits: bool = True) -> None:
    """Fiyat güncellemesi + moda özel çıkışlar (5 mod, motor hariç)."""
    from elite_trader.panel_strategy import live_only_execution

    if live_only_execution() or not prices:
        return
    patch_open_prices(prices)
    if check_exits:
        check_paper_exits(prices)


def check_paper_exits(
    prices: dict[str, float],
    *,
    deadline: float | None = None,
) -> bool:
    """Paper TP/SL — fiyat patch sonrası; deadline ile bütçeli."""
    if not prices:
        return False
    st = _load()
    dirty = False
    with _state_lock:
        for mid in paper_mode_ids():
            if is_live_binance_motor(mid):
                continue
            if deadline is not None and time.time() >= deadline:
                break
            book = st["universes"][mid]
            if not book.get("open"):
                continue
            if _tick_book(mid, book, prices, check_exits=True):
                dirty = True
    if dirty:
        _save(st)
    return dirty


def open_position_coins() -> list[str]:
    """Açık paper pozisyon coinleri — önbellekten hızlı okuma."""
    global _state_cache
    if _state_cache is not None:
        coins: set[str] = set()
        from elite_trader.mode_registry import enabled_mode_ids

        for mid in enabled_mode_ids():
            for p in _state_cache.get("universes", {}).get(mid, {}).get("open") or []:
                sym = str(p.get("symbol") or "")
                if sym:
                    coins.add(sym.replace("USDT", ""))
        return sorted(coins)
    st = _load()
    coins: set[str] = set()
    from elite_trader.mode_registry import enabled_mode_ids

    for mid in enabled_mode_ids():
        for p in st["universes"][mid].get("open") or []:
            sym = str(p.get("symbol") or "")
            if sym:
                coins.add(sym.replace("USDT", ""))
    return sorted(coins)


def patch_open_prices(prices: dict[str, float]) -> None:
    """Paper açık pozisyon fiyatları — bellek içi, disk/çıkış yok."""
    if not prices:
        return
    st = _load()
    with _state_lock:
        for mid in paper_mode_ids():
            if is_live_binance_motor(mid):
                continue
            book = st["universes"][mid]
            for pos in book.get("open") or []:
                sym = str(pos.get("symbol") or "")
                coin = sym.replace("USDT", "")
                px = float(prices.get(coin) or prices.get(sym) or 0)
                if px <= 0:
                    continue
                pos["current_price"] = px
                pos["price_updated_at"] = time.time()
                ep = float(pos.get("entry_price") or px)
                size = float(pos.get("size") or 0)
                if size > 0:
                    if str(pos.get("side") or "LONG") == "LONG":
                        pos["unrealized_pnl"] = (px - ep) * size
                    else:
                        pos["unrealized_pnl"] = (ep - px) * size
                    stake = max(float(pos.get("stake_usd") or 1), 0.01)
                    pos["pnl_pct"] = float(pos["unrealized_pnl"]) / stake * 100


def open_positions_monitor(mode_id: str | None = None) -> list[dict[str, Any]]:
    """Açık paper pozisyonlar — bellek içi fiyat yaşı (disk değil)."""
    now = time.time()
    st = _load()
    rows: list[dict[str, Any]] = []
    mids = [mode_id] if mode_id else list(paper_mode_ids())
    for mid in mids:
        if is_live_binance_motor(mid):
            continue
        for pos in st.get("universes", {}).get(mid, {}).get("open") or []:
            upd = float(pos.get("price_updated_at") or 0)
            rows.append(
                {
                    "mode_id": mid,
                    "id": pos.get("id"),
                    "symbol": pos.get("symbol"),
                    "side": pos.get("side"),
                    "entry_price": pos.get("entry_price"),
                    "current_price": pos.get("current_price"),
                    "unrealized_pnl": pos.get("unrealized_pnl"),
                    "pnl_pct": pos.get("pnl_pct"),
                    "price_updated_at": upd if upd > 0 else None,
                    "price_age_ms": round((now - upd) * 1000, 1) if upd > 0 else None,
                }
            )
    return rows


def open_counts_by_mode() -> dict[str, int]:
    """Açık paper/live kitap sayıları — status şeridi için hafif."""
    st = _load()
    return {
        mid: len(st["universes"].get(mid, {}).get("open") or [])
        for mid in all_mode_ids()
    }


def get_books() -> dict[str, dict[str, Any]]:
    st = _load()
    with _state_lock:
        return {mid: deepcopy(st["universes"][mid]) for mid in all_mode_ids()}


def get_universe_book(mode_id: str) -> dict[str, Any]:
    mid = mode_id if mode_id in all_mode_ids() else DEFAULT_ACTIVE_FUTURES_MODE
    st = _load()
    with _state_lock:
        return deepcopy(st["universes"].get(mid, _empty_book()))


def all_universe_books() -> dict[str, dict[str, Any]]:
    st = _load()
    with _state_lock:
        return {mid: st["universes"].get(mid, _empty_book()) for mid in all_mode_ids()}


def record_live_open(mode_id: str, position: dict[str, Any]) -> None:
    """Binance motor açılışını ilgili mod kitabına yaz."""
    st = _load()
    book = st["universes"].setdefault(mode_id, _empty_book())
    row = dict(position)
    row["panel_mode"] = mode_id
    row["universe_id"] = mode_id
    row["execution_mode_at_open"] = mode_id
    row["on_exchange"] = bool(row.get("on_exchange"))
    sym = row.get("symbol")
    book["open"] = [
        p for p in book["open"]
        if not (p.get("symbol") == sym and p.get("side") == row.get("side"))
    ]
    book["open"].append(row)
    _save(st)


def record_live_close(mode_id: str, closed: dict[str, Any]) -> None:
    """Binance motor kapanışını ilgili mod kitabına yaz."""
    st = _load()
    book = st["universes"].setdefault(mode_id, _empty_book())
    row = dict(closed)
    row["panel_mode"] = mode_id
    row["universe_id"] = mode_id
    row["execution_mode_at_close"] = mode_id
    pid = row.get("id")
    book["open"] = [p for p in book["open"] if p.get("id") != pid]
    book["closed"].append(row)
    if len(book["closed"]) > 800:
        book["closed"] = book["closed"][-800:]
    _save(st)


def _closed_row_matches(
    row: dict[str, Any],
    trade_id: int,
    *,
    symbol: str | None = None,
    exit_time: str | None = None,
) -> bool:
    if int(row.get("id") or -1) != int(trade_id):
        return False
    if symbol and str(row.get("symbol") or "").upper() != str(symbol).upper():
        return False
    if exit_time:
        et = str(row.get("exit_time") or row.get("closed_at") or "")
        if et != str(exit_time):
            return False
    return True


def remove_closed_trade(
    trade_id: int,
    *,
    mode_id: str | None = None,
    symbol: str | None = None,
    exit_time: str | None = None,
) -> bool:
    """Paralel kitaptan tek kapanmış işlem satırını kaldır."""
    st = _load()
    universes = st.get("universes") or {}
    mids = [mode_id] if mode_id else list(universes.keys())
    removed = False
    for mid in mids:
        book = universes.get(mid)
        if not isinstance(book, dict):
            continue
        closed = list(book.get("closed") or [])
        new_closed = [
            c
            for c in closed
            if not _closed_row_matches(
                c, trade_id, symbol=symbol, exit_time=exit_time
            )
        ]
        if len(new_closed) != len(closed):
            book["closed"] = new_closed
            universes[mid] = book
            removed = True
    if removed:
        st["universes"] = universes
        _save(st)
    return removed


def clear_paper_open_positions(*, mode_id: str | None = None) -> int:
    """Live-only — paper/gölge açık pozisyonları kitaptan temizle."""
    st = _load()
    cleared = 0
    mids = [mode_id] if mode_id else list(all_mode_ids())
    for mid in mids:
        book = st["universes"].setdefault(mid, _empty_book())
        n = len(book.get("open") or [])
        if n:
            book["open"] = []
            cleared += n
    if cleared:
        _save(st)
        _flush_if_needed(force=True)
    return cleared


def reconcile_books_with_exchange(
    exchange_list: list[dict[str, Any]],
    *,
    mode_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Canlı motor kitabı — yalnızca borsada olan açık pozisyonları tut.
    Borsada kapalı / hayalet satırları kitaptan sil (panel sayısı = Binance).
    """
    from elite_trader.exchange_position_sync import exchange_map_by_symbol_side
    from elite_trader.panel_strategy import active_execution_mode, is_live_binance_motor

    mid = mode_id or active_execution_mode()
    if not is_live_binance_motor(mid):
        return {"skipped": True, "mode_id": mid}

    emap = exchange_map_by_symbol_side(exchange_list or [])
    st = _load()
    book = st["universes"].setdefault(mid, _empty_book())
    before_n = len(book.get("open") or [])
    removed: list[str] = []
    kept: list[dict[str, Any]] = []
    for p in list(book.get("open") or []):
        sym = str(p.get("symbol") or "").upper()
        side = str(p.get("side") or "LONG").upper()
        if not sym:
            continue
        key = (sym, side)
        on_ex = bool(p.get("on_exchange") or p.get("exchange_synced"))
        # Canlı motor: kitap = borsa (hayalet satır kalmasın)
        if key not in emap and (on_ex or is_live_binance_motor(mid)):
            removed.append(f"{sym}:{side}")
            continue
        kept.append(p)

    changed = len(removed) > 0 or len(kept) != len(book.get("open") or [])
    if changed or force:
        book["open"] = kept
        _save(st)

    return {
        "mode_id": mid,
        "exchange_open": len(emap),
        "book_open_before": before_n,
        "book_open_after": len(kept),
        "removed": removed,
    }


def reset_mode_session(
    mode_id: str,
    *,
    session_start: float | None = None,
    clear_closed: bool = True,
) -> dict[str, Any]:
    """Motor oturumu: açıkları sil, bakiyeyi profile göre sıfırla."""
    mid = mode_id if mode_id in all_mode_ids() else DEFAULT_ACTIVE_FUTURES_MODE
    st = _load()
    old = st["universes"].get(mid) or {}
    o_n = len(old.get("open") or [])
    c_n = len(old.get("closed") or []) if clear_closed else 0
    ss = float(session_start or _mode_session_start(st, mid))
    st["universes"][mid] = _empty_book(ss)
    if not clear_closed and old.get("closed"):
        st["universes"][mid]["closed"] = list(old["closed"])
    st.setdefault("starting_capital_by_mode", {})[mid] = ss
    _save(st)
    return {
        "mode_id": mid,
        "cleared_open": o_n,
        "cleared_closed": len(old.get("closed") or []) if clear_closed else 0,
        "session_start": ss,
    }


def reset_mode_book(mode_id: str) -> dict[str, Any]:
    """Tek mod kitabını sıfırla (ayar dosyalarına dokunmaz)."""
    mid = mode_id if mode_id in all_mode_ids() else DEFAULT_ACTIVE_FUTURES_MODE
    st = _load()
    old = st["universes"].get(mid) or {}
    o_n = len(old.get("open") or [])
    c_n = len(old.get("closed") or [])
    ss = _mode_session_start(st, mid)
    st["universes"][mid] = _empty_book(ss)
    _save(st)
    return {
        "mode_id": mid,
        "cleared_open": o_n,
        "cleared_closed": c_n,
        "session_start": ss,
    }


def clear_mode_closed_trades(mode_id: str) -> dict[str, Any]:
    """Yalnızca kapanmış işlemleri sil — açık pozisyonlar kalır."""
    mid = mode_id if mode_id in all_mode_ids() else DEFAULT_ACTIVE_FUTURES_MODE
    st = _load()
    book = st["universes"].setdefault(mid, _empty_book(_mode_session_start(st, mid)))
    n = len(book.get("closed") or [])
    book["closed"] = []
    _save(st)
    return {
        "mode_id": mid,
        "cleared_closed": n,
        "open_kept": len(book.get("open") or []),
    }


def set_mode_session_start(mode_id: str, capital: float) -> None:
    if capital <= 0:
        return
    st = _load()
    st.setdefault("starting_capital_by_mode", {})[mode_id] = round(capital, 2)
    book = st["universes"].setdefault(mode_id, _empty_book(capital))
    book["session_start"] = round(capital, 2)
    _save(st)


def migrate_legacy_live_trades(
    *,
    open_positions: list[dict[str, Any]] | None = None,
    closed_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tek seferlik: global canlı listeleri panel_mode kitaplarına dağıt."""
    from elite_trader.panel_strategy import resolve_mode_id

    st = _load()
    moved_o = moved_c = 0
    if open_positions:
        for pos in open_positions:
            mid = resolve_mode_id(
                str(pos.get("panel_mode") or pos.get("execution_mode_at_open") or DEFAULT_ACTIVE_FUTURES_MODE)
            )
            book = st["universes"].setdefault(mid, _empty_book())
            if not any(
                p.get("id") == pos.get("id") for p in book["open"]
            ):
                book["open"].append(dict(pos))
                moved_o += 1
    if closed_rows:
        for row in closed_rows:
            mid = resolve_mode_id(
                str(
                    row.get("panel_mode")
                    or row.get("execution_mode_at_close")
                    or DEFAULT_ACTIVE_FUTURES_MODE
                )
            )
            book = st["universes"].setdefault(mid, _empty_book())
            cid = row.get("id")
            if not any(c.get("id") == cid for c in book["closed"]):
                book["closed"].append(dict(row))
                moved_c += 1
    _save(st)
    return {"moved_open": moved_o, "moved_closed": moved_c}


def build_summary(mode_id: str) -> dict[str, Any]:
    book = get_universe_book(mode_id)
    st = _load()
    session_start = _mode_session_start(st, mode_id)
    open_p = book["open"]
    closed_p = book["closed"]
    realized = sum(float(c.get("final_pnl") or 0) for c in closed_p)
    unreal = sum(float(p.get("unrealized_pnl") or 0) for p in open_p)
    total_pnl = realized + unreal
    balance = session_start + total_pnl
    open_stake = sum(float(p.get("stake_usd") or 0) for p in open_p)
    open_win = len([p for p in open_p if float(p.get("unrealized_pnl") or 0) > 0])
    open_loss = len([p for p in open_p if float(p.get("unrealized_pnl") or 0) <= 0])
    wins = len([c for c in closed_p if float(c.get("final_pnl") or 0) > 0])
    closed_n = len(closed_p)
    losses = max(0, closed_n - wins)
    wr = (wins / closed_n * 100.0) if closed_n else 0.0
    avail = round(balance - open_stake, 2)
    return {
        "starting_capital": round(session_start, 2),
        "current_capital": round(balance, 2),
        "session_total_balance": round(balance, 2),
        "session_available_est": avail,
        "available_capital": avail,
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unreal, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / session_start * 100.0, 2) if session_start else 0,
        "open_trades": len(open_p),
        "closed_trades": closed_n,
        "win_count": wins,
        "closed_losses": losses,
        "win_rate": round(wr, 1),
        "open_win": open_win,
        "open_loss": open_loss,
        "total_active_stake": round(open_stake, 2),
        "total_position_value": round(
            sum(
                float(p.get("position_value") or 0)
                or float(p.get("size") or 0) * float(p.get("current_price") or 0)
                for p in open_p
            ),
            2,
        ),
        "total_fees": round(sum(float(c.get("total_fees") or 0) for c in closed_p), 2),
        "total_taxes": round(sum(float(c.get("tax") or 0) for c in closed_p), 2),
    }


def sync_session_start(capital: float, mode_id: str | None = None) -> None:
    if capital <= 0:
        return
    st = _load()
    st["starting_capital"] = capital
    if mode_id:
        set_mode_session_start(mode_id, capital)
        return
    for mid in all_mode_ids():
        st.setdefault("starting_capital_by_mode", {})[mid] = capital
        st["universes"].setdefault(mid, _empty_book(capital))["session_start"] = capital
    _save(st)


def wipe_all_universes_fresh(capital: float) -> dict[str, Any]:
    """9005 tam sıfır — tüm mod kitapları + session başlangıç bakiyesi."""
    cap = round(max(float(capital), 1.0), 2)
    cleared = 0
    st = _load()
    for mid in all_mode_ids():
        book = (st.get("universes") or {}).get(mid) or {}
        cleared += len(book.get("closed") or []) + len(book.get("open") or [])
    st = _default_state()
    st["starting_capital"] = cap
    st["starting_capital_by_mode"] = {mid: cap for mid in all_mode_ids()}
    for mid in all_mode_ids():
        st["universes"][mid] = _empty_book(cap)
    st["updated_at"] = datetime.now(timezone.utc).isoformat()
    global _state_cache
    _state_cache = st
    _save(st)
    _flush_if_needed(force=True)
    return {
        "starting_capital": cap,
        "modes_reset": len(all_mode_ids()),
        "cleared_rows": cleared,
    }
