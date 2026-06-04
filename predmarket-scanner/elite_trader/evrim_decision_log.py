"""Evrim karar günlüğü — JSONL (ring buffer)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_LOG_PATH = _ROOT / "data" / "evrim_decision_log.jsonl"
_MAX_LINES = 50_000
_trim_counter = 0
_TRIM_EVERY = 200  # her yazımda tüm dosyayı okuma — periyodik trim


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_decision(record: dict[str, Any]) -> None:
    global _trim_counter
    row = dict(record)
    row.setdefault("ts", _now_iso())
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    _trim_counter += 1
    if _trim_counter >= _TRIM_EVERY:
        _trim_counter = 0
        _trim_if_needed()


def _trim_if_needed() -> None:
    if not _LOG_PATH.is_file():
        return
    try:
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    if len(lines) <= _MAX_LINES:
        return
    keep = lines[-_MAX_LINES:]
    _LOG_PATH.write_text("\n".join(keep) + "\n", encoding="utf-8")


def read_recent(limit: int = 50) -> list[dict[str, Any]]:
    if not _LOG_PATH.is_file():
        return []
    try:
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def aggregate_stats(limit: int = 500) -> dict[str, Any]:
    rows = read_recent(limit)
    if not rows:
        return {"n": 0}
    entered = [r for r in rows if r.get("entered")]
    skipped = [r for r in rows if not r.get("entered")]
    tiers: dict[str, int] = {}
    skip_reasons: dict[str, int] = {}
    comp_sum: dict[str, float] = {}
    comp_n = 0
    for r in rows:
        t = str(r.get("tier") or "none")
        tiers[t] = tiers.get(t, 0) + 1
        if not r.get("entered"):
            rs = str(r.get("reason_skip") or "unknown")[:40]
            skip_reasons[rs] = skip_reasons.get(rs, 0) + 1
        comps = r.get("components") or {}
        if comps:
            comp_n += 1
            for k, v in comps.items():
                comp_sum[k] = comp_sum.get(k, 0) + float(v)
    avg_score = sum(float(r.get("total_score") or 0) for r in rows) / len(rows)
    avg_entered = (
        sum(float(r.get("total_score") or 0) for r in entered) / len(entered)
        if entered
        else 0.0
    )
    return {
        "n": len(rows),
        "entered_n": len(entered),
        "skipped_n": len(skipped),
        "avg_total_score": round(avg_score, 1),
        "avg_score_entered": round(avg_entered, 1),
        "tier_counts": tiers,
        "top_skip_reasons": sorted(
            skip_reasons.items(), key=lambda x: -x[1]
        )[:10],
        "avg_components": {
            k: round(comp_sum[k] / max(1, comp_n), 2) for k in comp_sum
        },
    }
