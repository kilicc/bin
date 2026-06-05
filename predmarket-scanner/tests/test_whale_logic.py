"""Whale-copy mimarisi smoke testleri.
Çalıştırmak için:  python tests/test_whale_logic.py
"""
from __future__ import annotations

import sys, os, importlib.util, types
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(modname: str, relpath: str):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(modname, os.path.join(here, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# Stub'lar — pydantic gerektiren paketleri bypass et
sys.modules.setdefault("markets", types.ModuleType("markets"))


def test_wallet_ranking_and_pareto():
    # markets.wallets standalone (pydantic kullanmıyor)
    wallets_mod = _load("markets.wallets", "markets/wallets.py")
    scoring = _load("core.wallet_scoring_direct", "core/wallet_scoring.py")

    WalletStats = wallets_mod.WalletStats
    pool = [
        WalletStats("whale1", 150, 120, 30, 5_000, 20_000),   # WR 80%, ROI 25%
        WalletStats("whale2", 200, 145, 55, 3_500, 50_000),   # WR 72.5%, ROI 7% (ROI eşiği fail)
        WalletStats("noise",   80,  60, 20,   500,  5_000),   # WR 75% ama trade<100
        WalletStats("loser",  500, 200, 300,-1_000, 50_000),  # WR 40%
        WalletStats("huge",   300, 230, 70, 50_000, 100_000), # WR 76.7%, ROI 50%
    ]
    # Default: rank by wilson_lower_bound; both whale1 (n=150) and huge (n=300) qualify,
    # huge has larger n so its WLB is closer to its WR; either order acceptable
    top = scoring.rank_wallets(pool, scoring.RankingCriteria())
    names = [s.wallet for s in top]
    assert set(names) == {"huge", "whale1"}, f"got {names}"
    conc = scoring.pareto_concentration(pool, top_k=2)
    assert 0.90 <= conc <= 1.0, f"pareto={conc}"
    print(f"test_wallet_ranking_and_pareto OK (top=huge,whale1; pareto={conc:.3f})")


def test_consensus_rules():
    cons = _load("core.consensus_direct", "core/consensus.py")
    Vote, AgentVote, decide = cons.Vote, cons.AgentVote, cons.decide

    # 3 ajan da YES → full
    d = decide([AgentVote("a", Vote.BUY_YES, 1.0),
                AgentVote("b", Vote.BUY_YES, 1.0),
                AgentVote("c", Vote.BUY_YES, 1.0)])
    assert d.size_multiplier == 1.0 and d.vote == Vote.BUY_YES

    # 2 YES, 1 PASS → full
    d = decide([AgentVote("a", Vote.BUY_YES, 1.0),
                AgentVote("b", Vote.BUY_YES, 1.0),
                AgentVote("c", Vote.NO_TRADE, 0.0)])
    assert d.size_multiplier == 1.0

    # 1 YES, 1 NO, 1 pass → çatışma → no trade
    d = decide([AgentVote("a", Vote.BUY_YES, 1.0),
                AgentVote("b", Vote.BUY_NO, 1.0),
                AgentVote("c", Vote.NO_TRADE, 0.0)])
    assert d.size_multiplier == 0.0

    # 1 alone → half size
    d = decide([AgentVote("a", Vote.BUY_NO, 1.0),
                AgentVote("b", Vote.NO_TRADE, 0.0),
                AgentVote("c", Vote.NO_TRADE, 0.0)])
    assert d.size_multiplier == 0.5 and d.vote == Vote.BUY_NO

    # Hepsi pass → no trade
    d = decide([AgentVote("a", Vote.NO_TRADE, 0.0)] * 3)
    assert d.size_multiplier == 0.0
    print("test_consensus_rules OK")


def test_exit_policy():
    exit_mod = _load("core.exit_policy_direct", "core/exit_policy.py")
    Snap = exit_mod.PositionSnapshot
    cfg = exit_mod.ExitConfig()
    now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)

    # 1) Capture %85 triggers (0.30 → 0.48 = 90% of 0.20 expected)
    s = Snap("m", "YES", entry_price=0.30, expected_target=0.50,
             opened_at=now - timedelta(hours=2),
             current_price=0.48, recent_volume=100, baseline_volume=100,
             settlement_at=now + timedelta(days=10))
    exit_now, reason = exit_mod.should_exit(s, cfg, now=now)
    assert exit_now and "captured" in reason, reason

    # 2) Volume spike triggers
    s2 = Snap("m", "YES", 0.30, 0.50, now - timedelta(hours=1),
              0.32, recent_volume=500, baseline_volume=100,
              settlement_at=now + timedelta(days=10))
    exit_now, reason = exit_mod.should_exit(s2, cfg, now=now)
    assert exit_now and "spike" in reason, reason

    # 3) Pre-settlement buffer triggers
    s3 = Snap("m", "YES", 0.30, 0.50, now - timedelta(hours=1),
              0.32, recent_volume=100, baseline_volume=100,
              settlement_at=now + timedelta(hours=2))
    exit_now, reason = exit_mod.should_exit(s3, cfg, now=now)
    assert exit_now and "pre-settlement" in reason, reason

    # 4) Henüz çıkma
    s4 = Snap("m", "YES", 0.30, 0.50, now - timedelta(hours=1),
              0.34, recent_volume=100, baseline_volume=100,
              settlement_at=now + timedelta(days=10))
    exit_now, reason = exit_mod.should_exit(s4, cfg, now=now)
    assert not exit_now, reason
    print("test_exit_policy OK")


def test_whale_tracker_dedupe():
    # Once stub markets.wallets so whale_tracker can import it
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wallets_mod = _load("markets.wallets", "markets/wallets.py")
    tracker_mod = _load("core.whale_tracker_direct", "core/whale_tracker.py")

    WalletTrade = wallets_mod.WalletTrade
    now = datetime.now(timezone.utc)
    trades = [
        WalletTrade("w1", "m1", "YES", 0.30, 100.0, "open", now, tx_hash="0xa"),
        WalletTrade("w1", "m1", "YES", 0.30, 100.0, "open", now, tx_hash="0xa"),  # dup
        WalletTrade("w1", "m2", "NO",  0.40,  50.0, "open", now, tx_hash="0xb"),
        WalletTrade("w2", "m1", "YES", 0.31,  20.0, "close", now, tx_hash="0xc"), # close, skip
    ]
    def fetcher(addrs, since): return [t for t in trades if t.wallet in set(addrs)]
    t = tracker_mod.WhaleTracker(watch_list={"w1", "w2"}, fetcher=fetcher)
    first = t.poll(now=now)
    assert len(first) == 2 and {e.raw.tx_hash for e in first} == {"0xa", "0xb"}
    # İkinci pollda hepsi dup
    second = t.poll(now=now)
    assert len(second) == 0
    print("test_whale_tracker_dedupe OK")


if __name__ == "__main__":
    test_wallet_ranking_and_pareto()
    test_consensus_rules()
    test_exit_policy()
    test_whale_tracker_dedupe()
    print("\nALL WHALE-LOGIC TESTS PASSED")
