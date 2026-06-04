"""Hunter paper öğrenme önerileri — profili otomatik değiştirmez."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SUGGESTIONS_PATH = _ROOT / "data" / "hunter_learning_suggestions.json"
_INTERVAL = 50


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


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
    fake_cnt = 0
    liq_wins = 0
    liq_total = 0
    vol_spike_wins = 0
    vol_spike_total = 0
    delays: list[float] = []
    breakout_scores: list[float] = []

    for c in closed:
        sym = str(c.get("symbol") or "")
        sym_pnl[sym] += _pnl(c)
        ex = str(c.get("exit_reason") or "")
        if "fake" in ex.lower() or c.get("fake_breakout_result"):
            fake_cnt += 1
        if float(c.get("liquidation_cascade_score") or 0) >= 75:
            liq_total += 1
            if _pnl(c) > 0:
                liq_wins += 1
        if str(c.get("spike_type") or "") == "volume_spike":
            vol_spike_total += 1
            if _pnl(c) > 0:
                vol_spike_wins += 1
        if c.get("entry_delay_sec") is not None:
            delays.append(float(c["entry_delay_sec"]))
        if c.get("breakout_score") is not None:
            breakout_scores.append(float(c["breakout_score"]))

    wr = len(wins) / len(closed) if closed else 0.0
    gross = sum(max(0.0, _pnl(c)) for c in closed)
    loss_sum = abs(sum(_pnl(c) for c in losses))
    pf = gross / max(0.01, loss_sum)

    return {
        "best_breakout_pattern": "strong_breakout" if wr > 0.6 else "medium_breakout",
        "worst_fakeout_pattern": "no_volume_confirmation",
        "best_symbols_for_spike": sorted(sym_pnl, key=sym_pnl.get, reverse=True)[:5],
        "worst_symbols_for_fakeout": sorted(sym_pnl, key=sym_pnl.get)[:5],
        "optimal_entry_delay_sec": round(sum(delays) / len(delays), 1) if delays else 5.0,
        "recommended_tp_stake_pct": 0.0095,
        "recommended_sl_stake_pct": 0.0042,
        "recommended_breakout_thresholds": {
            "hunter_breakout_change_pct": 0.30,
            "hunter_breakout_vol_ratio": 1.35,
        },
        "recommended_spread_limit": 0.18,
        "liquidation_continuation_rate": round(liq_wins / max(1, liq_total), 3),
        "volume_spike_success_rate": round(vol_spike_wins / max(1, vol_spike_total), 3),
        "fake_breakout_rate": round(fake_cnt / max(1, len(closed)), 3),
        "hunter_confidence_score": round(min(1.0, len(closed) / 150.0), 2),
        "avg_breakout_score": round(
            sum(breakout_scores) / len(breakout_scores), 1
        )
        if breakout_scores
        else 0.0,
        "win_rate": round(wr * 100, 1),
        "profit_factor": round(pf, 3),
    }


def record_fake_breakout_event(
    signal: dict[str, Any],
    meta: dict[str, Any],
    reason: str,
) -> None:
    st = _load()
    events = list(st.get("fake_breakout_events") or [])
    events.append(
        {
            "symbol": signal.get("symbol"),
            "reason": reason,
            "fake_breakout_risk": meta.get("fake_breakout_risk"),
            "fake_breakout_reason": meta.get("fake_breakout_reason"),
            "breakout_score": meta.get("breakout_score"),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )
    st["fake_breakout_events"] = events[-200:]
    st["fake_breakout_event_count"] = int(st.get("fake_breakout_event_count") or 0) + 1
    _save(st)


def on_hunter_trade_closed(closed: dict[str, Any], book_closed: list[dict[str, Any]]) -> None:
    st = _load()
    n = int(st.get("trade_count_since") or 0) + 1
    st["trade_count_since"] = n
    st["last_closed"] = {
        "symbol": closed.get("symbol"),
        "pnl": round(_pnl(closed), 4),
        "reason": closed.get("exit_reason"),
        "breakout_score": closed.get("breakout_score"),
    }
    if n >= _INTERVAL and n % _INTERVAL == 0:
        st["suggestions"] = _build_suggestions(book_closed[-_INTERVAL:])
        st["suggestion_at_trade"] = n
    _save(st)


def get_suggestions() -> dict[str, Any]:
    data = _load()
    return {
        "hunter_learning_suggestions": data.get("suggestions") or {},
        "trade_count_since": data.get("trade_count_since", 0),
        "suggestion_at_trade": data.get("suggestion_at_trade"),
    }
