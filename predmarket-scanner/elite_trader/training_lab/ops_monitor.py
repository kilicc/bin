"""Ops monitor — AI providers, bots, connections (9007 dashboard)."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

_ROOT_PORT = os.getenv("BINANCE_ELITE_PORT", "9007")

PORT_META: dict[int, dict[str, Any]] = {
    9005: {
        "name": "BERSERK2",
        "role": "paper_scan",
        "rest_expected": False,
        "live_orders": False,
    },
    9006: {
        "name": "MEGA sim",
        "role": "paper_sim",
        "rest_expected": False,
        "live_orders": False,
    },
    9007: {
        "name": "MEGA canlı",
        "role": "live_demo",
        "rest_expected": True,
        "live_orders": True,
    },
}


def _timed_get(url: str, *, timeout: float = 6.0) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            ms = round((time.perf_counter() - t0) * 1000, 1)
            try:
                data = json.loads(body)
            except Exception:
                data = {"raw": body[:500]}
            return {"ok": True, "status": resp.status, "latency_ms": ms, "data": data}
    except Exception as exc:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"ok": False, "latency_ms": ms, "error": str(exc)}


def _binance_rest_label(
    port: int,
    *,
    api_ok: bool | None,
    api_paper: bool | None,
    auth_error: str | None,
) -> tuple[str, str]:
    """(label, css_class) — 9005/9006 REST kapalı tasarım gereği."""
    meta = PORT_META.get(port) or {}
    if not meta.get("rest_expected"):
        return "REST kapalı (paper port · normal)", "ok"
    if auth_error:
        return f"Auth hatası", "bad"
    if api_paper:
        return "Paper fallback", "warn"
    if api_ok:
        return "Bağlı · signed REST", "ok"
    return "Kopuk / degraded", "bad"


def _extract_perf(
    hb: dict[str, Any] | None,
    mon: dict[str, Any] | None,
    conn: dict[str, Any] | None,
) -> dict[str, Any]:
    hb = hb or {}
    mon = mon or {}
    conn = conn or {}
    summ = mon.get("summary") or {}
    motor = mon.get("motor") or {}
    scan = mon.get("mega_scan") or mon.get("scan") or {}
    mega_h = hb.get("mega") or {}
    bt = conn.get("bookticker") or {}
    mw = conn.get("mark_ws") or {}
    rest = conn.get("rest") or {}
    threads = hb.get("threads") or {}

    alive_threads = sum(1 for v in threads.values() if v)
    thread_total = len(threads) or 0

    return {
        "motor_eval_ms": hb.get("motor_eval_ms"),
        "motor_interval_ms": hb.get("motor_interval_ms"),
        "motor_ago_sec": hb.get("motor_ago"),
        "position_tick_ms": hb.get("position_tick_ms"),
        "position_ago_sec": hb.get("position_ago"),
        "fast_tick_ms": hb.get("fast_tick_ms"),
        "tick_ago_sec": hb.get("tick_ago"),
        "exchange_poll_ms": hb.get("exchange_poll_ms"),
        "exchange_api_ema_ms": hb.get("exchange_api_ema_ms"),
        "exchange_cache_age_ms": hb.get("exchange_cache_age_ms"),
        "paper_open": hb.get("paper_open"),
        "live_open": hb.get("live_open"),
        "live_max_open": hb.get("live_max_open"),
        "recoveries": hb.get("recoveries"),
        "position_stalls": hb.get("position_stalls"),
        "threads_alive": alive_threads,
        "threads_total": thread_total,
        "motor_queue": motor.get("queue") or scan.get("motor_queue"),
        "reject_top": (motor.get("reject_top_txt") or "")[:120],
        "orders_opened": motor.get("orders_opened"),
        "session_pnl": summ.get("session_pnl"),
        "equity": summ.get("current_capital") or summ.get("equity"),
        "closed_trades": summ.get("closed_trades"),
        "bookticker_lag_ms": bt.get("lag_ms"),
        "mark_ws_lag_ms": mw.get("lag_ms"),
        "mark_ws_health": mw.get("health"),
        "rest_coins": rest.get("coins"),
        "rest_age_ms": rest.get("age_ms"),
        "mega_cache_age_ms": mega_h.get("cache_age_ms"),
        "mega_rest_worker": mega_h.get("rest_worker"),
        "mega_close_sync_ago": (mega_h.get("close_sync") or {}).get("last_run_ago_sec"),
    }


def probe_bot(port: int) -> dict[str, Any]:
    base = f"http://127.0.0.1:{port}"
    meta = dict(PORT_META.get(port) or {})
    meta["port"] = port

    endpoints: dict[str, tuple[str, float]] = {
        "ping": (f"{base}/api/heartbeat", 3.5),
        "conn": (f"{base}/api/connection/live", 10.0),
        "monitor": (f"{base}/api/monitor/snapshot", 6.0),
        "alerts": (f"{base}/api/connection/alerts", 8.0),
    }
    if port == 9007:
        endpoints["health"] = (f"{base}/api/health/strip", 5.0)

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
        futs = {
            pool.submit(_timed_get, url, timeout=to): key
            for key, (url, to) in endpoints.items()
        }
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                results[key] = fut.result()
            except Exception as exc:
                results[key] = {"ok": False, "latency_ms": None, "error": str(exc)}

    ping_r = results.get("ping") or {}
    conn_r = results.get("conn") or {}
    mon_r = results.get("monitor") or {}
    alert_r = results.get("alerts") or {}
    health_r = results.get("health") or {}

    conn_d = (conn_r.get("data") or {}) if conn_r.get("ok") else {}
    ping_d = (ping_r.get("data") or {}) if ping_r.get("ok") else {}
    mon_d = (mon_r.get("data") or {}) if mon_r.get("ok") else {}
    alert_d = (alert_r.get("data") or {}) if alert_r.get("ok") else {}
    hb = ping_d if ping_d else (mon_d.get("heartbeat") or {})

    api_ok = conn_d.get("api_ok")
    api_paper = conn_d.get("api_paper")
    auth_error = conn_d.get("auth_error")
    rest_lbl, rest_cls = _binance_rest_label(
        port, api_ok=api_ok, api_paper=api_paper, auth_error=auth_error
    )

    ws_ok = bool((conn_d.get("bookticker") or {}).get("ok"))
    process_ok = bool(ping_r.get("ok"))
    reachable = bool(conn_r.get("ok") or ping_r.get("ok"))

    perf = _extract_perf(hb, mon_d, conn_d)

    if meta.get("live_orders"):
        health_ok = bool(api_ok and not api_paper and ws_ok and process_ok)
    else:
        health_ok = bool(reachable and ws_ok and process_ok)

    return {
        "port": port,
        "meta": meta,
        "reachable": reachable,
        "process_ok": process_ok,
        "health_ok": health_ok,
        "ping_ms": ping_r.get("latency_ms"),
        "conn_ms": conn_r.get("latency_ms"),
        "monitor_ms": mon_r.get("latency_ms"),
        "latency_ms": ping_r.get("latency_ms") or conn_r.get("latency_ms"),
        "api_ok": api_ok,
        "api_paper": api_paper,
        "auth_error": auth_error,
        "api_label": conn_d.get("api_label"),
        "binance_rest_label": rest_lbl,
        "binance_rest_class": rest_cls,
        "bookticker": conn_d.get("bookticker"),
        "mark_ws": conn_d.get("mark_ws"),
        "open_positions": conn_d.get("open_positions"),
        "health_strip": health_r.get("data") if health_r.get("ok") else None,
        "alerts": alert_d.get("alerts") or [],
        "alert_severity": alert_d.get("severity"),
        "error": conn_r.get("error") or ping_r.get("error"),
        "perf": perf,
        "heartbeat": hb,
        "monitor": {
            "summary": mon_d.get("summary"),
            "motor": mon_d.get("motor"),
            "mega_scan": mon_d.get("mega_scan"),
        },
    }


def probe_llm_providers() -> dict[str, Any]:
    from elite_trader.training_lab import llm_client

    out: dict[str, Any] = {"configured": {}}
    for key in (
        "LAB_LLM_PROVIDER",
        "LAB_LLM_MODEL",
        "LAB_VISION_MODEL",
        "LAB_LLM_FALLBACK",
        "GCP_PROJECT",
        "GCP_REGION",
    ):
        val = os.getenv(key, "").strip()
        if val:
            out["configured"][key] = val

    out["primary"] = llm_client.probe_provider(
        os.getenv("LAB_LLM_PROVIDER", "openai").strip().lower()
    )
    fb = os.getenv("LAB_LLM_FALLBACK", "ollama").strip().lower()
    prim = os.getenv("LAB_LLM_PROVIDER", "openai").strip().lower()
    proj = llm_client.gcp_project_resolved()
    if proj:
        out["configured"]["GCP_PROJECT"] = proj
    if fb and fb not in ("none", "off", "0", "false") and fb != prim:
        out["fallback"] = llm_client.probe_provider(fb)
    else:
        out["fallback"] = {"ok": False, "skipped": True, "provider": fb}

    out["openai_key_set"] = bool(os.getenv("OPENAI_API_KEY", "").strip())
    return out


def knowledge_status() -> dict[str, Any]:
    from elite_trader.training_lab import lab_store

    docs = lab_store.lab_data_dir() / "documents"
    marker = docs / ".knowledge_bootstrap_ts"
    return {
        "bootstrapped": marker.is_file(),
        "bootstrap_ts": marker.read_text(encoding="utf-8").strip()
        if marker.is_file()
        else None,
        "sys_documents": [p.name for p in sorted(docs.glob("sys_*.txt"))] if docs.is_dir() else [],
        "lessons_count": len(lab_store.read_lessons(limit=500)),
        "sessions_count": len(lab_store.list_sessions(limit=200))
        if (lab_store.lab_data_dir() / "sessions").is_dir()
        else 0,
    }


def ops_dashboard(*, fresh_llm: bool = False) -> dict[str, Any]:
    from elite_trader.health_strip import health_strip_payload
    from elite_trader.training_lab.lab_api import executor_metrics

    if fresh_llm:
        import elite_trader.health_strip as hs

        hs._LLM_PING_CACHE["ts"] = 0.0
        hs._LLM_PING_CACHE["data"] = None

    strip = health_strip_payload()

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as pool:
        bots = list(pool.map(probe_bot, (9005, 9006, 9007)))
    probe_total_ms = round((time.perf_counter() - t0) * 1000, 1)

    llm = probe_llm_providers()

    checks: list[dict[str, Any]] = []
    for b in bots:
        checks.append(
            {
                "name": f"bot_{b['port']}",
                "ok": b.get("health_ok"),
                "latency_ms": b.get("ping_ms"),
                "detail": f"ping={b.get('ping_ms')}ms conn={b.get('conn_ms')}ms",
            }
        )
    checks.append(
        {
            "name": "llm_primary",
            "ok": (llm.get("primary") or {}).get("ok"),
            "latency_ms": (llm.get("primary") or {}).get("latency_ms"),
            "detail": (llm.get("primary") or {}).get("provider"),
        }
    )
    checks.append(
        {
            "name": "llm_health_strip",
            "ok": (strip.get("llm") or {}).get("ok"),
            "detail": strip.get("llm"),
        }
    )

    all_ok = all(c.get("ok") for c in checks if c.get("name", "").startswith("bot_"))

    connection_alerts: list[dict[str, Any]] = []
    for b in bots:
        port = b.get("port")
        meta = b.get("meta") or {}
        if not b.get("reachable"):
            connection_alerts.append(
                {
                    "level": "critical",
                    "code": "bot_down",
                    "title": f"Bot {port} yanıt vermiyor",
                    "detail": b.get("error") or "systemd / port kapalı — panel 502 olabilir.",
                }
            )
        elif meta.get("live_orders") and b.get("auth_error"):
            connection_alerts.append(
                {
                    "level": "critical",
                    "code": "auth",
                    "title": f"Bot {port} Binance auth hatası",
                    "detail": str(b.get("auth_error"))[:200],
                }
            )
        elif meta.get("live_orders") and b.get("api_paper"):
            connection_alerts.append(
                {
                    "level": "warn",
                    "code": "paper",
                    "title": f"Bot {port} paper fallback",
                    "detail": "Canlı emir gitmiyor — recovery veya API limit kontrol edin.",
                }
            )
        for a in b.get("alerts") or []:
            if a not in connection_alerts:
                connection_alerts.append(a)

    ping_vals = [b.get("ping_ms") for b in bots if b.get("ping_ms") is not None]
    conn_vals = [b.get("conn_ms") for b in bots if b.get("conn_ms") is not None]

    return {
        "ok": all_ok,
        "ts": time.time(),
        "port": _ROOT_PORT,
        "probe_total_ms": probe_total_ms,
        "probe_latency": {
            "ping_ms_min": min(ping_vals) if ping_vals else None,
            "ping_ms_max": max(ping_vals) if ping_vals else None,
            "conn_ms_max": max(conn_vals) if conn_vals else None,
        },
        "health_strip": strip,
        "lab_executor": executor_metrics(),
        "bots": bots,
        "llm": llm,
        "knowledge": knowledge_status(),
        "checks": checks,
        "connection_alerts": connection_alerts,
    }
