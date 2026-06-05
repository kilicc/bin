"""Pre-settlement exit policy — tweet 3'ün "%85 of expected move or 3x volume spike".

Whale'lar settlement'a kadar tutmaz (tweet'e göre %91 erken çıkar, %73 max profit
yakalanır). Bunun teorik nedeni:
  - Settlement = oracle disputed risk → tail variance
  - Sermaye redeployment opportunity cost
  - Time value erozyonu (theta-like)

Bu modül üç parametreli bir state machine:
  - expected_move:   girişten beklenen p_target − p_entry (TrueProb tahmininden)
  - capture_pct:     bu hareketin %X'i geldiğinde kapat (default 85%)
  - vol_spike_mult:  son N tick ortalama hacmin X katına çıkarsa kapat (default 3.0)
  - max_hold:        zaman dolarsa zorla kapat
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class PositionSnapshot:
    market_id: str
    side: str
    entry_price: float
    expected_target: float      # TrueProb tahminin (entry'de hesaplandı)
    opened_at: datetime
    current_price: float
    recent_volume: float        # son N dakika
    baseline_volume: float      # geçmiş ortalama
    settlement_at: Optional[datetime] = None


@dataclass(frozen=True)
class ExitConfig:
    capture_pct: float = 0.85
    vol_spike_mult: float = 3.0
    max_hold_hours: float = 72.0
    pre_settlement_buffer_hours: float = 6.0  # settlement <6h kala her halükarda çık


def should_exit(pos: PositionSnapshot, cfg: ExitConfig, now: Optional[datetime] = None) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)

    # 1) Pre-settlement güvenlik buffer'ı
    if pos.settlement_at:
        settle = pos.settlement_at if pos.settlement_at.tzinfo else pos.settlement_at.replace(tzinfo=timezone.utc)
        if (settle - now) <= timedelta(hours=cfg.pre_settlement_buffer_hours):
            return True, "pre-settlement buffer reached"

    # 2) Max hold
    opened = pos.opened_at if pos.opened_at.tzinfo else pos.opened_at.replace(tzinfo=timezone.utc)
    if (now - opened) >= timedelta(hours=cfg.max_hold_hours):
        return True, "max hold reached"

    # 3) Capture target
    expected_move = pos.expected_target - pos.entry_price
    if pos.side == "NO":
        expected_move = -expected_move  # NO için yön ters
    realized_move = pos.current_price - pos.entry_price
    if pos.side == "NO":
        realized_move = -realized_move
    if expected_move > 0 and realized_move >= cfg.capture_pct * expected_move:
        return True, f"captured {realized_move/expected_move:.0%} of expected move"

    # 4) Volume spike (whale aksiyonu sinyali — likidite kaçmadan çık)
    if pos.baseline_volume > 0 and pos.recent_volume >= cfg.vol_spike_mult * pos.baseline_volume:
        return True, f"volume spike {pos.recent_volume/pos.baseline_volume:.1f}x"

    return False, "hold"
