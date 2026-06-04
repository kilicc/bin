"""CLOB prices-history endpoint probe — mispricing analizi için gerekli.

Daha önce diagnostic'te: 'market (asset id) is mandatory' dedi. Demek ki
asset (token_id) parametresi lazım, conditionId değil.

Bu script:
  1. Cached closed market'lerden birini alıyor
  2. Gamma'dan onun clobTokenIds'lerini öğreniyor
  3. prices-history'yi 3 farklı interval'le test ediyor
  4. Şemayı yazdırıyor
"""
from __future__ import annotations

import json
import sys

import httpx


CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"


def main():
    # Bilinen yüksek hacimli closed market örnekleri
    print("=== Step 1: yüksek hacimli closed market örneği bul ===")
    r = httpx.get(f"{GAMMA}/markets", params={
        "closed": "true", "limit": 5, "order": "volume", "ascending": "false",
    }, timeout=15.0)
    r.raise_for_status()
    markets = r.json()
    if not markets:
        print("Hiç closed market yok??")
        sys.exit(1)

    for m in markets[:3]:
        print(f"\nMarket: {m.get('question','?')[:60]}")
        print(f"  slug: {m.get('slug')}")
        print(f"  conditionId: {m.get('conditionId')}")
        print(f"  volume: ${float(m.get('volume') or 0):,.0f}")
        print(f"  closed: {m.get('closed')}  outcome: {m.get('outcomePrices')}")
        print(f"  clobTokenIds: {m.get('clobTokenIds')}")

    # İlkini detaylı incele
    m = markets[0]
    tokens_raw = m.get("clobTokenIds")
    if isinstance(tokens_raw, str):
        try:
            tokens = json.loads(tokens_raw)
        except Exception:
            tokens = [tokens_raw]
    else:
        tokens = tokens_raw or []
    print(f"\n=== Step 2: Token IDs ===")
    print(f"  parsed tokens: {tokens}")

    if not tokens:
        print("Token ID yok — alternatif endpoint gerek")
        sys.exit(1)

    # Step 3: prices-history için çağrı dene
    print(f"\n=== Step 3: prices-history endpoint testleri ===")
    yes_token = tokens[0]
    print(f"  YES token: {yes_token}")

    test_urls = [
        ("market= param",
         f"{CLOB}/prices-history?market={yes_token}&interval=1h"),
        ("startTs param",
         f"{CLOB}/prices-history?market={yes_token}&startTs=0&endTs=99999999999&interval=1d"),
        ("interval=max",
         f"{CLOB}/prices-history?market={yes_token}&interval=max"),
    ]
    for label, url in test_urls:
        try:
            r = httpx.get(url, timeout=15.0)
            print(f"\n  [{label}]  {r.status_code}  len={len(r.content)}")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    history = data.get("history", [])
                    print(f"    history: {len(history)} kayıt")
                    if history:
                        print(f"    örnek (ilk 3):")
                        for h in history[:3]:
                            print(f"      {h}")
                else:
                    print(f"    {str(data)[:200]}")
            else:
                print(f"    {r.text[:200]}")
        except Exception as e:
            print(f"  [{label}]  ERR: {e}")


if __name__ == "__main__":
    main()
