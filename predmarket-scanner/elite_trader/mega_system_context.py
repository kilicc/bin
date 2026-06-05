"""MEGA SystemContext — işlem yaşam döngüsü ölçümü (P0, karar mantığı değiştirmez)."""
from __future__ import annotations

import os
import time
from typing import Any


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def system_context_enabled() -> bool:
    return _env_bool("MEGA_SYSTEM_CONTEXT_ENABLED", True)


def _compact(obj: Any, *, max_str: int = 120) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _compact(v, max_str=max_str) for k, v in obj.items() if v is not None}
    if isinstance(obj, (list, tuple)):
        return [_compact(x, max_str=max_str) for x in obj[:24]]
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, str) and len(obj) > max_str:
        return obj[:max_str]
    return obj


def _reject_mix_top(limit: int = 4) -> list[dict[str, Any]]:
    try:
        from elite_trader.mode_reject_buffer import get_rejects

        rows = get_rejects("mega", limit=80)
    except Exception:
        return []
    if not rows:
        return []
    ctr: dict[str, int] = {}
    for r in rows:
        k = str(r.get("reason") or "unknown")
        ctr[k] = ctr.get(k, 0) + 1
    total = sum(ctr.values()) or 1
    ranked = sorted(ctr.items(), key=lambda x: -x[1])[: max(1, limit)]
    return [{"reason": k, "share": round(v / total, 3)} for k, v in ranked]


def _hub_mark_meta() -> dict[str, Any]:
    out: dict[str, Any] = {"source": None, "mark_lag_ms": None, "alive": False}
    try:
        from elite_trader.mega_async_hub import get_mega_hub, hub_marks_snapshot, mega_hub_enabled

        if not mega_hub_enabled():
            return out
        hub = get_mega_hub()
        if not hub:
            return out
        _, meta = hub_marks_snapshot(max_recv_age_sec=3.0)
        out["source"] = "mega_hub"
        out["alive"] = bool(meta.get("alive"))
        lag = meta.get("mark_lag_ms")
        if lag is not None:
            out["mark_lag_ms"] = round(float(lag), 1)
    except Exception:
        pass
    return out


def _motor_meta() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from elite_trader.runtime_status import read_heartbeat

        hb = read_heartbeat() or {}
        out["motor_eval_ms"] = hb.get("motor_eval_ms")
        out["fast_tick_ms"] = hb.get("fast_tick_ms")
        out["position_tick_ms"] = hb.get("position_tick_ms")
        mega = hb.get("mega") or {}
        if isinstance(mega, dict):
            for k in ("last_exit_tick_ms", "position_sync", "close_sync"):
                if mega.get(k) is not None:
                    out[k] = mega.get(k)
    except Exception:
        pass
    return out


def _btc_slice() -> dict[str, Any]:
    try:
        from elite_trader.berserk2_btc_context import get_btc_context

        btc = get_btc_context() or {}
    except Exception:
        return {}
    age = None
    try:
        u = float(btc.get("updated_at") or 0)
        if u > 0:
            age = round(max(0.0, time.time() - u), 1)
    except (TypeError, ValueError):
        pass
    return _compact(
        {
            "regime": btc.get("btc_regime"),
            "regime_base": btc.get("btc_regime_base"),
            "btc_price": btc.get("btc_price"),
            "btc_24h_change": btc.get("btc_24h_change"),
            "btc_book_imbalance": btc.get("btc_book_imbalance"),
            "btc_vol_spike": btc.get("btc_vol_spike"),
            "btc_vol_ratio": btc.get("btc_vol_ratio"),
            "btc_1m_wick_drop_pct": btc.get("btc_1m_wick_drop_pct"),
            "btc_1m_wick_pump_pct": btc.get("btc_1m_wick_pump_pct"),
            "context_age_sec": age,
        }
    )


def _market_regime_slice() -> dict[str, Any]:
    try:
        from elite_trader.mega_market_regime import snapshot as regime_snapshot

        r = regime_snapshot() or {}
    except Exception:
        return {}
    return _compact(
        {
            "regime": r.get("regime"),
            "regime_locked": r.get("regime_locked"),
            "transition_active": r.get("transition_active"),
            "transition_reason": r.get("transition_reason"),
            "reject_mix": r.get("reject_mix"),
        }
    )


def _signal_slice(signal: dict[str, Any] | None, pos: dict[str, Any] | None) -> dict[str, Any]:
    sig = dict(signal or {})
    p = pos or {}
    meta = sig.get("mega_meta") or {}
    return _compact(
        {
            "symbol": sig.get("symbol") or p.get("symbol"),
            "side": sig.get("type") or sig.get("side") or p.get("side"),
            "change": sig.get("change"),
            "strength": sig.get("strength") or p.get("signal_strength"),
            "mega_score": meta.get("mega_score"),
            "vol_tier": sig.get("mega_vol_tier") or meta.get("vol_tier"),
            "vol_rank": sig.get("mega_vol_rank") or meta.get("vol_rank"),
            "mover_rank": sig.get("berserk2_mover_rank"),
            "flash": bool(
                sig.get("mega_flash_reversal")
                or sig.get("flash_reversal")
                or p.get("mega_flash_reversal")
            ),
            "elite": bool(sig.get("mega_elite_entry") or p.get("mega_elite_entry")),
            "signal_source": p.get("signal_source"),
        }
    )


def _position_slice(pos: dict[str, Any] | None) -> dict[str, Any]:
    if not pos:
        return {}
    return _compact(
        {
            "id": pos.get("id"),
            "symbol": pos.get("symbol"),
            "side": pos.get("side"),
            "stake_usd": pos.get("stake_usd"),
            "leverage": pos.get("leverage"),
            "entry_price": pos.get("entry_price"),
            "pre_send_net": pos.get("pre_send_net"),
            "pre_send_gross": pos.get("pre_send_gross"),
            "max_unreal_seen": pos.get("max_unreal_seen"),
            "max_net_seen": pos.get("max_net_seen"),
            "demo_fast_close": pos.get("demo_fast_close"),
        }
    )


def _exec_slice(
    pos: dict[str, Any] | None,
    *,
    settlement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = pos or {}
    s = settlement or {}
    return _compact(
        {
            "pre_send_net": p.get("pre_send_net"),
            "pre_send_gross": p.get("pre_send_gross"),
            "wallet_pnl": s.get("wallet_pnl") or s.get("net_pnl") or s.get("final_pnl"),
            "pnl_gross": s.get("pnl_usd") or s.get("pnl_gross_usd"),
            "phantom_slippage": p.get("phantom_slippage"),
            "close_order_id": s.get("exchange_close_order_id") or p.get("exchange_close_order_id"),
        }
    )


def build_system_context(
    phase: str,
    *,
    signal: dict[str, Any] | None = None,
    pos: dict[str, Any] | None = None,
    exit_reason: str | None = None,
    settlement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    phase: entry | exit | close_attempt
    Önbellek okuma — ek REST yok (P0 sıcak yol güvenli).
    """
    if not system_context_enabled():
        return {}
    ts = time.time()
    ctx: dict[str, Any] = {
        "schema": "mega_system_context_v1",
        "phase": str(phase or "unknown"),
        "ts": ts,
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        "signal": _signal_slice(signal, pos),
        "btc": _btc_slice(),
        "market_regime": _market_regime_slice(),
        "system": _compact(
            {
                "reject_top": _reject_mix_top(),
                "hub": _hub_mark_meta(),
                "motor": _motor_meta(),
            }
        ),
        "position": _position_slice(pos),
        "exec": _exec_slice(pos, settlement=settlement),
    }
    if exit_reason:
        ctx["exit_reason"] = str(exit_reason)[:48]
    return ctx


def attach_entry_context(
    pos: dict[str, Any],
    *,
    signal: dict[str, Any] | None = None,
) -> None:
    snap = build_system_context("entry", signal=signal, pos=pos)
    if snap:
        pos["entry_context"] = snap
        pos["entry_context_ts"] = snap.get("ts")


def attach_exit_context(
    closed: dict[str, Any],
    *,
    pos: dict[str, Any] | None = None,
    exit_reason: str | None = None,
    settlement: dict[str, Any] | None = None,
) -> None:
    snap = build_system_context(
        "exit",
        pos=pos or closed,
        exit_reason=exit_reason or str(closed.get("exit_reason") or ""),
        settlement=settlement,
    )
    if snap:
        closed["exit_context"] = snap
        closed["exit_context_ts"] = snap.get("ts")
    if pos and pos.get("entry_context"):
        closed["entry_context"] = pos.get("entry_context")
