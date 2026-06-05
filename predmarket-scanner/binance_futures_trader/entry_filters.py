"""Giriş filtreleri — erken SL / zayıf giriş önleme."""
from __future__ import annotations

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.leverage import _atr_pct


MOMENTUM_TAGS = frozenset({"MOM3", "MOM", "BURST", "EMA", "VOL"})


def effective_sl_frac(candles: list[dict] | None) -> float:
    """ATR tabanlı minimum SL — çok dar SL'de hemen stop olmasın."""
    base = cfg.SL_PCT
    if not candles or len(candles) < 14:
        return base
    atrp = _atr_pct(candles)
    dynamic = atrp * cfg.SL_ATR_MULT
    return round(min(0.025, max(base, dynamic)), 5)


def has_momentum_tag(strategies: str) -> bool:
    parts = {s.strip().upper() for s in (strategies or "").split(",") if s.strip()}
    return bool(parts & MOMENTUM_TAGS)


def entry_microstructure_ok(
    client: BinanceFuturesClient,
    coin: str,
    side: str,
) -> tuple[bool, str]:
    """Son mum yönü girişe ters ise bekle (açılır açılmaz SL riski)."""
    try:
        candles = client.klines(coin, cfg.CANDLE_INTERVAL, 6)
    except Exception:
        return True, ""
    if len(candles) < 3:
        return True, ""
    last = float(candles[-1].get("c") or 0)
    prev = float(candles[-2].get("c") or 0)
    o_last = float(candles[-1].get("o") or last)
    if last <= 0 or prev <= 0:
        return True, ""
    bar_chg = (last - o_last) / o_last
    trend = (last - prev) / prev
    if side == "LONG":
        if bar_chg < -cfg.SL_BUFFER_PCT * 2 and trend < 0:
            return False, "son mum kırmızı"
        if trend < -cfg.SCALP_MOM_THRESH:
            return False, "kısa trend aşağı"
    else:
        if bar_chg > cfg.SL_BUFFER_PCT * 2 and trend > 0:
            return False, "son mum yeşil"
        if trend > cfg.SCALP_MOM_THRESH:
            return False, "kısa trend yukarı"
    return True, ""
