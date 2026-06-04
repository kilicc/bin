"""Hızlı mum backtest — giriş öncesi coin kalitesi."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.signals import _rsi, _ema, fear_greed

LOOKBACK = 30
BT_CACHE_PATH = cfg.ROOT / "data" / "binance_futures_bt_cache.json"


def quick_backtest(client: BinanceFuturesClient, coin: str, days: int = 5) -> dict:
    n = days * 24 * 4 + LOOKBACK + 5
    candles = client.klines(coin, cfg.CANDLE_INTERVAL, min(n, 500))
    if len(candles) < LOOKBACK + 10:
        return {"wins": 0, "losses": 0, "win_rate": 0.5, "trades": 0, "avg_pnl": 0.0}

    wins = losses = 0
    pnls: list[float] = []
    bt_min = cfg.MIN_SCORE * (0.45 if cfg.is_scalp() else 0.55)
    fg = fear_greed()

    for i in range(LOOKBACK, len(candles) - 2):
        window = candles[i - LOOKBACK : i]
        closes = [float(c["c"]) for c in window]
        if len(closes) < 20:
            continue
        mark = float(candles[i]["o"])
        score = 0.0
        rsi = _rsi(closes, period=10 if cfg.is_scalp() else 14)
        rsi_lo, rsi_hi = (40, 60) if cfg.is_scalp() else (35, 65)
        if rsi < rsi_lo:
            score += 2.0
        elif rsi > rsi_hi:
            score -= 2.0
        if cfg.is_scalp():
            ef, es = _ema(closes[-24:], 5), _ema(closes[-24:], 13)
        else:
            ef, es = _ema(closes[-20:], 9), _ema(closes[-20:], 21)
        if ef > es:
            score += 1.2
        elif ef < es:
            score -= 1.2
        if cfg.is_scalp() and len(closes) >= 3:
            mom3 = (closes[-1] - closes[-3]) / closes[-3]
            if mom3 > cfg.SCALP_MOM_THRESH:
                score += 1.0
            elif mom3 < -cfg.SCALP_MOM_THRESH:
                score -= 1.0
        if fg <= 25:
            score += 1.0
        elif fg >= 75:
            score -= 1.0
        if abs(score) < bt_min:
            continue
        side = "LONG" if score > 0 else "SHORT"
        tp = mark * (1 + cfg.TP_PCT) if side == "LONG" else mark * (1 - cfg.TP_PCT)
        sl = mark * (1 - cfg.SL_PCT) if side == "LONG" else mark * (1 + cfg.SL_PCT)
        hold = cfg.SCALP_BT_HOLD_BARS if cfg.is_scalp() else 20
        for j in range(i + 1, min(i + hold, len(candles))):
            hi, lo = float(candles[j]["h"]), float(candles[j]["l"])
            if side == "LONG":
                if lo <= sl:
                    losses += 1
                    pnls.append(-cfg.SL_PCT)
                    break
                if hi >= tp:
                    wins += 1
                    pnls.append(cfg.TP_PCT)
                    break
            else:
                if hi >= sl:
                    losses += 1
                    pnls.append(-cfg.SL_PCT)
                    break
                if lo <= tp:
                    wins += 1
                    pnls.append(cfg.TP_PCT)
                    break
        else:
            last = float(candles[min(i + 19, len(candles) - 1)]["c"])
            pnl = (last - mark) / mark if side == "LONG" else (mark - last) / mark
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            pnls.append(pnl)

    n_tr = wins + losses
    return {
        "wins": wins,
        "losses": losses,
        "win_rate": wins / n_tr if n_tr else 0.5,
        "trades": n_tr,
        "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
    }


def run_startup_backtests(client: BinanceFuturesClient) -> dict[str, float]:
    out: dict[str, float] = {}
    for coin in cfg.WATCHLIST:
        try:
            bt = quick_backtest(client, coin)
            out[coin] = float(bt.get("win_rate") or 0.5)
        except Exception:
            out[coin] = 0.5
    save_bt_cache(out)
    return out


def save_bt_cache(wrs: dict[str, float]) -> None:
    BT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BT_CACHE_PATH.write_text(
        json.dumps(
            {"ts": datetime.now(timezone.utc).isoformat(), "win_rates": wrs},
            indent=0,
        ),
        encoding="utf-8",
    )


def load_bt_cache() -> dict[str, float]:
    if not BT_CACHE_PATH.is_file():
        return {}
    try:
        data = json.loads(BT_CACHE_PATH.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in (data.get("win_rates") or {}).items()}
    except Exception:
        return {}
