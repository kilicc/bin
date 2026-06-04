"""MEGA — BTC/alt rejim, trend hizası, aynı yön kümeleme koruması."""
from __future__ import annotations

import os
import time
from typing import Any

from elite_trader.berserk2_btc_context import get_btc_context, schedule_btc_refresh


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return _env_bool("MEGA_DIRECTION_GUARD", True)


_VALID_BTC_REGIMES = frozenset(
    {"trend_up", "trend_down", "chop", "mixed"}
)


def btc_context_max_age_sec() -> float:
    return max(15.0, _env_float("MEGA_BTC_CONTEXT_MAX_AGE_SEC", 120.0))


def btc_context_ready(
    price_history: dict[str, list] | None = None,
    *,
    binance_client: Any | None = None,
) -> tuple[bool, str]:
    """
    BTC rejimi net değilse (unknown / bayat) hiç işlem açma.
    Restart sonrası klines gelene kadar beklenir.
    """
    if not enabled():
        return True, ""
    if not _env_bool("MEGA_BTC_REQUIRE_READY", True):
        return True, ""
    btc = btc_context_extended(price_history, binance_client=binance_client)
    regime = str(btc.get("btc_regime") or "unknown").lower().strip()
    if regime not in _VALID_BTC_REGIMES:
        return False, "btc_regime_unknown"
    updated = float(btc.get("regime_updated_at") or btc.get("updated_at") or 0)
    if updated <= 0:
        return False, "btc_context_no_timestamp"
    age = time.time() - updated
    if age > btc_context_max_age_sec():
        return False, "btc_context_stale"
    if _env_bool("MEGA_BTC_REQUIRE_PRICE", True):
        try:
            px = float(btc.get("btc_price") or 0)
        except (TypeError, ValueError):
            px = 0.0
        if px <= 0:
            return False, "btc_price_missing"
    return True, ""


def bear_short_entry_boost() -> dict[str, float]:
    """BTC düşüş — SHORT giriş eşiklerini gevşet (çok TP scalp)."""
    bear, _ = btc_bearish()
    if not bear or not _env_bool("MEGA_BEAR_SHORT_BOOST", True):
        return {
            "score_delta": 0.0,
            "edge_mult": 1.0,
            "move_mult": 1.0,
            "stake_mult": 1.0,
            "vol_min_momentum_mult": 1.0,
        }
    return {
        "score_delta": _env_float("MEGA_BEAR_SHORT_SCORE_DELTA", 10.0),
        "edge_mult": _env_float("MEGA_BEAR_SHORT_EDGE_MULT", 0.72),
        "move_mult": _env_float("MEGA_BEAR_SHORT_MOVE_MULT", 0.80),
        "stake_mult": _env_float("MEGA_BEAR_SHORT_STAKE_MULT", 1.08),
        "vol_min_momentum_mult": _env_float("MEGA_BEAR_VOL_MIN_MOMENTUM_MULT", 0.65),
    }


def _price_history() -> dict[str, list]:
    try:
        import binance_elite_pro as bep

        return bep.price_history
    except Exception:
        return {}


def _norm_symbol(sym: str) -> str:
    s = str(sym or "").upper().strip()
    if not s:
        return ""
    return s if s.endswith("USDT") else f"{s}USDT"


def _hist_prices(sym: str, price_history: dict[str, list]) -> list[float]:
    su = _norm_symbol(sym)
    hist = price_history.get(su) or price_history.get(su.replace("USDT", "")) or []
    out: list[float] = []
    for h in hist:
        p = float(h.get("price") or 0)
        if p > 0:
            out.append(p)
    return out


def _pct_change(cur: float, old: float) -> float:
    if old <= 0 or cur <= 0:
        return 0.0
    return (cur - old) / old * 100.0


def symbol_momentum(
    sym: str,
    price_history: dict[str, list],
    *,
    lookback: int | None = None,
) -> float:
    """İmzalı momentum % — pozitif yukarı."""
    prices = _hist_prices(sym, price_history)
    if len(prices) < 2:
        return 0.0
    lb = lookback if lookback is not None else _env_int("MEGA_VOL_MOMENTUM_LOOKBACK", 2)
    lb = max(2, min(8, lb))
    idx = min(lb, len(prices) - 1)
    return _pct_change(prices[-1], prices[-1 - idx])


def symbol_medium_trend(
    sym: str,
    price_history: dict[str, list],
) -> float:
    """Orta vadeli trend — micro yeşil mum tuzaklarını filtreler."""
    prices = _hist_prices(sym, price_history)
    if len(prices) < 3:
        return 0.0
    lb = max(4, min(36, _env_int("MEGA_TREND_MEDIUM_BARS", 14)))
    idx = min(lb, len(prices) - 1)
    return _pct_change(prices[-1], prices[-1 - idx])


def btc_recent_drop_pct(price_history: dict[str, list] | None = None) -> float | None:
    """BTC kısa pencerede tepe→dip % (diğer coinlerle aynı mantık)."""
    ph = price_history if price_history is not None else _price_history()
    prices = _hist_prices("BTCUSDT", ph)
    if len(prices) < 6:
        return None
    lb = max(6, min(48, _env_int("MEGA_BTC_DIP_LOOKBACK_BARS", 20)))
    window = prices[-lb:]
    peak = max(window)
    low = min(window)
    if peak <= 0 or low >= peak:
        return None
    return (peak - low) / peak * 100.0


def btc_context_extended(
    price_history: dict[str, list] | None = None,
    *,
    binance_client: Any | None = None,
) -> dict[str, Any]:
    if binance_client is not None:
        schedule_btc_refresh(binance_client)
    btc = dict(get_btc_context())
    dip = btc_recent_drop_pct(price_history)
    if dip is not None:
        btc["btc_recent_drop_pct"] = round(dip, 4)
    ch24 = btc.get("btc_24h_change")
    try:
        btc["btc_24h_change"] = float(ch24) if ch24 is not None else None
    except (TypeError, ValueError):
        btc["btc_24h_change"] = None
    return btc


def btc_bearish(
    price_history: dict[str, list] | None = None,
    *,
    binance_client: Any | None = None,
) -> tuple[bool, str]:
    """BTC düşüş — LONG engeli / SHORT teşvik."""
    if not enabled():
        return False, ""
    btc = btc_context_extended(price_history, binance_client=binance_client)
    regime = str(btc.get("btc_regime") or "").lower()
    ch24 = btc.get("btc_24h_change")
    bear_24h_thr = _env_float("MEGA_BTC_BEAR_24H_PCT", 0.35)
    dip_thr = _env_float("MEGA_BTC_DIP_BLOCK_PCT", 0.45)
    dip = btc.get("btc_recent_drop_pct")

    if regime == "trend_down":
        return True, "btc_trend_down"
    if ch24 is not None and float(ch24) <= -bear_24h_thr:
        return True, "btc_24h_bear"
    if dip is not None and float(dip) >= dip_thr:
        return True, "btc_recent_dip"
    return False, ""


def alt_in_dip(
    sym: str,
    price_history: dict[str, list],
) -> tuple[bool, float]:
    """Sembol kendi penceresinde belirgin dip yaptı mı (BTC ile paralel)."""
    prices = _hist_prices(sym, price_history)
    if len(prices) < 6:
        return False, 0.0
    lb = max(6, min(36, _env_int("MEGA_ALT_DIP_LOOKBACK_BARS", 16)))
    window = prices[-lb:]
    peak = max(window)
    low = min(window)
    if peak <= 0 or low >= peak:
        return False, 0.0
    dip_pct = (peak - low) / peak * 100.0
    thr = _env_float("MEGA_ALT_DIP_PCT", 0.55)
    return dip_pct >= thr, dip_pct


def resolve_vol_scan_side(
    sym: str,
    micro_change: float,
    price_history: dict[str, list],
    *,
    min_abs_pct: float,
) -> tuple[str | None, str]:
    """
  Vol tarama yönü — micro + orta trend + BTC rejim.
  Returns (LONG|SHORT|None, block_reason).
  """
    ready, ready_tag = btc_context_ready(price_history)
    if not ready:
        return None, ready_tag

    boost = bear_short_entry_boost()
    eff_min = float(min_abs_pct)
    if float(boost["vol_min_momentum_mult"]) < 1.0 and micro_change < 0:
        eff_min = min_abs_pct * float(boost["vol_min_momentum_mult"])
    if abs(micro_change) < eff_min:
        return None, "micro_move_low"

    try:
        from elite_trader.btc_flash_cascade import bounce_favors_long

        bounce, _ = bounce_favors_long(price_history)
        if bounce and micro_change > 0:
            return "LONG", "btc_bounce_favor_long"
    except Exception:
        pass

    medium = symbol_medium_trend(sym, price_history)
    med_thr = _env_float("MEGA_TREND_MEDIUM_MIN_PCT", 0.06)
    bear, bear_tag = btc_bearish(price_history)
    alt_dip, alt_dip_pct = alt_in_dip(sym, price_history)

    if bear and micro_change > 0:
        try:
            from elite_trader.btc_flash_cascade import bounce_favors_long as _bfl

            _bounce, _ = _bfl(price_history)
        except Exception:
            _bounce = False
        if _bounce:
            return "LONG", "btc_bounce_favor_long"
        if medium <= -med_thr * 0.5:
            return "SHORT", ""
        if _env_bool("MEGA_BEAR_BLOCK_COUNTER_LONG", True):
            return None, bear_tag or "btc_bear_no_long"

    if alt_dip and micro_change > 0 and medium <= 0:
        if _env_bool("MEGA_ALT_DIP_BLOCK_LONG", True):
            return "SHORT" if micro_change >= min_abs_pct else None, "alt_dip_fade"

    if medium >= med_thr:
        if micro_change > 0:
            return "LONG", ""
        if micro_change < 0 and not bear:
            return "SHORT", ""
        return None, "micro_vs_medium"

    if medium <= -med_thr:
        if micro_change < 0:
            return "SHORT", ""
        if micro_change > 0 and bear:
            return None, "bear_bounce_long_blocked"
        if micro_change > 0:
            return "SHORT", "fade_bounce"

    if micro_change > 0:
        if bear:
            return None, bear_tag or "btc_bear"
        return "LONG", ""
    return "SHORT", ""


def _is_flash_long(signal: dict[str, Any]) -> bool:
    if signal.get("flash_pump_reversal") or signal.get("mega_flash_pump"):
        return False
    return bool(
        signal.get("flash_reversal")
        or signal.get("mega_flash_reversal")
        or "FlashReversal-LONG" in str(signal.get("signal_source") or "")
        or "MegaFlashReversal-LONG" in str(signal.get("signal_source") or "")
    )


def _is_flash_short(signal: dict[str, Any]) -> bool:
    return bool(
        signal.get("flash_pump_reversal")
        or signal.get("mega_flash_pump")
        or "FlashReversal-SHORT" in str(signal.get("signal_source") or "")
        or "MegaFlashReversal-SHORT" in str(signal.get("signal_source") or "")
    )


def cluster_allows_side(
    side: str,
    *,
    price_history: dict[str, list] | None = None,
) -> tuple[bool, str]:
    """
    Aynı yönde eşzamanlı açık slot sınırı (varsayılan kapalı).

    Yalnızca halen açık pozisyonlar sayılır — hızlı TP ile kapanan işlemler
    sonraki girişi engellemez. Hızlı scalp için MEGA_CLUSTER_GUARD=0 bırakın.
    """
    if not _env_bool("MEGA_CLUSTER_GUARD", False):
        return True, ""
    if _env_bool("MEGA_CLUSTER_BEAR_ONLY", True):
        bear, _ = btc_bearish(price_history)
        if not bear:
            return True, ""
    s = str(side or "LONG").upper()
    max_same = _env_int("MEGA_CLUSTER_MAX_SAME_SIDE", 4)
    open_only = _env_bool("MEGA_CLUSTER_OPEN_ONLY", True)
    window_sec = _env_float("MEGA_CLUSTER_WINDOW_SEC", 2700.0)
    now = time.time()
    try:
        from elite_trader.mega_live import _mega_max_open, _mega_positions
    except Exception:
        return True, ""

    cap = max_same
    if cap <= 0:
        try:
            cap = _mega_max_open()
        except Exception:
            cap = 4

    open_same = 0
    for p in _mega_positions:
        if str(p.get("side") or p.get("type") or "LONG").upper() != s:
            continue
        if open_only:
            open_same += 1
            continue
        et = float(p.get("entry_time") or 0)
        if et <= 0:
            open_same += 1
            continue
        if now - et <= window_sec:
            open_same += 1
    if open_same >= cap:
        return False, f"cluster_{s.lower()}_{open_same}"
    return True, ""


def btc_context_snapshot(
    price_history: dict[str, list] | None = None,
    *,
    binance_client: Any | None = None,
) -> dict[str, Any]:
    """Panel — BTC rejim + giriş kilidi durumu."""
    btc = btc_context_extended(price_history, binance_client=binance_client)
    ready, ready_tag = btc_context_ready(price_history, binance_client=binance_client)
    bear, bear_tag = btc_bearish(price_history, binance_client=binance_client)
    bounce_long = False
    try:
        from elite_trader.btc_flash_cascade import bounce_favors_long

        bounce_long, _ = bounce_favors_long(price_history)
    except Exception:
        bounce_long = False
    age = None
    try:
        updated = float(btc.get("updated_at") or 0)
        if updated > 0:
            age = round(max(0.0, time.time() - updated), 1)
    except (TypeError, ValueError):
        pass
    regime = str(btc.get("btc_regime") or "unknown").lower()
    labels = {
        "trend_up": "BTC ↑ trend",
        "trend_down": "BTC ↓ trend",
        "chop": "BTC yatay",
        "mixed": "BTC karışık",
        "unknown": "BTC bilinmiyor",
    }
    regime_base = str(btc.get("btc_regime_base") or "").lower()
    if regime_base and regime_base != regime and regime_base in labels:
        regime_label = labels.get(regime, regime) + f" · 1m→{labels.get(regime_base, regime_base)}"
    else:
        regime_label = labels.get(regime, regime)
    cascade: dict[str, Any] = {}
    macro: dict[str, Any] = {}
    try:
        from elite_trader.btc_flash_cascade import cascade_snapshot

        cascade = cascade_snapshot(price_history)
    except Exception:
        pass
    try:
        from elite_trader.btc_macro_feed import macro_snapshot

        macro = macro_snapshot()
    except Exception:
        pass
    liq: dict[str, Any] = {}
    try:
        from elite_trader.btc_liq_feed import liq_snapshot

        liq = liq_snapshot()
    except Exception:
        pass
    return {
        "ready": ready,
        "ready_label": "Hazır" if ready else "Bekle",
        "block_reason": ready_tag if not ready else "",
        "bearish": bear,
        "bear_tag": bear_tag,
        "regime": regime,
        "regime_label": regime_label,
        "regime_base": regime_base or regime,
        "btc_1m_wick_drop_pct": btc.get("btc_1m_wick_drop_pct"),
        "btc_vol_spike": btc.get("btc_vol_spike"),
        "btc_vol_ratio": btc.get("btc_vol_ratio"),
        "btc_book_imbalance": btc.get("btc_book_imbalance"),
        "klines_interval": btc.get("klines_interval"),
        "btc_price": btc.get("btc_price"),
        "btc_24h_change": btc.get("btc_24h_change"),
        "btc_recent_drop_pct": btc.get("btc_recent_drop_pct"),
        "context_age_sec": age,
        "long_allowed": ready and (not bear or bounce_long),
        "short_favored": bear and not bounce_long,
        "btc_cascade": cascade,
        "btc_macro": macro,
        "btc_liq": liq,
    }


def mega_entry_allowed(
    signal: dict[str, Any],
    *,
    price_history: dict[str, list] | None = None,
    binance_client: Any | None = None,
) -> tuple[bool, str]:
    """MEGA açılış öncesi — rejim, BTC, kümeleme."""
    if not enabled():
        return True, ""
    ph = price_history if price_history is not None else _price_history()
    ready, ready_tag = btc_context_ready(ph, binance_client=binance_client)
    if not ready:
        return False, ready_tag

    try:
        from elite_trader.btc_macro_feed import macro_entry_allowed

        ok_macro, macro_tag = macro_entry_allowed(
            str(signal.get("type") or "LONG"), signal
        )
        if not ok_macro:
            return False, macro_tag
    except Exception:
        pass

    side = str(signal.get("type") or "LONG").upper()

    try:
        from elite_trader.btc_liq_feed import liq_entry_allowed

        ok_liq, liq_tag = liq_entry_allowed(side)
        if not ok_liq:
            return False, liq_tag
    except Exception:
        pass

    sym = _norm_symbol(str(signal.get("symbol") or ""))

    ok_cluster, cluster_tag = cluster_allows_side(side, price_history=ph)
    if not ok_cluster:
        return False, cluster_tag

    if signal.get("mega_btc_cascade_long") or signal.get("mega_btc_cascade_direct"):
        return True, ""

    if _is_flash_long(signal):
        bear, tag = btc_bearish(ph, binance_client=binance_client)
        if bear and _env_bool("MEGA_FLASH_LONG_BLOCK_IN_BEAR", True):
            return False, tag or "btc_bear_flash_long"
        return True, ""

    if signal.get("mega_btc_cascade_short"):
        return True, ""

    if _is_flash_short(signal):
        return True, ""

    if side == "SHORT":
        try:
            from elite_trader.btc_flash_cascade import cascade_blocks_late_short

            late, late_tag = cascade_blocks_late_short(ph)
            if late:
                return False, late_tag
        except Exception:
            pass

    bear, bear_tag = btc_bearish(ph, binance_client=binance_client)
    bounce_long = False
    try:
        from elite_trader.btc_flash_cascade import bounce_favors_long

        bounce_long, _ = bounce_favors_long(ph)
    except Exception:
        bounce_long = False
    if (
        side == "LONG"
        and bear
        and not bounce_long
        and _env_bool("MEGA_BEAR_BLOCK_LONG", True)
    ):
        return False, bear_tag or "btc_bear_long"

    if side == "LONG":
        medium = symbol_medium_trend(sym, ph)
        med_thr = _env_float("MEGA_TREND_MEDIUM_MIN_PCT", 0.06)
        if (
            not bounce_long
            and medium <= -med_thr
            and _env_bool("MEGA_MEDIUM_BEAR_BLOCK_LONG", True)
        ):
            return False, "symbol_medium_bear"
        alt_dip, _ = alt_in_dip(sym, ph)
        micro = float(signal.get("change") or symbol_momentum(sym, ph))
        if (
            not bounce_long
            and alt_dip
            and micro > 0
            and _env_bool("MEGA_ALT_DIP_BLOCK_LONG", True)
        ):
            return False, "alt_dip_long"

    if side == "SHORT" and not bear:
        ch24 = btc_context_extended(ph).get("btc_24h_change")
        if ch24 is not None and float(ch24) >= _env_float("MEGA_BTC_BULL_BLOCK_SHORT_24H", 2.5):
            if _env_bool("MEGA_BULL_BLOCK_SHORT", False):
                return False, "btc_24h_bull_short"

    return True, ""
