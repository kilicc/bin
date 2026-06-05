"""Wallet bot vs insan davranış sınıflandırması.

Trade frekansı, position size dağılımı, time-of-day pattern üzerinden
her wallet'a "bot likelihood" skoru verir.
"""
from __future__ import annotations

import pickle
import statistics
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

DATA = Path("data")


def main():
    trades = pickle.load(open(DATA / "history_trades.pkl", "rb"))
    print(f"Yüklendi: {len(trades):,} trade")

    by_wallet = defaultdict(list)
    for t in trades:
        by_wallet[t.wallet].append(t)

    print(f"\n{'wallet':<44}  {'n':>5}  {'med_gap':>8}  {'sizes':>15}  {'class':>14}")
    print(f"{'-'*44}  {'-'*5}  {'-'*8}  {'-'*15}  {'-'*14}")

    rows = []
    for wallet, ts_list in by_wallet.items():
        if len(ts_list) < 10:
            continue
        sorted_ts = sorted(t.timestamp for t in ts_list)
        gaps = [(sorted_ts[i+1] - sorted_ts[i]).total_seconds()
                for i in range(len(sorted_ts) - 1)]
        med_gap = statistics.median(gaps) if gaps else 0
        sizes = [t.size_usd for t in ts_list]
        med_size = statistics.median(sizes)
        max_size = max(sizes)
        # Sınıflandırma
        if med_gap < 60:
            cls = "BOT (<1min)"
        elif med_gap < 300:
            cls = "BOT? (<5min)"
        elif med_gap < 1800:
            cls = "active human"
        else:
            cls = "human"
        rows.append((wallet, len(ts_list), med_gap, med_size, max_size, cls))

    # Sort by median gap (slow = human-like first)
    rows.sort(key=lambda r: -r[2])
    for wallet, n, gap, med_sz, max_sz, cls in rows:
        gap_str = f"{gap/60:.1f}m" if gap < 3600 else f"{gap/3600:.1f}h"
        sizes_str = f"${med_sz:.0f}/${max_sz:.0f}"
        print(f"{wallet:<44}  {n:>5}  {gap_str:>8}  {sizes_str:>15}  {cls:>14}")

    # Save filtered human-like list
    human_like = {w for w, _, gap, _, _, cls in rows
                  if cls in ("human", "active human")}
    print(f"\n{len(human_like)} 'insan-benzeri' wallet bulundu (median gap >= 5 min)")

    # Filter the curated whale list
    curated = pickle.load(open(DATA / "whale_watchlist_curated.pkl", "rb"))
    print(f"\nMevcut curated whale listesi: {len(curated)}")
    print(f"Bunlardan kaçı human-like: {len(set(curated) & human_like)}")
    if curated & human_like:
        print(f"Human-like whale'ler:")
        for w in (curated & human_like):
            print(f"  {w}")

    # Save the intersection (curated AND human-like)
    final = curated & human_like
    if final:
        pickle.dump(final, open(DATA / "whale_watchlist_humans.pkl", "wb"))
        print(f"\n{len(final)} cüzdan data/whale_watchlist_humans.pkl olarak kaydedildi")


if __name__ == "__main__":
    main()
