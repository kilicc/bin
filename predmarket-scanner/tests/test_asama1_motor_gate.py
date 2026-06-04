"""Aşama 1 — motor gate güvenlik testleri (MD spec)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from elite_trader import futures_order_router as router
from elite_trader.futures_order_router import route_order_intent
from elite_trader.order_gate import (
    ORDER_ROUTE_LIVE,
    ORDER_ROUTE_PAPER,
    PaperModeOrderBlockedError,
    assert_binance_send_allowed,
    build_order_intent,
    route_order,
    run_live_preflight_checks,
)


def _intent(sym: str = "BTCUSDT") -> dict:
    return build_order_intent("berserk", symbol=sym, side="LONG")


@pytest.fixture
def safe_path(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "_SAFE_MODE_PATH", tmp_path / "safe.json")
    return tmp_path


# Test 1 — active=EVRIM, berserk → PAPER
def test_berserk_paper_when_evrim_active(safe_path):
    g = route_order(
        "berserk",
        _intent(),
        active_futures_mode="evrim",
        api_healthy=True,
        live_orders_enabled=True,
    )
    assert g.order_route == ORDER_ROUTE_PAPER
    assert g.is_paper is True
    assert g.send_live is False


# Test 2 — active=HUNTER, hunter → LIVE candidate; preflight olmadan send yok
def test_hunter_live_candidate_needs_preflight(safe_path):
    g = route_order(
        "hunter",
        build_order_intent("hunter", symbol="ETHUSDT", side="LONG"),
        active_futures_mode="hunter",
        api_healthy=True,
        live_orders_enabled=True,
    )
    assert g.order_route == ORDER_ROUTE_LIVE
    assert g.send_live is True
    assert g.allow_binance_send is False
    g2 = run_live_preflight_checks(g, api_healthy=False)
    assert g2.allow_binance_send is False


# Test 3 — active=null → all PAPER
def test_all_paper_when_active_empty(safe_path):
    for mid in ("evrim", "berserk", "hunter", "chop_master", "sentinel"):
        g = route_order(
            mid,
            build_order_intent(mid, symbol="X", side="LONG"),
            active_futures_mode="",
            api_healthy=True,
        )
        assert g.order_route == ORDER_ROUTE_PAPER
        assert g.send_live is False


# Test 4 — paper mod Binance assert
def test_paper_mode_cannot_assert_binance_send():
    with pytest.raises(PaperModeOrderBlockedError):
        assert_binance_send_allowed("berserk", "evrim")
    with pytest.raises(PaperModeOrderBlockedError):
        assert_binance_send_allowed("evrim", "")


# Test 5 — motor değişince profil aynı kalır
def test_mode_switch_does_not_change_profile(tmp_path, monkeypatch):
    prof_path = tmp_path / "mode_profiles.json"
    orig = {
        "modes": {
            "evrim": {"min_edge": 0.08, "max_open": 10},
            "berserk": {"min_edge": 0.045, "max_open": 18},
        }
    }
    prof_path.write_text(json.dumps(orig), encoding="utf-8")
    monkeypatch.setattr(
        "elite_trader.mode_profiles._PROFILES_PATH",
        prof_path,
        raising=False,
    )
    before = json.loads(prof_path.read_text(encoding="utf-8"))
    from elite_trader.panel_strategy import set_execution_mode

    try:
        set_execution_mode("berserk")
        set_execution_mode("evrim")
    except Exception:
        pass
    after = json.loads(prof_path.read_text(encoding="utf-8"))
    assert before["modes"]["evrim"]["min_edge"] == after["modes"]["evrim"]["min_edge"]
    assert before["modes"]["berserk"]["max_open"] == after["modes"]["berserk"]["max_open"]


# Test 6 — active=SENTINEL, others paper
def test_sentinel_active_others_paper(safe_path):
    for mid in ("evrim", "berserk", "hunter", "chop_master"):
        g = route_order(
            mid,
            build_order_intent(mid, symbol="BTCUSDT", side="LONG"),
            active_futures_mode="sentinel",
            api_healthy=True,
            live_orders_enabled=True,
        )
        assert g.order_route == ORDER_ROUTE_PAPER
        with pytest.raises(PaperModeOrderBlockedError):
            assert_binance_send_allowed(mid, "sentinel")


# Test 7 — live trade yalnızca active mode
def test_live_trade_ingest_active_mode_only():
    from elite_trader.data_lake.ingest import ingest_live_trade

    trade = {"symbol": "BTCUSDT", "side": "LONG", "stake_usd": 100}
    with pytest.raises(PermissionError):
        ingest_live_trade("evrim", trade, closing=True, active_futures_mode="hunter")


def test_router_live_has_order_route_field(safe_path):
    r = route_order_intent(
        "evrim",
        {"symbol": "BTCUSDT"},
        active_futures_mode="evrim",
        api_healthy=True,
        live_orders_enabled=True,
    )
    assert r.order_route == ORDER_ROUTE_LIVE
    assert r.order_sent is False


# Test 8 — MD 32 zorunlu log alanı decision_log tablosunda kolon olarak var
def test_decision_log_has_32_mandatory_columns(tmp_path, monkeypatch):
    from elite_trader.data_lake import db as dl_db

    monkeypatch.setattr(dl_db, "DB_PATH", tmp_path / "test_data_lake.db")
    monkeypatch.setattr(dl_db, "_conn", None, raising=False)
    dl_db.init_db()
    conn = dl_db.get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(decision_log)").fetchall()}
    md_required = {
        "ts", "mode_id", "mode_name", "active_futures_mode",
        "symbol", "side", "market_regime",
        "score_total", "score_breakdown",
        "entry_reason", "reject_reason", "veto_reason", "risk_level",
        "expected_net_pnl", "spread", "slippage_estimate",
        "expected_fee", "expected_funding",
        "order_route", "is_paper", "order_sent", "exchange_accepted",
        "entry_price", "exit_price", "gross_pnl", "fee", "funding", "net_pnl",
        "hold_time", "result", "learning_tag",
    }
    missing = md_required - cols
    assert not missing, f"decision_log missing MD columns: {missing}"


# Test 9 — ingest_decision_log paper kararı yazıp okunabilir
def test_ingest_decision_log_writes_paper_row(tmp_path, monkeypatch):
    from elite_trader.data_lake import db as dl_db
    from elite_trader.data_lake.ingest import (
        ingest_decision_log,
        query_decision_log,
        reject_summary,
        route_distribution,
    )

    monkeypatch.setattr(dl_db, "DB_PATH", tmp_path / "test_data_lake_2.db")
    monkeypatch.setattr(dl_db, "_conn", None, raising=False)
    dl_db.init_db()

    ingest_decision_log(
        "berserk",
        mode_name="BERSERK",
        active_futures_mode="evrim",
        symbol="BTCUSDT",
        side="LONG",
        market_regime="trending_up",
        score_total=0.73,
        entry_reason="trend+score",
        reject_reason="spread_too_wide",
        risk_level="LOW",
        expected_net_pnl=0.42,
        spread=0.05,
        order_route="PAPER_ENGINE",
        is_paper=True,
        order_sent=False,
    )
    rows = query_decision_log("berserk", reader_id="evrim", limit=10)
    assert len(rows) == 1
    assert rows[0]["mode_id"] == "berserk"
    assert rows[0]["order_route"] == "PAPER_ENGINE"
    assert rows[0]["is_paper"] == 1
    assert rows[0]["reject_reason"] == "spread_too_wide"

    rejects = reject_summary("berserk", reader_id="evrim")
    assert rejects and rejects[0]["reason"] == "spread_too_wide"

    dist = route_distribution("berserk", reader_id="evrim")
    assert dist.get("PAPER_ENGINE") == 1
