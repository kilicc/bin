"""CoinMarketCap REST client — cold path only."""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

from binance_futures_trader.network_ssl import httpx_verify

BASE = "https://pro-api.coinmarketcap.com/v1"


def _api_key() -> str:
    return (os.getenv("COINMARKETCAP_API_KEY") or "").strip()


class CoinMarketCapClient:
    QUOTES_TTL = 60.0
    LISTINGS_TTL = 120.0
    GLOBAL_TTL = 120.0

    def __init__(self) -> None:
        self._quotes: dict[str, dict[str, Any]] = {}
        self._quotes_ts = 0.0
        self._listings: list[dict[str, Any]] = []
        self._listings_ts = 0.0
        self._global: dict[str, Any] = {}
        self._global_ts = 0.0
        self.last_error: str | None = None
        self.last_fetch_ms: int = 0
        self.degraded = False

    def _enabled(self) -> bool:
        return bool(_api_key())

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=BASE,
            timeout=httpx.Timeout(25.0, connect=10.0),
            verify=httpx_verify(),
            headers={
                "Accept": "application/json",
                "X-CMC_PRO_API_KEY": _api_key(),
            },
        )

    async def fetch_quotes(
        self, symbols: list[str], *, force: bool = False
    ) -> dict[str, dict[str, Any]]:
        if not self._enabled():
            self.degraded = True
            return dict(self._quotes)
        now = time.time()
        if not force and self._quotes and (now - self._quotes_ts) < self.QUOTES_TTL:
            return dict(self._quotes)
        syms = [str(s).upper().replace("USDT", "") for s in symbols if s][:100]
        if not syms:
            return dict(self._quotes)
        try:
            async with await self._client() as client:
                r = await client.get(
                    "/cryptocurrency/quotes/latest",
                    params={"symbol": ",".join(syms), "convert": "USD"},
                )
                r.raise_for_status()
                data = r.json().get("data") or {}
            out: dict[str, dict[str, Any]] = {}
            for sym, row in data.items():
                q = (row or {}).get("quote", {}).get("USD") or {}
                out[sym.upper()] = {
                    "price": float(q.get("price") or 0),
                    "change_24h": float(q.get("percent_change_24h") or 0),
                    "market_cap": float(q.get("market_cap") or 0),
                    "rank": int((row or {}).get("cmc_rank") or 0),
                }
            self._quotes = out
            self._quotes_ts = now
            self.last_fetch_ms = int(time.time() * 1000)
            self.degraded = False
            self.last_error = None
            return dict(out)
        except Exception as exc:
            self.last_error = str(exc)[:160]
            self.degraded = True
            return dict(self._quotes)

    async def fetch_listings(self, *, force: bool = False) -> list[dict[str, Any]]:
        if not self._enabled():
            return list(self._listings)
        now = time.time()
        if not force and self._listings and (now - self._listings_ts) < self.LISTINGS_TTL:
            return list(self._listings)
        try:
            async with await self._client() as client:
                r = await client.get(
                    "/cryptocurrency/listings/latest",
                    params={"limit": 50, "convert": "USD"},
                )
                r.raise_for_status()
                rows = r.json().get("data") or []
            self._listings = rows if isinstance(rows, list) else []
            self._listings_ts = now
            self.last_fetch_ms = int(time.time() * 1000)
            return list(self._listings)
        except Exception as exc:
            self.last_error = str(exc)[:160]
            self.degraded = True
            return list(self._listings)

    async def fetch_global_metrics(self, *, force: bool = False) -> dict[str, Any]:
        if not self._enabled():
            return dict(self._global)
        now = time.time()
        if not force and self._global and (now - self._global_ts) < self.GLOBAL_TTL:
            return dict(self._global)
        try:
            async with await self._client() as client:
                r = await client.get("/global-metrics/quotes/latest", params={"convert": "USD"})
                r.raise_for_status()
                data = r.json().get("data") or {}
            usd = (data.get("quote") or {}).get("USD") or {}
            self._global = {
                "total_market_cap": float(usd.get("total_market_cap") or 0),
                "btc_dominance": float(data.get("btc_dominance") or 0),
                "eth_dominance": float(data.get("eth_dominance") or 0),
            }
            self._global_ts = now
            self.last_fetch_ms = int(time.time() * 1000)
            return dict(self._global)
        except Exception as exc:
            self.last_error = str(exc)[:160]
            self.degraded = True
            return dict(self._global)

    def status(self) -> dict[str, Any]:
        return {
            "ok": self._enabled() and not self.degraded,
            "enabled": self._enabled(),
            "degraded": self.degraded,
            "last_fetch_ms": self.last_fetch_ms,
            "quotes_n": len(self._quotes),
            "listings_n": len(self._listings),
            "last_error": self.last_error,
        }
