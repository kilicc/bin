"""Data lake erişim — evrim tüm modları okur; diğerleri yalnız kendi."""
from __future__ import annotations

from elite_trader.mode_registry import can_read_mode_data, resolve_mode_id


def can_query_mode(reader_id: str, target_mode_id: str) -> bool:
    return can_read_mode_data(reader_id, target_mode_id)


def assert_can_query(reader_id: str, target_mode_id: str) -> None:
    if not can_query_mode(reader_id, target_mode_id):
        raise PermissionError(
            f"{resolve_mode_id(reader_id)} cannot read {resolve_mode_id(target_mode_id)}"
        )
