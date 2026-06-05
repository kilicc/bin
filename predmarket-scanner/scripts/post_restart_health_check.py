#!/usr/bin/env python3
"""Phase 9 — post-restart health check report."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / "data" / "reports"


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _http_get(url: str, timeout: float = 3.0) -> tuple[int, Any]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body[:500]
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            return exc.code, body[:500]
        except Exception:
            return exc.code, str(exc)
    except Exception as exc:
        return 0, str(exc)


def _motor_gate_smoke() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from elite_trader.order_gate import ORDER_ROUTE_LIVE, ORDER_ROUTE_PAPER, build_order_intent, route_order

        g1 = route_order(
            "berserk",
            build_order_intent("berserk", symbol="BTCUSDT", side="LONG"),
            active_futures_mode="evrim",
            api_healthy=True,
            live_orders_enabled=True,
        )
        out["test1_berserk_paper_under_evrim"] = g1.order_route == ORDER_ROUTE_PAPER
        g2 = route_order(
            "hunter",
            build_order_intent("hunter", symbol="ETHUSDT", side="LONG"),
            active_futures_mode="hunter",
            api_healthy=True,
            live_orders_enabled=True,
        )
        out["test2_hunter_live_candidate"] = g2.order_route == ORDER_ROUTE_LIVE
        g3 = route_order(
            "evrim",
            build_order_intent("evrim", symbol="BTCUSDT", side="LONG"),
            active_futures_mode="evrim",
            api_healthy=True,
            live_orders_enabled=True,
        )
        out["test3_evrim_live_when_active"] = g3.order_route in (ORDER_ROUTE_LIVE, ORDER_ROUTE_PAPER)
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _import_checks() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from elite_trader.evrim_snapshot_loader import load_latest_training_bias

        snap = load_latest_training_bias()
        out["training_snapshot_loaded"] = snap is not None
        out["training_snapshot_created_at"] = (snap or {}).get("created_at")
    except Exception as exc:
        out["training_snapshot_error"] = str(exc)
    try:
        from elite_trader.evrim_learning_runtime import learning_snapshot

        ls = learning_snapshot()
        out["learning_active"] = ls.get("learning_active")
        out["learning_blocks_trading"] = ls.get("learning_blocks_trading")
        out["trading_continues_during_learning"] = ls.get("trading_continues_during_learning")
    except Exception as exc:
        out["learning_error"] = str(exc)
    try:
        from elite_trader.evrim_config_version import config_version_snapshot

        cv = config_version_snapshot()
        out["active_config_version"] = cv.get("active_config_version")
        out["candidate_config_version"] = cv.get("candidate_config_version")
    except Exception as exc:
        out["config_error"] = str(exc)
    try:
        from elite_trader.panel_strategy import active_futures_mode, is_live_binance_motor, mode_order
        from elite_trader.parallel_universe_engine import get_universe_book

        out["active_futures_mode"] = active_futures_mode()
        modes: dict[str, Any] = {}
        for mid in mode_order():
            book = get_universe_book(mid)
            modes[mid] = {
                "open_paper": len(book.get("open") or []),
                "closed": len(book.get("closed") or []),
                "live_motor": is_live_binance_motor(mid),
            }
        out["modes"] = modes
    except Exception as exc:
        out["modes_error"] = str(exc)
    try:
        from elite_trader.data_lake.db import DB_PATH, get_conn

        out["data_lake"] = {"path": str(DB_PATH.relative_to(ROOT)), "ok": DB_PATH.is_file()}
        if DB_PATH.is_file():
            conn = get_conn()
            out["data_lake"]["paper_trades"] = conn.execute(
                "SELECT COUNT(*) FROM paper_trades"
            ).fetchone()[0]
            out["data_lake"]["live_trades"] = conn.execute(
                "SELECT COUNT(*) FROM live_trades"
            ).fetchone()[0]
    except Exception as exc:
        out["data_lake_error"] = str(exc)
    return out


def run_health_check(*, port: int = 9005, base_url: str = "") -> dict[str, Any]:
    base = base_url or f"http://127.0.0.1:{port}"
    endpoints = {
        "panel_mode": f"{base}/api/panel/mode",
        "motor_gate": f"{base}/api/motor-gate/status",
        "connection_live": f"{base}/api/connection/live",
    }
    http: dict[str, Any] = {}
    for name, url in endpoints.items():
        code, body = _http_get(url)
        http[name] = {"status": code, "ok": 200 <= code < 300, "body_preview": body}
    payload: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "http": http,
        "imports": _import_checks(),
        "motor_gate_smoke": _motor_gate_smoke(),
        "warnings": [],
    }
    if not all(v.get("ok") for v in http.values()):
        payload["warnings"].append("One or more HTTP endpoints unreachable")
    imp = payload["imports"]
    if imp.get("learning_blocks_trading"):
        payload["warnings"].append("learning_blocks_trading is true (unexpected)")
    if imp.get("active_futures_mode") != "evrim":
        payload["warnings"].append(f"active motor is {imp.get('active_futures_mode')}, expected evrim")
    smoke = payload["motor_gate_smoke"]
    if smoke.get("test1_berserk_paper_under_evrim") is False:
        payload["warnings"].append("Motor gate test1 failed")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _now_stamp()
    path = REPORTS_DIR / f"RESTART_HEALTH_{stamp}.md"
    latest = REPORTS_DIR / "RESTART_HEALTH_latest.md"
    lines = [
        "# RESTART_HEALTH",
        "",
        f"- Generated: `{payload['created_at']}`",
        f"- Base URL: `{base}`",
        "",
        "## HTTP",
        "",
    ]
    for name, block in http.items():
        lines.append(f"- **{name}**: status={block['status']} ok={block['ok']}")
    lines.extend(["", "## Imports / runtime", "", "```json"])
    lines.append(json.dumps(imp, indent=2, default=str))
    lines.extend(["```", "", "## Motor gate smoke", "", "```json"])
    lines.append(json.dumps(smoke, indent=2, default=str))
    lines.extend(["```"])
    if payload["warnings"]:
        lines.extend(["", "## Warnings", ""])
        for w in payload["warnings"]:
            lines.append(f"- {w}")
    md = "\n".join(lines) + "\n"
    path.write_text(md, encoding="utf-8")
    latest.write_text(md, encoding="utf-8")
    payload["report_path"] = str(path.relative_to(ROOT))
    (REPORTS_DIR / f"RESTART_HEALTH_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="Post-restart health check")
    p.add_argument("--port", type=int, default=9005)
    p.add_argument("--base-url", default="")
    args = p.parse_args()
    payload = run_health_check(port=args.port, base_url=args.base_url)
    print(f"Health → {payload['report_path']}")
    if payload.get("warnings"):
        for w in payload["warnings"]:
            print(f"  ⚠ {w}")
    return 0 if not payload.get("warnings") else 1


if __name__ == "__main__":
    raise SystemExit(main())
