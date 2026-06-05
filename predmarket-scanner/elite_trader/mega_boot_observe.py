"""MEGA — yeniden başlatma sonrası gözlem penceresi (giriş yok, tarama devam)."""
from __future__ import annotations

import os
import time
from typing import Any

_process_boot_at = time.time()


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def boot_observe_enabled() -> bool:
    return _env_bool("MEGA_BOOT_OBSERVE", True)


def boot_observe_sec() -> float:
    return max(0.0, _env_float("MEGA_BOOT_OBSERVE_SEC", 60.0))


def boot_elapsed_sec() -> float:
    return max(0.0, time.time() - _process_boot_at)


def boot_observe_active() -> bool:
    if not boot_observe_enabled():
        return False
    return boot_elapsed_sec() < boot_observe_sec()


def boot_observe_remaining_sec() -> float:
    if not boot_observe_active():
        return 0.0
    return max(0.0, boot_observe_sec() - boot_elapsed_sec())


def reset_boot_clock() -> None:
    """Veri sıfırlama / kontrol restart — gözlem penceresini yeniden başlat."""
    global _process_boot_at
    _process_boot_at = time.time()


def boot_entry_block_reason() -> str:
    if not boot_observe_active():
        return ""
    rem = boot_observe_remaining_sec()
    m = int(rem // 60)
    s = int(rem % 60)
    total = int(boot_observe_sec())
    return (
        f"Başlangıç gözlemi {m}:{s:02d} kaldı — ilk {total // 60} dk tarama/analiz; "
        f"giriş kapalı (BTC/makro/rejim)."
    )


def snapshot() -> dict[str, Any]:
    total = boot_observe_sec()
    rem = boot_observe_remaining_sec()
    active = boot_observe_active()
    return {
        "enabled": boot_observe_enabled(),
        "active": active,
        "observe_sec": total,
        "elapsed_sec": round(boot_elapsed_sec(), 1),
        "remaining_sec": round(rem, 1),
        "entries_allowed": not active,
        "label": (
            f"gözlem {int(rem // 60)}:{int(rem % 60):02d}"
            if active
            else "scalp hazır"
        ),
    }
