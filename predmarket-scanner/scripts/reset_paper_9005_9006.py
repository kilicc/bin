#!/usr/bin/env python3
"""9005 (berserk2) + 9006 (mega sim) paper kitaplarını arşivleyip sıfırla."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CAPITAL_9005 = 30_000.0
CAPITAL_9006 = 5_000.0


def _archive_dir(reason: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = "".join(c if c.isalnum() else "_" for c in reason.strip()[:40]).strip("_") or "reset"
    out = ROOT / "data" / "deleted_archives" / f"paper_9005_9006_{ts}_{slug}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _append_manifest(entry: dict) -> None:
    from elite_trader.data_archive import MANIFEST_PATH, _load_manifest, _save_manifest

    data = _load_manifest()
    archives = list(data.get("archives") or [])
    archives.append(entry)
    data["archives"] = archives
    _save_manifest(data)
    print(f"  ✓ manifest: {MANIFEST_PATH}")


def _archive_mode_book(mode_id: str, dest: Path, reason: str) -> dict | None:
    from elite_trader import parallel_universe_engine as pe

    st = pe._load()
    book = (st.get("universes") or {}).get(mode_id)
    if not book:
        return None
    payload = {
        "reason": reason,
        "mode_id": mode_id,
        "session_start": (st.get("starting_capital_by_mode") or {}).get(mode_id),
        "open": len(book.get("open") or []),
        "closed": len(book.get("closed") or []),
        "book": book,
    }
    path = dest / f"{mode_id}_parallel_book.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _archive_file(path: Path, dest: Path) -> bool:
    if not path.is_file():
        return False
    shutil.copy2(path, dest / path.name)
    return True


def _state_db_9005() -> Path:
    return ROOT / "data" / "binance_elite_8300_9005_state.db"


def _archive_state_closed(mode_id: str, dest: Path, reason: str) -> int:
    """9005 state DB — mod kapalı işlemlerini arşivle."""
    import sqlite3

    db = _state_db_9005()
    if not db.is_file():
        return 0
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT id, symbol, mode_id, payload FROM closed_trades WHERE mode_id = ?",
        (mode_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return 0
    payload = {
        "reason": reason,
        "mode_id": mode_id,
        "count": len(rows),
        "rows": [
            {"id": r[0], "symbol": r[1], "mode_id": r[2], "payload": r[3]} for r in rows
        ],
    }
    path = dest / f"{mode_id}_state_closed.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(rows)


def _clear_state_closed(mode_id: str) -> int:
    import sqlite3

    db = _state_db_9005()
    if not db.is_file():
        return 0
    conn = sqlite3.connect(str(db))
    n = conn.execute(
        "SELECT COUNT(*) FROM closed_trades WHERE mode_id = ?",
        (mode_id,),
    ).fetchone()[0]
    conn.execute("DELETE FROM closed_trades WHERE mode_id = ?", (mode_id,))
    conn.commit()
    conn.close()
    return int(n)


def reset_berserk2(*, capital: float, reason: str, dest: Path) -> dict:
    from elite_trader import parallel_universe_engine as pe

    db_n = _archive_state_closed("berserk2", dest, reason)
    cleared_db = _clear_state_closed("berserk2") if db_n else 0
    archived = _archive_mode_book("berserk2", dest, reason)
    out = pe.reset_mode_book("berserk2")
    pe.set_mode_session_start("berserk2", capital)
    out["archived_open"] = (archived or {}).get("open", 0)
    out["archived_closed"] = (archived or {}).get("closed", 0)
    out["archived_state_closed"] = db_n
    out["cleared_state_closed"] = cleared_db
    out["capital"] = capital
    return out


def reset_mega_9006(*, capital: float, reason: str, dest: Path) -> dict:
    os.environ["BINANCE_ELITE_PORT"] = "9006"
    from elite_trader import parallel_universe_engine as pe
    from elite_trader.mega_live import (
        _mega_closed_path,
        _mega_open_book_path,
        _mega_open_meta_path,
        _mega_session_path,
        _save_session_anchor,
        mega_instance_data_dir,
    )

    db_n = _archive_state_closed("mega", dest, reason)
    cleared_db = _clear_state_closed("mega") if db_n else 0
    archived = _archive_mode_book("mega", dest, reason)
    mega_files: list[str] = []
    for path in (
        _mega_closed_path(),
        _mega_open_book_path(),
        _mega_open_meta_path(),
        _mega_session_path(),
    ):
        if _archive_file(path, dest):
            mega_files.append(path.name)
            path.unlink(missing_ok=True)

    book_out = pe.reset_mode_book("mega")
    pe.set_mode_session_start("mega", capital)
    _save_session_anchor(capital, reason=reason)

    return {
        "mode_id": "mega",
        "instance": "9006",
        "data_dir": str(mega_instance_data_dir()),
        "archived_files": mega_files,
        "archived_open": (archived or {}).get("open", 0),
        "archived_closed": (archived or {}).get("closed", 0),
        "archived_state_closed": db_n,
        "cleared_state_closed": cleared_db,
        "cleared_open": book_out.get("cleared_open"),
        "cleared_closed": book_out.get("cleared_closed"),
        "capital": capital,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="9005/9006 paper sıfırlama (arşivli)")
    p.add_argument("--reason", "-r", required=True)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--capital-9005", type=float, default=CAPITAL_9005)
    p.add_argument("--capital-9006", type=float, default=CAPITAL_9006)
    args = p.parse_args()
    reason = args.reason.strip()
    if not args.yes:
        ans = input(
            "9005 berserk2 + 9006 mega paper açık/kapalı silinecek. Onay? [y/N]: "
        )
        if ans.strip().lower() not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return

    dest = _archive_dir(reason)
    print(f"Arşiv: {dest}")

    berserk2 = reset_berserk2(capital=args.capital_9005, reason=reason, dest=dest)
    mega = reset_mega_9006(capital=args.capital_9006, reason=reason, dest=dest)

    _append_manifest(
        {
            "archive_id": dest.name,
            "ports": [9005, 9006],
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "trigger": "reset_paper_9005_9006",
            "path": str(dest.relative_to(ROOT)),
            "berserk2": berserk2,
            "mega_9006": mega,
        }
    )

    out = {"ok": True, "reason": reason, "archive": str(dest), "berserk2": berserk2, "mega_9006": mega}
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
