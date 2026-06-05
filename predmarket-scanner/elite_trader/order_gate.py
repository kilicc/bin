"""
Aşama 1 — Order gate: live/paper routing, güvenlik, log.

Strateji/filtre/TP-SL ayarlarına dokunmaz.
Yalnızca hangi modun Binance Futures motoruna gideceğini belirler.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from elite_trader.futures_order_router import RouteResult, route_order_intent
from elite_trader.mode_registry import MODE_IDS, MODE_META, resolve_mode_id

_ROOT = Path(__file__).resolve().parent.parent
_ROUTE_LOG = _ROOT / "data" / "order_route_log.jsonl"
_recent_routes: list[dict[str, Any]] = []

ORDER_ROUTE_LIVE = "BINANCE_FUTURES_LIVE_ENGINE"
ORDER_ROUTE_PAPER = "PAPER_ENGINE"


class PaperModeOrderBlockedError(RuntimeError):
    """Paper mod Binance order endpoint çağıramaz."""


@dataclass
class OrderGateResult:
    mode_id: str
    mode_name: str
    active_futures_mode: str
    is_live_candidate: bool
    is_paper: bool
    strategy_source: str
    symbol: str
    side: str
    entry_reason: str
    score_total: float
    expected_net_pnl: float
    order_route: str
    send_live: bool
    allow_binance_send: bool
    order_sent: bool
    reason: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_log_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["is_paper"] = self.is_paper
        return d


def _mode_name(mode_id: str) -> str:
    meta = MODE_META.get(resolve_mode_id(mode_id)) or {}
    return str(meta.get("display_name") or mode_id.upper())


def build_order_intent(
    mode_id: str,
    *,
    symbol: str = "",
    side: str = "",
    signal: dict[str, Any] | None = None,
    entry_reason: str = "",
    strategy_source: str = "mode_profile",
) -> dict[str, Any]:
    sig = signal or {}
    mid = resolve_mode_id(mode_id)
    hybrid = sig.get("evrim_hybrid") or {}
    return {
        "mode_id": mid,
        "mode_name": _mode_name(mid),
        "symbol": str(symbol or sig.get("symbol") or ""),
        "side": str(side or sig.get("type") or sig.get("side") or ""),
        "entry_reason": entry_reason or str(sig.get("evrim_entry_reason") or sig.get("reason") or ""),
        "score_total": float(sig.get("score_total") or hybrid.get("total_score") or 0),
        "expected_net_pnl": float(
            sig.get("expected_net_pnl")
            or hybrid.get("expected_net_pnl_usd")
            or 0
        ),
        "strategy_source": strategy_source,
        "signal": sig,
    }


def route_order(
    mode_id: str,
    intent: dict[str, Any],
    *,
    active_futures_mode: str | None,
    api_healthy: bool = True,
    live_orders_enabled: bool = True,
) -> OrderGateResult:
    """mode_id == active_futures_mode → LIVE route; aksi halde PAPER."""
    mid = resolve_mode_id(mode_id)
    active = resolve_mode_id(active_futures_mode) if active_futures_mode else ""
    sym = str(intent.get("symbol") or "")
    side = str(intent.get("side") or intent.get("type") or "")

    base = route_order_intent(
        mid,
        intent,
        active_futures_mode=active or None,
        api_healthy=api_healthy,
        live_orders_enabled=live_orders_enabled,
    )

    is_live_candidate = bool(active) and (
        mid == active
        or (
            mid == "mega"
            and base.send_live
            and base.reason == "mega_secondary_live"
        )
    )
    if base.send_live and is_live_candidate:
        order_route = ORDER_ROUTE_LIVE
        is_paper = False
    else:
        order_route = ORDER_ROUTE_PAPER
        is_paper = True

    result = OrderGateResult(
        mode_id=mid,
        mode_name=_mode_name(mid),
        active_futures_mode=active,
        is_live_candidate=is_live_candidate,
        is_paper=is_paper,
        strategy_source=str(intent.get("strategy_source") or "mode_profile"),
        symbol=sym,
        side=side,
        entry_reason=str(intent.get("entry_reason") or "")[:200],
        score_total=float(intent.get("score_total") or 0),
        expected_net_pnl=float(intent.get("expected_net_pnl") or 0),
        order_route=order_route,
        send_live=base.send_live and order_route == ORDER_ROUTE_LIVE,
        allow_binance_send=False,
        order_sent=False,
        reason=base.reason,
    )
    log_route(result)
    return result


def run_live_preflight_checks(
    result: OrderGateResult,
    *,
    symbol_tradable: bool = True,
    balance_ok: bool = True,
    exposure_ok: bool = True,
    risk_filter_ok: bool = True,
    expected_net_ok: bool = True,
    spread_ok: bool = True,
    daily_risk_ok: bool = True,
    api_healthy: bool = True,
) -> OrderGateResult:
    """Live route sonrası — geçmeden Binance emri gönderilmez."""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    if result.order_route != ORDER_ROUTE_LIVE:
        add("route", False, ORDER_ROUTE_PAPER)
        result.checks = checks
        result.allow_binance_send = False
        result.reason = result.reason or "paper_route"
        log_route(result)
        return result

    add("api_healthy", api_healthy, "")
    add("symbol_tradable", symbol_tradable, result.symbol)
    add("balance_ok", balance_ok, "")
    add("exposure_ok", exposure_ok, "")
    add("risk_filter_ok", risk_filter_ok, "")
    add("expected_net_ok", expected_net_ok, str(result.expected_net_pnl))
    add("spread_ok", spread_ok, "")
    add("daily_risk_ok", daily_risk_ok, "")

    passed = all(c["ok"] for c in checks)
    result.checks = checks
    result.allow_binance_send = passed
    if not passed:
        failed = next(c["name"] for c in checks if not c["ok"])
        result.reason = f"live_preflight_failed:{failed}"
    else:
        result.reason = "live_preflight_ok"
    log_route(result)
    return result


def assert_binance_send_allowed(mode_id: str, active_futures_mode: str | None) -> None:
    """client.market_order öncesi — paper mod engeli."""
    mid = resolve_mode_id(mode_id)
    active = resolve_mode_id(active_futures_mode) if active_futures_mode else ""
    if not active or mid != active:
        raise PaperModeOrderBlockedError(
            f"mode {mid} is not active_futures_mode ({active or 'empty'})"
        )


def log_route(result: OrderGateResult | dict[str, Any]) -> None:
    global _recent_routes
    payload = result.to_log_dict() if isinstance(result, OrderGateResult) else dict(result)
    payload["timestamp"] = payload.get("timestamp") or time.time()
    _recent_routes.append(payload)
    _recent_routes = _recent_routes[-20:]
    try:
        _ROUTE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _ROUTE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    try:
        from elite_trader.data_lake.ingest import ingest_decision, ingest_decision_log

        ingest_decision(
            payload.get("mode_id") or "evrim",
            symbol=str(payload.get("symbol") or ""),
            side=str(payload.get("side") or ""),
            allowed=bool(payload.get("allow_binance_send") or payload.get("send_live")),
            reason=str(payload.get("reason") or "")[:240],
            execution_path="live" if payload.get("order_route") == ORDER_ROUTE_LIVE else "paper",
            order_sent=bool(payload.get("order_sent")),
            extra={
                "order_route": payload.get("order_route"),
                "active_futures_mode": payload.get("active_futures_mode"),
                "is_paper": payload.get("is_paper"),
                "mode_name": payload.get("mode_name"),
                "checks": payload.get("checks"),
            },
        )

        signal = payload.get("signal") or {}
        hybrid = signal.get("evrim_hybrid") if isinstance(signal, dict) else None
        hybrid = hybrid if isinstance(hybrid, dict) else {}
        reason_str = str(payload.get("reason") or "")
        is_live_send = bool(payload.get("allow_binance_send") or payload.get("send_live"))
        reject_r = reason_str if not is_live_send and reason_str else ""
        veto_r = reason_str if reason_str.startswith("veto") or "veto" in reason_str.lower() else ""
        ingest_decision_log(
            payload.get("mode_id") or "evrim",
            mode_name=str(payload.get("mode_name") or ""),
            active_futures_mode=str(payload.get("active_futures_mode") or ""),
            symbol=str(payload.get("symbol") or ""),
            side=str(payload.get("side") or ""),
            market_regime=str(signal.get("market_regime") or hybrid.get("market_regime") or ""),
            score_total=float(payload.get("score_total") or 0),
            score_breakdown=hybrid.get("score_breakdown") or signal.get("score_breakdown"),
            entry_reason=str(payload.get("entry_reason") or ""),
            reject_reason=reject_r,
            veto_reason=veto_r,
            risk_level=str(signal.get("risk_level") or hybrid.get("risk_level") or ""),
            expected_net_pnl=float(payload.get("expected_net_pnl") or 0),
            spread=float(signal.get("spread_pct") or hybrid.get("spread_pct") or 0),
            slippage_estimate=float(signal.get("slippage_estimate") or hybrid.get("slippage_estimate") or 0),
            expected_fee=float(signal.get("expected_fee") or hybrid.get("expected_fee_usd") or 0),
            expected_funding=float(signal.get("expected_funding") or hybrid.get("expected_funding_usd") or 0),
            order_route=str(payload.get("order_route") or ""),
            is_paper=bool(payload.get("is_paper")),
            order_sent=bool(payload.get("order_sent")),
            exchange_accepted=payload.get("exchange_accepted"),
            extra={
                "checks": payload.get("checks"),
                "strategy_source": payload.get("strategy_source"),
                "is_live_candidate": payload.get("is_live_candidate"),
                "allow_binance_send": payload.get("allow_binance_send"),
            },
        )
    except Exception:
        pass
    try:
        mid = str(payload.get("mode_id") or "evrim")
        if mid == "evrim" and payload.get("order_route") == ORDER_ROUTE_LIVE:
            from elite_trader.evrim_live_decisions import record_decision

            sig = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}
            v2 = sig.get("evrim_v2") or {}
            hybrid = sig.get("evrim_hybrid") or {}
            record_decision(
                symbol=str(payload.get("symbol") or ""),
                side=str(payload.get("side") or ""),
                allowed=bool(payload.get("allow_binance_send")),
                reason=str(payload.get("reason") or ""),
                final_score=v2.get("final_score") or hybrid.get("final_score"),
                expected_net_pnl=float(payload.get("expected_net_pnl") or hybrid.get("expected_net_pnl_usd") or 0),
                order_route=str(payload.get("order_route") or ""),
                preflight_ok=bool(payload.get("allow_binance_send")),
                order_sent=bool(payload.get("order_sent")),
                exchange_accepted=bool(payload.get("exchange_accepted")),
            )
    except Exception:
        pass


def mark_order_sent(mode_id: str, *, exchange_accepted: bool = True) -> None:
    if _recent_routes:
        _recent_routes[-1]["order_sent"] = True
        _recent_routes[-1]["exchange_accepted"] = exchange_accepted


def get_routing_status(active_futures_mode: str | None = None) -> dict[str, Any]:
    from elite_trader.mode_registry import enabled_mode_ids
    from elite_trader.panel_strategy import is_live_binance_motor

    active = resolve_mode_id(active_futures_mode) if active_futures_mode else ""
    enabled = list(enabled_mode_ids())
    live_mid = active if active and is_live_binance_motor(active) else ""
    paper_modes = [m for m in enabled if not is_live_binance_motor(m)]
    if active and not live_mid and active not in paper_modes:
        paper_modes = [active, *paper_modes]
    live_label = _mode_name(live_mid) if live_mid else None
    if active and not live_mid:
        live_label = f"{_mode_name(active)} (paper)"
    return {
        "active_futures_mode": active,
        "live_mode": live_mid or None,
        "live_mode_name": live_label,
        "paper_modes": paper_modes,
        "paper_mode_names": [_mode_name(m) for m in paper_modes],
        "order_route_live": ORDER_ROUTE_LIVE,
        "order_route_paper": ORDER_ROUTE_PAPER,
        "recent_routes": list(_recent_routes[-20:]),
        # Paralel evren: live motor kendi paper kitabına yazmaz; aday paylaşımlı
        "live_motor_parallel_paper": False,
        "shared_market_feed": True,
        "profiles_independent": True,
    }
