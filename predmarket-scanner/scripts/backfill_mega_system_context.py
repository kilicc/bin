#!/usr/bin/env python3
"""Kapalı MEGA işlemlerine retro entry_context / exit_context + isteğe bağlı audit."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    p = argparse.ArgumentParser(description="MEGA P0 retro system context backfill")
    p.add_argument("--instance", default=os.getenv("MEGA_INSTANCE_ID", "9006"))
    p.add_argument("--data-dir", default="", help="varsayılan data/mega_{instance}")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="mevcut context üzerine yaz")
    p.add_argument("--include-archives", action="store_true", help="deleted_archives kapalıları birleştir")
    p.add_argument(
        "--consolidate-out",
        default="",
        help="tüm unique kapalı işlemler (archives dahil) — P2 veri seti",
    )
    p.add_argument("--audit", action="store_true", help="mega_close_audit.jsonl system_context")
    p.add_argument("--audit-only", action="store_true")
    args = p.parse_args()

    os.environ.setdefault("MEGA_INSTANCE_ID", str(args.instance))
    from pathlib import Path

    from elite_trader.mega_live import mega_instance_data_dir
    from elite_trader.mega_system_context_backfill import (
        backfill_audit_file,
        enrich_closed_row,
        find_archive_closed_files,
        load_audit_index,
        load_closed_payload,
        merge_closed_unique,
        save_closed_payload,
    )

    data_dir = Path(args.data_dir) if args.data_dir else mega_instance_data_dir()
    closed_path = data_dir / "mega_live_closed.json"
    audit_path = data_dir / "mega_close_audit.jsonl"
    data_root = data_dir.parent

    audit_idx = load_audit_index(audit_path)
    archive_paths = find_archive_closed_files(data_root, str(args.instance)) if args.include_archives else []

    all_row_lists: list[list[dict]] = []
    if closed_path.is_file():
        _, rows = load_closed_payload(closed_path)
        all_row_lists.append(rows)
    for ap in archive_paths:
        try:
            _, ar = load_closed_payload(ap)
            if ar:
                all_row_lists.append(ar)
                print(f"  archive +{len(ar)} from {ap.relative_to(data_root)}")
        except Exception as exc:
            print(f"  ⚠ archive skip {ap}: {exc}")

    merged_for_audit = merge_closed_unique(all_row_lists) if all_row_lists else []

    if args.consolidate_out:
        out = data_dir / args.consolidate_out
        merged = merge_closed_unique(all_row_lists) if all_row_lists else []
        changed = 0
        for row in merged:
            if enrich_closed_row(row, audit_idx, force=args.force):
                changed += 1
        payload = {
            "schema": "mega_live_closed_history_v1",
            "instance": str(args.instance),
            "note": "retro backfill; btc/regime at trade time not available",
            "trade_count": len(merged),
            "closed": merged,
        }
        if not args.dry_run:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": args.dry_run,
                    "consolidate_out": str(out),
                    "trades": len(merged),
                    "enriched": changed,
                    "archives": len(archive_paths),
                },
                indent=2,
            )
        )

    if not args.audit_only and closed_path.is_file():
        wrapper, rows = load_closed_payload(closed_path)
        n_changed = 0
        for row in rows:
            if enrich_closed_row(row, audit_idx, force=args.force):
                n_changed += 1
        if not args.dry_run and n_changed:
            save_closed_payload(closed_path, wrapper, rows)
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": args.dry_run,
                    "closed_path": str(closed_path),
                    "rows": len(rows),
                    "enriched": n_changed,
                    "audit_positions": len(audit_idx),
                },
                indent=2,
            )
        )
    elif not args.audit_only and not closed_path.is_file():
        print(json.dumps({"ok": False, "error": "mega_live_closed.json yok", "path": str(closed_path)}))

    if args.audit or args.audit_only:
        rows_for_audit = merged_for_audit
        if not rows_for_audit and closed_path.is_file():
            _, rows_for_audit = load_closed_payload(closed_path)
        if rows_for_audit:
            st = backfill_audit_file(audit_path, rows_for_audit, dry_run=args.dry_run)
            print(json.dumps({"audit": st, "dry_run": args.dry_run}, indent=2))
        else:
            print(json.dumps({"audit": {"error": "no closed rows for audit join"}, "dry_run": args.dry_run}))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
