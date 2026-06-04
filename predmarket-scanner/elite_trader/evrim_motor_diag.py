"""
Evrim canlı motor — red / geçiş özeti (panel; profil dokunmaz).
"""
from __future__ import annotations

from typing import Any


def _short_reason(reason: str) -> str:
    r = str(reason or "unknown").strip()[:56]
    if "spread" in r.lower():
        return "spread"
    if "fee" in r.lower() or "net-tp" in r.lower() or "ücret" in r.lower():
        return "fee_net_tp"
    if "dd_halt" in r or "daily_dd" in r:
        return "dd_halt"
    if "spread_halt" in r:
        return "spread_halt"
    if "universe" in r.lower() or "not in" in r.lower():
        return "not_in_universe"
    if "weak" in r.lower():
        return "weak_signal"
    if "volume" in r.lower():
        return "volume"
    if "negative_expectancy" in r:
        return "expectancy"
    if "regime" in r:
        return "regime"
    if "radar" in r or "uncertain" in r:
        return "radar"
    if "fake" in r:
        return "fake_breakout"
    if "ban" in r.lower() or "sl" in r.lower():
        return "loss_ban"
    if "risk" in r.lower() or "cautious" in r.lower():
        return "risk"
    return r.split(":")[0].split("(")[0].strip() or "other"


def summarize_reject_stats(raw: dict[str, int] | None) -> dict[str, Any]:
    """Ham red sayaçlarını kısa anahtarlara topla."""
    merged: dict[str, int] = {}
    for k, v in (raw or {}).items():
        short = _short_reason(k)
        merged[short] = merged.get(short, 0) + int(v)
    top = sorted(merged.items(), key=lambda x: -x[1])[:8]
    total = sum(merged.values())
    return {
        "total": total,
        "top": [{"reason": k, "count": v} for k, v in top],
        "top_txt": ", ".join(f"{k}:{v}" for k, v in top[:5]) if top else "",
    }


def build_motor_diag(
    *,
    execution_mode: str,
    reject_stats: dict[str, int] | None,
    queue_len: int = 0,
    open_count: int = 0,
    max_open: int = 0,
    last_order_ago_sec: float | None = None,
    queue_added: int = 0,
    orders_opened: int = 0,
) -> dict[str, Any]:
    """Panel + API için motor özeti."""
    rej = summarize_reject_stats(reject_stats)
    hybrid: dict[str, Any] = {"n": 0}
    try:
        from elite_trader.evrim_decision_log import aggregate_stats

        hybrid = aggregate_stats(500)
    except Exception:
        pass
    entered_h = int(hybrid.get("entered_n") or 0)
    skipped_h = int(hybrid.get("skipped_n") or 0)
    n_h = int(hybrid.get("n") or 0)
    hybrid_pass_pct = (
        round(entered_h / n_h * 100, 1) if n_h else None
    )
    top_skip_h = hybrid.get("top_skip_reasons") or []
    top_skip_txt = ", ".join(
        f"{_short_reason(str(k))}:{v}" for k, v in top_skip_h[:4]
    )
    avg_entered = hybrid.get("avg_score_entered")
    motor_pass = max(0, int(queue_added))
    motor_block = int(rej.get("total") or 0)
    motor_total = motor_pass + motor_block
    motor_pass_pct = (
        round(motor_pass / motor_total * 100, 1) if motor_total else None
    )
    return {
        "execution_mode": execution_mode,
        "queue_len": queue_len,
        "open_count": open_count,
        "max_open": max_open,
        "last_order_ago_sec": last_order_ago_sec,
        "queue_added": queue_added,
        "orders_opened_session": orders_opened,
        "reject_total": motor_block,
        "reject_top": rej.get("top") or [],
        "reject_top_txt": rej.get("top_txt") or "",
        "hybrid_eval_n": n_h,
        "hybrid_entered_n": entered_h,
        "hybrid_skipped_n": skipped_h,
        "hybrid_pass_pct": hybrid_pass_pct,
        "hybrid_top_skip_txt": top_skip_txt,
        "motor_pass_pct": motor_pass_pct,
        "avg_hybrid_score": hybrid.get("avg_total_score"),
        "avg_score_entered": avg_entered,
    }
