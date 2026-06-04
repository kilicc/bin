#!/usr/bin/env python3
"""Son silinen 9005 arşivlerini listele (geri dönüş için)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elite_trader.data_archive import MANIFEST_PATH, list_archives


def main() -> None:
    print(f"Manifest: {MANIFEST_PATH}\n")
    for a in list_archives(limit=25):
        ct = next(
            (
                f.get("closed_trades_count")
                for f in a.get("files") or []
                if "closed_trades_count" in f
            ),
            "-",
        )
        print(f"{a.get('archive_id')}")
        print(f"  {a.get('deleted_at', '')[:19]} | {a.get('reason')}")
        print(f"  işlem: {ct} | {a.get('path')}\n")


if __name__ == "__main__":
    main()
