"""Elite giriş kararı — kalibrasyon (Yol B) vs whale SuccessFormula modları."""
from __future__ import annotations

import os

from elite_trader.success_formula import MarketFeatures, SuccessFormula


def decision_mode() -> str:
    m = (os.getenv("ELITE_DECISION_MODE") or "whale_legacy").strip().lower()
    if m in (
        "calibration_primary",
        "hybrid_and",
        "calibration_only",
        "paper_learned",
        "formula_learned",
        "whale_legacy",
    ):
        return m
    return "whale_legacy"


def entry_allowed(
    formula: SuccessFormula,
    feats: MarketFeatures,
    edge: float,
    *,
    min_edge: float,
    min_score_floor: float,
    pacing_edge_boost: float,
) -> tuple[bool, float, dict[str, float], str]:
    """
    Giriş izni, whale skoru, skor parçaları, red nedeni veya 'ok'.
    calibration_primary: edge yeterli ise gir; whale skoru sadece bilgi/stake.
    """
    mode = decision_mode()
    ok_w, score, parts = formula.should_trade(feats)
    need = max(
        min_score_floor,
        formula.min_score + pacing_edge_boost,
        formula.theme_min_score(feats.theme),
    )

    if edge < min_edge:
        return False, score, parts, f"edge<{min_edge:.3f}"

    if mode == "calibration_only":
        return True, score, parts, "ok"

    if mode == "calibration_primary":
        return True, score, parts, "ok"

    if mode == "formula_learned":
        learned_need = max(min_score_floor, formula.min_score - 0.02 + pacing_edge_boost)
        if edge < min_edge:
            return False, score, parts, f"edge<{min_edge:.3f}"
        if not ok_w or score < learned_need:
            return False, score, parts, f"formula={score:.2f}<{learned_need:.2f}"
        return True, score, parts, "ok"

    if mode in ("hybrid_and", "whale_legacy", "paper_learned"):
        if not ok_w or score < need:
            return False, score, parts, f"whale_score={score:.2f}<{need:.2f}"
        return True, score, parts, "ok"

    return True, score, parts, "ok"


def stake_multiplier_from_whale(score: float, theme: str) -> float:
    """calibration_primary: whale skoru stake'i hafif ayarlar (giriş kapısı değil)."""
    _ = theme
    if decision_mode() not in ("calibration_primary",):
        return 1.0
    try:
        lo = float(os.getenv("ELITE_WHALE_STAKE_LO", "0.88"))
        hi = float(os.getenv("ELITE_WHALE_STAKE_HI", "1.12"))
    except ValueError:
        lo, hi = 0.88, 1.12
    t = max(0.0, min(1.0, (score - 0.45) / 0.25))
    return lo + t * (hi - lo)


def mode_label_tr() -> str:
    labels = {
        "calibration_primary": "Ana: kalibrasyon edge (Yol B) | Whale: sadece stake",
        "calibration_only": "Yalnızca kalibrasyon edge",
        "hybrid_and": "Kalibrasyon edge + whale skoru (ikisi de)",
        "whale_legacy": "Eski: whale skoru kapısı",
        "paper_learned": "Paper geçmişi + whale (geliştirme)",
        "formula_learned": "Global elite öğrenilmiş formül (kör kopya yok)",
    }
    return labels.get(decision_mode(), decision_mode())


def alignment_status(
    edge: float,
    score: float,
    *,
    min_edge: float,
    min_score: float,
) -> str:
    cal_ok = edge >= min_edge
    whale_ok = score >= min_score
    if cal_ok and whale_ok:
        return "aligned"
    if cal_ok and not whale_ok:
        return "cal_only"
    if not cal_ok and whale_ok:
        return "whale_only"
    return "conflict"
