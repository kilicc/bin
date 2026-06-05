"""Aggregated health strip for 9007 desk header."""
from __future__ import annotations

import os
import time
from typing import Any

_LLM_PING_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_LLM_PING_TTL = 30.0


def _llm_ping_cached() -> dict[str, Any]:
    now = time.time()
    if _LLM_PING_CACHE["data"] is not None and now - float(_LLM_PING_CACHE["ts"]) < _LLM_PING_TTL:
        return dict(_LLM_PING_CACHE["data"])
    out: dict[str, Any] = {"ok": False, "provider": os.getenv("LAB_LLM_PROVIDER", "openai")}
    try:
        from elite_trader.training_lab.llm_client import ping

        out = ping()
    except Exception as exc:
        out = {"ok": False, "error": str(exc)}
    _LLM_PING_CACHE["ts"] = now
    _LLM_PING_CACHE["data"] = out
    return dict(out)


def health_strip_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True, "ts": time.time()}
    try:
        from elite_trader.mega_control import get_status

        payload["control"] = get_status()
    except Exception as exc:
        payload["control"] = {"error": str(exc)}
    try:
        from elite_trader.mega_close_sync import close_sync_health

        payload["close_sync"] = close_sync_health()
    except Exception as exc:
        payload["close_sync"] = {"error": str(exc)}
    try:
        from elite_trader.mega_position_sync import position_sync_health

        payload["position_sync"] = position_sync_health()
    except Exception:
        payload["position_sync"] = None
    try:
        from elite_trader.training_lab.lab_api import executor_metrics

        payload["lab"] = executor_metrics()
    except Exception as exc:
        payload["lab"] = {"error": str(exc)}
    payload["llm"] = _llm_ping_cached()
    payload["port"] = os.getenv("BINANCE_ELITE_PORT", "")
    try:
        from elite_trader.mega_live import mega_api_outage_active

        payload["mega_api"] = {
            "outage_active": mega_api_outage_active(),
            "recovery_enabled": os.getenv("MEGA_RECOVERY_ENABLED", "1").strip().lower()
            in ("1", "true", "yes", "on"),
            "fresh_start_on_recovery": os.getenv(
                "MEGA_FRESH_START_ON_RECOVERY", "1"
            ).strip().lower()
            in ("1", "true", "yes", "on"),
        }
    except Exception as exc:
        payload["mega_api"] = {"error": str(exc)}
    return payload
