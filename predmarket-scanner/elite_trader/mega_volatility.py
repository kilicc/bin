"""MEGA — göreli volatilite tespiti (sessiz piyasada en hareketli coinler)."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

_lock = threading.Lock()
_rows: dict[str, dict[str, Any]] = {}
_ranked: list[str] = ()
_updated_at: float = 0.0


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return _env_bool("MEGA_VOL_SCAN", True)


def micro_price_filter_enabled() -> bool:
    return _env_bool("MEGA_MICRO_PRICE_FILTER", True)


def micro_price_max_usd() -> float:
    """Bu fiyatın altı = mikro coin (ör. PEPE ~0.0034)."""
    return _env_float("MEGA_MICRO_PRICE_MAX_USD", 0.008)


def is_micro_price(price: float) -> bool:
    fp = float(price or 0)
    return micro_price_filter_enabled() and fp > 0 and fp < micro_price_max_usd()


def micro_price_scan_eligible(
    price: float,
    *,
    change_pct: float = 0.0,
    vol_score: float = 0.0,
    vol_tier: str = "",
    strength: str = "",
) -> bool:
    """Mikro fiyatlı coin — yalnızca güçlü momentum / vol skoru ile taramaya girer."""
    if not is_micro_price(price):
        return True
    min_move = _env_float("MEGA_MICRO_MIN_MOVE_PCT", 0.10)
    min_vol = _env_float("MEGA_MICRO_MIN_VOL_SCORE", 14.0)
    ch = abs(float(change_pct))
    if ch >= min_move:
        return True
    if float(vol_score) >= min_vol:
        return True
    if str(vol_tier) == "hot" and ch >= min_move * 0.85:
        return True
    if str(strength) == "Strong" and ch >= min_move * 0.70:
        return True
    return False


def _norm_symbol(sym: str) -> str:
    s = str(sym or "").upper().strip()
    if not s:
        return ""
    if not s.endswith("USDT"):
        s = f"{s}USDT"
    return s


def _momentum_pct(
    sym: str,
    price: float,
    price_history: dict[str, list],
) -> float:
    hist = price_history.get(sym) or price_history.get(sym.replace("USDT", "")) or []
    if len(hist) < 2:
        return 0.0
    cur = float(price)
    hp = float(hist[-1].get("price") or 0)
    if hp > 0:
        cur = hp
    if cur <= 0:
        return 0.0
    lb = max(2, min(5, _env_int("MEGA_VOL_MOMENTUM_LOOKBACK", 2)))
    idx = min(lb, len(hist) - 1)
    old = float(hist[-1 - idx].get("price") or 0)
    if old <= 0:
        return 0.0
    return abs((cur - old) / old * 100.0)


def _volume_ratio_from_hist(sym: str, price_history: dict[str, list]) -> float:
    hist = price_history.get(sym) or price_history.get(sym.replace("USDT", "")) or []
    if len(hist) < 5:
        return 1.0
    try:
        recent = sum(float(h.get("volume") or 0) for h in hist[-2:])
        base = sum(float(h.get("volume") or 0) for h in hist[-5:-2]) / 3.0
        if base <= 0:
            return 1.0
        return max(1.0, recent / base)
    except Exception:
        return 1.0


def _vol_score(
    *,
    change_pct: float,
    vol_ratio: float,
    spread_pct: float,
    on_top_mover: bool,
) -> float:
    score = abs(float(change_pct)) * 100.0
    score += max(0.0, float(vol_ratio) - 1.0) * 8.0
    if on_top_mover:
        score += 3.0
    if 0 < spread_pct < 0.06:
        score += 2.0
    return score


def refresh_from_price_universe(
    symbols: list[str],
    prices: dict[str, float],
    price_history: dict[str, list],
    *,
    spread_map: dict[str, float] | None = None,
    volume_map: dict[str, float] | None = None,
    top_movers: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Evren içinden volatilite skoruna göre hot/warm/cold sırala."""
    global _rows, _ranked, _updated_at
    if not enabled():
        return []
    spread_map = spread_map or {}
    volume_map = volume_map or {}
    top_set = {_norm_symbol(s) for s in (top_movers or ()) if s}
    scored: list[tuple[float, str, dict[str, Any]]] = []

    for raw in symbols:
        sym = _norm_symbol(raw)
        if not sym:
            continue
        fp = float(prices.get(sym) or prices.get(sym.replace("USDT", "")) or 0)
        if fp <= 0:
            continue
        ch = _momentum_pct(sym, fp, price_history)
        vr = float(volume_map.get(sym) or volume_map.get(sym.replace("USDT", "")) or 0)
        if vr <= 1.01:
            vr = _volume_ratio_from_hist(sym, price_history)
        spread = float(spread_map.get(sym) or spread_map.get(sym.replace("USDT", "")) or 0)
        on_top = sym in top_set
        if not on_top:
            try:
                from elite_trader.berserk2_movers import is_top_mover

                on_top = is_top_mover(sym)
            except Exception:
                pass
        vs = _vol_score(
            change_pct=ch,
            vol_ratio=vr,
            spread_pct=spread,
            on_top_mover=on_top,
        )
        if is_micro_price(fp) and not micro_price_scan_eligible(
            fp, change_pct=ch, vol_score=vs
        ):
            continue
        row = {
            "symbol": sym,
            "price": round(fp, 8),
            "change_pct": round(ch, 4),
            "vol_ratio": round(vr, 3),
            "vol_score": round(vs, 2),
            "top_mover": on_top,
        }
        scored.append((vs, sym, row))

    scored.sort(key=lambda x: -x[0])
    hot_n = _env_int("MEGA_VOL_HOT_N", 6)
    warm_n = max(hot_n, _env_int("MEGA_VOL_WARM_N", 12))
    cold_n = max(0, _env_int("MEGA_VOL_COLD_N", 0))
    scan_limit = warm_n + cold_n
    out: list[dict[str, Any]] = []

    with _lock:
        _rows.clear()
        _ranked = []
        for i, (_, sym, row) in enumerate(scored):
            if i < hot_n:
                row["tier"] = "hot"
            elif i < warm_n:
                row["tier"] = "warm"
            else:
                row["tier"] = "cold"
            row["rank"] = i + 1
            _rows[sym] = dict(row)
            _ranked.append(sym)
            if i < scan_limit:
                out.append(dict(row))
        _updated_at = time.time()
        out_rows = [dict(_rows[s]) for s in _ranked if s in _rows][:scan_limit]
    try:
        from elite_trader.mega_market_regime import record_sample

        record_sample(out_rows)
    except Exception:
        pass
    return out_rows


def tier_for(symbol: str) -> str:
    sym = _norm_symbol(symbol)
    if not sym or not enabled():
        return "cold"
    with _lock:
        row = _rows.get(sym)
        if row and (time.time() - _updated_at) < 45.0:
            return str(row.get("tier") or "cold")
    return "cold"


def row_for(symbol: str) -> dict[str, Any] | None:
    sym = _norm_symbol(symbol)
    if not sym:
        return None
    with _lock:
        row = _rows.get(sym)
        if row and (time.time() - _updated_at) < 45.0:
            return dict(row)
    return None


def is_volatile(symbol: str, *, min_tier: str = "warm") -> bool:
    order = {"hot": 0, "warm": 1, "cold": 2}
    return order.get(tier_for(symbol), 9) <= order.get(min_tier, 1)


def thresholds(profile: dict[str, Any], symbol: str) -> dict[str, Any]:
    """Sembol tier'ı + piyasa rejimi → dinamik giriş eşikleri."""
    base_move = float(profile.get("mega_min_move_pct") or 0.08)
    base_score = float(profile.get("mega_min_score") or 48)
    base_edge = float(profile.get("min_edge") or 0.04)
    tier = tier_for(symbol)
    require_top = bool(profile.get("mega_require_top_mover", True))

    if not enabled():
        return {
            "min_move": base_move,
            "min_score": base_score,
            "min_edge": base_edge,
            "require_top_mover": require_top,
            "tier": "off",
            "rank": None,
            "regime": "off",
        }

    row = row_for(symbol) or {}
    regime = "normal"
    try:
        from elite_trader.mega_market_regime import tier_thresholds as regime_tiers

        rt = regime_tiers(profile, tier)
        regime = str(rt.get("regime") or "normal")
        if tier in ("hot", "warm"):
            if regime == "off":
                hot_move = _env_float("MEGA_VOL_HOT_MIN_MOVE_PCT", 0.004)
                warm_move = _env_float("MEGA_VOL_WARM_MIN_MOVE_PCT", 0.008)
                hot_score = _env_float("MEGA_VOL_HOT_MIN_SCORE", 20.0)
                edge_hot = _env_float("MEGA_VOL_EDGE_RELAX_HOT", 0.50)
                edge_warm = _env_float("MEGA_VOL_EDGE_RELAX_WARM", 0.62)
                if tier == "hot":
                    return {
                        "min_move": min(base_move, hot_move),
                        "min_score": min(base_score, hot_score),
                        "min_edge": base_edge * edge_hot,
                        "require_top_mover": False,
                        "tier": tier,
                        "rank": row.get("rank"),
                        "regime": "vol",
                    }
                return {
                    "min_move": min(base_move, warm_move),
                    "min_score": min(base_score, base_score - 5.0),
                    "min_edge": base_edge * edge_warm,
                    "require_top_mover": False,
                    "tier": tier,
                    "rank": row.get("rank"),
                    "regime": "vol",
                }
            return {
                "min_move": float(rt["min_move"]),
                "min_score": float(rt["min_score"]),
                "min_edge": float(rt["min_edge"]),
                "require_top_mover": False,
                "tier": tier,
                "rank": row.get("rank"),
                "regime": regime,
            }
    except Exception:
        pass

    return {
        "min_move": base_move,
        "min_score": base_score,
        "min_edge": base_edge,
        "require_top_mover": require_top,
        "tier": tier,
        "rank": row.get("rank"),
        "regime": regime,
    }


def build_vol_scan_candidate(
    symbol: str,
    price: float,
    price_history: dict[str, list],
    *,
    min_abs_change_pct: float | None = None,
) -> dict[str, Any] | None:
    """MEGA vol taraması — micro-trend zorunluluğu yok, düşük momentum eşiği."""
    from datetime import datetime

    sym = _norm_symbol(symbol)
    if not sym or price <= 0:
        return None
    try:
        from elite_trader.mega_direction_guard import btc_context_ready

        ready, _ = btc_context_ready(price_history)
        if not ready:
            return None
    except Exception:
        pass
    min_pct = (
        float(min_abs_change_pct)
        if min_abs_change_pct is not None
        else _env_float("MEGA_VOL_SCAN_MIN_MOMENTUM_PCT", 0.002)
    )
    hist = price_history.get(sym) or price_history.get(sym.replace("USDT", "")) or []
    if len(hist) < 2:
        return None
    lb = max(2, min(5, _env_int("MEGA_VOL_MOMENTUM_LOOKBACK", 2)))
    idx = min(lb, len(hist) - 1)
    old = float(hist[-1 - idx].get("price") or 0)
    if old <= 0:
        return None
    change = ((float(price) - old) / old) * 100.0
    if abs(change) < min_pct:
        return None
    row = row_for(sym) or {}
    if not micro_price_scan_eligible(
        float(price),
        change_pct=change,
        vol_score=float(row.get("vol_score") or 0),
        vol_tier=str(row.get("tier") or ""),
    ):
        return None
    try:
        from elite_trader.mega_direction_guard import resolve_vol_scan_side

        direction, block = resolve_vol_scan_side(
            sym, change, price_history, min_abs_pct=min_pct
        )
        if not direction:
            return None
    except Exception:
        direction = "LONG" if change > 0 else "SHORT"
        block = ""
    abs_c = abs(change)
    strength = "Strong" if abs_c > 0.5 else "Medium" if abs_c > 0.25 else "Weak"
    return {
        "symbol": sym,
        "type": direction,
        "price": float(price),
        "change": float(change),
        "time": datetime.utcnow().strftime("%H:%M:%S"),
        "strength": strength,
        "vol_ratio": row.get("vol_ratio"),
        "mega_vol_tier": row.get("tier"),
        "mega_vol_rank": row.get("rank"),
        "target_mode": "mega",
        "mega_vol_scan_aligned": True,
        "mega_direction_block": block or None,
    }


def scan_symbol_list(
    *,
    include_watchlist: bool | None = None,
    prices: dict[str, float] | None = None,
) -> list[str]:
    """MEGA tarama evreni — vol sıralı hot/warm/cold + isteğe bağlı tüm watchlist."""
    if include_watchlist is None:
        include_watchlist = _env_bool("MEGA_SCAN_UNIVERSE_WATCHLIST", False)
    with _lock:
        rows = [dict(_rows[s]) for s in _ranked if s in _rows]
    warm_n = max(_env_int("MEGA_VOL_HOT_N", 6), _env_int("MEGA_VOL_WARM_N", 12))
    cold_n = max(0, _env_int("MEGA_VOL_COLD_N", 0))
    limit = warm_n + cold_n
    syms: list[str] = []
    seen: set[str] = set()
    for row in rows[:limit]:
        sym = _norm_symbol(str(row.get("symbol") or ""))
        if sym and sym not in seen:
            syms.append(sym)
            seen.add(sym)
    if include_watchlist:
        raw = os.getenv("BINANCE_WATCHLIST", "").strip()
        if raw:
            for part in raw.split(","):
                sym = _norm_symbol(part.strip())
                if not sym or sym in seen:
                    continue
                fp = float(
                    (prices or {}).get(sym)
                    or (prices or {}).get(sym.replace("USDT", ""))
                    or 0
                )
                if fp > 0 and is_micro_price(fp):
                    vol_row = row_for(sym) or {}
                    if not micro_price_scan_eligible(
                        fp,
                        change_pct=float(vol_row.get("change_pct") or 0),
                        vol_score=float(vol_row.get("vol_score") or 0),
                        vol_tier=str(vol_row.get("tier") or ""),
                    ):
                        continue
                syms.append(sym)
                seen.add(sym)
    return syms


def snapshot() -> dict[str, Any]:
    with _lock:
        rows = [dict(_rows[s]) for s in _ranked if s in _rows]
        warm_n = _env_int("MEGA_VOL_WARM_N", 12)
        cold_n = _env_int("MEGA_VOL_COLD_N", 0)
        scan_limit = warm_n + cold_n
        snap = {
            "enabled": enabled(),
            "micro_price_filter": micro_price_filter_enabled(),
            "micro_price_max_usd": micro_price_max_usd(),
            "updated_at": _updated_at,
            "age_sec": round(time.time() - _updated_at, 1) if _updated_at else None,
            "hot_n": _env_int("MEGA_VOL_HOT_N", 6),
            "warm_n": warm_n,
            "cold_n": cold_n,
            "coins": rows[:scan_limit],
            "hot": [r for r in rows if r.get("tier") == "hot"],
            "warm": [r for r in rows if r.get("tier") == "warm"],
            "cold": [r for r in rows if r.get("tier") == "cold"][:cold_n],
        }
    snap["scan_universe_n"] = len(scan_symbol_list())
    return snap
