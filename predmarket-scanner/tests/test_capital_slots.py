"""capital_slots — tam marjin $1000 / küçük cüzdan $100–700."""
from __future__ import annotations

import os
from unittest.mock import patch

from elite_trader.capital_slots import (
    effective_max_open,
    plan_stake,
    stake_policy_label,
    wallet_full_balance_mode,
)


def test_large_wallet_slots():
    with patch.dict(
        os.environ,
        {
            "MEGA_WALLET_FULL_BALANCE": "1",
            "MEGA_SLOT_UNIT_USD": "1000",
            "MEGA_SMALL_WALLET_THRESHOLD_USD": "1000",
            "MEGA_MAX_OPEN_HARD_CAP": "50",
        },
        clear=False,
    ):
        n = effective_max_open(5000, profile_cap=4, mode_id="mega")
        assert n == 5
        stake = plan_stake(3000, 2, mode_id="mega", max_open=3, profile_cap=4)
        assert stake == 1000.0
        assert stake_policy_label(5000, "mega") == "$1000"


def test_zero_deployable_max_open():
    with patch.dict(
        os.environ, {"MEGA_WALLET_FULL_BALANCE": "1", "MEGA_MAX_OPEN_HARD_CAP": "50"},
        clear=False,
    ):
        assert effective_max_open(0, profile_cap=4, mode_id="mega") == 0


def test_small_wallet_stake_clamp():
    with patch.dict(
        os.environ,
        {
            "MEGA_WALLET_FULL_BALANCE": "1",
            "MEGA_SLOT_UNIT_USD": "1000",
            "MEGA_SMALL_WALLET_THRESHOLD_USD": "1000",
            "MEGA_SMALL_STAKE_MIN_USD": "100",
            "MEGA_SMALL_STAKE_MAX_USD": "700",
        },
        clear=False,
    ):
        assert effective_max_open(800, profile_cap=4, mode_id="mega") == 1
        stake = plan_stake(450, 0, mode_id="mega", max_open=1, profile_cap=4)
        assert 100 <= stake <= 700
        assert stake_policy_label(450, "mega") == "$100–$700"
        flash = plan_stake(
            600,
            0,
            mode_id="mega",
            max_open=1,
            profile_cap=4,
            is_flash=True,
            flash_min=100,
            flash_max=700,
        )
        assert 100 <= flash <= 700


def test_wallet_full_mode_default_on():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MEGA_WALLET_FULL_BALANCE", None)
        assert wallet_full_balance_mode("mega") is True


def test_equity_budget_more_slots_than_avail_only():
    """$2488 avail + $2430 bağlı → bütçe ~$4900 → 4 slot (2 değil)."""
    with patch.dict(
        os.environ,
        {
            "MEGA_WALLET_FULL_BALANCE": "1",
            "MEGA_SLOT_UNIT_USD": "1000",
            "MEGA_MAX_OPEN_HARD_CAP": "50",
        },
        clear=False,
    ):
        budget = 2488 + 2430 - 30
        assert effective_max_open(budget, profile_cap=50, mode_id="mega") == 4
        assert effective_max_open(2488, profile_cap=50, mode_id="mega") == 2


def test_wallet_cap_from_total_margin_not_leftover():
    """$2487 toplam → 2 slot; kalan $28 ile ek slot sayılmamalı."""
    with patch.dict(
        os.environ,
        {
            "MEGA_WALLET_FULL_BALANCE": "1",
            "MEGA_SLOT_UNIT_USD": "1000",
            "MEGA_MAX_OPEN_HARD_CAP": "50",
        },
        clear=False,
    ):
        assert effective_max_open(2457, profile_cap=50, mode_id="mega") == 2
        assert effective_max_open(28, profile_cap=50, mode_id="mega") == 0
