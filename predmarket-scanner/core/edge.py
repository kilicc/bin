"""Edge, expected value, and Kelly sizing.

Bütün "matematik" buraya toplandı. Tweet'in "fiyat sapması >%6" kuralı burada
EdgeSignal.edge ile karşılığını bulur, ama gerçek karar EV + Kelly üzerinden alınır.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from markets.base import Market
from probability.base import ProbabilityEstimate


@dataclass
class EdgeSignal:
    market: Market
    side: str                  # "YES" veya "NO"
    market_price: float        # alış fiyatı [0,1]
    true_prob: float           # tahmin
    edge: float                # true_prob - market_price (side YES için)
    expected_value: float      # bahis başına dolar EV ($1 stake → bu kadar kâr beklenir)
    kelly_full: float          # tam Kelly fraction [0,1]
    kelly_sized: float         # fractional Kelly * bankroll fraction
    confidence: float
    rationale: str

    def __str__(self) -> str:
        return (
            f"{self.side} @ {self.market_price:.3f}  edge={self.edge:+.3f}  "
            f"EV=${self.expected_value:+.3f}/$1  kelly={self.kelly_sized:.2%}"
        )


def kelly_fraction(true_prob: float, price: float) -> float:
    """Binary kontrat için Kelly. Kontratı `price`'tan al, $1 öde.
    b = (1/price - 1) → kazanma durumunda $1 başına net kar.
    f* = (p*b - q) / b  where q = 1-p.
    Negatif gelirse, bahis yok (kıs).
    """
    if not (0.0 < price < 1.0):
        return 0.0
    b = (1.0 / price) - 1.0
    q = 1.0 - true_prob
    f = (true_prob * b - q) / b
    return max(0.0, f)


def compute_signal(
    market: Market,
    est: ProbabilityEstimate,
    *,
    edge_threshold: float = 0.06,
    kelly_multiplier: float = 0.25,
) -> Optional[EdgeSignal]:
    """Market + tahmin → trade sinyali (yeterli edge varsa).

    İki tarafı da değerlendirir (YES alım veya NO alım = YES satım).
    """
    p_market = market.yes_price
    if p_market is None:
        return None
    p_true = est.true_prob

    edge_yes = p_true - p_market
    edge_no = (1.0 - p_true) - (1.0 - p_market)  # == -edge_yes; simetrik

    if abs(edge_yes) < edge_threshold:
        return None

    if edge_yes > 0:
        side = "YES"
        price = p_market
        prob = p_true
        edge = edge_yes
    else:
        side = "NO"
        price = 1.0 - p_market
        prob = 1.0 - p_true
        edge = -edge_yes

    # EV per $1 stake: ödeme $1, maliyet `price`
    # win: net +(1-price); loss: net -price
    ev = prob * (1.0 - price) - (1.0 - prob) * price

    kf = kelly_fraction(prob, price)
    # Confidence düşükse Kelly'yi de kıs
    kelly_sized = kf * kelly_multiplier * est.confidence

    return EdgeSignal(
        market=market,
        side=side,
        market_price=price,
        true_prob=prob,
        edge=edge,
        expected_value=ev,
        kelly_full=kf,
        kelly_sized=kelly_sized,
        confidence=est.confidence,
        rationale=est.rationale,
    )
