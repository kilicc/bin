"""Evrim V2 — birleşik giriş katmanı (meta + risk + recovery + exploration + execution)."""
from __future__ import annotations

from typing import Any

_last_meta: dict[str, Any] = {}
_last_risk: dict[str, Any] = {}


def last_v2_meta() -> dict[str, Any]:
    return dict(_last_meta)


def last_v2_risk() -> dict[str, Any]:
    return dict(_last_risk)


def _learning_log_fields() -> dict[str, Any]:
    out: dict[str, Any] = {
        "learning_blocks_trading": False,
        "trading_continues_during_learning": True,
    }
    try:
        from elite_trader.evrim_config_version import config_version_snapshot
        from elite_trader.evrim_learning_runtime import learning_snapshot

        ls = learning_snapshot()
        cv = config_version_snapshot()
        out.update(ls)
        out.update(cv)
    except Exception:
        pass
    return out


def _attach_log(payload: dict[str, Any], learning_fields: dict[str, Any]) -> dict[str, Any]:
    payload["learning"] = learning_fields
    return payload


def _record_v2(
    signal: dict[str, Any],
    allowed: bool,
    reason: str,
    payload: dict[str, Any],
    *,
    execution_path: str,
) -> None:
    try:
        from elite_trader.evrim_cross_strategy_lab import record_evrim_v2_decision

        record_evrim_v2_decision(signal, allowed, reason, payload, execution_path=execution_path)
    except Exception:
        pass


def run_evrim_v2_entry_checks(
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    *,
    execution_path: str = "paper",
    closed: list[dict[str, Any]] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    global _last_meta, _last_risk

    from elite_trader.evrim_config_version import get_trading_profile
    from elite_trader.evrim_execution_optimizer import choose_execution
    from elite_trader.evrim_exploration import assess_exploration, touch_reject
    from elite_trader.evrim_meta_score import compute_evrim_meta_score
    from elite_trader.evrim_recovery import maybe_enter_recovery
    from elite_trader.evrim_risk_governor import assess_evrim_risk

    trading_profile = get_trading_profile(profile)

    meta = compute_evrim_meta_score(
        signal,
        ctx,
        trading_profile,
        hybrid=signal.get("evrim_hybrid"),
        closed=closed,
    )
    recovery = maybe_enter_recovery(ctx, meta, trading_profile)
    score_boost = float(recovery.get("recovery_score_boost") or 0)
    in_recovery = bool(recovery.get("recovery_mode"))
    risk = assess_evrim_risk(
        signal,
        ctx,
        trading_profile,
        meta,
        execution_path=execution_path,
        recovery_score_boost=score_boost if in_recovery else 0.0,
        in_recovery=in_recovery,
    )
    exploration = assess_exploration(trading_profile)
    exec_plan = choose_execution(signal, ctx, meta, trading_profile)

    _last_meta = meta
    _last_risk = risk

    learning_fields = _learning_log_fields()
    payload = {
        "meta": meta,
        "risk": risk,
        "recovery": recovery,
        "exploration": exploration,
        "execution": exec_plan,
        "learning": learning_fields,
    }

    if exploration.get("exploration_mode") and execution_path == "live":
        touch_reject()
        out = False, "exploration_paper_only", _attach_log(payload, learning_fields)
        _record_v2(signal, out[0], out[1], payload, execution_path=execution_path)
        return out

    if risk.get("risk_veto"):
        touch_reject()
        reason = str(risk.get("risk_veto_reason") or "risk_veto")
        out = False, reason, _attach_log(payload, learning_fields)
        _record_v2(signal, out[0], out[1], payload, execution_path=execution_path)
        return out

    min_sc = float(trading_profile.get("evrim_v2_min_final_score") or 55)
    if exploration.get("exploration_mode"):
        paper_thr = float(exploration.get("exploration_paper_threshold") or min_sc - 5)
        if float(meta.get("final_score") or 0) < paper_thr and execution_path == "paper":
            touch_reject()
            out = False, "exploration_score_low", _attach_log(payload, learning_fields)
            _record_v2(signal, out[0], out[1], payload, execution_path=execution_path)
            return out

    if in_recovery:
        eff_min = float(risk.get("effective_min_final_score") or min_sc + score_boost)
        if float(meta.get("final_score") or 0) < eff_min:
            touch_reject()
            out = False, "recovery_score_low", _attach_log(payload, learning_fields)
            _record_v2(signal, out[0], out[1], payload, execution_path=execution_path)
            return out

    hybrid = signal.get("evrim_hybrid") or {}
    stake_mult = float(hybrid.get("stake_mult") or 1.0)
    stake_mult *= float(risk.get("risk_stake_mult") or 1.0)
    stake_mult *= float(recovery.get("recovery_stake_mult") or 1.0)
    hybrid["stake_mult"] = round(stake_mult, 4)
    signal["evrim_hybrid"] = hybrid
    signal["evrim_meta"] = meta
    signal["evrim_risk"] = risk
    signal["evrim_v2"] = payload
    signal["evrim_execution"] = exec_plan
    signal["evrim_learning"] = learning_fields
    out = True, "evrim_v2_pass", _attach_log(payload, learning_fields)
    _record_v2(signal, out[0], out[1], payload, execution_path=execution_path)
    return out


def evrim_v2_live_preflight(signal: dict[str, Any] | None) -> tuple[bool, str]:
    """Live Binance gönderimi öncesi — signal üzerindeki V2 risk snapshot."""
    if not signal:
        return True, ""
    risk = signal.get("evrim_risk") or _last_risk
    if risk.get("risk_veto"):
        return False, str(risk.get("risk_veto_reason") or "risk_veto")
    meta = signal.get("evrim_meta") or _last_meta
    if float(meta.get("expected_net_pnl_usd") or signal.get("expected_net_pnl") or 0) <= 0:
        exp = (signal.get("evrim_hybrid") or {}).get("expected_net_pnl_usd")
        if exp is not None and float(exp) <= 0:
            return False, "expected_net_negative"
    exploration = (signal.get("evrim_v2") or {}).get("exploration") or {}
    if exploration.get("exploration_mode"):
        return False, "exploration_paper_only"
    return True, ""
