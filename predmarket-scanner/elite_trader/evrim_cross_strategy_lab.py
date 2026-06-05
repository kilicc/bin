"""
Evrim çapraz strateji laboratuvarı — tüm mod kararları + Evrim redleri.

- Restart'ta seviye/hafıza düşmez (ayrı kalıcı dosya).
- Öğrenme işlem açmayı durdurmaz; yalnızca skor ipuçları + aday config önerir.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "evrim_persistent_learning.json"
_REPORT_DIR = _ROOT / "data" / "reports"
_REPORT_LATEST = _REPORT_DIR / "EVRIM_CROSS_STRATEGY_latest.md"

_MAX_REJECTS = 400
_MAX_CROSS = 200
_ANALYSIS_EVERY = 30
_ANALYSIS_MIN_SEC = 90.0

_LEVEL_TITLES = [
    (1, "Çırak"),
    (5, "Öğrenci"),
    (10, "Avcı"),
    (15, "Tüccar"),
    (20, "Stratejist"),
    (30, "Usta"),
    (40, "Uzman"),
    (50, "Elit"),
    (60, "Master"),
    (70, "Grandmaster"),
    (80, "Efsane"),
    (90, "Evrim"),
    (99, "Kusursuza yakın"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "learning_level": 1,
        "peak_level": 1,
        "total_xp": 0,
        "stats": {
            "evrim_signals": 0,
            "evrim_rejects": 0,
            "evrim_entries": 0,
            "mode_decisions": 0,
            "analysis_cycles": 0,
        },
        "reject_reasons": {},
        "mode_stats": {},
        "recent_rejects": [],
        "recent_cross": [],
        "cross_insights": {
            "regime_best_mode": {},
            "evrim_miss_vs_other": [],
            "strategy_notes": [],
        },
        "strategy_hints": {
            "score_boost_by_regime": {},
            "favor_symbols": [],
            "caution_symbols": [],
            "learned_min_score_delta": 0,
        },
        "backtest_memory": {},
        "last_report": {},
        "last_analysis_at": 0.0,
        "decisions_since_analysis": 0,
    }


def _load() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return _default_state()
    try:
        st = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        base = _default_state()
        base.update({k: v for k, v in st.items() if k != "version"})
        return base
    except Exception:
        return _default_state()


def _save(st: dict[str, Any]) -> None:
    st["updated_at"] = _now_iso()
    peak = int(st.get("peak_level") or 1)
    lvl = int(st.get("learning_level") or 1)
    st["peak_level"] = max(peak, lvl)
    st["learning_level"] = st["peak_level"]
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _level_title(level: int) -> str:
    title = "Çırak"
    for lv, name in _LEVEL_TITLES:
        if level >= lv:
            title = name
    return title


def _add_xp(st: dict[str, Any], delta: int, reason: str) -> None:
    if delta <= 0:
        return
    st["total_xp"] = int(st.get("total_xp") or 0) + delta
    computed = min(99, max(1, 1 + st["total_xp"] // 40))
    prev = int(st.get("peak_level") or 1)
    if computed > prev:
        st["learning_level"] = computed
        st["peak_level"] = computed
        notes = st.setdefault("cross_insights", {}).setdefault("strategy_notes", [])
        notes.append(f"{_now_iso()[:19]} seviye ↑{computed} ({reason})")
        if len(notes) > 40:
            st["cross_insights"]["strategy_notes"] = notes[-40:]
    else:
        st["learning_level"] = prev


def _compact_signal(signal: dict[str, Any]) -> dict[str, Any]:
    hybrid = signal.get("evrim_hybrid") or {}
    v2 = signal.get("evrim_v2") or {}
    meta = (v2.get("meta") if isinstance(v2, dict) else None) or signal.get("evrim_meta") or {}
    return {
        "symbol": str(signal.get("symbol") or ""),
        "side": str(signal.get("type") or signal.get("side") or ""),
        "change": signal.get("change"),
        "strength": signal.get("strength"),
        "formula_score": signal.get("formula_score"),
        "edge": signal.get("edge"),
        "market_regime": signal.get("market_regime") or meta.get("regime_best_mode"),
        "final_score": meta.get("final_score") or hybrid.get("total_score"),
        "meta_tier": meta.get("meta_tier"),
        "total_score": hybrid.get("total_score"),
        "tier": hybrid.get("tier"),
        "reason_skip": hybrid.get("reason_skip") or hybrid.get("hard_veto"),
    }


def record_mode_decision(
    mode_id: str,
    signal: dict[str, Any],
    allowed: bool,
    reason: str,
    execution_path: str,
) -> None:
    """Tüm mod kararları — kalıcı lab + çapraz karşılaştırma."""
    st = _load()
    sym = str(signal.get("symbol") or "")
    mid = str(mode_id or "evrim")
    rk = str(reason or "")[:48]
    dedupe = (mid, sym, rk, allowed, int(time.time() // 2))
    if st.get("_last_dedupe") == dedupe:
        return
    st["_last_dedupe"] = dedupe
    st["_last_dedupe"] = dedupe
    stats = st.setdefault("stats", {})
    stats["mode_decisions"] = int(stats.get("mode_decisions") or 0) + 1
    st["decisions_since_analysis"] = int(st.get("decisions_since_analysis") or 0) + 1

    ms = st.setdefault("mode_stats", {}).setdefault(mid, {"allowed": 0, "rejected": 0, "reasons": {}})
    if allowed:
        ms["allowed"] = int(ms.get("allowed") or 0) + 1
    else:
        ms["rejected"] = int(ms.get("rejected") or 0) + 1
        reasons = ms.setdefault("reasons", {})
        reasons[rk] = int(reasons.get(rk) or 0) + 1

    if mid != "evrim":
        try:
            from elite_trader.evrim_zero_data_guard import classify_mode_data_status
            from elite_trader.parallel_universe_engine import get_universe_book

            book = get_universe_book(mid)
            closed_n = len(book.get("closed") or [])
            cls = classify_mode_data_status(
                mid,
                paper_trade_count=closed_n,
                decision_count=int(ms.get("allowed") or 0) + int(ms.get("rejected") or 0),
                reject_count=int(ms.get("rejected") or 0),
                exploration_active=bool(signal.get("minimum_data_mode_active")),
            )
            ms["data_status"] = cls.get("mode_data_status")
            ms["evrim_zero_data_guard"] = cls.get("evrim_zero_data_guard")
        except Exception:
            pass

    batch_key = f"{sym}:{int(time.time() // 15)}"
    cross = {
        "ts": _now_iso(),
        "batch_key": batch_key,
        "mode_id": mid,
        "symbol": sym,
        "side": str(signal.get("type") or ""),
        "allowed": allowed,
        "reason": str(reason or "")[:64],
        "execution_path": execution_path,
        "regime": signal.get("market_regime"),
        "score": _compact_signal(signal).get("final_score") or _compact_signal(signal).get("total_score"),
    }
    recent_cross = list(st.get("recent_cross") or [])
    recent_cross.append(cross)
    st["recent_cross"] = recent_cross[-_MAX_CROSS:]

    if mid == "evrim":
        stats["evrim_signals"] = int(stats.get("evrim_signals") or 0) + 1
        if allowed:
            stats["evrim_entries"] = int(stats.get("evrim_entries") or 0) + 1
        else:
            stats["evrim_rejects"] = int(stats.get("evrim_rejects") or 0) + 1
            rk = str(reason or "unknown")[:48]
            rr = st.setdefault("reject_reasons", {})
            rr[rk] = int(rr.get(rk) or 0) + 1
            row = {
                "ts": _now_iso(),
                "symbol": sym,
                "side": cross["side"],
                "reason": rk,
                "execution_path": execution_path,
                **_compact_signal(signal),
            }
            rejects = list(st.get("recent_rejects") or [])
            rejects.append(row)
            st["recent_rejects"] = rejects[-_MAX_REJECTS:]

    _save(st)
    maybe_run_analysis()


def record_evrim_v2_decision(
    signal: dict[str, Any],
    allowed: bool,
    reason: str,
    payload: dict[str, Any] | None,
    *,
    execution_path: str = "paper",
) -> None:
    """V2 katmanı — zengin meta ile kayıt."""
    sig = dict(signal)
    if payload:
        sig["evrim_v2"] = payload
    record_mode_decision("evrim", sig, allowed, reason, execution_path)


def record_hybrid_decision(
    signal: dict[str, Any],
    decision: Any,
    *,
    execution_path: str = "paper",
) -> None:
    """Hybrid scorer — kabul + red."""
    ok = bool(getattr(decision, "ok", False))
    reason = (
        getattr(decision, "reason_enter", "")
        if ok
        else (getattr(decision, "reason_skip", "") or getattr(decision, "hard_veto", "") or "hybrid_fail")
    )
    sig = dict(signal)
    sig["evrim_hybrid"] = {
        "total_score": getattr(decision, "total_score", None),
        "tier": getattr(decision, "tier", None),
        "reason_skip": getattr(decision, "reason_skip", None),
        "hard_veto": getattr(decision, "hard_veto", None),
        "components": getattr(decision, "components", None),
    }
    record_mode_decision("evrim", sig, ok, str(reason or ""), execution_path)


def merge_backtest_learnings(summary: dict[str, Any]) -> dict[str, Any]:
    """Backtest sonucu — seviye düşürmeden hafızaya ekle."""
    if not summary:
        return {"ok": False}
    st = _load()
    mem = st.setdefault("backtest_memory", {})
    mem["last_at"] = _now_iso()
    mem["win_rate_pct"] = summary.get("win_rate_pct")
    mem["profit_factor"] = summary.get("profit_factor")
    mem["dominant_regime"] = summary.get("dominant_regime")
    mem["regime_wr"] = summary.get("regime_wr") or summary.get("regime_stats")
    mem["param_validation"] = summary.get("param_validation")
    if summary.get("learning_analysis"):
        mem["learning_analysis"] = summary["learning_analysis"]
    _add_xp(st, 3, "backtest")
    hints = st.setdefault("strategy_hints", {})
    bt_wr = float(summary.get("win_rate_pct") or 0)
    if bt_wr >= 55:
        hints["learned_min_score_delta"] = min(0, int(hints.get("learned_min_score_delta") or 0))
    notes = st.setdefault("cross_insights", {}).setdefault("strategy_notes", [])
    notes.append(
        f"{_now_iso()[:19]} backtest WR={bt_wr}% PF={summary.get('profit_factor')}"
    )
    st["cross_insights"]["strategy_notes"] = notes[-40:]
    _save(st)
    maybe_run_analysis(force=True)
    return {"ok": True, "level": st.get("learning_level")}


def _analyze_cross_batch(st: dict[str, Any]) -> None:
    """Aynı sembol penceresinde modlar arası karşılaştırma."""
    batches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in st.get("recent_cross") or []:
        batches[str(row.get("batch_key") or "")].append(row)

    misses: list[dict[str, Any]] = []
    regime_wins: Counter[str] = Counter()

    for _key, rows in batches.items():
        if len(rows) < 2:
            continue
        evrim_rows = [r for r in rows if r.get("mode_id") == "evrim"]
        other_allowed = [r for r in rows if r.get("mode_id") != "evrim" and r.get("allowed")]
        if not evrim_rows or not other_allowed:
            continue
        ev = evrim_rows[-1]
        if ev.get("allowed"):
            continue
        best = other_allowed[0]
        miss = {
            "ts": ev.get("ts"),
            "symbol": ev.get("symbol"),
            "evrim_reason": ev.get("reason"),
            "other_mode": best.get("mode_id"),
            "other_reason": best.get("reason"),
            "regime": ev.get("regime"),
        }
        misses.append(miss)
        reg = str(ev.get("regime") or "mixed").lower()
        regime_wins[f"{reg}:{best.get('mode_id')}"] += 1

    insights = st.setdefault("cross_insights", {})
    prev_miss = list(insights.get("evrim_miss_vs_other") or [])
    prev_miss.extend(misses[-20:])
    insights["evrim_miss_vs_other"] = prev_miss[-80:]

    best_by_regime: dict[str, str] = {}
    for key, cnt in regime_wins.most_common(30):
        reg, mod = key.split(":", 1)
        if reg not in best_by_regime:
            best_by_regime[reg] = mod
    insights["regime_best_mode"] = best_by_regime

    hints = st.setdefault("strategy_hints", {})
    boost = dict(hints.get("score_boost_by_regime") or {})
    for reg, mod in best_by_regime.items():
        boost[reg] = min(5.0, float(boost.get(reg) or 0) + 0.2)
    hints["score_boost_by_regime"] = boost

    notes = insights.setdefault("strategy_notes", [])
    if misses:
        last = misses[-1]
        notes.append(
            f"{_now_iso()[:19]} Evrim red ({last.get('evrim_reason')}) — "
            f"{last.get('other_mode')} açardı ({last.get('symbol')})"
        )
    insights["strategy_notes"] = notes[-40:]


def _analyze_closed_books(st: dict[str, Any]) -> None:
    try:
        from elite_trader.parallel_universe_engine import get_books

        books = get_books() or {}
    except Exception:
        return
    sym_pnl: dict[str, float] = defaultdict(float)
    sym_n: Counter[str] = Counter()
    for mid, book in books.items():
        for c in book.get("closed") or []:
            sym = str(c.get("symbol") or "")
            pnl = float(c.get("final_pnl") or c.get("net_pnl") or 0)
            sym_pnl[sym] += pnl
            sym_n[sym] += 1
    hints = st.setdefault("strategy_hints", {})
    favor = []
    caution = []
    for sym, total in sym_pnl.items():
        if not sym or sym_n[sym] < 2:
            continue
        if total > 0:
            favor.append(sym)
        elif total < 0:
            caution.append(sym)
    hints["favor_symbols"] = sorted(favor, key=lambda s: -sym_pnl[s])[:15]
    hints["caution_symbols"] = sorted(caution, key=lambda s: sym_pnl[s])[:15]


def _top_reject_reasons(st: dict[str, Any], n: int = 12) -> list[dict[str, Any]]:
    rr = st.get("reject_reasons") or {}
    return [{"reason": k, "count": v} for k, v in sorted(rr.items(), key=lambda x: -x[1])[:n]]


def build_development_report() -> dict[str, Any]:
    st = _load()
    lvl = int(st.get("learning_level") or 1)
    stats = st.get("stats") or {}
    hints = st.get("strategy_hints") or {}
    insights = st.get("cross_insights") or {}
    report = {
        "learning_level": lvl,
        "peak_level": int(st.get("peak_level") or lvl),
        "level_title": _level_title(lvl),
        "total_xp": int(st.get("total_xp") or 0),
        "level_never_decreases": True,
        "stats": stats,
        "top_reject_reasons": _top_reject_reasons(st),
        "recent_rejects": list(reversed((st.get("recent_rejects") or [])[-15:])),
        "cross_mode_stats": st.get("mode_stats") or {},
        "regime_best_mode": insights.get("regime_best_mode") or {},
        "evrim_miss_vs_other": (insights.get("evrim_miss_vs_other") or [])[-10:],
        "strategy_notes": (insights.get("strategy_notes") or [])[-8:],
        "strategy_hints": hints,
        "backtest_memory": st.get("backtest_memory") or {},
        "analysis_cycles": int(stats.get("analysis_cycles") or 0),
        "updated_at": st.get("updated_at"),
        "learning_blocks_trading": False,
        "trading_continues": True,
    }
    st["last_report"] = report
    _save(st)
    return report


def _write_report_md(report: dict[str, Any]) -> None:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Evrim Çapraz Strateji Raporu",
        "",
        f"- Güncelleme: `{report.get('updated_at')}`",
        f"- Seviye: **{report.get('learning_level')}** ({report.get('level_title')}) — XP {report.get('total_xp')}",
        f"- Evrim sinyal/red/giriş: {report.get('stats', {}).get('evrim_signals')}/"
        f"{report.get('stats', {}).get('evrim_rejects')}/{report.get('stats', {}).get('evrim_entries')}",
        "",
        "## En çok red nedenleri",
        "",
    ]
    for row in report.get("top_reject_reasons") or []:
        lines.append(f"- `{row['reason']}`: {row['count']}")
    lines.extend(["", "## Son Evrim redleri", ""])
    for r in report.get("recent_rejects") or []:
        lines.append(
            f"- `{r.get('ts', '')[:19]}` {r.get('symbol')} {r.get('side')} "
            f"skor={r.get('final_score') or r.get('total_score')} → {r.get('reason')}"
        )
    lines.extend(["", "## Çapraz mod (rejim → en iyi)", ""])
    for reg, mod in (report.get("regime_best_mode") or {}).items():
        lines.append(f"- {reg}: **{mod}**")
    lines.extend(["", "## Strateji notları", ""])
    for n in report.get("strategy_notes") or []:
        lines.append(f"- {n}")
    _REPORT_LATEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def maybe_run_analysis(*, force: bool = False) -> dict[str, Any]:
    st = _load()
    now = time.time()
    since = int(st.get("decisions_since_analysis") or 0)
    last = float(st.get("last_analysis_at") or 0)
    if not force and since < _ANALYSIS_EVERY and (now - last) < _ANALYSIS_MIN_SEC:
        return {"skipped": True}

    _analyze_cross_batch(st)
    _analyze_closed_books(st)
    _add_xp(st, 2, "analysis_cycle")
    stats = st.setdefault("stats", {})
    stats["analysis_cycles"] = int(stats.get("analysis_cycles") or 0) + 1
    st["last_analysis_at"] = now
    st["decisions_since_analysis"] = 0

    hints = st.setdefault("strategy_hints", {})
    misses = len((st.get("cross_insights") or {}).get("evrim_miss_vs_other") or [])
    if misses >= 5:
        hints["learned_min_score_delta"] = max(-3, int(hints.get("learned_min_score_delta") or 0) - 1)

    _save(st)
    report = build_development_report()
    _write_report_md(report)

    try:
        from elite_trader.evrim_config_version import set_candidate

        delta = int(hints.get("learned_min_score_delta") or 0)
        if delta != 0 and stats.get("analysis_cycles", 0) % 5 == 0:
            from elite_trader.mode_profiles import get_profile

            prof = get_profile("evrim") or {}
            cur_min = int(prof.get("evrim_v2_min_final_score") or 55)
            new_min = max(48, min(65, cur_min + delta))
            if new_min != cur_min:
                set_candidate(
                    {"evrim_v2_min_final_score": new_min},
                    source="cross_strategy_lab",
                    task_type="continuous_learning",
                    risk_change="soft",
                    expected_improvement=f"miss={misses}",
                    source_modes=list((st.get("cross_insights") or {}).get("regime_best_mode", {}).values()),
                    approval_required=True,
                    backtest_passed=None,
                )
    except Exception:
        pass

    return {"ok": True, "report": report}


def get_learned_score_boost(signal: dict[str, Any], ctx: dict[str, Any]) -> float:
    """Soft skor artışı — veto eklemez, işlem açmayı kolaylaştırır."""
    st = _load()
    hints = st.get("strategy_hints") or {}
    boost = 0.0
    regime = str(ctx.get("regime") or signal.get("market_regime") or "mixed").lower()
    reg_boost = (hints.get("score_boost_by_regime") or {}).get(regime)
    if reg_boost:
        boost += float(reg_boost)
    sym = str(signal.get("symbol") or "").upper()
    if sym in (hints.get("favor_symbols") or []):
        boost += 1.5
    if sym in (hints.get("caution_symbols") or []):
        boost -= 0.5
    return max(-1.0, min(5.0, boost))


def ensure_persistent_learning() -> dict[str, Any]:
    """Boot — seviye asla düşmez; opportunity evolution ile senkron (max)."""
    st = _load()
    try:
        from elite_trader.evrim_opportunity import _load_state, _save_state, _default_evolution, _level_title

        opp = _load_state()
        ev = opp.setdefault("evolution", _default_evolution())
        peak = int(st.get("peak_level") or 1)
        opp_level = int(ev.get("level") or 1)
        merged = max(peak, opp_level)
        if merged > opp_level:
            ev["level"] = merged
            ev["title"] = _level_title(merged)
            ev["xp"] = max(int(ev.get("xp") or 0), int(st.get("total_xp") or 0))
            opp["evolution"] = ev
            _save_state(opp)
        if merged > peak:
            st["learning_level"] = merged
            st["peak_level"] = merged
            _save(st)
    except Exception:
        pass
    return {"level": st.get("learning_level"), "xp": st.get("total_xp")}


def sync_trade_closed(mode_id: str, closed: dict[str, Any]) -> None:
    """Kapanış — XP + sembol öğrenmesi."""
    st = _load()
    pnl = float(closed.get("final_pnl") or closed.get("net_pnl") or 0)
    if mode_id == "evrim" and pnl > 0:
        _add_xp(st, 2, "evrim_win")
    elif mode_id != "evrim" and pnl > 0:
        _add_xp(st, 1, f"{mode_id}_win_observed")
    _save(st)
