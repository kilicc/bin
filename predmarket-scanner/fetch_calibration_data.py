"""Closed market'lerden fiyat zaman serileri çek — calibration için.

Pipeline:
  1. Gamma'dan tüm closed market'leri çek (volume eşiği)
  2. Her market için clobTokenIds parse, YES token al
  3. CLOB prices-history endpoint'inden interval=max ile tüm price path'i çek
  4. Her (timestamp, price) için: (price, hours_to_close, eventual_outcome) topla
  5. Pickle olarak kaydet → analyze_calibration.py kullanır

Cache: gördüğü conditionId'leri pickle'a yazar, kesintilerden sonra devam eder.
"""
from __future__ import annotations

import json
import pickle
import signal
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

MIN_VOLUME = 1000.0           # $1000+ hacimli market'ler
MAX_MARKETS = 3000            # ilk N market (test için sınır)
PRICE_HISTORY_INTERVAL = "max"

CACHE_DATAPOINTS = DATA / "calibration_data.pkl"
CACHE_PROGRESS = DATA / "calibration_progress.pkl"


class Progress:
    def __init__(self):
        self.processed: set[str] = set()
        self.datapoints: list[tuple] = []  # (price, hours_to_close, outcome)

    @classmethod
    def load(cls):
        if CACHE_PROGRESS.exists():
            try:
                return pickle.load(open(CACHE_PROGRESS, "rb"))
            except Exception:
                pass
        return cls()

    def save(self):
        pickle.dump(self, open(CACHE_PROGRESS, "wb"))


def parse_outcome(prices_raw) -> bool | None:
    if isinstance(prices_raw, str):
        try:
            prices = json.loads(prices_raw)
        except Exception:
            return None
    else:
        prices = prices_raw
    if not prices or len(prices) < 2:
        return None
    try:
        yes, no = float(prices[0]), float(prices[1])
    except (ValueError, TypeError):
        return None
    if yes > 0.5 and no < 0.5:
        return True
    if no > 0.5 and yes < 0.5:
        return False
    return None  # voided/draw


def fetch_closed_markets(client: httpx.Client, max_markets: int) -> list[dict]:
    """Gamma'dan yüksek hacimli closed market'ler."""
    out = []
    offset = 0
    page_size = 500
    while len(out) < max_markets:
        r = client.get(f"{GAMMA}/markets", params={
            "closed": "true", "limit": page_size, "offset": offset,
            "order": "endDate", "ascending": "false",
        }, timeout=15.0)
        if r.status_code != 200:
            print(f"[gamma] offset={offset} status={r.status_code}")
            break
        batch = r.json()
        if not batch:
            break
        # filtre
        for m in batch:
            try:
                v = float(m.get("volume") or 0)
            except (TypeError, ValueError):
                v = 0
            if v < MIN_VOLUME:
                continue
            if parse_outcome(m.get("outcomePrices")) is None:
                continue
            out.append(m)
        offset += page_size
        if len(batch) < page_size:
            break
        time.sleep(0.10)
    return out[:max_markets]


def fetch_price_history(client: httpx.Client, token_id: str) -> list[dict]:
    """CLOB prices-history; başarısızsa boş döner."""
    try:
        r = client.get(f"{CLOB}/prices-history", params={
            "market": token_id, "interval": PRICE_HISTORY_INTERVAL,
        }, timeout=20.0)
        if r.status_code != 200:
            return []
        return (r.json() or {}).get("history") or []
    except httpx.HTTPError:
        return []


def main():
    progress = Progress.load()
    print(f"Mevcut progress: {len(progress.processed)} market, "
          f"{len(progress.datapoints):,} data point")

    stopped = False
    def _stop(*a):
        nonlocal stopped
        stopped = True
        print("\n[Ctrl+C] state kaydedilip durdurulacak...")
    signal.signal(signal.SIGINT, _stop)

    client = httpx.Client(
        timeout=20.0,
        headers={"User-Agent": "predmarket-scanner-cal/0.1",
                 "Accept": "application/json"},
    )

    print(f"\n=== Closed market listesi çekiliyor (min vol=${MIN_VOLUME:.0f}) ===")
    markets = fetch_closed_markets(client, MAX_MARKETS)
    print(f"   {len(markets)} aday market\n")

    t0 = time.time()
    skipped = 0
    no_history = 0
    for i, m in enumerate(markets, 1):
        if stopped:
            break
        cid = (m.get("conditionId") or "").lower()
        if not cid or cid in progress.processed:
            skipped += 1
            continue

        outcome = parse_outcome(m.get("outcomePrices"))
        if outcome is None:
            progress.processed.add(cid)
            continue

        tokens_raw = m.get("clobTokenIds")
        if isinstance(tokens_raw, str):
            try:
                tokens = json.loads(tokens_raw)
            except Exception:
                tokens = []
        else:
            tokens = tokens_raw or []
        if not tokens:
            progress.processed.add(cid)
            continue
        yes_token = tokens[0]

        # End time — close timestamp veya endDate
        end_str = m.get("closedTime") or m.get("endDate")
        if not end_str:
            progress.processed.add(cid)
            continue
        try:
            end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            end_ts = end_dt.timestamp()
        except Exception:
            progress.processed.add(cid)
            continue

        history = fetch_price_history(client, yes_token)
        if not history:
            no_history += 1
            progress.processed.add(cid)
            time.sleep(0.10)
            continue

        added = 0
        for h in history:
            try:
                t = int(h.get("t") or 0)
                p = float(h.get("p") or 0)
            except (TypeError, ValueError):
                continue
            if not (0 < p < 1):
                continue
            hours_to_close = max(0.0, (end_ts - t) / 3600.0)
            progress.datapoints.append((p, hours_to_close, outcome))
            added += 1
        progress.processed.add(cid)

        if i % 25 == 0:
            elapsed = time.time() - t0
            rate = i / max(1, elapsed)
            print(f"   {i:>4}/{len(markets)}  processed={len(progress.processed):,}  "
                  f"datapoints={len(progress.datapoints):,}  "
                  f"no_hist={no_history}  rate={rate:.1f}/s  elapsed={elapsed:.0f}s")
            progress.save()
        time.sleep(0.10)

    progress.save()
    pickle.dump(progress.datapoints, open(CACHE_DATAPOINTS, "wb"))

    print(f"\n=== Tamamlandı ===")
    print(f"  processed: {len(progress.processed)}")
    print(f"  data points: {len(progress.datapoints):,}")
    print(f"  no_history: {no_history}")
    print(f"  saved: {CACHE_DATAPOINTS}")
    client.close()


if __name__ == "__main__":
    main()
