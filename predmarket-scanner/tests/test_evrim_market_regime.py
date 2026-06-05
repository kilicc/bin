"""Smoke tests for 8-regime classifier."""
from __future__ import annotations

from elite_trader.evrim_market_regime import REGIMES, classify_market_regime


def _ctx(**kw) -> dict:
    base = {
        "atr_pct": 0.08,
        "vol_ratio": 1.0,
        "spread_pct": 0.05,
        "chop": False,
        "last_candle": {"o": 100, "h": 101, "l": 99, "c": 100.5},
        "klines_5m": [{"o": 100, "h": 100.5, "l": 99.5, "c": 100}],
    }
    base.update(kw)
    return base


def test_regimes_tuple():
    assert len(REGIMES) == 8


def test_news_shock_spread():
    rid, conf, pol = classify_market_regime(
        _ctx(spread_pct=0.20), "LONG", {"evrim_regime_news_spread_pct": 0.15}
    )
    assert rid == "news_shock"
    assert pol.veto


def test_liquidation_cascade():
    rid, _, _ = classify_market_regime(
        _ctx(vol_ratio=3.0, last_candle={"o": 100, "h": 105, "l": 95, "c": 98}),
        "SHORT",
        {},
    )
    assert rid == "liquidation_cascade"


def test_fake_pump_dump():
    rid, _, pol = classify_market_regime(
        _ctx(pa={"fake_breakout_prob": 0.75}), "LONG", {"evrim_regime_fake_pump_prob": 0.60}
    )
    assert rid == "fake_pump_dump"
    assert pol.stake_mult <= 0.55


def test_low_volatility():
    rid, _, pol = classify_market_regime(_ctx(atr_pct=0.02), "LONG", {"evrim_atr_min_pct": 0.055})
    assert rid == "low_volatility"
    assert pol.veto or not pol.allow_enter


def test_high_volatility():
    rid, _, _ = classify_market_regime(_ctx(atr_pct=0.15), "LONG", {"evrim_atr_min_pct": 0.055})
    assert rid == "high_volatility"


def test_breakout():
    rid, _, _ = classify_market_regime(
        _ctx(vol_ratio=1.5, mtf={"summary": {"bb_breakout_up": True, "chop_mode": False}}),
        "LONG",
        {},
    )
    assert rid == "breakout"


def test_trending():
    rid, _, _ = classify_market_regime(
        _ctx(
            mtf={"summary": {"trend_alignment": "bull", "chop_mode": False}},
            vol_ratio=1.1,
        ),
        "LONG",
        {},
    )
    assert rid == "trending"


def test_chop_fallback():
    rid, _, _ = classify_market_regime(_ctx(chop=True, atr_pct=0.08), "LONG", {})
    assert rid == "chop"
