#!/usr/bin/env python3
"""Phase 2 — full reset backup + manifest + verification gate."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BACKUP_ROOT = ROOT / "data" / "backups" / "full_reset_before_evrim_restart"
MIN_FILES = 5

COPY_PATHS: list[tuple[str, Path]] = [
    ("mode_profiles", ROOT / "data" / "mode_profiles.json"),
    ("parallel_universes", ROOT / "data" / "parallel_universes.json"),
    ("panel_strategy_state", ROOT / "data" / "panel_strategy_state.json"),
    ("data_lake_db", ROOT / "data" / "data_lake.db"),
    ("state_db", ROOT / "data" / "binance_elite_8300_9005_state.db"),
    ("evrim_config_versions", ROOT / "data" / "evrim_config_versions.json"),
    ("evrim_learning_runtime", ROOT / "data" / "evrim_learning_runtime.json"),
    ("evrim_config_suggestions", ROOT / "data" / "evrim_config_suggestions.json"),
    ("evrim_adaptive_state", ROOT / "data" / "evrim_adaptive_state.json"),
    ("evrim_training_state", ROOT / "data" / "evrim_training_state.json"),
    ("evrim_meta_learning_state", ROOT / "data" / "evrim_meta_learning_state.json"),
    ("evrim_persistent_learning", ROOT / "data" / "evrim_persistent_learning.json"),
    ("elite_9005_trade_lessons", ROOT / "data" / "elite_9005_trade_lessons.json"),
    ("elite_9005_learning_registry", ROOT / "data" / "elite_9005_learning_registry.json"),
    ("elite_9005_proposals", ROOT / "data" / "elite_9005_proposals.json"),
    ("elite_sl_emergency_registry", ROOT / "data" / "elite_sl_emergency_registry.json"),
    ("elite_9005_loss_postmortem_json", ROOT / "data" / "elite_9005_loss_postmortem.json"),
    ("scenario_env", ROOT / "scenarios" / "binance_elite_8300_9005.env"),
    ("log_tail", ROOT / "logs" / "binance_elite_8300_9005.log"),
]

SECRET_PATTERNS = [
    re.compile(r"^(BN_.*KEY.*|BINANCE_.*SECRET.*|.*SECRET.*)$", re.I),
    re.compile(r"(api_secret|secret_key|password)", re.I),
]


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _mask_env(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        if "=" not in line or line.strip().startswith("#"):
            out.append(line)
            continue
        key, _, val = line.partition("=")
        if any(p.search(key.strip()) for p in SECRET_PATTERNS):
            out.append(f"{key}=***")
        else:
            out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def _copy_with_sidecars(src: Path, dest: Path, *, mask: bool = False) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        return 0
    if mask:
        dest.write_text(_mask_env(src.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    else:
        shutil.copy2(src, dest)
    total = dest.stat().st_size
    for ext in (".wal", ".shm"):
        side = Path(str(src) + ext)
        if side.is_file():
            shutil.copy2(side, Path(str(dest) + ext))
            total += side.stat().st_size
    return total


def _lake_table_counts() -> dict[str, Any]:
    from elite_trader.data_lake.db import DB_PATH, get_conn

    out: dict[str, Any] = {}
    if not DB_PATH.is_file():
        return out
    conn = get_conn()
    for tbl in ("mode_decisions", "paper_trades", "live_trades", "mode_metrics"):
        try:
            rows = conn.execute(
                f"SELECT mode_id, COUNT(*) FROM {tbl} GROUP BY mode_id"
            ).fetchall()
            out[tbl] = {str(r[0]): int(r[1]) for r in rows}
        except Exception:
            pass
    return out


def _state_db_counts() -> dict[str, Any]:
    db = ROOT / "data" / "binance_elite_8300_9005_state.db"
    if not db.is_file():
        return {}
    try:
        conn = sqlite3.connect(str(db))
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        counts = {}
        for t in tables:
            try:
                counts[t] = int(conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0])
            except Exception:
                pass
        conn.close()
        return counts
    except Exception:
        return {}


def _git_head() -> str:
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (p.stdout or "").strip()
    except Exception:
        return ""


def run_backup(*, report_path: str = "") -> dict[str, Any]:
    stamp = _now_stamp()
    dest_dir = BACKUP_ROOT / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    total_bytes = 0
    for label, src in COPY_PATHS:
        target = dest_dir / src.name
        mask = label == "scenario_env"
        if label == "log_tail" and src.is_file():
            try:
                text = src.read_text(encoding="utf-8", errors="replace")
                tail = "\n".join(text.splitlines()[-5000:])
                target.write_text(tail, encoding="utf-8")
                nbytes = target.stat().st_size
            except Exception as exc:
                copied.append({"label": label, "source": str(src.relative_to(ROOT)), "error": str(exc)})
                continue
        else:
            nbytes = _copy_with_sidecars(src, target, mask=mask)
        if nbytes:
            copied.append(
                {
                    "label": label,
                    "source": str(src.relative_to(ROOT)),
                    "dest": str(target.relative_to(ROOT)),
                    "bytes": nbytes,
                    "masked": mask,
                }
            )
            total_bytes += nbytes
    try:
        from elite_trader.panel_strategy import active_futures_mode
        from elite_trader.evrim_config_version import config_version_snapshot

        active_mode = active_futures_mode()
        config_versions = config_version_snapshot()
    except Exception as exc:
        active_mode = "unknown"
        config_versions = {"error": str(exc)}
    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backup_dir": str(dest_dir.relative_to(ROOT)),
        "copied_files": copied,
        "table_counts_before_reset": {
            "data_lake": _lake_table_counts(),
            "state_db": _state_db_counts(),
        },
        "active_futures_mode_before_reset": active_mode,
        "config_versions": config_versions,
        "git_head": _git_head(),
        "report_path": report_path,
        "total_bytes": total_bytes,
        "backup_verified": False,
        "verification_errors": [],
    }
    verified = True
    errors: list[str] = []
    if not copied:
        verified = False
        errors.append("no files copied")
    if len(copied) < MIN_FILES:
        verified = False
        errors.append(f"copied {len(copied)} files, need >= {MIN_FILES}")
    if not manifest["table_counts_before_reset"].get("data_lake") and (
        ROOT / "data" / "data_lake.db"
    ).is_file():
        errors.append("data_lake counts empty")
    manifest_path = dest_dir / "backup_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not manifest_path.is_file() or manifest_path.stat().st_size < 20:
        verified = False
        errors.append("manifest not written")
    manifest["backup_verified"] = verified and not errors
    manifest["verification_errors"] = errors
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    latest = BACKUP_ROOT / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "backup_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (latest / "backup_dir.txt").write_text(str(dest_dir.relative_to(ROOT)) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    p = argparse.ArgumentParser(description="Full reset backup before Evrim restart")
    p.add_argument("--report-path", default="")
    args = p.parse_args()
    manifest = run_backup(report_path=args.report_path)
    print(f"Backup → {manifest['backup_dir']}")
    print(f"Verified: {manifest['backup_verified']}")
    if manifest.get("verification_errors"):
        for e in manifest["verification_errors"]:
            print(f"  ⚠ {e}")
    return 0 if manifest["backup_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
