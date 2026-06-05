"""Smoke tests — pydantic/httpx olmadan çalışır.
Çalıştırmak için:  python -m tests.test_edge_math
"""
from __future__ import annotations

import sys, os, importlib.util
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# core/__init__.py pydantic'i çekiyor; doğrudan dosyaları yükle ki test edebilelim.

def _load(modname: str, relpath: str):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(modname, os.path.join(here, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    # core/edge.py markets.base'i import ediyor; sadece kelly_fraction'ı test etmek için stub geç
    spec.loader.exec_module(mod)
    return mod


# Stub markets.base & probability.base — sadece type referans olarak gerekli
class _Stub:
    pass
sys.modules.setdefault("markets", type(sys)("markets"))
sys.modules.setdefault("markets.base", type(sys)("markets.base"))
sys.modules["markets.base"].Market = _Stub
sys.modules.setdefault("probability", type(sys)("probability"))
sys.modules.setdefault("probability.base", type(sys)("probability.base"))
sys.modules["probability.base"].ProbabilityEstimate = _Stub

from math import isclose


def test_kelly_basic():
    edge = _load("core_edge_direct", "core/edge.py")
    kelly_fraction = edge.kelly_fraction
    # Adil oran: p=0.5, price=0.5 → kelly=0
    assert isclose(kelly_fraction(0.5, 0.5), 0.0, abs_tol=1e-9)
    # Edge'li: p=0.7, price=0.5 (b=1) → f = (0.7*1 - 0.3)/1 = 0.4
    assert isclose(kelly_fraction(0.7, 0.5), 0.4, abs_tol=1e-9)
    # Negatif edge: p=0.3, price=0.5 → klip 0
    assert kelly_fraction(0.3, 0.5) == 0.0
    # Tweet örneği: market 0.13, true 0.70 → b=(1/0.13-1)=6.692; f=(0.7*6.692-0.3)/6.692
    expected = (0.7 * (1/0.13 - 1) - 0.3) / (1/0.13 - 1)
    assert isclose(kelly_fraction(0.7, 0.13), expected, abs_tol=1e-9)
    print("test_kelly_basic OK")


def test_breakeven_winrate():
    """Tweet 'win rate 1/4 yeter' iddiası: 0.20 cent kontratta breakeven = 0.20."""
    edge = _load("core_edge_direct2", "core/edge.py")
    kelly_fraction = edge.kelly_fraction
    # 20c kontratta payoff oranı = (1/0.2 - 1) = 4:1; breakeven p = 0.20
    # p=0.20'da kelly tam sıfır olmalı
    assert isclose(kelly_fraction(0.20, 0.20), 0.0, abs_tol=1e-9)
    # p=0.25'te küçük pozitif kelly
    f = kelly_fraction(0.25, 0.20)
    assert f > 0 and f < 0.1
    print(f"test_breakeven_winrate OK (kelly at p=0.25, price=0.20 → {f:.4f})")


def test_signals_composite_bounds():
    """composite_bias [-0.5, +0.5] aralığında kalmalı, ne olursa olsun."""
    sig = _load("core_signals_direct", "core/signals.py")
    SignalContext, composite_bias, TickEvent = sig.SignalContext, sig.composite_bias, sig.TickEvent
    from datetime import datetime, timedelta, timezone

    # Extreme: spot strike'tan çok yukarıda + büyük momentum
    now = datetime.now(timezone.utc)
    ticks = [TickEvent(ts=now - timedelta(seconds=i), yes_price=0.5 + 0.4 * (1 - i/20),
                       yes_size=100, no_size=100) for i in range(20)]
    ctx = SignalContext(
        market_id="x",
        market_yes_price=0.5,
        end_date=now + timedelta(days=3),
        underlying_spot=300.0,
        strike=200.0,
        tick_history=ticks,
    )
    b = composite_bias(ctx, category="crypto")
    assert -0.5 <= b <= 0.5, f"bias out of range: {b}"
    print(f"test_signals_composite_bounds OK (bias={b:+.4f})")


def test_timing_tracker():
    timing = _load("core_timing_direct", "core/timing.py")
    t = timing.LatencyTracker()
    with t.measure("hot_path"):
        sum(range(1000))
    r = t.report()
    assert "hot_path" in r and r["hot_path"]["n"] == 1
    print(f"test_timing_tracker OK (p50={r['hot_path']['p50']:.4f}ms)")


def test_reconciler_diff():
    # PaperPosition is a dataclass; portfolio/paper imports config which imports dotenv.
    # Define a minimal stand-in with the same attributes.
    from dataclasses import dataclass
    @dataclass
    class PP:
        id: int; venue: str; market_id: str; side: str
        entry_price: float; contracts: float; stake_usd: float

    # Inject stub into the module the reconciler imports
    import types
    pkg = types.ModuleType("portfolio"); sys.modules["portfolio"] = pkg
    paper_mod = types.ModuleType("portfolio.paper")
    paper_mod.PaperPosition = PP
    paper_mod.PaperBook = object
    sys.modules["portfolio.paper"] = paper_mod

    rec = _load("core_reconciler_direct", "core/reconciler.py")
    local = [PP(1, "polymarket", "m1", "YES", 0.30, 100.0, 30.0),
             PP(2, "polymarket", "m2", "NO",  0.40, 50.0, 20.0)]
    remote = [rec.ExchangePosition("m1", "YES", 100.0, 0.30),
              rec.ExchangePosition("m3", "YES", 25.0, 0.10)]
    d = rec.diff_positions(local, remote)
    assert len(d["missing_locally"]) == 1 and d["missing_locally"][0].market_id == "m3"
    assert len(d["missing_remotely"]) == 1 and d["missing_remotely"][0].market_id == "m2"
    assert d["size_mismatch"] == []
    print("test_reconciler_diff OK")


if __name__ == "__main__":
    test_kelly_basic()
    test_breakeven_winrate()
    test_signals_composite_bounds()
    test_timing_tracker()
    test_reconciler_diff()
    print("\nALL SMOKE TESTS PASSED")
