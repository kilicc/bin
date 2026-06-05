"""Motor değişimi — borsa senkron, oturum bakiyesi sıfır, profilden devam."""
from __future__ import annotations

from typing import Any

from elite_trader.mode_profiles import get_profile
# live_mode_id deprecated


def restart_motor_session(
    old: str,
    new: str,
    *,
    positions: list[dict[str, Any]],
    closed_positions: list[dict[str, Any]],
    motor_signals: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    close_exchange_fn,
    sync_exchange_fn,
) -> dict[str, Any]:
    """
    Motor mod değişince:
    - Borsadaki açık pozisyonları kapat
    - Motor mod kitabında açıkları temizle, bakiyeyi profil starting_balance'a al
    - Ana Hat DB'ye dokunma (wipe_db=False)
    """
    from elite_trader.parallel_universe_engine import reset_mode_session

    out: dict[str, Any] = {"old": old, "new": new}
    exchange_out = None
    if close_exchange_fn:
        try:
            exchange_out = close_exchange_fn()
            out["exchange"] = exchange_out
        except Exception as exc:
            out["exchange_error"] = str(exc)

    motor_signals.clear()
    signals.clear()
    positions.clear()
    closed_positions.clear()

    prof = get_profile(new) or {}
    start = float(prof.get("starting_balance") or 5000.0)
    book_out = reset_mode_session(
        new,
        session_start=start,
        clear_closed=True,
    )
    out["book"] = book_out
    out["keep_db"] = False

    if sync_exchange_fn:
        try:
            sync_exchange_fn()
            out["synced"] = True
        except Exception as exc:
            out["sync_error"] = str(exc)

    out["session_start"] = start
    return out
