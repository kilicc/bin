#!/usr/bin/env python3
"""Kopya/hayalet kapalı işlemleri sil — yalnızca gerçek borsa settlement kalır."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["BINANCE_ELITE_PORT"] = "9005"
os.environ["PROFILE_NAME"] = "binance_elite_8300_9005"


def main() -> None:
    p = argparse.ArgumentParser(description="9005 kopya kapalı işlem temizliği")
    p.add_argument("--reason", "-r", default="Kopya kayıt temizliği", help="Neden")
    p.add_argument("--dry-run", action="store_true", help="Silmeden say")
    p.add_argument("--yes", action="store_true", help="Onay sormadan uygula")
    args = p.parse_args()

    from elite_pro_state import load_closed
    from elite_trader.exchange_trade_truth import is_verified_exchange_trade, purge_copy_closed_trades

    rows = load_closed()
    keep = [r for r in rows if is_verified_exchange_trade(r)]
    remove = [r for r in rows if not is_verified_exchange_trade(r)]

    print(f"DB kapalı: {len(rows)}  →  tut {len(keep)}  sil {len(remove)}")
    if remove:
        by_reason: dict[str, int] = {}
        for r in remove:
            key = f"{r.get('exit_reason')}|{r.get('signal_source')}"
            by_reason[key] = by_reason.get(key, 0) + 1
        print("Silinecek gruplar:")
        for k, n in sorted(by_reason.items(), key=lambda x: -x[1])[:12]:
            print(f"  {n:3d}  {k}")

    if args.dry_run:
        print("\n(dry-run — değişiklik yok)")
        return

    if not args.yes:
        ans = input("\nOnaylıyor musunuz? [y/N]: ").strip().lower()
        if ans not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return

    out = purge_copy_closed_trades(reason=args.reason)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
