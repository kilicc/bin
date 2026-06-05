"""Polymarket Gamma API — market çözümleme (query + path fallback)."""
from __future__ import annotations

from typing import Any

GAMMA = "https://gamma-api.polymarket.com"


async def resolve_gamma_market(client: Any, market_id: str) -> dict[str, Any] | None:
    """
    market_id: Gamma numeric id veya conditionId (0x…).
  `GET /markets?id=` bazen boş döner; `/markets/{id}` yedeklenir.
    """
    mid = str(market_id or "").strip()
    if not mid:
        return None

    if mid.startswith("0x"):
        r = await client.get(f"{GAMMA}/markets", params={"conditionId": mid})
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                return data[0]
        return None

    r = await client.get(f"{GAMMA}/markets", params={"id": mid})
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list) and data:
            return data[0]

    r2 = await client.get(f"{GAMMA}/markets/{mid}")
    if r2.status_code != 200:
        return None
    raw = r2.json()
    if isinstance(raw, dict) and (raw.get("id") is not None or raw.get("question")):
        return raw
    if isinstance(raw, list) and raw:
        return raw[0]
    return None
