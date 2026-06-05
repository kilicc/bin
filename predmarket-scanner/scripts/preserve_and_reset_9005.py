#!/usr/bin/env python3
"""
Öğrenme verisini kaydet → tüm mod işlemlerini sil → sıfırdan başla.

  python3 scripts/preserve_and_reset_9005.py -r "Yeni deney" --yes
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BINANCE_ELITE_PORT"] = "9005"
os.environ["PROFILE_NAME"] = "binance_elite_8300_9005"


def main() -> None:
    p = argparse.ArgumentParser(description="Öğrenme kaydı + tüm mod sıfırlama")
    p.add_argument("--reason", "-r", required=True, help="Deney notu")
    p.add_argument("--yes", action="store_true", help="Onaysız çalıştır")
    args = p.parse_args()
    reason = (args.reason or "").strip()
    if not reason:
        print("Hata: --reason zorunlu")
        sys.exit(1)

    if not args.yes:
        print("1) Öğrenme paketi (Evrim master + tüm kapanışlar)")
        print("2) Tüm mod kitapları arşiv + sıfır")
        print("3) 9005 state DB + lessons sil (arşivli)")
        print(f"Neden: {reason}")
        ans = input("Onaylıyor musunuz? [y/N]: ").strip().lower()
        if ans not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return

    from elite_trader.learning_preservation import (
        export_learning_snapshot,
        reset_all_mode_books,
    )
    from elite_trader.data_archive import wipe_9005_with_archive

    print("━━━ 1/3 Öğrenme kaydı ━━━")
    export_learning_snapshot(reason=reason)

    print("━━━ 2/3 Mod kitapları sıfır ━━━")
    reset_all_mode_books(reason=reason)

    print("━━━ 3/3 9005 geçmiş sil (arşivli) ━━━")
    meta = wipe_9005_with_archive(reason=reason, trigger="preserve_reset")
    print(f"  ✓ Tamamlandı — arşiv: {meta.get('archive_id') or meta.get('path')}")


if __name__ == "__main__":
    main()
