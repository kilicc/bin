"""Açık pozisyon UI — yalnızca Binance positionRisk + mark + klines."""
from __future__ import annotations

import os
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from elite_trader.exchange_position_sync import (
    apply_exchange_snapshot,
    exchange_map_by_symbol_side,
    live_tp_sl_usd,
)
from elite_trader.panel_strategy import active_execution_mode
from elite_trader.fee_economics import round_trip_fee_usd

_chart_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _chart_ttl_sec() -> float:
    import os

    try:
        return max(15.0, float(os.getenv("MEGA_CHART_CACHE_SEC", "45")))
    except ValueError:
        return 45.0


def _kline_row_to_candle(row: dict[str, Any]) -> dict[str, Any] | None:
    try:
        t_ms = int(row.get("t") or row.get("openTime") or 0)
        o = float(row.get("o") or row.get("open") or 0)
        h = float(row.get("h") or row.get("high") or 0)
        l = float(row.get("l") or row.get("low") or 0)
        c = float(row.get("c") or row.get("close") or 0)
        v = float(row.get("v") or row.get("volume") or 0)
    except (TypeError, ValueError):
        return None
    if t_ms <= 0 or c <= 0:
        return None
    return {
        "time": t_ms // 1000,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
    }


def _load_kline_candles(
    sym: str,
    client: Any,
    *,
    interval: str = "1m",
    limit: int = 90,
    allow_fetch: bool = True,
) -> list[dict[str, Any]]:
    now = time.time()
    cached = _chart_cache.get(sym)
    if cached and (now - cached[0]) < _chart_ttl_sec():
        return list(cached[1])
    if not allow_fetch:
        return list(cached[1]) if cached else []
    coin = sym.replace("USDT", "")
    try:
        rows = client.klines(coin, interval=interval, limit=limit) or []
    except Exception:
        rows = []
    candles: list[dict[str, Any]] = []
    for row in rows:
        cnd = _kline_row_to_candle(row)
        if cnd:
            candles.append(cnd)
    if candles:
        _chart_cache[sym] = (now, candles)
    elif cached:
        return list(cached[1])
    return candles


def _apply_chart_to_pos(
    pos: dict[str, Any],
    candles: list[dict[str, Any]],
    *,
    mark: float,
    entry: float,
) -> None:
    if not candles:
        opened = pos.get("opened_at_iso") or datetime.now(timezone.utc).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()
        if entry > 0 and mark > 0:
            pos["price_history"] = [entry, mark]
            pos["time_history"] = [opened, now_iso]
        elif mark > 0:
            pos["price_history"] = [mark]
            pos["time_history"] = [now_iso]
        pos["chart_candles"] = []
        pos["chart_source"] = "mark"
        return
    out = [dict(c) for c in candles[-120:]]
    if mark > 0 and out:
        out[-1]["close"] = mark
        out[-1]["high"] = max(float(out[-1]["high"]), mark)
        out[-1]["low"] = min(float(out[-1]["low"]), mark)
    pos["chart_candles"] = out
    pos["chart_source"] = "klines"
    pos["price_history"] = [float(c["close"]) for c in out]
    pos["time_history"] = [
        datetime.fromtimestamp(int(c["time"]), tz=timezone.utc).isoformat() for c in out
    ]


def _iso_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def attach_binance_chart(
    pos: dict[str, Any],
    client: Any,
    *,
    interval: str = "1m",
    limit: int = 90,
    allow_fetch: bool = True,
) -> None:
    """Grafik: 1m klines (önbellek) + canlı mark; tick spam kullanılmaz."""
    sym = str(pos.get("symbol") or "")
    if not sym or client.paper:
        return
    mark = float(pos.get("current_price") or 0)
    entry = float(pos.get("entry_price") or 0)
    candles = _load_kline_candles(
        sym, client, interval=interval, limit=limit, allow_fetch=allow_fetch
    )
    _apply_chart_to_pos(pos, candles, mark=mark, entry=entry)


def _minimal_position_from_exchange(
    ep: dict[str, Any],
    *,
    position_id: int,
    local_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    sym = str(ep.get("symbol") or f"{ep.get('coin')}USDT")
    side = str(ep.get("side") or "LONG")
    entry = float(ep.get("entry_price") or 0)
    mark = float(ep.get("mark_price") or entry)
    size = float(ep.get("contracts") or 0)
    lev = max(int(ep.get("leverage") or 5), 1)
    notional = abs(float(ep.get("notional_usd") or 0))
    if notional <= 0 and size > 0 and mark > 0:
        notional = size * mark
    stake = notional / lev if notional > 0 else 0.0
    meta = local_meta or {}
    mid = (
        meta.get("panel_mode")
        or meta.get("execution_mode_at_open")
        or active_execution_mode()
    )
    tp_usd, sl_usd = live_tp_sl_usd(max(stake, 1.0), lev, mid)
    if side == "LONG":
        tp_p = entry + tp_usd / size if size > 0 else entry
        sl_p = entry - sl_usd / size if size > 0 else entry
    else:
        tp_p = entry - tp_usd / size if size > 0 else entry
        sl_p = entry + sl_usd / size if size > 0 else entry

    opened = meta.get("opened_at_iso") or datetime.now(timezone.utc).isoformat()
    entry_fee = meta.get("entry_fee")
    if entry_fee is not None:
        entry_fee = float(entry_fee)
    else:
        entry_fee = None

    pos: dict[str, Any] = {
        "id": int(meta.get("id") or position_id),
        "symbol": sym,
        "side": side,
        "entry_price": entry,
        "current_price": mark,
        "size": size,
        "leverage": lev,
        "stake_usd": round(stake, 4),
        "position_value": round(notional, 4),
        "unrealized_pnl": round(float(ep.get("unrealized_pnl") or 0), 4),
        "pnl_pct": 0.0,
        "entry_time": float(meta.get("entry_time") or time.time()),
        "entry_time_str": meta.get("entry_time_str")
        or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "opened_at_iso": opened,
        "tp_target": tp_p,
        "sl_target": sl_p,
        "tp_target_usd": tp_usd,
        "sl_target_usd": sl_usd,
        "price_history": [mark],
        "time_history": [datetime.now(timezone.utc).isoformat()],
        "entry_fee": entry_fee,
        "total_fees": entry_fee,
        "fee_source": meta.get("fee_source"),
        "edge": float(meta.get("edge") or 0),
        "formula_score": float(meta.get("formula_score") or 0),
        "signal_source": meta.get("signal_source") or "Binance",
        "signal_strength": meta.get("signal_strength") or "—",
        "on_exchange": True,
        "exchange_synced": True,
        "data_source": "binance",
        "panel_mode": meta.get("panel_mode") or active_execution_mode(),
        "execution_mode_at_open": meta.get("execution_mode_at_open"),
        "exchange_order_id": meta.get("exchange_order_id") or "",
        "min_unreal_seen": float(meta.get("min_unreal_seen") or 0),
        "max_unreal_seen": float(meta.get("max_unreal_seen") or 0),
    }
    if meta.get("price_history") and len(meta["price_history"]) >= 2:
        pos["price_history"] = list(meta["price_history"])
        pos["time_history"] = list(meta.get("time_history") or [])
    apply_exchange_snapshot(pos, ep)
    pos["data_source"] = "binance"
    pos["round_trip_fee_est_usd"] = round_trip_fee_usd(float(pos["stake_usd"]), lev)
    return pos


def reconcile_local_positions(
    local: list[dict[str, Any]],
    exchange_list: list[dict[str, Any]],
) -> None:
    """Yerel on_exchange satırlarını her tick Binance ile güncelle."""
    emap = exchange_map_by_symbol_side(exchange_list)
    for pos in local:
        if not pos.get("on_exchange"):
            continue
        key = (str(pos["symbol"]), str(pos["side"]))
        ep = emap.get(key)
        if not ep:
            continue
        apply_exchange_snapshot(pos, ep)
        pos["data_source"] = "binance"
        pos["exchange_synced"] = True
        mark = float(pos.get("current_price") or 0)
        if mark > 0:
            hist = pos.setdefault("price_history", [])
            times = pos.setdefault("time_history", [])
            if not hist or abs(hist[-1] - mark) > 1e-12:
                hist.append(mark)
                times.append(datetime.now(timezone.utc).isoformat())
                if len(hist) > 120:
                    hist.pop(0)
                    times.pop(0)


def _panel_min_notional_usd() -> float:
    try:
        return max(0.0, float(os.getenv("MEGA_PANEL_MIN_NOTIONAL_USD", "5")))
    except ValueError:
        return 5.0


def _filter_exchange_rows_for_panel(
    exchange_list: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Demo UI ile hizalama — toz pozisyonları (min notional altı) gizle."""
    floor = _panel_min_notional_usd()
    if floor <= 0:
        return list(exchange_list)
    out: list[dict[str, Any]] = []
    for ep in exchange_list:
        notional = abs(float(ep.get("notional_usd") or 0))
        if notional <= 0:
            size = abs(float(ep.get("contracts") or 0))
            mark = float(ep.get("mark_price") or 0)
            notional = size * mark if size > 0 and mark > 0 else 0.0
        if notional >= floor:
            out.append(ep)
    return out


def build_open_positions_for_ui(
    local_positions: list[dict[str, Any]],
    exchange_list: list[dict[str, Any]],
    client: Any,
    *,
    allow_chart_fetch: bool = True,
    enrich_fill: bool = True,
) -> list[dict[str, Any]]:
    """
    Panel açık pozisyon listesi — yalnızca borsada olanlar, tüm alanlar Binance.
    Yerel meta (sinyal, id) sembol+yön ile birleştirilir.
    """
    if not exchange_list:
        return []

    exchange_list = _filter_exchange_rows_for_panel(exchange_list)

    local_map: dict[tuple[str, str], dict[str, Any]] = {}
    for p in local_positions:
        if p.get("on_exchange") or p.get("exchange_synced"):
            local_map[(str(p["symbol"]), str(p["side"]))] = p

    out: list[dict[str, Any]] = []
    for ep in exchange_list:
        key = (str(ep.get("symbol") or f"{ep.get('coin')}USDT"), str(ep.get("side")))
        meta = local_map.get(key)
        pid = int(meta["id"]) if meta and meta.get("id") is not None else 0
        row = _minimal_position_from_exchange(ep, position_id=pid, local_meta=meta)
        if meta and not enrich_fill:
            for key in (
                "fill_price_est",
                "fill_gross_unreal",
                "fill_net_est",
                "fill_net_ready",
                "fill_net_fees_est",
                "fill_net_funding_est",
                "est_funding_fee_usd",
                "funding_rate",
                "exit_min_net_usd",
            ):
                if meta.get(key) is not None:
                    row[key] = meta[key]
        if allow_chart_fetch:
            attach_binance_chart(row, client, allow_fetch=allow_chart_fetch)
        if enrich_fill and not getattr(client, "paper", True):
            try:
                from elite_trader.exchange_trade_truth import enrich_open_entry_fee_api
                from elite_trader.fee_economics import entry_fee_api_ready

                if meta and entry_fee_api_ready(meta):
                    row["entry_fee"] = meta.get("entry_fee")
                    row["fee_source"] = meta.get("fee_source")
                    row["exchange_order_id"] = meta.get("exchange_order_id") or row.get(
                        "exchange_order_id"
                    )
                else:
                    enrich_open_entry_fee_api(row, client, allow_fetch=True)
                    if meta is not None and entry_fee_api_ready(row):
                        meta["entry_fee"] = row.get("entry_fee")
                        meta["total_fees"] = row.get("total_fees")
                        meta["fee_source"] = row.get("fee_source")
                        if row.get("exchange_order_id"):
                            meta["exchange_order_id"] = row.get("exchange_order_id")
            except Exception:
                pass
        panel_exchange_only = os.getenv(
            "MEGA_PANEL_EXCHANGE_ONLY", "0"
        ).strip().lower() in ("1", "true", "yes", "on")
        if enrich_fill and not panel_exchange_only and not getattr(client, "paper", True):
            try:
                from elite_trader.exchange_fill_truth import enrich_open_position_fill_fields

                enrich_open_position_fill_fields(
                    row,
                    client=client,
                    mode_id=str(row.get("panel_mode") or active_execution_mode()),
                )
            except Exception:
                pass
        out.append(row)
    return out
