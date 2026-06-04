"""Gamma API filter'larını probe eder.

Sorun: condition_id filter'i boş dönüyor → market resolution çalışmıyor.
Bu script alternatif filter şemalarını dener.
"""
from __future__ import annotations

import json

import httpx

CLOSED_MARKETS_TESTS = [
    ("closed=true limit=3",
     "https://gamma-api.polymarket.com/markets?closed=true&limit=3"),
    ("closed=true offset=0 limit=500",
     "https://gamma-api.polymarket.com/markets?closed=true&limit=500"),
    ("archived=true limit=3",
     "https://gamma-api.polymarket.com/markets?archived=true&limit=3"),
    # Filter by condition_id (mevcut deneme — boş çıkıyor)
    ("condition_id direct",
     "https://gamma-api.polymarket.com/markets?condition_id=0xc6564d7fc7bb20de273fd8383fa95322a1323c18bdd3b59e04ff1140e48d04a9&limit=1"),
    # Alternatif: conditionIds (camelCase)
    ("conditionIds camelCase",
     "https://gamma-api.polymarket.com/markets?conditionIds=0xc6564d7fc7bb20de273fd8383fa95322a1323c18bdd3b59e04ff1140e48d04a9&limit=1"),
    # condition_ids plural
    ("condition_ids plural",
     "https://gamma-api.polymarket.com/markets?condition_ids=0xc6564d7fc7bb20de273fd8383fa95322a1323c18bdd3b59e04ff1140e48d04a9&limit=1"),
    # By slug
    ("slug filter",
     "https://gamma-api.polymarket.com/markets?slug=will-michael-younger-win-the-california-governor-election-in-2026&limit=1"),
    # Direct lookup by id (numeric)
    ("id=964332",
     "https://gamma-api.polymarket.com/markets/964332"),
]


def probe(url: str) -> dict:
    try:
        r = httpx.get(url, timeout=10.0, headers={"Accept": "application/json"})
        return {"status": r.status_code, "len": len(r.content),
                "snippet": r.text[:150].replace("\n", " ")}
    except httpx.HTTPError as e:
        return {"error": str(e)[:100]}


def main():
    print(f"  {'test':<35}  {'status':<6}  {'len':<6}  {'snippet'}")
    print(f"  {'-'*35}  {'-'*6}  {'-'*6}  {'-'*70}")
    for label, url in CLOSED_MARKETS_TESTS:
        r = probe(url)
        if "error" in r:
            print(f"  {label:<35}  ERR     {'-':<6}  {r['error']}")
        else:
            print(f"  {label:<35}  {r['status']:<6}  {r['len']:<6}  {r['snippet']}")

    # Eğer closed=true çalışıyorsa, response içinde resolution bilgisi var mı?
    print("\n=== closed=true sample full record ===")
    try:
        r = httpx.get("https://gamma-api.polymarket.com/markets?closed=true&limit=1",
                      timeout=10.0)
        if r.status_code == 200:
            data = r.json()
            if data:
                m = data[0]
                # Resolution ile ilgili field'ları öne çıkar
                interesting = ['id', 'conditionId', 'slug', 'closed', 'closedTime',
                               'umaResolutionStatus', 'outcomePrices', 'outcomes',
                               'volume', 'active', 'archived']
                print("\nResolution field'ları:")
                for k in interesting:
                    if k in m:
                        v = m[k]
                        if isinstance(v, str) and len(v) > 80:
                            v = v[:80] + "..."
                        print(f"  {k:<25} = {v}")
    except Exception as e:
        print(f"  err: {e}")

    print("\n=== data-api /trades page_size doğrulaması ===")
    for limit in [100, 200, 500, 1000]:
        try:
            r = httpx.get(f"https://data-api.polymarket.com/trades?limit={limit}",
                          timeout=10.0)
            if r.status_code == 200:
                n = len(r.json())
                print(f"  limit={limit:<5}  döndürdü {n} kayıt")
            else:
                print(f"  limit={limit:<5}  status={r.status_code}")
        except Exception as e:
            print(f"  limit={limit}: {e}")


if __name__ == "__main__":
    main()
