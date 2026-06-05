#!/usr/bin/env python3
"""MEGA paper/canlı oturum geçmişini sıfırla — bakiye çapası API'den alınır."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BINANCE_ELITE_PORT", "9005")
os.environ.setdefault("PROFILE_NAME", "binance_elite_8300_9005")

# Senaryo env
scenario = ROOT / "scenarios" / "binance_elite_8300_9005.env"
if scenario.is_file():
    for line in scenario.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            os.environ[k] = v

env_file = ROOT / ".env"
if env_file.is_file():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k.startswith("MEGA_") or k in ("BINANCE_LIVE_ORDERS",):
            os.environ[k] = v


def _archive_mega_book(reason: str) -> Path | None:
    from elite_trader import parallel_universe_engine as pe

    st = pe._load()
    mega = st.get("universes", {}).get("mega")
    if not mega:
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "data" / "deleted_archives" / f"mega_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "mega_parallel_book.json"
    path.write_text(
        json.dumps({"reason": reason, "mega": mega}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    p = argparse.ArgumentParser(description="MEGA geçmişini sıfırla (arşivli)")
    p.add_argument("--reason", "-r", required=True, help="Sıfırlama nedeni")
    p.add_argument("--yes", action="store_true", help="Onay sormadan")
    p.add_argument("--no-api", action="store_true", help="API çağrısı yapma (sadece yerel sıfırla)")
    args = p.parse_args()
    reason = args.reason.strip()
    if not args.yes:
        ans = input("MEGA paper kitabı + oturum kayıtları silinecek. Onay? [y/N]: ")
        if ans.strip().lower() not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return

    archived = _archive_mega_book(reason)
    if archived:
        print(f"  ✓ Arşiv: {archived}")

    from elite_trader.mega_live import reset_mega_history

    out = reset_mega_history(reason=reason, fetch_wallet=not args.no_api)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
