"""Kar/zarar hesaplama — paper ve raporlama."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionPnL:
    side: str
    entry_price: float
    close_price: float
    stake_usd: float
    contracts: float = 0.0

    @property
    def pnl_usd(self) -> float:
        contracts = self.contracts
        if contracts <= 0:
            contracts = self.stake_usd / max(1e-6, self.entry_price)
        delta = self.close_price - self.entry_price
        if self.side == "NO":
            delta = -delta
        return contracts * delta

    @property
    def pnl_pct(self) -> float:
        return (self.pnl_usd / self.stake_usd * 100.0) if self.stake_usd else 0.0


class PnLEngine:
    @staticmethod
    def unrealized(
        side: str,
        entry_price: float,
        yes_price: float,
        stake_usd: float,
        *,
        contracts: float | None = None,
    ) -> float:
        """yes_price = Gamma/CLOB YES olasılığı; entry_price = pozisyon tarafı girişi."""
        c = contracts if contracts and contracts > 0 else stake_usd / max(1e-6, entry_price)
        cur_side = yes_price if side == "YES" else (1.0 - yes_price)
        return c * (cur_side - entry_price)

    @staticmethod
    def cap_sl_pnl(pnl: float, stake_usd: float, sl_pct: float) -> float:
        floor = -stake_usd * sl_pct
        return max(pnl, floor)
