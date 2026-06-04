"""Sembol / ücret yardımcıları (STALE, spike quick TP)."""
from __future__ import annotations

# Binance USDT-M taker ~0.04% / bacak (binance_elite_pro ile uyumlu)
_DEFAULT_TAKER = 0.0004


def round_trip_fee_usd(stake_usd: float, leverage: int = 3) -> float:
    """Giriş+çıkış komisyonu — stake marj, notional ≈ stake × kaldıraç."""
    if stake_usd <= 0:
        return 0.0
    lev = max(int(leverage or 1), 1)
    notional = stake_usd * lev
    return notional * _DEFAULT_TAKER * 2.0
