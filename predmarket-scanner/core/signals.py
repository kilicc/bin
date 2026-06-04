"""Baseline signal generators referenced in EXECUTION.md.

Bunlar `ProbabilityEstimator`'a hammadde sağlar. Çıktıları **olasılık ayarı**
(market price üzerine küçük delta) olarak kullan; ham olasılık üretmezler.

Her sinyal aynı sözleşmeye sahip:
    f(context) -> float in [-0.5, +0.5]
        pozitif = YES tarafı için bias, negatif = NO tarafı için bias.

Bu sinyalleri ağırlıklı kombinasyonla `composite_bias` üzerinden birleştir;
sonra `final_p = clip(market_price + bias, 0.01, 0.99)`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence


@dataclass
class TickEvent:
    """Order book'tan bir tick — momentum için."""
    ts: datetime
    yes_price: float
    yes_size: float        # YES tarafında en iyi seviyenin size'ı
    no_size: float


@dataclass
class SignalContext:
    """Sinyallerin tükettiği ortam."""
    market_id: str
    market_yes_price: float
    end_date: Optional[datetime] = None
    underlying_spot: Optional[float] = None       # örn. BTC fiyatı
    strike: Optional[float] = None                # market'in strike eşiği (örn. $200 SOL)
    tick_history: Sequence[TickEvent] = field(default_factory=list)


# --- 1) CLOB momentum --------------------------------------------------------

def clob_momentum(ctx: SignalContext, lookback: int = 20) -> float:
    """Son N tick'in order-flow yönüne göre [-0.5, +0.5] bias.

    Buy pressure = YES size azalıp price yukarı; sell pressure = tersi.
    Basit proxy: son N tick yes_price ortalama log return * tanh.
    """
    ticks = list(ctx.tick_history)[-lookback:]
    if len(ticks) < 2:
        return 0.0
    p0 = max(1e-6, ticks[0].yes_price)
    pN = max(1e-6, ticks[-1].yes_price)
    r = math.log(pN / p0)
    return 0.5 * math.tanh(r * 5.0)  # ~%10 hareket → 0.23 bias


# --- 2) Spot distance from strike -------------------------------------------

def spot_distance(ctx: SignalContext, scale: float = 0.05) -> float:
    """Underlying spot strike'a yakınsa daha hassas, uzaksa karara yakın.

    "SOL breaks $200" piyasası, SOL=$180 ve event 1 hafta sonra ise:
        diff = (180-200)/200 = -10%, scale=5% → z=-2 → sigmoid yakın 0.12 → bias -0.38
    """
    if ctx.underlying_spot is None or ctx.strike is None or ctx.strike == 0:
        return 0.0
    diff = (ctx.underlying_spot - ctx.strike) / ctx.strike
    z = diff / scale
    p = 1.0 / (1.0 + math.exp(-z))          # 0..1 (event-true olasılığı proxy)
    # Bias = p - 0.5 (merkezden sapma)
    return max(-0.5, min(0.5, p - 0.5))


# --- 3) Time-weighted signal -------------------------------------------------

def time_weighted(ctx: SignalContext, now: Optional[datetime] = None) -> float:
    """Event yaklaştıkça mevcut market price'ın true prob'a yaklaştığı bilinir.
    Uzakta = market noisy. Bu nedenle sinyal ağırlığını azalt.

    Bu fonksiyon **bias değil**, çoğunlukla diğer sinyallere çarpan olarak kullanılır.
    Burada [0..1] döndürür; composite_bias bunu çarpan olarak çağırsın.
    """
    if ctx.end_date is None:
        return 1.0
    now = now or datetime.now(timezone.utc)
    if ctx.end_date.tzinfo is None:
        end = ctx.end_date.replace(tzinfo=timezone.utc)
    else:
        end = ctx.end_date
    hours_left = max(0.0, (end - now).total_seconds() / 3600.0)
    # 0 saat → 0 (kapanmak üzere, sinyale güvenme)
    # 24-168 saat → ~0.8 (sweet spot)
    # 720+ saat → tail
    if hours_left < 1:
        return 0.1
    return min(1.0, math.exp(-abs(math.log(hours_left / 72.0))))


# --- 4) Day-of-week bias -----------------------------------------------------

# Örnek conditional priors — gerçek değerleri kendi backtest'inden çıkar.
# Anahtar: ISO weekday (1=Mon..7=Sun); değer: ortalama log-edge.
DOW_BIAS_BY_CATEGORY: dict[str, dict[int, float]] = {
    "crypto":    {1: +0.005, 2: 0.000, 3: -0.003, 4: 0.000, 5: +0.008, 6: -0.005, 7: -0.005},
    "politics":  {1: 0.000, 2: 0.000, 3: +0.004, 4: +0.005, 5: 0.000, 6: 0.000, 7: 0.000},
    "sports":    {1: 0.000, 2: 0.000, 3: 0.000, 4: 0.000, 5: +0.003, 6: +0.010, 7: +0.012},
}


def day_of_week_bias(ctx: SignalContext, category: Optional[str], now: Optional[datetime] = None) -> float:
    if not category:
        return 0.0
    table = DOW_BIAS_BY_CATEGORY.get(category.lower())
    if not table:
        return 0.0
    now = now or datetime.now(timezone.utc)
    return table.get(now.isoweekday(), 0.0)


# --- Composite ---------------------------------------------------------------

def composite_bias(
    ctx: SignalContext,
    category: Optional[str] = None,
    weights: Optional[dict[str, float]] = None,
) -> float:
    """Tüm sinyalleri birleştir → [-0.5, +0.5] toplam bias.

    Time-weighted bir çarpan olarak diğer üçüne uygulanır; day-of-week direkt eklenir.
    """
    w = weights or {"momentum": 1.0, "spot": 1.5, "dow": 0.5}
    tw = time_weighted(ctx)
    raw = (
        w["momentum"] * clob_momentum(ctx)
        + w["spot"] * spot_distance(ctx)
    ) * tw + w["dow"] * day_of_week_bias(ctx, category)
    return max(-0.5, min(0.5, raw))
