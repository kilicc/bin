#!/usr/bin/env python3
"""MEGA P1 sistem skor kartı — stdout / JSON / Telegram."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--instance", default=os.getenv("MEGA_INSTANCE_ID", "9006"))
    p.add_argument("--hours", type=float, default=24.0)
    p.add_argument("--telegram", action="store_true")
    p.add_argument("--no-telegram", action="store_true")
    p.add_argument("--json-only", action="store_true")
    args = p.parse_args()
    os.environ["MEGA_INSTANCE_ID"] = str(args.instance)

    from elite_trader.mega_system_report import emit_report, format_telegram

    tg = None
    if args.telegram:
        tg = True
    if args.no_telegram:
        tg = False
    report = emit_report(telegram=tg, window_hours=args.hours)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_telegram(report))
        print("\n--- JSON → data/mega_*/mega_system_report_latest.json ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
