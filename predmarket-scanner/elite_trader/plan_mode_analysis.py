"""Mod bazlı işlem analizi — 1s / 24s / 7g / 30g / 1y ufukları + günlük hedef."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from elite_trader.mode_profiles import get_profile
from elite_trader.panel_strategy import mode_order
from elite_trader.parallel_universe_engine import get_books
from elite_trader.plan_modes import (
    ANALYSIS_HORIZONS,
    LIVE_ID,
    load_goals,
    mode_label,
    normalize_mode_id,
)
from elite_trader.panel_strategy import mode_catalog

_PARALLEL = ("hunter", "berserk", "chop_master", "evrim")


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or row.get("unrealized_pnl") or 0)


def _parse_ts(row: dict[str, Any]) -> float | None:
    for key in ("exit_time", "closed_at", "entry_time_str", "entry_time", "opened_at_iso"):
        v = row.get(key)
        if not v:
            continue
        s = str(v).replace("Z", "+00:00")[:32]
        try:
            if len(s) >= 19 and "T" not in s and " " in s:
                s = s.replace(" ", "T", 1)
            return datetime.fromisoformat(s).timestamp()
        except Exception:
            continue
    return None


def _mode_trades(
    mode_id: str,
    *,
    live_closed: list[dict[str, Any]] | None = None,
    live_open: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mid = normalize_mode_id(mode_id)
    if mid == LIVE_ID:
        return list(live_open or []), list(live_closed or [])
    book = (get_books() or {}).get(mid) or {}
    return list(book.get("open") or []), list(book.get("closed") or [])


def _filter_closed_since(closed: list[dict[str, Any]], since_ts: float) -> list[dict[str, Any]]:
    out = []
    for c in closed:
        ts = _parse_ts(c)
        if ts is None or ts >= since_ts:
            out.append(c)
    return out


def _horizon_stats(closed: list[dict[str, Any]], open_pos: list[dict[str, Any]]) -> dict[str, Any]:
    losses = [c for c in closed if _pnl(c) < 0]
    wins = [c for c in closed if _pnl(c) > 0]
    total = sum(_pnl(c) for c in closed)
    unreal = sum(_pnl(p) for p in open_pos)
    by_reason: dict[str, int] = defaultdict(int)
    for c in losses:
        by_reason[str(c.get("exit_reason") or "?")[:24]] += 1
    top_loss = sorted(losses, key=_pnl)[:5]
    return {
        "closed_n": len(closed),
        "open_n": len(open_pos),
        "wins": len(wins),
        "losses": len(losses),
        "pnl_closed": round(total, 2),
        "unrealized": round(unreal, 2),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "top_loss_reasons": dict(sorted(by_reason.items(), key=lambda x: -x[1])[:5]),
        "top_losses": [
            {
                "symbol": x.get("symbol"),
                "pnl": round(_pnl(x), 2),
                "reason": x.get("exit_reason"),
            }
            for x in top_loss
        ],
    }


def build_mode_analysis_bundle(
    mode_id: str,
    *,
    live_closed: list[dict[str, Any]] | None = None,
    live_open: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tüm ufuklar + günlük hedef ilerlemesi."""
    mid = normalize_mode_id(mode_id)
    open_pos, all_closed = _mode_trades(mid, live_closed=live_closed, live_open=live_open)
    now = time.time()
    horizons: dict[str, Any] = {}
    for key, label_h, sec in ANALYSIS_HORIZONS:
        subset = _filter_closed_since(all_closed, now - sec)
        horizons[key] = {
            "label": label_h,
            "seconds": sec,
            "stats": _horizon_stats(subset, open_pos if key == "1h" else []),
        }
    # 24h = günlük hedef takibi
    day_closed = _filter_closed_since(all_closed, now - 86400)
    day_pnl = sum(_pnl(c) for c in day_closed)
    goals = load_goals().get(mid) or {}
    target = float(goals.get("daily_pnl_target_usd") or 0)
    max_loss = float(goals.get("daily_max_loss_usd") or 0)
    goal_gap = round(target - day_pnl, 2) if target else None
    prof = get_profile(mid) if mid in _PARALLEL else {}
    return {
        "mode_id": mid,
        "label": mode_label(mid),
        "is_live": mid == LIVE_ID,
        "horizons": horizons,
        "daily": {
            "pnl": round(day_pnl, 2),
            "target": target,
            "max_loss": max_loss,
            "gap_to_target": goal_gap,
            "loss_trades": len([c for c in day_closed if _pnl(c) < 0]),
            "closed_trades": len(day_closed),
            "on_track": day_pnl >= target if target else None,
        },
        "profile": prof,
        "open_count": len(open_pos),
        "total_closed": len(all_closed),
    }


def format_analysis_for_prompt(bundle: dict[str, Any]) -> str:
    lines = [
        f"MOD: {bundle.get('label')} ({bundle.get('mode_id')})",
        f"Açık pozisyon: {bundle.get('open_count', 0)} — bunlara dokunulmayacak, yalnızca yeni giriş/çıkış kuralları.",
        "",
        "GÜNLÜK HEDEF:",
    ]
    d = bundle.get("daily") or {}
    lines.append(
        f"  Bugün PnL {d.get('pnl', 0)}$ / hedef {d.get('target', 0)}$ "
        f"(fark {d.get('gap_to_target', '—')}$) · {d.get('loss_trades', 0)} zararlı kapanış"
    )
    lines.append("")
    for key, _lbl, _ in ANALYSIS_HORIZONS:
        h = (bundle.get("horizons") or {}).get(key) or {}
        st = h.get("stats") or {}
        if not st.get("closed_n") and not st.get("open_n"):
            lines.append(f"{h.get('label', key)}: veri yok")
            continue
        lines.append(
            f"{h.get('label')}: {st.get('closed_n', 0)} kapanan, WR {st.get('win_rate', '—')}%, "
            f"PnL {st.get('pnl_closed', 0)}$, açık {st.get('open_n', 0)}"
        )
        if st.get("top_losses"):
            for t in st["top_losses"][:3]:
                lines.append(f"  · {t.get('symbol')} {t.get('pnl')}$ ({t.get('reason')})")
    lines.append("")
    lines.append(
        "Görev: Türkçe analiz + 3–5 yapılacak madde. Sonunda «Uygulama notu»: "
        "yalnızca paper profil veya Ana Hat için GÜVENLİ giriş/çıkış eşikleri (açık pozisyon stake/SL değişmez)."
    )
    return "\n".join(lines)


def rule_based_safe_patch(bundle: dict[str, Any]) -> dict[str, Any]:
    """İstatistikten güvenli ince ayar önerisi (açık pozisyonu etkilemez)."""
    mid = bundle.get("mode_id")
    if mid == LIVE_ID:
        return _live_safe_patch(bundle)
    return _parallel_safe_patch(bundle)


def _parallel_safe_patch(bundle: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    d = bundle.get("daily") or {}
    h24 = ((bundle.get("horizons") or {}).get("24h") or {}).get("stats") or {}
    losses = h24.get("losses") or 0
    closed = h24.get("closed_n") or 0
    wr = h24.get("win_rate")
    gap = d.get("gap_to_target")
    prof = bundle.get("profile") or {}

    if gap is not None and gap > 25 and closed >= 3:
        patch["entry_min_edge_mult"] = round(
            min(1.35, float(prof.get("entry_min_edge_mult") or 1.0) + 0.04), 3
        )
    if losses >= 5 and closed >= 8 and (wr or 100) < 70:
        patch["entry_min_formula_mult"] = round(
            min(1.25, float(prof.get("entry_min_formula_mult") or 1.0) + 0.03), 3
        )
    reasons = h24.get("top_loss_reasons") or {}
    if reasons.get("SL-EMERGENCY", 0) >= 2:
        patch["entry_skip_cautious"] = True
    if d.get("pnl", 0) > (d.get("target") or 0) * 1.2 and closed >= 4:
        patch["entry_stake_mult"] = round(
            max(0.75, float(prof.get("entry_stake_mult") or 1.0) - 0.03), 3
        )
    return patch


def _live_safe_patch(bundle: dict[str, Any]) -> dict[str, str]:
    """Ana Hat .env — yalnızca yeni işlemleri etkileyen anahtarlar."""
    patch: dict[str, str] = {}
    h24 = ((bundle.get("horizons") or {}).get("24h") or {}).get("stats") or {}
    losses = h24.get("losses") or 0
    if losses >= 4:
        patch["ELITE_MIN_EDGE"] = "0.050"
    if losses >= 6:
        patch["ELITE_MIN_FORMULA_SCORE"] = "0.54"
    reasons = h24.get("top_loss_reasons") or {}
    if reasons.get("SL-EMERGENCY", 0) >= 2:
        patch["ELITE_SL_EM_EXTRA_EDGE"] = "0.030"
    return patch
