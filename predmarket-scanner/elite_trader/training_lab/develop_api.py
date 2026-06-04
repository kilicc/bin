"""Develop desk — bootstrap, proposals, restart, logs (9007)."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent

_SECRET_FRAGMENTS = ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "PRIVATE")


def _scenario_path() -> Path | None:
    raw = os.getenv("BINANCE_ELITE_SCENARIO", "").strip()
    if raw and Path(raw).is_file():
        return Path(raw)
    for name in ("binance_elite_mega_9007_mainnet.env", "binance_elite_mega_9007.env"):
        p = _ROOT / "scenarios" / name
        if p.is_file():
            return p
    return None


def _mask_key(key: str, val: str) -> str:
    ku = key.upper()
    if any(f in ku for f in _SECRET_FRAGMENTS):
        return "***" if val else ""
    if len(val) > 120:
        return val[:120] + "…"
    return val


def scenario_summary() -> dict[str, Any]:
    p = _scenario_path()
    if not p:
        return {"ok": False, "error": "scenario not found"}
    keys: dict[str, str] = {}
    prefixes = ("MEGA_", "ELITE_", "LAB_", "BERSERK2_", "BINANCE_", "GCP_", "BN_FUT_")
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        if k.startswith(prefixes):
            keys[k] = _mask_key(k, v.strip())
    return {"ok": True, "path": str(p.relative_to(_ROOT)), "keys": keys}


def develop_status() -> dict[str, Any]:
    from elite_trader.training_lab import lab_store

    docs = lab_store.lab_data_dir() / "documents"
    marker = docs / ".knowledge_bootstrap_ts"
    port = os.getenv("BINANCE_ELITE_PORT", "9007")
    log_path = _ROOT / "logs" / f"binance_elite_mega_{port}.log"
    if port == "9005":
        log_path = _ROOT / "logs" / "binance_elite_8300_9005.log"

    git_rev = None
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if r.returncode == 0:
            git_rev = r.stdout.strip()
    except Exception:
        pass

    return {
        "ok": True,
        "port": port,
        "scenario": scenario_summary(),
        "knowledge": {
            "bootstrapped": marker.is_file(),
            "bootstrap_ts": marker.read_text(encoding="utf-8").strip() if marker.is_file() else None,
            "sys_docs": len(list(docs.glob("sys_*.txt"))) if docs.is_dir() else 0,
            "lessons": len(lab_store.read_lessons(limit=500)),
        },
        "log_file": log_path.name if log_path.is_file() else None,
        "git_rev": git_rev,
        "develop_mode": os.getenv("DEVELOP_ACCESS", "1"),
    }


def list_proposals_ui(*, status: str | None = None) -> dict[str, Any]:
    from elite_trader.loss_learner import _load_proposals, snapshot_for_ui

    props = (_load_proposals().get("proposals") or [])
    if status:
        props = [p for p in props if p.get("status") == status]
    snap = snapshot_for_ui()
    return {"ok": True, "proposals": props, "learner": snap}


def restart_bot() -> dict[str, Any]:
    from elite_trader.settings_registry import restart_live_bot

    return {"ok": True, **restart_live_bot()}


def try_systemd_restart(service: str = "binance-elite-9007-mainnet") -> dict[str, Any]:
    """GCP systemd restart — sudo gerekebilir."""
    try:
        r = subprocess.run(
            ["sudo", "-n", "systemctl", "restart", service],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return {"ok": True, "service": service, "via": "systemd"}
        return {"ok": False, "error": (r.stderr or r.stdout or "systemd failed")[:500]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_self_checks() -> dict[str, Any]:
    """Hızlı develop self-test."""
    checks: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    try:
        from elite_trader.training_lab.lab_knowledge import bootstrap_system_knowledge

        r = bootstrap_system_knowledge()
        checks.append(
            {
                "name": "knowledge_bootstrap",
                "ok": bool(r.get("ok")),
                "detail": r.get("reason") or f"written={len(r.get('written') or [])}",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        )
    except Exception as exc:
        checks.append({"name": "knowledge_bootstrap", "ok": False, "detail": str(exc)})

    t0 = time.perf_counter()
    try:
        from elite_trader.training_lab.llm_client import ping

        llm = ping()
        checks.append(
            {
                "name": "lab_llm",
                "ok": bool(llm.get("ok")),
                "detail": llm.get("provider") or llm.get("error"),
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        )
    except Exception as exc:
        checks.append({"name": "lab_llm", "ok": False, "detail": str(exc)})

    sp = _scenario_path()
    checks.append({"name": "scenario_file", "ok": sp is not None, "detail": str(sp) if sp else "missing"})

    ok_all = all(c.get("ok") for c in checks)
    return {"ok": ok_all, "checks": checks}
