"""End-to-end backtest runner.

Çalıştır:  python run_backtest.py

Sentetik 100-günlük evren üretir → 5 estimator karşılaştırması →
parameter sweep → final rapor.
"""
from __future__ import annotations

import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest.engine import (
    BacktestConfig, market_baseline, momentum_estimator,
    whale_consensus_estimator_factory, run_backtest,
)
from backtest.optimizer import grid_search
from backtest.synthetic import generate
from markets.wallets import aggregate_stats
from core.wallet_scoring import rank_wallets, RankingCriteria, pareto_concentration


def main():
    print("=" * 70)
    print(" SENTETİK BACKTEST — 100 günlük prediction market evreni")
    print("=" * 70)

    # 1) Universe
    print("\n[1] Sentetik evren üretiliyor...")
    universe = generate(
        n_markets=200,
        n_wallets=800,
        pct_edge_wallets=0.08,
        horizon_days=100,
        ticks_per_day=6,
        seed=42,
    )
    n_resolved = sum(1 for m in universe.markets if m.resolved_yes is not None)
    print(f"   markets={len(universe.markets)} (resolved={n_resolved})")
    print(f"   trades={len(universe.trades)}")
    print(f"   wallets={len(universe.wallet_edge)} "
          f"(edge'li={sum(1 for v in universe.wallet_edge.values() if v>0)})")

    # 2) Wallet ranking — tweet 3'ün "47 wallet bul" karşılığı
    print("\n[2] Wallet ranking (90 günlük)...")
    market_outcomes = {m.market_id: m.resolved_yes for m in universe.markets
                       if m.resolved_yes is not None}
    stats = aggregate_stats(universe.trades, market_outcomes)
    print(f"   total wallets in stats: {len(stats)}")
    top = rank_wallets(stats.values(), RankingCriteria(
        min_trades=20, min_win_rate=0.53, min_volume_usd=200,
        min_roi=0.03, min_wilson_wr=0.48, top_n=50, rank_by="wilson"))
    print(f"   ranked top: {len(top)} wallets")
    if top:
        pc = pareto_concentration(list(stats.values()), top_k=20)
        print(f"   pareto (top-20 / total positive): {pc:.2%}")
        # Recall: ne kadarı gerçekten edge'li?
        edge_set = {w for w, v in universe.wallet_edge.items() if v > 0}
        precision = sum(1 for s in top if s.wallet in edge_set) / len(top)
        recall = sum(1 for s in top if s.wallet in edge_set) / max(1, len(edge_set))
        print(f"   precision={precision:.2%}  recall={recall:.2%}")
        print(f"   (precision = top-N içinde gerçek edge'li oranı; "
              f"recall = gerçek edge'lilerin yakalanan oranı)")

    whale_set = {s.wallet for s in top}

    # 3) Build trades index per market for whale estimator
    trades_by_market = defaultdict(list)
    for t in universe.trades:
        trades_by_market[t.market_id].append(t)

    # 4) Estimator karşılaştırması
    print("\n[3] Estimator karşılaştırması (default config)...")
    estimators = {
        "market_baseline": market_baseline,
        "momentum":         momentum_estimator,
        "whale_consensus":  whale_consensus_estimator_factory(
            whale_wallets=whale_set,
            trades_by_market_time=trades_by_market,
            confidence=0.55, weight=0.20,
        ),
    }
    cfg = BacktestConfig(starting_balance=2000.0, edge_threshold=0.06,
                         kelly_fraction=0.25, max_position_usd=50.0,
                         fee_rate=0.02, slippage=0.01, min_confidence=0.25)

    reports = {}
    for name, est in estimators.items():
        rep = run_backtest(universe, est, cfg)
        reports[name] = rep
        print(f"   {name:18s}  {rep.pretty()}")

    # 5) Grid search — whale_consensus üzerinde
    print("\n[4] Parameter sweep (whale_consensus)...")
    grid = grid_search(
        universe,
        whale_consensus_estimator_factory(whale_set, trades_by_market, 0.55, 0.20),
        edge_thresholds=(0.03, 0.05, 0.07, 0.10),
        kelly_fractions=(0.10, 0.25, 0.50),
        min_confidences=(0.20, 0.30, 0.40, 0.50),
    )
    print("   top 5 configs by composite score:")
    for g in grid[:5]:
        print(f"     edge={g.edge_threshold:.2f}  kelly={g.kelly_fraction:.2f}  "
              f"conf={g.min_confidence:.2f}  →  {g.report.pretty()}")

    # 6) Walk-forward: train ilk %60, test son %40 — out-of-sample asıl önemli
    print("\n[5] Walk-forward — train ilk %60, test son %40...")
    sorted_trades = sorted(universe.trades, key=lambda t: t.timestamp)
    cut_idx = int(len(sorted_trades) * 0.60)
    cut_time = sorted_trades[cut_idx].timestamp
    train_trades = [t for t in sorted_trades if t.timestamp <= cut_time]
    # Sadece train'de zaten resolved olmuş market'ler kullanılabilir
    train_resolved = {m.market_id: m.resolved_yes for m in universe.markets
                      if m.resolved_yes is not None and m.end_date <= cut_time}
    train_stats = aggregate_stats(train_trades, train_resolved)

    # Birkaç ranking criteria dene → in-sample best'i seç
    print("   ranking criteria sweep (train period)...")
    criteria_grid = [
        RankingCriteria(min_trades=10, min_win_rate=0.52, min_volume_usd=100,
                        min_roi=0.02, min_wilson_wr=0.45, top_n=80, rank_by="wilson"),
        RankingCriteria(min_trades=15, min_win_rate=0.52, min_volume_usd=150,
                        min_roi=0.02, min_wilson_wr=0.47, top_n=60, rank_by="wilson"),
        RankingCriteria(min_trades=20, min_win_rate=0.53, min_volume_usd=200,
                        min_roi=0.03, min_wilson_wr=0.48, top_n=50, rank_by="wilson"),
        RankingCriteria(min_trades=30, min_win_rate=0.53, min_volume_usd=300,
                        min_roi=0.03, min_wilson_wr=0.50, top_n=40, rank_by="wilson"),
    ]
    edge_set = {w for w, v in universe.wallet_edge.items() if v > 0}
    best_train_pnl = -1e18
    best_whales: set[str] = set()
    best_crit: RankingCriteria | None = None
    # Cache train universe + train trades index outside the loop
    train_trades_by_market = defaultdict(list)
    for t in train_trades:
        train_trades_by_market[t.market_id].append(t)
    train_uni = type(universe)(
        markets=[m for m in universe.markets if m.end_date <= cut_time],
        trades=train_trades, wallet_edge=universe.wallet_edge,
    )
    for crit in criteria_grid:
        whales = {s.wallet for s in rank_wallets(train_stats.values(), crit)}
        if not whales:
            print(f"     min_trades={crit.min_trades:3d}  wilson>={crit.min_wilson_wr:.2f}  → 0 whales (skipped)")
            continue
        train_est = whale_consensus_estimator_factory(whales, train_trades_by_market, 0.55, 0.20)
        prec = sum(1 for w in whales if w in edge_set) / len(whales)
        tr_rep = run_backtest(train_uni, train_est, cfg)
        score = tr_rep.total_pnl
        print(f"     min_trades={crit.min_trades:3d}  wilson>={crit.min_wilson_wr:.2f}  "
              f"→ whales={len(whales):3d}  precision={prec:.2%}  train_PnL=${tr_rep.total_pnl:+,.0f}")
        if score > best_train_pnl:
            best_train_pnl = score
            best_whales = whales
            best_crit = crit

    if best_crit is None:
        print("   no criteria produced whales; OOS test skipped")
        return
    train_precision_best = sum(1 for w in best_whales if w in edge_set) / max(1, len(best_whales))
    print(f"   BEST train criteria: min_trades={best_crit.min_trades}, "
          f"wilson>={best_crit.min_wilson_wr:.2f}, whales={len(best_whales)}, "
          f"in-sample precision={train_precision_best:.2%}")

    # Out-of-sample test
    test_trades_by_market = defaultdict(list)
    for t in sorted_trades[cut_idx:]:
        test_trades_by_market[t.market_id].append(t)
    test_uni = type(universe)(
        markets=[m for m in universe.markets if m.end_date > cut_time],
        trades=[t for t in sorted_trades if t.timestamp > cut_time],
        wallet_edge=universe.wallet_edge,
    )
    test_est = whale_consensus_estimator_factory(best_whales, test_trades_by_market, 0.55, 0.20)
    test_rep = run_backtest(test_uni, test_est, cfg)
    print(f"   OUT-OF-SAMPLE: {test_rep.pretty()}")

    # 7) Final özet
    print("\n" + "=" * 70)
    print(" ÖZET")
    print("=" * 70)
    base = reports["market_baseline"]
    whale = reports["whale_consensus"]
    print(f"  Market baseline Brier:   {base.brier:.4f}")
    print(f"  Whale-consensus Brier:   {whale.brier:.4f}  "
          f"({'iyileşme' if whale.brier < base.brier else 'baseline tutuyor / kötü'})")
    print(f"  Baseline trade sayısı:   {base.n_trades}  (edge=0 olduğu için 0 olmalı)")
    print(f"  Whale-consensus PnL:     ${whale.total_pnl:+,.0f}  on ${cfg.starting_balance:,.0f}")
    print(f"  Out-of-sample whale PnL: ${test_rep.total_pnl:+,.0f}")
    print()
    print("  YORUM:")
    print("  - Bu evrende edge gerçekten var (sentetik); whale-consensus baseline'ı yenmeli")
    print("  - Gerçek Polymarket verisinde bu sonuçların tekrarı GARANTİ DEĞİL")
    print("  - Walk-forward out-of-sample PnL > 0 ise mimari mantıklı")
    print("  - Hâlâ paper'da en az 30 gün koş, sonra fractional Kelly ile başla")


if __name__ == "__main__":
    main()
