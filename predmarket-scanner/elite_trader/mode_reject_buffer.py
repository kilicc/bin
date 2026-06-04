"""Per-mode reject ring buffer (500) — unified reject telemetry."""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.mode_registry import MODE_IDS, resolve_mode_id

_ROOT = Path(__file__).resolve().parent.parent
_BUF_DIR = _ROOT / "data" / "mode_reject_buffers"
_MAX = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(mode_id: str) -> Path:
    mid = resolve_mode_id(mode_id)
    return _BUF_DIR / f"{mid}.json"


def _load(mode_id: str) -> dict[str, Any]:
    p = _path(mode_id)
    if not p.is_file():
        return {"mode_id": resolve_mode_id(mode_id), "rejects": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"mode_id": resolve_mode_id(mode_id), "rejects": []}


def _save(mode_id: str, data: dict[str, Any]) -> None:
    _BUF_DIR.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    _path(mode_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_reject(mode_id: str, row: dict[str, Any]) -> None:
    mid = resolve_mode_id(mode_id)
    data = _load(mid)
    rejects: list[dict[str, Any]] = list(data.get("rejects") or [])
    entry = {
        "timestamp": row.get("timestamp") or _now_iso(),
        "ts": row.get("ts") or time.time(),
        "mode_id": mid,
        "symbol": row.get("symbol"),
        "reason": str(row.get("reason") or "unknown")[:120],
        "score": row.get("score"),
        "spread": row.get("spread"),
        "expected_net_pnl": row.get("expected_net_pnl"),
        "market_regime": row.get("market_regime"),
        "strength": row.get("strength"),
        "execution_path": row.get("execution_path", "paper"),
        "key_engine_score": row.get("key_engine_score") or {},
    }
    rejects.append(entry)
    if len(rejects) > _MAX:
        rejects = rejects[-_MAX:]
    data["rejects"] = rejects
    data["total_appended"] = int(data.get("total_appended") or 0) + 1
    _save(mid, data)


def get_rejects(mode_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    data = _load(mode_id)
    rejects = list(data.get("rejects") or [])
    rejects.reverse()
    return rejects[: max(1, min(limit, _MAX))]


def top_reasons(mode_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    data = _load(mode_id)
    c: Counter[str] = Counter()
    for r in data.get("rejects") or []:
        c[str(r.get("reason") or "unknown")[:64]] += 1
    return [{"reason": k, "count": v} for k, v in c.most_common(limit)]


def summary(mode_id: str) -> dict[str, Any]:
    data = _load(mode_id)
    rejects = list(data.get("rejects") or [])
    return {
        "mode_id": resolve_mode_id(mode_id),
        "reject_count": len(rejects),
        "total_appended": int(data.get("total_appended") or len(rejects)),
        "top_reject_reasons": top_reasons(mode_id),
        "last_20_rejects": get_rejects(mode_id, limit=20),
        "updated_at": data.get("updated_at"),
    }


def clear_mode(mode_id: str) -> bool:
    """Oturum sıfırlama — red telemetrisini temizle."""
    mid = resolve_mode_id(mode_id)
    p = _path(mid)
    if p.is_file():
        p.unlink()
        return True
    return False


def all_summaries() -> dict[str, Any]:
    return {mid: summary(mid) for mid in MODE_IDS}


def build_reject_row(
    mode_id: str,
    signal: dict[str, Any],
    reason: str,
    *,
    execution_path: str = "paper",
) -> dict[str, Any]:
    mid = resolve_mode_id(mode_id)
    meta = (
        signal.get("hunter_meta")
        or signal.get("chop_meta")
        or signal.get("sentinel_meta")
        or signal.get("berserk_meta")
        or {}
    )
    key_score: dict[str, Any] = {}
    if mid == "hunter":
        key_score = {
            "breakout_score": meta.get("breakout_score") or signal.get("breakout_score"),
            "fake_breakout_risk": meta.get("fake_breakout_risk") or signal.get("fake_breakout_risk"),
            "liquidation_cascade_score": meta.get("liquidation_cascade_score"),
        }
    elif mid == "chop_master":
        key_score = {
            "chop_score": meta.get("chop_score"),
            "reversal_score": meta.get("reversal_score"),
            "trend_guard_active": meta.get("trend_guard_active") or signal.get("trend_guard_active"),
        }
    elif mid == "sentinel":
        key_score = {
            "quality_score": meta.get("sentinel_quality_score") or signal.get("sentinel_quality_score"),
            "execution_quality_score": meta.get("sentinel_execution_quality_score"),
            "risk_off": meta.get("sentinel_risk_off"),
        }
    elif mid == "evrim":
        v2 = signal.get("evrim_v2") or {}
        key_score = {
            "final_score": v2.get("final_score") or signal.get("final_score"),
            "expected_net_pnl": v2.get("expected_net_pnl") or signal.get("expected_net_pnl"),
        }
    return {
        "symbol": signal.get("symbol"),
        "reason": reason,
        "score": signal.get("final_score") or signal.get("total_score") or meta.get("breakout_score"),
        "spread": signal.get("spread_pct") or meta.get("spread_pct"),
        "expected_net_pnl": meta.get("expected_net_pnl_usd") or signal.get("expected_net_pnl"),
        "market_regime": signal.get("market_regime"),
        "strength": signal.get("strength"),
        "execution_path": execution_path,
        "key_engine_score": key_score,
    }
