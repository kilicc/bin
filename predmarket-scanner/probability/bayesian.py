"""Beta-Binomial online learner — küçük veriyle "kendini iyileştiren" tahmin.

Klasik RL 100 günlük data'da çöker çünkü gradient gürültüsü sinyali boğar.
Bayesian online learning kavramsal olarak şudur:
  - Her wallet için bir Beta(α, β) prior tut
  - Her resolved trade'de posterior güncelle: α += win_count, β += loss_count
  - Tahmin = posterior credible interval'ın alt sınırı (riske karşı muhafazakar)

Bu yaklaşım:
  - 10 trade ile bile anlamlı sonuç verir (Wilson LB ile aynı aile)
  - Yeni veri geldikçe doğal olarak günceller — "self-improving"
  - Hiperparametre yok; α0=β0=1 → uniform prior (Laplace's law of succession)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class BetaPosterior:
    alpha: float = 1.0       # prior 1 = uniform; daha skeptik için 2 yapabilirsin
    beta: float = 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def n(self) -> int:
        return int(round(self.alpha + self.beta - 2))

    def update(self, wins: int, losses: int) -> None:
        self.alpha += wins
        self.beta += losses

    def credible_lower(self, q: float = 0.05) -> float:
        """Posterior'ın quantile-q'su (yaklaşık). q=0.05 → %95 alt sınır.
        Normal yaklaşımı (large-n) — küçük-n'de Wilson LB daha doğru ama Beta CDF için
        scipy gerek; bu modül stdlib-only kalsın.
        """
        a, b = self.alpha, self.beta
        if a + b <= 2:
            return 0.0
        mu = a / (a + b)
        var = (a * b) / ((a + b) ** 2 * (a + b + 1))
        sd = math.sqrt(var)
        # Normal approximation lower q-quantile
        # z for q=0.05 = -1.6449
        z = _norm_quantile(q)
        return max(0.0, mu + z * sd)

    def thompson_sample(self, rng=None) -> float:
        """Posterior'dan örnekle — Thompson sampling için.
        Multi-armed bandit setup'ında bunu çağırırsın."""
        import random
        r = rng or random
        return r.betavariate(self.alpha, self.beta)


def _norm_quantile(q: float) -> float:
    """Beasley-Springer-Moro approximation; yeterince doğru, stdlib-only."""
    if q <= 0 or q >= 1:
        return 0.0
    # Rational approximation
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low = 0.02425
    p_high = 1 - p_low
    if q < p_low:
        q_ = math.sqrt(-2 * math.log(q))
        return (((((c[0]*q_+c[1])*q_+c[2])*q_+c[3])*q_+c[4])*q_+c[5]) / \
               ((((d[0]*q_+d[1])*q_+d[2])*q_+d[3])*q_+1)
    if q > p_high:
        q_ = math.sqrt(-2 * math.log(1 - q))
        return -(((((c[0]*q_+c[1])*q_+c[2])*q_+c[3])*q_+c[4])*q_+c[5]) / \
                ((((d[0]*q_+d[1])*q_+d[2])*q_+d[3])*q_+1)
    q_ = q - 0.5
    r = q_ * q_
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5]) * q_ / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


@dataclass
class BayesianWalletScorer:
    """Online wallet ranker. Her resolved trade'de güncellenir.

    Kullanım:
      scorer = BayesianWalletScorer()
      for trade in resolved_trades_stream:
          scorer.observe(trade.wallet, won=...)
      scorer.score("0xabc")  # credible lower bound, [0,1]
    """
    prior_alpha: float = 2.0       # hafif skeptik prior; %50 WR önyargısı
    prior_beta: float = 2.0
    posteriors: dict[str, BetaPosterior] = field(default_factory=dict)

    def observe(self, wallet: str, won: bool) -> None:
        p = self.posteriors.get(wallet)
        if p is None:
            p = BetaPosterior(self.prior_alpha, self.prior_beta)
            self.posteriors[wallet] = p
        p.update(1, 0) if won else p.update(0, 1)

    def observe_batch(self, wallet: str, wins: int, losses: int) -> None:
        p = self.posteriors.get(wallet)
        if p is None:
            p = BetaPosterior(self.prior_alpha, self.prior_beta)
            self.posteriors[wallet] = p
        p.update(wins, losses)

    def score(self, wallet: str, quantile: float = 0.05) -> float:
        p = self.posteriors.get(wallet)
        if p is None:
            return BetaPosterior(self.prior_alpha, self.prior_beta).credible_lower(quantile)
        return p.credible_lower(quantile)

    def top_n(self, n: int, min_n: int = 10, quantile: float = 0.05) -> list[tuple[str, float, int]]:
        out = [(w, p.credible_lower(quantile), p.n)
               for w, p in self.posteriors.items() if p.n >= min_n]
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:n]
