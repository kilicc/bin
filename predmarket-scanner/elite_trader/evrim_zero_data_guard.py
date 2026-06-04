"""Evrim zero-data guard — distinguish filter silence from bad strategy."""
from __future__ import annotations

from typing import Any

CLASSIFICATIONS = frozenset(
    {
        "no_signal",
        "filtered_out",
        "observation_only",
        "exploration_trade",
        "normal_trade",
        "profitable_trade",
        "losing_trade",
        "no_trade_due_to_filters",
    }
)


def classify_mode_data_status(
    mode_id: str,
    *,
    paper_trade_count: int,
    decision_count: int,
    reject_count: int = 0,
    observation_count: int = 0,
    exploration_active: bool = False,
) -> dict[str, Any]:
    mid = str(mode_id or "")
    if paper_trade_count > 0:
        status = "normal_trade"
    elif decision_count <= 0:
        status = "no_signal"
    elif exploration_active and observation_count > 0:
        status = "observation_only"
    elif exploration_active:
        status = "exploration_trade"
    elif decision_count > 0 and paper_trade_count == 0:
        status = "no_trade_due_to_filters"
    elif reject_count > 0:
        status = "filtered_out"
    else:
        status = "no_signal"

    return {
        "mode_id": mid,
        "mode_data_status": status,
        "paper_trade_count": paper_trade_count,
        "decision_count": decision_count,
        "reject_count": reject_count,
        "observation_count": observation_count,
        "is_zero_trade": paper_trade_count == 0,
        "strategy_bad": False if status == "no_trade_due_to_filters" else None,
        "evrim_zero_data_guard": status in ("no_trade_due_to_filters", "observation_only", "no_signal"),
    }


def enrich_mode_stats(mode_stats: dict[str, Any], books: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    books = books or {}
    out: dict[str, Any] = {}
    for mid, ms in (mode_stats or {}).items():
        if mid == "evrim":
            continue
        book = books.get(mid) or {}
        closed = len(book.get("closed") or [])
        allowed = int(ms.get("allowed") or 0)
        rejected = int(ms.get("rejected") or 0)
        cls = classify_mode_data_status(
            mid,
            paper_trade_count=closed,
            decision_count=allowed + rejected,
            reject_count=rejected,
        )
        enriched = dict(ms)
        enriched.update(cls)
        out[mid] = enriched
    return out


def mode_reject_diagnosis(mode_id: str) -> dict[str, Any]:
    from elite_trader.mode_reject_buffer import summary

    return {
        "mode_id": mode_id,
        "mode_reject_diagnosis": summary(mode_id),
    }
