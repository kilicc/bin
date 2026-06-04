#!/usr/bin/env python3
"""Kapalı MEGA satırını arşivleyip mega_live_closed.json'dan çıkar."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--instance", default=os.getenv("MEGA_INSTANCE_ID", "9006"))
    p.add_argument("--position-id", type=int, action="append", dest="position_ids")
    p.add_argument("--symbol", action="append", dest="symbols")
    p.add_argument("--reason", required=True)
    args = p.parse_args()
    os.environ["MEGA_INSTANCE_ID"] = str(args.instance)
    from elite_trader import mega_live as ml

    ml.mega_instance_id()
    out = ml._remove_mega_closed_records(
        position_ids=args.position_ids or None,
        symbols=args.symbols or None,
        reason=args.reason,
    )
    print(out)
    return 0 if int(out.get("removed") or 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
