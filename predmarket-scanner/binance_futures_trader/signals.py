"""Çok kaynaklı sinyal — teknik + CEX spread + gap + flow + makro."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import httpx

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient

FG_URL = "https://api.alternative.me/fng/?limit=1"
_fg_cache: tuple[int, float] = (50, 0.0)

W_FUND = 2.5
W_RSI = 2.0
W_EMA = 1.5
W_BB = 1.5
W_VOL = 1.0
W_FG = 1.5
W_MOM = 1.0


@dataclass
class SignalPart:
    name: str
    score: float
    detail: str = ""


@dataclass
class CoinSignal:
    coin: str
    mark_px: float
    side: str = ""
    total_score: float = 0.0
    confidence: float = 0.0
    parts: list[SignalPart] = field(default_factory=list)
    funding: float = 0.0
    backtest_wr: float = 0.5
    leverage: int = 0
    leverage_reason: str = ""

    def compute(self, min_score: float | None = None) -> None:
        self.total_score = sum(p.score for p in self.parts)
        self.confidence = min(8.0, abs(self.total_score))
        thresh = cfg.MIN_SCORE if min_score is None else min_score
        if self.total_score >= thresh:
            self.side = "LONG"
        elif self.total_score <= -thresh:
            self.side = "SHORT"
        else:
            self.side = ""

    def snapshot(self) -> dict:
        return {
            "coin": self.coin,
            "mark": self.mark_px,
            "score": self.total_score,
            "side": self.side,
            "parts": [(p.name, p.score, p.detail) for p in self.parts],
            "bt_wr": self.backtest_wr,
        }


def fear_greed() -> int:
    global _fg_cache
    now = time.time()
    if now - _fg_cache[1] < 3600:
        return _fg_cache[0]
    try:
        r = httpx.get(FG_URL, timeout=8.0)
        v = int(r.json()["data"][0]["value"])
        _fg_cache = (v, now)
        return v
    except Exception:
        return _fg_cache[0]


def _rsi(closes: list[float], period: int = 14) -> float:
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


def _ema(vals: list[float], span: int) -> float:
    if not vals:
        return 0.0
    k = 2 / (span + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def analyze_coin(
    client: BinanceFuturesClient,
    coin: str,
    mark: float,
    *,
    cex_book: dict[str, dict[str, float]] | None = None,
    strategy_weights: dict[str, float] | None = None,
    backtest_wr: float = 0.5,
) -> CoinSignal:
    if cfg.PORTFOLIO_ENGINE:
        from binance_futures_trader.portfolio_signals import analyze_coin_portfolio

        return analyze_coin_portfolio(
            client,
            coin,
            mark,
            strategy_weights=strategy_weights,
            backtest_wr=backtest_wr,
        )
    if cfg.is_scalp():
        from binance_futures_trader.scalp_strategy import analyze_coin_scalp

        return analyze_coin_scalp(
            client,
            coin,
            mark,
            cex_book=cex_book,
            strategy_weights=strategy_weights,
            backtest_wr=backtest_wr,
        )
    from binance_futures_trader.cex_arb import build_cex_book, sig_cex_spread
    from binance_futures_trader.flow import sig_large_flow
    from binance_futures_trader.gaps import sig_gap
    from binance_futures_trader.learner import apply_weights
    from binance_futures_trader.news import sig_macro_news

    cs = CoinSignal(coin=coin, mark_px=mark, backtest_wr=backtest_wr)
    candles = client.klines(coin, cfg.CANDLE_INTERVAL, 80)
    closes = [c["c"] for c in candles if "c" in c]
    vols = [c["v"] for c in candles if "v" in c]
    if len(closes) < 25:
        return cs

    fund = client.funding_rate(coin) or 0.0
    cs.funding = fund
    if fund > 0.0001:
        cs.parts.append(SignalPart("FUND", -W_FUND, f"funding={fund:.5f}"))
    elif fund < -0.00008:
        cs.parts.append(SignalPart("FUND", W_FUND, f"funding={fund:.5f}"))

    rsi = _rsi(closes)
    if rsi < 35:
        cs.parts.append(SignalPart("RSI", W_RSI, f"rsi={rsi:.1f}"))
    elif rsi > 65:
        cs.parts.append(SignalPart("RSI", -W_RSI, f"rsi={rsi:.1f}"))

    ef = _ema(closes[-30:], 9)
    es = _ema(closes[-30:], 21)
    if ef > es * 1.001:
        cs.parts.append(SignalPart("EMA", W_EMA * 0.8, "golden"))
    elif ef < es * 0.999:
        cs.parts.append(SignalPart("EMA", -W_EMA * 0.8, "death"))

    if len(closes) >= 20:
        window = closes[-20:]
        mid = sum(window) / len(window)
        std = math.sqrt(sum((x - mid) ** 2 for x in window) / len(window)) or 1e-9
        upper, lower = mid + 2 * std, mid - 2 * std
        if mark <= lower:
            cs.parts.append(SignalPart("BB", W_BB, "below"))
        elif mark >= upper:
            cs.parts.append(SignalPart("BB", -W_BB, "above"))

    if len(vols) >= 20:
        avg_v = sum(vols[-20:-1]) / 19
        if avg_v > 0 and vols[-1] > avg_v * 1.8:
            direction = 1 if closes[-1] > closes[-2] else -1
            cs.parts.append(SignalPart("VOL", W_VOL * direction, "spike"))

    fg = fear_greed()
    if fg <= 25:
        cs.parts.append(SignalPart("FG", W_FG, f"fg={fg}"))
    elif fg >= 75:
        cs.parts.append(SignalPart("FG", -W_FG, f"fg={fg}"))

    if len(closes) >= 5:
        mom = (closes[-1] - closes[-5]) / closes[-5]
        if mom > 0.008:
            cs.parts.append(SignalPart("MOM", W_MOM, f"{mom:+.2%}"))
        elif mom < -0.008:
            cs.parts.append(SignalPart("MOM", -W_MOM, f"{mom:+.2%}"))

    if cfg.CEX_ARB_ENABLED:
        book = cex_book if cex_book is not None else build_cex_book()
        venues = book.get(coin) or {}
        if venues:
            cs.parts.append(sig_cex_spread(coin, mark, venues))

    if cfg.GAP_ANALYSIS_ENABLED and candles:
        cs.parts.append(sig_gap(candles))

    if cfg.FLOW_ANALYSIS_ENABLED:
        cs.parts.append(sig_large_flow(client, coin, mark))

    if cfg.NEWS_ENABLED:
        cs.parts.append(sig_macro_news(fg))

    if strategy_weights:
        apply_weights(cs.parts, strategy_weights)

    cs.compute()
    return cs
