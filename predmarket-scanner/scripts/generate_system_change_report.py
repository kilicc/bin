#!/usr/bin/env python3
"""Phase 1 — read-only SYSTEM_CHANGE_REPORT (git, profiles, DB, tests)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / "data" / "reports"
LATEST_NAME = "SYSTEM_CHANGE_REPORT_latest.md"

MODE_TAG_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("evrim", re.compile(r"evrim", re.I)),
    ("berserk", re.compile(r"berserk|simsek|spike", re.I)),
    ("hunter", re.compile(r"hunter|avci", re.I)),
    ("chop", re.compile(r"chop|kalkan", re.I)),
    ("sentinel", re.compile(r"sentinel|ana_hat|9005", re.I)),
]

V2_PREFIXES: dict[str, tuple[str, ...]] = {
    "evrim": ("role", "evrim_v2_"),
    "berserk": ("role", "berserk_"),
    "hunter": ("role", "hunter_"),
    "chop_master": ("role", "chop_"),
    "sentinel": ("role", "sentinel_"),
}

TEST_PATTERNS: list[tuple[str, str]] = [
    ("evrim", "test_evrim_*.py"),
    ("berserk", "test_berserk_mode.py"),
    ("hunter", "test_hunter_mode.py"),
    ("chop", "test_chop_mode.py"),
    ("sentinel", "test_sentinel_mode.py"),
    ("motor_gate", "test_asama1_motor_gate.py"),
]


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _tag_file(path: str) -> str:
    for label, pat in MODE_TAG_RULES:
        if pat.search(path):
            return label
    return "shared"


def _run(cmd: list[str], *, cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd or ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as exc:
        return 1, "", str(exc)


def _git_changes() -> dict[str, Any]:
    rc, names, err = _run(["git", "diff", "--name-only", "HEAD"])
    if rc != 0 and not names.strip():
        rc2, names2, _ = _run(["git", "status", "--porcelain"])
        if rc2 == 0:
            names = "\n".join(
                line[3:].strip() for line in names2.splitlines() if line.strip()
            )
        else:
            return {"error": err or "git unavailable", "files": []}
    files: list[dict[str, str]] = []
    for line in names.splitlines():
        p = line.strip()
        if not p:
            continue
        _, stat_out, _ = _run(["git", "diff", "--stat", "HEAD", "--", p])
        files.append({"path": p, "tag": _tag_file(p), "stat": stat_out.strip()[:200]})
    return {"files": files, "count": len(files)}


def _v2_audit() -> dict[str, Any]:
    from elite_trader.mode_profiles import _BUILTIN_MODES  # noqa: SLF001

    path = ROOT / "data" / "mode_profiles.json"
    live: dict[str, Any] = {}
    if path.is_file():
        try:
            live = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            live = {}
    modes = live.get("modes") or live
    out: dict[str, Any] = {}
    for mid, prefixes in V2_PREFIXES.items():
        builtin = dict(_BUILTIN_MODES.get(mid) or {})
        current = dict((modes.get(mid) if isinstance(modes, dict) else {}) or {})
        keys = [k for k in set(builtin) | set(current) if any(k.startswith(p) or k == p for p in prefixes)]
        missing = [k for k in keys if k in builtin and k not in current]
        extra = [k for k in keys if k in current and k not in builtin]
        drift = [
            k
            for k in keys
            if k in builtin and k in current and builtin[k] != current[k]
        ]
        out[mid] = {
            "role": current.get("role") or builtin.get("role"),
            "keys_checked": len(keys),
            "missing_from_live": missing[:20],
            "extra_in_live": extra[:20],
            "value_drift": drift[:20],
        }
    return out


def _runtime_snapshot() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from elite_trader.evrim_config_version import config_version_snapshot

        out["evrim_config"] = config_version_snapshot()
    except Exception as exc:
        out["evrim_config_error"] = str(exc)
    try:
        from elite_trader.evrim_learning_runtime import learning_snapshot

        out["evrim_learning"] = learning_snapshot()
    except Exception as exc:
        out["evrim_learning_error"] = str(exc)
    try:
        from elite_trader.evrim_cross_mode_learner import read_cross_mode_summaries

        out["cross_mode"] = read_cross_mode_summaries()
    except Exception as exc:
        out["cross_mode_error"] = str(exc)
    try:
        from elite_trader.panel_strategy import active_futures_mode, is_live_binance_motor, mode_order

        out["active_futures_mode"] = active_futures_mode()
        out["motor_gate"] = {
            mid: is_live_binance_motor(mid) for mid in mode_order()
        }
    except Exception as exc:
        out["motor_gate_error"] = str(exc)
    return out


def _lake_counts() -> dict[str, Any]:
    from elite_trader.data_lake.db import DB_PATH, get_conn

    tables = ("mode_decisions", "paper_trades", "live_trades", "mode_metrics")
    out: dict[str, Any] = {"db_path": str(DB_PATH.relative_to(ROOT)), "tables": {}}
    if not DB_PATH.is_file():
        out["missing"] = True
        return out
    conn = get_conn()
    for tbl in tables:
        try:
            rows = conn.execute(
                f"SELECT mode_id, COUNT(*) AS n FROM {tbl} GROUP BY mode_id"
            ).fetchall()
            out["tables"][tbl] = {str(r[0]): int(r[1]) for r in rows}
        except Exception as exc:
            out["tables"][tbl] = {"error": str(exc)}
    return out


def _state_db_counts() -> dict[str, Any]:
    db = ROOT / "data" / "binance_elite_8300_9005_state.db"
    if not db.is_file():
        return {"missing": True}
    out: dict[str, Any] = {"path": str(db.relative_to(ROOT)), "bytes": db.stat().st_size}
    try:
        conn = sqlite3.connect(str(db))
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        for t in tables:
            try:
                counts[t] = int(conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0])
            except Exception:
                pass
        conn.close()
        out["table_counts"] = counts
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _run_tests() -> dict[str, Any]:
    results: dict[str, Any] = {}
    for label, pattern in TEST_PATTERNS:
        rc, out, err = _run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                pattern,
                "-v",
            ]
        )
        combined = (out + "\n" + err).strip()
        passed = combined.count(" OK")
        failed = combined.count(" FAIL") + combined.count(" ERROR")
        results[label] = {
            "pattern": pattern,
            "exit_code": rc,
            "passed_hint": passed,
            "failed_hint": failed,
            "tail": combined.splitlines()[-8:] if combined else [],
        }
    return results


def _render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# SYSTEM_CHANGE_REPORT",
        "",
        f"- Generated: `{payload['created_at']}`",
        f"- Git HEAD: `{payload.get('git_head', '?')}`",
        "",
        "## A) File changes",
        "",
    ]
    git = payload.get("git") or {}
    if git.get("error"):
        lines.append(f"- Git error: {git['error']}")
    else:
        lines.append(f"- Changed files: **{git.get('count', 0)}**")
        for f in (git.get("files") or [])[:80]:
            lines.append(f"  - `[{f['tag']}]` `{f['path']}`")
    lines.extend(["", "## B) V2 profile checklist", ""])
    for mid, audit in (payload.get("v2_audit") or {}).items():
        lines.append(f"### {mid}")
        lines.append(f"- role: `{audit.get('role')}`")
        lines.append(f"- keys checked: {audit.get('keys_checked')}")
        if audit.get("missing_from_live"):
            lines.append(f"- missing: {audit['missing_from_live']}")
        if audit.get("value_drift"):
            lines.append(f"- drift: {audit['value_drift']}")
        lines.append("")
    lines.extend(["## C) Motor gate / runtime", ""])
    rt = payload.get("runtime") or {}
    lines.append(f"- active_futures_mode: `{rt.get('active_futures_mode')}`")
    mg = rt.get("motor_gate") or {}
    for mid, live in mg.items():
        lines.append(f"  - `{mid}` live motor: **{live}**")
    lines.extend(["", "## D) DB / data", ""])
    lines.append("```json")
    lines.append(json.dumps({"data_lake": payload.get("data_lake"), "state_db": payload.get("state_db")}, indent=2))
    lines.append("```")
    lines.extend(["", "## E) Test results", ""])
    tests = payload.get("tests") or {}
    if tests.get("skipped"):
        lines.append("- Tests skipped (`--skip-tests`)")
    for label, tr in tests.items():
        if label == "skipped" or not isinstance(tr, dict):
            continue
        status = "PASS" if tr.get("exit_code") == 0 else "FAIL"
        lines.append(f"- **{label}** ({tr.get('pattern')}): {status} (exit {tr.get('exit_code')})")
        for tline in tr.get("tail") or []:
            lines.append(f"  - `{tline}`")
    gaps = payload.get("risk_gaps") or []
    if gaps:
        lines.extend(["", "## Risk gaps", ""])
        for g in gaps:
            lines.append(f"- {g}")
    return "\n".join(lines) + "\n"


def generate_report(*, skip_tests: bool = False) -> dict[str, Any]:
    os.environ.setdefault("BINANCE_ELITE_PORT", "9005")
    os.environ.setdefault("PROFILE_NAME", "binance_elite_8300_9005")
    _, head, _ = _run(["git", "rev-parse", "--short", "HEAD"])
    git_head = head.strip() or "unknown"
    payload: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "git": _git_changes(),
        "v2_audit": _v2_audit(),
        "runtime": _runtime_snapshot(),
        "data_lake": _lake_counts(),
        "state_db": _state_db_counts(),
    }
    if not skip_tests:
        payload["tests"] = _run_tests()
    else:
        payload["tests"] = {"skipped": True}
    gaps: list[str] = []
    for label, tr in (payload.get("tests") or {}).items():
        if label == "skipped" or not isinstance(tr, dict):
            continue
        if tr.get("exit_code", 0) != 0:
            gaps.append(f"Test suite failed: {label}")
    if payload.get("state_db", {}).get("missing"):
        gaps.append("9005 state DB missing")
    payload["risk_gaps"] = gaps
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _now_stamp()
    path = REPORTS_DIR / f"SYSTEM_CHANGE_REPORT_{stamp}.md"
    latest = REPORTS_DIR / LATEST_NAME
    md = _render_md(payload)
    path.write_text(md, encoding="utf-8")
    latest.write_text(md, encoding="utf-8")
    payload["report_path"] = str(path.relative_to(ROOT))
    payload["latest_path"] = str(latest.relative_to(ROOT))
    meta = REPORTS_DIR / f"SYSTEM_CHANGE_REPORT_{stamp}.json"
    meta.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="Generate SYSTEM_CHANGE_REPORT")
    p.add_argument("--skip-tests", action="store_true")
    args = p.parse_args()
    payload = generate_report(skip_tests=args.skip_tests)
    print(f"Report → {payload['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
