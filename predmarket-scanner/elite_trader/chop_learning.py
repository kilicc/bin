"""Chop paper öğrenme önerileri — profili otomatik değiştirmez."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SUGGESTIONS_PATH = _ROOT / "data" / "chop_learning_suggestions.json"
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
    sym_pnl: dict[str, float] = defaultdict(float)
    chop_scores: list[float] = []
    range_widths: list[float] = []
    mr_wins = mr_total = 0
    fb_wins = fb_total = 0
    vwap_wins = vwap_total = 0
    bb_wins = bb_total = 0
    narrow_cnt = 0
    tg_blocks = 0

    for c in closed:
        sym = str(c.get("symbol") or "")
        sym_pnl[sym] += _pnl(c)
        if c.get("chop_score") is not None:
            chop_scores.append(float(c["chop_score"]))
        if c.get("range_width_pct") is not None:
            range_widths.append(float(c["range_width_pct"]))
        if c.get("range_too_narrow"):
            narrow_cnt += 1
        if c.get("trend_guard_active"):
            tg_blocks += 1
        if float(c.get("mean_reversion_score") or 0) >= 65:
            mr_total += 1
            if _pnl(c) > 0:
                mr_wins += 1
        if c.get("failed_breakout_detected"):
            fb_total += 1
            if _pnl(c) > 0:
                fb_wins += 1
        if c.get("vwap_return_success") or "vwap" in str(c.get("exit_reason") or "").lower():
            vwap_total += 1
            if _pnl(c) > 0:
                vwap_wins += 1
        if c.get("bb_rejection_success"):
            bb_total += 1
            if _pnl(c) > 0:
                bb_wins += 1

    wins = [c for c in closed if _pnl(c) > 0]
    gross = sum(max(0.0, _pnl(c)) for c in closed)
    fees = sum(float(c.get("total_fees") or 0) for c in closed)

    return {
        "chop_quality_score": round(
            sum(chop_scores) / len(chop_scores), 1
        )
        if chop_scores
        else 0.0,
        "best_range_width": round(
            sum(range_widths) / len(range_widths), 4
        )
        if range_widths
        else 0.0,
        "best_reversal_pattern": "failed_breakout_reversal"
        if fb_wins > mr_wins
        else "range_rejection",
        "worst_chop_symbols": sorted(sym_pnl, key=sym_pnl.get)[:5],
        "best_chop_symbols": sorted(sym_pnl, key=sym_pnl.get, reverse=True)[:5],
        "suggested_tp_sl": {
            "tp_stake_pct": 0.0028,
            "sl_stake_pct": 0.0018,
            "tp_trigger_frac": 0.99,
        },
        "suggested_spread_limit": 0.12,
        "fake_breakout_reversal_success": round(fb_wins / max(1, fb_total), 3),
        "VWAP_return_success": round(vwap_wins / max(1, vwap_total), 3),
        "range_too_narrow_rate": round(narrow_cnt / max(1, len(closed)), 3),
        "trend_guard_success": round(tg_blocks / max(1, len(closed)), 3),
        "mean_reversion_success": round(mr_wins / max(1, mr_total), 3),
        "bollinger_rejection_success": round(bb_wins / max(1, bb_total), 3),
        "confidence": round(min(1.0, len(closed) / 150.0), 2),
        "win_rate": round(len(wins) / max(1, len(closed)) * 100, 1),
        "fee_gross_ratio": round(fees / max(0.01, gross), 4) if gross else 0.0,
    }


def on_chop_trade_closed(closed: dict[str, Any], book_closed: list[dict[str, Any]]) -> None:
    st = _load()
    n = int(st.get("trade_count_since") or 0) + 1
    st["trade_count_since"] = n
    st["last_closed"] = {
        "symbol": closed.get("symbol"),
        "pnl": round(_pnl(closed), 4),
        "reason": closed.get("exit_reason"),
        "chop_score": closed.get("chop_score"),
    }
    if n >= _INTERVAL and n % _INTERVAL == 0:
        st["suggestions"] = _build_suggestions(book_closed[-_INTERVAL:])
        st["suggestion_at_trade"] = n
    _save(st)


def get_suggestions() -> dict[str, Any]:
    data = _load()
    return {
        "chop_learning_suggestions": data.get("suggestions") or {},
        "trade_count_since": data.get("trade_count_since", 0),
        "suggestion_at_trade": data.get("suggestion_at_trade"),
    }
