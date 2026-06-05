#!/usr/bin/env python3
"""MEGA panel — seçili TR günü için kapalı işlem sayısını doğrula (disk + borsa)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader import mega_live as ml  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="MEGA panel gün özeti")
    p.add_argument("--from", dest="from_date", required=True, help="TR YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", default=None, help="TR YYYY-MM-DD")
    p.add_argument("--no-exchange", action="store_true", help="userTrades tamamlama kapalı")
    args = p.parse_args()
    to = args.to_date or args.from_date
    if args.no_exchange:
        import os

        os.environ["MEGA_PANEL_HISTORY_EXCHANGE"] = "0"
    disk = ml._load_mega_closed_panel_rows(limit=10000)
    disk_f = ml._filter_closed_tr_date_range(
        disk, from_tr=args.from_date, to_tr=to
    )
    payload = ml.mega_closed_history_payload(
        from_date=args.from_date, to_date=to, limit=10000
    )
    print(f"TR aralık: {args.from_date} → {to}")
    print(f"Disk only: {len(disk_f)} kapanış")
    s = payload.get("summary") or {}
    print(
        f"Panel (disk+audit+exchange): {payload.get('count')} kapanış, "
        f"net {s.get('net_pnl')} USD, "
        f"borsa ek {payload.get('exchange_backfill_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
