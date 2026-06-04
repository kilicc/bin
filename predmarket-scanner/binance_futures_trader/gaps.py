"""Mum fiyat boşlukları (gap) analizi."""
from __future__ import annotations

from dataclasses import dataclass

from binance_futures_trader.signals import SignalPart

GAP_MIN_PCT = 0.004
W_GAP = 1.8


@dataclass
class PriceGap:
    index: int
    pct: float
    direction: str  # up | down
    filled: bool


def find_gaps(candles: list[dict], min_pct: float = GAP_MIN_PCT) -> list[PriceGap]:
    gaps: list[PriceGap] = []
    for i in range(1, len(candles)):
        prev_c = float(candles[i - 1].get("c") or 0)
        cur_o = float(candles[i].get("o") or 0)
        if prev_c <= 0:
            continue
        pct = (cur_o - prev_c) / prev_c
        if abs(pct) < min_pct:
            continue
        direction = "up" if pct > 0 else "down"
        filled = False
        if i + 1 < len(candles):
            nxt_c = float(candles[i].get("c") or prev_c)
            if direction == "up" and nxt_c <= prev_c * 1.001:
                filled = True
            if direction == "down" and nxt_c >= prev_c * 0.999:
                filled = True
        gaps.append(PriceGap(i, pct, direction, filled))
    return gaps


def sig_gap(candles: list[dict]) -> SignalPart:
    """Son gap dolmamışsa ters yöne hafif bias (boşluk kapanma)."""
    gaps = find_gaps(candles)
    if not gaps:
        return SignalPart("GAP", 0.0, "gap yok")
    last = gaps[-1]
    if last.filled:
        return SignalPart("GAP", 0.0, f"gap {last.pct*100:+.2f}% dolmuş")
    score = -W_GAP if last.direction == "up" else W_GAP
    return SignalPart(
        "GAP",
        score,
        f"açık gap {last.pct*100:+.2f}% ({last.direction})",
    )
