"""mega_star_sl — yıldızlı coin −25% brüt."""
from __future__ import annotations

import os
from unittest.mock import patch

from elite_trader.mega_star_sl import (
    evaluate_berserk_star_sl,
    evaluate_star_sl,
    loss_floor_usd,
)


def test_loss_floor():
    assert loss_floor_usd(1000) == -250.0


def test_star_sl_no_star_no_exit():
    pos = {"symbol": "BTC", "stake_usd": 1000, "side": "LONG", "unrealized_pnl": -300}
    with patch.dict(os.environ, {"MEGA_STAR_SL_ENABLED": "1"}, clear=False):
        with patch("elite_trader.mega_coin_watch.is_starred", return_value=False):
            assert evaluate_star_sl(pos) is None


def test_star_sl_below_floor_btc_close():
    pos = {
        "symbol": "ETH",
        "stake_usd": 1000,
        "side": "LONG",
        "unrealized_pnl": -280,
    }
    with patch.dict(os.environ, {"MEGA_STAR_SL_ENABLED": "1"}, clear=False):
        with patch("elite_trader.mega_coin_watch.is_starred", return_value=True):
            with patch(
                "elite_trader.mega_star_sl._btc_recovery_ok",
                return_value=(False, "btc_trend_down"),
            ):
                with patch(
                    "elite_trader.mega_star_sl._gross_unreal",
                    return_value=-280.0,
                ):
                    reason = evaluate_star_sl(pos)
                    assert reason == "SL-COIN25-BTC"
                    assert pos.get("mega_sl_review") is True


def test_berserk_star_sl_recovery_hold():
    with patch.dict(os.environ, {"MEGA_STAR_SL_ENABLED": "1"}, clear=False):
        with patch("elite_trader.mega_coin_watch.is_starred", return_value=True):
            with patch(
                "elite_trader.mega_star_sl._btc_recovery_ok",
                return_value=(True, "btc_recovery_long"),
            ):
                assert (
                    evaluate_berserk_star_sl(
                        unrealized_usd=-260,
                        stake_usd=1000,
                        side="LONG",
                        symbol="SOL",
                    )
                    is None
                )
