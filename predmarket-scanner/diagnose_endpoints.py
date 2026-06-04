"""Polymarket endpoint diagnostic.

Polymarket'in birden çok API servisi var ve "Relayer API Key" hangi servise
gittiği belgelere göre değişir. Bu script tüm bilinen public endpoint'leri
hem auth'lu hem auth'suz dener, hangi kombinasyonun çalıştığını raporlar.

Çıktıyı bana gönderebilirsin — KEY'İ DEĞİL, sadece endpoint + status code matrisini.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# .env'i bul ve yükle
env_path = ROOT / ".env"
if not env_path.exists():
    print(f"[X] .env bulunamadı: {env_path}")
    print("    cp .env.example .env && nano .env  (RELAYER_API_KEY'i doldur)")
    sys.exit(1)

load_dotenv(env_path)

SIGNER = os.getenv("SIGNER_ADDRESS",
                   os.getenv("RELAYER_API_KEY_ADDRESS", "")).lower()
API_KEY = os.getenv("RELAYER_API_KEY", "").strip()
API_KEY_ADDR = os.getenv("RELAYER_API_KEY_ADDRESS", "").strip()

# All known Polymarket public endpoints we can poke
ENDPOINTS = [
    # Gamma — public market metadata, no auth
    ("GET",  "https://gamma-api.polymarket.com/markets?limit=1",       False),
    # CLOB — order book, may accept auth
    ("GET",  "https://clob.polymarket.com/",                            False),
    ("GET",  "https://clob.polymarket.com/markets?limit=1",             False),
    ("GET",  "https://clob.polymarket.com/auth/api-keys",               True),
    ("GET",  "https://clob.polymarket.com/auth/ban-status/cert-required", True),
    # Data API — user positions, history
    ("GET",  f"https://data-api.polymarket.com/positions?user={SIGNER}", True),
    ("GET",  f"https://data-api.polymarket.com/value?user={SIGNER}",     True),
    ("GET",  f"https://data-api.polymarket.com/trades?user={SIGNER}",    True),
    # Relayer (varsa)
    ("GET",  "https://relayer-v2.polymarket.com/",                       True),
    ("GET",  "https://relayer-v2.polymarket.com/api/v1/health",          True),
    ("GET",  "https://relayer.polymarket.com/",                          True),
    # Strapi back-end (eski)
    ("GET",  "https://strapi-matic.poly.market/markets?_limit=1",        False),
]


def _try(method: str, url: str, with_auth: bool) -> dict:
    headers = {"User-Agent": "predmarket-scanner-diagnostic/0.1",
               "Accept": "application/json"}
    if with_auth and API_KEY:
        headers["RELAYER_API_KEY"] = API_KEY
        headers["RELAYER_API_KEY_ADDRESS"] = API_KEY_ADDR
        # Polymarket CLOB uses different header naming; try both
        headers["POLY_API_KEY"] = API_KEY
        headers["POLY_ADDRESS"] = API_KEY_ADDR
    try:
        r = httpx.request(method, url, headers=headers, timeout=8.0)
        return {"status": r.status_code,
                "len": len(r.content),
                "ctype": r.headers.get("content-type", "")[:40],
                "snippet": r.text[:120].replace("\n", " ")}
    except httpx.HTTPError as e:
        return {"error": str(e)[:100]}


def main():
    if not API_KEY or API_KEY.startswith("<"):
        print(f"[X] RELAYER_API_KEY {env_path} içinde geçerli değil.")
        print(f"    Şu an: '{API_KEY[:20]}...' (placeholder olabilir)")
        print(f"    .env'i aç ve gerçek UUID'yi yapıştır.")
        sys.exit(1)
    print(f".env yüklendi: {env_path}")
    print(f"Signer:        {SIGNER}")
    print(f"Key prefix:    {API_KEY[:8]}...")
    print(f"Key length:    {len(API_KEY)}  (UUID = 36 karakter)")
    print()
    print(f"  {'method':<5}  {'auth':<5}  {'status':<6}  url")
    print(f"  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*60}")
    for method, url, with_auth in ENDPOINTS:
        r = _try(method, url, with_auth)
        if "error" in r:
            print(f"  {method:<5}  {'Y' if with_auth else 'N':<5}  ERR     {url}\n    -> {r['error']}")
        else:
            print(f"  {method:<5}  {'Y' if with_auth else 'N':<5}  {r['status']:<6}  {url}")
            if r["status"] != 200:
                print(f"    -> {r['snippet']}")
    print()
    print("Yorum:")
    print("  200 dönen endpoint'ler → senin key'inle çalışıyor demek")
    print("  401/403 dönen → endpoint doğru ama auth şekli farklı")
    print("  404 dönen → endpoint adı yanlış")
    print("  Bunu bana yapıştır (KEY'İ DEĞİL), doğru endpoint'i kodda düzelteyim")


if __name__ == "__main__":
    main()
