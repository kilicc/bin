"""MEGA tepe yakalama — TP gelene kadar TP-PEAK, tam TP'de TP."""
from __future__ import annotations

import os
from unittest.mock import patch

from elite_trader.mega_live import (
    _mega_peak_capture_close_reason,
    _mega_peak_capture_until_tp_enabled,
)


def test_peak_capture_disabled_by_default_without_env():
    with patch.dict(os.environ, {"MEGA_PEAK_CAPTURE_UNTIL_TP": "0"}, clear=False):
        assert not _mega_peak_capture_until_tp_enabled()
        assert (
            _mega_peak_capture_close_reason(
                {"tp_net_target_usd": 40, "max_unreal_seen": 30, "unrealized_pnl": 28},
                stake=1000,
                lev=10,
                mc=None,
                tp_g=45.0,
            )
            is None
        )


def test_peak_capture_tp_peak_on_retrace():
    pos = {
        "tp_net_target_usd": 40.0,
        "max_unreal_seen": 28.0,
        "unrealized_pnl": 26.0,
        "max_net_seen": 22.0,
        "stake_usd": 1000,
        "leverage": 10,
    }
    env = {
        "MEGA_PEAK_CAPTURE_UNTIL_TP": "1",
        "MEGA_PEAK_TRAIL_ARM_GROSS": "1.5",
        "MEGA_PEAK_TRAIL_RETRACE_FRAC": "0.97",
        "MEGA_PEAK_TP_TAKE_FRAC": "1.0",
    }
    with patch.dict(os.environ, env, clear=False):
        reason = _mega_peak_capture_close_reason(
            pos, stake=1000, lev=10, mc=None, tp_g=50.0
        )
        assert reason == "TP-PEAK"


def test_peak_capture_full_tp():
    pos = {
        "tp_net_target_usd": 40.0,
        "max_unreal_seen": 48.0,
        "unrealized_pnl": 47.0,
        "max_net_seen": 42.0,
        "stake_usd": 1000,
        "leverage": 10,
    }
    env = {
        "MEGA_PEAK_CAPTURE_UNTIL_TP": "1",
        "MEGA_PEAK_TP_TAKE_FRAC": "1.0",
    }
    with patch.dict(os.environ, env, clear=False):
        reason = _mega_peak_capture_close_reason(
            pos, stake=1000, lev=10, mc=None, tp_g=45.0
        )
        assert reason == "TP"
