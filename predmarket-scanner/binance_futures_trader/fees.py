"""Binance Futures ücretleri — komisyon, funding, net PnL."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from binance_futures_trader import config as cfg


def gross_pnl(side: str, entry: float, close: float, contracts: float) -> float:
    if contracts <= 0 or entry <= 0 or close <= 0:
        return 0.0
    if side == "LONG":
        return contracts * (close - entry)
    return contracts * (entry - close)


def trade_fee(notional: float, rate: float | None = None) -> float:
    if notional <= 0:
        return 0.0
    r = rate if rate is not None else cfg.TAKER_FEE_RATE
    return round(notional * r, 6)


def estimate_open_fee(contracts: float, entry: float, rate: float | None = None) -> float:
    return trade_fee(abs(contracts) * entry, rate)


def estimate_close_fee(contracts: float, close: float, rate: float | None = None) -> float:
    return trade_fee(abs(contracts) * close, rate)


def close_fee_breakdown(
    *,
    side: str,
    entry: float,
    close: float,
    contracts: float,
    entry_fee: float = 0.0,
    exit_fee: float = 0.0,
    funding_fee: float = 0.0,
    income_commission: float = 0.0,
    income_funding: float = 0.0,
) -> dict[str, float]:
    """Tüm ücret kalemleri pozitif maliyet olarak (USD)."""
    g = gross_pnl(side, entry, close, contracts)
    ef = float(entry_fee or 0)
    xf = float(exit_fee or 0)
    if xf <= 0:
        xf = estimate_close_fee(contracts, close)
    if ef <= 0:
        ef = estimate_open_fee(contracts, entry)

    # Borsa income: komisyon genelde negatif, funding işaretli
    comm_income = abs(float(income_commission or 0))
    fund_income = float(income_funding or 0)
    # Funding pozitif income = bize ödeme → maliyet değil
    funding_cost = float(funding_fee or 0)
    if funding_cost <= 0 and fund_income < 0:
        funding_cost = abs(fund_income)
    elif funding_cost <= 0 and comm_income > 0:
        pass

    commission_total = comm_income if comm_income > (ef + xf) * 0.5 else (ef + xf)
    fees = round(commission_total + funding_cost, 4)
    net = round(g - fees, 4)
    return {
        "pnl_gross_usd": round(g, 4),
        "entry_fee_usd": round(ef, 4),
        "exit_fee_usd": round(xf, 4),
        "commission_usd": round(commission_total, 4),
        "funding_fee_usd": round(funding_cost, 4),
        "fees_usd": fees,
        "pnl_usd": net,
    }


def _parse_iso_ms(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def fetch_close_fees_from_client(client, coin: str, opened_at: str | None) -> dict[str, float]:
    """Borsa income geçmişinden komisyon + funding (kapalı pozisyon)."""
    out = {"income_commission": 0.0, "income_funding": 0.0}
    if client.paper:
        return out
    start_ms = _parse_iso_ms(opened_at)
    if start_ms is None:
        return out
    try:
        rows = client.income_history(coin, start_ms=start_ms)
    except Exception:
        return out
    comm = fund = 0.0
    for r in rows or []:
        t = str(r.get("type") or "")
        inc = float(r.get("income") or 0)
        if t == "COMMISSION":
            comm += inc
        elif t == "FUNDING_FEE":
            fund += inc
    out["income_commission"] = comm
    out["income_funding"] = fund
    return out
