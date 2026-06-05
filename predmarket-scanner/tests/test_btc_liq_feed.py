"""btc_liq_feed — arka plan önbellek, cluster, giriş bias."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

import elite_trader.btc_liq_feed as liq


@pytest.fixture(autouse=True)
def _reset_liq(monkeypatch):
    monkeypatch.setenv("MEGA_BTC_LIQ_ENABLED", "1")
    monkeypatch.setenv("MEGA_BTC_LIQ_CQ_ENABLED", "0")
    liq._ctx.clear()
    liq._ctx["updated_at"] = 0.0
    liq._force_ring.clear()
    liq._oi_ring.clear()
    yield


def test_fetch_binance_builds_clusters(monkeypatch):
    client = MagicMock()
    client.paper = False

    def fake_get(path, params=None):
        if path == "/fapi/v1/premiumIndex":
            return {"markPrice": "100000"}
        if path == "/fapi/v1/openInterest":
            return {"openInterest": "1000"}
        if "globalLongShort" in path:
            return [{"longShortRatio": "1.2", "longAccount": "0.55", "shortAccount": "0.45"}]
        if "allForceOrders" in path:
            return [
                {"price": "99000", "origQty": "1", "side": "SELL", "time": int(time.time() * 1000)},
                {"price": "101000", "origQty": "0.5", "side": "BUY", "time": int(time.time() * 1000)},
            ]
        return {}

    client._get = fake_get
    out = liq._fetch_binance_liq(client)
    assert out.get("binance_ok") is True
    assert out.get("mark_price") == 100000.0
    assert float(out.get("long_liq_below_usd") or 0) > 0
    assert out.get("cluster_bias") in ("long_liq_below", "short_liq_above", "neutral")


def test_liq_snapshot_reads_cache(monkeypatch):
    liq._ctx.update(
        {
            "updated_at": time.time(),
            "cluster_summary": "↓long liq $0.10M",
            "cluster_bias": "long_liq_below",
            "mark_price": 100000,
        }
    )
    snap = liq.liq_snapshot()
    assert "long" in snap["summary"].lower() or snap["bias"] == "long_liq_below"


def test_liquidation_proxy_range(monkeypatch):
    liq._ctx.update({"long_liq_below_usd": 500_000, "short_liq_above_usd": 100_000})
    p = liq.liquidation_proxy()
    assert 0.0 <= p <= 1.0


def test_entry_gate_default_off(monkeypatch):
    monkeypatch.setenv("MEGA_BTC_LIQ_ENTRY_GATE", "0")
    liq._ctx.update({"cluster_bias": "long_liq_below", "long_liq_below_usd": 999_999})
    ok, _ = liq.liq_entry_allowed("LONG")
    assert ok is True


def test_fast_tick_rebuilds_clusters(monkeypatch):
    monkeypatch.setenv("MEGA_BTC_LIQ_FAST_SEC", "1")
    liq._force_ring.append(
        {
            "ts": time.time(),
            "price": 99000,
            "qty": 2,
            "usd": 198000,
            "side": "SELL",
        }
    )
    liq._ctx.update({"mark_price": 100000, "rest_updated_at": time.time()})
    out = liq.refresh_btc_liq_fast(force=True)
    assert out.get("fast_updated_at", 0) > 0
    assert float(out.get("long_liq_below_usd") or 0) > 0


def test_rest_refresh_sec_default(monkeypatch):
    monkeypatch.delenv("MEGA_BTC_LIQ_REST_SEC", raising=False)
    monkeypatch.delenv("MEGA_BTC_LIQ_REFRESH_SEC", raising=False)
    assert liq.rest_refresh_sec() == 10.0
    assert liq.fast_tick_sec() >= 1.0
