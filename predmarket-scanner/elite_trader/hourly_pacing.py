"""Saatlik $800 hedef — risk ayarı (garanti değil) + gerçekçi tavan."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class HourlyPacing:
    target_usd_per_hour: float = 800.0
    realistic_usd_per_hour: float = 0.0
    session_start_equity: float = 22_000.0
    realized_pnl: float = 0.0
    started_at: datetime | None = None
    _cached_realistic: float = field(default=0.0, repr=False)

    @classmethod
    def from_env(cls) -> "HourlyPacing":
        try:
            tgt = float(os.getenv("ELITE_TARGET_HOURLY_USD", "800"))
        except ValueError:
            tgt = 800.0
        try:
            bal = float(os.getenv("STARTING_BALANCE", "22000"))
        except ValueError:
            bal = 22_000.0
        p = cls(target_usd_per_hour=tgt, session_start_equity=bal)
        p.realistic_usd_per_hour = p.compute_realistic_hourly_cap()
        return p

    def compute_realistic_hourly_cap(self) -> float:
        """Stake × TP × max_open × WR × kapanış/saat — aspirasyon altı tavan."""
        override = (os.getenv("ELITE_TARGET_REALISTIC_USD") or "").strip()
        if override:
            try:
                return float(override)
            except ValueError:
                pass
        try:
            max_stake = float(os.getenv("ELITE_MAX_STAKE_USD", "175"))
            max_open = float(os.getenv("ELITE_MAX_OPEN", "36"))
            tp_pct = float(os.getenv("ELITE_TP_STAKE_PCT", "0.007"))
            tp_trig = float(os.getenv("ELITE_TP_TRIGGER_FRAC", "0.96"))
            wr = float(os.getenv("ELITE_ASSUMED_WR", "0.58"))
            closes_hr = float(os.getenv("ELITE_CLOSES_PER_HOUR", "4"))
        except ValueError:
            max_stake, max_open, tp_pct, tp_trig = 175, 36, 0.007, 0.96
            wr, closes_hr = 0.58, 4.0
        per_win = max_stake * tp_pct * tp_trig
        return max_open * per_win * wr * closes_hr

    def hours_elapsed(self) -> float:
        if not self.started_at:
            return 0.01
        return max(
            0.01,
            (datetime.now(timezone.utc) - self.started_at).total_seconds() / 3600.0,
        )

    def expected_pnl(self) -> float:
        return self.target_usd_per_hour * self.hours_elapsed()

    def expected_realistic_pnl(self) -> float:
        cap = self.realistic_usd_per_hour or self.compute_realistic_hourly_cap()
        return cap * self.hours_elapsed()

    def pace_ratio(self) -> float:
        exp = self.expected_pnl()
        if exp <= 0:
            return 1.0
        return self.realized_pnl / exp

    def pace_vs_realistic(self) -> float:
        exp = self.expected_realistic_pnl()
        if exp <= 0:
            return 1.0
        return self.realized_pnl / exp

    def stake_multiplier(self) -> float:
        """Hedefte gerideyken stake şişirme — daha çok küçük işlem."""
        r = self.pace_vs_realistic()
        if r < 0.5:
            return 0.88
        if r < 0.85:
            return 0.95
        if r > 1.2:
            return 0.82
        if r > 1.0:
            return 0.90
        return 1.0

    def _edge_boost_cap(self) -> float:
        try:
            return float(os.getenv("ELITE_PACING_EDGE_BOOST_MAX", "0.06"))
        except ValueError:
            return 0.06

    def edge_boost(self) -> float:
        """Skor eşiğine eklenecek sıkılaştırma (yüksek WR)."""
        cap = self._edge_boost_cap()
        r = self.pace_vs_realistic()
        boost = 0.0
        if r > 1.15:
            boost = 0.05
        elif r < 0.5:
            boost = 0.06
        elif r < 0.85:
            boost = 0.03
        return min(boost, cap) if cap >= 0 else boost

    def status_line(self) -> str:
        h = self.hours_elapsed()
        exp = self.expected_pnl()
        exp_r = self.expected_realistic_pnl()
        cap = self.realistic_usd_per_hour or self.compute_realistic_hourly_cap()
        return (
            f"Aspirasyon ${self.target_usd_per_hour:.0f}/h | "
            f"Gerçekçi ~${cap:.0f}/h | "
            f"{h:.1f}h → beklenen ${exp:+.0f} (real ${exp_r:+.0f}) | "
            f"realize ${self.realized_pnl:+.2f} | "
            f"pace {self.pace_ratio():.0%} / real {self.pace_vs_realistic():.0%}"
        )

    def target_equity_mult(self) -> float:
        try:
            return float(os.getenv("ELITE_TARGET_EQUITY_MULT", "0"))
        except ValueError:
            return 0.0

    def target_hours(self) -> float:
        try:
            return float(os.getenv("ELITE_TARGET_HOURS", "24"))
        except ValueError:
            return 24.0

    def current_equity(self) -> float:
        return self.session_start_equity + self.realized_pnl

    def pace_vs_2x_target(self) -> float | None:
        mult = self.target_equity_mult()
        if mult <= 1.0:
            return None
        goal = self.session_start_equity * mult
        h = self.hours_elapsed()
        expected = self.session_start_equity + (goal - self.session_start_equity) * (
            h / max(0.01, self.target_hours())
        )
        if expected <= self.session_start_equity:
            return 1.0
        return self.current_equity() / expected

    def snapshot(self) -> dict:
        cap = self.realistic_usd_per_hour or self.compute_realistic_hourly_cap()
        out = {
            "target_aspiration_usd_h": self.target_usd_per_hour,
            "target_realistic_usd_h": round(cap, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "current_equity": round(self.current_equity(), 2),
            "hours_elapsed": round(self.hours_elapsed(), 3),
            "expected_aspiration": round(self.expected_pnl(), 2),
            "expected_realistic": round(self.expected_realistic_pnl(), 2),
            "pace_vs_aspiration": round(self.pace_ratio(), 4),
            "pace_vs_realistic": round(self.pace_vs_realistic(), 4),
        }
        mult = self.target_equity_mult()
        if mult > 1.0:
            goal = self.session_start_equity * mult
            p2x = self.pace_vs_2x_target()
            out["target_equity_mult"] = mult
            out["target_equity_usd"] = round(goal, 2)
            out["pace_vs_2x"] = round(p2x, 4) if p2x is not None else None
        return out
