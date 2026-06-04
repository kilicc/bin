"""Quality-filtered whale ranking.

fetch_and_rank.py'ın top-40'ından mikro-skalper bot'ları eler, gerçek smart
money adaylarını sıralar. Posterior LB × ortalama trade başı PnL bazlı skor.
"""
from __future__ import annotations

import pickle
from collections import defaultdict
from pathlib import Path

from probability.bayesian import BayesianWalletScorer

DATA = Path("data")
MIN_TOTAL_PNL = 500.0          # $500 toplam kar altındakileri ele (mikro-skalper)
MIN_AVG_PNL_PER_TRADE = 5.0    # $5 trade başı altındakini ele
MIN_TRADES = 15
MIN_POSTERIOR_LB = 0.55        # %55 posterior LB


def main():
    trades = pickle.load(open(DATA / "history_trades.pkl", "rb"))
    print(f"Yüklendi: {len(trades):,} trade")

    # Close-PnL per position
    pos = defaultdict(lambda: {"oc": 0.0, "cc": 0.0, "on": 0, "cn": 0})
    for t in trades:
        k = (t.wallet, t.market_id, t.side)
        if t.direction == "open":
            pos[k]["oc"] += t.size_usd
            pos[k]["on"] += 1
        else:
            pos[k]["cc"] += t.size_usd
            pos[k]["cn"] += 1
    pnl_by_wallet = defaultdict(list)
    for k, v in pos.items():
        if v["cn"] == 0:
            continue
        pnl_by_wallet[k[0]].append(v["cc"] - v["oc"])

    # Bayesian
    bayes = BayesianWalletScorer(prior_alpha=2.0, prior_beta=2.0)
    for wallet, pnls in pnl_by_wallet.items():
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        if wins + losses == 0:
            continue
        bayes.observe_batch(wallet, wins=wins, losses=losses)

    # Build quality-filtered list
    candidates = []
    for wallet, pnls in pnl_by_wallet.items():
        n = len(pnls)
        if n < MIN_TRADES:
            continue
        total_pnl = sum(pnls)
        avg_pnl = total_pnl / n
        if total_pnl < MIN_TOTAL_PNL:
            continue
        if avg_pnl < MIN_AVG_PNL_PER_TRADE:
            continue
        lb = bayes.score(wallet, quantile=0.10)
        if lb < MIN_POSTERIOR_LB:
            continue
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / n
        # Quality score: posterior LB × log(1+avg_pnl) — büyük PnL ile skill kombinasyonu
        import math
        score = lb * math.log1p(max(0.0, avg_pnl))
        candidates.append({
            "wallet": wallet, "n": n, "wr": wr, "lb": lb,
            "total_pnl": total_pnl, "avg_pnl": avg_pnl, "score": score,
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)

    print(f"\nQUALITY-FILTERED WHALES (n>={MIN_TRADES}, total>=${MIN_TOTAL_PNL:.0f}, "
          f"avg>=${MIN_AVG_PNL_PER_TRADE:.0f}, LB>={MIN_POSTERIOR_LB:.0%})")
    print(f"Bulunan: {len(candidates)} cüzdan\n")
    print(f"  {'wallet':<44}  {'n':>4}  {'WR':>6}  {'LB':>6}  "
          f"{'total$':>9}  {'avg$':>7}  score")
    for c in candidates[:20]:
        print(f"  {c['wallet']:<44}  {c['n']:>4}  {c['wr']:>5.1%}  "
              f"{c['lb']:>5.1%}  ${c['total_pnl']:>+8,.0f}  ${c['avg_pnl']:>+6,.1f}  "
              f"{c['score']:.2f}")

    # Save curated watchlist
    curated = {c["wallet"] for c in candidates[:20]}
    pickle.dump(curated, open(DATA / "whale_watchlist_curated.pkl", "wb"))
    print(f"\n{len(curated)} curated cüzdan data/whale_watchlist_curated.pkl olarak kaydedildi")

    print(f"\nManuel inceleme için profil URL'leri:")
    for c in candidates[:10]:
        print(f"  https://polymarket.com/profile/{c['wallet']}")


if __name__ == "__main__":
    main()
