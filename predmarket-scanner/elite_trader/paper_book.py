"""Paper kitap (9005/9006) — canlı cüzdan olmadan sermaye ve stake."""
from __future__ import annotations

import os

from elite_trader.mode_registry import berserk2_paper_only, resolve_mode_id


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def mega_paper_sim_book() -> bool:
    try:
        from elite_trader.mega_live import mega_paper_sim_only

        return mega_paper_sim_only()
    except Exception:
        return False


def paper_book_equity_floor(mode_id: str | None = None) -> float:
    """REST cüzdan yokken paper stake hesabı için taban sermaye."""
    mid = resolve_mode_id(mode_id or "berserk2")
    if mid == "berserk2" or berserk2_paper_only():
        return max(
            1000.0,
            _env_float(
                "BERSERK2_PAPER_EQUITY_USD",
                _env_float("STARTING_BALANCE", 30_000.0),
            ),
        )
    if mid == "mega" or mega_paper_sim_book():
        return max(
            1000.0,
            _env_float(
                "MEGA_SIM_EQUITY_USD",
                _env_float("STARTING_BALANCE", 10_000.0),
            ),
        )
    return max(1000.0, _env_float("STARTING_BALANCE", 5000.0))


def effective_paper_equity(
    book_equity: float,
    mode_id: str | None = None,
) -> float:
    floor = paper_book_equity_floor(mode_id)
    if book_equity >= floor * 0.25:
        return book_equity
    return floor


def berserk2_paper_fallback_stake(
    *,
    min_stake: float,
    max_stake: float,
    open_count: int,
    max_open: int,
) -> float | None:
    """Kelly/allocator stake=0 iken paper berserk2 sabit stake."""
    if not berserk2_paper_only() or open_count >= max_open:
        return None
    fixed = _env_float("BERSERK2_PAPER_FIXED_STAKE_USD", 0)
    if fixed <= 0:
        fixed = _env_float("BERSERK2_FIXED_STAKE_USD", 0)
    if fixed > 0:
        return min(fixed, max_stake) if max_stake < float("inf") else fixed
    if min_stake > 0:
        return min_stake
    return None
