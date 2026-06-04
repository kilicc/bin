"""Data lake erişim kuralları."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader.data_lake.access import can_query_mode


def test_evrim_reads_all():
    for mid in ("berserk", "hunter", "chop_master", "sentinel", "evrim"):
        assert can_query_mode("evrim", mid)


def test_paper_modes_own_only():
    assert can_query_mode("berserk", "berserk")
    assert not can_query_mode("berserk", "hunter")
    assert not can_query_mode("hunter", "chop_master")
