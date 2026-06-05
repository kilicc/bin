"""Büyük işlem / taker akışı — bot olmayan agresif alım-satım proxy."""
from __future__ import annotations

from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.signals import SignalPart

W_FLOW = 2.0


def sig_large_flow(client: BinanceFuturesClient, coin: str, mark: float) -> SignalPart:
    """
    Son aggTrades: büyük taker hacim dengesizliği.
    maker=false → piyasa emri (taker).
    """
    sym = f"{coin}USDT"
    try:
        raw = client._get(
            "/fapi/v1/aggTrades",
            {"symbol": sym, "limit": 500},
        )
    except Exception as exc:
        return SignalPart("FLOW", 0.0, f"flow err {exc}")

    if not isinstance(raw, list) or not raw:
        return SignalPart("FLOW", 0.0, "flow yok")

    buy_usd = sell_usd = 0.0
    large_n = 0
    for t in raw[-200:]:
        try:
            px = float(t.get("p") or 0)
            qty = float(t.get("q") or 0)
            usd = px * qty
            if usd < mark * 0.02:
                continue
            large_n += 1
            if t.get("m"):
                sell_usd += usd
            else:
                buy_usd += usd
        except Exception:
            pass

    total = buy_usd + sell_usd
    if total < 5000 or large_n < 3:
        return SignalPart("FLOW", 0.0, f"flow zayıf ${total:.0f}")

    imbalance = (buy_usd - sell_usd) / total
    score = W_FLOW * max(-1.0, min(1.0, imbalance * 2))
    side = "alım" if score > 0 else "satım"
    return SignalPart(
        "FLOW",
        score,
        f"büyük taker {side} imb={imbalance*100:+.1f}% (${total:.0f})",
    )
