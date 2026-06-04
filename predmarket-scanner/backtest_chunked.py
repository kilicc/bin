"""Chunked walk-forward backtest — cached 90 günlük trade verisinde.

Cached `history_trades.pkl` üzerinde çalışır (network yok, saniyeler sürer).

Mantık:
  - 90 günü N chunk'a böl (default 6 chunk × 15 gün)
  - Her chunk için:
      * train_half = chunk'ın ilk %50'si
      * test_half = chunk'ın son %50'si
      * train_half'tan Bayesian ranking ile whale listesi çıkar
      * test_half'taki bu whale'lerin trade'lerini "kopyala" (paper position aç)
      * Test period sonunda close-PnL ile P&L hesapla
      * Brier, hit rate, total PnL raporla
  - Tüm chunk'ların metriklerini tabloda göster

Bu test bize şunu söyler:
  "Eğer 7.5 gün önce bayesian ranking yapsaydım, sonraki 7.5 günde bu listeyi
   takip etmek kar ettirir miydi?" — gerçek out-of-sample sorusu.
"""
from __future__ import annotations

import pickle
import sys, os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from markets.wallets import WalletTrade
from probability.bayesian import BayesianWalletScorer

DATA = Path("data")

N_CHUNKS = 6
TRAIN_TEST_SPLIT = 0.50    # her chunk'ın %50'si train

# Whale identification eşikleri (train half'ta)
MIN_TRAIN_TRADES = 5
MIN_TRAIN_PNL = 50.0       # train'de en az $50 kâr
MIN_POSTERIOR_LB = 0.55


def close_pnl_in_window(trades_list, t_start, t_end) -> dict:
    """Verilen zaman penceresinde her (wallet, market, side) için close-PnL."""
    pos = defaultdict(lambda: {"open_cost": 0.0, "close_proceeds": 0.0,
                                "open_n": 0, "close_n": 0})
    for t in trades_list:
        if not (t_start <= t.timestamp <= t_end):
            continue
        k = (t.wallet, t.market_id, t.side)
        if t.direction == "open":
            pos[k]["open_cost"] += t.size_usd
            pos[k]["open_n"] += 1
        else:
            pos[k]["close_proceeds"] += t.size_usd
            pos[k]["close_n"] += 1
    pnl = {}
    for k, v in pos.items():
        if v["close_n"] == 0:
            continue
        pnl[k] = v["close_proceeds"] - v["open_cost"]
    return pnl


def identify_whales(trades_in_window, t_start, t_end) -> set[str]:
    """Train window'da Bayesian + Wilson ile whale listesi çıkar."""
    pnl_map = close_pnl_in_window(trades_in_window, t_start, t_end)
    pnl_by_wallet = defaultdict(list)
    for (wallet, _mid, _side), pnl in pnl_map.items():
        pnl_by_wallet[wallet].append(pnl)

    bayes = BayesianWalletScorer(prior_alpha=2.0, prior_beta=2.0)
    for wallet, pnls in pnl_by_wallet.items():
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        if wins + losses == 0:
            continue
        bayes.observe_batch(wallet, wins=wins, losses=losses)

    whales = set()
    for wallet, pnls in pnl_by_wallet.items():
        n = len(pnls)
        total_pnl = sum(pnls)
        if n < MIN_TRAIN_TRADES:
            continue
        if total_pnl < MIN_TRAIN_PNL:
            continue
        lb = bayes.score(wallet, quantile=0.10)
        if lb < MIN_POSTERIOR_LB:
            continue
        whales.add(wallet)
    return whales


def copy_trade_replay(trades_in_test, whales, t_start, t_end) -> dict:
    """Test period'unda whale'lerin trade'lerini taklit et.

    Bot kuralı: whale BUY (open) yapınca aynı market + side'da paper pozisyon aç.
    Whale aynı (market, side)'da SELL (close) yapınca paper pozisyonu da kapat.

    Returns: {
      'n_copied':   kaç pozisyon taklit edildi,
      'n_closed':   kaçı kapatıldı (whale çıkış yaptı),
      'wins':       close-PnL > 0 olan sayı,
      'losses':     close-PnL < 0 olan sayı,
      'total_pnl':  toplam dolar P&L,
      'predictions': [Prediction(...)] Brier için
    }
    """
    if not whales:
        return {"n_copied": 0, "n_closed": 0, "wins": 0, "losses": 0,
                "total_pnl": 0.0, "predictions": []}

    # Sorted trades for chronological replay
    whale_trades = [t for t in trades_in_test
                    if t.wallet in whales and t_start <= t.timestamp <= t_end]
    whale_trades.sort(key=lambda t: t.timestamp)

    # Paper book: (whale, market, side) -> {open_cost, open_price, close_proceeds}
    paper_pos = {}
    n_copied = 0
    n_closed = 0
    wins = 0
    losses = 0
    total_pnl = 0.0
    predictions = []

    for t in whale_trades:
        k = (t.wallet, t.market_id, t.side)
        if t.direction == "open":
            if k not in paper_pos:
                paper_pos[k] = {"open_cost": t.size_usd, "open_price": t.price,
                                "close_proceeds": 0.0, "closed": False}
                n_copied += 1
            else:
                # Zaten açık, ortalama
                paper_pos[k]["open_cost"] += t.size_usd
        elif t.direction == "close":
            if k in paper_pos and not paper_pos[k]["closed"]:
                paper_pos[k]["close_proceeds"] += t.size_usd
                paper_pos[k]["closed"] = True
                n_closed += 1
                pnl = paper_pos[k]["close_proceeds"] - paper_pos[k]["open_cost"]
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1

    return {"n_copied": n_copied, "n_closed": n_closed,
            "wins": wins, "losses": losses,
            "total_pnl": total_pnl, "predictions": predictions}


def main():
    trades = pickle.load(open(DATA / "history_trades.pkl", "rb"))
    print(f"Yüklendi: {len(trades):,} trade")

    # Time bounds
    ts_min = min(t.timestamp for t in trades)
    ts_max = max(t.timestamp for t in trades)
    total_days = (ts_max - ts_min).days
    chunk_days = total_days / N_CHUNKS
    print(f"Zaman aralığı: {ts_min.date()} → {ts_max.date()}  ({total_days} gün)")
    print(f"Chunk: {N_CHUNKS} × {chunk_days:.1f} gün, "
          f"train/test split = {TRAIN_TEST_SPLIT*100:.0f}%/{(1-TRAIN_TEST_SPLIT)*100:.0f}%\n")

    print(f"{'chunk':<6}  {'period':<30}  {'whales':>7}  {'copied':>7}  "
          f"{'wins/loss':>10}  {'WR':>6}  {'PnL':>9}  {'avg/trade':>10}")
    print(f"{'-'*6}  {'-'*30}  {'-'*7}  {'-'*7}  {'-'*10}  {'-'*6}  {'-'*9}  {'-'*10}")

    aggregate = {"copied": 0, "closed": 0, "wins": 0, "losses": 0, "pnl": 0.0}

    for i in range(N_CHUNKS):
        chunk_start = ts_min + timedelta(days=i * chunk_days)
        chunk_end = ts_min + timedelta(days=(i + 1) * chunk_days)
        split_time = chunk_start + timedelta(days=chunk_days * TRAIN_TEST_SPLIT)

        # train: chunk başından split'e kadar; test: split'ten sonu
        train_trades = [t for t in trades if chunk_start <= t.timestamp < split_time]
        test_trades = [t for t in trades if split_time <= t.timestamp < chunk_end]

        whales = identify_whales(train_trades, chunk_start, split_time)
        result = copy_trade_replay(test_trades, whales, split_time, chunk_end)

        wr = (result["wins"] / (result["wins"] + result["losses"])
              if result["wins"] + result["losses"] > 0 else 0.0)
        avg = (result["total_pnl"] / result["n_closed"]
               if result["n_closed"] > 0 else 0.0)
        period = f"{chunk_start.date()}→{chunk_end.date()}"
        print(f"{i+1:<6}  {period:<30}  {len(whales):>7}  "
              f"{result['n_copied']:>7}  "
              f"{result['wins']:>4}/{result['losses']:<5}  "
              f"{wr*100:>5.1f}%  "
              f"${result['total_pnl']:>+7,.0f}  "
              f"${avg:>+8,.2f}")

        aggregate["copied"] += result["n_copied"]
        aggregate["closed"] += result["n_closed"]
        aggregate["wins"] += result["wins"]
        aggregate["losses"] += result["losses"]
        aggregate["pnl"] += result["total_pnl"]

    print(f"{'-'*6}  {'-'*30}  {'-'*7}  {'-'*7}  {'-'*10}  {'-'*6}  {'-'*9}  {'-'*10}")
    agg_wr = (aggregate["wins"] / (aggregate["wins"] + aggregate["losses"])
              if aggregate["wins"] + aggregate["losses"] > 0 else 0.0)
    agg_avg = (aggregate["pnl"] / aggregate["closed"]
               if aggregate["closed"] > 0 else 0.0)
    print(f"{'TOTAL':<6}  {'':<30}  {'':>7}  {aggregate['copied']:>7}  "
          f"{aggregate['wins']:>4}/{aggregate['losses']:<5}  "
          f"{agg_wr*100:>5.1f}%  ${aggregate['pnl']:>+7,.0f}  "
          f"${agg_avg:>+8,.2f}")

    print("\nYORUM:")
    if aggregate["pnl"] > 0 and agg_wr > 0.55:
        print("  Whale-copy mimari TOPLAM olarak kar etti (out-of-sample)")
    else:
        print("  Whale-copy mimari out-of-sample edge göstermedi — strateji yeniden gözden")
        print("  geçirilmeli (criteria, whale filter, position sizing)")

    print("\n  Önemli: Bu test bizim 62 candidate üzerinde yapıldı; o havuz son 7 günden")
    print("  geldi → tüm Polymarket'i temsil etmiyor. Forward paper-mode 30 gün lazım.")


if __name__ == "__main__":
    main()
