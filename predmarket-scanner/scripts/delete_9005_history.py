#!/usr/bin/env python3
"""
9005 geçmiş verisini SİZ isteyince sil — önce arşivler.

Örnek:
  python3 scripts/delete_9005_history.py --reason "Yeni deney öncesi temiz slate"
  python3 scripts/delete_9005_history.py --list   # son silinen arşivler
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import os

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BINANCE_ELITE_PORT"] = "9005"
os.environ["PROFILE_NAME"] = "binance_elite_8300_9005"


def main() -> None:
    p = argparse.ArgumentParser(description="9005 veri silme (arşivli)")
    p.add_argument("--reason", "-r", default="", help="Silme nedeni (zorunlu silmede)")
    p.add_argument("--list", action="store_true", help="Son arşivleri listele")
    p.add_argument("--yes", action="store_true", help="Onay sormadan sil")
    args = p.parse_args()

    from elite_trader.data_archive import (
        ARCHIVE_ROOT,
        list_archives,
        wipe_9005_with_archive,
    )

    if args.list:
        archives = list_archives(limit=20)
        print(f"Manifest: {ARCHIVE_ROOT.parent / 'deleted_archives' / 'manifest.json'}")
        for a in archives:
            n = sum(
                1
                for f in a.get("files") or []
                if f.get("label") == "state_db"
            )
            ct = next(
                (
                    f.get("closed_trades_count")
                    for f in a.get("files") or []
                    if f.get("closed_trades_count") is not None
                ),
                "?",
            )
            print(
                f"\n  {a.get('archive_id')}\n"
                f"    Tarih: {a.get('deleted_at', '')[:19]}\n"
                f"    Neden: {a.get('reason')}\n"
                f"    Tetik: {a.get('trigger')} | Kapanan işlem: {ct}\n"
                f"    Klasör: {a.get('path')}"
            )
        return

    reason = (args.reason or "").strip()
    if not reason:
        print("Hata: --reason \"...\" zorunlu (deney notu yazın).")
        sys.exit(1)

    if not args.yes:
        print("Silinecek: state DB, lessons, learner registry, proposals, SL registry, postmortem")
        print(f"Neden: {reason}")
        ans = input("Onaylıyor musunuz? [y/N]: ").strip().lower()
        if ans not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return

    meta = wipe_9005_with_archive(reason=reason, trigger="user")
    print(f"  ✓ Silindi: {len(meta.get('removed_files') or [])} dosya")
    print(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
