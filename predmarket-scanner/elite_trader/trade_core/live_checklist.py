"""EVRIM canlı geçiş checklist."""
from __future__ import annotations

from typing import Any

from elite_trader.panel_strategy import active_execution_mode, active_futures_mode
from elite_trader.trade_core.expectancy import compute_expectancy


def run_live_checklist(
    *,
    profile: dict[str, Any],
    signal: dict[str, Any] | None = None,
    api_healthy: bool = True,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    m = metrics or {}
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("active_futures_mode_evrim", active_futures_mode() == "evrim", active_futures_mode())
    add("api_healthy", api_healthy, "")
    add("fee_gross_ok", float(m.get("fee_gross_ratio") or 0) < 0.75, str(m.get("fee_gross_ratio")))
    add("pf_ok", float(m.get("profit_factor") or 0) >= 1.05, str(m.get("profit_factor")))
    add("drawdown_ok", float(m.get("drawdown") or 0) < float(profile.get("daily_dd_halt_pct") or 0.12) * 5000,
        str(m.get("drawdown")))

    if signal:
        stake = float(profile.get("min_stake_usd") or 140)
        exp = compute_expectancy(
            stake_usd=stake,
            leverage=int(profile.get("leverage") or 10),
            side=str(signal.get("type") or "LONG"),
            expected_gross_pct=abs(float(signal.get("change") or 0)),
            spread_pct=float(signal.get("spread_pct") or 0),
            profile=profile,
        )
        add("expected_net_positive", exp.allow_entry, exp.reason)
        add("spread_ok", exp.spread_vs_tp < 0.65, str(exp.spread_vs_tp))
    else:
        add("expected_net_positive", True, "no_signal")
        add("spread_ok", True, "")

    add("execution_mode_match", active_execution_mode() == "evrim", active_execution_mode())
    passed = all(c["ok"] for c in checks)
    return {
        "passed": passed,
        "checks": checks,
        "allow_live_order": passed,
    }
