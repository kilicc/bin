"""BERSERK2 — en hareketli top-N USDT perpetual seçimi (varsayılan 20)."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

_lock = threading.Lock()
_top10: tuple[str, ...] = ()
_updated_at: float = 0.0
_TTL_SEC = 15.0
_EXCLUDE_BASE = frozenset(
    {"BTC", "USDC", "USDT", "FDUSD", "TUSD", "BUSD", "DAI", "EUR", "AEUR"}
)
_LIQUID_FALLBACK: tuple[str, ...] = (
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "BNBUSDT",
    "ETHUSDT",
    "DOTUSDT",
    "MATICUSDT",
)


def configured_top_n(default: int = 20) -> int:
    raw = os.getenv("BERSERK2_TOP_N", "").strip()
    if not raw:
        try:
            from elite_trader.mode_profiles import get_profile

            raw = str((get_profile("berserk2") or {}).get("berserk2_top_n") or default)
        except Exception:
            raw = str(default)
    try:
        return max(5, min(40, int(float(raw))))
    except ValueError:
        return default


_TIER_S_SYMBOLS = frozenset(
    {"SOLUSDT", "ETHUSDT", "BNBUSDT", "AVAXUSDT"}
)
_TIER_A_SYMBOLS = frozenset(
    {"XRPUSDT", "ADAUSDT", "DOGEUSDT", "MATICUSDT", "LINKUSDT"}
)


def _norm_symbol(sym: str) -> str:
    s = str(sym or "").upper().strip()
    if not s:
        return ""
    if not s.endswith("USDT"):
        s = f"{s}USDT"
    return s


def _short_momentum(sym: str, price: float, price_history: dict[str, list]) -> float:
    hist = price_history.get(sym) or price_history.get(sym.replace("USDT", "")) or []
    if len(hist) < 2 or price <= 0:
        return 0.0
    old = float(hist[-2].get("price") or 0) if len(hist) >= 2 else float(hist[0].get("price") or 0)
    if old <= 0:
        return 0.0
    return abs((float(price) - old) / old * 100.0)


def _spread_quality_score(sym: str, spread_map: dict[str, float]) -> float:
    """Spread < 0.04% → +10 puan."""
    spread = spread_map.get(sym, 1.0)
    if spread < 0.0004:
        return 10.0
    if spread < 0.0008:
        return 5.0
    return 0.0


def _volume_surge_score(sym: str, volume_map: dict[str, float]) -> float:
    """Volume surge > 1.8 → +8 puan."""
    vol_ratio = volume_map.get(sym, 1.0)
    if vol_ratio > 1.8:
        return 8.0
    if vol_ratio > 1.4:
        return 5.0
    if vol_ratio > 1.1:
        return 2.0
    return 0.0


def _volatility_regime_score(hist: list[dict]) -> float:
    """ATR moderate → +6 puan (çok düşük veya extreme değil)."""
    if len(hist) < 5:
        return 0.0
    try:
        prices = [float(h.get("price", 0)) for h in hist[-5:]]
        if any(p <= 0 for p in prices):
            return 0.0
        avg = sum(prices) / len(prices)
        if avg <= 0:
            return 0.0
        diffs = [abs(p - prices[i-1]) / avg for i, p in enumerate(prices[1:], 1)]
        atr_pct = sum(diffs) / len(diffs) if diffs else 0.0
        if 0.02 < atr_pct < 0.10:
            return 6.0
        if 0.01 < atr_pct < 0.15:
            return 3.0
        return 0.0
    except Exception:
        return 0.0


def _micro_trend_score(hist: list[dict]) -> float:
    """Son 3 bar aligned → +5 puan."""
    if len(hist) < 3:
        return 0.0
    try:
        last3 = [float(h.get("price", 0)) for h in hist[-3:]]
        if any(p <= 0 for p in last3):
            return 0.0
        if all(last3[i] > last3[i-1] for i in range(1, len(last3))):
            return 5.0
        if all(last3[i] < last3[i-1] for i in range(1, len(last3))):
            return 5.0
        return 0.0
    except Exception:
        return 0.0


def _scalp_score(
    sym: str,
    price: float,
    price_history: dict[str, list],
    ticker_24h: dict[str, float],
    spread_map: dict[str, float],
    volume_map: dict[str, float],
) -> float:
    """Multi-factor scalp scoring."""
    mom = _short_momentum(sym, price, price_history)
    hist = price_history.get(sym) or price_history.get(sym.replace("USDT", "")) or []
    
    score = mom * 40  # momentum base
    score += _spread_quality_score(sym, spread_map)
    score += _volume_surge_score(sym, volume_map)
    score += _volatility_regime_score(hist)
    score += _micro_trend_score(hist)
    
    # Tier bonus
    if sym in _TIER_S_SYMBOLS:
        score += 5.0
    elif sym in _TIER_A_SYMBOLS:
        score += 2.0
    
    return score


def refresh_top_movers(
    watchlist: list[str],
    prices: dict[str, float],
    price_history: dict[str, list],
    *,
    min_volume_usdt: float = 5_000_000,
    top_n: int | None = None,
    ticker_24h: dict[str, float] | None = None,
    spread_map: dict[str, float] | None = None,
    volume_map: dict[str, float] | None = None,
) -> tuple[str, ...]:
    """Watchlist içinden hareket skoruna göre top-N güncelle (multi-factor)."""
    global _top10, _updated_at
    top_n = configured_top_n() if top_n is None else max(5, min(40, int(top_n)))
    now = time.time()
    scores: list[tuple[float, str]] = []
    ticker_24h = ticker_24h or {}
    spread_map = spread_map or {}
    volume_map = volume_map or {}
    
    use_multi_factor = bool(spread_map or volume_map)

    for raw in watchlist:
        sym = _norm_symbol(raw)
        if not sym:
            continue
        base = sym.replace("USDT", "")
        if base in _EXCLUDE_BASE:
            continue
        fp = float(prices.get(sym) or prices.get(base) or 0)
        if fp <= 0:
            continue
        
        if use_multi_factor:
            score = _scalp_score(sym, fp, price_history, ticker_24h, spread_map, volume_map)
            min_sc = float(os.getenv("BERSERK2_MOVER_MIN_SCORE", "45"))
            if score < min_sc:
                continue
        else:
            ch24 = abs(float(ticker_24h.get(sym) or ticker_24h.get(base) or 0))
            mom = _short_momentum(sym, fp, price_history)
            score = mom * 0.6 + ch24 * 0.4
            if score <= 0.01 and ch24 <= 0.01:
                continue
            if min_volume_usdt > 0 and ch24 < 0.015 and mom < 0.03:
                continue
        
        scores.append((score, sym))

    scores.sort(key=lambda x: -x[0])
    picked_list = [s for _, s in scores[: max(1, top_n)]]
    if len(picked_list) < top_n:
        have = set(picked_list)
        universe_set = {_norm_symbol(x) for x in watchlist if x}
        for fb in _LIQUID_FALLBACK:
            if len(picked_list) >= top_n:
                break
            if fb in have:
                continue
            if universe_set and fb not in universe_set and fb.replace("USDT", "") not in {
                u.replace("USDT", "") for u in universe_set
            }:
                continue
            fp = float(prices.get(fb) or prices.get(fb.replace("USDT", "")) or 0)
            if fp > 0:
                picked_list.append(fb)
                have.add(fb)
    picked = tuple(picked_list[:top_n])
    with _lock:
        _top10 = picked
        _updated_at = now
    return picked


def get_top10() -> tuple[str, ...]:
    with _lock:
        if _top10 and (time.time() - _updated_at) < _TTL_SEC:
            return _top10
        return _top10


def is_top_mover(symbol: str) -> bool:
    sym = _norm_symbol(symbol)
    if not sym:
        return False
    top = get_top10()
    if not top:
        return sym in _LIQUID_FALLBACK
    return sym in top


def iter_tracked_symbols() -> tuple[str, ...]:
    """Sürekli taranan top-N (+ henüz dolmadıysa likit yedek)."""
    top = get_top10()
    n = configured_top_n()
    if top:
        return top[:n]
    return _LIQUID_FALLBACK[: min(n, len(_LIQUID_FALLBACK))]


def movers_snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "top10": list(_top10),
            "top_n": configured_top_n(),
            "updated_at": _updated_at,
            "age_sec": round(time.time() - _updated_at, 1) if _updated_at else None,
        }
