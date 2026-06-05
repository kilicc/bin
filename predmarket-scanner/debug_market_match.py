"""matched=0 problemini teşhis et: trade conditionId'leri gamma'daki ile eşleşmiyor mu,
yoksa trade'lerin %100'ü hala açık market'lerde mi?
"""
from __future__ import annotations

import pickle
from collections import Counter
from pathlib import Path

import httpx

from markets.polymarket_data_api import PolymarketDataAPI, GAMMA_BASE

DATA = Path("data")


def main():
    trades = pickle.load(open(DATA / "history_trades.pkl", "rb"))
    outcomes = pickle.load(open(DATA / "outcomes.pkl", "rb"))
    print(f"trades:   {len(trades):,}")
    print(f"outcomes: {len(outcomes):,}")

    # Sample compare
    trade_cids = list({t.market_id for t in trades})
    outcome_cids = list(outcomes.keys())
    print(f"\nTrade'lerden örnek conditionId:")
    for c in trade_cids[:5]:
        print(f"  {c}")
    print(f"\nKapanmış market örneklerinden:")
    for c in outcome_cids[:5]:
        print(f"  {c}")

    # Check overlap
    overlap = set(trade_cids) & set(outcome_cids)
    print(f"\nOverlap: {len(overlap)}")

    # Spot-check: ilk trade'in condId'sini gamma'da ara
    sample_cid = trade_cids[0]
    print(f"\nGamma'da '{sample_cid}' aranıyor (3 farklı yöntem):")
    with httpx.Client(timeout=10.0) as c:
        # camelCase
        r = c.get(f"{GAMMA_BASE}/markets",
                  params={"conditionIds": sample_cid, "limit": 1})
        d = r.json() if r.status_code == 200 else []
        if d:
            m = d[0]
            print(f"  conditionIds → bulundu: closed={m.get('closed')}, "
                  f"active={m.get('active')}, archived={m.get('archived')}, "
                  f"outcomePrices={m.get('outcomePrices')}, slug={m.get('slug')[:50]}")
        else:
            print(f"  conditionIds → bulunamadı (status {r.status_code})")

    # En popüler 5 trade market'inin durumu nedir
    cnt = Counter(t.market_id for t in trades)
    print(f"\nEn aktif 5 market (trade adedi):")
    for cid, n in cnt.most_common(5):
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{GAMMA_BASE}/markets",
                      params={"conditionIds": cid, "limit": 1})
            d = r.json() if r.status_code == 200 else []
            status = "?"
            if d:
                m = d[0]
                status = (f"closed={m.get('closed')} "
                          f"active={m.get('active')} "
                          f"outcomePrices={m.get('outcomePrices')} "
                          f"slug={(m.get('slug') or '')[:40]}")
            print(f"  {cid[:14]}... ({n} trade)  {status}")


if __name__ == "__main__":
    main()
