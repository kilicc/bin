"""9005 — zararlı kapanışları arka planda analiz et; öneri üret (otomatik uygulama yok)."""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_REGISTRY = _ROOT / "data" / "elite_9005_learning_registry.json"
_PROPOSALS = _ROOT / "data" / "elite_9005_proposals.json"
_POSTMORTEM = _ROOT / "data" / "elite_9005_loss_postmortem.json"

_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=500)
_worker_started = False
_worker_lock = threading.Lock()
_seen_trade_keys: set[str] = set()


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    if os.getenv("ELITE_LEARNER_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        return False
    port = os.environ.get("BINANCE_ELITE_PORT", "")
    profile = os.environ.get("PROFILE_NAME", "")
    return port == "9005" or "9005" in profile or "8300_9005" in profile


def auto_apply() -> bool:
    return os.getenv("ELITE_LEARNER_AUTO_APPLY", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_registry() -> dict[str, Any]:
    if not _REGISTRY.is_file():
        return {"patterns": {}, "trades": [], "updated_at": None}
    try:
        return json.loads(_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {"patterns": {}, "trades": [], "updated_at": None}


def _save_registry(data: dict[str, Any]) -> None:
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    trades = data.get("trades") or []
    if len(trades) > 600:
        data["trades"] = trades[-600:]
    _REGISTRY.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_proposals() -> dict[str, Any]:
    if not _PROPOSALS.is_file():
        return {"proposals": [], "updated_at": None}
    try:
        return json.loads(_PROPOSALS.read_text(encoding="utf-8"))
    except Exception:
        return {"proposals": [], "updated_at": None}


def _save_proposals(data: dict[str, Any]) -> None:
    _PROPOSALS.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    props = data.get("proposals") or []
    if len(props) > 120:
        data["proposals"] = props[-120:]
    _PROPOSALS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def _planned(stake: float) -> tuple[float, float]:
    tp_pct = _env_float("ELITE_TP_STAKE_PCT", 0.010)
    sl_pct = _env_float("ELITE_SL_STAKE_PCT", 0.015)
    trig = _env_float("ELITE_TP_TRIGGER_FRAC", 0.98)
    s = max(stake, 1.0)
    return s * tp_pct * trig, s * sl_pct


def _trade_key(row: dict[str, Any]) -> str:
    return (
        f"{row.get('id')}:{row.get('symbol')}:{_pnl(row):.4f}:"
        f"{row.get('exit_time') or row.get('exit_reason')}"
    )


def _classify(row: dict[str, Any]) -> str:
    stake = float(row.get("stake_usd") or 250)
    pnl = _pnl(row)
    _, sl_plan = _planned(stake)
    ex = str(row.get("exit_reason") or "").upper()
    ratio = abs(pnl) / max(sl_plan, 0.01) if pnl < 0 else 0.0
    if "SL-EMERGENCY" in ex or ratio >= 3.0:
        return "severe_sl_overshoot"
    if ratio >= 1.5:
        return "moderate_sl_overshoot"
    if pnl < 0:
        return "planned_sl_band"
    return "win"


def _update_patterns(reg: dict[str, Any], row: dict[str, Any]) -> None:
    sym = str(row.get("symbol") or "").upper()
    if not sym:
        return
    patterns: dict[str, Any] = reg.setdefault("patterns", {})
    st = patterns.setdefault(
        sym,
        {
            "loss_count": 0,
            "win_count": 0,
            "sl_emergency_count": 0,
            "sum_loss_usd": 0.0,
            "max_loss_usd": 0.0,
            "last_class": "",
            "last_ts": None,
        },
    )
    pnl = _pnl(row)
    cls = _classify(row)
    st["last_class"] = cls
    st["last_ts"] = _now_iso()
    if pnl < 0:
        st["loss_count"] = int(st.get("loss_count") or 0) + 1
        st["sum_loss_usd"] = round(float(st.get("sum_loss_usd") or 0) + pnl, 2)
        st["max_loss_usd"] = round(min(float(st.get("max_loss_usd") or 0), pnl), 2)
        if "SL-EMERGENCY" in str(row.get("exit_reason") or "").upper():
            st["sl_emergency_count"] = int(st.get("sl_emergency_count") or 0) + 1
    elif pnl > 0:
        st["win_count"] = int(st.get("win_count") or 0) + 1


def _recent_symbol_losses(reg: dict[str, Any], symbol: str, hours: float = 72.0) -> int:
    cutoff = time.time() - hours * 3600.0
    n = 0
    for t in reg.get("trades") or []:
        if str(t.get("symbol") or "").upper() != symbol.upper():
            continue
        if _pnl(t) >= 0:
            continue
        ts = t.get("analyzed_at") or t.get("exit_time")
        if not ts:
            n += 1
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.timestamp() >= cutoff:
                n += 1
        except Exception:
            n += 1
    return n


def _proposal_exists(proposals: list[dict[str, Any]], rule_id: str) -> bool:
    for p in proposals:
        if p.get("rule_id") == rule_id and p.get("status") == "pending":
            return True
    return False


def _add_proposal(
    proposals: list[dict[str, Any]],
    *,
    rule_id: str,
    title: str,
    detail: str,
    suggested_env: dict[str, str],
    evidence: dict[str, Any],
    priority: int = 5,
) -> None:
    if _proposal_exists(proposals, rule_id):
        return
    proposals.append(
        {
            "id": str(uuid.uuid4())[:8],
            "rule_id": rule_id,
            "status": "pending",
            "created_at": _now_iso(),
            "title": title,
            "detail": detail,
            "suggested_env": suggested_env,
            "evidence": evidence,
            "priority": priority,
            "auto_apply": False,
        }
    )
    print(f"  📋 STRATEJİ ÖNERİSİ [{priority}]: {title}")
    print(f"      {detail}")


def _add_strategy_insight(
    reg: dict[str, Any],
    *,
    insight_id: str,
    title: str,
    detail: str,
    symbols: list[str] | None = None,
    priority: int = 5,
) -> None:
    """Geçmişten öğrenme notu — giriş veto değil; panelde strateji özeti."""
    insights: list[dict[str, Any]] = reg.setdefault("strategy_insights", [])
    sym_set = {str(s).upper() for s in (symbols or []) if s}
    for ins in insights:
        if ins.get("insight_id") == insight_id:
            ins["title"] = title
            ins["detail"] = detail
            ins["priority"] = priority
            ins["updated_at"] = _now_iso()
            prev = {str(x).upper() for x in (ins.get("symbols") or [])}
            ins["symbols"] = sorted(prev | sym_set)
            return
    insights.append(
        {
            "insight_id": insight_id,
            "title": title,
            "detail": detail,
            "symbols": sorted(sym_set),
            "priority": priority,
            "updated_at": _now_iso(),
        }
    )
    if len(insights) > 40:
        reg["strategy_insights"] = sorted(
            insights, key=lambda x: -int(x.get("priority") or 0)
        )[:40]


def _generate_proposals(reg: dict[str, Any], row: dict[str, Any]) -> None:
    data = _load_proposals()
    proposals: list[dict[str, Any]] = list(data.get("proposals") or [])
    sym = str(row.get("symbol") or "").upper()
    stake = float(row.get("stake_usd") or 250)
    pnl = _pnl(row)
    if pnl >= 0:
        _save_proposals(data)
        return

    _, sl_plan = _planned(stake)
    ex = str(row.get("exit_reason") or "")
    ratio = abs(pnl) / max(sl_plan, 0.01)
    cls = _classify(row)
    pat = (reg.get("patterns") or {}).get(sym) or {}

    if "SL-EMERGENCY" in ex.upper() or ratio >= 3.0:
        _add_proposal(
            proposals,
            rule_id="sl_instant_no_emergency",
            title="Plan SL anında kapat (SL-EMERGENCY yok)",
            detail=(
                f"{sym}: zarar ${pnl:.2f} plan SL ${sl_plan:.2f} katı ({ratio:.1f}×). "
                "Acil çıkış yolu kaybı büyütüyor."
            ),
            suggested_env={
                "ELITE_SL_EMERGENCY_MULT": "1.0",
            },
            evidence={"symbol": sym, "pnl": pnl, "ratio": round(ratio, 2), "exit": ex},
            priority=10,
        )

    if stake >= 700:
        cap = str(int(min(500, max(250, stake * 0.45))))
        _add_proposal(
            proposals,
            rule_id=f"stake_cap_{cap}",
            title=f"Tek işlem stake tavanı (~${cap})",
            detail=(
                f"{sym}: stake ${stake:.0f} ile zarar ${pnl:.2f}. "
                "Büyük stake + küçük TP = tail risk."
            ),
            suggested_env={"ELITE_MAX_STAKE_USD": cap},
            evidence={"symbol": sym, "stake": stake, "pnl": pnl},
            priority=8,
        )

    recent_losses = _recent_symbol_losses(reg, sym)
    if recent_losses >= 2 or int(pat.get("sl_emergency_count") or 0) >= 2:
        _add_strategy_insight(
            reg,
            insight_id=f"temkin_{sym}",
            title=f"{sym} — geçmişten temkin",
            detail=(
                f"Son 72 saatte {recent_losses} zarar; SL-EMERGENCY kaydı "
                f"{pat.get('sl_emergency_count', 0)}. Canlıda temkinli giriş (daha yüksek edge/skor); "
                "gölge modda «Temkinli» ile karşılaştırın. Sembol engeli önerilmez."
            ),
            symbols=[sym],
            priority=7,
        )

    if cls == "planned_sl_band" and stake >= 400 and ratio <= 1.8:
        _add_proposal(
            proposals,
            rule_id="breakeven_after_mfe",
            title="Kısmi kâr kilidi (breakeven / hafif STALE)",
            detail=(
                f"{sym}: planlı SL bandında kapandı (${pnl:.2f}). "
                "TP'ye ulaşmadan yeşile dönüp kırmızıya dönen işlemler için "
                "ELITE_STALE_TP veya MFE breakeven düşünün."
            ),
            suggested_env={
                "ELITE_STALE_TP_ENABLED": "1",
                "ELITE_STALE_TP_MIN_AGE_MIN": "2",
            },
            evidence={"symbol": sym, "class": cls, "pnl": pnl},
            priority=5,
        )

    entry = float(row.get("entry_price") or 0)
    if entry > 0 and entry < 0.05:
        _add_strategy_insight(
            reg,
            insight_id="low_price_caution",
            title="Düşük fiyatlı coinlerde temkin",
            detail=(
                f"{sym} giriş ${entry:.6f} — slipaj riski. "
                "İnceleyip uygulayabileceğiniz strateji: min giriş fiyatı veya stake tavanı."
            ),
            symbols=[sym],
            priority=6,
        )

    data["proposals"] = proposals
    _save_proposals(data)


def _analyze_one(row: dict[str, Any]) -> None:
    key = _trade_key(row)
    if key in _seen_trade_keys:
        return
    _seen_trade_keys.add(key)

    reg = _load_registry()
    stake = float(row.get("stake_usd") or 250)
    tp_plan, sl_plan = _planned(stake)
    pnl = _pnl(row)
    record = {
        **{
            k: row.get(k)
            for k in (
                "id",
                "symbol",
                "side",
                "entry_price",
                "exit_price",
                "stake_usd",
                "leverage",
                "exit_reason",
                "entry_time",
                "exit_time",
                "duration",
                "signal_strength",
                "formula_score",
            )
        },
        "final_pnl": pnl,
        "planned_tp_usd": round(tp_plan, 2),
        "planned_sl_usd": round(sl_plan, 2),
        "loss_vs_planned_sl": (
            round(abs(pnl) / max(sl_plan, 0.01), 2) if pnl < 0 else 0.0
        ),
        "class": _classify(row),
        "analyzed_at": _now_iso(),
    }
    trades: list[dict[str, Any]] = reg.setdefault("trades", [])
    trades.append(record)
    _update_patterns(reg, row)
    _save_registry(reg)

    if pnl < 0:
        _generate_proposals(reg, row)


def _worker_loop() -> None:
    while True:
        try:
            item = _queue.get(timeout=2.0)
        except queue.Empty:
            continue
        try:
            _analyze_one(item)
        except Exception as exc:
            print(f"  ⚠ LossLearner: {exc}")
        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker_started
    if not enabled():
        return
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(
            target=_worker_loop, name="elite-loss-learner", daemon=True
        )
        t.start()
        _worker_started = True


def enqueue_loss_analysis(closed: dict[str, Any]) -> None:
    """Kapanış sonrası — bloklamaz."""
    if not enabled():
        return
    _ensure_worker()
    try:
        _queue.put_nowait(dict(closed))
    except queue.Full:
        print("  ⚠ LossLearner kuyruk dolu — analiz atlandı")


def scan_interval_sec() -> float:
    return _env_float("ELITE_LEARNER_SCAN_MIN", 15.0) * 60.0


_last_periodic_scan: float = 0.0


def maybe_periodic_scan(closed_list: list[dict[str, Any]]) -> None:
    global _last_periodic_scan
    if not enabled():
        return
    now = time.time()
    if now - _last_periodic_scan < scan_interval_sec():
        return
    _last_periodic_scan = now
    for row in [c for c in closed_list if _pnl(c) < 0][-25:]:
        enqueue_loss_analysis(row)


def bootstrap_from_postmortem() -> int:
    if not enabled() or not _POSTMORTEM.is_file():
        return 0
    try:
        raw = json.loads(_POSTMORTEM.read_text(encoding="utf-8"))
    except Exception:
        return 0
    n = 0
    for row in (raw.get("all_losses") or [])[-80:]:
        if _pnl(row) >= 0:
            continue
        enqueue_loss_analysis(
            {
                "id": row.get("id"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "entry_price": row.get("entry_price"),
                "stake_usd": row.get("stake_usd"),
                "exit_reason": row.get("exit_reason"),
                "final_pnl": row.get("final_pnl"),
                "exit_time": "bootstrap",
            }
        )
        n += 1
    return n


def bootstrap_from_logs(max_files: int = 2) -> int:
    if not enabled():
        return 0
    log_dir = _ROOT / "logs"
    files = sorted(log_dir.glob("binance_elite_8300_9005.log*"))[-max_files:]
    open_re = re.compile(
        r"✅ (LONG|SHORT) (\w+) @ \$([\d.]+) \| (\d+)x \| stake=\$([\d.]+)"
    )
    close_re = re.compile(r"✅ Closed #(\d+): (\w+) \| \$([-\d.]+)")
    exit_re = re.compile(r"Borsa kapanış (\w+) ([\w-]+) qty=")
    pending: dict[str, dict[str, Any]] = {}
    n = 0
    for lf in files:
        for line in lf.read_text(errors="replace").splitlines():
            m = open_re.search(line)
            if m:
                pending[m.group(2)] = {
                    "side": m.group(1),
                    "symbol": m.group(2),
                    "entry_price": float(m.group(3)),
                    "stake_usd": float(m.group(5)),
                }
                continue
            m = exit_re.search(line)
            if m and m.group(1) in pending:
                pending[m.group(1)]["exit_reason"] = m.group(2)
                continue
            m = close_re.search(line)
            if m:
                sym = m.group(2)
                pnl = float(m.group(3))
                if pnl >= 0:
                    pending.pop(sym, None)
                    continue
                base = pending.pop(sym, {})
                enqueue_loss_analysis(
                    {
                        "id": int(m.group(1)),
                        "symbol": sym,
                        "final_pnl": pnl,
                        **base,
                        "exit_time": "log_bootstrap",
                    }
                )
                n += 1
    return n


def get_proposal(proposal_id: str) -> dict[str, Any] | None:
    for p in _load_proposals().get("proposals") or []:
        if p.get("id") == proposal_id:
            return p
    return None


def ensure_bootstrap_proposals() -> None:
    """Kullanıcı onaylı denemeler — kuyrukta bekleyen öneri (otomatik uygulanabilir)."""
    data = _load_proposals()
    proposals: list[dict[str, Any]] = list(data.get("proposals") or [])
    _add_proposal(
        proposals,
        rule_id="spike_quick_scalp",
        title="Spike hızlı scalp (ücret+marj sonrası erken çıkış)",
        detail=(
            "Fee sonrası kısa yeşil pencerede SPIKE-QUICK ile çık; pozisyon kontrolü 0.5sn."
        ),
        suggested_env={
            "ELITE_SPIKE_QUICK_TP_ENABLED": "1",
            "ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC": "40",
            "ELITE_SPIKE_QUICK_TP_FEE_MULT": "1.08",
            "ELITE_SPIKE_QUICK_TP_MAX_FRAC": "0.72",
            "ELITE_POSITION_CHECK_SEC": "0.5",
            "ELITE_STALE_TP_ENABLED": "1",
            "ELITE_STALE_TP_MIN_AGE_MIN": "0.75",
            "ELITE_STALE_MODE": "flat_release",
        },
        evidence={"source": "user_spike_scalp_request"},
        priority=9,
    )
    for p in proposals:
        if p.get("rule_id") == "spike_quick_scalp":
            p["auto_apply"] = True
    data["proposals"] = proposals
    _save_proposals(data)


def list_proposals(*, status: str | None = "pending") -> list[dict[str, Any]]:
    data = _load_proposals()
    props = data.get("proposals") or []
    if status:
        props = [p for p in props if p.get("status") == status]
    return sorted(
        props, key=lambda p: (-int(p.get("priority") or 0), p.get("created_at") or "")
    )


def set_proposal_status(proposal_id: str, status: str) -> bool:
    if status not in ("pending", "approved", "rejected", "archived"):
        return False
    data = _load_proposals()
    ok = False
    for p in data.get("proposals") or []:
        if p.get("id") == proposal_id:
            p["status"] = status
            p["resolved_at"] = _now_iso()
            ok = True
            if status == "approved":
                print(f"  ✓ Öneri onaylandı (manuel env): {p.get('title')}")
                for k, v in (p.get("suggested_env") or {}).items():
                    print(f"      {k}={v}")
            break
    if ok:
        _save_proposals(data)
    return ok


def snapshot_for_ui() -> dict[str, Any]:
    from elite_trader.proposal_auto_apply import (
        DEFAULT_AUTO_RULES,
        is_approvable,
    )

    reg = _load_registry()
    patterns = reg.get("patterns") or {}
    worst = sorted(
        patterns.items(),
        key=lambda x: float((x[1] or {}).get("sum_loss_usd") or 0),
    )[:8]
    pending = list_proposals(status="pending")
    pending = [
        p
        for p in pending
        if not str(p.get("rule_id") or "").startswith("symbol_caution")
        and str(p.get("rule_id") or "") != "low_price_veto"
    ]
    for p in pending:
        p["auto_eligible"] = is_approvable(p)
    insights = sorted(
        (reg.get("strategy_insights") or []),
        key=lambda x: (-int(x.get("priority") or 0), x.get("updated_at") or ""),
    )[:15]
    return {
        "enabled": enabled(),
        "auto_apply": auto_apply(),
        "auto_apply_rules": sorted(
            {
                x.strip()
                for x in os.getenv("ELITE_LEARNER_AUTO_APPLY_RULES", "").split(",")
                if x.strip()
            }
            or DEFAULT_AUTO_RULES
        ),
        "queue_size": _queue.qsize(),
        "trades_analyzed": len(reg.get("trades") or []),
        "pending_proposals": len(pending),
        "proposals": pending[:8],
        "strategy_insights": insights,
        "worst_symbols": [
            {
                "symbol": sym,
                "loss_count": st.get("loss_count"),
                "sl_emergency_count": st.get("sl_emergency_count"),
                "sum_loss_usd": st.get("sum_loss_usd"),
            }
            for sym, st in worst
            if float((st or {}).get("sum_loss_usd") or 0) < 0
        ],
        "updated_at": reg.get("updated_at"),
    }


def start_background() -> None:
    if not enabled():
        return
    _ensure_worker()
    n1 = bootstrap_from_postmortem()
    n2 = bootstrap_from_logs(2)
    if n1 or n2:
        print(
            f"  🧠 LossLearner bootstrap: {n1} postmortem + {n2} log zararı kuyruğa alındı"
        )
