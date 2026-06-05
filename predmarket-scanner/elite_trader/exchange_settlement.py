"""Ana Hat kapanışı — Binance Futures demo/testnet gerçek fill + fee + PnL."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from binance_futures_trader.fees import (
    _parse_iso_ms,
    close_fee_breakdown,
    fetch_close_fees_from_client,
)


def exchange_truth_enabled() -> bool:
    import os

    v = os.getenv("ELITE_EXCHANGE_TRUTH", "1").strip().lower()
    return v not in ("0", "false", "no")


def _parse_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "qty": 0.0,
            "quote_qty": 0.0,
            "avg_price": 0.0,
            "realized_pnl": 0.0,
            "commission": 0.0,
            "trade_count": 0,
            "exit_ms": 0,
        }
    qty = 0.0
    quote = 0.0
    realized = 0.0
    commission = 0.0
    for t in trades:
        q = float(t.get("qty") or 0)
        px = float(t.get("price") or 0)
        qq = float(t.get("quoteQty") or 0)
        if qq <= 0 and q > 0 and px > 0:
            qq = q * px
        qty += q
        quote += qq
        realized += float(t.get("realizedPnl") or 0)
        commission += float(t.get("commission") or 0)
    avg = quote / qty if qty > 0 else 0.0
    exit_ms = max((int(t.get("time") or 0) for t in trades), default=0)
    return {
        "qty": round(qty, 8),
        "quote_qty": round(quote, 4),
        "avg_price": round(avg, 8),
        "realized_pnl": round(realized, 8),
        "commission": round(abs(commission), 8),
        "trade_count": len(trades),
        "exit_ms": exit_ms,
    }


def fetch_order_fills(client: Any, coin: str, order_id: str | int | None) -> dict[str, Any]:
    if client.paper or not order_id:
        return _parse_trades([])
    try:
        trades = client.user_trades(coin, order_id=int(order_id), limit=100)
    except Exception:
        trades = []
    return _parse_trades(trades or [])


def _filter_trades_by_order_ids(
    trades: list[dict[str, Any]],
    order_ids: list[str | int | None],
) -> list[dict[str, Any]]:
    oids = {str(o) for o in order_ids if o}
    if not oids:
        return []
    return [t for t in trades if str(t.get("orderId") or "") in oids]


def _closing_side_trades(
    trades: list[dict[str, Any]], position_side: str
) -> list[dict[str, Any]]:
    """Pozisyon kapanış yönü — SHORT→BUY, LONG→SELL."""
    close_side = "BUY" if str(position_side or "").upper() == "SHORT" else "SELL"
    return [
        t
        for t in trades
        if str(t.get("side") or "").upper() == close_side
    ]


def settlement_has_api_close_fills(settled: dict[str, Any] | None) -> bool:
    """userTrades'ten doğrulanmış kapanış fill'i — pencere/tahmin değil."""
    if not settled:
        return False
    if str(settled.get("fee_source") or "") != "binance_api":
        return False
    if str(settled.get("pnl_source") or "") != "binance_api":
        return False
    return int(settled.get("trade_count_close") or 0) > 0


def fetch_symbol_trades_since(
    client: Any,
    coin: str,
    opened_at_iso: str | None,
    *,
    pre_buffer_ms: int = 0,
    extra_ms: int = 120_000,
) -> list[dict[str, Any]]:
    if client.paper:
        return []
    start_ms = _parse_iso_ms(opened_at_iso)
    if start_ms is None:
        start_ms = int((time.time() - 3600) * 1000)
    else:
        start_ms = max(0, int(start_ms) - max(int(pre_buffer_ms), 0))
    end_ms = int(time.time() * 1000) + max(int(extra_ms), 0)
    try:
        trades = client.user_trades(coin, start_ms=start_ms, limit=1000) or []
    except Exception:
        return []
    if not trades or end_ms <= 0:
        return trades
    return [t for t in trades if int(t.get("time") or 0) <= end_ms]


def settle_position_close(
    client: Any,
    pos: dict[str, Any],
    *,
    close_order_id: str | int | None = None,
    settle_wait_sec: float = 0.55,
) -> dict[str, Any] | None:
    """
    Borsa kapanışından sonra userTrades ile gerçek fiyat, fee, realized PnL.
    Panel kaydı Binance ile aynı olmalı (simüle vergi yok).
    """
    if client.paper or not pos.get("on_exchange"):
        return None
    if not exchange_truth_enabled():
        return None

    coin = str(pos.get("symbol") or "").replace("USDT", "")
    if not coin:
        return None

    if settle_wait_sec > 0:
        time.sleep(settle_wait_sec)

    opened_iso = pos.get("opened_at_iso") or pos.get("entry_time_str")
    entry_oid = pos.get("exchange_order_id")
    close_oid = close_order_id or pos.get("exchange_close_order_id")

    close_trades = fetch_order_fills(client, coin, close_oid)
    if close_trades["trade_count"] == 0 and close_oid:
        time.sleep(0.35)
        close_trades = fetch_order_fills(client, coin, close_oid)

    all_trades = fetch_symbol_trades_since(client, coin, opened_iso)
    side = str(pos.get("side") or "LONG")
    sym_u = f"{coin}USDT".upper()
    if close_trades["trade_count"] == 0:
        try:
            for ep in client.exchange_positions() or []:
                if str(ep.get("symbol") or "").upper() == sym_u:
                    if str(ep.get("side") or "LONG").upper() == side.upper():
                        return None
        except Exception:
            pass
        closing = _closing_side_trades(all_trades, side)
        if closing:
            by_order: dict[str, list[dict[str, Any]]] = {}
            for t in closing:
                oid_key = str(t.get("orderId") or t.get("id") or "")
                if oid_key:
                    by_order.setdefault(oid_key, []).append(t)
            if by_order:
                latest_oid = max(
                    by_order.keys(),
                    key=lambda k: max(int(f.get("time") or 0) for f in by_order[k]),
                )
                close_trades = _parse_trades(by_order[latest_oid])
                close_oid = latest_oid
    if close_trades["trade_count"] == 0:
        return None

    window = _parse_trades(all_trades)
    order_scoped = _parse_trades(
        _filter_trades_by_order_ids(all_trades, [entry_oid, close_oid])
    )

    entry_trades = fetch_order_fills(client, coin, entry_oid)
    entry_fee = entry_trades["commission"]
    if entry_fee <= 0:
        entry_fee = float(pos.get("entry_fee") or 0)

    exit_fee = close_trades["commission"]
    income = fetch_close_fees_from_client(client, coin, opened_iso)

    entry = float(pos.get("entry_price") or 0)
    contracts = float(close_trades["qty"] or pos.get("size") or 0)
    exit_px = float(close_trades["avg_price"] or pos.get("current_price") or 0)

    if entry_trades["avg_price"] > 0:
        entry = entry_trades["avg_price"]
    if contracts <= 0:
        contracts = float(pos.get("size") or 0)

    # Öncelik: kapanış emri fill → order-id kapsamı (pencere/tahmin yok)
    realized_exchange = close_trades["realized_pnl"]
    if abs(realized_exchange) < 1e-8 and close_oid and order_scoped["realized_pnl"]:
        realized_exchange = order_scoped["realized_pnl"]
    if abs(realized_exchange) < 1e-8:
        return None

    fb = close_fee_breakdown(
        side=side,
        entry=entry,
        close=exit_px,
        contracts=contracts,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        income_commission=income["income_commission"],
        income_funding=income["income_funding"],
    )

    exit_comm = round(exit_fee, 8)
    hold_funding = float(income.get("income_funding") or 0)
    close_ms = int(close_trades.get("exit_ms") or 0) or int(time.time() * 1000)

    from elite_trader.income_close import (
        aggregate_close_income_at_ms,
        income_matches_realized,
    )

    income_close = aggregate_close_income_at_ms(
        client,
        coin,
        close_ms,
        since_ms=_parse_iso_ms(opened_iso),
    )
    pnl_gross = round(realized_exchange, 4)
    if income_close and income_matches_realized(income_close, realized_exchange):
        wallet_pnl = float(income_close.get("wallet_pnl") or 0)
        exit_comm = float(income_close.get("total_commission") or exit_comm)
        pnl_gross = round(float(income_close.get("realized_pnl") or realized_exchange), 4)
        hold_funding = float(income_close.get("funding_income") or hold_funding)
    else:
        wallet_pnl = round(realized_exchange - exit_comm + hold_funding, 4)
    commission_total = round(exit_comm, 8)

    stake = float(pos.get("stake_usd") or 1)
    return {
        "exchange_settled": True,
        "entry_price": round(entry, 8),
        "exit_price": round(exit_px, 8),
        "size": round(contracts, 8),
        "position_value": round(contracts * exit_px, 4),
        "quote_qty_close": close_trades["quote_qty"],
        "pnl_usd": pnl_gross,
        "pnl_gross_usd": pnl_gross,
        "entry_fee": round(entry_fee, 8),
        "exit_fee": round(exit_comm, 8),
        "total_fees": round(commission_total, 8),
        "funding_fee": fb["funding_fee_usd"],
        "net_pnl": wallet_pnl,
        "net_pnl_pct": round(wallet_pnl / stake * 100, 4) if stake else 0,
        "tax": 0.0,
        # final_pnl / wallet_pnl: Binance Transaction History (realized + tüm commission satırları)
        "final_pnl": wallet_pnl,
        "wallet_pnl": wallet_pnl,
        "fee_source": "binance_api",
        "pnl_source": "binance_api",
        "data_source": "binance_api",
        "exchange_close_order_id": str(close_oid or ""),
        "exchange_realized_pnl": round(realized_exchange, 8),
        "exchange_commission": round(commission_total, 8),
        "calc_pnl_gross": fb["pnl_gross_usd"],
        "trade_count_close": close_trades["trade_count"],
        "trade_count_window": window["trade_count"],
        "trade_count_order_scoped": order_scoped["trade_count"],
    }
