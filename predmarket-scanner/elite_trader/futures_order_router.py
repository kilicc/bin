"""Canlı emir yönlendirme — yalnızca active_futures_mode borsaya gider."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent
_SAFE_MODE_PATH = _ROOT / "data" / "system_safe_mode.json"
_SWITCH_LOG = _ROOT / "data" / "mode_switch_log.jsonl"


ORDER_ROUTE_LIVE = "BINANCE_FUTURES_LIVE_ENGINE"
ORDER_ROUTE_PAPER = "PAPER_ENGINE"


@dataclass
class RouteResult:
    send_live: bool
    is_paper: bool
    order_sent: bool
    reason: str
    log: str = ""
    mode_id: str = ""
    routed_to_paper: bool = False
    order_route: str = ORDER_ROUTE_PAPER
    active_futures_mode: str = ""


def is_safe_mode_active() -> bool:
    if not _SAFE_MODE_PATH.is_file():
        return False
    try:
        st = json.loads(_SAFE_MODE_PATH.read_text(encoding="utf-8"))
        return bool(st.get("active"))
    except Exception:
        return False


def set_safe_mode(active: bool, reason: str = "") -> None:
    _SAFE_MODE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SAFE_MODE_PATH.write_text(
        json.dumps(
            {
                "active": bool(active),
                "reason": reason[:200],
                "ts": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def log_mode_switch(old_mode: str, new_mode: str, *, trigger: str = "panel") -> None:
    line = json.dumps(
        {
            "ts": time.time(),
            "old": old_mode,
            "new": new_mode,
            "trigger": trigger,
        },
        ensure_ascii=False,
    )
    _SWITCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _SWITCH_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def route_order_intent(
    mode_id: str,
    intent: dict[str, Any],
    *,
    active_futures_mode: str | None,
    api_healthy: bool = True,
    live_orders_enabled: bool = True,
) -> RouteResult:
    """
    Canlı emir niyetini yönlendir.
    - API/safe mode kapalı → paper
    - mode_id != active_futures_mode → paper
    - Aksi halde canlı
    """
    mid = str(mode_id or "").strip().lower()
    active = str(active_futures_mode or "").strip().lower()
    sym = str(intent.get("symbol") or "?")

    def paper(reason: str, log: str = "") -> RouteResult:
        return RouteResult(
            send_live=False,
            is_paper=True,
            order_sent=False,
            reason=reason,
            log=log or reason,
            mode_id=mid,
            routed_to_paper=True,
            order_route=ORDER_ROUTE_PAPER,
            active_futures_mode=active,
        )

    if not live_orders_enabled:
        return paper("live_orders_disabled", log="routed_to_paper")
    if is_safe_mode_active():
        return paper("system_safe_mode", log="safe_mode_paper")
    if not api_healthy:
        return paper("api_unhealthy", log="api_paper_fallback")
    if not active:
        return paper("no_active_futures_mode", log="routed_to_paper")
    if mid != active:
        try:
            from elite_trader.mega_live import mega_live_enabled

            if mid == "mega" and mega_live_enabled():
                return RouteResult(
                    send_live=True,
                    is_paper=False,
                    order_sent=False,
                    reason="mega_secondary_live",
                    log=f"mega_live_route:{sym}",
                    mode_id=mid,
                    routed_to_paper=False,
                    order_route=ORDER_ROUTE_LIVE,
                    active_futures_mode=active,
                )
        except Exception:
            pass
        return paper(
            f"mode_not_active:{mid}!={active}",
            log="routed_to_paper",
        )
    return RouteResult(
        send_live=True,
        is_paper=False,
        order_sent=False,
        reason="live_route_candidate",
        log=f"live_route:{sym}",
        mode_id=mid,
        routed_to_paper=False,
        order_route=ORDER_ROUTE_LIVE,
        active_futures_mode=active,
    )


def paper_simulate(
    mode_id: str,
    intent: dict[str, Any],
    *,
    reason: str,
    on_paper: Callable[[str, dict[str, Any]], None] | None = None,
) -> RouteResult:
    if on_paper:
        try:
            on_paper(mode_id, intent)
        except Exception:
            pass
    return RouteResult(
        send_live=False,
        is_paper=True,
        order_sent=False,
        reason=reason,
        log="paper_simulate",
        mode_id=mode_id,
        routed_to_paper=True,
    )
