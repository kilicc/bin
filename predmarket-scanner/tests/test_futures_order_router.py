"""futures_order_router — 5 senaryo."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import futures_order_router as router
from elite_trader.futures_order_router import route_order_intent


def _intent(sym: str = "BTCUSDT") -> dict:
    return {"symbol": sym, "side": "LONG"}


def test_live_when_active_and_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "_SAFE_MODE_PATH", tmp_path / "safe.json")
    r = route_order_intent(
        "evrim",
        _intent(),
        active_futures_mode="evrim",
        api_healthy=True,
        live_orders_enabled=True,
    )
    assert r.send_live is True
    assert r.is_paper is False
    assert r.routed_to_paper is False
    assert r.order_route == "BINANCE_FUTURES_LIVE_ENGINE"
    assert r.order_sent is False


def test_paper_when_mode_not_active(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "_SAFE_MODE_PATH", tmp_path / "safe.json")
    r = route_order_intent(
        "berserk",
        _intent(),
        active_futures_mode="evrim",
        api_healthy=True,
    )
    assert r.send_live is False
    assert r.routed_to_paper is True
    assert "mode_not_active" in r.reason


def test_paper_when_api_unhealthy(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "_SAFE_MODE_PATH", tmp_path / "safe.json")
    r = route_order_intent(
        "evrim",
        _intent(),
        active_futures_mode="evrim",
        api_healthy=False,
    )
    assert r.send_live is False
    assert r.reason == "api_unhealthy"


def test_paper_when_safe_mode(tmp_path, monkeypatch):
    safe = tmp_path / "safe.json"
    monkeypatch.setattr(router, "_SAFE_MODE_PATH", safe)
    safe.write_text(json.dumps({"active": True}), encoding="utf-8")
    r = route_order_intent(
        "evrim",
        _intent(),
        active_futures_mode="evrim",
        api_healthy=True,
    )
    assert r.send_live is False
    assert r.reason == "system_safe_mode"


def test_paper_when_live_orders_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "_SAFE_MODE_PATH", tmp_path / "safe.json")
    r = route_order_intent(
        "evrim",
        _intent(),
        active_futures_mode="evrim",
        live_orders_enabled=False,
    )
    assert r.send_live is False
    assert r.reason == "live_orders_disabled"
