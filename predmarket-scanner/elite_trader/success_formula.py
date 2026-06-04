"""Başarı formülü — elite örüntülerden türetilmiş skor (kör kopya değil)."""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from elite_trader.pattern_miner import ElitePatterns

ROOT = Path(__file__).resolve().parent.parent
FORMULA_PATH = ROOT / "data" / "elite_success_formula.pkl"


@dataclass
class MarketFeatures:
    yes_price: float
    side: str
    edge: float
    hours_left: float
    spread: float
    momentum: float | None
    theme: str
    question: str = ""


@dataclass
class SuccessFormula:
    """Ağırlıklı başarı skoru — 0..1."""
    version: int = 1
    min_score: float = 0.52
    weights: dict[str, float] = field(default_factory=dict)
    price_bucket_wr: dict[str, float] = field(default_factory=dict)
    theme_wr: dict[str, float] = field(default_factory=dict)
    preferred_hours: tuple[float, float] = (2.0, 48.0)
    rules_tr: list[str] = field(default_factory=list)
    source_wallets: list[str] = field(default_factory=list)

    @classmethod
    def from_patterns(
        cls,
        patterns: ElitePatterns,
        *,
        elite_wallets: list[str],
        version: int = 1,
    ) -> "SuccessFormula":
        w: dict[str, float] = {
            "price_fit": 0.28,
            "theme_fit": 0.22,
            "edge": 0.20,
            "timing": 0.15,
            "momentum": 0.10,
            "spread_penalty": 0.05,
        }
        min_score = 0.50
        if patterns.trades_analyzed < 500:
            min_score = 0.55
        return cls(
            version=version,
            min_score=min_score,
            weights=w,
            price_bucket_wr=dict(patterns.price_bucket_wr),
            theme_wr=dict(patterns.theme_wr),
            preferred_hours=patterns.preferred_hours_left,
            rules_tr=list(patterns.rules_tr),
            source_wallets=list(elite_wallets[:30]),
        )

    def _price_bucket(self, p: float) -> str:
        i = min(9, max(0, int(p * 10)))
        return f"{i/10:.1f}-{(i+1)/10:.1f}"

    def score(self, f: MarketFeatures) -> tuple[float, dict[str, float]]:
        """Formül skoru ve bileşenler."""
        parts: dict[str, float] = {}
        b = self._price_bucket(f.yes_price if f.side == "YES" else (1.0 - f.yes_price))
        parts["price_fit"] = self.price_bucket_wr.get(b, 0.45)
        parts["theme_fit"] = self.theme_wr.get(f.theme, 0.45)
        parts["edge"] = min(1.0, max(0.0, f.edge / 0.25))
        lo, hi = self.preferred_hours
        if lo <= f.hours_left <= hi:
            parts["timing"] = 1.0
        elif f.hours_left < lo:
            parts["timing"] = max(0.2, f.hours_left / lo)
        else:
            parts["timing"] = max(0.2, hi / max(f.hours_left, hi + 1))
        if f.momentum is not None:
            m = float(f.momentum)
            if f.side == "YES" and m > 0:
                parts["momentum"] = min(1.0, abs(m) * 40)
            elif f.side == "NO" and m < 0:
                parts["momentum"] = min(1.0, abs(m) * 40)
            else:
                parts["momentum"] = 0.25
        else:
            parts["momentum"] = 0.4
        parts["spread_penalty"] = max(0.0, 1.0 - f.spread / 0.08)

        total = 0.0
        wsum = 0.0
        for k, wt in self.weights.items():
            total += parts.get(k, 0.5) * wt
            wsum += wt
        score = total / wsum if wsum else 0.5
        return score, parts

    def theme_min_score(self, theme: str) -> float:
        """Tema bazlı ek eşik — env veya whale WR zayıf temalar."""
        import os

        raw = (os.getenv("ELITE_THEME_MIN_SCORE") or "").strip()
        if raw:
            try:
                overrides = json.loads(raw)
                if isinstance(overrides, dict) and theme in overrides:
                    return float(overrides[theme])
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        boost = 0.0
        if theme.startswith("sports"):
            boost = float(os.getenv("ELITE_SPORTS_MIN_SCORE_BOOST", "0.12"))
        whale_wr = self.theme_wr.get(theme, 0.5)
        if whale_wr < 0.52:
            boost = max(boost, 0.08)
        return self.min_score + boost

    def should_trade(self, f: MarketFeatures) -> tuple[bool, float, dict[str, float]]:
        s, parts = self.score(f)
        need = self.theme_min_score(f.theme)
        return s >= need, s, parts

    def save(self, path: Path | None = None) -> None:
        path = path or FORMULA_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fp:
            pickle.dump(self, fp)

    @classmethod
    def load(cls, path: Path | None = None) -> "SuccessFormula | None":
        path = path or FORMULA_PATH
        if not path.is_file():
            return None
        try:
            with open(path, "rb") as fp:
                obj = pickle.load(fp)
            if isinstance(obj, cls):
                return obj
        except Exception:
            pass
        return None

    def summary_tr(self) -> str:
        import os

        mode = (os.getenv("ELITE_DECISION_MODE") or "whale_legacy").strip().lower()
        gate = "giriş kapısı"
        if mode == "calibration_primary":
            gate = "stake ayarı (giriş kapısı değil)"
        elif mode == "formula_learned":
            gate = "öğrenilmiş global elite kuralları"
        elif mode == "calibration_only":
            gate = "kullanılmıyor (yalnızca kalibrasyon)"
        lines = [
            f"Whale formülü v{self.version} — min skor {self.min_score:.2f} ({gate})",
        ]
        lines.extend(f"  • {r}" for r in self.rules_tr[:8])
        return "\n".join(lines)
