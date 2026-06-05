"""Mod başına Cursor analiz döngüsü — öneri sohbetini doldurur."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from elite_trader.plan_chats import INSIGHTS_CHAT_ID, append_messages, get_chat
from elite_trader.plan_mode_analysis import (
    build_mode_analysis_bundle,
    format_analysis_for_prompt,
)
from elite_trader.plan_modes import all_plan_mode_ids, cycle_interval_sec, mode_label
from elite_trader.plan_safe_apply import apply_mode_recommendations

_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data/plan_mode_cycle_state.json"
_lock = threading.Lock()
_last_global: float = 0.0


def _load_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {"modes": {}}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"modes": {}}


def _save_state(st: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def run_mode_cycle(
    mode_id: str,
    *,
    dash: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    live_closed: list[dict[str, Any]] | None = None,
    live_open: list[dict[str, Any]] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Tek mod için analiz + sohbet + güvenli uygulama."""
    from elite_trader.plan_advisor import advisor_reply
    from elite_trader.strategy_planner import plan_dashboard

    mid = mode_id
    interval = cycle_interval_sec()
    now = time.time()
    st = _load_state()
    modes = st.setdefault("modes", {})
    mst = modes.get(mid) or {}
    last = float(mst.get("last_run_ts") or 0)
    if not force and (now - last) < interval:
        return {"ok": True, "skipped": True, "mode_id": mid, "reason": "interval"}

    if dash is None:
        dash = plan_dashboard(snapshot or {}, live_closed=live_closed)
    bundle = build_mode_analysis_bundle(mid, live_closed=live_closed, live_open=live_open)
    prompt = format_analysis_for_prompt(bundle)
    lbl = mode_label(mid)
    answer, _advisor = advisor_reply(
        prompt,
        dash=dash,
        reports={mid: (dash.get("per_mode_losses") or {}).get(mid, {})},
        focus_mode=mid,
        history=[],
        snapshot=snapshot,
        can_apply=False,
    )
    if not answer:
        return {"ok": False, "error": "cursor_no_reply", "mode_id": mid}

    apply_out = apply_mode_recommendations(mid, bundle)
    apply_note = ""
    if apply_out.get("applied"):
        apply_note = f"\n\n✅ Otomatik uygulandı: {apply_out.get('message', '')}"
    elif apply_out.get("pending"):
        apply_note = f"\n\n📋 Öneri hazır (paper): {json.dumps(apply_out.get('patch', {}), ensure_ascii=False)}"

    stamp = time.strftime("%d.%m %H:%M", time.localtime())
    header = f"📊 {lbl} — analiz döngüsü ({stamp})\n"
    daily = bundle.get("daily") or {}
    header += (
        f"Günlük: {daily.get('pnl', 0)}$ / hedef {daily.get('target', 0)}$ · "
        f"açık {bundle.get('open_count', 0)} pozisyon (dokunulmadı)\n\n"
    )

    append_messages(
        mid,
        INSIGHTS_CHAT_ID,
        assistant=header + answer + apply_note,
        system=f"Otomatik mod analizi · {mid}",
    )

    modes[mid] = {"last_run_ts": now, "last_apply": apply_out.get("applied")}
    st["modes"] = modes
    _save_state(st)

    global _last_global
    _last_global = now
    return {
        "ok": True,
        "refreshed": True,
        "mode_id": mid,
        "apply": apply_out,
        "chat": get_chat(mid, INSIGHTS_CHAT_ID),
    }


def run_all_mode_cycles(
    *,
    dash: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    live_closed: list[dict[str, Any]] | None = None,
    live_open: list[dict[str, Any]] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    results = []
    for mid in all_plan_mode_ids():
        try:
            results.append(
                run_mode_cycle(
                    mid,
                    dash=dash,
                    snapshot=snapshot,
                    live_closed=live_closed,
                    live_open=live_open,
                    force=force,
                )
            )
        except Exception as exc:
            results.append({"ok": False, "mode_id": mid, "error": str(exc)[:200]})
    return {"ok": True, "results": results}


def start_plan_cycle_background(
    *,
    get_live_closed: Any,
    get_live_open: Any,
    get_snapshot: Any,
) -> None:
    """Arka plan thread — tüm modları sırayla tarar."""

    def _loop() -> None:
        while True:
            try:
                snap = get_snapshot()
                from elite_trader.strategy_planner import plan_dashboard

                dash = plan_dashboard(snap, live_closed=list(get_live_closed()))
                run_all_mode_cycles(
                    dash=dash,
                    snapshot=snap,
                    live_closed=list(get_live_closed()),
                    live_open=list(get_live_open()),
                )
            except Exception as exc:
                print(f"  ⚠ Plan mod döngüsü: {exc}")
            time.sleep(max(300, cycle_interval_sec()))

    if os.getenv("ELITE_PLAN_CYCLE_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        return
    t = threading.Thread(target=_loop, name="plan-mode-cycle", daemon=True)
    t.start()
    print(f"  ✓ Plan mod analiz döngüsü ({cycle_interval_sec() // 60} dk / mod)")
