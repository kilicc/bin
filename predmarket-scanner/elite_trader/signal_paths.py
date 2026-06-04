"""
Tek fiyat taraması → ortak ham aday havuzu.

- build_raw_momentum_candidate: tüm evren, tek tarama (full + hızlı)
- Her mod: kendi mode_profiles / .env filtresi (_entry_allowed veya live_path)
- Canlı motor: yalnızca seçili modun filtresinden geçenler → Binance demo
- Diğer modlar: aynı havuz → paper kitap (paralel evren)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable


def update_price_history(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    *,
    max_len: int = 60,
) -> None:
    if price <= 0:
        return
    if symbol not in price_history:
        price_history[symbol] = []
    price_history[symbol].append(
        {"time": datetime.utcnow().isoformat(), "price": price}
    )
    if len(price_history[symbol]) > max_len:
        price_history[symbol].pop(0)


def build_raw_momentum_candidate(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    *,
    min_ticks: int = 20,
    min_abs_change_pct: float = 0.05,
) -> dict[str, Any] | None:
    """
    Moddan bağımsız ham aday — edge/formül/strength kapısı yok.
    Paralel modlar kendi profil filtrelerini uygular.
    """
    hist = price_history.get(symbol) or []
    if len(hist) <= min_ticks:
        return None
    old_price = hist[-min_ticks]["price"]
    if old_price <= 0:
        return None
    change = ((price - old_price) / old_price) * 100
    boost = 0.0
    if len(hist) > 4:
        op4 = hist[-4]["price"]
        if op4 > 0:
            micro = ((price - op4) / op4) * 100
            if abs(micro) > abs(change) * 0.35:
                boost = 0.02 * (1 if change * micro > 0 else -1)
    adj_change = change + boost
    if abs(adj_change) <= min_abs_change_pct:
        return None
    direction = "LONG" if adj_change > 0 else "SHORT"
    abs_c = abs(adj_change)
    strength = (
        "Strong" if abs_c > 0.5 else "Medium" if abs_c > 0.25 else "Weak"
    )
    return {
        "symbol": symbol,
        "type": direction,
        "price": price,
        "change": float(adj_change),
        "time": datetime.utcnow().strftime("%H:%M:%S"),
        "strength": strength,
    }


def build_berserk2_momentum_candidate(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    *,
    min_abs_change_pct: float | None = None,
) -> dict[str, Any] | None:
    """BERSERK2 fast-tick — 2 bar yeterli (build_raw 20 bar beklemez)."""
    import os

    min_pct = float(
        min_abs_change_pct
        if min_abs_change_pct is not None
        else os.getenv("BERSERK2_MIN_MOMENTUM_PCT", "0.004")
    )
    hist = price_history.get(symbol) or price_history.get(symbol.replace("USDT", "")) or []
    if len(hist) < 2 or price <= 0:
        return None
    lb = max(2, min(5, int(os.getenv("BERSERK2_MOMENTUM_LOOKBACK", "2"))))
    idx = min(lb, len(hist) - 1)
    old_price = float(hist[-1 - idx].get("price") or 0)
    if old_price <= 0:
        return None
    change = ((price - old_price) / old_price) * 100
    if abs(change) < min_pct:
        return None
    direction = "LONG" if change > 0 else "SHORT"
    require_trend = os.getenv("BERSERK2_REQUIRE_MICRO_TREND", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if require_trend and len(hist) >= 3:
        last3 = [float(h.get("price") or 0) for h in hist[-3:]]
        if all(p > 0 for p in last3):
            rising = all(last3[i] > last3[i - 1] for i in range(1, len(last3)))
            falling = all(last3[i] < last3[i - 1] for i in range(1, len(last3)))
            if direction == "LONG" and not rising:
                return None
            if direction == "SHORT" and not falling:
                return None
    abs_c = abs(change)
    strength = (
        "Strong" if abs_c > 0.5 else "Medium" if abs_c > 0.25 else "Weak"
    )
    return {
        "symbol": symbol,
        "type": direction,
        "price": price,
        "change": float(change),
        "time": datetime.utcnow().strftime("%H:%M:%S"),
        "strength": strength,
    }


def build_raw_momentum_candidate_flex(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    *,
    windows: list[tuple[int, float]] | None = None,
) -> dict[str, Any] | None:
    """
    Kısa ve uzun pencere — UI approaching ile motor giriş hizası.
    Önce uzun pencere (20 bar), sonra kısa (UI lookback).
    """
    import os

    ui_lb = max(2, min(10, int(os.getenv("UI_APPROACHING_LOOKBACK", "3"))))
    short_pct = float(os.getenv("ENTRY_SHORT_MOMENTUM_PCT", "0.025"))
    if windows is None:
        windows = [
            (20, 0.05),
            (10, 0.04),
            (ui_lb, short_pct),
        ]
    for min_ticks, min_pct in windows:
        cand = build_raw_momentum_candidate(
            symbol,
            price,
            price_history,
            min_ticks=min_ticks,
            min_abs_change_pct=min_pct,
        )
        if cand:
            cand["momentum_window"] = min_ticks
            return cand
    return None


def live_path_accepts(
    candidate: dict[str, Any],
    recent_signals: list[dict[str, Any]],
    *,
    min_edge: float,
    min_formula: float,
    edge_fn: Callable[[float], float],
    formula_fn: Callable[[float], float],
    dedup_tail: int = 12,
) -> bool:
    """Ana Hat yolu — yalnızca canlı .env eşikleri (signals bus)."""
    ch = float(candidate.get("change") or 0)
    if edge_fn(ch) < min_edge:
        return False
    if formula_fn(ch) < min_formula:
        return False
    if candidate.get("strength") == "Weak":
        return False
    sym = candidate.get("symbol")
    direction = candidate.get("type")
    if any(
        s.get("symbol") == sym and s.get("type") == direction
        for s in recent_signals[-dedup_tail:]
    ):
        return False
    return True


def append_live_signal(
    candidate: dict[str, Any],
    signals: list[dict[str, Any]],
    *,
    max_signals: int = 120,
) -> dict[str, Any]:
    signals.append(dict(candidate))
    if len(signals) > max_signals:
        signals.pop(0)
    return signals[-1]
