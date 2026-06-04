#!/usr/bin/env python3
"""MEGA kapalı işlemleri Binance userTrades ile hizala — hayalet kayıt sil."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> None:
    p = argparse.ArgumentParser(description="MEGA kapalı tablo ↔ Binance reconcile")
    p.add_argument(
        "--instance",
        default=os.getenv("MEGA_INSTANCE_ID", "9007"),
        help="9006 veya 9007",
    )
    p.add_argument("--force", action="store_true", help="Rate limit atla")
    args = p.parse_args()

    os.environ["MEGA_INSTANCE_ID"] = str(args.instance)
    os.environ["BINANCE_ELITE_PORT"] = str(args.instance)

    from elite_trader import mega_live as ml

    ml._mega_client = None
    out = ml.reconcile_mega_closed_with_exchange(force=True)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
