"""Ops monitor — AI providers, bots, connections (9007 dashboard)."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

_ROOT_PORT = os.getenv("BINANCE_ELITE_PORT", "9007")


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


def probe_bot(port: int) -> dict[str, Any]:
    base = f"http://127.0.0.1:{port}"
    conn = _timed_get(f"{base}/api/connection/live")
    alerts = _timed_get(f"{base}/api/connection/alerts")
    health = _timed_get(f"{base}/api/health/strip") if port == 9007 else {"ok": False, "skipped": True}
    d = (conn.get("data") or {}) if conn.get("ok") else {}
    alert_d = (alerts.get("data") or {}) if alerts.get("ok") else {}
    return {
        "port": port,
        "reachable": conn.get("ok", False),
        "latency_ms": conn.get("latency_ms"),
        "api_ok": d.get("api_ok"),
        "api_paper": d.get("api_paper"),
        "auth_error": d.get("auth_error"),
        "api_label": d.get("api_label"),
        "bookticker": d.get("bookticker"),
        "mark_ws": d.get("mark_ws"),
        "health_strip": health.get("data") if health.get("ok") else None,
        "alerts": alert_d.get("alerts") or [],
        "alert_severity": alert_d.get("severity"),
        "error": conn.get("error"),
    }


def probe_llm_providers() -> dict[str, Any]:
    from elite_trader.training_lab import llm_client

    out: dict[str, Any] = {"configured": {}}
    for key in ("LAB_LLM_PROVIDER", "LAB_LLM_MODEL", "LAB_VISION_MODEL", "LAB_LLM_FALLBACK", "GCP_PROJECT", "GCP_REGION"):
        val = os.getenv(key, "").strip()
        if val:
            out["configured"][key] = val

    out["primary"] = llm_client.probe_provider(os.getenv("LAB_LLM_PROVIDER", "openai").strip().lower())
    fb = os.getenv("LAB_LLM_FALLBACK", "ollama").strip().lower()
    prim = os.getenv("LAB_LLM_PROVIDER", "openai").strip().lower()
    proj = llm_client.gcp_project_resolved()
    if proj:
        out["configured"]["GCP_PROJECT"] = proj
    if fb and fb not in ("none", "off", "0", "false") and fb != prim:
        out["fallback"] = llm_client.probe_provider(fb)
    else:
        out["fallback"] = {"ok": False, "skipped": True, "provider": fb}

    # OpenAI key present?
    out["openai_key_set"] = bool(os.getenv("OPENAI_API_KEY", "").strip())
    return out


def knowledge_status() -> dict[str, Any]:
    from elite_trader.training_lab import lab_store

    docs = lab_store.lab_data_dir() / "documents"
    marker = docs / ".knowledge_bootstrap_ts"
    return {
        "bootstrapped": marker.is_file(),
        "bootstrap_ts": marker.read_text(encoding="utf-8").strip() if marker.is_file() else None,
        "sys_documents": [p.name for p in sorted(docs.glob("sys_*.txt"))] if docs.is_dir() else [],
        "lessons_count": len(lab_store.read_lessons(limit=500)),
        "sessions_count": len(lab_store.list_sessions(limit=200)) if (lab_store.lab_data_dir() / "sessions").is_dir() else 0,
    }


def ops_dashboard(*, fresh_llm: bool = False) -> dict[str, Any]:
    from elite_trader.health_strip import health_strip_payload
    from elite_trader.training_lab.lab_api import executor_metrics

    if fresh_llm:
        import elite_trader.health_strip as hs

        hs._LLM_PING_CACHE["ts"] = 0.0
        hs._LLM_PING_CACHE["data"] = None

    strip = health_strip_payload()
    bots = [probe_bot(p) for p in (9005, 9006, 9007)]
    llm = probe_llm_providers()

    checks: list[dict[str, Any]] = []
    for b in bots:
        checks.append(
            {
                "name": f"bot_{b['port']}",
                "ok": b.get("reachable"),
                "latency_ms": b.get("latency_ms"),
                "detail": f"api_ok={b.get('api_ok')} paper={b.get('api_paper')}",
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
        if not b.get("reachable"):
            connection_alerts.append(
                {
                    "level": "critical",
                    "code": "bot_down",
                    "title": f"Bot {b['port']} yanıt vermiyor",
                    "detail": b.get("error") or "systemd / port kapalı — panel 502 olabilir.",
                }
            )
        elif b.get("auth_error"):
            connection_alerts.append(
                {
                    "level": "critical",
                    "code": "auth",
                    "title": f"Bot {b['port']} Binance auth hatası",
                    "detail": str(b.get("auth_error"))[:200],
                }
            )
        elif b.get("api_paper"):
            connection_alerts.append(
                {
                    "level": "warn",
                    "code": "paper",
                    "title": f"Bot {b['port']} paper modda",
                    "detail": "Gerçek emir gitmiyor — mainnet env ve API anahtarı kontrol edin.",
                }
            )
        for a in b.get("alerts") or []:
            if a not in connection_alerts:
                connection_alerts.append(a)

    return {
        "ok": all_ok,
        "ts": time.time(),
        "port": _ROOT_PORT,
        "health_strip": strip,
        "lab_executor": executor_metrics(),
        "bots": bots,
        "llm": llm,
        "knowledge": knowledge_status(),
        "checks": checks,
        "connection_alerts": connection_alerts,
    }
