"""Polymarket coğrafi kısıt kontrolü — canlı emir öncesi.

Resmi endpoint (CLOB/Gamma değil):
  GET https://polymarket.com/api/geoblock

Dönen `blocked: true` ise API emirleri reddedilir (ülke/bölge yasak).
Bu, VPN/sunucu konumunu kontrol eder — kullanıcının fiziksel adresi değil.

Dokümantasyon: https://docs.polymarket.com/api-reference/geoblock
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

GEOBLOCK_URL = os.getenv("POLYMARKET_GEOBLOCK_URL", "https://polymarket.com/api/geoblock")
_CACHE_TTL_SEC = int(os.getenv("POLYMARKET_GEOBLOCK_CACHE_SEC", "300"))
_cache: dict[str, Any] = {"ts": 0.0, "payload": None}


def fetch_geoblock(client: httpx.Client | None = None) -> dict[str, Any]:
    """Ham geoblock JSON."""
    own = client
    if own is None:
        with httpx.Client(timeout=10.0, headers={"Accept": "application/json"}) as c:
            r = c.get(GEOBLOCK_URL)
            r.raise_for_status()
            data = r.json()
    else:
        r = own.get(GEOBLOCK_URL, timeout=10.0)
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, dict):
        return {"blocked": True, "country": "?", "region": "?"}
    return data


def get_geoblock_status(force_refresh: bool = False) -> dict[str, Any]:
    """Önbellekli geoblock sonucu."""
    now = time.time()
    if (
        not force_refresh
        and _cache.get("payload")
        and (now - float(_cache.get("ts") or 0)) < _CACHE_TTL_SEC
    ):
        return _cache["payload"]
    try:
        payload = fetch_geoblock()
    except Exception as exc:
        payload = {
            "blocked": None,
            "error": str(exc),
            "country": "",
            "region": "",
        }
    _cache["ts"] = now
    _cache["payload"] = payload
    return payload


def is_trading_blocked() -> tuple[bool, str]:
    """
    (blocked, mesaj)
    blocked=True  → yeni emir açma
    blocked=None  → kontrol başarısız (POLYMARKET_GEOBLOCK_FAIL_OPEN=1 ise izin ver)
    """
    if os.getenv("POLYMARKET_GEOBLOCK_CHECK", "1").strip().lower() in ("0", "false", "no"):
        return False, "geoblock_kapalı"

    geo = get_geoblock_status()
    if geo.get("error"):
        if os.getenv("POLYMARKET_GEOBLOCK_FAIL_OPEN", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            return False, "geoblock_erişilemedi_izin"
        return True, f"geoblock_erişilemedi: {geo['error']}"

    if geo.get("blocked") is True:
        cc = geo.get("country") or "?"
        reg = geo.get("region") or ""
        reg_s = f"/{reg}" if reg else ""
        return True, f"coğrafi_engel {cc}{reg_s}"

    return False, "geoblock_ok"


def assert_can_trade_live() -> tuple[bool, str]:
    """Canlı emir öncesi çağır. (ok, mesaj)"""
    blocked, msg = is_trading_blocked()
    return (not blocked), msg
