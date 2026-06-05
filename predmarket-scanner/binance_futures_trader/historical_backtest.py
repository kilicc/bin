"""6 aylık geçmiş veri backtest — eğitimden türetilmiş strateji varyasyonları."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.education_memory import (
    load_variants,
    log_inference,
    save_best_strategy,
)
from binance_futures_trader.ta_indicators import (
    adx,
    atr,
    bollinger,
    ema,
    macd,
    rsi,
    stochastic,
)

LOOKBACK_DEFAULT = 40
REPORT_PATH = cfg.ROOT / "data" / "education" / "backtest_6m_report.json"
BASELINE_REPORT_PATH = cfg.ROOT / "data" / "education" / "backtest_6m_report_baseline.json"
COMPARISON_PATH = cfg.ROOT / "data" / "education" / "backtest_improvement.json"


@dataclass
class StrategyVariant:
    id: str
    label: str
    min_score: float
    min_modules_aligned: int
    tp_pct: float
    sl_pct: float
    hold_bars: int
    rsi_period: int = 14
    rsi_lo: float = 35
    rsi_hi: float = 65
    ema_fast: int = 9
    ema_slow: int = 21
    bb_std: float = 2.0
    bb_period: int = 20
    use_macd: bool = False
    use_vol: bool = False
    use_fg: bool = False
    fg_fear: int = 25
    fg_greed: int = 75
    mom_thresh: float = 0.0035
    modules: list[str] = field(default_factory=list)
    education_basis: list[str] = field(default_factory=list)
    lookback_bars: int = LOOKBACK_DEFAULT
    ema_mid: int = 21
    ema_slow: int = 50
    use_adx_filter: bool = False
    adx_min: float = 22.0
    adx_max: float = 60.0
    use_ema200_filter: bool = False
    use_triple_ema: bool = False
    use_stoch: bool = False
    stoch_lo: float = 22.0
    stoch_hi: float = 78.0
    use_atr_exits: bool = False
    atr_sl_mult: float = 1.5
    atr_tp_mult: float = 2.5

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategyVariant:
        return cls(
            id=str(d["id"]),
            label=str(d.get("label") or d["id"]),
            min_score=float(d.get("min_score", 2.0)),
            min_modules_aligned=int(d.get("min_modules_aligned", 2)),
            tp_pct=float(d.get("tp_pct", 0.015)),
            sl_pct=float(d.get("sl_pct", 0.012)),
            hold_bars=int(d.get("hold_bars", 16)),
            rsi_period=int(d.get("rsi_period", 14)),
            rsi_lo=float(d.get("rsi_lo", 35)),
            rsi_hi=float(d.get("rsi_hi", 65)),
            ema_fast=int(d.get("ema_fast", 9)),
            bb_std=float(d.get("bb_std", 2.0)),
            bb_period=int(d.get("bb_period", 20)),
            use_macd=bool(d.get("use_macd")),
            use_vol=bool(d.get("use_vol")),
            use_fg=bool(d.get("use_fg")),
            fg_fear=int(d.get("fg_fear", 25)),
            fg_greed=int(d.get("fg_greed", 75)),
            mom_thresh=float(d.get("mom_thresh", 0.0035)),
            modules=list(d.get("modules") or []),
            education_basis=list(d.get("education_basis") or []),
            lookback_bars=int(d.get("lookback_bars", LOOKBACK_DEFAULT)),
            ema_mid=int(d.get("ema_mid", 21)),
            ema_slow=int(d.get("ema_slow", 50)),
            use_adx_filter=bool(d.get("use_adx_filter")),
            adx_min=float(d.get("adx_min", 22)),
            adx_max=float(d.get("adx_max", 60)),
            use_ema200_filter=bool(d.get("use_ema200_filter")),
            use_triple_ema=bool(d.get("use_triple_ema")),
            use_stoch=bool(d.get("use_stoch")),
            stoch_lo=float(d.get("stoch_lo", 22)),
            stoch_hi=float(d.get("stoch_hi", 78)),
            use_atr_exits=bool(d.get("use_atr_exits")),
            atr_sl_mult=float(d.get("atr_sl_mult", 1.5)),
            atr_tp_mult=float(d.get("atr_tp_mult", 2.5)),
        )


def load_strategy_variants() -> list[StrategyVariant]:
    return [StrategyVariant.from_dict(v) for v in load_variants()]


def _passes_regime_filters(
    variant: StrategyVariant,
    closes: list[float],
    candles: list[dict],
) -> bool:
    if variant.use_adx_filter and candles:
        ax = adx(candles[-30:] if len(candles) >= 30 else candles)
        if ax < variant.adx_min or ax > variant.adx_max:
            return False
    if variant.use_ema200_filter and len(closes) >= 50:
        e200 = ema(closes[-min(len(closes), 220) :], min(200, len(closes) - 1))
        if e200 <= 0:
            return False
        # rejim filtresi skor yönünde uygulanır; burada sadece aşırı karşıtı ele
    if variant.use_triple_ema and len(closes) >= variant.ema_slow + 5:
        e1 = ema(closes, variant.ema_fast)
        e2 = ema(closes, variant.ema_mid)
        e3 = ema(closes, variant.ema_slow)
        if not (e1 > e2 > e3 or e1 < e2 < e3):
            return False
    return True


def _score_bar(
    variant: StrategyVariant,
    closes: list[float],
    vols: list[float],
    mark: float,
    candles: list[dict],
    *,
    fg_value: int = 50,
) -> tuple[float, int, list[str]]:
    """Toplam skor, hizalı modül sayısı, aktif modül isimleri."""
    if not _passes_regime_filters(variant, closes, candles):
        return 0.0, 0, []

    parts: list[tuple[str, float]] = []
    r = rsi(closes, variant.rsi_period)
    if r < variant.rsi_lo:
        parts.append(("RSI", 2.0))
    elif r > variant.rsi_hi:
        parts.append(("RSI", -2.0))

    ef = ema(closes[-max(variant.ema_slow + 5, 24) :], variant.ema_fast)
    es = ema(closes[-max(variant.ema_slow + 5, 24) :], variant.ema_slow)
    if ef > es * 1.0005:
        parts.append(("EMA", 1.5))
    elif ef < es * 0.9995:
        parts.append(("EMA", -1.5))

    lower, mid, upper = bollinger(closes, variant.bb_period, variant.bb_std)
    if mark <= lower:
        parts.append(("BB", 1.5))
    elif mark >= upper:
        parts.append(("BB", -1.5))

    if variant.use_macd and len(closes) >= 35:
        ml, sl, hist = macd(closes)
        if hist > 0 and ml > sl:
            parts.append(("MACD", 1.4))
        elif hist < 0 and ml < sl:
            parts.append(("MACD", -1.4))

    if len(closes) >= 3:
        mom3 = (closes[-1] - closes[-3]) / closes[-3]
        if mom3 > variant.mom_thresh:
            parts.append(("MOM3", 1.0))
        elif mom3 < -variant.mom_thresh:
            parts.append(("MOM3", -1.0))

    if variant.use_vol and len(vols) >= 12:
        avg_v = sum(vols[-12:-1]) / max(1, len(vols[-12:-1]))
        if avg_v > 0 and vols[-1] > avg_v * 1.5:
            direction = 1 if closes[-1] > closes[-2] else -1
            parts.append(("VOL", 0.8 * direction))

    if variant.use_fg:
        if fg_value <= variant.fg_fear:
            parts.append(("FG", 0.6))
        elif fg_value >= variant.fg_greed:
            parts.append(("FG", -0.6))

    if variant.use_stoch:
        k, d = stochastic(closes)
        if k < variant.stoch_lo and d < variant.stoch_lo:
            parts.append(("STOCH", 1.3))
        elif k > variant.stoch_hi and d > variant.stoch_hi:
            parts.append(("STOCH", -1.3))

    if variant.use_adx_filter and candles:
        ax = adx(candles[-30:] if len(candles) >= 30 else candles)
        if ax >= variant.adx_min:
            trend_up = parts and sum(s for _, s in parts) > 0
            parts.append(("ADX", 0.5 if trend_up else -0.5))

    if variant.use_ema200_filter and len(closes) >= 50:
        e200 = ema(closes[-min(len(closes), 220) :], min(200, len(closes) - 1))
        if mark > e200:
            parts.append(("EMA200", 0.7))
        elif mark < e200:
            parts.append(("EMA200", -0.7))

    total = sum(s for _, s in parts)

    # EMA200 rejim: long sadece üstte, short sadece altta
    if variant.use_ema200_filter and len(closes) >= 50:
        e200 = ema(closes[-min(len(closes), 220) :], min(200, len(closes) - 1))
        if total > 0 and mark < e200:
            return 0.0, 0, []
        if total < 0 and mark > e200:
            return 0.0, 0, []
    aligned = sum(
        1
        for name, s in parts
        if name in variant.modules and abs(s) >= 0.5
    )
    active = [n for n, _ in parts]
    return total, aligned, active


def simulate_variant_on_candles(
    variant: StrategyVariant,
    candles: list[dict],
    *,
    fee_rate: float | None = None,
    fg_value: int = 50,
) -> dict[str, Any]:
    fee = fee_rate if fee_rate is not None else cfg.TAKER_FEE_RATE
    wins = losses = 0
    pnls: list[float] = []
    trades = 0
    lb = max(LOOKBACK_DEFAULT, variant.lookback_bars)

    for i in range(lb, len(candles) - 2):
        window = candles[i - lb : i]
        closes = [float(c["c"]) for c in window]
        vols = [float(c.get("v") or 0) for c in window]
        if len(closes) < 25:
            continue
        mark = float(candles[i]["o"])
        score, aligned, _active = _score_bar(
            variant, closes, vols, mark, window, fg_value=fg_value
        )
        if abs(score) < variant.min_score:
            continue
        if aligned < variant.min_modules_aligned:
            continue
        side = "LONG" if score > 0 else "SHORT"
        sl_pct = variant.sl_pct
        tp_pct = variant.tp_pct
        if variant.use_atr_exits:
            a = atr(window)
            if a > 0 and mark > 0:
                sl_pct = min(0.05, (a * variant.atr_sl_mult) / mark)
                tp_pct = min(0.08, (a * variant.atr_tp_mult) / mark)
        tp = mark * (1 + tp_pct) if side == "LONG" else mark * (1 - tp_pct)
        sl = mark * (1 - sl_pct) if side == "LONG" else mark * (1 + sl_pct)
        hold = variant.hold_bars
        exit_pnl: float | None = None
        for j in range(i + 1, min(i + hold + 1, len(candles))):
            hi, lo = float(candles[j]["h"]), float(candles[j]["l"])
            if side == "LONG":
                if lo <= sl:
                    exit_pnl = -sl_pct
                    losses += 1
                    break
                if hi >= tp:
                    exit_pnl = tp_pct
                    wins += 1
                    break
            else:
                if hi >= sl:
                    exit_pnl = -sl_pct
                    losses += 1
                    break
                if lo <= tp:
                    exit_pnl = tp_pct
                    wins += 1
                    break
        if exit_pnl is None:
            last = float(candles[min(i + hold, len(candles) - 1)]["c"])
            raw = (last - mark) / mark if side == "LONG" else (mark - last) / mark
            exit_pnl = raw
            if raw > 0:
                wins += 1
            else:
                losses += 1
        round_trip_fee = fee * 2
        net = exit_pnl - round_trip_fee
        pnls.append(net)
        trades += 1

    n = wins + losses
    total_pnl = sum(pnls)
    return {
        "wins": wins,
        "losses": losses,
        "trades": trades,
        "win_rate": wins / n if n else 0.0,
        "avg_pnl_pct": total_pnl / len(pnls) if pnls else 0.0,
        "total_pnl_pct": total_pnl,
        "profit_factor": _profit_factor(pnls),
        "max_drawdown_pct": _max_drawdown(pnls),
    }


def _profit_factor(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    if losses < 1e-12:
        return gains if gains > 0 else 0.0
    return round(gains / losses, 3)


def _max_drawdown(pnls: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return round(max_dd, 4)


def run_6m_backtest(
    client: BinanceFuturesClient,
    *,
    days: int = 180,
    interval: str = "15m",
    coins: list[str] | None = None,
) -> dict[str, Any]:
    """Tüm eğitim varyasyonlarını watchlist üzerinde test et."""
    from binance_futures_trader.signals import fear_greed

    variants = load_strategy_variants()
    max_lb = max((v.lookback_bars for v in variants), default=LOOKBACK_DEFAULT)
    coin_list = coins or list(cfg.WATCHLIST[:8])  # API yükü: ilk 8 coin
    fg = fear_greed()

    aggregate: dict[str, dict[str, Any]] = {
        v.id: {
            "label": v.label,
            "education_basis": v.education_basis,
            "coins": {},
            "wins": 0,
            "losses": 0,
            "trades": 0,
            "total_pnl_pct": 0.0,
            "pnls": [],
        }
        for v in variants
    }

    for coin in coin_list:
        print(f"  📥 {coin} {interval} {days}g…")
        candles = client.klines_history(coin, interval, days)
        if len(candles) < max_lb + 50:
            print(f"     ⚠ yetersiz veri ({len(candles)} mum)")
            continue
        for variant in variants:
            res = simulate_variant_on_candles(variant, candles, fg_value=fg)
            agg = aggregate[variant.id]
            agg["coins"][coin] = res
            agg["wins"] += res["wins"]
            agg["losses"] += res["losses"]
            agg["trades"] += res["trades"]
            agg["total_pnl_pct"] += res["total_pnl_pct"]
            agg["pnls"].extend(
                [res["avg_pnl_pct"]] * max(1, res["trades"])
            )

    ranking: list[dict[str, Any]] = []
    for vid, agg in aggregate.items():
        n = agg["wins"] + agg["losses"]
        wr = agg["wins"] / n if n else 0.0
        pf = _profit_factor(agg["pnls"])
        dd = _max_drawdown(agg["pnls"])
        score = _rank_score(wr, pf, agg["total_pnl_pct"], dd, agg["trades"])
        ranking.append(
            {
                "variant_id": vid,
                "label": agg["label"],
                "education_basis": agg["education_basis"],
                "win_rate": round(wr, 4),
                "trades": agg["trades"],
                "total_pnl_pct": round(agg["total_pnl_pct"], 4),
                "profit_factor": pf,
                "max_drawdown_pct": dd,
                "rank_score": round(score, 4),
                "per_coin": agg["coins"],
            }
        )

    ranking.sort(key=lambda x: x["rank_score"], reverse=True)
    best = ranking[0] if ranking else {}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "knowledge_version": 2,
        "includes_github_strategies": True,
        "days": days,
        "interval": interval,
        "coins_tested": coin_list,
        "fee_rate": cfg.TAKER_FEE_RATE,
        "fg_at_test": fg,
        "ranking": ranking,
        "best_variant_id": best.get("variant_id"),
        "best_summary": {
            k: best.get(k)
            for k in (
                "variant_id",
                "label",
                "win_rate",
                "trades",
                "total_pnl_pct",
                "profit_factor",
                "max_drawdown_pct",
                "rank_score",
            )
        },
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _save_improvement_vs_baseline(report)

    if best.get("variant_id"):
        save_best_strategy(str(best["variant_id"]), report["best_summary"])
        log_inference(
            "backtest_6m_complete",
            f"En iyi: {best['variant_id']} WR={best.get('win_rate')} PF={best.get('profit_factor')}",
            evidence_ids=[str(best["variant_id"])],
        )

    return report


def _rank_score(
    wr: float,
    pf: float,
    total_pnl: float,
    max_dd: float,
    trades: int,
) -> float:
    """WR odaklı sıralama (kullanıcı geri bildirimi) + PF ve PnL."""
    if trades < 20:
        sample_penalty = trades / 20.0
    else:
        sample_penalty = 1.0
    dd_penalty = max(0.0, 1.0 - max_dd * 4)
    wr_bonus = 0.1 if wr >= 0.52 else 0.0
    return sample_penalty * (
        wr * 0.50 + wr_bonus + min(pf, 3.0) * 0.20 + total_pnl * 1.5 + dd_penalty * 0.15
    )


def _save_improvement_vs_baseline(current: dict[str, Any]) -> None:
    if not BASELINE_REPORT_PATH.is_file():
        return
    try:
        baseline = json.loads(BASELINE_REPORT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    b_best = (baseline.get("best_summary") or {})
    c_best = current.get("best_summary") or {}
    improved = False
    deltas: dict[str, Any] = {}
    for key in ("win_rate", "profit_factor", "total_pnl_pct", "rank_score"):
        bv, cv = b_best.get(key), c_best.get(key)
        if bv is None or cv is None:
            continue
        deltas[key] = round(float(cv) - float(bv), 4)
        if key == "win_rate" and cv > bv:
            improved = True
        if key == "total_pnl_pct" and cv > bv:
            improved = True
        if key == "profit_factor" and cv > bv:
            improved = True
    payload = {
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "baseline_best": b_best.get("variant_id"),
        "current_best": c_best.get("variant_id"),
        "improved": improved,
        "deltas": deltas,
        "baseline_summary": b_best,
        "current_summary": c_best,
    }
    COMPARISON_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if improved:
        log_inference(
            "backtest_improvement_after_github",
            f"Gelişim: {deltas} | yeni en iyi: {c_best.get('variant_id')}",
            evidence_ids=[str(c_best.get("variant_id"))],
        )


def variant_to_env_patch(variant_id: str) -> dict[str, str]:
    """Seçilen varyantı demo env anahtarlarına map et (uygulama öncesi yedek gerekir)."""
    variants = {v.id: v for v in load_strategy_variants()}
    v = variants.get(variant_id)
    if not v:
        return {}
    patch: dict[str, str] = {
        "BN_FUT_TP_PCT": str(v.tp_pct),
        "BN_FUT_SL_PCT": str(v.sl_pct),
        "BN_FUT_MIN_SCORE": str(v.min_score),
        "BN_FUT_SCALP_BT_HOLD_BARS": str(v.hold_bars),
        "BN_FUT_MIN_SIGNAL_PARTS": str(v.min_modules_aligned),
    }
    if "scalp" in v.id:
        patch["BN_FUT_STRATEGY_PROFILE"] = "scalp"
        patch["BN_FUT_SCALP_MOM_THRESH"] = str(v.mom_thresh)
        patch["BN_FUT_CANDLE_INTERVAL"] = "5m"
    else:
        patch["BN_FUT_STRATEGY_PROFILE"] = "standard"
        patch["BN_FUT_CANDLE_INTERVAL"] = "15m"
    if v.use_macd:
        patch["BN_FUT_EDU_MACD"] = "1"
    else:
        patch["BN_FUT_EDU_MACD"] = "0"
    patch["BN_FUT_EDU_MEMORY"] = "1"
    patch["BN_FUT_EDU_STRATEGY_ID"] = variant_id
    if getattr(v, "use_adx_filter", False):
        patch["BN_FUT_EDU_ADX_FILTER"] = "1"
        patch["BN_FUT_EDU_ADX_MIN"] = str(getattr(v, "adx_min", 22))
    if getattr(v, "use_atr_exits", False):
        patch["BN_FUT_EDU_ATR_EXITS"] = "1"
        patch["BN_FUT_SL_ATR_MULT"] = str(getattr(v, "atr_sl_mult", 1.5))
    if getattr(v, "use_ema200_filter", False):
        patch["BN_FUT_EDU_EMA200_FILTER"] = "1"
    return patch
