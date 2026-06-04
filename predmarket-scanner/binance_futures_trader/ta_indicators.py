"""Teknik göstergeler — eğitim deposundaki TA kavramları için backtest."""
from __future__ import annotations

import math


def rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al < 1e-12:
        return 100.0
    rs = ag / al
    return 100.0 - 100.0 / (1.0 + rs)


def ema(vals: list[float], span: int) -> float:
    if not vals:
        return 0.0
    k = 2 / (span + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float, float]:
    """macd_line, signal_line, histogram."""
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    series: list[float] = []
    for i in range(slow, len(closes) + 1):
        w = closes[:i]
        ef = ema(w[-slow:], fast) if len(w) >= fast else ema(w, fast)
        es = ema(w[-slow:], slow)
        series.append(ef - es)
    if len(series) < signal:
        return 0.0, 0.0, 0.0
    macd_line = series[-1]
    sig_line = ema(series[-signal:], signal)
    return macd_line, sig_line, macd_line - sig_line


def bollinger(
    closes: list[float],
    period: int = 20,
    std_mult: float = 2.0,
) -> tuple[float, float, float]:
    if len(closes) < period:
        mid = sum(closes) / max(1, len(closes))
        return mid, mid, mid
    window = closes[-period:]
    mid = sum(window) / len(window)
    std = math.sqrt(sum((x - mid) ** 2 for x in window) / len(window)) or 1e-9
    return mid - std_mult * std, mid, mid + std_mult * std


def adx(candles: list[dict], period: int = 14) -> float:
    """Average Directional Index — trend gücü."""
    if len(candles) < period + 2:
        return 0.0
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    tr_list: list[float] = []
    for i in range(-period, 0):
        h, l = float(candles[i]["h"]), float(candles[i]["l"])
        ph, pl = float(candles[i - 1]["h"]), float(candles[i - 1]["l"])
        pc = float(candles[i - 1]["c"])
        up = h - ph
        down = pl - l
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_v = sum(tr_list) / period or 1e-9
    pdi = 100 * (sum(plus_dm) / period) / atr_v
    mdi = 100 * (sum(minus_dm) / period) / atr_v
    dx = 100 * abs(pdi - mdi) / max(pdi + mdi, 1e-9)
    return dx


def stochastic(
    closes: list[float],
    *,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[float, float]:
    """%K ve %D (0-100)."""
    if len(closes) < k_period:
        return 50.0, 50.0
    window = closes[-k_period:]
    lo, hi = min(window), max(window)
    if hi - lo < 1e-12:
        return 50.0, 50.0
    k = 100 * (closes[-1] - lo) / (hi - lo)
    # basit %D: son d_period K ortalaması yaklaşımı
    ks: list[float] = []
    for off in range(d_period):
        w = closes[-(k_period + off) : len(closes) - off or None]
        if len(w) < k_period:
            continue
        w = w[-k_period:]
        lo2, hi2 = min(w), max(w)
        ks.append(100 * (w[-1] - lo2) / (hi2 - lo2) if hi2 > lo2 else 50.0)
    d = sum(ks) / len(ks) if ks else k
    return k, d


def atr(candles: list[dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs: list[float] = []
    for i in range(-period, 0):
        h, l = float(candles[i]["h"]), float(candles[i]["l"])
        prev_c = float(candles[i - 1]["c"])
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    return sum(trs) / len(trs) if trs else 0.0
