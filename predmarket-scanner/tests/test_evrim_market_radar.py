"""Smoke tests for evrim_market_radar."""
from elite_trader.evrim_market_radar import (
    classify_news,
    detect_opportunity,
    evaluate_emergency,
    scan_market_radar,
    SOURCE_TYPES,
)


def test_source_types():
    assert len(SOURCE_TYPES) >= 10


def test_emergency_spread_halt():
    prof = {"evrim_radar_spread_spike_pct": 0.15}
    out = evaluate_emergency(prof, {}, {"spread_pct": 0.20})
    assert out["block_new_entries"] is True
    assert "spread_spike" in out["reasons"]


def test_scan_bt_proxy():
    ctx = {
        "ok": True,
        "radar_bt_proxy": True,
        "vol_ratio": 2.2,
        "spread_pct": 0.06,
        "atr_pct": 0.08,
        "funding_abs": 0,
        "last_candle": {"o": 1, "h": 1.1, "l": 0.9, "c": 1.05},
    }
    r = scan_market_radar("BTCUSDT", "LONG", ctx, {"evrim_market_radar_enabled": True})
    assert r.ok
    assert r.feeds.get("volume_spike")


def test_classify_bullish():
    feeds = {
        "binance_ticker": {"change_pct": 2.0},
        "funding_rates": {"rate": 0.0001},
    }
    sent, _, ld, sd = classify_news(feeds, {}, "LONG")
    assert sent == "bullish"
    assert ld > sd


if __name__ == "__main__":
    test_source_types()
    test_emergency_spread_halt()
    test_scan_bt_proxy()
    test_classify_bullish()
    print("ok")
