"""
Evrim — işlem sonrası öğrenme kaydı, 50 işlem analizi, sınırlı parametre güncelleme.

Yeni ayarlar yalnızca backtest onayından sonra profile yazılır; önce backup alınır.
"""
from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.evrim_opportunity import MODE_ID
from elite_trader.mode_profiles import get_profile, save_profile

_ROOT = Path(__file__).resolve().parent.parent
_JOURNAL_PATH = _ROOT / "data" / "evrim_trade_journal.jsonl"
_BACKUP_DIR = _ROOT / "data" / "backups"
_ANALYSIS_EVERY_N = 50

PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "min_edge": (0.06, 0.45),
    "evrim_min_total_score": (48, 75),
    "tp_stake_pct": (0.0018, 0.015),
    "sl_stake_pct": (0.0012, 0.006),
    "max_open": (3, 20),
    "active_capital_pct": (0.20, 0.95),
}

MIN_BT_WR_TO_APPLY = 38.0
MIN_BT_TRADES_TO_APPLY = 25


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _pct_to_stake(v: float) -> float:
    return v / 100.0 if v >= 0.05 else v


def clamp_parameter_patch(patch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, (lo, hi) in PARAM_BOUNDS.items():
        if key not in patch:
            continue
        val = patch[key]
        if key in ("evrim_min_total_score", "max_open"):
            out[key] = int(_clamp(float(val), lo, hi))
        elif key == "min_edge":
            out[key] = round(_clamp(float(val), lo, hi), 3)
        elif key in ("tp_stake_pct", "sl_stake_pct", "active_capital_pct"):
            out[key] = round(_clamp(float(val), lo, hi), 5)
        else:
            out[key] = val
    return out


def backup_evrim_profile() -> str:
    """Mevcut evrim profilini timestamp ile yedekle."""
    src = _ROOT / "data" / "mode_profiles.json"
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = _BACKUP_DIR / f"evrim_profile_{ts}.json"
    if src.is_file():
        shutil.copy2(src, dest)
    try:
        from elite_trader.evrim_training import load_training_state, _save_training_state

        st = load_training_state()
        hist = st.setdefault("profile_backup_paths", [])
        hist.append(str(dest.relative_to(_ROOT)))
        st["profile_backup_paths"] = hist[-20:]
        _save_training_state(st)
    except Exception:
        pass
    return str(dest)


def _compute_quality_score(
    net_pnl: float,
    mfe: float,
    mae: float,
    hold_sec: float,
    exit_reason: str,
) -> float:
    """0-100 işlem kalite skoru."""
    s = 50.0
    if net_pnl > 0:
        s += min(25, net_pnl * 3)
    else:
        s -= min(30, abs(net_pnl) * 4)
    if mfe > 0 and mae < 0:
        capture = net_pnl / mfe if mfe > 1e-9 else 0
        s += _clamp(capture * 20, -10, 15)
    if hold_sec > 3600:
        s -= 5
    if exit_reason in ("TP", "TP-PARTIAL", "PARTIAL-TRAIL"):
        s += 8
    elif exit_reason in ("SL", "SL-TRAIL"):
        s -= 5
    elif exit_reason == "MOMENTUM-FADE" and net_pnl > 0:
        s += 4
    return round(_clamp(s, 0, 100), 1)


def build_learning_snapshot(
    *,
    signal: dict[str, Any] | None = None,
    ctx: dict[str, Any] | None = None,
    entry_reason: str = "",
) -> dict[str, Any]:
    """Açılış anı — kapanışta journal'a eklenir."""
    ctx = ctx or {}
    sig = signal or {}
    hybrid = sig.get("evrim_hybrid") or {}
    return {
        "entry_reason": entry_reason[:200] or str(sig.get("evrim_entry_reason") or "hybrid"),
        "score_breakdown": hybrid.get("components") or ctx.get("hybrid_components") or {},
        "hybrid_score": hybrid.get("total_score") or ctx.get("hybrid_score"),
        "hybrid_tier": hybrid.get("tier") or ctx.get("hybrid_tier"),
        "market_regime": ctx.get("market_regime") or ctx.get("regime"),
        "indicators": (ctx.get("mtf") or {}).get("summary") or ctx.get("mtf"),
        "volume_state": ctx.get("vo") or {
            "vol_ratio": ctx.get("vol_ratio"),
            "rel_volume": (ctx.get("vo") or {}).get("rel_volume"),
        },
        "orderbook_state": {
            "spread_pct": ctx.get("spread_pct"),
            "vo": (ctx.get("vo") or {}).get("signals"),
        },
        "dynamic_exit": sig.get("evrim_dynamic_exit") or ctx.get("dynamic_exit"),
        "expectancy": (ctx.get("expectancy") or hybrid.get("expectancy")),
        "edge": float(sig.get("edge") or ctx.get("edge") or 0),
        "formula_score": float(sig.get("formula_score") or ctx.get("formula_score") or 0),
    }


def build_trade_record(
    closed: dict[str, Any],
    *,
    open_snapshot: dict[str, Any] | None = None,
    entry_reason: str = "",
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snap = open_snapshot or closed.get("learning_snapshot") or {}
    if ctx:
        snap = {**snap, **build_learning_snapshot(ctx=ctx, entry_reason=entry_reason)}
    ec = closed.get("entry_context") or {}
    entry_px = float(closed.get("entry_price") or 0)
    exit_px = float(closed.get("exit_price") or 0)
    stake = float(closed.get("stake_usd") or 1)
    mfe = float(closed.get("max_unreal_seen") or closed.get("mfe_usd") or 0)
    mae = float(closed.get("min_unreal_seen") or closed.get("mae_usd") or 0)
    net = float(closed.get("final_pnl") or closed.get("net_pnl") or 0)
    fees = float(closed.get("total_fees") or 0)
    hold = float(closed.get("duration") or 0)
    exit_reason = str(closed.get("exit_reason") or "")
    opened = closed.get("opened_at_iso") or closed.get("entry_time") or ""
    hour_utc = ""
    try:
        if opened:
            hour_utc = str(datetime.fromisoformat(opened.replace("Z", "+00:00")).hour)
    except Exception:
        hour_utc = ""

    slippage_bps = float(ec.get("slippage_bps") or snap.get("slippage_bps") or 0)
    spread_pct = float(ec.get("spread_pct") or 0)

    rec = {
        "at": _now_iso(),
        "symbol": str(closed.get("symbol") or ""),
        "direction": str(closed.get("side") or ""),
        "entry_reason": snap.get("entry_reason") or entry_reason or "unknown",
        "exit_reason": exit_reason,
        "score_breakdown": snap.get("score_breakdown") or ec.get("hybrid_components") or {},
        "market_regime": str(
            closed.get("market_regime") or snap.get("market_regime") or "chop"
        ),
        "indicators": snap.get("indicators") or {},
        "volume_state": snap.get("volume_state") or {},
        "orderbook_state": snap.get("orderbook_state") or {},
        "entry_price": entry_px,
        "exit_price": exit_px,
        "fee": round(fees, 4),
        "slippage_bps": slippage_bps,
        "spread_pct": spread_pct,
        "net_pnl": round(net, 4),
        "hold_time_sec": round(hold, 1),
        "mfe_usd": round(mfe, 4),
        "mae_usd": round(mae, 4),
        "trade_quality_score": 0.0,
        "hour_utc": hour_utc,
        "hybrid_score": snap.get("hybrid_score") or ec.get("hybrid_score"),
        "edge": snap.get("edge") or float(closed.get("edge") or 0),
        "source": closed.get("source") or "live",
    }
    rec["trade_quality_score"] = _compute_quality_score(
        net, mfe, mae, hold, exit_reason
    )
    return rec


def append_trade_record(record: dict[str, Any]) -> int:
    """Journal dosyasına ekle; toplam sayı döner."""
    _JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    try:
        from elite_trader.evrim_training import load_training_state, _save_training_state

        st = load_training_state()
        n = int(st.get("trade_journal_count") or 0) + 1
        st["trade_journal_count"] = n
        _save_training_state(st)
        if n % _ANALYSIS_EVERY_N == 0:
            run_periodic_analysis()
        return n
    except Exception:
        return 0


def load_recent_trades(limit: int = 500) -> list[dict[str, Any]]:
    if not _JOURNAL_PATH.is_file():
        return []
    lines = _JOURNAL_PATH.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def run_periodic_analysis(n: int = _ANALYSIS_EVERY_N) -> dict[str, Any]:
    """Son n işlem üzerinde analiz + pending patch (canlıya yazılmaz)."""
    records = load_recent_trades(n)
    if len(records) < max(10, n // 5):
        records = load_recent_trades(max(len(records), 20))
    if not records:
        return {"ok": False, "reason": "no_trades"}

    analysis = _analyze_trades(records)
    prof = get_profile(MODE_ID) or {}
    patch = propose_parameter_patch(analysis, prof)
    patch = clamp_parameter_patch(patch)

    try:
        from elite_trader.evrim_training import load_training_state, _save_training_state

        st = load_training_state()
        st["last_learning_analysis_at"] = _now_iso()
        st["last_learning_analysis"] = analysis
        st["pending_parameter_patch"] = patch
        st["pending_patch_requires_backtest"] = True
        st["pending_patch_created_at"] = _now_iso()
        _save_training_state(st)
    except Exception:
        pass

    return {"ok": True, "analysis": analysis, "pending_patch": patch, "trades_n": len(records)}


def _analyze_trades(records: list[dict[str, Any]]) -> dict[str, Any]:
    wins: list[dict] = []
    losses: list[dict] = []
    sym_pnl: dict[str, float] = defaultdict(float)
    hour_pnl: dict[str, float] = defaultdict(float)
    regime_pnl: dict[str, float] = defaultdict(float)
    regime_n: dict[str, int] = defaultdict(int)
    component_win: dict[str, list[float]] = defaultdict(list)
    component_loss: dict[str, list[float]] = defaultdict(list)
    tp_exits = sl_exits = 0
    edges_win: list[float] = []
    edges_loss: list[float] = []

    for r in records:
        net = float(r.get("net_pnl") or 0)
        sym = str(r.get("symbol") or "")
        sym_pnl[sym] += net
        hr = str(r.get("hour_utc") or "?")
        hour_pnl[hr] += net
        reg = str(r.get("market_regime") or "chop")
        regime_pnl[reg] += net
        regime_n[reg] += 1
        if net > 0:
            wins.append(r)
            edges_win.append(float(r.get("edge") or 0))
        else:
            losses.append(r)
            edges_loss.append(float(r.get("edge") or 0))
        ex = str(r.get("exit_reason") or "")
        if ex.startswith("TP") or ex in ("PARTIAL-TRAIL", "MOMENTUM-FADE"):
            tp_exits += 1
        if ex.startswith("SL"):
            sl_exits += 1
        bd = r.get("score_breakdown") or {}
        if isinstance(bd, dict):
            for k, v in bd.items():
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if net > 0:
                    component_win[k].append(fv)
                else:
                    component_loss[k].append(fv)

    def _top_keys(d: dict[str, float], n: int = 5, best: bool = True) -> list[tuple[str, float]]:
        items = sorted(d.items(), key=lambda x: x[1], reverse=best)
        return items[:n]

    profitable_signals = []
    losing_signals = []
    for k, vals in component_win.items():
        if vals and sum(vals) / len(vals) > 12:
            profitable_signals.append(k)
    for k, vals in component_loss.items():
        if vals and sum(vals) / len(vals) > 12:
            losing_signals.append(k)

    n = len(records)
    wr = len(wins) / n * 100 if n else 0
    tp_sl_ratio = tp_exits / max(1, sl_exits)
    avg_edge_win = sum(edges_win) / len(edges_win) if edges_win else 0
    avg_edge_loss = sum(edges_loss) / len(edges_loss) if edges_loss else 0
    edge_too_low = avg_edge_loss > 0 and avg_edge_win < avg_edge_loss * 1.1

    return {
        "trades_n": n,
        "win_rate_pct": round(wr, 1),
        "profitable_signals": profitable_signals[:8],
        "losing_signals": losing_signals[:8],
        "best_symbols": _top_keys(sym_pnl, 5, True),
        "worst_symbols": _top_keys(sym_pnl, 5, False),
        "best_hours": _top_keys(hour_pnl, 4, True),
        "worst_hours": _top_keys(hour_pnl, 4, False),
        "regime_pnl": dict(regime_pnl),
        "harmful_regimes": [
            k for k, v in regime_pnl.items() if v < 0 and regime_n[k] >= 3
        ],
        "tp_sl_ratio": round(tp_sl_ratio, 2),
        "tp_sl_ok": 0.8 <= tp_sl_ratio <= 2.5,
        "edge_threshold_low": edge_too_low,
        "avg_edge_win": round(avg_edge_win, 3),
        "avg_edge_loss": round(avg_edge_loss, 3),
        "net_pnl_sum": round(sum(float(r.get("net_pnl") or 0) for r in records), 2),
    }


def propose_parameter_patch(
    analysis: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Analiz sonucu — sınırlar içinde öneri (henüz canlı değil)."""
    patch: dict[str, Any] = {}
    wr = float(analysis.get("win_rate_pct") or 0)
    min_sc = int(profile.get("evrim_min_total_score") or 55)
    edge = float(profile.get("min_edge") or 0.10)
    tp = float(profile.get("tp_stake_pct") or 0.006)
    sl = float(profile.get("sl_stake_pct") or 0.0025)
    max_open = int(profile.get("max_open") or 11)
    active = float(profile.get("active_capital_pct") or 0.70)

    if wr < 42:
        patch["evrim_min_total_score"] = min_sc + 1
        patch["min_edge"] = edge + 0.02
    elif wr > 52:
        patch["evrim_min_total_score"] = max(48, min_sc - 1)

    if analysis.get("edge_threshold_low"):
        patch["min_edge"] = edge + 0.03

    if not analysis.get("tp_sl_ok"):
        ratio = float(analysis.get("tp_sl_ratio") or 1)
        if ratio < 0.8:
            patch["tp_stake_pct"] = tp * 1.05
            patch["sl_stake_pct"] = sl * 0.95
        elif ratio > 2.5:
            patch["tp_stake_pct"] = tp * 0.95
            patch["sl_stake_pct"] = sl * 1.05

    harmful = analysis.get("harmful_regimes") or []
    if "chop" in harmful or "news_shock" in harmful:
        patch["evrim_min_total_score"] = min_sc + 1
        patch["active_capital_pct"] = active - 0.03

    worst_hours = analysis.get("worst_hours") or []
    if worst_hours and wr < 45:
        patch["max_open"] = max_open - 1

    return clamp_parameter_patch(patch)


def apply_pending_patch_after_backtest(summary: dict[str, Any]) -> dict[str, Any]:
    """
    Otomatik test: journal 500 + BT + 30dk forward → karşılaştır → kabul/rollback.
    """
    try:
        from elite_trader.evrim_param_validator import validate_and_apply_pending_patch

        return validate_and_apply_pending_patch(summary)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)[:120]}


def record_trade_from_backtest(
    *,
    symbol: str,
    side: str,
    entry: float,
    exit_px: float,
    win: bool,
    exit_tag: str,
    dec_context: dict[str, Any],
    dec_components: dict[str, float],
    total_score: float,
    regime_id: str,
    profile: dict[str, Any],
    stake_est: float,
    fees: float,
    hold_sec: float = 300.0,
    mfe: float = 0.0,
    mae: float = 0.0,
) -> None:
    """Backtest simülasyon kaydı."""
    gross = (
        stake_est * float(profile.get("tp_stake_pct") or 0.006) * 0.98
        if win
        else -stake_est * float(profile.get("sl_stake_pct") or 0.0025)
    )
    closed = {
        "symbol": symbol,
        "side": side,
        "entry_price": entry,
        "exit_price": exit_px,
        "exit_reason": exit_tag,
        "final_pnl": gross - fees,
        "net_pnl": gross - fees,
        "total_fees": fees,
        "stake_usd": stake_est,
        "duration": hold_sec,
        "max_unreal_seen": mfe if mfe else max(gross, 0.01),
        "min_unreal_seen": mae,
        "market_regime": regime_id,
        "source": "backtest",
        "learning_snapshot": build_learning_snapshot(
            ctx={
                **dec_context,
                "hybrid_score": total_score,
                "hybrid_components": dec_components,
                "market_regime": regime_id,
            },
            entry_reason=dec_context.get("reason_enter") or "hybrid_bt",
        ),
    }
    append_trade_record(build_trade_record(closed))
