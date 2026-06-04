"""Elite trader araştırma pipeline — leaderboard + örüntü + formül."""
from __future__ import annotations

import pickle
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from elite_trader.global_selector import select_global_elite, to_leaderboard_traders
from elite_trader.leaderboard import LeaderboardTrader, fetch_leaderboard
from elite_trader.pattern_miner import mine_patterns
from elite_trader.success_formula import SuccessFormula
from markets.polymarket_data_api import PolymarketDataAPI
from markets.wallets import WalletTrade, aggregate_stats
from core.wallet_scoring import rank_wallets, RankingCriteria, wilson_lower_bound

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _is_likely_bot(t: LeaderboardTrader) -> bool:
    """Aşırı hacim / düşük PnL verimliliği — kör takip riski."""
    if t.volume_usd > 5_000_000 and t.pnl_usd < t.volume_usd * 0.02:
        return True
    if t.volume_usd > 20_000_000 and t.pnl_usd < 500_000:
        return True
    return False


def select_elite_traders(
    *,
    limit: int = 40,
    time_period: str = "MONTH",
) -> list[LeaderboardTrader]:
    raw = fetch_leaderboard(time_period=time_period, limit=limit * 2)
    filtered = [t for t in raw if t.pnl_usd > 0 and not _is_likely_bot(t)]
    return filtered[:limit]


def fetch_elite_trade_history(
    wallets: list[str],
    *,
    days: int = 30,
    max_pages_per_wallet: int = 4,
) -> list[WalletTrade]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    all_trades: list[WalletTrade] = []
    with PolymarketDataAPI(sleep_between_pages=0.25) as api:
        for i, w in enumerate(wallets, 1):
            for t in api.iter_recent_trades(
                since=since, user=w, max_pages=max_pages_per_wallet
            ):
                all_trades.append(t)
            if i % 10 == 0:
                print(f"  elite fetch {i}/{len(wallets)} cum={len(all_trades):,}")
            time.sleep(0.12)
    return all_trades


def run_full_research(
    *,
    elite_count: int = 35,
    history_days: int = 30,
    save: bool = True,
) -> tuple[SuccessFormula, list[LeaderboardTrader]]:
    print("=" * 60)
    print(" ELITE TRADER ARAŞTIRMA — başarı formülü")
    print("=" * 60)

    elites = select_elite_traders(limit=elite_count)
    print(f"  Seçilen elite: {len(elites)} cüzdan (MONTH PnL)")
    for t in elites[:5]:
        print(f"    #{t.rank} {t.username[:20]:20s} PnL=${t.pnl_usd:,.0f} vol=${t.volume_usd:,.0f}")

    wallets = [t.wallet for t in elites]
    trades = fetch_elite_trade_history(wallets, days=history_days)
    print(f"  Toplam elite trade: {len(trades):,}")

    if save:
        pickle.dump(elites, open(DATA / "elite_traders.pkl", "wb"))
        pickle.dump(trades, open(DATA / "elite_trades_research.pkl", "wb"))

    print("  Market sonuçları çekiliyor...")
    with PolymarketDataAPI() as api:
        outcomes = api.fetch_all_closed_markets(max_pages=30)

    patterns = mine_patterns(trades, outcomes)
    print(f"  Örüntü: {patterns.trades_analyzed} trade, {patterns.wallets_analyzed} cüzdan")
    for rule in patterns.rules_tr[:6]:
        print(f"    → {rule}")

    formula = SuccessFormula.from_patterns(patterns, elite_wallets=wallets)
    if save:
        formula.save()
        pickle.dump(patterns, open(DATA / "elite_patterns.pkl", "wb"))

    # Wilson doğrulama — aggregate stats
    stats = aggregate_stats(trades, outcomes)
    ranked = rank_wallets(
        stats.values(),
        RankingCriteria(min_trades=20, min_win_rate=0.55, min_wilson_wr=0.50, top_n=20),
    )
    if ranked:
        print(f"  Wilson top-{len(ranked)} (geçmiş trade örnekleme):")
        for s in ranked[:5]:
            wlb = wilson_lower_bound(s.win_count, s.win_count + s.loss_count)
            print(f"    {s.wallet[:12]}… WR={s.win_rate:.0%} wlb={wlb:.0%} n={s.trade_count}")

    print("\n" + formula.summary_tr())
    print("=" * 60)
    return formula, elites


def build_wallet_fingerprints(
    trades: list[WalletTrade],
    outcomes: dict[str, bool],
) -> dict[str, dict]:
    """Cüzdan bazlı özet — panel / rapor."""
    from collections import defaultdict

    by_w: dict[str, list] = defaultdict(list)
    for t in trades:
        by_w[t.wallet].append(t)
    fps: dict[str, dict] = {}
    for w, ts in by_w.items():
        fps[w] = {
            "trade_count": len(ts),
            "markets": len({t.market_id for t in ts}),
        }
    return fps


def run_global_research(
    *,
    elite_count: int = 40,
    history_days: int = 28,
    save: bool = True,
) -> tuple[SuccessFormula, list[LeaderboardTrader]]:
    """Çok-kategori global elite → formül v2."""
    print("=" * 60)
    print(" ELITE GLOBAL ARAŞTIRMA — çok-kategori leaderboard")
    print("=" * 60)

    global_elites = select_global_elite(max_wallets=elite_count)
    elites = to_leaderboard_traders(global_elites)
    print(f"  Global elite: {len(elites)} cüzdan")
    for g in global_elites[:5]:
        print(
            f"    {g.username[:18]:18s} PnL=${g.pnl_usd:,.0f} "
            f"kat={','.join(g.categories[:3])} skor={g.rank_score:.2f}"
        )

    wallets = [t.wallet for t in elites]
    trades = fetch_elite_trade_history(
        wallets, days=history_days, max_pages_per_wallet=5
    )
    print(f"  Toplam trade: {len(trades):,}")

    if save:
        pickle.dump(global_elites, open(DATA / "elite_global_wallets.pkl", "wb"))
        pickle.dump(trades, open(DATA / "elite_global_trades.pkl", "wb"))
        pickle.dump(elites, open(DATA / "elite_traders.pkl", "wb"))
        pickle.dump(trades, open(DATA / "elite_trades_research.pkl", "wb"))

    print("  Market sonuçları çekiliyor...")
    with PolymarketDataAPI() as api:
        outcomes = api.fetch_all_closed_markets(max_pages=30)

    fingerprints = build_wallet_fingerprints(trades, outcomes)
    if save:
        pickle.dump(fingerprints, open(DATA / "elite_wallet_fingerprints.pkl", "wb"))

    patterns = mine_patterns(trades, outcomes)
    print(f"  Örüntü: {patterns.trades_analyzed} trade, {patterns.wallets_analyzed} cüzdan")
    for rule in patterns.rules_tr[:8]:
        print(f"    → {rule}")

    formula = SuccessFormula.from_patterns(
        patterns, elite_wallets=wallets, version=2
    )
    if save:
        formula.save()
        pickle.dump(patterns, open(DATA / "elite_patterns.pkl", "wb"))

    print("\n" + formula.summary_tr())
    print("=" * 60)
    return formula, elites


if __name__ == "__main__":
    import sys

    if "--global" in sys.argv:
        run_global_research()
    else:
        run_full_research()
