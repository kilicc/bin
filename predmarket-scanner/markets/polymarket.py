"""Polymarket public market data client.

Polymarket'in iki API'si var:
  - Gamma API (read-only metadata + indikatif fiyat): auth gerekmez, bu repo'da kullandığımız.
  - CLOB API (order book, trading): EVM cüzdan + signature, KASTEN implement etmedik.

Burada sadece Gamma API'den aktif binary piyasaları çekiyoruz.
Resmi dokümantasyon: https://docs.polymarket.com/
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, Optional

import httpx

from .base import Market, Outcome


class PolymarketClient:
    def __init__(self, base_url: str = "https://gamma-api.polymarket.com", timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": "predmarket-scanner/0.1 (educational)"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- Public API ----------------------------------------------------------

    def list_active_markets(self, limit: int = 100, offset: int = 0) -> list[Market]:
        """Aktif (henüz kapanmamış) piyasaları getir."""
        params = {
            "active": "true",
            "closed": "false",
            "archived": "false",
            "limit": str(limit),
            "offset": str(offset),
        }
        resp = self._client.get("/markets", params=params)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            return []
        return [m for m in (self._parse(item) for item in payload) if m is not None]

    def iter_active_markets(self, page_size: int = 100, max_pages: int = 20) -> Iterable[Market]:
        for page in range(max_pages):
            batch = self.list_active_markets(limit=page_size, offset=page * page_size)
            if not batch:
                return
            yield from batch

    # --- Parser --------------------------------------------------------------

    def _parse(self, item: dict) -> Optional[Market]:
        try:
            outcomes_raw = item.get("outcomes")
            prices_raw = item.get("outcomePrices")

            # Polymarket bazen JSON-string olarak dönüyor, parse et
            if isinstance(outcomes_raw, str):
                outcomes_raw = json.loads(outcomes_raw)
            if isinstance(prices_raw, str):
                prices_raw = json.loads(prices_raw)

            if not outcomes_raw or not prices_raw:
                return None
            if len(outcomes_raw) != len(prices_raw):
                return None

            outcomes = [
                Outcome(name=str(n), price=float(p))
                for n, p in zip(outcomes_raw, prices_raw)
            ]

            end_date = None
            if item.get("endDate"):
                try:
                    end_date = datetime.fromisoformat(item["endDate"].replace("Z", "+00:00"))
                except Exception:
                    end_date = None

            slug = item.get("slug") or ""
            url = f"https://polymarket.com/event/{slug}" if slug else None

            return Market(
                venue="polymarket",
                market_id=str(item.get("id") or item.get("conditionId") or slug),
                question=item.get("question") or item.get("title") or "(no question)",
                category=item.get("category"),
                end_date=end_date,
                volume_24h=float(item.get("volume24hr") or 0.0),
                liquidity=float(item.get("liquidity") or 0.0),
                outcomes=outcomes,
                url=url,
                raw=item,
            )
        except Exception:
            # Bozuk kayıtları sessizce atla — sayıları rapor ederiz scanner'da
            return None
