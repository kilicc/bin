#!/usr/bin/env python3
"""9006 — borsada açık yokken yerel MEGA açık kitabı temizle (hayalet panel satırları)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("BINANCE_ELITE_PORT", "9006")
os.environ.setdefault("MEGA_INSTANCE_ID", "9006")
_scenario = _ROOT / "scenarios" / "binance_elite_mega_9006_mainnet.env"
if _scenario.is_file():
    for line in _scenario.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

_secrets = _ROOT / "scenarios" / ".env.mega_9006"
if _secrets.is_file():
    try:
        from dotenv import load_dotenv

        load_dotenv(_secrets, override=True)
    except ImportError:
        pass


def _clear_open_file(path: Path) -> int:
    if not path.is_file():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = list(data.get("open") or [])
    n = len(rows)
    if n == 0:
        return 0
    backup = path.with_suffix(f".json.bak.{int(datetime.now(timezone.utc).timestamp())}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    data["open"] = []
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  backup: {backup.name}")
    print(f"  cleared {n} rows from {path.name}")
    return n


def main() -> int:
    from elite_trader.mega_live import (
        mega_instance_data_dir,
        prune_ghost_open_positions,
        panel_exchange_sync,
    )

    open_path = mega_instance_data_dir() / "mega_live_open.json"
    disk_n = _clear_open_file(open_path)
    try:
        pruned = prune_ghost_open_positions(force=True)
    except Exception as exc:
        print(f"  prune_ghost (runtime): {exc}")
        pruned = disk_n
    else:
        pruned = max(pruned, disk_n)
    sync = panel_exchange_sync(force=True)
    print(f"  pruned={pruned} book_n={sync.get('book_n')} exchange_n={sync.get('exchange_n')}")
    return 0 if int(sync.get("book_n") or 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
