"""mega_coin_watch — behavior playbook from starred trades."""
from __future__ import annotations

import time

from elite_trader.mega_coin_rank import _build_behavior_playbook
from elite_trader.mega_coin_watch import apply_star_entry_hints


def test_playbook_prefers_winning_side():
    trades = [
        {
            "side": "LONG",
            "stake_usd": 1000,
            "wallet_pnl": 40,
            "exit_reason": "SPIKE-FLASH",
            "duration": 120,
            "entry_context": {"btc": {"regime": "trend_up"}},
        },
        {
            "side": "LONG",
            "stake_usd": 1000,
            "wallet_pnl": 30,
            "exit_reason": "TP",
            "duration": 90,
        },
        {
            "side": "SHORT",
            "stake_usd": 1000,
            "wallet_pnl": -10,
            "exit_reason": "SL",
        },
    ]
    pb = _build_behavior_playbook(trades, {"profit_yield": 0.06, "win_rate_pct": 66.7})
    assert pb["preferred_side"] == "LONG"
    assert pb["expects_spike_or_flash_exit"] is True
    assert pb["btc_regime_when_winning"] == "trend_up"


def test_star_aligned_lowers_score_threshold():
    import os
    from unittest.mock import patch

    reg = {
        "symbols": {
            "NEARUSDT": {
                "starred": True,
                "starred_until": time.time() + 3600,
                "boost_rules": [],
                "behavior_playbook": {
                    "preferred_side": "LONG",
                    "preferred_side_share": 0.8,
                    "flash_share": 0.5,
                    "expects_spike_or_flash_exit": True,
                    "typical_exit": "SPIKE-FLASH",
                },
            }
        }
    }
    with patch(
        "elite_trader.mega_coin_watch.load_registry",
        return_value=reg,
    ):
        with patch.dict(os.environ, {"MEGA_STAR_ALIGNED_SCORE_BONUS": "4"}, clear=False):
            h = apply_star_entry_hints(
                "NEARUSDT",
                "LONG",
                {"type": "LONG", "mega_flash_reversal": True},
            )
    assert h["starred"] is True
    assert "aligned" in h["alignment"]
    assert h["min_score_delta"] < 0
    assert h["open_behavior"].get("profitable_coin") is True
