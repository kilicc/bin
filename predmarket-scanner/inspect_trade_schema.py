"""Polymarket data-api /trades response şemasını yazdır.

Tek bir trade nasıl görünüyor? Pagination nasıl yapılıyor?
Bu script bir örnek alıp tüm field'larını ve değer tiplerini gösterir.
"""
from __future__ import annotations

import json
import sys

import httpx


def main():
    print("=== Sample (limit=3) ===")
    r = httpx.get("https://data-api.polymarket.com/trades?limit=3", timeout=15.0)
    r.raise_for_status()
    data = r.json()
    print(f"Returned: {len(data)} kayıt\n")
    if not data:
        print("Boş — başka filter dene")
        sys.exit(1)

    # Tüm field'ları topla
    all_fields = set()
    for t in data:
        all_fields.update(t.keys())

    print(f"Toplam {len(all_fields)} field:\n")
    sample = data[0]
    for f in sorted(all_fields):
        v = sample.get(f)
        vtype = type(v).__name__
        if isinstance(v, str) and len(v) > 60:
            v_show = v[:60] + "..."
        else:
            v_show = v
        print(f"  {f:<30} ({vtype:<8})  {v_show}")

    print("\n=== Full JSON of first trade ===")
    print(json.dumps(sample, indent=2, default=str)[:1500])

    print("\n=== Pagination test (offset=10) ===")
    r2 = httpx.get("https://data-api.polymarket.com/trades?limit=3&offset=10", timeout=15.0)
    r2.raise_for_status()
    data2 = r2.json()
    print(f"offset=10 → {len(data2)} kayıt")
    if data2 and data:
        same_ids = (data[0].get("transactionHash") == data2[0].get("transactionHash"))
        print(f"İlk kayıt tekrar etti mi? {same_ids} (False olmalı = pagination çalışıyor)")


if __name__ == "__main__":
    main()
