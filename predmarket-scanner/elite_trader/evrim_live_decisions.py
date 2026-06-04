"""Evrim live/demo decision ring buffer (500)."""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "evrim_live_decisions.json"
_MAX = 500

_counts = {
    "decision_count": 0,
    "order_attempts": 0,
    "order_sent": 0,
    "exchange_accepted": 0,
    "reject_count": 0,
    "allow_count": 0,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {"decisions": [], "counts": dict(_counts)}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"decisions": [], "counts": dict(_counts)}


def _save(data: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    _STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_decision(
    *,
    symbol: str = "",
    side: str = "",
    allowed: bool,
    reason: str = "",
    final_score: float | None = None,
    expected_net_pnl: float | None = None,
    order_route: str = "",
    preflight_ok: bool | None = None,
    order_sent: bool = False,
    exchange_accepted: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    global _counts
    data = _load()
    counts = data.setdefault("counts", dict(_counts))
    counts["decision_count"] = int(counts.get("decision_count") or 0) + 1
    if allowed:
        counts["allow_count"] = int(counts.get("allow_count") or 0) + 1
    else:
        counts["reject_count"] = int(counts.get("reject_count") or 0) + 1
    if order_sent:
        counts["order_sent"] = int(counts.get("order_sent") or 0) + 1
    if exchange_accepted:
        counts["exchange_accepted"] = int(counts.get("exchange_accepted") or 0) + 1
    _counts.update(counts)

    row = {
        "timestamp": _now_iso(),
        "ts": time.time(),
        "symbol": symbol,
        "side": side,
        "allowed": allowed,
        "reason": str(reason or "")[:120],
        "final_score": final_score,
        "expected_net_pnl": expected_net_pnl,
        "order_route": order_route,
        "preflight_ok": preflight_ok,
        "order_sent": order_sent,
        "exchange_accepted": exchange_accepted,
    }
    if extra:
        row.update(extra)
    decisions: list[dict[str, Any]] = list(data.get("decisions") or [])
    decisions.append(row)
    if len(decisions) > _MAX:
        decisions = decisions[-_MAX:]
    data["decisions"] = decisions
    _save(data)


def record_order_attempt(**kwargs: Any) -> None:
    data = _load()
    counts = data.setdefault("counts", dict(_counts))
    counts["order_attempts"] = int(counts.get("order_attempts") or 0) + 1
    _counts["order_attempts"] = counts["order_attempts"]
    _save(data)
    record_decision(**kwargs)


def get_panel() -> dict[str, Any]:
    data = _load()
    decisions = list(data.get("decisions") or [])
    counts = data.get("counts") or dict(_counts)
    rejects = [d for d in decisions if not d.get("allowed")]
    c: Counter[str] = Counter()
    scores: list[float] = []
    pnls: list[float] = []
    for d in decisions:
        if not d.get("allowed"):
            c[str(d.get("reason") or "unknown")[:64]] += 1
        if d.get("final_score") is not None:
            scores.append(float(d["final_score"]))
        if d.get("expected_net_pnl") is not None:
            pnls.append(float(d["expected_net_pnl"]))
    last = list(reversed(decisions))[:20]
    last_rej = list(reversed(rejects))[:20]
    return {
        "evrim_live_decision_count": int(counts.get("decision_count") or 0),
        "evrim_live_order_attempts": int(counts.get("order_attempts") or 0),
        "evrim_live_order_sent": int(counts.get("order_sent") or 0),
        "evrim_live_exchange_accepted": int(counts.get("exchange_accepted") or 0),
        "evrim_live_reject_count": int(counts.get("reject_count") or 0),
        "evrim_live_allow_count": int(counts.get("allow_count") or 0),
        "evrim_live_reject_reasons": [{"reason": k, "count": v} for k, v in c.most_common(10)],
        "evrim_final_score_avg": round(sum(scores) / len(scores), 2) if scores else None,
        "evrim_expected_net_pnl_avg": round(sum(pnls) / len(pnls), 4) if pnls else None,
        "evrim_last_20_live_decisions": last,
        "evrim_last_20_rejects": last_rej,
        "note": (
            "Evrim active live/demo motor olduğu için parallel paper kitabına yazılmaz. "
            "Evrim kararları live/demo decision panelinde izlenir."
        ),
        "updated_at": data.get("updated_at"),
    }
