"""Dinamik kaldıraç — sinyal, volatilite, backtest WR, funding."""
from __future__ import annotations

from binance_futures_trader import config as cfg

# Büyük cap'ler daha düşük max kaldıraç
_COIN_TIER: dict[str, float] = {
    "BTC": 0.85,
    "ETH": 0.9,
    "BNB": 0.92,
    "SOL": 0.95,
}


def _atr_pct(candles: list[dict], period: int = 14) -> float:
    if len(candles) < period + 2:
        return 0.02
    trs: list[float] = []
    for i in range(-period, 0):
        h = float(candles[i].get("h") or 0)
        l = float(candles[i].get("l") or 0)
        c_prev = float(candles[i - 1].get("c") or candles[i].get("o") or 0)
        if h <= 0 or l <= 0:
            continue
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        trs.append(tr)
    if not trs:
        return 0.02
    atr = sum(trs) / len(trs)
    last_c = float(candles[-1].get("c") or 1)
    return atr / last_c if last_c > 0 else 0.02


def compute_leverage(
    coin: str,
    *,
    confidence: float,
    total_score: float,
    bt_wr: float = 0.55,
    candles: list[dict] | None = None,
    funding: float = 0.0,
    side: str = "LONG",
) -> tuple[int, str]:
    """
    Kaldıraç: MIN–MAX arası, strateji verisine göre.
    Yüksek güven + iyi backtest → daha yüksek (risk sınırlı).
    Yüksek volatilite / zayıf WR / aşırı funding → düşük.
    """
    lev_min = cfg.LEVERAGE_MIN
    lev_max = cfg.LEVERAGE_MAX
    mid = cfg.LEVERAGE_DEFAULT

    # Backtest WR: 0.35 → min, 0.55 → mid, 0.70+ → üst band
    if bt_wr < 0.4:
        wr_lev = lev_min
    elif bt_wr < 0.5:
        wr_lev = lev_min + (mid - lev_min) * 0.5
    elif bt_wr < 0.58:
        wr_lev = mid
    elif bt_wr < 0.68:
        wr_lev = mid + (lev_max - mid) * 0.45
    else:
        wr_lev = lev_max * 0.92

    # Sinyal güveni (0–8): zayıf sinyal → kıs
    conf = max(0.0, min(8.0, confidence))
    conf_mult = 0.55 + (conf / 8.0) * 0.55

    # Skor netliği
    score_mult = 0.85 + min(0.15, abs(total_score) / 12.0)

    lev = wr_lev * conf_mult * score_mult

    # Volatilite (ATR%)
    vol_note = ""
    if candles:
        atrp = _atr_pct(candles)
        if atrp > 0.045:
            lev *= 0.55
            vol_note = f"vol yüksek {atrp*100:.1f}%"
        elif atrp > 0.03:
            lev *= 0.75
            vol_note = f"vol orta {atrp*100:.1f}%"
        elif atrp < 0.012:
            lev *= 1.08
            vol_note = f"vol düşük {atrp*100:.1f}%"

    # Funding — pozisyon yönüne ters yüksek funding → kıs
    fund_note = ""
    if funding > 0.00015 and side == "LONG":
        lev *= 0.7
        fund_note = "fund+ long"
    elif funding < -0.00012 and side == "SHORT":
        lev *= 0.7
        fund_note = "fund+ short"
    elif funding < -0.00008 and side == "LONG":
        lev *= 1.05
    elif funding > 0.0001 and side == "SHORT":
        lev *= 1.05

    tier = _COIN_TIER.get(coin.upper(), 1.0)
    lev *= tier

    lev = int(round(max(lev_min, min(lev_max, lev))))
    if cfg.is_scalp():
        from binance_futures_trader.scalp_strategy import scalp_leverage_boost

        lev = scalp_leverage_boost(lev, conf)
    parts = [f"WR{bt_wr*100:.0f}%", f"conf{conf:.1f}", f"x{lev}"]
    if cfg.is_scalp():
        parts.insert(0, "SCALP")
    if vol_note:
        parts.append(vol_note)
    if fund_note:
        parts.append(fund_note)
    return lev, " · ".join(parts)
