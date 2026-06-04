"""İki aşamalı gerçek Polymarket wallet ranking.

Aşama 1: Son 7 günü tam tara → en aktif top-N wallet
Aşama 2: Top-N'in 90 günlük geçmişini ayrı çek
Aşama 3: Resolved market sonuçlarını çek + aggregate
Aşama 4: Bayesian + Wilson ranking

Sonuçlar data/ klasörüne pickle olarak kaydedilir; tekrar tekrar çekmemek için.
"""
from __future__ import annotations

import os
import pickle
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from markets.polymarket_data_api import PolymarketDataAPI
from markets.wallets import WalletTrade, aggregate_stats, WalletStats
from core.wallet_scoring import rank_wallets, RankingCriteria, wilson_lower_bound
from probability.bayesian import BayesianWalletScorer


DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

RECENT_WINDOW_DAYS = 7
HISTORY_WINDOW_DAYS = 90
TOP_N_FROM_RECENT = 200       # son 7 günden en aktif kaç wallet
MIN_RECENT_TRADES = 3         # son ~3500 trade içinde min trade (cap dolayısıyla düşük)
MAX_PAGES_RECENT = 7          # API cap: max offset 3000 → 7 sayfa × 500
MAX_PAGES_PER_WALLET = 7      # wallet başına da aynı cap


def step_1_fetch_recent_active() -> tuple[list[WalletTrade], list[str]]:
    """Son 7 günü tara, en aktif top-N wallet'ı dön."""
    print("=" * 70)
    print(f" AŞAMA 1: Son {RECENT_WINDOW_DAYS} gün toplu tarama")
    print("=" * 70)
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_WINDOW_DAYS)
    t0 = time.time()
    with PolymarketDataAPI(sleep_between_pages=0.25) as api:
        trades = list(api.iter_recent_trades(since=since, max_pages=MAX_PAGES_RECENT))
    elapsed = time.time() - t0
    print(f"   {len(trades):,} trade çekildi ({elapsed:.1f}s)")

    if not trades:
        print("   [X] Hiç trade gelmedi, bağlantı veya endpoint sorunu")
        sys.exit(1)

    # Wallet trade sayıları
    cnt = Counter(t.wallet for t in trades if t.direction == "open")
    candidates = [w for w, c in cnt.most_common(TOP_N_FROM_RECENT) if c >= MIN_RECENT_TRADES]
    print(f"   {len(candidates)} wallet ≥{MIN_RECENT_TRADES} trade (son {RECENT_WINDOW_DAYS} gün)")
    if candidates:
        print(f"   en aktif top-5:")
        for w in candidates[:5]:
            print(f"     {w[:14]}... → {cnt[w]} trade")

    pickle.dump(trades, open(DATA_DIR / "recent_trades.pkl", "wb"))
    pickle.dump(candidates, open(DATA_DIR / "candidates.pkl", "wb"))
    return trades, candidates


def step_2_fetch_history(candidates: list[str]) -> list[WalletTrade]:
    """Top-N adayın 90 günlük geçmişini çek."""
    print("\n" + "=" * 70)
    print(f" AŞAMA 2: Her aday için {HISTORY_WINDOW_DAYS} günlük geçmiş")
    print("=" * 70)
    since = datetime.now(timezone.utc) - timedelta(days=HISTORY_WINDOW_DAYS)
    all_trades: list[WalletTrade] = []
    t0 = time.time()
    with PolymarketDataAPI(sleep_between_pages=0.20) as api:
        for i, addr in enumerate(candidates, 1):
            wts = list(api.iter_recent_trades(
                since=since, user=addr, max_pages=MAX_PAGES_PER_WALLET,
            ))
            all_trades.extend(wts)
            if i % 20 == 0 or i == len(candidates):
                print(f"   {i:>4}/{len(candidates)}  cum_trades={len(all_trades):,}  "
                      f"elapsed={time.time()-t0:.1f}s")
            time.sleep(0.15)
    print(f"   toplam {len(all_trades):,} historic trade")
    pickle.dump(all_trades, open(DATA_DIR / "history_trades.pkl", "wb"))
    return all_trades


def step_3_resolve_markets(trades: list[WalletTrade]) -> dict[str, bool]:
    """Tüm kapanmış market'leri tek seferde çek (~30 saniye, dakikalar değil)."""
    print("\n" + "=" * 70)
    print(f" AŞAMA 3: Market resolution (bulk fetch)")
    print("=" * 70)
    trade_market_ids = {t.market_id for t in trades}
    print(f"   trade'lerden {len(trade_market_ids)} unique market geliyor")

    t0 = time.time()
    with PolymarketDataAPI() as api:
        all_closed = api.fetch_all_closed_markets(max_pages=50, page_size=500)
    print(f"   gamma'dan {len(all_closed)} kapanmış market çekildi "
          f"({time.time()-t0:.1f}s)")

    # Bizim trade market'lerimizle eşleştir
    outcomes = {mid: all_closed[mid] for mid in trade_market_ids if mid in all_closed}
    not_yet = trade_market_ids - all_closed.keys()
    print(f"   matched: {len(outcomes)} resolved, {len(not_yet)} hala açık veya voided")

    pickle.dump(outcomes, open(DATA_DIR / "outcomes.pkl", "wb"))
    return outcomes


def _close_pnl_per_position(trades: list[WalletTrade]) -> dict:
    """Her (wallet, market, side) için close-PnL hesapla.
    Returns: {(wallet, market, side): pnl_usd}
    Wallet pozisyon açıp kapattıysa: pnl = (close_proceeds) - (open_cost).
    Hiç kapatmadıysa pozisyon hala açık — None.
    """
    legs = defaultdict(lambda: {"open_cost": 0.0, "close_proceeds": 0.0,
                                 "open_n": 0, "close_n": 0})
    for t in trades:
        k = (t.wallet, t.market_id, t.side)
        if t.direction == "open":
            legs[k]["open_cost"] += t.size_usd
            legs[k]["open_n"] += 1
        else:
            legs[k]["close_proceeds"] += t.size_usd
            legs[k]["close_n"] += 1
    pnl_map = {}
    for k, v in legs.items():
        if v["close_n"] == 0:
            continue  # hala açık, skip
        pnl_map[k] = v["close_proceeds"] - v["open_cost"]
    return pnl_map


def step_4_rank(trades: list[WalletTrade], outcomes: dict[str, bool]) -> None:
    """Frequentist (Wilson) + Bayesian (close-PnL bazlı) ranking."""
    print("\n" + "=" * 70)
    print(f" AŞAMA 4: Wilson + Bayesian ranking (close-PnL bazlı)")
    print("=" * 70)
    stats = aggregate_stats(trades, outcomes)
    print(f"   {len(stats)} unique wallet özetlendi")
    print(f"   {sum(s.trade_count for s in stats.values()):,} toplam pozisyon")

    # Close-PnL bazlı win/loss
    pnl_per_pos = _close_pnl_per_position(trades)
    pnl_by_wallet = defaultdict(list)
    for (wallet, _mid, _side), pnl in pnl_per_pos.items():
        pnl_by_wallet[wallet].append(pnl)
    n_closed_positions = sum(len(v) for v in pnl_by_wallet.values())
    print(f"   {n_closed_positions:,} kapanmış pozisyon (BUY→SELL döngüsü tamamlanmış)")

    # Frequentist
    crit_grid = [
        ("strict", RankingCriteria(min_trades=30, min_win_rate=0.55,
                                    min_volume_usd=500, min_roi=0.05,
                                    min_wilson_wr=0.52, top_n=50, rank_by="wilson")),
        ("moderate", RankingCriteria(min_trades=20, min_win_rate=0.52,
                                      min_volume_usd=300, min_roi=0.03,
                                      min_wilson_wr=0.48, top_n=50, rank_by="wilson")),
        ("loose",   RankingCriteria(min_trades=10, min_win_rate=0.50,
                                     min_volume_usd=100, min_roi=0.0,
                                     min_wilson_wr=0.45, top_n=80, rank_by="wilson")),
    ]
    print(f"\n   Frequentist (Wilson LB, close-PnL):")
    for name, crit in crit_grid:
        ranked = rank_wallets(stats.values(), crit)
        print(f"     {name:<10}  {len(ranked):>3} wallet  "
              f"(min_n={crit.min_trades}, wilson>={crit.min_wilson_wr:.2f})")
        for s in ranked[:5]:
            w_lb = wilson_lower_bound(s.win_count, s.win_count + s.loss_count)
            print(f"       {s.wallet[:14]}...  n={s.trade_count}  "
                  f"WR={s.win_rate:.2%}  WLB={w_lb:.2%}  "
                  f"PnL=${s.total_profit_usd:+,.0f}  Vol=${s.total_volume_usd:,.0f}")

    # Bayesian — close-PnL > 0 = win
    print(f"\n   Bayesian posterior (close-PnL > 0 = win):")
    bayes = BayesianWalletScorer(prior_alpha=2.0, prior_beta=2.0)
    for wallet, pnls in pnl_by_wallet.items():
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        if wins + losses == 0:
            continue
        bayes.observe_batch(wallet, wins=wins, losses=losses)

    top = bayes.top_n(50, min_n=10, quantile=0.10)
    print(f"     {len(top)} wallet (min_n=10, q=0.10)")
    for w, lb, n in top[:20]:
        wallet_pnls = pnl_by_wallet.get(w, [])
        total_pnl = sum(wallet_pnls)
        print(f"       {w[:14]}...  n={n}  posterior_LB={lb:.2%}  "
              f"total_close_PnL=${total_pnl:+,.0f}")

    # Save watchlist
    whales = {w for w, _, _ in top}
    pickle.dump(whales, open(DATA_DIR / "whale_watchlist.pkl", "wb"))
    print(f"\n   {len(whales)} cüzdan data/whale_watchlist.pkl olarak kaydedildi")

    # Spot check: top 5'i Polymarket profile URL'leri ile yazdır
    print(f"\n   Manuel inceleme için top-10 Polymarket URL'leri:")
    for w, lb, n in top[:10]:
        print(f"     https://polymarket.com/profile/{w}")


def main():
    # Cache'li çalış: aşamalar daha önce yapıldıysa atla
    use_cache = os.environ.get("USE_CACHE", "").lower() in ("1", "true", "yes")
    if use_cache and (DATA_DIR / "recent_trades.pkl").exists():
        print("[cache] recent_trades.pkl yükleniyor...")
        recent_trades = pickle.load(open(DATA_DIR / "recent_trades.pkl", "rb"))
        candidates = pickle.load(open(DATA_DIR / "candidates.pkl", "rb"))
    else:
        recent_trades, candidates = step_1_fetch_recent_active()

    if not candidates:
        print("Hiç aday wallet yok, çıkılıyor")
        sys.exit(1)

    if use_cache and (DATA_DIR / "history_trades.pkl").exists():
        print("[cache] history_trades.pkl yükleniyor...")
        history = pickle.load(open(DATA_DIR / "history_trades.pkl", "rb"))
    else:
        history = step_2_fetch_history(candidates)

    if use_cache and (DATA_DIR / "outcomes.pkl").exists():
        print("[cache] outcomes.pkl yükleniyor...")
        outcomes = pickle.load(open(DATA_DIR / "outcomes.pkl", "rb"))
    else:
        outcomes = step_3_resolve_markets(history)

    step_4_rank(history, outcomes)


if __name__ == "__main__":
    main()
