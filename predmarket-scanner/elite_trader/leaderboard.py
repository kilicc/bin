"""Polymarket resmi leaderboard API."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import httpx

DATA_API = "https://data-api.polymarket.com"


@dataclass(frozen=True)
class LeaderboardTrader:
    rank: int
    wallet: str
    username: str
    volume_usd: float
    pnl_usd: float
    verified: bool


def fetch_leaderboard(
    *,
    category: str = "OVERALL",
    time_period: str = "MONTH",
    order_by: str = "PNL",
    limit: int = 50,
    max_offset: int = 200,
) -> list[LeaderboardTrader]:
    """Sayfalı leaderboard çek."""
    out: list[LeaderboardTrader] = []
    offset = 0
    page_size = min(50, limit)
    with httpx.Client(timeout=25.0, headers={"Accept": "application/json"}) as client:
        while len(out) < limit and offset <= max_offset:
            r = client.get(
                f"{DATA_API}/v1/leaderboard",
                params={
                    "category": category,
                    "timePeriod": time_period,
                    "orderBy": order_by,
                    "limit": page_size,
                    "offset": offset,
                },
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            for row in batch:
                try:
                    out.append(
                        LeaderboardTrader(
                            rank=int(row.get("rank") or len(out) + 1),
                            wallet=str(row["proxyWallet"]).lower(),
                            username=str(row.get("userName") or ""),
                            volume_usd=float(row.get("vol") or 0),
                            pnl_usd=float(row.get("pnl") or 0),
                            verified=bool(row.get("verifiedBadge")),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if len(out) >= limit:
                    break
            if len(batch) < page_size:
                break
            offset += page_size
    return out[:limit]


def iter_categories() -> Iterator[str]:
    for c in (
        "OVERALL",
        "POLITICS",
        "SPORTS",
        "CRYPTO",
        "CULTURE",
        "ECONOMICS",
        "TECH",
        "FINANCE",
    ):
        yield c
