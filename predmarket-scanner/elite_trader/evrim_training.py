"""Evrim canlı eğitim modu — karar logu + prompt ile rehber güncelleme."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.evrim_opportunity import LEARNING_GUIDE, MODE_ID, _GUIDE_PATH
from elite_trader.mode_profiles import get_profile, save_profile

_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "evrim_training_state.json"
_BT_PATH = _ROOT / "data" / "evrim_mtf_backtest.json"

MTF_TRAINING_PROMPT = """
Çoklu zaman dilimli indikatör motoru — yalnızca hybrid trade skoruna katkı; tek başına emir açmaz.

EMA: 9, 21, 50, 200 | RSI: 7, 14 | MACD: histogram yönü, momentum değişimi
ATR: 14, expansion | Bollinger: squeeze, expansion, breakout
VWAP: üstü long bias, altı short bias | ADX: trend gücü

Kurallar: Trend alignment → skor artır. RSI aşırı → ters yönde risk azalt.
ATR düşük → stake düşür. ADX düşük → chop modu.
TF: 5m, 15m, 1h.
""".strip()

PRICE_ACTION_TRAINING_PROMPT = """
Price action analiz modülü — yalnızca hybrid skor katkısı; tek başına emir açmaz.

Yapılar: breakout, fake breakout, liquidity grab, stop hunt, wick rejection,
momentum candle, engulfing, range breakout, micro HH/HL, micro LL/LH,
body expansion, consecutive candle pressure.

Long: higher high, bullish expansion, volume destekli breakout,
üst fitil zayıf güçlü kapanış.
Short: lower low, bearish expansion, volume breakdown,
alt fitil zayıf güçlü kapanış.

Fake breakout ihtimali yüksekse veto veya stake azalt; asla tek başına giriş açma.
""".strip()

VOLUME_ORDERBOOK_TRAINING_PROMPT = """
Volume ve orderbook analiz motoru — yalnızca hybrid skor katkısı; tek başına emir açmaz.

Takip: volume spike, relative volume, buy/sell imbalance, bid/ask wall,
liquidity pull, orderbook sweep, büyük emir giriş/iptal, aggressive market buy/sell.
Whale/news API placeholder (sonra entegre).

Kurallar: rel_vol >= 1.2 skor artır; >= 1.8 agresif mod.
OB long baskın → long skor; short baskın → short skor.
Spread genişse işlem açma. Slippage yüksekse stake düşür.
""".strip()

MARKET_REGIME_TRAINING_PROMPT = """
Piyasa rejimi motoru — 8 rejim; yalnızca hybrid skor ve parametre katkısı; tek başına emir açmaz.

Rejimler: trending, breakout, chop, high_volatility, low_volatility,
liquidation_cascade, news_shock, fake_pump_dump.

Trending: trend yönünde işlem, TP büyüt, trailing aktif.
Breakout: hızlı giriş, partial TP, re-entry açık.
Chop: işlem azalt, stake düşür, TP küçült, filtre sıkı.
Low volatility: işlem açma veya minimum stake.
High volatility: stake kontrollü, SL genişlet, slippage kontrolü artır.
News shock: spread genişse işlem açma, volatilite oturana kadar bekle.
""".strip()

DYNAMIC_EXIT_TRAINING_PROMPT = """
Dinamik TP/SL — skor ve piyasa koşuluna göre; sabit profil TP/SL yerine giriş anı hesaplanır.

Girdiler: ATR, momentum gücü (change/strength), volume spike, spread, fee, slippage,
market regime, hybrid skor (65-75 / 75-85 / 85+).

Skor bantları (yüzde puan, stake hedefi):
65-75: TP 0.25-0.40, SL 0.15-0.25
75-85: TP 0.40-0.75, SL 0.20-0.35
85+: TP 0.75-1.50, SL 0.30-0.55

Trailing: kâra geçince SL break-even üstüne taşınır.
Momentum devam → tut; momentum zayıflarsa çık (MOMENTUM-FADE).
Partial TP: pozisyonun %50'si ilk TP seviyesinde kapanır; kalan trailing ile sürer.

Fee tabanı: TP her zaman round-trip ücreti aşmalı. Spread/slippage yüksekse hedef küçült.
Rejim: trending TP genişlet; chop/high_vol SL genişlet; news_shock bekle.
""".strip()

EXPECTANCY_TRAINING_PROMPT = """
Net expectancy — her işlem öncesi hesapla; negatifse açma.

expected_net_pnl =
  expected_gross_move - entry_fee - exit_fee - spread_cost - slippage_cost - funding_cost

expected_gross_move: dinamik TP hedefi (stake × tp_stake_pct × trigger).
Ücretler: giriş + çıkış taker/maker oranı. Spread ve slippage orderbook proxy.

Sürekli metrikler: Fee/Gross Profit %, Gross/Fee, Net PnL/trade, avg slippage,
avg spread, maker/taker oranı, profit factor, win rate, avg win/loss, expectancy.

Kurallar:
- Fee/Gross Profit > %45 → agresiflik azalt (stake ×0.85).
- Fee/Gross Profit > %70 → işlem hızı düşür (min skor +2, stake ×0.7).
- Fees >= Gross Profit → acil koruma (giriş blok / stake ×0.45).
""".strip()

TRADE_LEARNING_TRAINING_PROMPT = """
İşlem sonrası öğrenme — her trade için journal kaydı; her 50 işlemde analiz.

Kayıt alanları: symbol, direction, entry/exit reason, score breakdown, market regime,
indicators, volume, orderbook, entry/exit price, fee, slippage, net PnL, hold time, MFE, MAE,
trade quality score.

50 işlem analizi: kazandıran/kaybettiren sinyaller, verimli coinler, kötü saatler,
zararlı rejimler, TP/SL oranı, edge threshold.

Parametre sınırları (dışına çıkma):
min_edge 0.06-0.45 | min_skor 48-75 | TP %0.18-1.50 | SL %0.12-0.60
max_open 3-20 | aktif_sermaye %20-95

Güncelleme: önce profil backup; yeni ayar yalnızca backtest onayından sonra canlıya.
""".strip()

PARAM_AUTO_TEST_TRAINING_PROMPT = """
Otomatik parametre testi — her değişimde:

1. Mevcut ayarları backup al
2. Yeni ayarları simülasyonda test et
3. Son 500 işlem journal verisiyle baseline karşılaştır
4. Kline backtest + son 30 dakika forward test
5. Eski vs yeni metrik karşılaştırması

Metrikler: Net PnL, max drawdown, fee ratio, profit factor, avg win/loss,
trade count, PnL velocity, consecutive loss, liquidation risk, slippage efficiency.

Kabul: Net PnL daha iyi; drawdown daha kötü değil; fee ratio kabul edilebilir;
profit factor >= 1.15; slippage kontrol altında.

Kötü sonuç → otomatik rollback. Canlıya backtest+validasyon olmadan yazma.
Parametre sınırları: min_edge 0.06-0.45, min_skor 48-75, TP 0.18-1.50%,
SL 0.12-0.60%, max_open 3-20, aktif_sermaye 20-95%.
""".strip()

MARKET_RADAR_TRAINING_PROMPT = """
Aktif piyasa risk ve fırsat radarı — tüm kaynakları izler; hybrid skor ve acil kurallar.

Kaynaklar: Binance futures ticker, funding, open interest, liquidation proxy,
volume spike, whale alerts, BTC dominance, crypto news, ETF/regulation,
macro calendar, exchange announcements, listing/delisting.

Haber motoru:
- Bullish: long skor artır; spread genişse LONG bekle.
- Bearish: short skor artır; aşırı volatilitede stake düşür.
- Belirsiz: yeni pozisyon açma; açık pozisyonlarda risk azalt.

Acil durum:
- Spread patlaması → yeni işlem durdur.
- API gecikmesi → işlem durdur.
- 3 arka arkaya SL → agresiflik azalt.
- Günlük drawdown %8 → yarı risk; %12 → trade durdur.
- Fees >= Gross Profit → acil yavaş mod.
- Slippage yüksek → market emir azalt.

Fırsat modu (agresifleş):
liquidation cascade, volume explosion, breakout confirmation, orderbook sweep.
""".strip()

UNIFIED_ENGINE_TRAINING_PROMPT = """
Evrim birleşik motor — 10 modül tek orchestrator (yalnızca evrim).

Modüller: MTF, PA, VO, rejim, dinamik çıkış, expectancy, trade learning,
param validator, market radar, hybrid skor.

Hedef: hızlı, agresif, yüksek işlem sayısı; fee-aware; her işlemden öğrenme.
Varsayılan demo/testnet paper. Canlı kapalı — risk raporu yeşil olmadan açılmaz.

Canlı öncesi rapor: beklenen PnL/gün, fee/gross %, tahmini max DD, backtest WR.
RSS/haber feed radar_news_feed üzerinden skora bağlanır.

Self-tune: PARAM_BOUNDS içinde; backup → backtest → validator onayı olmadan canlıya yazma.
""".strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_expectancy_metrics() -> dict[str, Any]:
    from elite_trader.evrim_expectancy import _default_metrics

    return _default_metrics()


def _default_state() -> dict[str, Any]:
    return {
        "enabled": True,
        "mtf_enabled": True,
        "mtf_prompt_ingested": False,
        "pa_enabled": True,
        "pa_prompt_ingested": False,
        "pa_weights": {
            "breakout": 1.0,
            "fake_breakout": 1.0,
            "micro_hh_hl": 1.0,
            "micro_ll_lh": 1.0,
            "momentum_candle": 1.0,
            "engulfing": 1.0,
            "volume_breakout": 1.0,
            "volume_breakdown": 1.0,
            "strong_close_long": 1.0,
            "strong_close_short": 1.0,
        },
        "vo_enabled": True,
        "vo_prompt_ingested": False,
        "vo_weights": {
            "volume_spike": 1.0,
            "relative_volume": 1.0,
            "buy_sell_imbalance": 1.0,
            "bid_wall": 1.0,
            "ask_wall": 1.0,
            "liquidity_pull": 1.0,
            "orderbook_sweep": 1.0,
            "aggressive_market_buy": 1.0,
            "aggressive_market_sell": 1.0,
        },
        "regime_enabled": True,
        "regime_prompt_ingested": False,
        "regime_stats": {},
        "regime_overrides": {},
        "dynamic_exit_enabled": True,
        "dynamic_exit_prompt_ingested": False,
        "dynamic_exit_stats": {},
        "dynamic_exit_overrides": {},
        "expectancy_enabled": True,
        "expectancy_prompt_ingested": False,
        "expectancy_metrics": _default_expectancy_metrics(),
        "expectancy_overrides": {},
        "trade_learning_enabled": True,
        "trade_learning_prompt_ingested": False,
        "trade_journal_count": 0,
        "last_learning_analysis": None,
        "last_learning_analysis_at": None,
        "pending_parameter_patch": {},
        "pending_patch_requires_backtest": False,
        "profile_backup_paths": [],
        "param_auto_test_enabled": True,
        "param_auto_test_prompt_ingested": False,
        "last_param_validation": None,
        "param_validation_history": [],
        "prompt_history": [],
        "prompt_rules": [],
        "risk_symbols": [],
        "boost_symbols": [],
        "component_weight_overrides": {},
        "indicator_weights": {
            "trend_alignment": 1.0,
            "macd": 1.0,
            "bollinger": 1.0,
            "vwap": 1.0,
            "rsi_penalty": 1.0,
        },
        "last_backtest_at": None,
        "last_backtest_summary": None,
        "updated_at": _now_iso(),
    }


def load_training_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return _default_state()
    try:
        st = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        base = _default_state()
        base.update(st)
        return base
    except Exception:
        return _default_state()


def _save_training_state(st: dict[str, Any]) -> None:
    st["updated_at"] = _now_iso()
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(st, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def is_live_training_enabled(profile: dict[str, Any] | None = None) -> bool:
    prof = profile or get_profile(MODE_ID) or {}
    if prof.get("evrim_live_training") is False:
        return False
    st = load_training_state()
    return bool(prof.get("evrim_live_training", True)) or bool(st.get("enabled", True))


def set_training_enabled(enabled: bool) -> dict[str, Any]:
    st = load_training_state()
    st["enabled"] = enabled
    _save_training_state(st)
    save_profile(MODE_ID, {"evrim_live_training": enabled})
    return training_snapshot()


def apply_training_prompt(text: str, source: str = "user") -> dict[str, Any]:
    """Kullanıcı promptunu rehbere ve eğitim state'e işle."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty prompt"}

    st = load_training_state()
    hist = st.setdefault("prompt_history", [])
    hist.append({"at": _now_iso(), "source": source, "text": text[:8000]})
    if len(hist) > 100:
        st["prompt_history"] = hist[-100:]

    rules = st.setdefault("prompt_rules", [])
    rules.append(text[:2000])
    if len(rules) > 50:
        st["prompt_rules"] = rules[-50:]

    patch_profile: dict[str, Any] = {}
    lower = text.lower()

    for sym in re.findall(r"\b([A-Z]{2,12}USDT)\b", text.upper()):
        if any(w in lower for w in ("veto", "ban", "yasak", "avoid", "kaçın")):
            rs = set(st.get("risk_symbols") or [])
            rs.add(sym)
            st["risk_symbols"] = sorted(rs)
        if any(w in lower for w in ("boost", "favor", "tercih", "izle")):
            bs = set(st.get("boost_symbols") or [])
            bs.add(sym)
            st["boost_symbols"] = sorted(bs)

    m_edge = re.search(r"min[_\s]?edge\s*[=:]\s*([0-9.]+)", lower)
    if m_edge:
        patch_profile["min_edge"] = float(m_edge.group(1))
    m_score = re.search(r"(?:min[_\s]?)?total[_\s]?score\s*[=:]\s*([0-9]+)", lower)
    if m_score:
        patch_profile["evrim_min_total_score"] = int(m_score.group(1))
    if "gevşet" in lower or "loosen" in lower or "agresif" in lower:
        patch_profile["evrim_min_total_score"] = max(
            50, int((get_profile(MODE_ID) or {}).get("evrim_min_total_score") or 55) - 3
        )
    if "sıkı" in lower or "tighten" in lower or "seçici" in lower:
        patch_profile["evrim_min_total_score"] = min(
            75, int((get_profile(MODE_ID) or {}).get("evrim_min_total_score") or 55) + 3
        )

    guide = dict(LEARNING_GUIDE)
    guide.setdefault("user_prompts", [])
    guide["user_prompts"] = (guide.get("user_prompts") or [])[-19:] + [
        {"at": _now_iso(), "source": source, "excerpt": text[:500]}
    ]
    guide["hybrid_scoring"] = {
        "components": {
            "price_action": 25,
            "volume_delta": 20,
            "volatility_atr": 15,
            "trend_ema": 15,
            "orderbook_liquidity": 10,
            "news_whale_risk": 10,
            "execution_quality": 5,
        },
        "thresholds": {
            "no_trade_below": 55,
            "normal": 65,
            "aggressive": 75,
            "max_aggressive": 85,
        },
    }
    guide["mtf_indicators"] = {
        "timeframes": ["5m", "15m", "1h"],
        "ema": [9, 21, 50, 200],
        "rsi": [7, 14],
        "rules": [
            "indicators_never_open_alone",
            "trend_alignment_boosts_score",
            "rsi_extreme_reduces_counter_side",
            "low_atr_reduces_stake",
            "low_adx_chop_mode",
        ],
    }
    if "mtf" in lower or "indikatör" in lower or "indicator" in lower:
        st["mtf_enabled"] = True
    if any(
        w in lower
        for w in ("price action", "price_action", "breakout", "fake breakout", "fitil")
    ):
        st["pa_enabled"] = True
    guide["volume_orderbook"] = {
        "metrics": [
            "volume_spike",
            "relative_volume",
            "buy_sell_imbalance",
            "bid_wall",
            "ask_wall",
            "liquidity_pull",
            "orderbook_sweep",
            "large_order_in",
            "large_order_cancel",
            "aggressive_market_buy",
            "aggressive_market_sell",
            "whale_news_placeholder",
        ],
        "rules": [
            "never_open_alone",
            "rel_vol_1_2_boost",
            "rel_vol_1_8_aggressive",
            "ob_pressure_side_boost",
            "spread_wide_veto",
            "high_slippage_reduce_stake",
        ],
    }
    if any(
        w in lower
        for w in ("volume", "orderbook", "order book", "spread", "slippage", "imbalance")
    ):
        st["vo_enabled"] = True
    if any(
        w in lower
        for w in ("rejim", "regime", "trending", "breakout", "chop", "volatility", "news shock")
    ):
        st["regime_enabled"] = True
    if any(
        w in lower
        for w in (
            "dinamik",
            "dynamic",
            "tp/sl",
            "trailing",
            "partial tp",
            "break-even",
            "breakeven",
        )
    ):
        st["dynamic_exit_enabled"] = True
    if any(
        w in lower
        for w in (
            "expectancy",
            "expectans",
            "net pnl",
            "fee / gross",
            "fee/gross",
            "profit factor",
            "maker/taker",
        )
    ):
        st["expectancy_enabled"] = True
    if any(
        w in lower
        for w in (
            "öğrenme kaydı",
            "learning record",
            "trade journal",
            "50 işlem",
            "mfe",
            "mae",
            "trade quality",
        )
    ):
        st["trade_learning_enabled"] = True
    guide["trade_learning"] = {
        "record_fields": [
            "symbol",
            "direction",
            "entry_reason",
            "exit_reason",
            "score_breakdown",
            "market_regime",
            "indicators",
            "volume_state",
            "orderbook_state",
            "entry_price",
            "exit_price",
            "fee",
            "slippage",
            "net_pnl",
            "hold_time",
            "mfe",
            "mae",
            "trade_quality_score",
        ],
        "analysis_every_n": 50,
        "param_bounds": {
            "min_edge": [0.06, 0.45],
            "min_score": [48, 75],
            "tp_pct": [0.18, 1.5],
            "sl_pct": [0.12, 0.6],
            "max_open": [3, 20],
            "active_capital_pct": [20, 95],
        },
        "rules": [
            "backup_before_patch",
            "backtest_required_before_live",
            "bounded_parameters_only",
        ],
    }
    guide["expectancy"] = {
        "formula": "expected_net = gross - entry_fee - exit_fee - spread - slippage - funding",
        "metrics": [
            "fee_to_gross_profit_pct",
            "gross_profit_to_fee_ratio",
            "net_pnl_per_trade",
            "avg_slippage_bps",
            "avg_spread_pct",
            "maker_taker_ratio",
            "profit_factor",
            "win_rate_pct",
            "avg_win_usd",
            "avg_loss_usd",
            "expectancy_usd",
        ],
        "rules": [
            "negative_expectancy_veto",
            "fee_gross_over_45_reduce_aggressive",
            "fee_gross_over_70_slow_trades",
            "fees_ge_gross_emergency",
        ],
    }
    guide["dynamic_exit"] = {
        "score_bands": [
            {"min": 65, "max": 75, "tp_pct": "0.25-0.40", "sl_pct": "0.15-0.25"},
            {"min": 75, "max": 85, "tp_pct": "0.40-0.75", "sl_pct": "0.20-0.35"},
            {"min": 85, "max": 100, "tp_pct": "0.75-1.50", "sl_pct": "0.30-0.55"},
        ],
        "inputs": [
            "atr",
            "momentum",
            "volume_spike",
            "spread",
            "fee",
            "slippage",
            "market_regime",
            "hybrid_score",
        ],
        "rules": [
            "trailing_breakeven_after_profit",
            "partial_tp_50_at_first_tp",
            "momentum_weak_exit",
            "fee_floor_on_tp",
        ],
    }
    guide["market_regimes"] = {
        "regimes": list(
            (
                "trending",
                "breakout",
                "chop",
                "high_volatility",
                "low_volatility",
                "liquidation_cascade",
                "news_shock",
                "fake_pump_dump",
            )
        ),
        "rules": [
            "regime_never_open_alone",
            "trending_follow_trend_trailing",
            "breakout_partial_tp_reentry",
            "chop_reduce_stake_filter",
            "news_shock_spread_veto",
        ],
    }
    guide["price_action_patterns"] = {
        "structures": [
            "breakout",
            "fake_breakout",
            "liquidity_grab",
            "stop_hunt",
            "wick_rejection",
            "momentum_candle",
            "engulfing",
            "range_breakout",
            "micro_hh_hl",
            "micro_ll_lh",
            "body_expansion",
            "consecutive_pressure",
        ],
        "rules": [
            "patterns_never_open_alone",
            "fake_breakout_veto_or_reduce_stake",
            "long_higher_high_expansion_volume_breakout",
            "short_lower_low_expansion_volume_breakdown",
        ],
    }
    _GUIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GUIDE_PATH.write_text(
        json.dumps(guide, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _save_training_state(st)
    merged = {}
    if patch_profile:
        merged = save_profile(MODE_ID, patch_profile)

    return {
        "ok": True,
        "prompt_len": len(text),
        "profile_patch": patch_profile,
        "profile": merged or get_profile(MODE_ID),
        "training": training_snapshot(),
    }


def ensure_mtf_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("mtf_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(MTF_TRAINING_PROMPT, source="mtf_spec")
    st = load_training_state()
    st["mtf_prompt_ingested"] = True
    st["mtf_enabled"] = True
    _save_training_state(st)
    save_profile(
        MODE_ID,
        {
            "evrim_mtf_enabled": True,
            "evrim_mtf_timeframes": ["5m", "15m", "1h"],
            "evrim_adx_chop_threshold": 18,
            "evrim_atr_stake_floor_mult": 0.80,
        },
    )
    return out


def ensure_pa_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("pa_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(PRICE_ACTION_TRAINING_PROMPT, source="pa_spec")
    st = load_training_state()
    st["pa_prompt_ingested"] = True
    st["pa_enabled"] = True
    _save_training_state(st)
    save_profile(
        MODE_ID,
        {
            "evrim_pa_enabled": True,
            "evrim_pa_fake_veto_threshold": 0.72,
            "evrim_pa_fake_stake_mult": 0.55,
        },
    )
    return out


def ensure_vo_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("vo_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(VOLUME_ORDERBOOK_TRAINING_PROMPT, source="vo_spec")
    st = load_training_state()
    st["vo_prompt_ingested"] = True
    st["vo_enabled"] = True
    _save_training_state(st)
    save_profile(
        MODE_ID,
        {
            "evrim_vo_enabled": True,
            "evrim_vo_rel_vol_boost": 1.2,
            "evrim_vo_aggressive_rel_vol": 1.8,
            "evrim_vo_spread_veto_pct": 0.12,
            "evrim_vo_slippage_stake_bps": 25,
            "evrim_vo_slippage_stake_mult": 0.70,
        },
    )
    return out


def ensure_regime_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("regime_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(MARKET_REGIME_TRAINING_PROMPT, source="regime_spec")
    st = load_training_state()
    st["regime_prompt_ingested"] = True
    st["regime_enabled"] = True
    _save_training_state(st)
    save_profile(
        MODE_ID,
        {
            "evrim_regime_enabled": True,
            "evrim_regime_news_spread_pct": 0.15,
            "evrim_regime_fake_pump_prob": 0.60,
        },
    )
    return out


def ensure_dynamic_exit_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("dynamic_exit_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(DYNAMIC_EXIT_TRAINING_PROMPT, source="dynamic_exit_spec")
    st = load_training_state()
    st["dynamic_exit_prompt_ingested"] = True
    st["dynamic_exit_enabled"] = True
    _save_training_state(st)
    save_profile(
        MODE_ID,
        {
            "evrim_dynamic_exit_enabled": True,
            "evrim_partial_tp_frac": 0.5,
            "evrim_trailing_enabled": True,
            "evrim_momentum_weak_exit": True,
            "evrim_breakeven_buffer_pct": 0.08,
        },
    )
    return out


def ensure_expectancy_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("expectancy_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(EXPECTANCY_TRAINING_PROMPT, source="expectancy_spec")
    st = load_training_state()
    st["expectancy_prompt_ingested"] = True
    st["expectancy_enabled"] = True
    if not st.get("expectancy_metrics"):
        st["expectancy_metrics"] = _default_expectancy_metrics()
    _save_training_state(st)
    save_profile(
        MODE_ID,
        {
            "evrim_expectancy_enabled": True,
            "evrim_expectancy_min_net_usd": 0.05,
        },
    )
    return out


def ensure_trade_learning_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("trade_learning_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(TRADE_LEARNING_TRAINING_PROMPT, source="trade_learning_spec")
    st = load_training_state()
    st["trade_learning_prompt_ingested"] = True
    st["trade_learning_enabled"] = True
    _save_training_state(st)
    save_profile(MODE_ID, {"evrim_trade_learning_enabled": True})
    return out


def ensure_param_auto_test_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("param_auto_test_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(PARAM_AUTO_TEST_TRAINING_PROMPT, source="param_auto_test_spec")
    st = load_training_state()
    st["param_auto_test_prompt_ingested"] = True
    st["param_auto_test_enabled"] = True
    _save_training_state(st)
    save_profile(MODE_ID, {"evrim_param_auto_test_enabled": True})
    return out


def ensure_unified_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("unified_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(UNIFIED_ENGINE_TRAINING_PROMPT, source="unified_engine_spec")
    st = load_training_state()
    st["unified_prompt_ingested"] = True
    st["unified_engine_enabled"] = True
    _save_training_state(st)
    save_profile(
        MODE_ID,
        {
            "evrim_unified_engine_enabled": True,
            "evrim_trading_mode": "demo",
            "evrim_live_trading_enabled": False,
        },
    )
    return out


def ensure_market_radar_prompt_ingested() -> dict[str, Any]:
    st = load_training_state()
    if st.get("market_radar_prompt_ingested"):
        return {"ok": True, "skipped": "already ingested"}
    out = apply_training_prompt(MARKET_RADAR_TRAINING_PROMPT, source="market_radar_spec")
    st = load_training_state()
    st["market_radar_prompt_ingested"] = True
    st["market_radar_enabled"] = True
    if not st.get("market_radar_state"):
        st["market_radar_state"] = {
            "day_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "day_pnl_usd": 0.0,
            "day_pnl_pct": 0.0,
            "consecutive_sl": 0,
        }
    _save_training_state(st)
    save_profile(
        MODE_ID,
        {
            "evrim_market_radar_enabled": True,
            "evrim_radar_spread_spike_pct": 0.18,
            "evrim_radar_news_spread_wait_pct": 0.14,
            "evrim_radar_api_max_ms": 2500,
        },
    )
    return out


def apply_backtest_results(summary: dict[str, Any]) -> dict[str, Any]:
    """Backtest sonucunu state'e yaz; trading active config'i korur."""
    try:
        from elite_trader.evrim_learning_runtime import learning_task

        with learning_task("backtest"):
            return _apply_backtest_results_inner(summary)
    except Exception:
        return _apply_backtest_results_inner(summary)


def _apply_backtest_results_inner(summary: dict[str, Any]) -> dict[str, Any]:
    learn_apply: dict[str, Any] = {}
    try:
        from elite_trader.evrim_trade_learning import apply_pending_patch_after_backtest

        learn_apply = apply_pending_patch_after_backtest(summary)
        summary["learning_patch_apply"] = learn_apply
        summary["param_validation"] = learn_apply.get("validation_report")
        summary["param_validation_accepted"] = learn_apply.get("ok") and bool(
            learn_apply.get("applied")
        )
    except Exception as exc:
        summary["learning_patch_apply"] = {"ok": False, "error": str(exc)[:80]}

    st = load_training_state()
    st["last_backtest_at"] = _now_iso()
    st["last_backtest_summary"] = summary
    if summary.get("indicator_weights"):
        st["indicator_weights"] = summary["indicator_weights"]
    if summary.get("pa_weights"):
        st["pa_weights"] = summary["pa_weights"]
    if summary.get("vo_weights"):
        st["vo_weights"] = summary["vo_weights"]
    if summary.get("regime_stats"):
        st["regime_stats"] = summary["regime_stats"]
    if summary.get("radar_stats"):
        st["radar_stats"] = summary["radar_stats"]
    if summary.get("regime_overrides"):
        st["regime_overrides"] = summary["regime_overrides"]
    if summary.get("dynamic_exit_stats"):
        st["dynamic_exit_stats"] = summary["dynamic_exit_stats"]
    if summary.get("dynamic_exit_overrides"):
        st["dynamic_exit_overrides"] = summary["dynamic_exit_overrides"]
    if summary.get("expectancy_metrics"):
        st["expectancy_metrics"] = summary["expectancy_metrics"]
    if summary.get("expectancy_overrides"):
        st["expectancy_overrides"] = summary["expectancy_overrides"]
    if summary.get("learning_analysis"):
        st["last_learning_analysis"] = summary["learning_analysis"]
    if summary.get("param_validation"):
        st["last_param_validation"] = summary["param_validation"]
    if summary.get("pending_parameter_patch") is not None and not (
        (summary.get("learning_patch_apply") or {}).get("applied")
    ):
        st["pending_parameter_patch"] = summary.get("pending_parameter_patch") or {}
        st["pending_patch_requires_backtest"] = bool(
            summary.get("pending_patch_requires_backtest", True)
        )
    if summary.get("pa_veto_threshold") is not None:
        st["pa_veto_threshold_note"] = summary["pa_veto_threshold"]
    _save_training_state(st)

    patch: dict[str, Any] = {}
    applied_keys = set((learn_apply.get("applied") or {}).keys())
    if summary.get("evrim_min_total_score") is not None and "evrim_min_total_score" not in applied_keys:
        patch["evrim_min_total_score"] = int(summary["evrim_min_total_score"])
    if summary.get("evrim_max_tier") and "evrim_max_tier" not in applied_keys:
        patch["evrim_max_tier"] = summary["evrim_max_tier"]
    if (
        summary.get("evrim_pa_fake_veto_threshold") is not None
        and "evrim_pa_fake_veto_threshold" not in applied_keys
    ):
        patch["evrim_pa_fake_veto_threshold"] = float(
            summary["evrim_pa_fake_veto_threshold"]
        )
    if (
        summary.get("evrim_vo_spread_veto_pct") is not None
        and "evrim_vo_spread_veto_pct" not in applied_keys
    ):
        patch["evrim_vo_spread_veto_pct"] = float(summary["evrim_vo_spread_veto_pct"])
    if patch:
        save_profile(MODE_ID, patch)

    _BT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _BT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        from elite_trader.evrim_cross_strategy_lab import merge_backtest_learnings

        merge_backtest_learnings(summary)
    except Exception:
        pass
    return {"ok": True, "summary": summary}


def trigger_mtf_backtest(*, background: bool = True) -> dict[str, Any]:
    """Offline backtest script — calisan bota dokunmaz."""
    import subprocess
    import sys

    script = _ROOT / "scripts" / "evrim_mtf_backtest.py"
    if not script.is_file():
        return {"ok": False, "error": "script missing"}
    cmd = [sys.executable, str(script)]
    if background:
        subprocess.Popen(
            cmd,
            cwd=str(_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"ok": True, "started": True, "background": True}
    proc = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True, timeout=900)
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": (proc.stderr or proc.stdout or "backtest failed")[:500],
        }
    return {"ok": True, "background": False, "snapshot": training_snapshot()}


def load_last_backtest() -> dict[str, Any] | None:
    if not _BT_PATH.is_file():
        return None
    try:
        return json.loads(_BT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def training_snapshot() -> dict[str, Any]:
    from elite_trader.evrim_decision_log import aggregate_stats, read_recent

    prof = get_profile(MODE_ID) or {}
    st = load_training_state()
    bt = st.get("last_backtest_summary") or load_last_backtest()
    risk_report: dict[str, Any] = {}
    try:
        from elite_trader.evrim_unified_engine import build_pre_live_risk_report

        risk_report = build_pre_live_risk_report(prof)
        st["last_risk_report"] = risk_report
        _save_training_state(st)
    except Exception:
        risk_report = st.get("last_risk_report") or {}
    lab: dict[str, Any] = {}
    try:
        from elite_trader.evrim_cross_strategy_lab import build_development_report

        lab = build_development_report()
    except Exception:
        pass
    return {
        "mode_id": MODE_ID,
        "live_training": is_live_training_enabled(prof),
        "mtf_enabled": prof.get("evrim_mtf_enabled", True),
        "pa_enabled": prof.get("evrim_pa_enabled", True),
        "vo_enabled": prof.get("evrim_vo_enabled", True),
        "regime_enabled": prof.get("evrim_regime_enabled", True),
        "dynamic_exit_enabled": prof.get("evrim_dynamic_exit_enabled", True),
        "expectancy_enabled": prof.get("evrim_expectancy_enabled", True),
        "trade_learning_enabled": prof.get("evrim_trade_learning_enabled", True),
        "param_auto_test_enabled": prof.get("evrim_param_auto_test_enabled", True),
        "market_radar_enabled": prof.get("evrim_market_radar_enabled", True),
        "unified_engine_enabled": prof.get("evrim_unified_engine_enabled", True),
        "evrim_trading_mode": prof.get("evrim_trading_mode", "demo"),
        "evrim_live_trading_enabled": prof.get("evrim_live_trading_enabled", False),
        "min_total_score": prof.get("evrim_min_total_score", 55),
        "min_edge": prof.get("min_edge"),
        "max_tier": prof.get("evrim_max_tier", "max_aggressive"),
        "training_state": {
            "enabled": st.get("enabled"),
            "mtf_enabled": st.get("mtf_enabled", True),
            "mtf_prompt_ingested": st.get("mtf_prompt_ingested", False),
            "pa_enabled": st.get("pa_enabled", True),
            "pa_prompt_ingested": st.get("pa_prompt_ingested", False),
            "pa_weights": st.get("pa_weights") or {},
            "vo_enabled": st.get("vo_enabled", True),
            "vo_prompt_ingested": st.get("vo_prompt_ingested", False),
            "vo_weights": st.get("vo_weights") or {},
            "regime_enabled": st.get("regime_enabled", True),
            "regime_prompt_ingested": st.get("regime_prompt_ingested", False),
            "regime_stats": st.get("regime_stats") or {},
            "regime_overrides": st.get("regime_overrides") or {},
            "dynamic_exit_enabled": st.get("dynamic_exit_enabled", True),
            "dynamic_exit_prompt_ingested": st.get("dynamic_exit_prompt_ingested", False),
            "dynamic_exit_stats": st.get("dynamic_exit_stats") or {},
            "dynamic_exit_overrides": st.get("dynamic_exit_overrides") or {},
            "expectancy_enabled": st.get("expectancy_enabled", True),
            "expectancy_prompt_ingested": st.get("expectancy_prompt_ingested", False),
            "expectancy_metrics": st.get("expectancy_metrics") or _default_expectancy_metrics(),
            "expectancy_overrides": st.get("expectancy_overrides") or {},
            "trade_learning_enabled": st.get("trade_learning_enabled", True),
            "trade_learning_prompt_ingested": st.get("trade_learning_prompt_ingested", False),
            "trade_journal_count": st.get("trade_journal_count", 0),
            "last_learning_analysis": st.get("last_learning_analysis"),
            "pending_parameter_patch": st.get("pending_parameter_patch") or {},
            "pending_patch_requires_backtest": st.get("pending_patch_requires_backtest", False),
            "param_auto_test_enabled": st.get("param_auto_test_enabled", True),
            "param_auto_test_prompt_ingested": st.get("param_auto_test_prompt_ingested", False),
            "last_param_validation": st.get("last_param_validation"),
            "market_radar_enabled": st.get("market_radar_enabled", True),
            "market_radar_prompt_ingested": st.get("market_radar_prompt_ingested", False),
            "market_radar_state": st.get("market_radar_state") or {},
            "radar_news_feed": st.get("radar_news_feed") or {},
            "last_risk_report": risk_report or st.get("last_risk_report") or {},
            "unified_engine_enabled": st.get("unified_engine_enabled", True),
            "unified_prompt_ingested": st.get("unified_prompt_ingested", False),
            "risk_symbols": st.get("risk_symbols") or [],
            "boost_symbols": st.get("boost_symbols") or [],
            "prompt_rules_count": len(st.get("prompt_rules") or []),
            "prompt_history_count": len(st.get("prompt_history") or []),
            "indicator_weights": st.get("indicator_weights") or {},
            "last_backtest_at": st.get("last_backtest_at"),
            "updated_at": st.get("updated_at"),
        },
        "last_backtest": bt,
        "recent_decisions": read_recent(30),
        "stats": aggregate_stats(500),
        "hybrid_gate_stats": aggregate_stats(500),
        "cross_strategy_lab": lab,
    }
