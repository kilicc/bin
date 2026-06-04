"""Ana Hat — açık pozisyon ve TP/SL kararları Binance positionRisk verisi."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

from elite_trader.exchange_settlement import exchange_truth_enabled
from elite_trader.panel_strategy import (
    active_execution_mode,
    evaluate_position_exit,
    mode_catalog,
    stake_targets,
)


def is_live_binance_execution() -> bool:
    """Demo canlı emir + borsa çıkışı — seçili motor (Ana Hat veya paralel)."""
    if not exchange_truth_enabled():
        return False
    try:
        from binance_elite_pro import LIVE_ORDERS, client
    except Exception:
        return False
    return LIVE_ORDERS and not client.paper


def live_tp_sl_usd(
    stake_usd: float,
    leverage: int = 5,
    mode_id: str | None = None,
) -> tuple[float, float]:
    """Seçili motor — net kâr hedefi + brüt çıkış eşiği (fee dahil)."""
    from elite_trader.fee_economics import tp_sl_gross_triggers, use_net_exit_targets

    mid = mode_id or active_execution_mode()
    s = max(float(stake_usd), 1.0)
    lev = max(int(leverage), 1)
    if use_net_exit_targets():
        tp_g, sl_g, _, _ = tp_sl_gross_triggers(s, lev, mid)
        return tp_g, sl_g
    m = mode_catalog().get(mid) or mode_catalog().get(active_execution_mode()) or {}
    return (
        s * float(m.get("tp_stake_pct", 0.01)) * float(m.get("tp_trigger_frac", 0.98)),
        s * float(m.get("sl_stake_pct", 0.015)),
    )


def _update_max_net_seen(pos: dict[str, Any], gross_unreal: float) -> None:
    """Tepe net (SPIKE/TP kilidi) — exchange_only sync'te de güncellenir."""
    if gross_unreal <= 0:
        return
    stake = max(float(pos.get("stake_usd") or 1), 0.01)
    lev = max(int(pos.get("leverage") or 2), 1)
    try:
        from elite_trader.fee_economics import estimate_close_pnl

        est = estimate_close_pnl(
            float(gross_unreal),
            stake,
            lev,
            entry_fee=float(pos.get("entry_fee") or 0) or None,
            pos=pos,
        )
        net = float(est.get("final_pnl") or gross_unreal)
    except Exception:
        net = float(gross_unreal)
    pos["max_net_seen"] = max(float(pos.get("max_net_seen") or 0), net)


def _exchange_display_from_ep(ep: dict[str, Any]) -> dict[str, str]:
    """Panel — API ham stringleri (virgül kayması yok)."""
    raw = ep.get("exchange_raw") or {}
    amt = str(raw.get("positionAmt") or ep.get("contracts") or "")
    if amt and not amt.startswith("-"):
        try:
            if float(amt) < 0:
                amt = str(abs(float(amt)))
        except ValueError:
            pass

    def _s(key: str, fallback_key: str | None = None) -> str:
        v = raw.get(key)
        if v is not None and str(v) != "":
            return str(v)
        if fallback_key and ep.get(fallback_key) is not None:
            return str(ep[fallback_key])
        return ""

    unreal_s = _s("unRealizedProfit", "unrealized_pnl")
    margin_s = _s("isolatedMargin") or _s("positionInitialMargin")
    pct_s = _s("percentage")
    try:
        u = float(unreal_s) if unreal_s else 0.0
        m = float(margin_s) if margin_s else 0.0
        if m > 0:
            implied_pct = (u / m) * 100.0
            if not pct_s.strip():
                pct_s = f"{implied_pct:.8f}".rstrip("0").rstrip(".")
            else:
                api_pct = float(pct_s)
                # Demo API bazen ROE% ≠ uPnL/marjin — panel ROI$ uPnL ile hizalansın.
                if abs(api_pct - implied_pct) > max(2.0, abs(implied_pct) * 0.08):
                    pct_s = f"{implied_pct:.8f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        pass

    return {
        "entryPrice": _s("entryPrice", "entry_price"),
        "markPrice": _s("markPrice", "mark_price"),
        "unRealizedProfit": unreal_s,
        "percentage": pct_s,
        "notional": _s("notional", "notional_usd"),
        "positionAmt": amt or _s("positionAmt"),
        "breakEvenPrice": _s("breakEvenPrice", "break_even_price"),
        "isolatedMargin": _s("isolatedMargin"),
        "positionInitialMargin": _s("positionInitialMargin"),
        "marginType": _s("marginType", "margin_type"),
        "leverage": _s("leverage", "leverage"),
        "updateTime": _s("updateTime"),
    }


def apply_exchange_snapshot(
    pos: dict[str, Any],
    ep: dict[str, Any],
    mode_id: str | None = None,
) -> None:
    """Borsa satırından giriş, mark, unrealized, stake — TP/SL USD yeniden."""
    keep_oid = str(pos.get("exchange_order_id") or "").strip()
    keep_fee = float(pos.get("entry_fee") or 0)
    keep_fee_src = pos.get("fee_source")
    entry = float(ep.get("entry_price") or 0)
    mark = float(ep.get("mark_price") or entry)
    size = float(ep.get("contracts") or 0)
    lev = max(int(ep.get("leverage") or 1), 1)
    notional = abs(float(ep.get("notional_usd") or 0))
    if notional <= 0 and size > 0 and mark > 0:
        notional = size * mark

    margin_used = float(ep.get("margin_used") or 0)
    stake = margin_used if margin_used > 0 else (
        notional / lev if notional > 0 else float(pos.get("stake_usd") or 1)
    )
    unreal = float(ep.get("unrealized_pnl") or 0)

    pos["entry_price"] = entry
    pos["current_price"] = mark
    pos["size"] = size
    pos["leverage"] = lev
    pos["stake_usd"] = stake
    pos["margin_used"] = margin_used
    pos["position_value"] = notional
    pos["unrealized_pnl"] = unreal
    pos["exchange_unrealized_pnl"] = unreal
    pos["max_exchange_unreal_seen"] = max(
        float(pos.get("max_exchange_unreal_seen") or unreal), unreal
    )
    pos["max_unreal_seen"] = pos["max_exchange_unreal_seen"]
    pos["min_unreal_seen"] = min(float(pos.get("min_unreal_seen", unreal)), unreal)
    _update_max_net_seen(pos, unreal)
    _update_max_net_seen(pos, float(pos.get("max_unreal_seen") or unreal))
    pos["pnl_pct"] = (unreal / margin_used * 100) if margin_used > 0 else 0.0
    pos["break_even_price"] = float(ep.get("break_even_price") or 0)
    pos["exchange_display"] = _exchange_display_from_ep(ep)
    pos["exchange_raw"] = ep.get("exchange_raw") or {}
    pos["exchange_update_ms"] = int(ep.get("exchange_update_ms") or 0)
    pos["exchange_synced"] = True

    mid = mode_id or pos.get("panel_mode") or active_execution_mode()
    tp_usd, sl_usd = live_tp_sl_usd(stake, lev, mid)
    pos["tp_target_usd"] = tp_usd
    pos["sl_target_usd"] = sl_usd
    from elite_trader.fee_economics import net_tp_target_usd, round_trip_fee_usd

    pos["tp_net_target_usd"] = net_tp_target_usd(stake, mid)
    pos["round_trip_fee_est_usd"] = round_trip_fee_usd(stake, lev)
    try:
        from elite_trader.fee_economics import estimate_next_funding_fee_usd

        bn_client = None
        try:
            from binance_elite_pro import client as bn_client
        except Exception:
            pass
        fu_ts = float(pos.get("_funding_est_ts") or 0)
        refresh_fu = (
            pos.get("est_funding_fee_usd") is None
            or (time.time() - fu_ts) >= 90.0
        )
        estimate_next_funding_fee_usd(
            pos, client=bn_client, refresh=refresh_fu
        )
        if refresh_fu:
            pos["_funding_est_ts"] = time.time()
    except Exception:
        pass
    if size > 0:
        if pos.get("side") == "LONG":
            pos["tp_target"] = entry + tp_usd / size
            pos["sl_target"] = entry - sl_usd / size
        else:
            pos["tp_target"] = entry - tp_usd / size
            pos["sl_target"] = entry + sl_usd / size
    if keep_oid:
        pos["exchange_order_id"] = keep_oid
    if keep_fee > 0 and str(keep_fee_src or "") == "binance_api":
        pos["entry_fee"] = keep_fee
        pos["total_fees"] = keep_fee
        pos["fee_source"] = keep_fee_src


def light_sync_exchange_fields(pos: dict[str, Any], ep: dict[str, Any]) -> None:
    """REST positionRisk satırı — mark + uPnL (demo-fapi)."""
    entry = float(ep.get("entry_price") or pos.get("entry_price") or 0)
    mark = float(ep.get("mark_price") or entry)
    size = float(ep.get("contracts") or pos.get("size") or 0)
    lev = max(int(ep.get("leverage") or pos.get("leverage") or 1), 1)
    notional = abs(float(ep.get("notional_usd") or 0))
    if notional <= 0 and size > 0 and mark > 0:
        notional = size * mark
    margin_used = float(ep.get("margin_used") or 0)
    stake = margin_used if margin_used > 0 else (
        notional / lev if notional > 0 else float(pos.get("stake_usd") or 1)
    )
    rest_unreal = float(ep.get("unrealized_pnl") or 0)
    if entry > 0:
        pos["entry_price"] = entry
    if size > 0:
        pos["size"] = size
    pos["leverage"] = lev
    pos["stake_usd"] = stake
    pos["margin_used"] = margin_used
    pos["position_value"] = notional
    pos["unrealized_pnl"] = rest_unreal
    pos["exchange_unrealized_pnl"] = rest_unreal
    pos["exchange_synced"] = True
    pos["exchange_update_ms"] = int(ep.get("exchange_update_ms") or 0)
    if mark > 0:
        pos["current_price"] = mark
    stake_d = max(stake, 0.01)
    pos["pnl_pct"] = round(rest_unreal / stake_d * 100, 4)
    pos["max_exchange_unreal_seen"] = max(
        float(pos.get("max_exchange_unreal_seen") or rest_unreal), rest_unreal
    )
    pos["max_unreal_seen"] = pos["max_exchange_unreal_seen"]
    pos["min_unreal_seen"] = min(float(pos.get("min_unreal_seen", rest_unreal)), rest_unreal)


def exchange_map_by_symbol_side(
    exchange_positions: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for ep in exchange_positions:
        sym = str(ep.get("symbol") or f"{ep.get('coin')}USDT")
        side = str(ep.get("side") or "LONG")
        out[(sym, side)] = ep
    return out


def _apply_local_price_tick(
    pos: dict[str, Any], bulk_prices: dict[str, float], exec_mode: str
) -> tuple[float, float]:
    """Paper / yerel pozisyon — tahmini fiyat (paralel motor kuralları)."""
    sym = pos.get("symbol")
    if sym:
        # bulk_prices "BTC" formatında, sym "BTCUSDT" formatında olabilir
        coin_key = sym.replace("USDT", "")
        raw_price = bulk_prices.get(coin_key) or bulk_prices.get(sym)
        if raw_price and float(raw_price) > 0:
            pos["current_price"] = float(raw_price)
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    side = pos.get("side")
    if size > 0 and entry > 0:
        if side == "LONG":
            pos["unrealized_pnl"] = (pos["current_price"] - entry) * size
        else:
            pos["unrealized_pnl"] = (entry - pos["current_price"]) * size
    stake = float(pos.get("stake_usd") or 1)
    pos["pnl_pct"] = (pos["unrealized_pnl"] / stake * 100) if stake > 0 else 0.0
    tp_tgt, sl_tgt = stake_targets(stake, exec_mode)
    if size > 0:
        if side == "LONG":
            pos["tp_target"] = entry + tp_tgt / size
            pos["sl_target"] = entry - sl_tgt / size
        else:
            pos["tp_target"] = entry - tp_tgt / size
            pos["sl_target"] = entry + sl_tgt / size
    return tp_tgt, sl_tgt


def resolve_exit_api_client(
    exec_mode: str | None = None,
    api_client: Any | None = None,
) -> Any | None:
    """Canlı çıkış API — MEGA port 9006 kendi MEGA_BINANCE_* client'ını kullanır."""
    if api_client is not None and not getattr(api_client, "paper", True):
        return api_client
    mid = str(exec_mode or "").lower()
    if mid == "mega":
        try:
            from elite_trader.mega_live import get_mega_client, mega_live_enabled

            if mega_live_enabled():
                mc = get_mega_client()
                if mc and not getattr(mc, "paper", True):
                    return mc
        except Exception:
            pass
    try:
        from binance_elite_pro import client as c

        if c is not None and not getattr(c, "paper", True):
            return c
    except Exception:
        pass
    return None


def process_position_exit(
    pos: dict[str, Any],
    *,
    exchange_positions: list[dict[str, Any]],
    bulk_prices: dict[str, float],
    exec_mode: str,
    live_orders: bool,
    client_paper: bool,
    api_client: Any | None = None,
) -> str | None:
    """Tek pozisyon: güncelle + kapanış nedeni (varsa)."""
    binance_active = live_orders and not client_paper
    sym, side = str(pos.get("symbol")), str(pos.get("side"))
    key = (sym, side)
    bn_client = resolve_exit_api_client(exec_mode, api_client)

    if pos.get("on_exchange") and binance_active:
        if bn_client is not None:
            from elite_trader.exchange_trade_truth import enrich_open_entry_fee_api

            allow_fee_fetch = str(exec_mode or "").lower() != "mega"
            enrich_open_entry_fee_api(pos, bn_client, allow_fetch=allow_fee_fetch)
        ep = exchange_map_by_symbol_side(exchange_positions).get(key)
        if not ep:
            from elite_trader.panel_strategy import position_age_seconds

            grace = float(os.getenv("ELITE_SYNC_EXCHANGE_GRACE_SEC", "8"))
            opened_at = pos.get("opened_at_iso") or pos.get("entry_time_str")
            age = position_age_seconds({"opened_at_iso": opened_at, "entry_time_str": opened_at})
            if age < grace:
                # Yeni açılış — önbellek gecikmesi SYNC-EXCHANGE tetiklemesin
                return None
            if str(exec_mode or "").lower() == "mega":
                # MEGA — berserk2 positionRisk önbelleği karışmasın
                return None
            # Önbellek gecikmesi — motor positionRisk (tek REST kaynağı)
            try:
                from binance_elite_pro import (
                    _exchange_cache_ts,
                    _exchange_position_absent_confirmed,
                    _exchange_position_row,
                    _positions_cache,
                    _refresh_positions_cache_only,
                )

                if time.time() - float(_exchange_cache_ts or 0) > 1.0:
                    _refresh_positions_cache_only(force=True)
                if exchange_map_by_symbol_side(list(_positions_cache)).get(key):
                    return None
                if _exchange_position_row(sym, side, force_fresh=True):
                    return None
                if _exchange_position_absent_confirmed(sym, side) is not True:
                    return None
            except Exception:
                return None
            return "SYNC-EXCHANGE"
        apply_exchange_snapshot(pos, ep, exec_mode)
        opened_at = pos.get("opened_at_iso") or pos.get("entry_time_str")
        unreal = float(pos.get("unrealized_pnl") or 0)
        unreal_for_exit = unreal
        near_tp = unreal >= float(pos.get("tp_target_usd") or 0) * 0.82
        skip_mega_book = str(exec_mode or "").lower() == "mega" and os.getenv(
            "MEGA_TP_FAST_PATH", "1"
        ).strip().lower() in ("1", "true", "yes")
        try:
            from elite_trader.exchange_fill_truth import fill_gross_unreal

            if near_tp and not skip_mega_book:
                fill_gross = fill_gross_unreal(pos, client=bn_client)
                if fill_gross is not None:
                    pos["fill_gross_unreal"] = fill_gross
                    unreal_for_exit = float(fill_gross)
        except Exception:
            pass
        return evaluate_position_exit(
            opened_at=opened_at,
            unrealized_usd=unreal_for_exit,
            tp_target_usd=float(pos["tp_target_usd"]),
            sl_target_usd=float(pos["sl_target_usd"]),
            stake_usd=float(pos["stake_usd"]),
            min_unreal_seen=float(pos.get("min_unreal_seen", unreal_for_exit)),
            max_unreal_seen=float(pos.get("max_unreal_seen", unreal_for_exit)),
            mode_id=exec_mode,
            leverage=max(int(pos.get("leverage") or 5), 1),
            entry_fee=float(pos.get("entry_fee") or 0) or None,
            pos=pos,
            client=bn_client,
        )

    tp_tgt, sl_tgt = _apply_local_price_tick(pos, bulk_prices, exec_mode)
    # REMOVED: Blocking live position exits - critical bug!
    # Live positions MUST be evaluated for TP/SPIKE exits
    opened_at = pos.get("opened_at_iso") or pos.get("entry_time_str")
    unreal = float(pos.get("unrealized_pnl") or 0)
    return evaluate_position_exit(
        opened_at=opened_at,
        unrealized_usd=unreal,
        tp_target_usd=tp_tgt,
        sl_target_usd=sl_tgt,
        stake_usd=float(pos.get("stake_usd") or 1),
        min_unreal_seen=float(pos.get("min_unreal_seen", unreal)),
        max_unreal_seen=float(pos.get("max_unreal_seen", unreal)),
        mode_id=exec_mode,
        leverage=max(int(pos.get("leverage") or 5), 1),
        pos=pos,
        client=bn_client,
    )


_upnl_cache: dict[tuple[str, str], tuple[float, float]] = {}  # (sym,side) -> (upnl, timestamp)
_upnl_cache_lock = threading.Lock()


def fresh_exchange_upnl(
    symbol: str,
    side: str,
    *,
    client: Any = None,
) -> float | None:
    """positionRisk önbelleği — ekstra REST yok (motor tek kaynak)."""
    del client
    key = (symbol, side)
    now = time.time()
    with _upnl_cache_lock:
        if key in _upnl_cache:
            cached_upnl, cached_ts = _upnl_cache[key]
            if now - cached_ts < 0.8:
                return cached_upnl
    try:
        from binance_elite_pro import _positions_cache

        sym = str(symbol)
        sd = str(side or "LONG")
        for ep in _positions_cache or []:
            es = str(ep.get("symbol") or f"{ep.get('coin')}USDT")
            if es == sym and str(ep.get("side") or "LONG") == sd:
                upnl = float(ep.get("unrealized_pnl") or 0)
                with _upnl_cache_lock:
                    _upnl_cache[key] = (upnl, now)
                return upnl
    except Exception:
        return None
    return None


def pre_close_upnl_verify_ok(
    pos: dict[str, Any],
    exit_reason: str,
    *,
    client: Any = None,
    mode_id: str | None = None,
) -> tuple[bool, str]:
    """
    Kapanış emri öncesi — book bid/ask fill net > min (mark-only TP engeli).
    REST uPnL yalnızca panel senkronu için güncellenir.
    """
    from elite_trader.exchange_fill_truth import pre_close_fill_verify_ok
    from elite_trader.fee_economics import is_profit_tp_exit

    if not is_profit_tp_exit(exit_reason):
        return True, ""

    sym = str(pos.get("symbol") or "")
    side = str(pos.get("side") or "LONG")
    mid = mode_id or str(pos.get("panel_mode") or active_execution_mode())
    skip_rest = (
        str(mid).lower() == "mega"
        and float(pos.get("exchange_unrealized_pnl") or pos.get("unrealized_pnl") or 0) != 0
        and (time.time() - float(pos.get("_gross_sync_ts") or 0)) < 0.2
    )
    if not skip_rest:
        fresh = fresh_exchange_upnl(sym, side, client=client)
        if fresh is not None:
            pos["unrealized_pnl"] = fresh
            pos["exchange_unrealized_pnl"] = fresh
    ok, detail, snap = pre_close_fill_verify_ok(
        pos, exit_reason, client=client, mode_id=mid
    )
    if snap:
        pos["close_signal"] = snap
    return ok, detail
