#!/usr/bin/env python3
"""MEGA 24h coin rank — manuel çalıştırma / bootstrap."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description="MEGA 24h coin rank")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--no-registry", action="store_true")
    args = ap.parse_args()
    from elite_trader.mega_coin_rank import emit_rank, format_telegram_rank

    report = emit_rank(
        window_hours=args.hours,
        write_registry=not args.no_registry,
    )
    print(format_telegram_rank(report))
    if not args.no_telegram:
        try:
            from elite_trader.telegram_notify import send_telegram_message

            send_telegram_message(format_telegram_rank(report))
        except Exception as exc:
            print(f"telegram skip: {exc}")
    print(f"written: {report.get('symbol_count', 0)} symbols, stars={report.get('stars')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
