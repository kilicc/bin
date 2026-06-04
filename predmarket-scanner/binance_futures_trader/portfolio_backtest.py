"""Gelişmiş portföy backtest — 22 coin, MTF, coin alpha, bileşik getiri hedefi."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.education_memory import log_inference, save_best_strategy
from binance_futures_trader.ta_indicators import adx, atr, bollinger, ema, macd, rsi, stochastic

REPORT_PATH = cfg.ROOT / "data" / "education" / "portfolio_backtest_6m.json"
VARIANTS_PATH = cfg.ROOT / "data" / "education" / "advanced_variants.json"
LOOKBACK = 220


@dataclass
class AdvVariant:
    id: str
    label: str
    risk_pct: float = 0.02
    max_positions: int = 6
    leverage: float = 3.0
    ltf_interval: str = "15m"
    htf_interval: str = "1h"
    min_score: float = 2.2
    min_modules: int = 2
    rsi_period: int = 14
    rsi_lo: float = 30.0
    rsi_hi: float = 70.0
    bb_period: int = 14
    bb_std: float = 2.0
    adx_min: float = 20.0
    adx_max: float = 50.0
    atr_sl_mult: float = 1.2
    atr_tp_mult: float = 3.5
    use_mtf: bool = True
    use_breakout: bool = False
    use_stoch: bool = False
    use_ema_pullback: bool = False
    use_trailing: bool = True
    trail_activate_pct: float = 0.008
    trail_distance_pct: float = 0.004
    coin_train_days: int = 90
    coin_min_pf: float = 1.05
    coin_min_wr: float = 0.48
    top_coins_n: int = 22
    hold_bars: int = 32
    fixed_coins: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AdvVariant:
        return cls(
            id=str(d["id"]),
            label=str(d.get("label") or d["id"]),
            risk_pct=float(d.get("risk_pct", 0.02)),
            max_positions=int(d.get("max_positions", 6)),
            leverage=float(d.get("leverage", 3)),
            ltf_interval=str(d.get("ltf_interval", "15m")),
            htf_interval=str(d.get("htf_interval", "1h")),
            min_score=float(d.get("min_score", 2.2)),
            min_modules=int(d.get("min_modules", 2)),
            rsi_period=int(d.get("rsi_period", 14)),
            rsi_lo=float(d.get("rsi_lo", 30)),
            rsi_hi=float(d.get("rsi_hi", 70)),
            bb_period=int(d.get("bb_period", 14)),
            bb_std=float(d.get("bb_std", 2.0)),
            adx_min=float(d.get("adx_min", 20)),
            adx_max=float(d.get("adx_max", 50)),
            atr_sl_mult=float(d.get("atr_sl_mult", 1.2)),
            atr_tp_mult=float(d.get("atr_tp_mult", 3.5)),
            use_mtf=bool(d.get("use_mtf", True)),
            use_breakout=bool(d.get("use_breakout")),
            use_stoch=bool(d.get("use_stoch")),
            use_ema_pullback=bool(d.get("use_ema_pullback")),
            use_trailing=bool(d.get("use_trailing", True)),
            trail_activate_pct=float(d.get("trail_activate_pct", 0.008)),
            trail_distance_pct=float(d.get("trail_distance_pct", 0.004)),
            coin_train_days=int(d.get("coin_train_days", 90)),
            coin_min_pf=float(d.get("coin_min_pf", 1.05)),
            coin_min_wr=float(d.get("coin_min_wr", 0.48)),
            top_coins_n=int(d.get("top_coins_n", 22)),
            hold_bars=int(d.get("hold_bars", 32)),
            fixed_coins=list(d.get("fixed_coins") or []),
        )


@dataclass
class PendingTrade:
    coin: str
    side: str
    entry_i: int
    entry_t: int
    entry_px: float
    sl_px: float
    tp_px: float
    size_usd: float
    trail_active: bool = False
    peak_px: float = 0.0
    use_trailing: bool = True


def load_advanced_variants() -> list[AdvVariant]:
    if not VARIANTS_PATH.is_file():
        return []
    data = json.loads(VARIANTS_PATH.read_text(encoding="utf-8"))
    return [AdvVariant.from_dict(v) for v in data.get("variants") or []]


def _htf_index(ltf_candles: list[dict], htf_candles: list[dict], ltf_i: int) -> int:
    if not htf_candles:
        return -1
    t = int(ltf_candles[ltf_i]["t"])
    best = -1
    for j, h in enumerate(htf_candles):
        if int(h["t"]) <= t:
            best = j
        else:
            break
    return best


def _htf_trend(htf_candles: list[dict], hi: int) -> int:
    """+1 bull, -1 bear, 0 nötr."""
    if hi < 50:
        return 0
    closes = [float(c["c"]) for c in htf_candles[: hi + 1]]
    e50 = ema(closes[-60:], 50) if len(closes) >= 50 else ema(closes, min(50, len(closes)))
    e200 = ema(closes[-min(220, len(closes)) :], min(200, len(closes) - 1))
    px = closes[-1]
    if px > e50 > e200:
        return 1
    if px < e50 < e200:
        return -1
    return 0


def _score_signal(
    variant: AdvVariant,
    ltf: list[dict],
    htf: list[dict],
    i: int,
) -> tuple[float, int, str]:
    window = ltf[i - 80 : i]
    closes = [float(c["c"]) for c in window]
    vols = [float(c.get("v") or 0) for c in window]
    mark = float(ltf[i]["o"])
    parts: list[tuple[str, float]] = []

    hi = _htf_index(ltf, htf, i)
    trend = _htf_trend(htf, hi) if variant.use_mtf and hi >= 0 else 0

    ax = adx(window)
    if ax < variant.adx_min or ax > variant.adx_max:
        return 0.0, 0, ""

    r = rsi(closes, variant.rsi_period)
    lower, _mid, upper = bollinger(closes, variant.bb_period, variant.bb_std)

    if r < variant.rsi_lo and mark <= lower * 1.002:
        parts.append(("RSI", 2.0))
        parts.append(("BB", 1.5))
    elif r > variant.rsi_hi and mark >= upper * 0.998:
        parts.append(("RSI", -2.0))
        parts.append(("BB", -1.5))

    ef = ema(closes[-30:], 9)
    es = ema(closes[-30:], 21)
    if ef > es * 1.001:
        parts.append(("EMA", 1.2))
    elif ef < es * 0.999:
        parts.append(("EMA", -1.2))

    if variant.use_stoch:
        k, d = stochastic(closes)
        if k < 22 and d < 25:
            parts.append(("STOCH", 1.2))
        elif k > 78 and d > 75:
            parts.append(("STOCH", -1.2))

    if variant.use_breakout and len(vols) >= 15:
        avg_v = sum(vols[-15:-1]) / 14
        if avg_v > 0 and vols[-1] > avg_v * 2.0:
            direction = 1 if closes[-1] > closes[-5] else -1
            parts.append(("VOL", 1.5 * direction))

    if variant.use_ema_pullback and trend != 0:
        e21 = ema(closes, 21)
        if trend > 0 and mark <= e21 * 1.003 and r < 45:
            parts.append(("PULL", 1.8))
        elif trend < 0 and mark >= e21 * 0.997 and r > 55:
            parts.append(("PULL", -1.8))

    ml, sl_m, hist = macd(closes)
    if hist > 0 and ml > sl_m:
        parts.append(("MACD", 0.8))
    elif hist < 0 and ml < sl_m:
        parts.append(("MACD", -0.8))

    total = sum(s for _, s in parts)
    aligned = len([p for p in parts if abs(p[1]) >= 0.8])

    if variant.use_mtf and trend != 0:
        if total > 0 and trend < 0:
            return 0.0, 0, ""
        if total < 0 and trend > 0:
            return 0.0, 0, ""

    if abs(total) < variant.min_score or aligned < variant.min_modules:
        return 0.0, 0, ""

    side = "LONG" if total > 0 else "SHORT"
    return total, aligned, side


def _coin_train_stats(
    variant: AdvVariant,
    ltf: list[dict],
    htf: list[dict],
    fee: float,
    train_end_i: int,
) -> dict[str, float]:
    wins = losses = 0
    pnls: list[float] = []
    for i in range(LOOKBACK, min(train_end_i, len(ltf) - 2)):
        score, _al, side = _score_signal(variant, ltf, htf, i)
        if not side:
            continue
        mark = float(ltf[i]["o"])
        a = atr(ltf[i - 30 : i])
        if a <= 0:
            continue
        sl_pct = min(0.04, (a * variant.atr_sl_mult) / mark)
        tp_pct = min(0.12, (a * variant.atr_tp_mult) / mark)
        tp = mark * (1 + tp_pct) if side == "LONG" else mark * (1 - tp_pct)
        sl = mark * (1 - sl_pct) if side == "LONG" else mark * (1 + sl_pct)
        won = False
        for j in range(i + 1, min(i + variant.hold_bars, len(ltf))):
            hi_p, lo_p = float(ltf[j]["h"]), float(ltf[j]["l"])
            if side == "LONG":
                if lo_p <= sl:
                    pnls.append(-sl_pct - fee * 2)
                    losses += 1
                    won = True
                    break
                if hi_p >= tp:
                    pnls.append(tp_pct - fee * 2)
                    wins += 1
                    won = True
                    break
            else:
                if hi_p >= sl:
                    pnls.append(-sl_pct - fee * 2)
                    losses += 1
                    won = True
                    break
                if lo_p <= tp:
                    pnls.append(tp_pct - fee * 2)
                    wins += 1
                    won = True
                    break
        if not won:
            last = float(ltf[min(i + variant.hold_bars - 1, len(ltf) - 1)]["c"])
            raw = (last - mark) / mark if side == "LONG" else (mark - last) / mark
            pnls.append(raw - fee * 2)
            if raw > 0:
                wins += 1
            else:
                losses += 1
    n = wins + losses
    wr = wins / n if n else 0.0
    gains = sum(p for p in pnls if p > 0)
    loss = abs(sum(p for p in pnls if p < 0))
    pf = gains / loss if loss > 1e-12 else (2.0 if gains > 0 else 0.0)
    return {"wr": wr, "pf": pf, "trades": n, "pnl": sum(pnls)}


def _select_coins(
    variant: AdvVariant,
    coin_data: dict[str, tuple[list, list]],
    fee: float,
    days: int,
) -> list[str]:
    """22 coin içinden train döneminde en iyi N — veya sabit liste."""
    if variant.fixed_coins:
        return [c for c in variant.fixed_coins if c in coin_data]
    bars_per_day = 96 if variant.ltf_interval == "15m" else 24
    train_bars = variant.coin_train_days * bars_per_day
    stats: list[tuple[str, float]] = []
    for coin, (ltf, htf) in coin_data.items():
        if len(ltf) < train_bars + LOOKBACK + 80:
            continue
        train_end = LOOKBACK + train_bars
        st = _coin_train_stats(variant, ltf, htf, fee, train_end)
        if st["trades"] < 3:
            score = st["pnl"] * 5.0
        else:
            score = st["pf"] * st["wr"] * 4.0 + st["pnl"] * 40.0 + min(st["trades"], 50) * 0.001
        stats.append((coin, score))
    stats.sort(key=lambda x: x[1], reverse=True)
    n = min(variant.top_coins_n, len(stats))
    return [s[0] for s in stats[: max(n, min(12, len(stats)))]]


def _load_coin_data(
    client: BinanceFuturesClient,
    coin_list: list[str],
    days: int,
) -> dict[str, tuple[list, list]]:
    coin_data: dict[str, tuple[list, list]] = {}
    for coin in coin_list:
        print(f"     {coin} LTF+HTF…")
        ltf = client.klines_history(coin, "15m", days)
        htf = client.klines_history(coin, "1h", days)
        if len(ltf) >= LOOKBACK + 100 and len(htf) >= 60:
            coin_data[coin] = (ltf, htf)
    return coin_data


def run_portfolio_backtest(
    client: BinanceFuturesClient,
    *,
    days: int = 180,
    coins: list[str] | None = None,
    start_balance: float = 5000.0,
    coin_data: dict[str, tuple[list, list]] | None = None,
) -> dict[str, Any]:
    variants = load_advanced_variants()
    coin_list = coins or list(cfg.WATCHLIST)
    fee = cfg.TAKER_FEE_RATE

    if coin_data is None:
        print(f"  📦 {len(coin_list)} coin veri yükleniyor…")
        coin_data = _load_coin_data(client, coin_list, days)
    else:
        print(f"  📦 Önbellekten {len(coin_data)} coin")

    results: list[dict[str, Any]] = []

    for variant in variants:
        allowed = _select_coins(variant, coin_data, fee, days)
        print(f"\n  🧪 {variant.id} — {len(allowed)} coin: {','.join(allowed[:10])}{'…' if len(allowed)>10 else ''}")
        if len(allowed) < 3:
            continue
        sim = _simulate_variant_portfolio(variant, coin_data, allowed, fee, days, start_balance)
        results.append(
            {
                "variant_id": variant.id,
                "label": variant.label,
                "coins_allowed": allowed,
                "start_balance": start_balance,
                "leverage": variant.leverage,
                "max_positions": variant.max_positions,
                **sim,
            }
        )
        print(
            f"     → getiri {sim['total_return_pct']:+.1f}%  WR {sim['win_rate']:.1%}  "
            f"işlem {sim['trades']}  PF {sim['profit_factor']:.2f}  DD {sim['max_drawdown_pct']:.1f}%"
        )

    for r in results:
        dd = max(float(r.get("max_drawdown_pct") or 1), 0.1)
        ret = float(r.get("total_return_pct") or 0)
        eq = float(r.get("end_equity") or 0)
        if eq < 0 or dd > 55:
            r["calmar_score"] = -999.0
        else:
            r["calmar_score"] = round(ret / dd, 3)
    results.sort(key=lambda x: (x.get("calmar_score", -999), x.get("total_return_pct", 0)), reverse=True)
    # %30 hedef: DD<=40 ve getiri max; yoksa en iyi calmar
    viable = [
        r
        for r in results
        if float(r.get("total_return_pct") or 0) >= 25
        and float(r.get("max_drawdown_pct") or 99) <= 40
        and float(r.get("end_equity") or 0) > 0
    ]
    best = viable[0] if viable else (results[0] if results else {})

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "portfolio_backtest_v1",
        "days": days,
        "coins_tested": list(coin_data.keys()),
        "start_balance": start_balance,
        "target_return_pct": 30,
        "ranking": results,
        "best": best,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if best.get("variant_id"):
        save_best_strategy(
            str(best["variant_id"]),
            {
                "variant_id": best["variant_id"],
                "total_return_pct": best.get("total_return_pct"),
                "win_rate": best.get("win_rate"),
                "profit_factor": best.get("profit_factor"),
                "engine": "portfolio",
            },
        )
        log_inference(
            "portfolio_backtest_6m",
            f"En iyi portföy: {best['variant_id']} getiri={best.get('total_return_pct')}%",
            evidence_ids=[str(best["variant_id"])],
        )

    return report


def optimize_per_coin_params(
    variant: AdvVariant,
    coin_data: dict[str, tuple[list, list]],
    fee: float,
) -> dict[str, dict[str, float]]:
    """Her coin için mini grid — train PnL maksimize."""
    bars_per_day = 96
    train_bars = variant.coin_train_days * bars_per_day
    out: dict[str, dict[str, float]] = {}
    tp_opts = [3.5, 5.0, 6.5, 8.0]
    rsi_opts = [(28, 72), (30, 70), (32, 68)]
    for coin, (ltf, htf) in coin_data.items():
        if len(ltf) < train_bars + LOOKBACK + 100:
            continue
        train_end = LOOKBACK + train_bars
        best_pnl = -999.0
        best: dict[str, float] = {}
        for tp_m in tp_opts:
            for rsi_lo, rsi_hi in rsi_opts:
                v = replace(
                    variant,
                    atr_tp_mult=tp_m,
                    rsi_lo=float(rsi_lo),
                    rsi_hi=float(rsi_hi),
                )
                st = _coin_train_stats(v, ltf, htf, fee, train_end)
                if st["pnl"] > best_pnl and st["trades"] >= 3:
                    best_pnl = st["pnl"]
                    best = {
                        "atr_tp_mult": tp_m,
                        "rsi_lo": float(rsi_lo),
                        "rsi_hi": float(rsi_hi),
                        "train_pnl": st["pnl"],
                        "train_wr": st["wr"],
                    }
        if best:
            out[coin] = best
    return out


def run_optimized_portfolio(
    client: BinanceFuturesClient,
    *,
    days: int = 180,
    coins: list[str] | None = None,
    start_balance: float = 5000.0,
    coin_data: dict[str, tuple[list, list]] | None = None,
) -> dict[str, Any]:
    """Per-coin optimize + portföy — 30% hedef için en agresif pipeline."""
    variants = load_advanced_variants()
    base = next((v for v in variants if v.id == "adv_alpha_max"), variants[0] if variants else None)
    if not base:
        return {}
    coin_list = coins or list(cfg.WATCHLIST)
    if coin_data is None:
        coin_data = _load_coin_data(client, coin_list, days)
    fee = cfg.TAKER_FEE_RATE

    print("  🔧 Per-coin parametre optimizasyonu…")
    coin_params = optimize_per_coin_params(base, coin_data, fee)
    allowed = sorted(
        coin_params.keys(),
        key=lambda c: coin_params[c].get("train_pnl", 0),
        reverse=True,
    )[: base.top_coins_n]
    print(f"     {len(allowed)} coin optimize edildi")

    # Agresif portföy ayarları
    agg = replace(
        base,
        id="adv_per_coin_optimized",
        label="Per-coin optimize + Alpha Max",
        risk_pct=0.045,
        leverage=10.0,
        max_positions=12,
        top_coins_n=len(allowed),
    )

    # Simülasyon: coin başına özel rsi/tp
    bars_per_day = 96
    test_start = LOOKBACK + agg.coin_train_days * bars_per_day
    equity = start_balance
    peak = equity
    max_dd = 0.0
    open_trades: list[PendingTrade] = []
    wins = losses = 0
    trade_log: list[float] = []
    min_len = min(len(coin_data[c][0]) for c in allowed) if allowed else 0

    for i in range(test_start, min_len - 2):
        still_open: list[PendingTrade] = []
        for tr in open_trades:
            ltf = coin_data[tr.coin][0]
            if i <= tr.entry_i:
                still_open.append(tr)
                continue
            closed, exit_pnl_pct = _close_trade(
                tr, agg, ltf, i, float(ltf[i]["h"]), float(ltf[i]["l"])
            )
            if closed:
                lev_pnl = exit_pnl_pct * agg.leverage - fee * 2 * agg.leverage
                equity += tr.size_usd * lev_pnl
                trade_log.append(lev_pnl)
                wins += int(lev_pnl > 0)
                losses += int(lev_pnl <= 0)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak if peak else 0)
            else:
                still_open.append(tr)
        open_trades = still_open
        if len(open_trades) >= agg.max_positions:
            continue

        # BTC rejim filtresi
        if "BTC" in coin_data:
            btc_ltf, btc_htf = coin_data["BTC"]
            if i < len(btc_ltf):
                _sc, _al, _sd = _score_signal(agg, btc_ltf, btc_htf, i)
                btc_trend = 1 if _sc > 0.5 else (-1 if _sc < -0.5 else 0)
            else:
                btc_trend = 0
        else:
            btc_trend = 0

        for coin in allowed:
            if any(t.coin == coin for t in open_trades):
                continue
            cp = coin_params.get(coin, {})
            v = replace(
                agg,
                atr_tp_mult=float(cp.get("atr_tp_mult", agg.atr_tp_mult)),
                rsi_lo=float(cp.get("rsi_lo", agg.rsi_lo)),
                rsi_hi=float(cp.get("rsi_hi", agg.rsi_hi)),
            )
            ltf, htf = coin_data[coin]
            score, _al, side = _score_signal(v, ltf, htf, i)
            if not side:
                continue
            if btc_trend != 0:
                if side == "LONG" and btc_trend < 0:
                    continue
                if side == "SHORT" and btc_trend > 0:
                    continue
            mark = float(ltf[i]["o"])
            a = atr(ltf[i - 30 : i])
            if a <= 0:
                continue
            sl_pct = min(0.055, (a * v.atr_sl_mult) / mark)
            tp_pct = min(0.22, (a * v.atr_tp_mult) / mark)
            risk_base = min(equity, start_balance * 2.5)
            risk_usd = risk_base * v.risk_pct
            size_usd = min(risk_usd / sl_pct, equity * 0.12) if sl_pct > 0 else 0
            if size_usd < 15:
                continue
            open_trades.append(
                PendingTrade(
                    coin=coin,
                    side=side,
                    entry_i=i,
                    entry_t=int(ltf[i]["t"]),
                    entry_px=mark,
                    sl_px=mark * (1 - sl_pct) if side == "LONG" else mark * (1 + sl_pct),
                    tp_px=mark * (1 + tp_pct) if side == "LONG" else mark * (1 - tp_pct),
                    size_usd=size_usd,
                    peak_px=mark,
                    use_trailing=v.use_trailing,
                )
            )
            if len(open_trades) >= agg.max_positions:
                break

    n = wins + losses
    ret = (equity - start_balance) / start_balance * 100
    gains = sum(p for p in trade_log if p > 0)
    loss = abs(sum(p for p in trade_log if p < 0))
    result = {
        "variant_id": "adv_per_coin_optimized",
        "label": agg.label,
        "coins_allowed": allowed,
        "coin_params": coin_params,
        "start_balance": start_balance,
        "end_equity": round(equity, 2),
        "total_return_pct": round(ret, 2),
        "win_rate": round(wins / n, 4) if n else 0,
        "trades": n,
        "profit_factor": round(gains / loss, 3) if loss > 1e-12 else 0,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "leverage": agg.leverage,
    }
    path = cfg.ROOT / "data" / "education" / "portfolio_optimized_6m.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    log_inference(
        "portfolio_per_coin_optimized",
        f"getiri={ret:.1f}% WR={result['win_rate']} coin={len(allowed)}",
        evidence_ids=["adv_per_coin_optimized"],
    )
    return result


def run_param_grid(
    client: BinanceFuturesClient,
    base_variant_id: str = "adv_mtf_bb_rsi_atr",
    *,
    days: int = 180,
    coins: list[str] | None = None,
    start_balance: float = 5000.0,
    coin_data: dict[str, tuple[list, list]] | None = None,
) -> dict[str, Any]:
    """En iyi portföy varyantı üzerinde parametre taraması."""
    variants = {v.id: v for v in load_advanced_variants()}
    base = variants.get(base_variant_id)
    if not base:
        return {}

    grid: list[dict[str, float]] = []
    for risk in (0.025, 0.035, 0.045):
        for lev in (4.0, 6.0, 8.0):
            for tp_m in (4.0, 5.5, 7.0):
                grid.append({"risk_pct": risk, "leverage": lev, "atr_tp_mult": tp_m})

    coin_list = coins or list(cfg.WATCHLIST)
    if coin_data is None:
        coin_data = _load_coin_data(client, coin_list, days)

    fee = cfg.TAKER_FEE_RATE
    grid_results: list[dict[str, Any]] = []

    for params in grid:
        v = replace(
            base,
            risk_pct=params["risk_pct"],
            leverage=params["leverage"],
            atr_tp_mult=params["atr_tp_mult"],
        )
        allowed = _select_coins(v, coin_data, fee, days)
        if len(allowed) < 3:
            continue
        # Hızlı portföy sim (aynı mantık, kısaltılmış)
        rep = _simulate_variant_portfolio(v, coin_data, allowed, fee, days, start_balance)
        rep["params"] = params
        grid_results.append(rep)

    grid_results.sort(key=lambda x: x.get("total_return_pct", 0), reverse=True)
    out = {
        "base_variant": base_variant_id,
        "grid_size": len(grid_results),
        "best": grid_results[0] if grid_results else {},
        "top5": grid_results[:5],
    }
    path = cfg.ROOT / "data" / "education" / "portfolio_grid_search.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def _simulate_variant_portfolio(
    variant: AdvVariant,
    coin_data: dict[str, tuple[list, list]],
    allowed: list[str],
    fee: float,
    days: int,
    start_balance: float,
) -> dict[str, Any]:
    bars_per_day = 96
    test_start_bar = LOOKBACK + variant.coin_train_days * bars_per_day
    equity = start_balance
    peak = equity
    max_dd = 0.0
    open_trades: list[PendingTrade] = []
    wins = losses = 0
    trade_log: list[float] = []
    equity_floor = start_balance * 0.35
    ruined = False

    min_len = min(len(coin_data[c][0]) for c in allowed)
    for i in range(test_start_bar, min_len - 2):
        if ruined or equity <= equity_floor:
            ruined = True
            break
        still_open: list[PendingTrade] = []
        for tr in open_trades:
            ltf = coin_data[tr.coin][0]
            if i <= tr.entry_i:
                still_open.append(tr)
                continue
            hi_p, lo_p = float(ltf[i]["h"]), float(ltf[i]["l"])
            closed, exit_pnl_pct = _close_trade(tr, variant, ltf, i, hi_p, lo_p)
            if closed:
                lev_pnl = exit_pnl_pct * variant.leverage - fee * 2 * variant.leverage
                usd_pnl = tr.size_usd * lev_pnl
                equity = max(0.0, equity + usd_pnl)
                trade_log.append(lev_pnl)
                wins += int(usd_pnl > 0)
                losses += int(usd_pnl <= 0)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak if peak else 0)
                if equity <= equity_floor:
                    ruined = True
            else:
                still_open.append(tr)
        open_trades = still_open
        if ruined or len(open_trades) >= variant.max_positions:
            continue
        risk_equity = min(equity, start_balance * 1.5)
        max_stake = min(equity * 0.12, start_balance * 0.14)
        for coin in allowed:
            if any(t.coin == coin for t in open_trades):
                continue
            ltf, htf = coin_data[coin]
            _score, _al, side = _score_signal(variant, ltf, htf, i)
            if not side:
                continue
            mark = float(ltf[i]["o"])
            a = atr(ltf[i - 30 : i])
            if a <= 0:
                continue
            sl_pct = min(0.05, (a * variant.atr_sl_mult) / mark)
            tp_pct = min(0.18, (a * variant.atr_tp_mult) / mark)
            risk_usd = risk_equity * variant.risk_pct
            size_usd = min(risk_usd / sl_pct, max_stake) if sl_pct > 0 else 0
            if size_usd < 15:
                continue
            open_trades.append(
                PendingTrade(
                    coin=coin,
                    side=side,
                    entry_i=i,
                    entry_t=int(ltf[i]["t"]),
                    entry_px=mark,
                    sl_px=mark * (1 - sl_pct) if side == "LONG" else mark * (1 + sl_pct),
                    tp_px=mark * (1 + tp_pct) if side == "LONG" else mark * (1 - tp_pct),
                    size_usd=size_usd,
                    peak_px=mark,
                    use_trailing=variant.use_trailing,
                )
            )
            if len(open_trades) >= variant.max_positions:
                break

    n = wins + losses
    equity = max(0.0, equity)
    ret = (equity - start_balance) / start_balance * 100
    gains = sum(p for p in trade_log if p > 0)
    loss = abs(sum(p for p in trade_log if p < 0))
    return {
        "total_return_pct": round(ret, 2),
        "win_rate": round(wins / n, 4) if n else 0,
        "trades": n,
        "profit_factor": round(gains / loss, 3) if loss > 1e-12 else 0,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "end_equity": round(equity, 2),
    }


def _close_trade(
    tr: PendingTrade,
    variant: AdvVariant,
    ltf: list[dict],
    i: int,
    hi_p: float,
    lo_p: float,
) -> tuple[bool, float]:
    closed = False
    exit_pnl_pct = 0.0
    if tr.side == "LONG":
        if tr.use_trailing:
            if hi_p > tr.peak_px:
                tr.peak_px = hi_p
            gain = (tr.peak_px - tr.entry_px) / tr.entry_px
            if gain >= variant.trail_activate_pct:
                tr.trail_active = True
            if tr.trail_active:
                tsl = tr.peak_px * (1 - variant.trail_distance_pct)
                if lo_p <= tsl:
                    exit_pnl_pct = (tsl - tr.entry_px) / tr.entry_px
                    return True, exit_pnl_pct
        if lo_p <= tr.sl_px:
            return True, (tr.sl_px - tr.entry_px) / tr.entry_px
        if hi_p >= tr.tp_px:
            return True, (tr.tp_px - tr.entry_px) / tr.entry_px
    else:
        if tr.use_trailing:
            if tr.peak_px == 0 or lo_p < tr.peak_px:
                tr.peak_px = lo_p
            gain = (tr.entry_px - tr.peak_px) / tr.entry_px
            if gain >= variant.trail_activate_pct:
                tr.trail_active = True
            if tr.trail_active:
                tsl = tr.peak_px * (1 + variant.trail_distance_pct)
                if hi_p >= tsl:
                    exit_pnl_pct = (tr.entry_px - tsl) / tr.entry_px
                    return True, exit_pnl_pct
        if hi_p >= tr.sl_px:
            return True, (tr.entry_px - tr.sl_px) / tr.entry_px
        if lo_p <= tr.tp_px:
            return True, (tr.entry_px - tr.tp_px) / tr.entry_px
    if i >= tr.entry_i + variant.hold_bars:
        last = float(ltf[i]["c"])
        raw = (
            (last - tr.entry_px) / tr.entry_px
            if tr.side == "LONG"
            else (tr.entry_px - last) / tr.entry_px
        )
        return True, raw
    return closed, exit_pnl_pct
