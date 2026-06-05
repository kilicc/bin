#!/usr/bin/env python3
"""EXCHANGE-SYNC / SYNC-EXCHANGE kapalı kayıtlarını sil (berserk2 DB + parallel + MEGA)."""
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
    p = argparse.ArgumentParser(description="9005 EXCHANGE-SYNC kapalı işlem temizliği")
    p.add_argument("--reason", "-r", default="EXCHANGE-SYNC temizliği", help="Neden")
    p.add_argument("--dry-run", action="store_true", help="Silmeden say")
    p.add_argument("--yes", action="store_true", help="Onay sormadan uygula")
    args = p.parse_args()

    from elite_pro_state import load_closed
    from elite_trader.exchange_trade_truth import (
        is_exchange_sync_close,
        purge_exchange_sync_closed_trades,
    )
    from elite_trader.parallel_universe_engine import _load as _pu_load

    rows = load_closed()
    db_remove = [r for r in rows if is_exchange_sync_close(r)]
    pu_remove = 0
    st = _pu_load()
    for mid, book in (st.get("universes") or {}).items():
        closed = book.get("closed") or []
        pu_remove += sum(1 for c in closed if is_exchange_sync_close(c))

    mega_remove = 0
    for rel in ("mega_live_closed.json", "mega_9007/mega_live_closed.json"):
        path = ROOT / "data" / rel
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        mega_remove += sum(
            1 for c in (data.get("closed") or []) if is_exchange_sync_close(c)
        )

    print(
        f"Silinecek: DB={len(db_remove)} parallel={pu_remove} mega={mega_remove}"
    )
    for r in db_remove:
        print(f"  DB #{r.get('id')} {r.get('symbol')} {r.get('exit_reason')}")

    if args.dry_run:
        print("\n(dry-run — değişiklik yok)")
        return

    if not args.yes and (db_remove or pu_remove or mega_remove):
        ans = input("\nOnaylıyor musunuz? [y/N]: ").strip().lower()
        if ans not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return

    out = purge_exchange_sync_closed_trades(reason=args.reason)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
