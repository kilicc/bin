"""Berserk V2 — momentum re-entry with revenge guard."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "berserk_reentry_state.json"

_symbol_state: dict[str, dict[str, Any]] = {}
_reentry_attempts = 0
_reentry_success = 0
_ban_until: dict[str, float] = {}


def _load() -> None:
    global _symbol_state, _reentry_attempts, _reentry_success
    if not _STATE_PATH.is_file():
        return
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        _symbol_state = dict(data.get("symbols") or {})
        _reentry_attempts = int(data.get("reentry_attempts") or 0)
        _reentry_success = int(data.get("reentry_success") or 0)
    except Exception:
        pass


def _save() -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(
            {
                "symbols": _symbol_state,
                "reentry_attempts": _reentry_attempts,
                "reentry_success": _reentry_success,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


_load()


def record_close_result(
    symbol: str,
    side: str,
    *,
    exit_reason: str,
    pnl: float,
    profile: dict[str, Any],
) -> None:
    sym = str(symbol or "").upper()
    if not sym:
        return
    won = pnl > 0
    prev = _symbol_state.get(sym) or {}
    fail_streak = int(prev.get("fail_streak") or 0)
    if won or "TP" in str(exit_reason).upper() or "SPIKE" in str(exit_reason).upper():
        fail_streak = 0
    elif "SL" in str(exit_reason).upper() or pnl < 0:
        fail_streak += 1
    max_fail = int(profile.get("berserk_reentry_max_failures") or 3)
    ban_min = float(profile.get("berserk_reentry_ban_min") or 3.0)
    if fail_streak >= max_fail:
        _ban_until[sym] = time.time() + ban_min * 60.0
        fail_streak = 0
    _symbol_state[sym] = {
        "last_side": str(side).upper(),
        "last_exit_reason": str(exit_reason or "")[:32],
        "last_pnl": round(pnl, 4),
        "last_won": won,
        "fail_streak": fail_streak,
        "closed_at": time.time(),
    }
    _save()


def _momentum_continuation(signal: dict[str, Any], ctx: dict[str, Any], side: str) -> float:
    score = float(signal.get("berserk_score") or (signal.get("berserk_meta") or {}).get("berserk_score") or 0)
    vr = float(ctx.get("vol_ratio") or signal.get("vol_ratio") or 1.0)
    ob = float(ctx.get("orderbook_pressure") or signal.get("orderbook_pressure") or 0)
    ch = float(signal.get("change") or 0)
    aligned = (ch > 0 and side == "LONG") or (ch < 0 and side == "SHORT")
    m = score * 0.5
    if vr >= 1.15:
        m += 8
    if aligned and ob != 0:
        m += min(12.0, abs(ob) * 15)
    return m


def evaluate_reentry(
    symbol: str,
    side: str,
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    global _reentry_attempts, _reentry_success
    sym = str(symbol or "").upper()
    side_u = str(side or "LONG").upper()
    meta: dict[str, Any] = {"reentry_attempt": False}

    ban_ts = _ban_until.get(sym, 0)
    if ban_ts > time.time():
        rem = ban_ts - time.time()
        meta["reentry_fail_reason"] = "reentry_symbol_ban"
        meta["reentry_ban_remaining_sec"] = round(rem, 1)
        return False, "reentry_symbol_ban", meta

    prev = _symbol_state.get(sym)
    if not prev:
        return True, "", meta

    last_side = str(prev.get("last_side") or "")
    last_reason = str(prev.get("last_exit_reason") or "")
    last_won = bool(prev.get("last_won"))
    closed_at = float(prev.get("closed_at") or 0)
    age = time.time() - closed_at if closed_at else 9999.0

    if age > 120:
        return True, "", meta

    if last_side == side_u and not last_won and "SL" in last_reason.upper():
        _reentry_attempts += 1
        meta["reentry_attempt"] = True
        norm = float(profile.get("berserk_normal_score") or 60)
        cont = _momentum_continuation(signal, ctx, side_u)
        meta["momentum_continuation_score"] = round(cont, 2)
        if float(signal.get("berserk_score") or 0) < norm and cont < norm:
            meta["reentry_fail_reason"] = "revenge_trading_blocked"
            return False, "revenge_trading_blocked", meta
        if float(signal.get("expected_net_pnl") or (signal.get("berserk_meta") or {}).get("expected_net_pnl_usd") or 0) <= 0:
            meta["reentry_fail_reason"] = "reentry_expected_net_negative"
            return False, "reentry_expected_net_negative", meta
        _reentry_success += 1
        meta["reentry_success"] = True
        _save()

    return True, "", meta


def reentry_stats() -> dict[str, Any]:
    return {
        "reentry_count": _reentry_attempts,
        "reentry_success_count": _reentry_success,
    }


def reset_reentry_state() -> None:
    global _symbol_state, _reentry_attempts, _reentry_success, _ban_until
    _symbol_state.clear()
    _ban_until.clear()
    _reentry_attempts = 0
    _reentry_success = 0
    if _STATE_PATH.is_file():
        _STATE_PATH.unlink(missing_ok=True)
