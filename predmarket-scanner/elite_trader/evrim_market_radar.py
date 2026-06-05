"""
Evrim — aktif piyasa risk ve fırsat radarı.

Kaynaklar: ticker, funding, OI, liquidation proxy, hacim, haber proxy,
BTC dominans, acil durum ve fırsat modu. Yalnızca evrim.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SOURCE_TYPES = (
    "binance_ticker",
    "funding_rates",
    "open_interest",
    "liquidation_proxy",
    "volume_spike",
    "whale_alerts",
    "btc_dominance",
    "crypto_news",
    "etf_regulation",
    "macro_calendar",
    "exchange_announcements",
    "listing_delisting",
)


@dataclass
class RadarResult:
    ok: bool = True
    feeds: dict[str, Any] = field(default_factory=dict)
    news_sentiment: str = "neutral"
    news_headline: str = ""
    opportunity_mode: bool = False
    opportunity_tags: list[str] = field(default_factory=list)
    emergency_level: str = "normal"
    block_new_entries: bool = False
    reduce_open_risk: bool = False
    stake_mult: float = 1.0
    long_score_delta: float = 0.0
    short_score_delta: float = 0.0
    min_score_delta: int = 0
    max_tier_cap: str | None = None
    market_order_scale: float = 1.0
    notes: list[str] = field(default_factory=list)
    veto: bool = False
    veto_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "feeds": self.feeds,
            "news_sentiment": self.news_sentiment,
            "news_headline": self.news_headline,
            "opportunity_mode": self.opportunity_mode,
            "opportunity_tags": self.opportunity_tags,
            "emergency_level": self.emergency_level,
            "block_new_entries": self.block_new_entries,
            "reduce_open_risk": self.reduce_open_risk,
            "stake_mult": self.stake_mult,
            "long_score_delta": self.long_score_delta,
            "short_score_delta": self.short_score_delta,
            "min_score_delta": self.min_score_delta,
            "max_tier_cap": self.max_tier_cap,
            "market_order_scale": self.market_order_scale,
            "notes": self.notes[:15],
            "veto": self.veto,
            "veto_reason": self.veto_reason,
        }


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _coin(symbol: str) -> str:
    s = str(symbol or "").upper()
    return s.replace("USDT", "") if s.endswith("USDT") else s


def _load_radar_state() -> dict[str, Any]:
    try:
        from elite_trader.evrim_training import load_training_state

        return dict(load_training_state().get("market_radar_state") or {})
    except Exception:
        return {}


def _save_radar_state(patch: dict[str, Any]) -> None:
    try:
        from elite_trader.evrim_training import load_training_state, _save_training_state

        st = load_training_state()
        rs = st.setdefault("market_radar_state", {})
        rs.update(patch)
        st["market_radar_state"] = rs
        _save_training_state(st)
    except Exception:
        pass


def _fetch_feeds(client: Any, symbol: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Binance + ctx birleşik feed özeti."""
    coin = _coin(symbol)
    sym = f"{coin}USDT"
    feeds: dict[str, Any] = {}
    t0 = time.perf_counter()

    feeds["binance_ticker"] = {"status": "proxy", "from": "ctx"}
    try:
        t24 = client._get("/fapi/v1/ticker/24hr", {"symbol": sym})
        feeds["binance_ticker"] = {
            "status": "ok",
            "change_pct": float(t24.get("priceChangePercent") or 0),
            "volume": float(t24.get("volume") or 0),
            "quote_volume": float(t24.get("quoteVolume") or 0),
        }
    except Exception as exc:
        feeds["binance_ticker"] = {"status": "error", "error": str(exc)[:60]}

    funding_rate = float(ctx.get("funding_abs") or 0)
    funding_sign = 0.0
    try:
        pi = client._get("/fapi/v1/premiumIndex", {"symbol": sym})
        funding_rate = float(pi.get("lastFundingRate") or 0)
        funding_sign = funding_rate
        feeds["funding_rates"] = {
            "status": "ok",
            "rate": funding_rate,
            "mark_price": float(pi.get("markPrice") or 0),
        }
    except Exception as exc:
        feeds["funding_rates"] = {"status": "error", "error": str(exc)[:60]}

    oi_val = 0.0
    try:
        oi = client._get("/fapi/v1/openInterest", {"symbol": sym})
        oi_val = float(oi.get("openInterest") or 0)
        feeds["open_interest"] = {"status": "ok", "oi": oi_val}
    except Exception as exc:
        feeds["open_interest"] = {"status": "proxy", "oi": 0}

    vol_ratio = float(ctx.get("vol_ratio") or 1.0)
    wick = 0.0
    lc = ctx.get("last_candle") or {}
    if lc:
        h, l, o, c = float(lc["h"]), float(lc["l"]), float(lc["o"]), float(lc["c"])
        rng = max(h - l, 1e-12)
        wick = max(0.0, (rng - abs(c - o)) / rng)
    liq_proxy = vol_ratio >= 2.5 and (wick >= 0.55 or abs(funding_sign) >= 0.001)
    feeds["liquidation_proxy"] = {
        "status": "ok",
        "detected": liq_proxy,
        "vol_ratio": vol_ratio,
        "wick_ratio": round(wick, 3),
    }
    feeds["volume_spike"] = {
        "status": "ok",
        "rel_vol": vol_ratio,
        "spike": vol_ratio >= 1.8,
    }

    feeds["whale_alerts"] = {"status": "placeholder", "detected": vol_ratio >= 2.8}

    btc_dom = 50.0
    try:
        btc_t = client._get("/fapi/v1/ticker/24hr", {"symbol": "BTCUSDT"})
        eth_t = client._get("/fapi/v1/ticker/24hr", {"symbol": "ETHUSDT"})
        bq = float(btc_t.get("quoteVolume") or 1)
        eq = float(eth_t.get("quoteVolume") or 1)
        btc_dom = bq / max(bq + eq, 1) * 100
        feeds["btc_dominance"] = {"status": "ok", "pct": round(btc_dom, 2)}
    except Exception:
        feeds["btc_dominance"] = {"status": "proxy", "pct": 52.0}

    stored_news = _load_stored_headlines()
    feeds["crypto_news"] = stored_news.get("crypto_news") or {"status": "placeholder"}
    feeds["etf_regulation"] = stored_news.get("etf_regulation") or {"status": "placeholder"}
    feeds["macro_calendar"] = stored_news.get("macro_calendar") or {"status": "placeholder"}
    feeds["exchange_announcements"] = stored_news.get("exchange_announcements") or {
        "status": "placeholder"
    }
    feeds["listing_delisting"] = stored_news.get("listing_delisting") or {"status": "placeholder"}

    latency_ms = (time.perf_counter() - t0) * 1000
    feeds["api_latency_ms"] = round(latency_ms, 1)
    feeds["spread_pct"] = float(ctx.get("spread_pct") or 0.05)
    return feeds


def _load_stored_headlines() -> dict[str, Any]:
    try:
        from elite_trader.evrim_training import load_training_state

        return dict(load_training_state().get("radar_news_feed") or {})
    except Exception:
        return {}


def classify_news(
    feeds: dict[str, Any],
    ctx: dict[str, Any],
    side: str,
) -> tuple[str, str, float, float]:
    """
    bullish / bearish / uncertain / neutral
    Dönüş: sentiment, headline, long_delta, short_delta
    """
    long_d = short_d = 0.0
    headline = ""

    for bucket, key in (
        ("crypto_news", "crypto"),
        ("etf_regulation", "etf"),
        ("exchange_announcements", "exchange"),
        ("listing_delisting", "listing"),
    ):
        block = feeds.get(bucket) or {}
        if block.get("status") == "ok" and block.get("headline"):
            headline = str(block.get("headline"))[:120]
            sent = str(block.get("sentiment") or "uncertain")
            if sent == "bullish":
                long_d += 4
            elif sent == "bearish":
                short_d += 4
            elif sent == "uncertain":
                return "uncertain", headline, 0.0, 0.0
            break

    ch = float((feeds.get("binance_ticker") or {}).get("change_pct") or 0)
    fund = float((feeds.get("funding_rates") or {}).get("rate") or 0)
    if ch >= 1.5 and fund >= 0:
        return "bullish", headline or "ticker_momentum_up", 5.0, -1.0
    if ch <= -1.5 and fund <= 0:
        return "bearish", headline or "ticker_momentum_down", -1.0, 5.0
    if abs(ch) < 0.3 and abs(fund) < 0.0003:
        return "neutral", headline, 0.0, 0.0
    if fund > 0.0005:
        long_d += 2
    elif fund < -0.0005:
        short_d += 2
    if ch > 0.5:
        long_d += 2
    elif ch < -0.5:
        short_d += 2
    if long_d > short_d + 2:
        return "bullish", headline, long_d, short_d
    if short_d > long_d + 2:
        return "bearish", headline, long_d, short_d
    return "neutral", headline, long_d, short_d


def detect_opportunity(
    feeds: dict[str, Any],
    ctx: dict[str, Any],
    vo: dict[str, Any] | None,
    regime_id: str,
) -> tuple[bool, list[str], float]:
    tags: list[str] = []
    stake_boost = 1.0
    if (feeds.get("liquidation_proxy") or {}).get("detected"):
        tags.append("liquidation_cascade")
    if float((feeds.get("volume_spike") or {}).get("rel_vol") or 0) >= 2.0:
        tags.append("volume_explosion")
    pa = ctx.get("pa") or {}
    if pa.get("detected") and "breakout" in str(pa.get("detected")):
        tags.append("breakout_confirmation")
    if regime_id == "breakout":
        tags.append("breakout_confirmation")
    vo_s = (vo or {}).get("signals") or {}
    if vo_s.get("orderbook_sweep", {}).get("detected"):
        tags.append("orderbook_sweep")
    if tags:
        stake_boost = 1.12 if len(tags) >= 2 else 1.06
    return bool(tags), tags, stake_boost


def evaluate_emergency(
    profile: dict[str, Any],
    ctx: dict[str, Any],
    feeds: dict[str, Any],
) -> dict[str, Any]:
    """Acil durum kuralları."""
    out = {
        "level": "normal",
        "block_new_entries": False,
        "reduce_open_risk": False,
        "stake_mult": 1.0,
        "min_score_delta": 0,
        "max_tier_cap": None,
        "market_order_scale": 1.0,
        "reasons": [],
    }
    spread = float(feeds.get("spread_pct") or ctx.get("spread_pct") or 0)
    spread_spike = float(profile.get("evrim_radar_spread_spike_pct") or 0.25)
    sym = str(ctx.get("symbol") or "")
    try:
        from elite_trader.evrim_risk_policy import assess_spread_risk

        assess = assess_spread_risk(sym, spread, ctx, profile)
        if assess.get("hard_veto"):
            out.update(
                {
                    "level": "spread_halt",
                    "block_new_entries": True,
                    "reasons": ["spread_extreme"],
                }
            )
            return out
        if assess.get("reason") == "spread_soft_penalty":
            out["level"] = "spread_soft"
            out["stake_mult"] = min(out["stake_mult"], float(assess.get("stake_mult") or 0.55))
            out["min_score_delta"] = max(out["min_score_delta"], 2)
            out["reasons"].append("spread_soft_penalty")
        elif spread >= spread_spike:
            out["level"] = "spread_elevated"
            out["stake_mult"] = min(out["stake_mult"], 0.7)
            out["min_score_delta"] = max(out["min_score_delta"], 1)
            out["reasons"].append("spread_elevated")
    except Exception:
        if spread >= spread_spike:
            out["level"] = "spread_elevated"
            out["stake_mult"] = min(out["stake_mult"], 0.7)
            out["reasons"].append("spread_spike_legacy")

    latency = float(feeds.get("api_latency_ms") or 0)
    if latency >= float(profile.get("evrim_radar_api_max_ms") or 2500):
        out.update(
            {
                "level": "api_slow",
                "block_new_entries": True,
                "reasons": ["api_latency"],
            }
        )
        return out

    rs = _load_radar_state()
    consec_sl = int(rs.get("consecutive_sl") or 0)
    if consec_sl >= 3:
        out["level"] = "loss_streak"
        out["stake_mult"] = 0.75
        out["min_score_delta"] = 2
        out["max_tier_cap"] = "aggressive"
        out["reasons"].append("3_consecutive_sl")

    day_pnl_pct = float(rs.get("day_pnl_pct") or 0)
    if day_pnl_pct <= -12:
        out.update(
            {
                "level": "dd_halt",
                "block_new_entries": True,
                "reasons": ["daily_dd_12"],
            }
        )
        return out
    if day_pnl_pct <= -8:
        out["level"] = "half_risk"
        out["stake_mult"] = 0.5
        out["min_score_delta"] = 1
        out["reasons"].append("daily_dd_8")

    try:
        from elite_trader.evrim_expectancy import (
            apply_fee_protection_rules,
            load_expectancy_metrics,
        )

        prot = apply_fee_protection_rules(load_expectancy_metrics(), profile)
        if prot.get("block_entries") and profile.get("evrim_fee_hard_block", False):
            out.update(
                {
                    "level": "fee_emergency",
                    "block_new_entries": True,
                    "stake_mult": float(prot.get("stake_mult") or 0.5),
                    "reasons": ["fees_ge_gross"],
                }
            )
            return out
        if prot.get("block_entries"):
            out["stake_mult"] = min(out["stake_mult"], float(prot.get("stake_mult") or 0.55))
            out["min_score_delta"] = max(out["min_score_delta"], 3)
            out["reasons"].append("fee_penalty_not_halt")
        if prot.get("protection_mode") == "slow":
            out["stake_mult"] = min(out["stake_mult"], float(prot.get("stake_mult") or 0.7))
            out["reasons"].append("fee_slow_mode")
    except Exception:
        pass

    vo = ctx.get("vo") or {}
    slip = float(vo.get("slippage_est_bps") or 0)
    slip_max = float(profile.get("evrim_vo_slippage_stake_bps") or 25)
    if slip >= slip_max * 1.4:
        out["market_order_scale"] = 0.6
        out["reasons"].append("slippage_high")

    return out


def record_trade_outcome_radar(
    *,
    exit_reason: str,
    net_pnl: float,
    stake_usd: float = 140.0,
) -> None:
    """SL streak ve günlük drawdown güncelle."""
    rs = _load_radar_state()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if rs.get("day_utc") != day:
        rs = {"day_utc": day, "day_pnl_usd": 0.0, "consecutive_sl": 0}
    rs["day_pnl_usd"] = round(float(rs.get("day_pnl_usd") or 0) + float(net_pnl), 2)
    base = float(rs.get("day_equity_base") or stake_usd * 10)
    rs["day_pnl_pct"] = round(rs["day_pnl_usd"] / max(base, 1) * 100, 2)
    if str(exit_reason).startswith("SL"):
        rs["consecutive_sl"] = int(rs.get("consecutive_sl") or 0) + 1
    else:
        rs["consecutive_sl"] = 0
    _save_radar_state(rs)


def _feeds_from_ctx(symbol: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Backtest / proxy — API çağrısı yok."""
    vol_ratio = float(ctx.get("vol_ratio") or 1.0)
    spread = float(ctx.get("spread_pct") or 0.05)
    lc = ctx.get("last_candle") or {}
    wick = 0.0
    if lc:
        h, l, o, c = float(lc["h"]), float(lc["l"]), float(lc["o"]), float(lc["c"])
        rng = max(h - l, 1e-12)
        wick = max(0.0, (rng - abs(c - o)) / rng)
    liq = vol_ratio >= 2.5 and (wick >= 0.55 or float(ctx.get("funding_abs") or 0) >= 0.001)
    vo = ctx.get("vo") or {}
    stored = _load_stored_headlines()
    return {
        "binance_ticker": {"status": "proxy", "change_pct": 0},
        "funding_rates": {"status": "proxy", "rate": float(ctx.get("funding_abs") or 0)},
        "open_interest": {"status": "proxy", "oi": 0},
        "liquidation_proxy": {
            "status": "ok",
            "detected": liq or bool(ctx.get("liquidation_proxy")),
            "vol_ratio": vol_ratio,
            "wick_ratio": round(wick, 3),
        },
        "volume_spike": {"status": "ok", "rel_vol": vol_ratio, "spike": vol_ratio >= 1.8},
        "whale_alerts": {"status": "proxy", "detected": vol_ratio >= 2.8},
        "btc_dominance": {"status": "proxy", "pct": 52.0},
        "crypto_news": stored.get("crypto_news") or {"status": "placeholder"},
        "etf_regulation": stored.get("etf_regulation") or {"status": "placeholder"},
        "macro_calendar": stored.get("macro_calendar") or {"status": "placeholder"},
        "exchange_announcements": stored.get("exchange_announcements") or {"status": "placeholder"},
        "listing_delisting": stored.get("listing_delisting") or {"status": "placeholder"},
        "api_latency_ms": float(ctx.get("api_latency_ms") or 50),
        "spread_pct": spread,
        "vo_slippage_bps": float(vo.get("slippage_est_bps") or 0),
    }


def scan_market_radar(
    symbol: str,
    side: str,
    ctx: dict[str, Any],
    profile: dict[str, Any] | None = None,
    *,
    client: Any = None,
) -> RadarResult:
    """Tam radar taraması — hybrid öncesi."""
    prof = profile or {}
    if not prof.get("evrim_market_radar_enabled", True):
        return RadarResult(ok=True)

    if not ctx.get("ok"):
        return RadarResult(ok=False, veto=True, veto_reason="market_data")

    if ctx.get("radar_bt_proxy"):
        feeds = _feeds_from_ctx(symbol, ctx)
    else:
        try:
            if client is None:
                from elite_trader.evrim_opportunity import _get_client

                client = _get_client()
        except Exception as exc:
            return RadarResult(ok=False, veto=True, veto_reason=f"client_{exc}"[:40])
        feeds = _fetch_feeds(client, symbol, ctx)

    regime_id = str(ctx.get("market_regime") or ctx.get("regime") or "chop")
    vo = dict(ctx.get("vo") or {})
    if not vo.get("slippage_est_bps") and feeds.get("vo_slippage_bps"):
        vo["slippage_est_bps"] = feeds["vo_slippage_bps"]
        ctx["vo"] = vo

    sentiment, headline, long_d, short_d = classify_news(feeds, ctx, side)
    spread = float(feeds.get("spread_pct") or 0)
    spread_wait = float(prof.get("evrim_radar_news_spread_wait_pct") or 0.14)

    opp, tags, opp_boost = detect_opportunity(feeds, ctx, vo, regime_id)
    emerg = evaluate_emergency(prof, ctx, feeds)

    stake_mult = float(emerg.get("stake_mult") or 1.0)
    min_score_delta = int(emerg.get("min_score_delta") or 0)
    max_tier = emerg.get("max_tier_cap")
    block = bool(emerg.get("block_new_entries"))
    reduce_risk = False
    notes: list[str] = list(emerg.get("reasons") or [])
    veto = block
    veto_reason = emerg.get("level") or ""

    long_adj = long_d
    short_adj = short_d
    if sentiment == "bullish":
        long_adj += 3
        if spread >= spread_wait:
            notes.append("bull_news_wait_spread")
            if side == "LONG" and not prof.get("evrim_radar_hard_veto_only_extreme", True):
                veto = True
                veto_reason = "bull_spread_wait"
            elif side == "LONG":
                long_adj -= 8
                notes.append("bull_spread_penalty")
        else:
            notes.append("bull_news")
    elif sentiment == "bearish":
        short_adj += 3
        atr = float(ctx.get("atr_pct") or 0)
        atr_min = float(prof.get("evrim_atr_min_pct") or 0.055)
        if atr >= atr_min * 2:
            stake_mult *= 0.85
            notes.append("bear_high_vol_stake_cut")
        if spread >= spread_wait and side == "SHORT":
            if not prof.get("evrim_radar_hard_veto_only_extreme", True):
                veto = True
                veto_reason = "bear_spread_wait"
            else:
                short_adj -= 8
                notes.append("bear_spread_penalty")
        else:
            notes.append("bear_news")
    elif sentiment == "uncertain":
        if prof.get("evrim_radar_hard_veto_only_extreme", True):
            long_adj -= 8
            short_adj -= 8
            notes.append("uncertain_news_penalty")
        else:
            veto = True
            veto_reason = "uncertain_news"
            reduce_risk = True
            notes.append("uncertain_news_no_entry")

    if opp:
        stake_mult *= opp_boost
        if side == "LONG":
            long_adj += 2
        else:
            short_adj += 2
        notes.extend(tags)

    try:
        from elite_trader.evrim_risk_policy import apply_radar_penalties

        pre = RadarResult(
            ok=True,
            feeds=feeds,
            news_sentiment=sentiment,
            news_headline=headline,
            opportunity_mode=opp,
            opportunity_tags=tags,
            emergency_level=str(emerg.get("level") or "normal"),
            block_new_entries=block,
            reduce_open_risk=reduce_risk,
            stake_mult=stake_mult,
            long_score_delta=long_adj,
            short_score_delta=short_adj,
            min_score_delta=min_score_delta,
            max_tier_cap=max_tier,
            market_order_scale=float(emerg.get("market_order_scale") or 1.0),
            notes=notes,
            veto=veto,
            veto_reason=veto_reason,
        )
        assess = None
        try:
            from elite_trader.evrim_risk_policy import assess_spread_risk

            assess = assess_spread_risk(symbol, spread, ctx, prof)
        except Exception:
            pass
        return apply_radar_penalties(pre, prof, spread_assess=assess)
    except Exception:
        pass

    return RadarResult(
        ok=True,
        feeds=feeds,
        news_sentiment=sentiment,
        news_headline=headline,
        opportunity_mode=opp,
        opportunity_tags=tags,
        emergency_level=str(emerg.get("level") or "normal"),
        block_new_entries=block,
        reduce_open_risk=reduce_risk,
        stake_mult=stake_mult,
        long_score_delta=long_adj,
        short_score_delta=short_adj,
        min_score_delta=min_score_delta,
        max_tier_cap=max_tier,
        market_order_scale=float(emerg.get("market_order_scale") or 1.0),
        notes=notes,
        veto=veto,
        veto_reason=veto_reason,
    )


def apply_radar_to_context(ctx: dict[str, Any], radar: RadarResult) -> None:
    ctx["market_radar"] = radar.to_dict()
    ctx["news_sentiment"] = radar.news_sentiment


def apply_radar_score_deltas(
    side: str,
    components: dict[str, float],
    radar: RadarResult,
) -> dict[str, float]:
    delta = radar.long_score_delta if side == "LONG" else radar.short_score_delta
    if delta:
        components["news_whale_risk"] = _clamp(
            components.get("news_whale_risk", 0) + delta * 0.4,
            0,
            10,
        )
        components["volume_delta"] = _clamp(
            components.get("volume_delta", 0) + delta * 0.25,
            0,
            20,
        )
    return components
