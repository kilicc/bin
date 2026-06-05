"""Strateji plan panosu — mod bazlı zarar analizi, sohbet, PIN ile uygulama."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.loss_learner import snapshot_for_ui as learner_snapshot
from elite_trader.mode_profiles import PARALLEL_IDS, get_profile
from elite_trader.mode_registry import DEFAULT_ACTIVE_FUTURES_MODE, resolve_mode_id
from elite_trader.parallel_universe_engine import get_books
from elite_trader.panel_strategy import (
    active_execution_mode,
    active_view_mode,
    mode_catalog,
    mode_order,
)
from elite_trader.plan_advisor import (
    advisor_reply,
    advisor_status,
    build_action_items,
    fmt_pct,
    fmt_usd,
)
from elite_trader.plan_memory import snapshot_for_ui as plan_memory_snapshot
from elite_trader.plan_mode_analysis import build_mode_analysis_bundle
from elite_trader.plan_modes import all_plan_mode_ids, load_goals
from elite_trader.plan_pin import verify_pin
from elite_trader.settings_registry import (
    apply_live_prompt,
    apply_live_settings,
    apply_parallel_settings,
    apply_prompt,
    parse_prompt_to_live_patch,
    parse_prompt_to_patch,
    preview_live_patch,
    preview_parallel_patch,
    restart_live_bot,
)

_ROOT = Path(__file__).resolve().parent.parent
_POSTMORTEM = _ROOT / "data" / "elite_9005_loss_postmortem.json"
_MOTOR_ID = DEFAULT_ACTIVE_FUTURES_MODE

_MODE_ALIASES: dict[str, str] = {
    "ana hat": "evrim",
    "anahat": "evrim",
    "canlı": "evrim",
    "live": "evrim",
    "evrim": "evrim",
    "sentinel": "sentinel",
    "ana_hat": "evrim",
    "avcı": "hunter",
    "avci": "hunter",
    "şimşek": "berserk",
    "simsek": "berserk",
    "kalkan": "chop_master",
    "evrim": "evrim",
    "2x": "evrim",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def _trade_row(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("id"),
        "symbol": c.get("symbol"),
        "side": c.get("side"),
        "pnl": round(_pnl(c), 2),
        "reason": c.get("exit_reason") or "—",
        "exit_time": (c.get("exit_time") or c.get("closed_at") or "")[:19],
        "stake_usd": round(float(c.get("stake_usd") or 0), 2),
        "leverage": c.get("leverage"),
        "max_unreal_seen": c.get("max_unreal_seen"),
    }


def _build_mode_loss_report(
    mode_id: str,
    label: str,
    closed: list[dict[str, Any]],
    *,
    is_live: bool = False,
) -> dict[str, Any]:
    losses = [c for c in closed if _pnl(c) < 0]
    losses_sorted = sorted(losses, key=_pnl)[:12]
    by_reason: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "sum_usd": 0.0}
    )
    for c in losses:
        r = str(c.get("exit_reason") or "unknown").upper()
        by_reason[r]["count"] += 1
        by_reason[r]["sum_usd"] = round(by_reason[r]["sum_usd"] + _pnl(c), 2)
    total_loss = round(sum(_pnl(c) for c in losses), 2)
    closed_n = len(closed)
    loss_n = len(losses)
    wins = len([c for c in closed if _pnl(c) > 0])
    wr = round(wins / closed_n * 100, 1) if closed_n else None
    patterns: list[str] = []
    for r, st in sorted(by_reason.items(), key=lambda x: x[1]["sum_usd"]):
        if st["count"]:
            patterns.append(f"{r}: {st['count']}× ({st['sum_usd']:.0f}$)")
    analysis = ""
    if not losses:
        analysis = f"{label}: henüz kayıplı kapanış yok."
    else:
        top = losses_sorted[0]
        analysis = (
            f"{label}: {loss_n} kayıplı işlem, toplam {fmt_usd(total_loss)}, "
            f"başarı {fmt_pct(wr)}. En ağır kayıp {top.get('symbol')} "
            f"({fmt_usd(_pnl(top))}, {top.get('exit_reason')})."
        )
        if is_live:
            em = by_reason.get("SL-EMERGENCY", {}).get("count", 0)
            if em >= 3:
                analysis += (
                    f" SL-EMERGENCY {em} kez — plan SL'den sapma; sıkı SL veya min-hold gözden geçirin."
                )
    return {
        "mode_id": mode_id,
        "label": label,
        "is_live": is_live,
        "closed_count": closed_n,
        "loss_count": loss_n,
        "total_loss_usd": total_loss,
        "win_rate": wr,
        "by_exit_reason": dict(by_reason),
        "top_losses": [_trade_row(c) for c in losses_sorted[:8]],
        "analysis": analysis,
        "patterns": patterns,
    }


def _postmortem_live_hint() -> str:
    if not _POSTMORTEM.is_file():
        return ""
    try:
        data = json.loads(_POSTMORTEM.read_text(encoding="utf-8"))
        s = data.get("summary") or {}
        buckets = s.get("by_bucket") or {}
        parts = []
        for k, v in list(buckets.items())[:3]:
            parts.append(f"{k}: {v.get('count')}× ({v.get('sum', 0):.0f}$)")
        top = (s.get("top15_losses") or [])[:2]
        top_s = ", ".join(
            f"{t.get('symbol')} {t.get('final_pnl')}$" for t in top if t.get("symbol")
        )
        return (
            f"Ana Hat geçmiş postmortem ({s.get('total_losses', 0)} zarar): "
            + "; ".join(parts)
            + (f" · en ağır: {top_s}" if top_s else "")
        )
    except Exception:
        return ""


def per_mode_loss_reports(
    snapshot: dict[str, Any] | None = None,
    *,
    live_closed: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    snap = snapshot or {}
    modes = mode_catalog()
    reports: dict[str, dict[str, Any]] = {}
    live_list = live_closed if live_closed is not None else (
        (snap.get("positions") or {}).get("closed") or []
    )
    if snap.get("display_source") == "parallel" and live_closed is None:
        pass
    motor = active_execution_mode()
    reports[motor] = _build_mode_loss_report(
        motor,
        modes.get(motor, {}).get("label") or "Evrim",
        list(live_list),
        is_live=True,
    )
    pm_hint = _postmortem_live_hint()
    if pm_hint:
        reports[motor]["postmortem_hint"] = pm_hint
        reports[motor]["analysis"] += " " + pm_hint
    books = get_books()
    for mid in mode_order():
        if mid == motor:
            continue
        prof = modes.get(mid) or get_profile(mid) or {}
        closed = list((books.get(mid) or {}).get("closed") or [])
        reports[mid] = _build_mode_loss_report(
            mid,
            prof.get("short_label") or prof.get("label") or mid,
            closed,
            is_live=False,
        )
    return reports


def _mode_rows_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    report = (snapshot.get("elite") or {}).get("parallel_universes") or {}
    rows: list[dict[str, Any]] = []
    for m in report.get("modes") or []:
        d = m.get("dashboard") or {}
        rows.append(
            {
                "mode_id": m.get("mode_id"),
                "label": m.get("short_label") or m.get("label"),
                "is_live": bool(m.get("is_live")),
                "balance": d.get("balance"),
                "total_pnl": d.get("total_pnl"),
                "win_rate": d.get("win_rate"),
                "open_n": m.get("open_n", 0),
                "closed_n": m.get("closed_n", 0),
            }
        )
    return rows


def plan_dashboard(
    snapshot: dict[str, Any] | None = None,
    *,
    live_closed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    snap = snapshot or {}
    ll = learner_snapshot()
    summary = snap.get("summary") or {}
    loss_reports = per_mode_loss_reports(snap, live_closed=live_closed)
    live_open = list((snap.get("positions") or {}).get("open") or [])
    mode_daily: dict[str, dict[str, Any]] = {}
    for mid in all_plan_mode_ids():
        try:
            bundle = build_mode_analysis_bundle(
                mid,
                live_closed=live_closed,
                live_open=live_open if mid == active_execution_mode() else None,
            )
            mode_daily[mid] = bundle.get("daily") or {}
        except Exception:
            mode_daily[mid] = {}
    return {
        "plan_mode": True,
        "auto_apply": False,
        "apply_requires_pin": True,
        "updated_at": _now_iso(),
        "view_mode": active_view_mode(),
        "execution_mode": active_execution_mode(),
        "session": {
            "closed_trades": summary.get("closed_trades"),
            "win_rate": (
                round(float(summary["win_rate"]), 1)
                if summary.get("win_rate") is not None
                else None
            ),
            "realized_pnl": summary.get("realized_pnl"),
            "total_pnl": summary.get("total_pnl"),
            "open_count": summary.get("open_count"),
        },
        "modes": _mode_rows_from_snapshot(snap),
        "per_mode_losses": loss_reports,
        "insights": (ll.get("strategy_insights") or [])[:4],
        "worst_symbols": (ll.get("worst_symbols") or [])[:4],
        "pending_proposals": ll.get("pending_proposals") or 0,
        "learner_enabled": ll.get("enabled"),
        "trades_analyzed": ll.get("trades_analyzed"),
        "advisor_memory": plan_memory_snapshot(),
        "advisor": advisor_status(),
        "mode_goals": load_goals(),
        "plan_modes": all_plan_mode_ids(),
        "mode_daily": mode_daily,
    }


def _resolve_mode_id(prompt: str, mode_id: str | None) -> str | None:
    if mode_id:
        rid = resolve_mode_id(mode_id)
        if rid in mode_order():
            return rid
    t = (prompt or "").lower()
    for alias, mid in _MODE_ALIASES.items():
        if alias in t:
            return mid
    for mid in PARALLEL_IDS:
        if mid.replace("evren_", "") in t:
            return mid
    return None


def _detect_scope(prompt: str, mode_id: str | None) -> tuple[str, str | None]:
    mid = _resolve_mode_id(prompt, mode_id)
    if mid == active_execution_mode():
        return "live", None
    if mid and mid in mode_order():
        return "parallel", mid
    t = (prompt or "").lower()
    if re.search(r"ana hat|canlı|live|\.env|9005", t):
        return "live", None
    if re.search(r"paralel|avcı|avci|şimşek|simsek|kalkan|paper", t):
        return "parallel", mid or "hunter"
    vw = active_view_mode()
    if vw in mode_order() and vw != active_execution_mode():
        return "parallel", vw
    if vw == active_execution_mode():
        return "live", None
    return "parallel", mid or "hunter"


def _build_apply_prompt(
    scope: str, mode_id: str | None, user_prompt: str, patch: dict[str, Any]
) -> str:
    if scope == "live":
        parts = [f"Ana Hat (.env) uygula — plan: {user_prompt.strip()[:200]}"]
        for k, v in sorted(patch.items()):
            parts.append(f"{k}={v}")
        return "\n".join(parts)
    label = mode_id or "hunter"
    try:
        label = mode_catalog().get(mode_id or "", {}).get("short_label") or label
    except Exception:
        pass
    parts = [f"Paralel «{label}» uygula — plan: {user_prompt.strip()[:200]}"]
    for k, v in sorted(patch.items()):
        parts.append(f"  {k}={v}")
    return "\n".join(parts)


def plan_ask(
    prompt: str,
    *,
    snapshot: dict[str, Any] | None = None,
    mode_id: str | None = None,
    scope: str | None = None,
    history: list[dict[str, str]] | None = None,
    live_closed: list[dict[str, Any]] | None = None,
    chat_id: str | None = None,
) -> dict[str, Any]:
    text = (prompt or "").strip()
    if not text:
        return {"ok": False, "error": "Mesaj boş"}
    snap = snapshot or {}
    dash = plan_dashboard(snap, live_closed=live_closed)
    reports = dash.get("per_mode_losses") or {}
    focus_mid = _resolve_mode_id(text, mode_id) or mode_id

    use_scope = (scope or "").strip().lower() or None
    if use_scope == "live":
        target_scope, target_mode = "live", None
    elif use_scope == "parallel" and focus_mid and focus_mid in PARALLEL_IDS:
        target_scope, target_mode = "parallel", focus_mid
    else:
        target_scope, target_mode = _detect_scope(text, focus_mid)

    patch: dict[str, Any] = {}
    preview: dict[str, Any] | None = None
    tuning = bool(
        re.search(
            r"seçici|agresif|tp|sl|spike|stale|açık|cooldown|edge|formül|stake|uygula|ayarla|değiştir|aç|kapat",
            text.lower(),
        )
    )

    if target_scope == "live":
        patch = parse_prompt_to_live_patch(text)
        if patch:
            preview = preview_live_patch(patch)
    else:
        target_mode = target_mode or "hunter"
        patch = parse_prompt_to_patch(text, target_mode)
        if patch:
            preview = preview_parallel_patch(target_mode, patch)

    can_apply = bool(patch and preview and preview.get("ok"))
    apply_prompt_text = ""
    if can_apply:
        apply_prompt_text = _build_apply_prompt(target_scope, target_mode, text, patch)

    from elite_trader.plan_modes import normalize_mode_id
    from elite_trader.plan_chats import (
        INSIGHTS_CHAT_ID,
        append_messages,
        create_chat,
        history_for_llm,
    )

    bound_mode = normalize_mode_id(focus_mid or mode_id or active_execution_mode())
    cid = (chat_id or "").strip() or None
    if not cid:
        new_chat = create_chat(mode_id=bound_mode)
        cid = new_chat.get("id") if new_chat else INSIGHTS_CHAT_ID
    chat_history = history_for_llm(bound_mode, cid) if cid else (history or [])
    if not chat_history and history:
        chat_history = history

    answer, advisor_st = advisor_reply(
        text,
        dash=dash,
        reports=reports,
        focus_mode=focus_mid,
        history=chat_history,
        snapshot=snap,
        can_apply=can_apply,
    )

    action_items, detail_report = build_action_items(
        reports,
        focus_mode=focus_mid,
        preview=preview if can_apply else None,
        suggested_scope=target_scope,
        suggested_mode=target_mode,
    )

    from elite_trader.plan_memory import record_exchange

    record_exchange(
        text,
        answer,
        focus_mode=focus_mid,
        action_items=action_items,
    )

    if cid:
        append_messages(bound_mode, cid, user=text, assistant=answer)

    return {
        "ok": True,
        "chat_id": cid,
        "mode_id": bound_mode,
        "plan_mode": True,
        "applied": False,
        "can_apply": can_apply,
        "apply_requires_pin": True,
        "answer": answer,
        "advisor": advisor_st,
        "apply_prompt": apply_prompt_text,
        "action_items": action_items,
        "detail_report": detail_report,
        "suggested_scope": target_scope,
        "suggested_mode_id": target_mode,
        "focus_mode_id": focus_mid or target_mode,
        "patch": patch,
        "preview": preview,
        "dashboard": dash,
        "per_mode_losses": reports,
    }


def plan_apply(
    pin: str,
    *,
    snapshot: dict[str, Any] | None = None,
    scope: str | None = None,
    mode_id: str | None = None,
    patch: dict[str, Any] | None = None,
    prompt: str | None = None,
    restart: bool = False,
) -> dict[str, Any]:
    if not verify_pin(pin):
        return {"ok": False, "error": "Uygulama kodu yanlış (4 hane)"}
    target_scope = (scope or "parallel").strip().lower()
    target_mode = mode_id
    use_patch = dict(patch or {})

    if prompt and not use_patch:
        if target_scope == "live":
            use_patch = parse_prompt_to_live_patch(prompt)
        else:
            target_mode = target_mode or "hunter"
            use_patch = parse_prompt_to_patch(prompt, target_mode)
    if not use_patch:
        return {"ok": False, "error": "Uygulanacak ayar yok — önce sohbette öneri üretin"}

    try:
        if target_scope == "live":
            result = apply_live_settings(use_patch)
            restart_info = None
            if restart:
                restart_info = restart_live_bot()
            return {
                "ok": True,
                "applied": True,
                "scope": "live",
                "result": result,
                "restart": restart_info,
                "message": "Ana Hat ayarları uygulandı."
                + (" Bot yeniden başlatıldı." if restart else ""),
            }
        target_mode = target_mode or "hunter"
        if prompt and not patch:
            out = apply_prompt(target_mode, prompt)
            return {
                "ok": True,
                "applied": True,
                "scope": "parallel",
                "mode_id": target_mode,
                **out,
                "message": f"Paralel {target_mode} güncellendi.",
            }
        result = apply_parallel_settings(target_mode, use_patch)
        return {
            "ok": True,
            "applied": True,
            "scope": "parallel",
            "mode_id": target_mode,
            "result": result,
            "message": f"Paralel mod ({target_mode}) ayarları uygulandı.",
        }
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
