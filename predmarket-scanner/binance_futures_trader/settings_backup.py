"""Ayar değişikliği öncesi zorunlu yedek — dosya adı + tarih."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from binance_futures_trader import config as cfg

BACKUP_ROOT = cfg.ROOT / "data" / "backups" / "settings"


def backup_env_file(
    source: Path,
    *,
    label: str | None = None,
) -> Path:
    """Env dosyasını `label_YYYYMMDDTHHMMSSZ.env` adıyla yedekle."""
    if not source.is_file():
        raise FileNotFoundError(f"Yedeklenecek dosya yok: {source}")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = label or source.stem
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in base)[:80]
    dest = BACKUP_ROOT / f"{safe}_{ts}.env"
    shutil.copy2(source, dest)
    return dest


def backup_before_change(
    paths: list[Path] | None = None,
    *,
    label: str | None = None,
) -> list[Path]:
    """Birden fazla ayar dosyasını yedekle."""
    defaults = [
        cfg.ROOT / "scenarios" / "binance_futures_demo.env",
        cfg.ROOT / ".env",
    ]
    targets = paths or defaults
    out: list[Path] = []
    for i, p in enumerate(targets):
        if not p.is_file():
            continue
        lbl = f"{label}_{p.stem}" if label and len(targets) > 1 else (label or p.stem)
        out.append(backup_env_file(p, label=lbl))
    return out
