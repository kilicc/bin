#!/usr/bin/env python3
"""9006 — yalnızca kapalı işlem defteri (arşiv + panel/RAM temiz; açık pozisyon/borsa dokunmaz)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    os.environ.setdefault("BINANCE_ELITE_PORT", "9006")
    os.environ.setdefault("MEGA_INSTANCE_ID", "9006")
    for name in (
        "scenarios/binance_elite_mega_9006_mainnet.env",
        "scenarios/.env.mega_9006",
        ".env",
    ):
        p = ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    p = argparse.ArgumentParser(description="MEGA kapalı işlem kayıtlarını arşivle ve sil")
    p.add_argument("--reason", "-r", required=True)
    p.add_argument("--yes", action="store_true")
    args = p.parse_args()
    if not args.yes:
        ans = input("Kapalı işlem tablosu arşivlenip silinecek. [y/N]: ")
        if ans.strip().lower() not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return 1

    _load_env()
    from elite_trader.mega_live import (
        _mega_closed_path,
        clear_mega_closed_records,
        mega_instance_data_dir,
        suppress_mega_closed_backfill,
    )
    import elite_trader.mega_live as ml

    ml._ensure_mega_closed_loaded()
    n_before = len(ml._mega_closed)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = ROOT / "data" / "deleted_archives" / f"mega_9006_closed_{ts}"
    archive.mkdir(parents=True, exist_ok=True)
    closed_path = _mega_closed_path()
    copied: list[str] = []
    if closed_path.is_file():
        dest = archive / closed_path.name
        shutil.copy2(closed_path, dest)
        copied.append(dest.name)
    inst = mega_instance_data_dir()
    hist = inst / "mega_live_closed_history.json"
    if hist.is_file():
        shutil.copy2(hist, archive / hist.name)
        copied.append(hist.name)
        hist.unlink(missing_ok=True)

    from elite_trader.mega_live import touch_closed_panel_epoch

    cleared = clear_mega_closed_records(suppress_backfill=True)
    suppress_mega_closed_backfill()
    touch_closed_panel_epoch(reason=args.reason)
    ml._mega_closed = []
    ml._mega_closed_loaded = True
    ml._mega_closed_ui_cache = None

    try:
        from elite_trader import parallel_universe_engine as pe

        st = pe._load()
        mega = (st.get("universes") or {}).get("mega")
        if isinstance(mega, dict) and mega.get("closed"):
            shutil.copy2(
                ROOT / "data" / "parallel_universes.json",
                archive / "parallel_universes_before.json",
            )
            mega["closed"] = []
            pe._save(st)
            copied.append("parallel_universes_mega_closed_cleared")
    except Exception:
        pass

    manifest = {
        "ok": True,
        "reason": args.reason[:200],
        "ts": ts,
        "instance": "9006",
        "rows_before": n_before,
        "cleared_closed": cleared,
        "copied": copied,
        "archive": str(archive.relative_to(ROOT)),
    }
    (archive / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        from elite_trader.data_archive import _load_manifest, _save_manifest

        data = _load_manifest()
        archives = list(data.get("archives") or [])
        archives.append(
            {
                "archive_id": archive.name,
                "port": 9006,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "reason": args.reason,
                "path": str(archive.relative_to(ROOT)),
                "cleared_closed": cleared,
            }
        )
        data["archives"] = archives
        _save_manifest(data)
    except Exception:
        pass

    print("OK — arşiv:", archive)
    print("  silinen kayıt:", cleared, "(bellek öncesi:", n_before, ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
