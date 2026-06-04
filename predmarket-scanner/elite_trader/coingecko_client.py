"""CoinGecko REST client — cold path only (no execution prices)."""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

from binance_futures_trader.network_ssl import httpx_verify

BASE = "https://api.coingecko.com/api/v3"

_CG_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "POL": "matic-network",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "NEAR": "near",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "SUI": "sui",
    "PEPE": "pepe",
    "WIF": "dogwifcoin",
    "TRX": "tron",
    "TON": "the-open-network",
    "SHIB": "shiba-inu",
    "FIL": "filecoin",
    "INJ": "injective-protocol",
    "TIA": "celestia",
    "SEI": "sei-network",
}


def _api_key() -> str:
    return (os.getenv("COINGECKO_API_KEY") or "").strip()


def _headers() -> dict[str, str]:
    key = _api_key()
    if not key:
        return {"Accept": "application/json"}
    return {
        "Accept": "application/json",
        "x-cg-demo-api-key": key,
    }


def coin_id_for_symbol(symbol: str) -> str | None:
    sym = str(symbol or "").upper().replace("USDT", "")
    return _CG_MAP.get(sym)


class CoinGeckoClient:
    """Async CoinGecko — macro quotes and market rankings."""

    MAJORS_TTL = 45.0
    MARKETS_TTL = 120.0

    def __init__(self) -> None:
        self._majors_cache: dict[str, Any] = {}
        self._majors_ts = 0.0
        self._markets_cache: list[dict[str, Any]] = []
        self._markets_ts = 0.0
        self.last_error: str | None = None
        self.last_fetch_ms: int = 0
        self.degraded = False

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=BASE,
            timeout=httpx.Timeout(20.0, connect=10.0),
            verify=httpx_verify(),
            headers=_headers(),
        )

    async def fetch_simple_prices(
        self,
        symbols: list[str] | None = None,
        *,
        force: bool = False,
    ) -> dict[str, float]:
        now = time.time()
        if not force and self._majors_cache and (now - self._majors_ts) < self.MAJORS_TTL:
            return dict(self._majors_cache.get("prices") or {})
        syms = symbols or list(_CG_MAP.keys())
        ids = []
        id_to_sym: dict[str, str] = {}
        for s in syms:
            cid = coin_id_for_symbol(s)
            if cid:
                ids.append(cid)
                id_to_sym[cid] = s.upper()
        if not ids:
            return {}
        try:
            async with await self._client() as client:
                r = await client.get(
                    "/simple/price",
                    params={
                        "ids": ",".join(ids[:50]),
                        "vs_currencies": "usd",
                        "include_24hr_change": "true",
                        "include_24hr_vol": "true",
                    },
                )
                r.raise_for_status()
                data = r.json()
            out: dict[str, float] = {}
            changes: dict[str, float] = {}
            for cid, row in (data or {}).items():
                sym = id_to_sym.get(cid, cid)
                px = float((row or {}).get("usd") or 0)
                if px > 0:
                    out[sym] = px
                    ch = (row or {}).get("usd_24h_change")
                    if ch is not None:
                        changes[sym] = float(ch)
            self._majors_cache = {"prices": out, "changes": changes}
            self._majors_ts = now
            self.last_fetch_ms = int(time.time() * 1000)
            self.degraded = False
            self.last_error = None
            return out
        except Exception as exc:
            self.last_error = str(exc)[:160]
            self.degraded = True
            return dict(self._majors_cache.get("prices") or {})

    async def fetch_markets(self, *, force: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if not force and self._markets_cache and (now - self._markets_ts) < self.MARKETS_TTL:
            return list(self._markets_cache)
        try:
            async with await self._client() as client:
                r = await client.get(
                    "/coins/markets",
                    params={
                        "vs_currency": "usd",
                        "order": "volume_desc",
                        "per_page": 50,
                        "page": 1,
                        "sparkline": "false",
                    },
                )
                r.raise_for_status()
                rows = r.json() or []
            self._markets_cache = rows if isinstance(rows, list) else []
            self._markets_ts = now
            self.last_fetch_ms = int(time.time() * 1000)
            return list(self._markets_cache)
        except Exception as exc:
            self.last_error = str(exc)[:160]
            self.degraded = True
            return list(self._markets_cache)

    def btc_24h_change(self) -> float | None:
        ch = (self._majors_cache.get("changes") or {}).get("BTC")
        return float(ch) if ch is not None else None

    def status(self) -> dict[str, Any]:
        return {
            "ok": not self.degraded and bool(self._majors_cache),
            "degraded": self.degraded,
            "last_fetch_ms": self.last_fetch_ms,
            "majors_n": len(self._majors_cache.get("prices") or {}),
            "markets_n": len(self._markets_cache),
            "last_error": self.last_error,
        }
