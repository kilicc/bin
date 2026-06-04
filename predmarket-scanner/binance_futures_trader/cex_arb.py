"""Çoklu borsa fiyat farkı — Binance vs Bybit/OKX/Gate medyanı."""
from __future__ import annotations

import statistics
import time
from typing import Any

import httpx

from binance_futures_trader import config as cfg
from binance_futures_trader.signals import SignalPart

BN = "https://fapi.binance.com"
BYBIT = "https://api.bybit.com/v5/market/tickers"
OKX = "https://www.okx.com/api/v5/market/tickers"
GATE = "https://api.gateio.ws/api/v4/futures/usdt/tickers"

_book_cache: tuple[float, dict[str, dict[str, float]]] = (0.0, {})
ARB_MIN = 0.0012
ARB_CAP = 0.008
W_ARB = 2.2


def _keys(coin: str) -> tuple[str, str, str, str]:
    u = f"{coin}USDT"
    return (u, u, f"{coin}-USDT-SWAP", f"{coin}_USDT")


def _get(url: str, params: dict | None = None, timeout: float = 15.0) -> Any:
    r = httpx.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def build_cex_book(watchlist: list[str] | None = None) -> dict[str, dict[str, float]]:
    global _book_cache
    now = time.time()
    if now - _book_cache[0] < 45 and _book_cache[1]:
        return _book_cache[1]
    coins = watchlist or cfg.WATCHLIST
    bn: dict[str, float] = {}
    bb: dict[str, float] = {}
    ok: dict[str, float] = {}
    gt: dict[str, float] = {}
    try:
        for row in _get(f"{BN}/fapi/v1/ticker/price") or []:
            if isinstance(row, dict) and row.get("symbol"):
                bn[str(row["symbol"])] = float(row["price"])
    except Exception:
        pass
    try:
        data = _get(BYBIT, {"category": "linear", "limit": "1000"})
        for it in (data or {}).get("result", {}).get("list") or []:
            sym = str(it.get("symbol", ""))
            px = float(it.get("lastPrice") or it.get("markPrice") or 0)
            if sym and px > 0:
                bb[sym] = px
    except Exception:
        pass
    try:
        data = _get(OKX, {"instType": "SWAP"})
        for it in (data or {}).get("data") or []:
            iid = str(it.get("instId", ""))
            px = float(it.get("last") or it.get("idxPx") or 0)
            if iid and px > 0:
                ok[iid] = px
    except Exception:
        pass
    try:
        raw = _get(GATE)
        if isinstance(raw, list):
            for it in raw:
                c = str(it.get("contract", ""))
                p = float(it.get("last") or it.get("mark_price") or 0)
                if c and p > 0:
                    gt[c] = p
    except Exception:
        pass
    book: dict[str, dict[str, float]] = {}
    for coin in coins:
        bns, bbs, oks, gts = _keys(coin)
        row: dict[str, float] = {}
        if bn.get(bns):
            row["binance"] = bn[bns]
        if bb.get(bbs):
            row["bybit"] = bb[bbs]
        if ok.get(oks):
            row["okx"] = ok[oks]
        if gt.get(gts):
            row["gate"] = gt[gts]
        if row:
            book[coin] = row
    _book_cache = (now, book)
    return book


def sig_cex_spread(coin: str, bn_px: float, venues: dict[str, float]) -> SignalPart:
    """Binance fiyatı diğer borsa medyanından sapmışsa mean-reversion."""
    others = [v for k, v in venues.items() if k != "binance" and v > 0]
    if len(others) < 1 or bn_px <= 0:
        return SignalPart("CEX_ARB", 0.0, "yetersiz borsa")
    med = statistics.median(others + [bn_px])
    if med <= 0:
        return SignalPart("CEX_ARB", 0.0, "medyan yok")
    diff = (bn_px - med) / med
    if abs(diff) < ARB_MIN:
        return SignalPart("CEX_ARB", 0.0, f"spread {diff*100:+.2f}%")
    intensity = min(1.0, (abs(diff) - ARB_MIN) / max(ARB_CAP - ARB_MIN, 1e-9))
    score = -W_ARB * intensity if diff > 0 else W_ARB * intensity
    labs = ",".join(f"{k}:{v:.4g}" for k, v in sorted(venues.items()))
    return SignalPart("CEX_ARB", score, f"BN vs med {diff*100:+.2f}% | {labs}")
