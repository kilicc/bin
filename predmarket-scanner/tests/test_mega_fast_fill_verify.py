"""Hızlı spike fill doğrulama — slippage reddi, spread toleransı."""
from __future__ import annotations

from elite_trader.exchange_fill_truth import (
    fill_gross_sane_vs_mark,
    fill_slippage_reject,
    _book_spread_cost_usd,
)


def test_slippage_reject_arb_style():
    assert fill_slippage_reject(29.0, -2.2, pre_send_gross=29.0) is True
    assert fill_slippage_reject(15.0, 6.0, pre_send_gross=15.0) is False


def test_spread_cost_long():
    pos = {"side": "LONG", "size": 1000.0}
    book = {"bid": 9.02, "ask": 9.04, "mid": 9.03}
    cost = _book_spread_cost_usd(pos, book)
    assert cost == round((9.03 - 9.02) * 1000.0, 4)


def test_fill_sane_spike_mark_below_fill():
    est = {
        "fill_gross": 12.0,
        "mark_unreal": 15.5,
        "book": {"bid": 9.02, "ask": 9.04, "mid": 9.03},
        "source": "book_fill_api",
    }
    pos = {
        "side": "LONG",
        "size": 1000.0,
        "unrealized_pnl": 15.5,
        "exchange_unrealized_pnl": 15.5,
    }
    assert fill_gross_sane_vs_mark(est, pos, exit_reason="SPIKE-FLASH") is True


def test_exchange_bid_profit_ok_rejects_negative_fill(monkeypatch):
    from unittest.mock import MagicMock

    from elite_trader import exchange_fill_truth as eft

    pos = {
        "symbol": "ZECUSDT",
        "side": "LONG",
        "entry_price": 555.62,
        "size": 5.5,
        "stake_usd": 304.0,
        "leverage": 10,
        "unrealized_pnl": 6.0,
        "exchange_unrealized_pnl": 6.0,
        "entry_fee": 1.2,
        "entry_fee_source": "api",
    }
    est = {
        "ok": True,
        "source": "book_fill_api",
        "fill_gross": -2.75,
        "final_pnl": -4.5,
        "net_pnl": -4.5,
        "mark_unreal": 6.0,
        "fill_price": 555.11,
        "book": {"bid": 555.11, "ask": 555.2},
    }
    monkeypatch.setattr(eft, "estimate_close_at_fill", lambda *a, **k: dict(est))
    monkeypatch.setattr(eft, "entry_fee_api_ready", lambda p: True)
    ok, detail = eft.exchange_bid_profit_ok(pos, MagicMock(), min_net=2.0)
    assert ok is False
    assert "brüt" in detail or "net" in detail


def test_mega_exchange_algo_safe_skips_flash(monkeypatch):
    from unittest.mock import MagicMock, patch

    from elite_trader import mega_live as ml

    pos = {
        "symbol": "ZECUSDT",
        "side": "LONG",
        "on_exchange": True,
        "mega_flash_reversal": True,
        "exchange_tp_order_id": "algo-1",
    }
    mc = MagicMock()
    mc.paper = False
    with patch.dict(
        "os.environ",
        {"MEGA_EXCHANGE_SKIP_FLASH_REV": "1", "MEGA_LIVE_ORDERS": "1"},
        clear=False,
    ):
        with patch.object(ml, "_cancel_exchange_tp") as ctp:
            with patch.object(ml, "_cancel_exchange_trail_lock") as clk:
                with patch.object(ml, "mega_exchange_tp_enabled", return_value=True):
                    with patch.object(
                        ml, "mega_exchange_trail_lock_enabled", return_value=True
                    ):
                        assert ml._mega_exchange_algo_safe(pos, mc) is False
        ctp.assert_called_once()
        clk.assert_called_once()
