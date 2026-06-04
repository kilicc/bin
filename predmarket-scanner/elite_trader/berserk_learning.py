"""Berserk paper öğrenme — 100 kapanış öneri; her 3 kapanışta −PnL autotune profil günceller."""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SUGGESTIONS_PATH = _ROOT / "data" / "berserk_learning_suggestions.json"
_INTERVAL = 100
_SL_AUTOTUNE_INTERVAL = 3


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def _duration(row: dict[str, Any]) -> float:
    return float(row.get("duration") or 0)


def _load() -> dict[str, Any]:
    if not _SUGGESTIONS_PATH.is_file():
        return {"trade_count_since": 0, "suggestions": {}}
    try:
        return json.loads(_SUGGESTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"trade_count_since": 0, "suggestions": {}}


def _save(data: dict[str, Any]) -> None:
    _SUGGESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _SUGGESTIONS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_suggestions(closed: list[dict[str, Any]]) -> dict[str, Any]:
    if not closed:
        return {}
    wins = [c for c in closed if _pnl(c) > 0]
    losses = [c for c in closed if _pnl(c) < 0]
    sym_pnl: dict[str, float] = defaultdict(float)
    strength_pnl: dict[str, float] = defaultdict(float)
    exit_reasons: Counter[str] = Counter()
    spread_levels: Counter[str] = Counter()
    stake_sources: Counter[str] = Counter()
    gross = sum(max(0.0, _pnl(c)) for c in closed)
    fees = sum(float(c.get("total_fees") or 0) for c in closed)
    durations = [_duration(c) for c in closed if _duration(c) > 0]
    t_span = max(1.0, (closed[-1].get("exit_time") or "") != "")
    first_ts = None
    last_ts = None
    for c in closed[-_INTERVAL:]:
        sym = str(c.get("symbol") or "")
        sym_pnl[sym] += _pnl(c)
        st = str(c.get("signal_strength") or "Medium")
        strength_pnl[st] += _pnl(c)
        exit_reasons[str(c.get("exit_reason") or "?")[:20]] += 1
        spread_levels[str(c.get("spread_risk_level") or "none")] += 1
        stake_sources[str(c.get("min_stake_source") or "?")] += 1
    best_sym = max(sym_pnl, key=sym_pnl.get) if sym_pnl else None
    worst_sym = min(sym_pnl, key=sym_pnl.get) if sym_pnl else None
    best_sig = max(strength_pnl, key=strength_pnl.get) if strength_pnl else None
    worst_sig = min(strength_pnl, key=strength_pnl.get) if strength_pnl else None
    avg_hold = sum(durations) / len(durations) if durations else 0.0
    wr = len(wins) / len(closed) if closed else 0.0
    avg_win = sum(_pnl(c) for c in wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(_pnl(c) for c in losses) / len(losses)) if losses else 0.0
    pf = gross / max(0.01, abs(sum(_pnl(c) for c in losses)))
    return {
        "suggested_min_move_pct": 0.09 if wr < 0.55 else 0.08,
        "suggested_min_score": 45 if wr >= 0.5 else 48,
        "suggested_tp_stake_pct": 0.0042,
        "suggested_sl_stake_pct": 0.0024,
        "suggested_spread_limit": 0.12,
        "best_symbols": sorted(sym_pnl, key=sym_pnl.get, reverse=True)[:5],
        "worst_symbols": sorted(sym_pnl, key=sym_pnl.get)[:5],
        "best_micro_signal": best_sig,
        "worst_micro_signal": worst_sig,
        "fee_damage_score": round(fees / max(0.01, gross + fees), 4) if gross else 0.0,
        "spread_damage_score": round(
            exit_reasons.get("berserk_spread_extreme", 0) / max(1, len(closed)), 4
        ),
        "slippage_damage_score": 0.0,
        "avg_hold_seconds": round(avg_hold, 1),
        "trades_per_minute": round(len(closed) / max(1.0, avg_hold / 60.0 * len(closed)), 4),
        "confidence": round(min(1.0, len(closed) / 200.0), 2),
        "win_rate": round(wr * 100, 1),
        "profit_factor": round(pf, 3),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "exit_reasons": dict(exit_reasons),
        "spread_risk_distribution": dict(spread_levels),
        "min_stake_source_distribution": dict(stake_sources),
    }


def _window_row(closed: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": closed.get("symbol"),
        "exit_reason": closed.get("exit_reason"),
        "final_pnl": _pnl(closed),
        "duration": _duration(closed),
        "max_unreal_seen": float(closed.get("max_unreal_seen") or 0),
        "min_unreal_seen": float(closed.get("min_unreal_seen") or 0),
        "stake_usd": float(closed.get("stake_usd") or 120),
        "leverage": int(closed.get("leverage") or 5),
        "total_fees": float(closed.get("total_fees") or 0),
    }


def on_berserk_trade_closed(closed: dict[str, Any], book_closed: list[dict[str, Any]]) -> None:
    st = _load()
    n = int(st.get("trade_count_since") or 0) + 1
    st["trade_count_since"] = n
    st["last_closed"] = {
        "symbol": closed.get("symbol"),
        "pnl": round(_pnl(closed), 4),
        "reason": closed.get("exit_reason"),
    }
    window: list[dict[str, Any]] = list(st.get("recent_closed_window") or [])
    window.append(_window_row(closed))
    if len(window) > 12:
        window = window[-12:]
    st["recent_closed_window"] = window

    if n % _SL_AUTOTUNE_INTERVAL == 0:
        try:
            from elite_trader.berserk_sl_autotune import apply_berserk_sl_autotune

            tune = apply_berserk_sl_autotune(window, book_closed, trade_n=n)
            hist = list(st.get("sl_autotune_history") or [])
            hist.append(tune)
            st["sl_autotune_history"] = hist[-20:]
            st["last_sl_autotune"] = tune
            st["next_sl_autotune_at"] = n + _SL_AUTOTUNE_INTERVAL
        except Exception as exc:
            st["last_sl_autotune_error"] = str(exc)[:200]

    if n >= _INTERVAL and n % _INTERVAL == 0:
        st["suggestions"] = _build_suggestions(book_closed[-_INTERVAL:])
        st["suggestion_at_trade"] = n
    _save(st)


def get_suggestions() -> dict[str, Any]:
    data = _load()
    n = int(data.get("trade_count_since") or 0)
    rem = n % _SL_AUTOTUNE_INTERVAL
    next_sl_in = _SL_AUTOTUNE_INTERVAL if rem == 0 else _SL_AUTOTUNE_INTERVAL - rem
    return {
        "berserk_learning_suggestions": data.get("suggestions") or {},
        "trade_count_since": n,
        "next_suggestion_at": (
            ((_INTERVAL - (n % _INTERVAL)) % _INTERVAL) or _INTERVAL
        ),
        "sl_autotune_interval": _SL_AUTOTUNE_INTERVAL,
        "next_sl_autotune_at": n + next_sl_in,
        "last_sl_autotune": data.get("last_sl_autotune"),
        "updated_at": data.get("updated_at"),
    }
