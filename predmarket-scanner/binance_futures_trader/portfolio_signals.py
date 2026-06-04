"""Canlı sinyal — portföy backtest ile aynı MTF + BB/RSI/ATR mantığı."""
from __future__ import annotations

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.portfolio_backtest import (
    AdvVariant,
    _score_signal,
    load_advanced_variants,
)
from binance_futures_trader.signals import CoinSignal, SignalPart, W_BB, W_RSI

_variant_cache: AdvVariant | None = None


def _active_variant() -> AdvVariant | None:
    global _variant_cache
    if _variant_cache is not None:
        return _variant_cache
    vid = cfg.EDU_STRATEGY_ID or "adv_alpha_max"
    for v in load_advanced_variants():
        if v.id == vid:
            _variant_cache = v
            return v
    variants = load_advanced_variants()
    _variant_cache = variants[0] if variants else None
    return _variant_cache


def analyze_coin_portfolio(
    client: BinanceFuturesClient,
    coin: str,
    mark: float,
    *,
    strategy_weights: dict[str, float] | None = None,
    backtest_wr: float = 0.5,
) -> CoinSignal:
    from binance_futures_trader.learner import apply_weights

    v = _active_variant()
    cs = CoinSignal(coin=coin, mark_px=mark, backtest_wr=backtest_wr)
    if not v:
        return cs

    ltf = client.klines(coin, v.ltf_interval, 120)
    htf = client.klines(coin, v.htf_interval, 80)
    if len(ltf) < 50:
        return cs

    i = len(ltf) - 1
    score, aligned, side = _score_signal(v, ltf, htf, i)
    if not side:
        return cs

    parts: list[SignalPart] = []
    if score > 0:
        parts.append(SignalPart("RSI", W_RSI, "portfolio long"))
        parts.append(SignalPart("BB", W_BB * 0.8, "mtf"))
    else:
        parts.append(SignalPart("RSI", -W_RSI, "portfolio short"))
        parts.append(SignalPart("BB", -W_BB * 0.8, "mtf"))
    if v.use_mtf:
        parts.append(SignalPart("EMA", 1.0 if score > 0 else -1.0, "htf"))
    parts.append(SignalPart("ADX", 0.5 if score > 0 else -0.5, f"align={aligned}"))

    if strategy_weights:
        apply_weights(parts, strategy_weights)
    cs.parts = parts
    cs.compute(min_score=v.min_score)
    return cs
