"""Polymarket trade history için alternatif veri kaynağı probe'u.

The Graph hosted service kapandığı için subgraph çalışmıyor. Bu script
şu kaynakları dener:
  1. Polymarket data-api (genel/filter'lı varyantlar)
  2. Polymarket CLOB API trade endpoint'leri
  3. Polymarket activity API
  4. Goldsky (alternatif indexer)
  5. The Graph yeni decentralized network (API key olmadan probe)

Çıktıya bak: hangisi 200 dönüp anlamlı veri veriyor.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
SIGNER = os.getenv("SIGNER_ADDRESS", os.getenv("RELAYER_API_KEY_ADDRESS", "")).lower()


PROBES = [
    # === Polymarket Data API varyantları ===
    ("data-api: trades (no filter)",
     "GET", "https://data-api.polymarket.com/trades", {}),
    ("data-api: trades limit=5",
     "GET", "https://data-api.polymarket.com/trades?limit=5", {}),
    ("data-api: activity (general)",
     "GET", "https://data-api.polymarket.com/activity?limit=5", {}),
    ("data-api: holders",
     "GET", "https://data-api.polymarket.com/holders?limit=5", {}),
    ("data-api: trades by user",
     "GET", f"https://data-api.polymarket.com/trades?user={SIGNER}&limit=5", {}),
    # === CLOB Data API ===
    ("clob: trades global",
     "GET", "https://clob.polymarket.com/trades?limit=5", {}),
    ("clob: data trades",
     "GET", "https://clob.polymarket.com/data/trades?limit=5", {}),
    ("clob: prices history",
     "GET", "https://clob.polymarket.com/prices-history?limit=5", {}),
    # === Gamma API ===
    ("gamma: events",
     "GET", "https://gamma-api.polymarket.com/events?limit=2", {}),
    ("gamma: markets order by volume",
     "GET", "https://gamma-api.polymarket.com/markets?limit=2&order=volume24hr",
     {}),
    # === Goldsky alternatives ===
    ("goldsky: polymarket pnl",
     "GET", "https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/polymarket-pnl/0.0.1/gn",
     {}),
    # === The Graph new gateway (no api key — should 401/403 but tells us URL) ===
    ("thegraph: gateway probe",
     "GET", "https://gateway-arbitrum.network.thegraph.com/api/subgraphs/id/81Dm16JjuFSrqz813HysXoUPvzTwE7fsfPk2RTf66nyC",
     {}),
]


def main():
    if not SIGNER:
        print("[X] SIGNER_ADDRESS yok .env'de")
        sys.exit(1)
    print(f"signer: {SIGNER}\n")
    print(f"  {'label':<40}  {'status':<6}  {'len':<6}  {'snippet':<60}")
    print(f"  {'-'*40}  {'-'*6}  {'-'*6}  {'-'*60}")
    headers = {"User-Agent": "predmarket-scanner-probe/0.1",
               "Accept": "application/json"}
    for label, method, url, extra in PROBES:
        try:
            r = httpx.request(method, url, headers=headers, timeout=8.0,
                              follow_redirects=False)
            snippet = r.text[:60].replace("\n", " ")
            print(f"  {label:<40}  {r.status_code:<6}  {len(r.content):<6}  {snippet}")
        except httpx.HTTPError as e:
            print(f"  {label:<40}  ERR    -       {str(e)[:60]}")

    print("\nYorum:")
    print("  200 + JSON dolu → bunu fetcher olarak kullanabiliriz")
    print("  301/302 → endpoint taşınmış")
    print("  401/403 → endpoint var ama auth lazım")
    print("  404 → endpoint yok")
    print("\nÇıktıyı yapıştır, gerçek subgraph yerine bu kaynaklardan birini bağlayacağım.")


if __name__ == "__main__":
    main()
