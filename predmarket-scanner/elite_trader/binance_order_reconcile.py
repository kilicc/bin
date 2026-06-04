"""Binance -1007 (emir zaman aşımı) — positionRisk + userTrades ile doğrulama."""
from __future__ import annotations

import time
from typing import Any

import httpx


def is_order_timeout_error(exc: BaseException | str | None) -> bool:
    if exc is None:
        return False
    body = str(exc)
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        body = exc.response.text or body
    low = body.lower()
    return "-1007" in body or (
        "execution status unknown" in low and "send status unknown" in low
    )


def _closing_trade_side(position_side: str) -> str:
    return "BUY" if str(position_side or "").upper() == "SHORT" else "SELL"


def _exchange_still_open(client: Any, symbol: str, side: str) -> bool:
    sym = str(symbol or "").upper()
    sd = str(side or "LONG").upper()
    try:
        for ep in client.exchange_positions() or []:
            if str(ep.get("symbol") or "").upper() != sym:
                continue
            if str(ep.get("side") or "LONG").upper() != sd:
                continue
            if abs(float(ep.get("contracts") or ep.get("positionAmt") or 0)) > 0:
                return True
    except Exception:
        pass
    return False


def _latest_close_order_id(client: Any, pos: dict[str, Any]) -> str | None:
    from elite_trader.exchange_settlement import fetch_symbol_trades_since

    coin = str(pos.get("symbol") or "").replace("USDT", "")
    if not coin or getattr(client, "paper", True):
        return None
    opened = pos.get("opened_at_iso") or pos.get("entry_time_str")
    close_side = _closing_trade_side(str(pos.get("side") or "LONG"))
    try:
        trades = fetch_symbol_trades_since(client, coin, opened, extra_ms=90_000)
    except Exception:
        trades = []
    hits = [
        t
        for t in (trades or [])
        if str(t.get("side") or "").upper() == close_side
    ]
    if not hits:
        return None
    hits.sort(key=lambda t: int(t.get("time") or 0), reverse=True)
    oid = hits[0].get("orderId")
    return str(oid) if oid else None


def recover_close_after_order_timeout(
    client: Any,
    pos: dict[str, Any],
    *,
    settle_wait_sec: float = 0.55,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    POST /order -1007 sonrası — tekrar MARKET göndermeden borsayı doğrula.
    Dönüş: (settlement, close_order_id). Pozisyon hâlâ açıksa (None, None).
    """
    if not client or getattr(client, "paper", True) or not pos.get("on_exchange"):
        return None, None

    sym = str(pos.get("symbol") or "")
    side = str(pos.get("side") or "LONG")
    if settle_wait_sec > 0:
        time.sleep(settle_wait_sec)

    if _exchange_still_open(client, sym, side):
        return None, None

    close_oid = _latest_close_order_id(client, pos)
    from elite_trader.exchange_settlement import (
        settle_position_close,
        settlement_has_api_close_fills,
    )

    settled: dict[str, Any] | None = None
    for wait in (0.15, 0.35, 0.55):
        settled = settle_position_close(
            client,
            pos,
            close_order_id=close_oid,
            settle_wait_sec=wait,
        )
        if settled and settlement_has_api_close_fills(settled):
            oid_out = str(
                settled.get("exchange_close_order_id") or close_oid or ""
            )
            return settled, oid_out or None
    return None, close_oid
