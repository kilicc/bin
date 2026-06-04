#!/usr/bin/env python3
"""Paper DB özet raporu: açık pozisyon temaları + son N gün kapanışlar.

Çalıştır:  python paper_insight.py
İsteğe bağlı .env: INSIGHT_CLOSED_DAYS=7  INSIGHT_CLOSED_LIMIT=80
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import momentum_scanner as ms  # noqa: E402
import self_improver as si  # noqa: E402


def main() -> None:
    conn = ms.init_db(ms.DB_PATH)
    try:
        days = int(os.getenv("INSIGHT_CLOSED_DAYS", "7"))
    except ValueError:
        days = 7
    try:
        limit = int(os.getenv("INSIGHT_CLOSED_LIMIT", "80"))
    except ValueError:
        limit = 80
    force = os.getenv("LEARN_REBUILD", "0").strip().lower() in ("1", "true", "yes")
    si.audit_all_trades(conn, force_relearn=force)
    si.print_open_positions_digest(conn)
    si.print_recent_closed_digest(conn, days=days, limit=limit)


if __name__ == "__main__":
    main()
