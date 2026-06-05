"""Makro haber / sentiment proxy (ücretsiz API)."""
from __future__ import annotations

import time

import httpx

from binance_futures_trader.signals import SignalPart

W_NEWS = 1.2
_cache: tuple[float, dict] = (0.0, {})


def _global_market() -> dict:
    global _cache
    now = time.time()
    if now - _cache[0] < 300 and _cache[1]:
        return _cache[1]
    out: dict = {}
    try:
        r = httpx.get("https://api.coingecko.com/api/v3/global", timeout=10.0)
        g = r.json().get("data") or {}
        out["mcap_change_24h"] = float(
            (g.get("market_cap_change_percentage_24h_usd") or 0)
        )
    except Exception:
        out["mcap_change_24h"] = 0.0
    _cache = (now, out)
    return out


def sig_macro_news(fg: int) -> SignalPart:
    """CoinGecko global + Fear&Greed birleşik makro bias."""
    g = _global_market()
    mcap_ch = float(g.get("mcap_change_24h") or 0)
    score = 0.0
    if mcap_ch > 2.5:
        score += W_NEWS * 0.6
    elif mcap_ch < -2.5:
        score -= W_NEWS * 0.6
    if fg <= 20:
        score += W_NEWS * 0.5
    elif fg >= 80:
        score -= W_NEWS * 0.5
    if abs(score) < 0.1:
        return SignalPart("NEWS", 0.0, f"mcap24h {mcap_ch:+.1f}% fg={fg}")
    return SignalPart("NEWS", score, f"mcap24h {mcap_ch:+.1f}% fg={fg}")
