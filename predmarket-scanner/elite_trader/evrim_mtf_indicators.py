"""
Evrim — çoklu zaman dilimli indikatör motoru.

Yalnızca skor katkısı; tek başına işlem açmaz.
TF: 5m, 15m, 1h
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

TIMEFRAMES = ("5m", "15m", "1h")
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 60.0
_client: Any = None


@dataclass
class MtfAdjust:
    component_deltas: dict[str, float] = field(default_factory=dict)
    stake_mult: float = 1.0
    chop_mode: bool = False
    min_score_delta: int = 0
    max_tier_cap: str | None = None
    notes: list[str] = field(default_factory=list)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _get_client() -> Any:
    global _client
    if _client is None:
        from binance_futures_trader.client import BinanceFuturesClient

        _client = BinanceFuturesClient()
    return _client


def _coin(symbol: str) -> str:
    s = str(symbol or "").upper()
    return s.replace("USDT", "") if s.endswith("USDT") else s


def _closes(candles: list[dict]) -> list[float]:
    return [float(x["c"]) for x in candles]


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values or period < 1:
        return []
    k = 2.0 / (period + 1)
    out: list[float] = []
    ema = values[0]
    out.append(ema)
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
        out.append(ema)
    return out


def _ema_last(values: list[float], period: int) -> float:
    s = _ema_series(values, period)
    return s[-1] if s else 0.0


def _rsi(values: list[float], period: int) -> float:
    if len(values) < period + 2:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l <= 0:
        return 100.0 if avg_g > 0 else 50.0
    rs = avg_g / avg_l
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(values: list[float]) -> dict[str, float]:
    if len(values) < 35:
        return {"macd": 0, "signal": 0, "hist": 0, "hist_prev": 0}
    ema12 = _ema_series(values, 12)
    ema26 = _ema_series(values, 26)
    macd_line = [a - b for a, b in zip(ema12[-len(ema26) :], ema26)]
    if len(macd_line) < 9:
        return {"macd": 0, "signal": 0, "hist": 0, "hist_prev": 0}
    sig = _ema_series(macd_line, 9)
    hist = macd_line[-1] - sig[-1]
    hist_prev = macd_line[-2] - sig[-2] if len(sig) > 1 else hist
    return {
        "macd": macd_line[-1],
        "signal": sig[-1],
        "hist": hist,
        "hist_prev": hist_prev,
    }


def _atr_series(candles: list[dict], period: int = 14) -> list[float]:
    if len(candles) < period + 2:
        return []
    trs: list[float] = []
    for i in range(1, len(candles)):
        h = float(candles[i]["h"])
        l = float(candles[i]["l"])
        pc = float(candles[i - 1]["c"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return []
    out: list[float] = []
    atr = sum(trs[:period]) / period
    out.append(atr)
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out.append(atr)
    return out


def _atr_pct(candles: list[dict], period: int = 14) -> tuple[float, float]:
    atrs = _atr_series(candles, period)
    if not atrs:
        return 0.0, 1.0
    last = float(candles[-1]["c"]) or 1.0
    atr_pct = (atrs[-1] / last) * 100.0
    avg = sum(atrs[-min(20, len(atrs)) :]) / max(1, min(20, len(atrs)))
    expansion = atrs[-1] / avg if avg > 0 else 1.0
    return round(atr_pct, 4), round(expansion, 3)


def _bollinger(values: list[float], period: int = 20, mult: float = 2.0) -> dict[str, float]:
    if len(values) < period:
        return {"upper": 0, "lower": 0, "mid": 0, "bandwidth": 0, "pct_b": 0.5}
    window = values[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    std = var**0.5
    upper = mid + mult * std
    lower = mid - mult * std
    price = values[-1]
    bw = ((upper - lower) / mid * 100) if mid else 0
    pct_b = (price - lower) / (upper - lower) if upper > lower else 0.5
    return {
        "upper": upper,
        "lower": lower,
        "mid": mid,
        "bandwidth": bw,
        "pct_b": pct_b,
        "squeeze": bw < 2.5,
        "expansion": bw > 5.5,
        "breakout_up": price > upper,
        "breakout_down": price < lower,
    }


def _vwap_proxy(candles: list[dict]) -> float:
    num = 0.0
    den = 0.0
    for c in candles[-48:]:
        tp = (float(c["h"]) + float(c["l"]) + float(c["c"])) / 3.0
        v = float(c.get("v") or 1)
        num += tp * v
        den += v
    return num / den if den else float(candles[-1]["c"])


def _adx(candles: list[dict], period: int = 14) -> float:
    if len(candles) < period + 5:
        return 0.0
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for i in range(1, len(candles)):
        h = float(candles[i]["h"])
        l = float(candles[i]["l"])
        ph = float(candles[i - 1]["h"])
        pl = float(candles[i - 1]["l"])
        pc = float(candles[i - 1]["c"])
        up = h - ph
        down = pl - l
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return 0.0
    sp = sum(plus_dm[:period])
    sm = sum(minus_dm[:period])
    st = sum(trs[:period])
    for i in range(period, len(trs)):
        sp = sp - sp / period + plus_dm[i]
        sm = sm - sm / period + minus_dm[i]
        st = st - st / period + trs[i]
    if st <= 0:
        return 0.0
    di_p = 100 * sp / st
    di_m = 100 * sm / st
    dx = 100 * abs(di_p - di_m) / (di_p + di_m) if (di_p + di_m) else 0
    return round(dx, 2)


def _ema_stack_bias(closes: list[float]) -> str:
    if len(closes) < 210:
        e9 = _ema_last(closes, 9)
        e21 = _ema_last(closes, 21)
        e50 = _ema_last(closes, 50)
        e200 = e50
    else:
        e9 = _ema_last(closes, 9)
        e21 = _ema_last(closes, 21)
        e50 = _ema_last(closes, 50)
        e200 = _ema_last(closes, 200)
    if e9 > e21 > e50 > e200:
        return "bull"
    if e9 < e21 < e50 < e200:
        return "bear"
    if e9 > e21 > e50:
        return "bull_partial"
    if e9 < e21 < e50:
        return "bear_partial"
    return "neutral"


def compute_tf_indicators(candles: list[dict]) -> dict[str, Any]:
    closes = _closes(candles)
    if len(closes) < 30:
        return {"ok": False}
    atr_pct, atr_exp = _atr_pct(candles)
    macd = _macd(closes)
    bb = _bollinger(closes)
    price = closes[-1]
    vwap = _vwap_proxy(candles)
    return {
        "ok": True,
        "price": price,
        "ema9": _ema_last(closes, 9),
        "ema21": _ema_last(closes, 21),
        "ema50": _ema_last(closes, 50),
        "ema200": _ema_last(closes, 200) if len(closes) >= 200 else _ema_last(closes, 50),
        "ema_stack": _ema_stack_bias(closes),
        "rsi7": round(_rsi(closes, 7), 2),
        "rsi14": round(_rsi(closes, 14), 2),
        "macd_hist": round(macd["hist"], 6),
        "macd_hist_delta": round(macd["hist"] - macd["hist_prev"], 6),
        "macd_hist_rising": macd["hist"] > macd["hist_prev"],
        "atr_pct": atr_pct,
        "atr_expansion": atr_exp,
        "bb_bandwidth": round(bb["bandwidth"], 3),
        "bb_squeeze": bb["squeeze"],
        "bb_expansion": bb["expansion"],
        "bb_breakout_up": bb["breakout_up"],
        "bb_breakout_down": bb["breakout_down"],
        "bb_pct_b": round(bb["pct_b"], 3),
        "vwap": round(vwap, 6),
        "above_vwap": price > vwap,
        "adx": _adx(candles),
    }


def fetch_klines(symbol: str, interval: str, limit: int) -> list[dict]:
    c = _get_client()
    coin = _coin(symbol)
    lim = {"5m": 120, "15m": 80, "1h": 60}.get(interval, limit)
    return c.klines(coin, interval, lim) or []


def compute_mtf_snapshot(symbol: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """5m / 15m / 1h indikatör paketi."""
    profile = profile or {}
    if not profile.get("evrim_mtf_enabled", True):
        return {"ok": False, "disabled": True}

    key = _coin(symbol)
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    tfs = profile.get("evrim_mtf_timeframes") or list(TIMEFRAMES)
    by_tf: dict[str, Any] = {}
    for tf in tfs:
        if tf not in ("5m", "15m", "1h"):
            continue
        kl = fetch_klines(symbol, tf, 120)
        by_tf[tf] = compute_tf_indicators(kl)

    adx_chop = float(profile.get("evrim_adx_chop_threshold") or 18)
    adx_15 = float((by_tf.get("15m") or {}).get("adx") or 0)
    adx_5 = float((by_tf.get("5m") or {}).get("adx") or 0)
    chop = adx_15 < adx_chop or (adx_5 < adx_chop and adx_15 < adx_chop + 5)

    stacks = [
        (by_tf.get(tf) or {}).get("ema_stack") for tf in ("1h", "15m", "5m") if tf in by_tf
    ]
    bull_n = sum(1 for s in stacks if s and "bull" in str(s))
    bear_n = sum(1 for s in stacks if s and "bear" in str(s))
    if bull_n >= 2:
        align = "bull"
    elif bear_n >= 2:
        align = "bear"
    else:
        align = "mixed"

    atr_exp = float((by_tf.get("5m") or {}).get("atr_expansion") or 1.0)
    rsi14 = float((by_tf.get("5m") or {}).get("rsi14") or 50)

    snap = {
        "ok": True,
        "symbol": symbol,
        "timeframes": by_tf,
        "summary": {
            "trend_alignment": align,
            "chop_mode": chop,
            "adx_15m": adx_15,
            "adx_5m": adx_5,
            "atr_expansion_5m": atr_exp,
            "rsi14_5m": rsi14,
            "alignment_score": bull_n - bear_n,
        },
    }
    _CACHE[key] = (now, snap)
    return snap


def apply_mtf_adjustments(
    side: str,
    components: dict[str, float],
    snapshot: dict[str, Any],
    profile: dict[str, Any],
) -> MtfAdjust:
    """Indikatörler yalnızca skor bileşenlerine katkı — tek başına trade yok."""
    adj = MtfAdjust(stake_mult=1.0)
    if not snapshot.get("ok"):
        return adj

    weights = profile.get("indicator_weights") or {}
    w_align = float(weights.get("trend_alignment", 1.0))
    w_macd = float(weights.get("macd", 1.0))
    w_bb = float(weights.get("bollinger", 1.0))
    w_vwap = float(weights.get("vwap", 1.0))
    w_rsi = float(weights.get("rsi_penalty", 1.0))

    summary = snapshot.get("summary") or {}
    tfs = snapshot.get("timeframes") or {}
    tf5 = tfs.get("5m") or {}
    tf15 = tfs.get("15m") or {}
    tf1h = tfs.get("1h") or {}

    align = str(summary.get("trend_alignment") or "mixed")
    if side == "LONG" and align == "bull":
        d = 5.0 * w_align
        adj.component_deltas["trend_ema"] = adj.component_deltas.get("trend_ema", 0) + d
        adj.notes.append("mtf_ema_align_bull")
    elif side == "SHORT" and align == "bear":
        d = 5.0 * w_align
        adj.component_deltas["trend_ema"] = adj.component_deltas.get("trend_ema", 0) + d
        adj.notes.append("mtf_ema_align_bear")
    elif align in ("bull", "bear"):
        d = 2.0 * w_align
        adj.component_deltas["trend_ema"] = adj.component_deltas.get("trend_ema", 0) + d

    for tf in (tf15, tf1h, tf5):
        if not tf.get("ok"):
            continue
        if side == "LONG" and tf.get("above_vwap"):
            adj.component_deltas["trend_ema"] = adj.component_deltas.get("trend_ema", 0) + 1.0 * w_vwap
            adj.notes.append("vwap_long")
            break
        if side == "SHORT" and not tf.get("above_vwap"):
            adj.component_deltas["trend_ema"] = adj.component_deltas.get("trend_ema", 0) + 1.0 * w_vwap
            adj.notes.append("vwap_short")
            break

    hist = float(tf5.get("macd_hist") or 0)
    rising = bool(tf5.get("macd_hist_rising"))
    if side == "LONG" and hist > 0 and rising:
        adj.component_deltas["price_action"] = adj.component_deltas.get("price_action", 0) + 3.0 * w_macd
        adj.notes.append("macd_long")
    elif side == "SHORT" and hist < 0 and not rising:
        adj.component_deltas["price_action"] = adj.component_deltas.get("price_action", 0) + 3.0 * w_macd
        adj.notes.append("macd_short")

    if side == "LONG" and tf5.get("bb_breakout_up"):
        adj.component_deltas["price_action"] = adj.component_deltas.get("price_action", 0) + 2.0 * w_bb
        adj.notes.append("bb_break_up")
    elif side == "SHORT" and tf5.get("bb_breakout_down"):
        adj.component_deltas["price_action"] = adj.component_deltas.get("price_action", 0) + 2.0 * w_bb
        adj.notes.append("bb_break_down")

    rsi14 = float(tf5.get("rsi14") or 50)
    rsi7 = float(tf5.get("rsi7") or 50)
    if side == "LONG" and rsi14 > 70:
        pen = -3.0 * w_rsi
        adj.component_deltas["news_whale_risk"] = adj.component_deltas.get("news_whale_risk", 0) + pen
        adj.notes.append("rsi14_overbought_long")
    elif side == "SHORT" and rsi14 < 30:
        pen = -3.0 * w_rsi
        adj.component_deltas["news_whale_risk"] = adj.component_deltas.get("news_whale_risk", 0) + pen
        adj.notes.append("rsi14_oversold_short")
    if side == "LONG" and rsi7 > 75:
        adj.component_deltas["news_whale_risk"] = adj.component_deltas.get("news_whale_risk", 0) - 1.0 * w_rsi
    elif side == "SHORT" and rsi7 < 25:
        adj.component_deltas["news_whale_risk"] = adj.component_deltas.get("news_whale_risk", 0) - 1.0 * w_rsi

    atr_exp = float(summary.get("atr_expansion_5m") or 1.0)
    floor_mult = float(profile.get("evrim_atr_stake_floor_mult") or 0.80)
    if atr_exp < 0.85:
        adj.stake_mult *= floor_mult
        adj.notes.append("atr_low_stake_reduce")

    if summary.get("chop_mode"):
        adj.chop_mode = True
        adj.min_score_delta = 2
        adj.max_tier_cap = "normal"
        adj.notes.append("adx_chop")

    caps = {
        "price_action": 25,
        "volume_delta": 20,
        "volatility_atr": 15,
        "trend_ema": 15,
        "orderbook_liquidity": 10,
        "news_whale_risk": 10,
        "execution_quality": 5,
    }
    for k, delta in list(adj.component_deltas.items()):
        base = components.get(k, 0)
        adj.component_deltas[k] = round(
            _clamp(base + delta, 0, caps.get(k, 25)) - base, 2
        )

    return adj


def merge_mtf_into_components(
    components: dict[str, float],
    adj: MtfAdjust,
) -> dict[str, float]:
    out = dict(components)
    for k, delta in adj.component_deltas.items():
        out[k] = round(_clamp(out.get(k, 0) + delta, 0, 100), 2)
    total = sum(out.values())
    if total > 100:
        scale = 100 / total
        out = {k: round(v * scale, 2) for k, v in out.items()}
    return out
