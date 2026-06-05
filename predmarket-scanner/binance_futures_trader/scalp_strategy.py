"""Hızlı TP / sıkı SL scalp stratejisi — kısa mum, momentum, yüksek kaldıraç."""
from __future__ import annotations

import math

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.signals import (
    CoinSignal,
    SignalPart,
    W_BB,
    W_EMA,
    W_FUND,
    W_MOM,
    W_RSI,
    W_VOL,
    _ema,
    _rsi,
    fear_greed,
)


def analyze_coin_scalp(
    client: BinanceFuturesClient,
    coin: str,
    mark: float,
    *,
    cex_book: dict[str, dict[str, float]] | None = None,
    strategy_weights: dict[str, float] | None = None,
    backtest_wr: float = 0.5,
) -> CoinSignal:
    from binance_futures_trader.cex_arb import build_cex_book, sig_cex_spread
    from binance_futures_trader.flow import sig_large_flow
    from binance_futures_trader.gaps import sig_gap
    from binance_futures_trader.learner import apply_weights
    from binance_futures_trader.news import sig_macro_news

    cs = CoinSignal(coin=coin, mark_px=mark, backtest_wr=backtest_wr)
    limit = max(60, cfg.SCALP_LOOKBACK)
    candles = client.klines(coin, cfg.CANDLE_INTERVAL, limit)
    closes = [float(c["c"]) for c in candles if c.get("c")]
    vols = [float(c["v"]) for c in candles if c.get("v")]
    if len(closes) < 20:
        return cs

    fund = client.funding_rate(coin) or 0.0
    cs.funding = fund
    if fund > 0.00012:
        cs.parts.append(SignalPart("FUND", -W_FUND * 0.7, f"funding={fund:.5f}"))
    elif fund < -0.00006:
        cs.parts.append(SignalPart("FUND", W_FUND * 0.7, f"funding={fund:.5f}"))

    rsi = _rsi(closes, period=10)
    if rsi < 40:
        cs.parts.append(SignalPart("RSI", W_RSI * 1.1, f"rsi={rsi:.1f}"))
    elif rsi > 60:
        cs.parts.append(SignalPart("RSI", -W_RSI * 1.1, f"rsi={rsi:.1f}"))

    ef = _ema(closes[-24:], 5)
    es = _ema(closes[-24:], 13)
    if ef > es * 1.0008:
        cs.parts.append(SignalPart("EMA", W_EMA, "fast golden"))
    elif ef < es * 0.9992:
        cs.parts.append(SignalPart("EMA", -W_EMA, "fast death"))

    if len(closes) >= 12:
        window = closes[-12:]
        mid = sum(window) / len(window)
        std = math.sqrt(sum((x - mid) ** 2 for x in window) / len(window)) or 1e-9
        upper, lower = mid + 1.8 * std, mid - 1.8 * std
        if mark <= lower:
            cs.parts.append(SignalPart("BB", W_BB * 0.9, "squeeze low"))
        elif mark >= upper:
            cs.parts.append(SignalPart("BB", -W_BB * 0.9, "squeeze high"))

    if len(vols) >= 12:
        avg_v = sum(vols[-12:-1]) / max(1, len(vols[-12:-1]))
        if avg_v > 0 and vols[-1] > avg_v * 1.5:
            direction = 1 if closes[-1] > closes[-2] else -1
            cs.parts.append(SignalPart("VOL", W_VOL * 1.3 * direction, "spike"))

    if len(closes) >= 3:
        mom3 = (closes[-1] - closes[-3]) / closes[-3]
        if mom3 > cfg.SCALP_MOM_THRESH:
            cs.parts.append(SignalPart("MOM3", W_MOM * 1.4, f"{mom3:+.2%}"))
        elif mom3 < -cfg.SCALP_MOM_THRESH:
            cs.parts.append(SignalPart("MOM3", -W_MOM * 1.4, f"{mom3:+.2%}"))

    if len(closes) >= 5:
        mom5 = (closes[-1] - closes[-5]) / closes[-5]
        if mom5 > cfg.SCALP_MOM_THRESH * 1.5:
            cs.parts.append(SignalPart("MOM", W_MOM, f"{mom5:+.2%}"))
        elif mom5 < -cfg.SCALP_MOM_THRESH * 1.5:
            cs.parts.append(SignalPart("MOM", -W_MOM, f"{mom5:+.2%}"))

    # Ardışık mum yönü (scalp burst)
    if len(closes) >= 4:
        ups = sum(1 for i in range(-3, 0) if closes[i] > closes[i - 1])
        if ups >= 3:
            cs.parts.append(SignalPart("BURST", W_MOM * 0.8, "3 green"))
        elif ups == 0:
            cs.parts.append(SignalPart("BURST", -W_MOM * 0.8, "3 red"))

    fg = fear_greed()
    if fg <= 30:
        cs.parts.append(SignalPart("FG", 0.8, f"fg={fg}"))
    elif fg >= 70:
        cs.parts.append(SignalPart("FG", -0.8, f"fg={fg}"))

    if cfg.CEX_ARB_ENABLED:
        book = cex_book if cex_book is not None else build_cex_book()
        venues = book.get(coin) or {}
        if venues:
            cs.parts.append(sig_cex_spread(coin, mark, venues))

    if cfg.GAP_ANALYSIS_ENABLED and candles:
        g = sig_gap(candles)
        if g.score:
            cs.parts.append(
                SignalPart(g.name, g.score * 1.15, g.detail or "gap")
            )

    if cfg.FLOW_ANALYSIS_ENABLED:
        f = sig_large_flow(client, coin, mark)
        if abs(f.score) > 0.2:
            cs.parts.append(SignalPart(f.name, f.score * 1.2, f.detail))

    if cfg.NEWS_ENABLED:
        n = sig_macro_news(fg)
        if abs(n.score) > 0.3:
            cs.parts.append(n)

    if strategy_weights:
        apply_weights(cs.parts, strategy_weights)

    cs.compute()
    return cs


def scalp_stake_multiplier(confidence: float) -> float:
    """Yüksek güven scalp → daha büyük stake."""
    c = max(0.0, min(8.0, confidence))
    return 1.0 + min(0.45, (c / 8.0) * 0.55)


def scalp_leverage_boost(lev: int, confidence: float) -> int:
    if confidence < cfg.SCALP_MIN_CONF_LEV:
        return lev
    boosted = int(round(lev * cfg.SCALP_LEV_MULT))
    return min(cfg.LEVERAGE_MAX, max(cfg.LEVERAGE_MIN, boosted))
