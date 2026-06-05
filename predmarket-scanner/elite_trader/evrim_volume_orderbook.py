"""
Evrim — volume + orderbook mikro yapı analizi.

Yalnızca hybrid skor katkısı; tek başına işlem açmaz.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DEPTH_PREV: dict[str, dict[str, float]] = {}
_CACHE_TTL = 45.0
_client: Any = None

DEFAULT_VO_WEIGHTS: dict[str, float] = {
    "volume_spike": 1.0,
    "relative_volume": 1.0,
    "buy_sell_imbalance": 1.0,
    "bid_wall": 1.0,
    "ask_wall": 1.0,
    "liquidity_pull": 1.0,
    "orderbook_sweep": 1.0,
    "large_order_in": 1.0,
    "large_order_cancel": 1.0,
    "aggressive_market_buy": 1.0,
    "aggressive_market_sell": 1.0,
}


@dataclass
class VoAnalysis:
    signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    rel_volume: float = 1.0
    imbalance: float = 0.0
    long_pressure: float = 0.0
    short_pressure: float = 0.0
    slippage_est_bps: float = 0.0
    spread_pct: float = 0.0
    veto: bool = False
    stake_mult: float = 1.0
    max_tier_floor: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_context_dict(self) -> dict[str, Any]:
        detected = [k for k, v in self.signals.items() if v.get("detected")]
        return {
            "signals": self.signals,
            "detected": detected,
            "rel_volume": round(self.rel_volume, 3),
            "imbalance": round(self.imbalance, 3),
            "long_pressure": round(self.long_pressure, 2),
            "short_pressure": round(self.short_pressure, 2),
            "slippage_est_bps": round(self.slippage_est_bps, 1),
            "spread_pct": round(self.spread_pct, 5),
            "veto": self.veto,
            "stake_mult": self.stake_mult,
            "max_tier_floor": self.max_tier_floor,
            "notes": self.notes[:12],
        }


@dataclass
class VoAdjust:
    component_deltas: dict[str, float] = field(default_factory=dict)
    stake_mult: float = 1.0
    max_tier_cap: str | None = None
    veto: bool = False
    notes: list[str] = field(default_factory=list)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _coin(symbol: str) -> str:
    s = str(symbol or "").upper()
    return s.replace("USDT", "") if s.endswith("USDT") else s


def _get_client() -> Any:
    global _client
    if _client is None:
        from binance_futures_trader.client import BinanceFuturesClient

        _client = BinanceFuturesClient()
    return _client


def _depth_notional(levels: list, mid: float, n: int = 10) -> tuple[float, float]:
    bid_n = ask_n = 0.0
    for row in (levels or [])[:n]:
        try:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                px, qty = float(row[0]), float(row[1])
                bid_n += px * qty
        except Exception:
            pass
    return bid_n, ask_n


def _parse_agg_flow(raw: list, mark: float) -> dict[str, Any]:
    buy_usd = sell_usd = 0.0
    large_n = 0
    thresh = max(mark * 0.02, 50.0)
    for t in raw[-200:]:
        try:
            px = float(t.get("p") or 0)
            qty = float(t.get("q") or 0)
            usd = px * qty
            if usd < thresh:
                continue
            large_n += 1
            if t.get("m"):
                sell_usd += usd
            else:
                buy_usd += usd
        except Exception:
            pass
    total = buy_usd + sell_usd
    imb = (buy_usd - sell_usd) / total if total > 0 else 0.0
    return {
        "buy_usd": buy_usd,
        "sell_usd": sell_usd,
        "total_usd": total,
        "imbalance": imb,
        "large_n": large_n,
    }


def fetch_market_microstructure(
    symbol: str,
    profile: dict[str, Any] | None = None,
    *,
    spread_pct: float | None = None,
    price: float | None = None,
    skip_api: bool = False,
) -> dict[str, Any]:
    """Depth + aggTrades; backtest proxy modunda API atlanir."""
    coin = _coin(symbol)
    sym = f"{coin}USDT"
    prof = profile or {}
    mark = float(price or 1.0)
    out: dict[str, Any] = {
        "symbol": sym,
        "spread_pct": float(spread_pct or 0.05),
        "bid_notional": 0.0,
        "ask_notional": 0.0,
        "total_depth": 0.0,
        "imbalance": 0.0,
        "buy_usd": 0.0,
        "sell_usd": 0.0,
        "flow_total_usd": 0.0,
        "liquidity_pull": False,
        "bid_wall": False,
        "ask_wall": False,
        "large_bid_add": False,
        "large_ask_add": False,
        "level_vanish": False,
        "slippage_est_bps": 0.0,
        "whale_news": {"available": False, "score": 0, "note": "placeholder"},
    }

    if skip_api:
        d3 = str(prof.get("_proxy_direction_3") or "")
        if d3 == "up":
            out["imbalance"] = 0.2
        elif d3 == "down":
            out["imbalance"] = -0.2
        sp = float(spread_pct or 0.05)
        out["slippage_est_bps"] = sp * 100 * 0.5
        return out

    cache_key = f"vo:{coin}"
    now = time.time()
    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL:
        cached = dict(hit[1])
        if spread_pct is not None:
            cached["spread_pct"] = spread_pct
        return cached

    try:
        c = _get_client()
        depth = c._get("/fapi/v1/depth", {"symbol": sym, "limit": 20}) or {}
        bids = depth.get("bids") or []
        asks = depth.get("asks") or []
        bid_n = sum(float(b[0]) * float(b[1]) for b in bids[:10] if len(b) >= 2)
        ask_n = sum(float(a[0]) * float(a[1]) for a in asks[:10] if len(a) >= 2)
        out["bid_notional"] = bid_n
        out["ask_notional"] = ask_n
        total_d = bid_n + ask_n
        out["total_depth"] = total_d
        if total_d > 0:
            out["imbalance"] = (bid_n - ask_n) / total_d

        prev = _DEPTH_PREV.get(coin)
        if prev and prev.get("total", 0) > 0:
            drop = (prev["total"] - total_d) / prev["total"]
            if drop >= 0.20:
                out["liquidity_pull"] = True
            if prev.get("bid", 0) > 0 and bid_n < prev["bid"] * 0.5:
                out["level_vanish"] = True
            if bid_n > prev.get("bid", 0) * 1.8:
                out["large_bid_add"] = True
            if ask_n > prev.get("ask", 0) * 1.8:
                out["large_ask_add"] = True
        _DEPTH_PREV[coin] = {"bid": bid_n, "ask": ask_n, "total": total_d}

        if bid_n > ask_n * 2.0 and bid_n > 5000:
            out["bid_wall"] = True
        if ask_n > bid_n * 2.0 and ask_n > 5000:
            out["ask_wall"] = True

        raw = c._get("/fapi/v1/aggTrades", {"symbol": sym, "limit": 300}) or []
        if isinstance(raw, list) and raw:
            flow = _parse_agg_flow(raw, mark)
            out.update(flow)
            out["flow_total_usd"] = flow["total_usd"]
            if flow["total_usd"] > 3000:
                out["imbalance"] = flow["imbalance"]

        sp = float(spread_pct if spread_pct is not None else out["spread_pct"])
        out["spread_pct"] = sp
        out["slippage_est_bps"] = sp * 100 * 0.6 + abs(out["imbalance"]) * 8
    except Exception as exc:
        out["error"] = str(exc)[:80]

    _CACHE[cache_key] = (now, out)
    return out


def _load_vo_weights(profile: dict[str, Any] | None) -> dict[str, float]:
    weights = dict(DEFAULT_VO_WEIGHTS)
    try:
        from elite_trader.evrim_training import load_training_state

        for k, v in (load_training_state().get("vo_weights") or {}).items():
            weights[k] = float(v)
    except Exception:
        pass
    return weights


def analyze_volume_orderbook(
    ctx: dict[str, Any],
    side: str,
    profile: dict[str, Any] | None = None,
) -> VoAnalysis:
    side = str(side or "LONG").upper()
    prof = profile or {}
    notes: list[str] = []
    rel_vol = float(ctx.get("vol_ratio") or 1.0)
    spread = float(ctx.get("spread_pct") or 0.05)
    vo_snap = ctx.get("vo_snapshot") or {}
    if not vo_snap and not ctx.get("vo_backtest_proxy"):
        try:
            vo_snap = fetch_market_microstructure(
                str(ctx.get("symbol") or ""),
                prof,
                spread_pct=spread,
                price=float(ctx.get("price") or 1),
            )
            ctx["vo_snapshot"] = vo_snap
        except Exception:
            vo_snap = {}
    elif ctx.get("vo_backtest_proxy") and not vo_snap:
        vo_snap = fetch_market_microstructure(
            str(ctx.get("symbol") or "BTCUSDT"),
            {**prof, "_proxy_direction_3": ctx.get("direction_3")},
            spread_pct=spread,
            price=float(ctx.get("price") or 1),
            skip_api=True,
        )
        ctx["vo_snapshot"] = vo_snap

    imb = float(vo_snap.get("imbalance") or 0)
    signals: dict[str, dict[str, Any]] = {}

    signals["relative_volume"] = {
        "detected": rel_vol >= 1.0,
        "score": _clamp(rel_vol * 5, 0, 10),
        "value": rel_vol,
    }
    signals["volume_spike"] = {
        "detected": rel_vol >= 1.5,
        "score": 8.0 if rel_vol >= 1.5 else 0.0,
    }
    signals["buy_sell_imbalance"] = {
        "detected": abs(imb) >= 0.12,
        "score": _clamp(abs(imb) * 20, 0, 10),
        "imbalance": imb,
    }
    signals["bid_wall"] = {"detected": bool(vo_snap.get("bid_wall")), "score": 7.0}
    signals["ask_wall"] = {"detected": bool(vo_snap.get("ask_wall")), "score": 7.0}
    signals["liquidity_pull"] = {
        "detected": bool(vo_snap.get("liquidity_pull")),
        "score": 6.0,
    }
    sweep = abs(imb) >= 0.2 and rel_vol >= 1.2
    signals["orderbook_sweep"] = {"detected": sweep, "score": 7.5 if sweep else 0.0}
    signals["large_order_in"] = {
        "detected": bool(vo_snap.get("large_bid_add") or vo_snap.get("large_ask_add")),
        "score": 6.5,
    }
    signals["large_order_cancel"] = {
        "detected": bool(vo_snap.get("level_vanish")),
        "score": 5.0,
    }
    agg_buy = imb > 0.15 and float(vo_snap.get("buy_usd") or 0) > float(
        vo_snap.get("sell_usd") or 0
    )
    agg_sell = imb < -0.15 and float(vo_snap.get("sell_usd") or 0) > float(
        vo_snap.get("buy_usd") or 0
    )
    signals["aggressive_market_buy"] = {
        "detected": agg_buy,
        "score": 8.0 if agg_buy else 0.0,
    }
    signals["aggressive_market_sell"] = {
        "detected": agg_sell,
        "score": 8.0 if agg_sell else 0.0,
    }
    signals["whale_news_placeholder"] = {
        "detected": False,
        "score": 0.0,
        "available": False,
    }

    long_p = short_p = 0.0
    if imb > 0:
        long_p += abs(imb) * 50
    else:
        short_p += abs(imb) * 50
    if signals["bid_wall"]["detected"]:
        long_p += 15
    if signals["ask_wall"]["detected"]:
        short_p += 15
    if signals["aggressive_market_buy"]["detected"]:
        long_p += 20
    if signals["aggressive_market_sell"]["detected"]:
        short_p += 20

    spread_veto_pct = float(prof.get("evrim_vo_spread_veto_pct") or 0.12)
    slippage_bps_thresh = float(prof.get("evrim_vo_slippage_stake_bps") or 25)
    slippage_mult = float(prof.get("evrim_vo_slippage_stake_mult") or 0.70)
    rel_boost = float(prof.get("evrim_vo_rel_vol_boost") or 1.2)
    rel_aggressive = float(prof.get("evrim_vo_aggressive_rel_vol") or 1.8)

    veto = False
    stake_mult = 1.0
    max_tier_floor = None
    slip_bps = float(vo_snap.get("slippage_est_bps") or spread * 100 * 0.5)
    sym = str(ctx.get("symbol") or "")

    try:
        from elite_trader.evrim_risk_policy import assess_spread_risk

        assess = assess_spread_risk(sym, spread, ctx, prof)
        if assess.get("hard_veto"):
            veto = True
            notes.append(f"spread_hard_{spread:.4f}")
        elif assess.get("reason") == "spread_soft_penalty":
            stake_mult = min(stake_mult, float(assess.get("stake_mult") or 0.55))
            notes.append(f"spread_soft_{spread:.4f}")
            ctx["evrim_prefer_limit"] = bool(assess.get("prefer_limit"))
            ctx["evrim_spread_tp_mult"] = float(assess.get("tp_mult") or 1.0)
        elif spread > spread_veto_pct:
            stake_mult = min(stake_mult, 0.6)
            notes.append(f"spread_penalty_{spread:.4f}")
    except Exception:
        if spread > spread_veto_pct:
            stake_mult = min(stake_mult, 0.6)
            notes.append(f"spread_penalty_{spread:.4f}")

    if slip_bps > slippage_bps_thresh and not veto:
        stake_mult = slippage_mult
        notes.append(f"slippage_stake_{slip_bps:.0f}bps")

    if rel_vol >= rel_aggressive:
        max_tier_floor = "aggressive"
        notes.append(f"rel_vol_aggressive_{rel_vol:.2f}")
    elif rel_vol >= rel_boost:
        notes.append(f"rel_vol_boost_{rel_vol:.2f}")

    for name, s in signals.items():
        if s.get("detected"):
            notes.append(name)

    return VoAnalysis(
        signals=signals,
        rel_volume=rel_vol,
        imbalance=imb,
        long_pressure=long_p,
        short_pressure=short_p,
        slippage_est_bps=slip_bps,
        spread_pct=spread,
        veto=veto,
        stake_mult=stake_mult,
        max_tier_floor=max_tier_floor,
        notes=notes,
    )


def score_volume_component(
    ctx: dict[str, Any],
    profile: dict[str, Any],
    vo: VoAnalysis | None = None,
    *,
    max_points: float = 20.0,
) -> float:
    if not profile.get("evrim_vo_enabled", True):
        vol_ratio = float(ctx.get("vol_ratio") or 0)
        target = float(profile.get("evrim_vol_mult") or 1.8)
        if vol_ratio >= target * 1.4:
            return 20.0
        if vol_ratio >= target:
            return 16.0
        if vol_ratio >= target * 0.85:
            return 10.0
        if vol_ratio >= 1.2:
            return 6.0
        return _clamp((vol_ratio / max(target, 0.5)) * 12, 0, max_points)

    vo = vo or analyze_volume_orderbook(ctx, "LONG", profile)
    base = _clamp(vo.rel_volume / 2.0 * 10, 0, 14)
    rel_boost = float(profile.get("evrim_vo_rel_vol_boost") or 1.2)
    if vo.rel_volume >= rel_boost:
        base += 4.0
    rel_agg = float(profile.get("evrim_vo_aggressive_rel_vol") or 1.8)
    if vo.rel_volume >= rel_agg:
        base += 3.0
    if vo.signals.get("volume_spike", {}).get("detected"):
        base += 2.0
    return _clamp(base, 0, max_points)


def score_orderbook_component(
    ctx: dict[str, Any],
    side: str,
    profile: dict[str, Any],
    vo: VoAnalysis | None = None,
    *,
    max_points: float = 10.0,
) -> float:
    if not profile.get("evrim_vo_enabled", True):
        spread = float(ctx.get("spread_pct") or 0.05)
        spread_frac = float(profile.get("evrim_spread_tp_frac") or 0.18)
        if spread <= spread_frac * 0.5:
            return 10.0
        if spread <= spread_frac:
            return 7.0
        if spread <= spread_frac * 1.5:
            return 4.0
        return 1.0

    vo = vo or analyze_volume_orderbook(ctx, side, profile)
    base = 4.0
    spread_frac = float(profile.get("evrim_spread_tp_frac") or 0.18)
    if vo.spread_pct <= spread_frac * 0.5:
        base += 3.0
    elif vo.spread_pct <= spread_frac:
        base += 1.5

    if side == "LONG" and vo.long_pressure > vo.short_pressure + 5:
        base += _clamp(vo.long_pressure / 10, 0, 4)
    elif side == "SHORT" and vo.short_pressure > vo.long_pressure + 5:
        base += _clamp(vo.short_pressure / 10, 0, 4)

    if vo.signals.get("bid_wall", {}).get("detected") and side == "LONG":
        base += 1.5
    if vo.signals.get("ask_wall", {}).get("detected") and side == "SHORT":
        base += 1.5

    return _clamp(base, 0, max_points)


def apply_vo_adjustments(
    side: str,
    components: dict[str, float],
    vo: VoAnalysis,
    profile: dict[str, Any],
) -> VoAdjust:
    weights = _load_vo_weights(profile)
    adj = VoAdjust(stake_mult=vo.stake_mult, veto=vo.veto)
    rel_boost = float(profile.get("evrim_vo_rel_vol_boost") or 1.2)
    rel_agg = float(profile.get("evrim_vo_aggressive_rel_vol") or 1.8)

    if vo.rel_volume >= rel_boost:
        adj.component_deltas["volume_delta"] = adj.component_deltas.get(
            "volume_delta", 0
        ) + 3.0 * weights.get("relative_volume", 1.0)
        adj.notes.append("vo_vol_boost")
    if vo.rel_volume >= rel_agg:
        adj.max_tier_cap = "aggressive"
        adj.notes.append("vo_aggressive_vol")

    if side == "LONG" and vo.imbalance > 0.15:
        adj.component_deltas["orderbook_liquidity"] = adj.component_deltas.get(
            "orderbook_liquidity", 0
        ) + 3.5 * weights.get("buy_sell_imbalance", 1.0)
        adj.notes.append("vo_ob_long")
    elif side == "SHORT" and vo.imbalance < -0.15:
        adj.component_deltas["orderbook_liquidity"] = adj.component_deltas.get(
            "orderbook_liquidity", 0
        ) + 3.5 * weights.get("buy_sell_imbalance", 1.0)
        adj.notes.append("vo_ob_short")
    elif side == "LONG" and vo.long_pressure > vo.short_pressure + 8:
        adj.component_deltas["orderbook_liquidity"] = adj.component_deltas.get(
            "orderbook_liquidity", 0
        ) + 2.0
    elif side == "SHORT" and vo.short_pressure > vo.long_pressure + 8:
        adj.component_deltas["orderbook_liquidity"] = adj.component_deltas.get(
            "orderbook_liquidity", 0
        ) + 2.0

    if vo.signals.get("orderbook_sweep", {}).get("detected"):
        adj.component_deltas["orderbook_liquidity"] = adj.component_deltas.get(
            "orderbook_liquidity", 0
        ) + 1.5 * weights.get("orderbook_sweep", 1.0)

    caps = {
        "volume_delta": 20,
        "orderbook_liquidity": 10,
    }
    for k, delta in list(adj.component_deltas.items()):
        base = components.get(k, 0)
        adj.component_deltas[k] = round(
            _clamp(base + delta, 0, caps.get(k, 20)) - base, 2
        )

    if vo.max_tier_floor and not adj.max_tier_cap:
        adj.max_tier_cap = vo.max_tier_floor

    return adj


def merge_vo_into_components(
    components: dict[str, float],
    adj: VoAdjust,
) -> dict[str, float]:
    out = dict(components)
    for k, delta in adj.component_deltas.items():
        out[k] = round(_clamp(out.get(k, 0) + delta, 0, 100), 2)
    total = sum(out.values())
    if total > 100:
        scale = 100 / total
        out = {k: round(v * scale, 2) for k, v in out.items()}
    return out


def apply_vo_to_context(ctx: dict[str, Any], vo: VoAnalysis | None) -> None:
    if vo:
        ctx["vo"] = vo.to_context_dict()
