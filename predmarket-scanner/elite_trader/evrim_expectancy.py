"""
Evrim — işlem öncesi net expectancy ve sürekli fee/PnL metrik takibi.

expected_net_pnl = expected_gross_move - entry_fee - exit_fee - spread_cost
                   - slippage_cost - funding_cost

Negatifse giriş yok.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MODE_ID = "evrim"

FEE_GROSS_REDUCE_AGGRESSIVE = 0.45
FEE_GROSS_SLOW_TRADES = 0.70
FEE_GROSS_EMERGENCY = 1.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _default_metrics() -> dict[str, Any]:
    return {
        "trades_n": 0,
        "wins_n": 0,
        "losses_n": 0,
        "gross_profit_usd": 0.0,
        "gross_loss_usd": 0.0,
        "total_fees_usd": 0.0,
        "net_pnl_usd": 0.0,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "funding_cost_usd": 0.0,
        "maker_fills": 0,
        "taker_fills": 0,
        "expectancy_vetoes": 0,
        "pre_trade_checks": 0,
        "protection_mode": "normal",
        "fee_to_gross_profit_pct": 0.0,
        "gross_profit_to_fee_ratio": 0.0,
        "net_pnl_per_trade": 0.0,
        "avg_slippage_bps": 0.0,
        "avg_spread_pct": 0.0,
        "maker_taker_ratio": 0.0,
        "profit_factor": 0.0,
        "win_rate_pct": 0.0,
        "avg_win_usd": 0.0,
        "avg_loss_usd": 0.0,
        "expectancy_usd": 0.0,
    }


def load_expectancy_metrics() -> dict[str, Any]:
    try:
        from elite_trader.evrim_training import load_training_state

        return dict(
            load_training_state().get("expectancy_metrics") or _default_metrics()
        )
    except Exception:
        return _default_metrics()


def save_expectancy_metrics(metrics: dict[str, Any]) -> None:
    try:
        from elite_trader.evrim_training import _save_training_state, load_training_state

        st = load_training_state()
        st["expectancy_metrics"] = metrics
        _save_training_state(st)
    except Exception:
        pass


def _recompute_derived(m: dict[str, Any]) -> dict[str, Any]:
    n = int(m.get("trades_n") or 0)
    wins = int(m.get("wins_n") or 0)
    gp = float(m.get("gross_profit_usd") or 0)
    gl = float(m.get("gross_loss_usd") or 0)
    fees = float(m.get("total_fees_usd") or 0)
    net = float(m.get("net_pnl_usd") or 0)
    spread_sum = float(m.get("spread_cost_usd") or 0)
    slip_sum = float(m.get("slippage_cost_usd") or 0)
    maker = int(m.get("maker_fills") or 0)
    taker = int(m.get("taker_fills") or 0)

    m["win_rate_pct"] = round(wins / n * 100, 2) if n else 0.0
    m["net_pnl_per_trade"] = round(net / n, 4) if n else 0.0
    m["expectancy_usd"] = m["net_pnl_per_trade"]
    m["fee_to_gross_profit_pct"] = round(fees / gp * 100, 2) if gp > 1e-9 else (
        100.0 if fees > 0 else 0.0
    )
    m["gross_profit_to_fee_ratio"] = round(gp / fees, 3) if fees > 1e-9 else (
        999.0 if gp > 0 else 0.0
    )
    m["profit_factor"] = round(gp / gl, 3) if gl > 1e-9 else (999.0 if gp > 0 else 0.0)
    m["avg_win_usd"] = round(gp / wins, 4) if wins else 0.0
    losses_n = int(m.get("losses_n") or 0)
    m["avg_loss_usd"] = round(-gl / losses_n, 4) if losses_n else 0.0
    m["avg_spread_pct"] = round(spread_sum / n, 4) if n else 0.0
    m["avg_slippage_bps"] = round(slip_sum / n, 2) if n else 0.0
    fills = maker + taker
    m["maker_taker_ratio"] = round(maker / fills, 3) if fills else 0.0
    return m


@dataclass
class ExpectancyBreakdown:
    expected_gross_move: float
    entry_fee: float
    exit_fee: float
    spread_cost: float
    slippage_cost: float
    funding_cost: float
    expected_net_pnl: float
    stake_usd: float
    leverage: int
    is_maker: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_gross_move": round(self.expected_gross_move, 4),
            "entry_fee": round(self.entry_fee, 4),
            "exit_fee": round(self.exit_fee, 4),
            "spread_cost": round(self.spread_cost, 4),
            "slippage_cost": round(self.slippage_cost, 4),
            "funding_cost": round(self.funding_cost, 4),
            "expected_net_pnl": round(self.expected_net_pnl, 4),
            "stake_usd": round(self.stake_usd, 2),
            "leverage": self.leverage,
            "is_maker": self.is_maker,
            "notes": self.notes[:10],
        }


def _estimate_stake(profile: dict[str, Any]) -> float:
    return max(
        float(profile.get("min_stake_usd") or 140),
        float(profile.get("entry_min_stake_usd") or 0) or 140,
    )


def _leverage_from_signal(signal: dict[str, Any]) -> int:
    strength = str(signal.get("strength") or "Medium")
    return 10 if strength == "Strong" else 7 if strength == "Medium" else 5


def compute_pre_trade_expectancy(
    *,
    signal: dict[str, Any],
    ctx: dict[str, Any],
    profile: dict[str, Any],
    total_score: float,
    dynamic_exit: dict[str, Any] | None = None,
    stake_usd: float | None = None,
    leverage: int | None = None,
) -> ExpectancyBreakdown:
    """Her işlem öncesi net expectancy."""
    prof = profile or {}
    stake = float(stake_usd or _estimate_stake(prof))
    lev = int(leverage or _leverage_from_signal(signal))
    lev_eff = min(lev, int(prof.get("evrim_expectancy_lev_cap") or 5))
    is_maker = bool(prof.get("evrim_prefer_maker", False))

    de = dynamic_exit or ctx.get("dynamic_exit") or signal.get("evrim_dynamic_exit") or {}
    tp_pct = float(de.get("tp_stake_pct") or prof.get("tp_stake_pct") or 0.006)
    trig = float(de.get("tp_trigger_frac") or prof.get("tp_trigger_frac") or 0.98)

    if not de and prof.get("evrim_dynamic_exit_enabled", True):
        try:
            from elite_trader.evrim_dynamic_exit import compute_dynamic_exit

            side = str(signal.get("type") or "LONG")
            plan = compute_dynamic_exit(
                total_score=total_score,
                side=side,
                signal=signal,
                ctx=ctx,
                profile=prof,
                stake_usd=stake,
                leverage=lev,
            )
            tp_pct = plan.tp_stake_pct
            trig = plan.tp_trigger_frac
        except Exception:
            pass

    expected_gross = stake * tp_pct * trig

    try:
        from elite_trader.fee_economics import fee_rate_per_side

        rate = fee_rate_per_side()
    except Exception:
        rate = 0.0004

    notional = stake * lev_eff
    entry_fee = notional * rate * (0.5 if is_maker else 1.0)
    exit_fee = entry_fee

    spread_pct = float(ctx.get("spread_pct") or 0.05)
    vo = ctx.get("vo") or {}
    if vo.get("spread_pct") is not None:
        spread_pct = float(vo["spread_pct"])
    # Stake-temelli PnL motoru ile uyumlu (notional tam çarpan değil)
    spread_cost = stake * (spread_pct / 100.0) * 0.35

    slip_bps = float(vo.get("slippage_bps") or ctx.get("slippage_bps") or 0)
    slip_cap = float(prof.get("evrim_vo_slippage_stake_bps") or 25)
    if slip_bps <= 0 and spread_pct > 0.08:
        slip_bps = slip_cap * 0.5
    slippage_cost = stake * (slip_bps / 10000.0) * 1.5

    funding_abs = float(ctx.get("funding_abs") or 0)
    funding_cost = stake * funding_abs * float(prof.get("evrim_funding_cost_mult") or 1.5)

    expected_net = (
        expected_gross
        - entry_fee
        - exit_fee
        - spread_cost
        - slippage_cost
        - funding_cost
    )

    notes: list[str] = []
    if expected_net < 0:
        notes.append("net_negative")
    if entry_fee + exit_fee > expected_gross * 0.5:
        notes.append("fee_heavy")

    return ExpectancyBreakdown(
        expected_gross_move=expected_gross,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        funding_cost=funding_cost,
        expected_net_pnl=expected_net,
        stake_usd=stake,
        leverage=lev,
        is_maker=is_maker,
        notes=notes,
    )


def apply_fee_protection_rules(
    metrics: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Fee/Gross kuralları → stake_mult, min_score_delta, max_tier_cap, protection_mode.
    """
    m = dict(metrics)
    fee_gross_pct = float(m.get("fee_to_gross_profit_pct") or 0)
    fees = float(m.get("total_fees_usd") or 0)
    gp = float(m.get("gross_profit_usd") or 0)
    trades_n = int(m.get("trades_n") or 0)

    out: dict[str, Any] = {
        "stake_mult": 1.0,
        "min_score_delta": 0,
        "max_tier_cap": None,
        "protection_mode": "normal",
        "block_entries": False,
    }

    hard_block = bool(profile.get("evrim_fee_hard_block", False))
    if fees >= gp and fees > 0 and trades_n >= 5:
        out.update(
            {
                "protection_mode": "emergency",
                "stake_mult": 0.45,
                "min_score_delta": 6,
                "max_tier_cap": "normal",
                "block_entries": hard_block,
            }
        )
        if not hard_block:
            out["min_score_delta"] = 3
    elif fee_gross_pct >= FEE_GROSS_EMERGENCY * 100:
        out.update(
            {
                "protection_mode": "emergency",
                "stake_mult": 0.5,
                "min_score_delta": 5,
                "max_tier_cap": "aggressive",
                "block_entries": hard_block,
            }
        )
        if not hard_block:
            out["min_score_delta"] = 2
    elif fee_gross_pct >= FEE_GROSS_SLOW_TRADES * 100:
        out.update(
            {
                "protection_mode": "slow",
                "stake_mult": 0.7,
                "min_score_delta": 2,
                "max_tier_cap": "aggressive",
            }
        )
    elif fee_gross_pct >= FEE_GROSS_REDUCE_AGGRESSIVE * 100:
        out.update(
            {
                "protection_mode": "cautious",
                "stake_mult": 0.85,
                "min_score_delta": 1,
            }
        )

    overrides = dict(profile.get("expectancy_overrides") or {})
    try:
        from elite_trader.evrim_training import load_training_state

        overrides.update(load_training_state().get("expectancy_overrides") or {})
    except Exception:
        pass
    if overrides.get("stake_mult"):
        out["stake_mult"] = float(overrides["stake_mult"])
    if overrides.get("min_score_delta"):
        out["min_score_delta"] = int(overrides["min_score_delta"])
    return out


def record_pre_trade_check(*, veto: bool = False) -> None:
    m = load_expectancy_metrics()
    m["pre_trade_checks"] = int(m.get("pre_trade_checks") or 0) + 1
    if veto:
        m["expectancy_vetoes"] = int(m.get("expectancy_vetoes") or 0) + 1
    save_expectancy_metrics(_recompute_derived(m))


def record_closed_trade(
    *,
    gross_pnl: float,
    net_pnl: float,
    fees_usd: float,
    spread_cost: float = 0.0,
    slippage_cost: float = 0.0,
    funding_cost: float = 0.0,
    is_maker: bool = False,
    spread_pct: float = 0.0,
    slippage_bps: float = 0.0,
) -> dict[str, Any]:
    """Kapanan işlem sonrası metrik güncelle."""
    m = load_expectancy_metrics()
    m["trades_n"] = int(m.get("trades_n") or 0) + 1
    g = float(gross_pnl)
    if g > 0:
        m["wins_n"] = int(m.get("wins_n") or 0) + 1
        m["gross_profit_usd"] = float(m.get("gross_profit_usd") or 0) + g
    else:
        m["losses_n"] = int(m.get("losses_n") or 0) + 1
        m["gross_loss_usd"] = float(m.get("gross_loss_usd") or 0) + abs(g)
    m["total_fees_usd"] = float(m.get("total_fees_usd") or 0) + float(fees_usd)
    m["net_pnl_usd"] = float(m.get("net_pnl_usd") or 0) + float(net_pnl)
    m["spread_cost_usd"] = float(m.get("spread_cost_usd") or 0) + float(spread_cost)
    m["slippage_cost_usd"] = float(m.get("slippage_cost_usd") or 0) + float(slippage_cost)
    m["funding_cost_usd"] = float(m.get("funding_cost_usd") or 0) + float(funding_cost)
    if is_maker:
        m["maker_fills"] = int(m.get("maker_fills") or 0) + 2
    else:
        m["taker_fills"] = int(m.get("taker_fills") or 0) + 2
    if spread_pct:
        m["avg_spread_pct"] = spread_pct
    if slippage_bps:
        m["avg_slippage_bps"] = slippage_bps

    m = _recompute_derived(m)
    prot = apply_fee_protection_rules(m, {})
    m["protection_mode"] = prot["protection_mode"]
    save_expectancy_metrics(m)
    return m


def gate_entry_from_expectancy(
    breakdown: ExpectancyBreakdown,
    profile: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    """Negatif net veya koruma modu → giriş engeli."""
    min_net = float(profile.get("evrim_expectancy_min_net_usd") or 0.01)
    metrics = load_expectancy_metrics()
    prot = apply_fee_protection_rules(metrics, profile)

    if (
        prot.get("block_entries")
        and profile.get("evrim_fee_hard_block", False)
        and not profile.get("evrim_expectancy_bt_simulation")
    ):
        record_pre_trade_check(veto=True)
        return (
            False,
            f"fee_protection_{prot['protection_mode']}",
            {**breakdown.to_dict(), "protection": prot, "metrics": metrics},
        )

    if breakdown.expected_net_pnl < min_net:
        record_pre_trade_check(veto=True)
        return (
            False,
            f"negative_expectancy (${breakdown.expected_net_pnl:.2f} < ${min_net:.2f})",
            {**breakdown.to_dict(), "protection": prot},
        )

    record_pre_trade_check(veto=False)
    return True, "ok", {**breakdown.to_dict(), "protection": prot}


def metrics_snapshot() -> dict[str, Any]:
    m = _recompute_derived(load_expectancy_metrics())
    return dict(m)
