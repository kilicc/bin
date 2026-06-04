#!/usr/bin/env python3
"""Evrim karar logu özeti — data/evrim_decision_log.jsonl"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from elite_trader.evrim_decision_log import aggregate_stats, read_recent


def main() -> None:
    stats = aggregate_stats(2000)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    recent = read_recent(10)
    if recent:
        print("\nSon 10 karar:")
        for r in recent:
            sym = r.get("symbol", "?")
            sc = r.get("total_score", 0)
            if r.get("entered"):
                print(f"  ✓ {sym} skor={sc} tier={r.get('tier')}")
            else:
                print(f"  ✗ {sym} skor={sc} — {r.get('reason_skip', '')[:50]}")


if __name__ == "__main__":
    main()
