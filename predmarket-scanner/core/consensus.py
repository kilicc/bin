"""Multi-agent consensus voter — tweet 3'ün "3 ajan, 2 katılırsa full, 1 alone yarım".

Üç sinyal kaynağı:
  - arbitrage:    cross-venue veya same-market YES+NO != 1 spread
  - convergence:  signal_estimator çıktısı (CLOB momentum + spot + time + dow)
  - whale_copy:   whale_tracker'dan gelen entry

Her ajan binary oy verir (BUY_YES / BUY_NO / NO_TRADE).
Çoğunluk + boyut çarpanı kuralı:
  - 3/3 aynı: full size
  - 2/3 aynı: full size
  - 1 alone: half size
  - tüm farklı veya hepsi NO_TRADE: skip

Tweet 'consensus filter alone killed 40% of losing trades' diyor; bu PLAUSİBLE
çünkü ortak hata sinyalleri korelasyon düşürür (Condorcet jury theorem).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Vote(str, Enum):
    BUY_YES = "BUY_YES"
    BUY_NO = "BUY_NO"
    NO_TRADE = "NO_TRADE"


@dataclass
class AgentVote:
    agent: str         # "arbitrage" | "convergence" | "whale_copy"
    vote: Vote
    confidence: float  # [0,1] — kullanıcı kompozite ağırlık verebilir
    note: str = ""


@dataclass
class ConsensusDecision:
    vote: Vote
    size_multiplier: float    # 0.0 | 0.5 | 1.0
    agreeing_agents: list[str]
    reason: str

    def is_trade(self) -> bool:
        return self.vote != Vote.NO_TRADE and self.size_multiplier > 0


def decide(votes: list[AgentVote]) -> ConsensusDecision:
    """Üç ajan oyu → tek karar."""
    # NO_TRADE oylarını sayıma katma; ama hepsi NO_TRADE ise skip
    actionable = [v for v in votes if v.vote != Vote.NO_TRADE]
    if not actionable:
        return ConsensusDecision(Vote.NO_TRADE, 0.0, [], "all agents passed")

    yes_voters = [v.agent for v in actionable if v.vote == Vote.BUY_YES]
    no_voters = [v.agent for v in actionable if v.vote == Vote.BUY_NO]

    # Yön çatışması (en az 1 YES, en az 1 NO) → skip
    if yes_voters and no_voters:
        return ConsensusDecision(Vote.NO_TRADE, 0.0,
                                 yes_voters + no_voters,
                                 "directional disagreement")

    side = Vote.BUY_YES if yes_voters else Vote.BUY_NO
    agreeing = yes_voters or no_voters

    if len(agreeing) >= 2:
        return ConsensusDecision(side, 1.0, agreeing,
                                 f"{len(agreeing)} agents agree")
    return ConsensusDecision(side, 0.5, agreeing, "single-agent half size")
