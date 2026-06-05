"""Binance Futures income — Transaction History ile aynı net kapanış satırı."""
from __future__ import annotations

from typing import Any

_REALIZED = "REALIZED_PNL"
_COMMISSION = "COMMISSION"
_FUNDING = "FUNDING_FEE"


def aggregate_close_income_at_ms(
    client: Any,
    coin: str,
    anchor_ms: int,
    *,
    since_ms: int | None = None,
    window_after_ms: int = 15_000,
    window_before_ms: int = 500,
    max_anchor_delta_ms: int = 60_000,
) -> dict[str, Any] | None:
    """
    Kapalı işlem cüzdan etkisi — REALIZED_PNL + aynı olaydaki COMMISSION satırları.

    Binance Transaction History tek kapanışta birden fazla Commission gösterebilir;
    net = realized + sum(commission) (+ funding varsa).
    """
    if client is None or getattr(client, "paper", True) or anchor_ms <= 0:
        return None
    start = since_ms if since_ms is not None else max(0, int(anchor_ms) - 86_400_000)
    try:
        rows = client.income_history(coin, start_ms=start, limit=500) or []
    except Exception:
        return None
    if not rows:
        return None

    rp_rows = [r for r in rows if str(r.get("type") or "") == _REALIZED]
    if not rp_rows:
        return None

    best_rp: dict[str, Any] | None = None
    best_delta = max_anchor_delta_ms + 1
    for r in rp_rows:
        t = int(r.get("time") or 0)
        delta = abs(t - int(anchor_ms))
        if delta < best_delta:
            best_delta = delta
            best_rp = r
    if best_rp is None or best_delta > max_anchor_delta_ms:
        return None

    t0 = int(best_rp.get("time") or 0)
    realized = float(best_rp.get("income") or 0)
    comm = 0.0
    fund = 0.0
    comm_lines = 0
    for r in rows:
        t = int(r.get("time") or 0)
        typ = str(r.get("type") or "")
        inc = float(r.get("income") or 0)
        if typ == _COMMISSION and (t0 - window_before_ms) <= t <= (t0 + window_after_ms):
            comm += inc
            comm_lines += 1
        elif typ == _FUNDING and abs(t - t0) <= 1_000:
            fund += inc

    wallet = round(realized + comm + fund, 4)
    return {
        "realized_pnl": round(realized, 8),
        "commission_income": round(comm, 8),
        "total_commission": round(abs(comm), 8),
        "funding_income": round(fund, 8),
        "wallet_pnl": wallet,
        "net_pnl": wallet,
        "final_pnl": wallet,
        "exit_ms": t0,
        "commission_lines": comm_lines,
        "income_settled": True,
    }


def income_matches_realized(income: dict[str, Any] | None, realized: float) -> bool:
    if not income:
        return False
    ir = float(income.get("realized_pnl") or 0)
    if abs(ir - realized) < max(0.05, abs(realized) * 0.002):
        return True
    return abs(ir) > 1e-8 and abs(realized) < 1e-6


def apply_income_wallet_to_close_row(
    row: dict[str, Any],
    income: dict[str, Any],
) -> dict[str, Any]:
    """userTrades satırına income net cüzdan değerlerini uygula."""
    out = dict(row)
    realized = float(income.get("realized_pnl") or out.get("pnl_usd") or 0)
    wallet = float(income.get("wallet_pnl") or 0)
    total_comm = float(income.get("total_commission") or 0)
    out["pnl_usd"] = round(realized, 4)
    out["pnl_gross_usd"] = round(realized, 4)
    out["exchange_realized_pnl"] = round(realized, 8)
    out["net_pnl"] = wallet
    out["wallet_pnl"] = wallet
    out["final_pnl"] = wallet
    out["exit_fee"] = total_comm
    out["total_fees"] = total_comm
    out["income_settled"] = True
    out["commission_lines"] = int(income.get("commission_lines") or 0)
    if income.get("exit_ms"):
        out["exit_ms"] = int(income["exit_ms"])
    stake = float(out.get("stake_usd") or 1)
    out["net_pnl_pct"] = round(wallet / stake * 100, 4) if stake else 0.0
    out["pnl_pct"] = out["net_pnl_pct"]
    return out
