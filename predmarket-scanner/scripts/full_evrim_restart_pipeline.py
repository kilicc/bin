#!/usr/bin/env python3
"""
Full System Restart Pipeline — Evrim + 5 mod.

  python3 scripts/full_evrim_restart_pipeline.py --reason "V2 clean start" --confirm
  python3 scripts/full_evrim_restart_pipeline.py --phase report|backup|snapshot|preflight|reset|motor|bootstrap|restart|health
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / "data" / "reports"
BACKUP_LATEST = ROOT / "data" / "backups" / "full_reset_before_evrim_restart" / "latest"
PHASES = (
    "report",
    "backup",
    "snapshot",
    "preflight",
    "reset",
    "motor",
    "bootstrap",
    "restart",
    "health",
    "all",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _setup_env() -> None:
    os.environ.setdefault("BINANCE_ELITE_PORT", "9005")
    os.environ.setdefault("PROFILE_NAME", "binance_elite_8300_9005")


def detect_live_open_positions() -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    try:
        from binance_futures_trader.client import BinanceFuturesClient

        client = BinanceFuturesClient()
        if not client.paper:
            positions.extend(client.exchange_positions() or [])
    except Exception:
        pass
    try:
        from elite_trader.parallel_universe_engine import get_books

        for mid, book in (get_books() or {}).items():
            for p in book.get("open") or []:
                if p.get("on_exchange") or p.get("live"):
                    row = dict(p)
                    row.setdefault("panel_mode", mid)
                    positions.append(row)
    except Exception:
        pass
    return positions


def _load_backup_manifest() -> dict[str, Any] | None:
    path = BACKUP_LATEST / "backup_manifest.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_script_module(filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def phase_report(*, skip_tests: bool = False) -> dict[str, Any]:
    mod = _load_script_module("generate_system_change_report.py")
    return mod.generate_report(skip_tests=skip_tests)


def phase_backup(*, report_path: str = "") -> dict[str, Any]:
    mod = _load_script_module("full_reset_backup.py")
    return mod.run_backup(report_path=report_path)


def phase_snapshot(*, reason: str, backup_dir: str = "") -> dict[str, Any]:
    from elite_trader.evrim_training_snapshot import build_pre_reset_training_snapshot

    bd = backup_dir
    if not bd:
        m = _load_backup_manifest()
        bd = (m or {}).get("backup_dir") or ""
    return build_pre_reset_training_snapshot(backup_dir=bd or None, reason=reason)


def phase_preflight(
    *,
    confirm_live_reset: bool,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or _load_backup_manifest()
    snap_path = ROOT / "data" / "evrim_training_snapshot" / "latest_training_snapshot.json"
    live_positions = detect_live_open_positions()
    out: dict[str, Any] = {
        "backup_exists": manifest is not None,
        "backup_verified": bool((manifest or {}).get("backup_verified")),
        "training_snapshot_exists": snap_path.is_file(),
        "table_counts_before_reset": (manifest or {}).get("table_counts_before_reset"),
        "env_masked_in_manifest": any(
            f.get("masked") for f in ((manifest or {}).get("copied_files") or [])
        ),
        "live_open_positions_detected": bool(live_positions),
        "live_open_count": len(live_positions),
        "live_positions_preview": live_positions[:5],
        "can_proceed_reset": True,
        "block_reasons": [],
    }
    if not out["backup_verified"]:
        out["can_proceed_reset"] = False
        out["block_reasons"].append("backup not verified")
    if not out["training_snapshot_exists"]:
        out["can_proceed_reset"] = False
        out["block_reasons"].append("training snapshot missing")
    if live_positions and not confirm_live_reset:
        out["can_proceed_reset"] = False
        out["block_reasons"].append("live open positions — need --confirm-live-reset")
    return out


def phase_reset(
    *,
    reason: str,
    clear_data_lake: bool,
    wipe_9005_history: bool,
    confirm_live_reset: bool,
) -> dict[str, Any]:
    pre = phase_preflight(confirm_live_reset=confirm_live_reset)
    if not pre["can_proceed_reset"]:
        return {"skipped": True, "preflight": pre}
    clear_live = confirm_live_reset and wipe_9005_history
    from elite_trader.full_reset_ops import run_selective_reset

    return run_selective_reset(
        reason=reason,
        clear_data_lake=clear_data_lake,
        clear_live_trades=clear_live,
        wipe_9005_history=wipe_9005_history,
    )


def phase_motor(*, note: str = "") -> dict[str, Any]:
    from elite_trader.full_reset_ops import set_motor_evrim

    return set_motor_evrim(note=note or "full_evrim_restart_pipeline")


def phase_bootstrap() -> dict[str, Any]:
    from elite_trader.evrim_snapshot_loader import apply_meta_bias_to_evrim_state

    return apply_meta_bias_to_evrim_state()


def phase_restart(*, no_exchange_close: bool) -> dict[str, Any]:
    reset_script = ROOT / "scripts" / "reset_binance_elite_9005.sh"
    start_script = ROOT / "run_binance_elite_8300_9005.sh"
    cmd = [str(reset_script)]
    if no_exchange_close:
        cmd.append("--no-exchange-close")
    stop_proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
    start_proc = subprocess.run(
        [str(start_script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    try:
        from elite_trader.system_checkpoint_md import on_restart

        on_restart(source="full_evrim_restart_pipeline", note="phase_restart")
    except Exception:
        pass
    return {
        "stop_exit_code": stop_proc.returncode,
        "start_exit_code": start_proc.returncode,
        "exit_code": start_proc.returncode if start_proc.returncode else stop_proc.returncode,
        "stdout_tail": ((stop_proc.stdout or "") + (start_proc.stdout or "")).splitlines()[-20:],
        "stderr_tail": ((stop_proc.stderr or "") + (start_proc.stderr or "")).splitlines()[-10:],
        "no_exchange_close": no_exchange_close,
        "started_via": str(start_script.relative_to(ROOT)),
    }


def phase_health(*, port: int = 9005, wait_sec: float = 8.0) -> dict[str, Any]:
    if wait_sec > 0:
        time.sleep(wait_sec)
    mod = _load_script_module("post_restart_health_check.py")
    return mod.run_health_check(port=port)


def build_final_report(ctx: dict[str, Any]) -> dict[str, Any]:
    """10-section combined FINAL report."""
    sections = {
        "1_SYSTEM_CHANGE_REPORT": ctx.get("report"),
        "2_BACKUP_REPORT": ctx.get("backup"),
        "3_TRAINING_SNAPSHOT_REPORT": ctx.get("snapshot"),
        "4_RESET_REPORT": ctx.get("reset"),
        "5_ACTIVE_MOTOR_REPORT": ctx.get("motor"),
        "6_EVRIM_LEARNING_READY_REPORT": _evrim_learning_section(ctx),
        "7_PAPER_MODES_READY_REPORT": _paper_modes_section(ctx),
        "8_RESTART_CHECKLIST": ctx.get("restart"),
        "9_WARNINGS": _warnings_section(ctx),
        "10_NEXT_ACTIONS": _next_actions(ctx),
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    md_path = REPORTS_DIR / f"FINAL_RESTART_REPORT_{stamp}.md"
    latest = REPORTS_DIR / "FINAL_RESTART_REPORT_latest.md"
    lines = [
        "# FINAL RESTART REPORT",
        "",
        f"- Pipeline run: `{ctx.get('started_at')}`",
        f"- Reason: `{ctx.get('reason')}`",
        "",
    ]
    titles = {
        "1_SYSTEM_CHANGE_REPORT": "1. System Change Report",
        "2_BACKUP_REPORT": "2. Backup Report",
        "3_TRAINING_SNAPSHOT_REPORT": "3. Training Snapshot",
        "4_RESET_REPORT": "4. Reset Report",
        "5_ACTIVE_MOTOR_REPORT": "5. Active Motor",
        "6_EVRIM_LEARNING_READY_REPORT": "6. Evrim Learning Ready",
        "7_PAPER_MODES_READY_REPORT": "7. Paper Modes Ready",
        "8_RESTART_CHECKLIST": "8. Restart Checklist",
        "9_WARNINGS": "9. Warnings",
        "10_NEXT_ACTIONS": "10. Next Actions",
    }
    for key, title in titles.items():
        lines.extend(["", f"## {title}", ""])
        block = sections.get(key)
        if block is None:
            lines.append("_not run_")
        else:
            lines.append("```json")
            lines.append(json.dumps(block, indent=2, ensure_ascii=False, default=str)[:12000])
            lines.append("```")
    md = "\n".join(lines) + "\n"
    md_path.write_text(md, encoding="utf-8")
    latest.write_text(md, encoding="utf-8")
    payload = {
        "created_at": _now_iso(),
        "reason": ctx.get("reason"),
        "sections": sections,
        "report_path": str(md_path.relative_to(ROOT)),
    }
    (REPORTS_DIR / f"FINAL_RESTART_REPORT_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return payload


def _evrim_learning_section(ctx: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from elite_trader.evrim_learning_runtime import learning_snapshot
        from elite_trader.evrim_config_version import config_version_snapshot
        from elite_trader.evrim_snapshot_loader import load_latest_training_bias

        out["learning"] = learning_snapshot()
        out["config"] = config_version_snapshot()
        snap = load_latest_training_bias()
        out["snapshot_loaded"] = snap is not None
        out["bootstrap"] = ctx.get("bootstrap")
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _paper_modes_section(ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        from elite_trader.panel_strategy import is_live_binance_motor, mode_order
        from elite_trader.parallel_universe_engine import get_universe_book

        return {
            mid: {
                "paper": not is_live_binance_motor(mid),
                "open": len(get_universe_book(mid).get("open") or []),
            }
            for mid in mode_order()
        }
    except Exception as exc:
        return {"error": str(exc)}


def _warnings_section(ctx: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    pre = ctx.get("preflight") or {}
    if pre.get("live_open_positions_detected"):
        warnings.append(f"Live positions at preflight: {pre.get('live_open_count')}")
    health = ctx.get("health") or {}
    warnings.extend(health.get("warnings") or [])
    report = ctx.get("report") or {}
    for g in report.get("risk_gaps") or []:
        warnings.append(g)
    restart = ctx.get("restart") or {}
    if restart.get("exit_code", 0) != 0:
        warnings.append("Restart script non-zero exit")
    return warnings


def _next_actions(ctx: dict[str, Any]) -> dict[str, Any]:
    port = os.environ.get("BINANCE_ELITE_PORT", "9005")
    return {
        "dashboard": f"http://127.0.0.1:{port}/",
        "config_approve_hint": f"http://127.0.0.1:{port}/api/evrim/config/pending",
        "review_reports": [
            str(REPORTS_DIR.relative_to(ROOT) / "FINAL_RESTART_REPORT_latest.md"),
            str(REPORTS_DIR.relative_to(ROOT) / "RESTART_HEALTH_latest.md"),
        ],
    }


def run_pipeline(args: argparse.Namespace) -> int:
    _setup_env()
    ctx: dict[str, Any] = {
        "started_at": _now_iso(),
        "reason": args.reason,
    }
    phase = args.phase
    run_all = phase == "all"
    stop_on_fail = not args.force

    def _should(name: str) -> bool:
        return run_all or phase == name

    if _should("report"):
        print("━━━ Phase 1: SYSTEM_CHANGE_REPORT ━━━")
        ctx["report"] = phase_report(skip_tests=args.skip_tests)
        print(f"  → {ctx['report'].get('report_path')}")

    if _should("backup"):
        print("━━━ Phase 2: Full backup ━━━")
        ctx["backup"] = phase_backup(report_path=(ctx.get("report") or {}).get("report_path", ""))
        print(f"  → verified={ctx['backup'].get('backup_verified')}")
        if stop_on_fail and not ctx["backup"].get("backup_verified"):
            print("DUR: backup verification failed — reset yok.")
            build_final_report(ctx)
            return 1

    if _should("snapshot"):
        print("━━━ Phase 3: Training snapshot ━━━")
        ctx["snapshot"] = phase_snapshot(
            reason=args.reason,
            backup_dir=(ctx.get("backup") or {}).get("backup_dir", ""),
        )
        print(f"  → {ctx['snapshot'].get('paths', {}).get('latest')}")

    if _should("preflight") or run_all:
        print("━━━ Phase 4: Preflight ━━━")
        ctx["preflight"] = phase_preflight(confirm_live_reset=args.confirm_live_reset)
        print(f"  → can_proceed_reset={ctx['preflight'].get('can_proceed_reset')}")
        if ctx["preflight"].get("live_open_positions_detected"):
            print(f"  ⚠ Live positions: {ctx['preflight'].get('live_open_count')}")

    if _should("reset"):
        if not args.confirm and run_all:
            print("DUR: --confirm gerekli (reset atlandı).")
            build_final_report(ctx)
            return 1
        print("━━━ Phase 5: Selective reset ━━━")
        ctx["reset"] = phase_reset(
            reason=args.reason,
            clear_data_lake=args.clear_data_lake,
            wipe_9005_history=args.wipe_9005_history,
            confirm_live_reset=args.confirm_live_reset,
        )
        if ctx["reset"].get("skipped"):
            print(f"  ⚠ Reset skipped: {ctx['reset'].get('preflight', {}).get('block_reasons')}")
            if stop_on_fail:
                build_final_report(ctx)
                return 1

    if _should("motor"):
        print("━━━ Phase 6: Motor = Evrim ━━━")
        ctx["motor"] = phase_motor(note=args.reason)
        print(f"  → mode={ctx['motor'].get('new_mode')}")

    if _should("bootstrap") or run_all:
        print("━━━ Phase 7: Snapshot bootstrap ━━━")
        ctx["bootstrap"] = phase_bootstrap()
        print(f"  → applied={ctx['bootstrap'].get('applied')}")

    if _should("restart"):
        if not args.confirm and run_all:
            print("Restart atlandı (--confirm yok).")
        else:
            print("━━━ Phase 8: Restart 9005 ━━━")
            no_close = args.no_exchange_close or (
                (ctx.get("preflight") or {}).get("live_open_positions_detected")
                and not args.confirm_live_reset
            )
            ctx["restart"] = phase_restart(no_exchange_close=no_close)
            print(f"  → exit={ctx['restart'].get('exit_code')}")

    if _should("health"):
        print("━━━ Phase 9: Health check ━━━")
        ctx["health"] = phase_health(port=args.port, wait_sec=args.wait_sec if args.phase == "health" or run_all else 0)
        print(f"  → {ctx['health'].get('report_path')}")

    if run_all or args.final_report:
        final = build_final_report(ctx)
        print(f"━━━ Phase 10: Final report → {final['report_path']}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Full Evrim restart pipeline")
    p.add_argument("--reason", "-r", default="full_evrim_restart")
    p.add_argument("--phase", choices=PHASES, default="all")
    p.add_argument("--confirm", action="store_true", help="Reset + restart onay")
    p.add_argument("--confirm-live-reset", action="store_true")
    p.add_argument("--clear-data-lake", action="store_true")
    p.add_argument("--wipe-9005-history", action="store_true")
    p.add_argument("--no-exchange-close", action="store_true")
    p.add_argument("--skip-tests", action="store_true")
    p.add_argument("--force", action="store_true", help="Backup fail olsa da devam etme — yine dur; sadece reset skip override")
    p.add_argument("--port", type=int, default=9005)
    p.add_argument("--wait-sec", type=float, default=10.0)
    p.add_argument("--final-report", action="store_true")
    args = p.parse_args()
    return run_pipeline(args)


if __name__ == "__main__":
    raise SystemExit(main())
