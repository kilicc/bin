#!/usr/bin/env python3
"""Ingest current system artifacts into lab RAG (lessons, proposals, checkpoints)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> int:
    p = argparse.ArgumentParser(description="Bootstrap lab knowledge from system files")
    p.add_argument("--force", action="store_true", help="Re-ingest even if already done")
    p.add_argument("--json", action="store_true", help="Print JSON result")
    args = p.parse_args()

    from elite_trader.training_lab.lab_knowledge import bootstrap_system_knowledge

    result = bootstrap_system_knowledge(force=args.force)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result.get("skipped"):
            print(f"Skipped (already bootstrapped at {result.get('ts')})")
        else:
            written = result.get("written") or []
            print(f"OK — {len(written)} documents:")
            for name in written:
                print(f"  - {name}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
