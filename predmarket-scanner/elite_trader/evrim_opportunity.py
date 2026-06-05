"""
Evrim — Opportunity hunter (noise değil fırsat).

Yalnızca evrim giriş yolunda çalışır; diğer modlara dokunmaz.
Öğrenme rehberi + 5 filtre + rejim (trend/chop) + gelişim seviyesi.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.panel_strategy import stake_targets

MODE_ID = "evrim"
_ROOT = Path(__file__).resolve().parent.parent
_STATE_PATH = _ROOT / "data" / "evrim_adaptive_state.json"
_GUIDE_PATH = _ROOT / "data" / "evrim_learning_guide.json"

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 300.0  # 5 dakika — ilk scan sonrası tekrar API çağrısı yapma
_client: Any = None

# Arka plan context önbellekleme — scan döngüsünü bloke etmez
_ctx_fetch_in_progress: set[str] = set()
_ctx_lock = __import__("threading").Lock()
_ctx_executor: Any = None


def _get_ctx_executor():
    global _ctx_executor
    if _ctx_executor is None:
        from concurrent.futures import ThreadPoolExecutor
        _ctx_executor = ThreadPoolExecutor(max_workers=12, thread_name_prefix="ctx-fetch")
    return _ctx_executor


def _bg_fetch_context(symbol: str) -> None:
    """Arka planda context verisini çek, önbelleğe yaz."""
    coin = symbol.replace("USDT", "").upper()
    key = coin
    with _ctx_lock:
        if key in _ctx_fetch_in_progress:
            return
        _ctx_fetch_in_progress.add(key)
    try:
        ctx = _do_fetch_context(symbol)
        now = time.time()
        _CACHE[key] = (now, ctx)
    except Exception:
        pass
    finally:
        with _ctx_lock:
            _ctx_fetch_in_progress.discard(key)


def _fallback_ctx(symbol: str) -> dict[str, Any]:
    """Anlık API verisi yokken kullanılan minimum bağlam."""
    return {
        "ok": True,
        "regime": "mixed",
        "vol_ratio": 1.5,
        "atr_pct": 0.08,
        "spread_pct": 0.05,
        "funding_abs": 0,
        "ema_trend": "flat",
        "direction_3": "none",
        "btc_regime": "unknown",
        "chop": False,
        "price": 1.0,
        "fallback": True,
        "symbol": symbol,
        "coin": symbol.replace("USDT", "").upper(),
    }

# Öğrenme rehberi (kullanıcı prompt özeti)
LEARNING_GUIDE: dict[str, Any] = {
    "version": 1,
    "title": "Evrim öğrenme rehberi",
    "core_problem": [
        "Gerçek edge yoksa ayar değişimi sonuç vermez (noise ≈ random).",
        "Market emir + slippage > fee hızlı botta.",
        "Hard veto yerine skor/stake cezası — önce demo işlem akışı (hedef 100 trade).",
    ],
    "risk_policy_v2": [
        "spread_halt yalnızca spread > TP×55% veya 30sn ort.×3 veya likidite çöküşü.",
        "news_shock max 90sn; haber yoksa volatility_shock (stake düşür, yasaklama).",
        "chop: stake×0.35, TP dar, işlem açık (mean reversion / micro scalp).",
        "radar: penalty -3/-8/-15; yalnızca extreme veto.",
        "30dk borsa açılan 0 → eşik -5, spread soft, recovery modu.",
    ],
    "goal": "Opportunity hunter — liquidation sweep, breakout, volume imbalance, trend continuation.",
    "not": "Every movement = signal",
    "filters": [
        "Volume: now > 1.8× avg",
        "ATR: düşük volatilitede yasak",
        "Spread < TP'nin %18'i",
        "EMA trend yönünde",
        "2 ardışık SL → coin 20dk ban",
    ],
    "measure": "PnL grouped by market regime (trend vs chop)",
    "perfection": "Kullanıcı onayı — seviye 100 manuel",
    "hybrid_scoring": {
        "price_action": 25,
        "volume_delta": 20,
        "volatility_atr": 15,
        "trend_ema": 15,
        "orderbook_liquidity": 10,
        "news_whale_risk": 10,
        "execution_quality": 5,
        "no_trade_below": 55,
        "normal": 65,
        "aggressive": 75,
        "max_aggressive": 85,
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(patch: dict[str, Any]) -> None:
    st = _load_state()
    st.update(patch)
    ev = st.setdefault("evolution", {})
    if ev.get("level", 0) >= 100:
        ev["level"] = 100
        ev["title"] = "Kusursuz (onaylı)"
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(
        json.dumps(st, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _get_client() -> Any:
    global _client
    if _client is None:
        from binance_futures_trader.client import BinanceFuturesClient

        _client = BinanceFuturesClient()
    return _client


def _coin(symbol: str) -> str:
    s = str(symbol or "").upper()
    return s.replace("USDT", "") if s.endswith("USDT") else s


def _ema(values: list[float], period: int) -> float:
    if not values or period < 1:
        return 0.0
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _atr_pct(candles: list[dict[str, Any]], period: int = 14) -> float:
    if len(candles) < period + 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(candles)):
        h = float(candles[i]["h"])
        l = float(candles[i]["l"])
        pc = float(candles[i - 1]["c"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return 0.0
    atr = sum(trs[-period:]) / period
    last = float(candles[-1]["c"]) or 1.0
    return (atr / last) * 100.0


def _do_fetch_context(symbol: str) -> dict[str, Any]:
    """Gerçek API context çekimi — sadece arka plan thread'inden çağrılır."""
    coin = _coin(symbol)
    key = coin
    now = time.time()
    ctx: dict[str, Any] = {"symbol": symbol, "coin": coin, "ok": False}
    try:
        c = _get_client()
        kl = c.klines(coin, "5m", 40) or []
        if len(kl) < 20:
            _CACHE[key] = (now, ctx)
            return ctx
        closes = [float(x["c"]) for x in kl]
        vols = [float(x["v"]) for x in kl]
        atr_pct = _atr_pct(kl)
        ema9 = _ema(closes[-25:], 9)
        ema21 = _ema(closes[-30:], 21)
        vol_now = vols[-1]
        vol_avg = sum(vols[-20:]) / max(1, min(20, len(vols)))
        vol_ratio = vol_now / vol_avg if vol_avg > 0 else 0.0
        last3 = closes[-3:]
        up3 = last3[0] < last3[1] < last3[2]
        down3 = last3[0] > last3[1] > last3[2]
        trend = "up" if ema9 > ema21 * 1.0003 else "down" if ema9 < ema21 * 0.9997 else "flat"
        chop = atr_pct < 0.06 and abs(closes[-1] - closes[-10]) / closes[-10] * 100 < 0.15
        regime = "chop" if chop else ("trend_up" if trend == "up" else "trend_down" if trend == "down" else "mixed")

        spread_pct = 0.05
        try:
            sym = f"{coin}USDT"
            bt = c._get("/fapi/v1/ticker/bookTicker", {"symbol": sym})
            bid = float(bt.get("bidPrice") or 0)
            ask = float(bt.get("askPrice") or 0)
            mid = (bid + ask) / 2 if bid and ask else 0
            if mid > 0:
                spread_pct = ((ask - bid) / mid) * 100.0
        except Exception:
            pass

        funding = 0.0
        try:
            pi = c._get("/fapi/v1/premiumIndex", {"symbol": f"{coin}USDT"})
            funding = abs(float(pi.get("lastFundingRate") or 0))
        except Exception:
            pass

        btc_regime = regime if coin == "BTC" else "unknown"
        if coin != "BTC":
            try:
                bkl = c.klines("BTC", "5m", 25) or []
                if len(bkl) >= 15:
                    bc = [float(x["c"]) for x in bkl]
                    be9 = _ema(bc[-20:], 9)
                    be21 = _ema(bc[-22:], 21)
                    bt = "up" if be9 > be21 * 1.0003 else "down" if be9 < be21 * 0.9997 else "flat"
                    bchop = _atr_pct(bkl) < 0.06
                    btc_regime = "chop" if bchop else f"trend_{bt}" if bt != "flat" else "mixed"
            except Exception:
                btc_regime = "unknown"

        last_kl = kl[-1] if kl else {}
        klines_5m = [
            {
                "o": float(x.get("o", 0)),
                "h": float(x.get("h", 0)),
                "l": float(x.get("l", 0)),
                "c": float(x.get("c", 0)),
                "v": float(x.get("v", 0)),
            }
            for x in kl[-35:]
        ]
        ctx = {
            "ok": True,
            "atr_pct": round(atr_pct, 4),
            "vol_ratio": round(vol_ratio, 3),
            "spread_pct": round(spread_pct, 5),
            "funding_abs": round(funding, 6),
            "ema_trend": trend,
            "direction_3": "up" if up3 else "down" if down3 else "none",
            "regime": regime,
            "regime_legacy": regime,
            "btc_regime": btc_regime,
            "chop": chop,
            "price": closes[-1],
            "klines_5m": klines_5m,
            "last_candle": {
                "o": float(last_kl.get("o", closes[-1])),
                "h": float(last_kl.get("h", closes[-1])),
                "l": float(last_kl.get("l", closes[-1])),
                "c": float(last_kl.get("c", closes[-1])),
            },
        }
        try:
            from elite_trader.mode_profiles import get_profile

            prof = get_profile(MODE_ID) or {}
            if prof.get("evrim_vo_enabled", True):
                from elite_trader.evrim_volume_orderbook import fetch_market_microstructure

                ctx["vo_snapshot"] = fetch_market_microstructure(
                    symbol,
                    prof,
                    spread_pct=ctx.get("spread_pct"),
                    price=ctx.get("price"),
                )
        except Exception:
            pass
    except Exception as exc:
        ctx["error"] = str(exc)[:120]
    _CACHE[key] = (now, ctx)
    return ctx


def _fetch_context(symbol: str) -> dict[str, Any]:
    """Önbellekten döner; yoksa fallback + arka plan fetch — scan bloke olmaz."""
    coin = _coin(symbol)
    key = coin
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    # Arka planda gerçek context çek
    try:
        _get_ctx_executor().submit(_bg_fetch_context, symbol)
    except Exception:
        pass
    return _fallback_ctx(symbol)


def _loss_streak_ban(symbol: str, ban_min: int) -> str | None:
    st = _load_state()
    if time.time() < float(st.get("loss_ban_paused_until") or 0):
        return None
    bans = st.get("symbol_bans") or {}
    until = float(bans.get(symbol) or 0)
    if time.time() < until:
        return f"loss_ban_{int((until - time.time()) / 60)}m"
    book = (__import__("elite_trader.parallel_universe_engine", fromlist=["get_books"]).get_books() or {}).get(MODE_ID) or {}
    closed = list(book.get("closed") or [])
    streak = 0
    for row in reversed(closed):
        if row.get("symbol") != symbol:
            continue
        pnl = float(row.get("final_pnl") or row.get("net_pnl") or 0)
        reason = str(row.get("exit_reason") or "")
        if pnl < 0 and "SL" in reason.upper():
            streak += 1
        else:
            break
        if streak >= 2:
            bans[symbol] = time.time() + ban_min * 60
            st["symbol_bans"] = bans
            _save_state(st)
            return f"2xSL_ban_{ban_min}m"
    return None


def _record_rejection(reason: str, ctx: dict[str, Any]) -> None:
    st = _load_state()
    ev = st.setdefault("evolution", _default_evolution())
    fs = ev.setdefault("filter_rejects", {})
    fs[reason] = int(fs.get(reason, 0)) + 1
    ev["rejections_total"] = int(ev.get("rejections_total", 0)) + 1
    _save_state(st)


def _default_evolution() -> dict[str, Any]:
    return {
        "level": 1,
        "xp": 0,
        "max_level": 99,
        "title": "Çırak",
        "filter_rejects": {},
        "regime_pnl": {"trend": 0.0, "chop": 0.0, "mixed": 0.0},
        "wins_trend": 0,
        "losses_chop": 0,
        "trades_total": 0,
        "rejections_total": 0,
    }


def _level_title(level: int) -> str:
    titles = [
        (1, "Çırak"), (5, "Öğrenci"), (10, "Avcı"), (15, "Tüccar"),
        (20, "Stratejist"), (30, "Usta"), (40, "Uzman"), (50, "Elit"),
        (60, "Master"), (70, "Grandmaster"), (80, "Efsane"), (90, "Evrim"),
        (99, "Kusursuza yakın"),
    ]
    t = "Çırak"
    for lv, name in titles:
        if level >= lv:
            t = name
    return t


def _add_xp(delta: int, reason: str) -> None:
    st = _load_state()
    ev = st.setdefault("evolution", _default_evolution())
    if ev.get("level", 0) >= 100:
        return
    ev["xp"] = int(ev.get("xp", 0)) + delta
    ev["last_xp_reason"] = reason
    # ~50 XP = 1 seviye; 99 = ~4950 XP
    new_level = min(99, max(1, 1 + ev["xp"] // 50))
    if new_level > ev.get("level", 1):
        ev["level"] = new_level
        ev["title"] = _level_title(new_level)
        print(f"  🧬 Evrim seviye ↑ {new_level} — {ev['title']} ({reason})")
    else:
        ev["level"] = new_level
        ev["title"] = _level_title(new_level)
    st["evolution"] = ev
    _save_state(st)


def opportunity_check(
    signal: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    """
    5 filtre + rejim. Dönüş: (ok, reason, context).
    """
    symbol = str(signal.get("symbol") or "")
    side = str(signal.get("type") or "LONG")
    if not symbol:
        return False, "no_symbol", {}

    vol_mult = float(profile.get("evrim_vol_mult") or 1.8)
    atr_min = float(profile.get("evrim_atr_min_pct") or 0.055)
    spread_tp_frac = float(profile.get("evrim_spread_tp_frac") or 0.18)
    ban_min = int(profile.get("evrim_loss_ban_min") or 20)
    funding_max = float(profile.get("evrim_funding_max") or 0.0008)

    ban = _loss_streak_ban(symbol, ban_min)
    if ban:
        _record_rejection(ban, {})
        return False, ban, {}

    ctx = _fetch_context(symbol)
    if not ctx.get("ok"):
        _record_rejection("market_data", ctx)
        return False, "market_data", ctx

    regime = str(ctx.get("regime") or "mixed")
    if regime == "chop" and not profile.get("evrim_chop_trade_enabled", True):
        _record_rejection("chop_regime", ctx)
        return False, "chop_regime", ctx

    if ctx.get("vol_ratio", 0) < vol_mult:
        _record_rejection("volume", ctx)
        return False, "volume_spike", ctx

    if float(ctx.get("atr_pct") or 0) < atr_min:
        _record_rejection("atr_low", ctx)
        return False, "atr_low", ctx

    stake_est = float(profile.get("min_stake_usd") or 140)
    tp_usd, _ = stake_targets(stake_est, MODE_ID)
    spread_cost = float(ctx.get("price") or 1) * float(ctx.get("spread_pct") or 0) / 100.0 * stake_est
    tp_ref = max(tp_usd, 0.5)
    if spread_cost > tp_ref * spread_tp_frac:
        _record_rejection("spread", ctx)
        return False, "spread_wide", ctx

    if float(ctx.get("funding_abs") or 0) > funding_max:
        _record_rejection("funding", ctx)
        return False, "funding_imbalance", ctx

    btc_r = str(ctx.get("btc_regime") or "")
    if btc_r == "chop":
        _record_rejection("btc_chop", ctx)
        return False, "btc_flat", ctx

    trend = str(ctx.get("ema_trend") or "")
    if side == "LONG" and trend == "down":
        _record_rejection("trend", ctx)
        return False, "against_trend", ctx
    if side == "SHORT" and trend == "up":
        _record_rejection("trend", ctx)
        return False, "against_trend", ctx

    d3 = str(ctx.get("direction_3") or "none")
    if side == "LONG" and d3 == "down":
        _record_rejection("no_direction", ctx)
        return False, "no_3m_direction", ctx
    if side == "SHORT" and d3 == "up":
        _record_rejection("no_direction", ctx)
        return False, "no_3m_direction", ctx

    return True, "opportunity", ctx


def evrim_entry_gate(
    mode_id: str,
    signal: dict[str, Any],
    profile: dict[str, Any],
    *,
    execution_path: str = "paper",
) -> tuple[bool, str]:
    if mode_id != MODE_ID:
        return True, ""
    if profile.get("evrim_unified_engine_enabled", True):
        try:
            from elite_trader.evrim_unified_engine import process_entry

            return process_entry(
                mode_id, signal, profile, execution_path=execution_path
            )
        except Exception:
            pass
    try:
        from elite_trader.evrim_training import is_live_training_enabled

        use_hybrid = is_live_training_enabled(profile)
    except Exception:
        use_hybrid = bool(profile.get("evrim_live_training", True))

    if use_hybrid:
        from elite_trader.evrim_hybrid_scorer import (
            decision_to_gate_tuple,
            evaluate,
        )

        dec = evaluate(
            signal,
            profile,
            execution_path=execution_path,
            log_decision=True,
        )
        ok, reason, ctx = decision_to_gate_tuple(dec)
        if ok:
            st = _load_state()
            st["last_opportunity_ctx"] = ctx
            _save_state(st)
            _add_xp(1, "hybrid_pass")
            signal["evrim_hybrid"] = {
                "total_score": dec.total_score,
                "tier": dec.tier,
                "stake_mult": dec.stake_mult,
                "components": dec.components,
                "expected_net_pnl_usd": dec.expected_net_pnl_usd,
            }
            if signal.get("evrim_dynamic_exit"):
                signal["evrim_hybrid"]["dynamic_exit"] = signal["evrim_dynamic_exit"]
            if (dec.context or {}).get("expectancy"):
                signal["evrim_hybrid"]["expectancy"] = dec.context["expectancy"]
            signal["evrim_entry_reason"] = reason[:200]
            if signal.get("evrim_regime"):
                ctx["market_regime"] = signal["evrim_regime"].get("id")
            return True, reason[:80]
        return False, reason[:80]

    ok, reason, ctx = opportunity_check(signal, profile)
    if ok:
        st = _load_state()
        st["last_opportunity_ctx"] = ctx
        _save_state(st)
        _add_xp(1, "filter_pass")
        return True, reason
    if reason in ("market_data", "market_data_skip"):
        ch = abs(float(signal.get("change") or 0))
        strength = str(signal.get("strength") or "")
        if ch >= 0.38 and strength in ("Strong", "Medium"):
            return True, "momentum_fallback"
    return False, reason


def get_last_hybrid_meta(signal: dict[str, Any]) -> dict[str, Any]:
    return dict(signal.get("evrim_hybrid") or {})


def on_trade_closed_evrim(closed: dict[str, Any], ctx: dict[str, Any] | None = None) -> None:
    pnl = float(closed.get("final_pnl") or closed.get("net_pnl") or 0)
    regime = str(
        (ctx or {}).get("market_regime")
        or closed.get("market_regime")
        or (ctx or {}).get("regime")
        or "mixed"
    )
    st = _load_state()
    ev = st.setdefault("evolution", _default_evolution())
    rp = ev.setdefault("regime_pnl", {"trend": 0.0, "chop": 0.0, "mixed": 0.0})
    bucket = "trend" if "trend" in regime else "chop" if regime == "chop" else "mixed"
    rp[bucket] = round(float(rp.get(bucket, 0)) + pnl, 2)
    try:
        from elite_trader.evrim_market_regime import REGIMES
        from elite_trader.evrim_training import _save_training_state, load_training_state

        rid = regime if regime in REGIMES else "chop"
        ts = load_training_state()
        rs = ts.setdefault("regime_stats", {})
        row = rs.setdefault(rid, {"pnl": 0.0, "trades": 0, "wins": 0})
        row["pnl"] = round(float(row.get("pnl", 0)) + pnl, 2)
        row["trades"] = int(row.get("trades", 0)) + 1
        if pnl > 0:
            row["wins"] = int(row.get("wins", 0)) + 1
        _save_training_state(ts)
    except Exception:
        pass
    try:
        from elite_trader.evrim_expectancy import record_closed_trade

        gross = float(closed.get("pnl_usd") or closed.get("final_pnl") or pnl)
        fees = float(closed.get("total_fees") or 0)
        net = float(closed.get("final_pnl") or closed.get("net_pnl") or pnl)
        ec = closed.get("entry_context") or {}
        record_closed_trade(
            gross_pnl=gross,
            net_pnl=net,
            fees_usd=fees,
            spread_pct=float(ec.get("spread_pct") or 0),
            slippage_bps=float(ec.get("slippage_bps") or 0),
        )
    except Exception:
        pass
    try:
        from elite_trader.evrim_trade_learning import append_trade_record, build_trade_record

        append_trade_record(
            build_trade_record(closed, ctx=ctx)
        )
    except Exception:
        pass
    try:
        from elite_trader.panel_strategy import is_live_binance_motor

        if is_live_binance_motor(MODE_ID) and (
            closed.get("on_exchange")
            or str(closed.get("data_source") or "") == "live"
        ):
            from elite_trader.evrim_market_radar import record_trade_outcome_radar

            record_trade_outcome_radar(
                exit_reason=str(closed.get("exit_reason") or ""),
                net_pnl=float(closed.get("final_pnl") or closed.get("net_pnl") or 0),
                stake_usd=float(closed.get("stake_usd") or 140),
            )
    except Exception:
        pass
    ev["trades_total"] = int(ev.get("trades_total", 0)) + 1
    if pnl > 0:
        if bucket == "trend":
            ev["wins_trend"] = int(ev.get("wins_trend", 0)) + 1
            _add_xp(8, "win_trend")
        else:
            _add_xp(4, "win")
    else:
        if bucket == "chop" or regime == "chop":
            ev["losses_chop"] = int(ev.get("losses_chop", 0)) + 1
            _add_xp(-5, "loss_chop")
        else:
            _add_xp(-2, "loss")
    st["evolution"] = ev
    _save_state(st)


def evolution_snapshot() -> dict[str, Any]:
    st = _load_state()
    ev = st.get("evolution") or _default_evolution()
    level = int(ev.get("level", 1))
    xp = int(ev.get("xp", 0))
    next_xp = (level + 1) * 50 if level < 99 else xp
    progress_pct = min(100.0, (xp % 50) / 50.0 * 100) if level < 99 else 100.0
    return {
        **ev,
        "level": level,
        "xp": xp,
        "xp_to_next_level": max(0, next_xp - xp),
        "level_progress_pct": round(progress_pct, 1),
        "learning_guide": LEARNING_GUIDE,
        "perfection_note": "Seviye 100 yalnızca sizin onayınızla (kusursuz mod).",
        "top_rejects": sorted(
            (ev.get("filter_rejects") or {}).items(),
            key=lambda x: -x[1],
        )[:8],
    }


def persist_learning_guide() -> None:
    _GUIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GUIDE_PATH.write_text(
        json.dumps(LEARNING_GUIDE, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
