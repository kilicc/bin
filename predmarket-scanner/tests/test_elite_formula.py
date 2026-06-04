"""Elite formula unit tests."""
from elite_trader.pattern_miner import _market_theme, mine_patterns
from elite_trader.success_formula import MarketFeatures, SuccessFormula
from elite_trader.pnl_engine import PnLEngine
from elite_trader.hourly_pacing import HourlyPacing
from markets.wallets import WalletTrade
from datetime import datetime, timezone


def test_market_theme():
    assert _market_theme("Bitcoin above 100k") == "crypto"
    assert _market_theme("Lakers vs Celtics spread") == "sports"


def test_formula_score():
    from elite_trader.pattern_miner import ElitePatterns

    p = ElitePatterns(
        price_bucket_wr={"0.5-0.6": 0.85},
        theme_wr={"crypto": 0.7},
    )
    f = SuccessFormula.from_patterns(p, elite_wallets=["0xabc"])
    ok, score, _ = f.should_trade(
        MarketFeatures(
            yes_price=0.55,
            side="YES",
            edge=0.12,
            hours_left=12.0,
            spread=0.02,
            momentum=0.01,
            theme="crypto",
        )
    )
    assert score > 0.4


def test_pnl_cap():
    pnl = PnLEngine.cap_sl_pnl(-500, 600, 0.025)
    assert pnl >= -15.1


def test_hourly_pacing():
    from datetime import datetime, timezone, timedelta

    p = HourlyPacing(target_usd_per_hour=800, realized_pnl=400)
    p.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    assert p.pace_ratio() > 0
    assert p.compute_realistic_hourly_cap() > 0
    assert p.pace_vs_realistic() >= 0


def test_pnl_unrealized_no_side():
    pnl = PnLEngine.unrealized("NO", 0.53, 0.52, 100.0)
    assert pnl > 0


def test_market_guards_cluster():
    from elite_trader.market_guards import event_cluster_key, is_bracket_or_strike_market

    q1 = 'Will "Michael" 4th Weekend Box Office be greater than 25m?'
    q2 = 'Will "Michael" 4th Weekend Box Office be between 22m and 25m?'
    assert event_cluster_key(q1) == event_cluster_key(q2)
    assert is_bracket_or_strike_market(q1)
    assert is_bracket_or_strike_market("Will Ethereum dip to $2,150 on May 16?")


def test_entry_price_band():
    from elite_trader.market_guards import entry_price_ok

    assert not entry_price_ok("YES", 0.238)
    assert entry_price_ok("YES", 0.55)


def test_attribution_build():
    from elite_trader.attribution import build_report

    r = build_report(include_backups=False)
    assert r.closed_count >= 0
    assert r.bottleneck in (
        "target_math",
        "market",
        "formula",
        "insufficient_data",
    )
