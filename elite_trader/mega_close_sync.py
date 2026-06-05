"""MEGA arka plan motoru — Binance userTrades ile eksik kapanışları disk ile eşleştir.

REST positionRisk döngüsünden ayrı thread; her tick ≤ birkaç coin (hedef <1s).
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

_stop = threading.Event()
_wake = threading.Event()
_force = False
_thread: threading.Thread | None = None
_last_run_ts: float = 0.0
_last_added: int = 0
_last_duration_ms: float = 0.0
_last_error: str | None = None
_last_error_ts: float = 0.0
_last_reconcile_error: str | None = None
_inflight = False
_coin_cursor: int = 0
_scan_pass: int = 0

_DEFAULT_WATCH = (
    "AVAX,LINK,SOL,ETH,XRP,ARB,WIF,DOT,BTC,BNB,DOGE,NEAR,APT,ADA,ONDO,SEI,INJ,OP"
)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "1" if default else "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _interval_sec() -> float:
    return max(8.0, _env_float("MEGA_SYNC_CLOSES_SEC", 20.0))


def close_sync_motor_alive() -> bool:
    return bool(_thread and _thread.is_alive())


def _session_path_str() -> str | None:
    try:
        from elite_trader import mega_live as ml

        return str(ml._mega_session_path())
    except Exception:
        return None


def close_sync_health() -> dict[str, Any]:
    now = time.time()
    return {
        "alive": close_sync_motor_alive(),
        "last_run_ago_sec": round(now - _last_run_ts, 1) if _last_run_ts else None,
        "last_added": _last_added,
        "last_duration_ms": _last_duration_ms,
        "inflight": _inflight,
        "interval_sec": _interval_sec(),
        "scan_pass": _scan_pass,
        "last_error": _last_error,
        "last_error_ts": _last_error_ts or None,
        "last_reconcile_error": _last_reconcile_error,
        "session_path": _session_path_str(),
    }


def _record_error(msg: str, *, reconcile: bool = False) -> None:
    global _last_error, _last_error_ts, _last_reconcile_error
    _last_error = msg[:500]
    _last_error_ts = time.time()
    if reconcile:
        _last_reconcile_error = _last_error


def wake_mega_close_sync(*, force: bool = False) -> None:
    global _force
    if force:
        _force = True
    _wake.set()


def _watch_coins(*, full: bool) -> list[str]:
    from elite_trader import mega_live as ml

    coins: set[str] = set()
    for p in ml._mega_positions:
        sym = str(p.get("symbol") or "").replace("USDT", "").upper()
        if sym:
            coins.add(sym)
    for ep in ml._mega_positions_cache or []:
        c = str(ep.get("coin") or "").upper()
        if c:
            coins.add(c)
    for row in (ml._mega_closed or [])[-12:]:
        sym = str(row.get("symbol") or "").replace("USDT", "").upper()
        if sym:
            coins.add(sym)
    if full or len(coins) < 2:
        for c in _DEFAULT_WATCH.split(","):
            c = c.strip().upper()
            if c:
                coins.add(c)
    return sorted(coins)


def _mega_closed_suppress_ts() -> float:
    """Panel temizliği zaman damgası (0 = suppress yok)."""
    try:
        from elite_trader import mega_live as ml

        p = ml._mega_closed_suppress_path()
        if not p.is_file():
            return 0.0
        raw = p.read_text(encoding="utf-8").strip()
        if not raw:
            return 0.0
        return float(raw.split()[0])
    except Exception:
        return 0.0


def _close_sync_since_ms(*, force: bool, lookback_h: float) -> int:
    """userTrades penceresi — reset sonrası yalnızca yeni kapanışlar."""
    from elite_trader import mega_live as ml

    since_ms = int((time.time() - lookback_h * 3600) * 1000)
    if force and ml._mega_session_path().is_file():
        try:
            st = json.loads(ml._mega_session_path().read_text(encoding="utf-8"))
            from elite_trader.exchange_settlement import _parse_iso_ms

            ms = _parse_iso_ms(st.get("set_at"))
            if ms:
                since_ms = min(since_ms, max(int(ms) - 3_600_000, since_ms))
        except Exception:
            pass
    if ml.mega_closed_backfill_suppressed():
        sup_ms = int(_mega_closed_suppress_ts() * 1000) - 120_000
        since_ms = max(since_ms, sup_ms)
    try:
        epoch_ms = int(ml._closed_panel_epoch_sec() * 1000)
        if epoch_ms > 0:
            since_ms = max(since_ms, epoch_ms)
    except Exception:
        pass
    return since_ms


def _next_coin_batch(watch: list[str], *, force: bool) -> list[str]:
    global _coin_cursor, _scan_pass
    if not watch:
        return []
    batch = max(1, _env_int("MEGA_CLOSE_SYNC_BATCH", 1))
    if force:
        _scan_pass += 1
        batch = max(batch, _env_int("MEGA_CLOSE_SYNC_FORCE_BATCH", 2))
    start = _coin_cursor
    end = start + batch
    if end >= len(watch):
        _coin_cursor = 0
        _scan_pass += 1
    else:
        _coin_cursor = end
    if start >= len(watch):
        start = 0
        end = min(batch, len(watch))
    return watch[start:end] or watch[:batch]


def mega_close_sync_enabled() -> bool:
    """Canlı 9006 — kapanış sonrası userTrades ile kapalı tabloyu tamamla."""
    try:
        from elite_trader.mega_live import mega_live_orders_enabled, mega_sim_enabled

        if mega_live_orders_enabled() and not mega_sim_enabled():
            return _env_bool("MEGA_CLOSE_SYNC_ENABLED", True)
    except Exception:
        pass
    return _env_bool("MEGA_CLOSE_SYNC_ENABLED", True)


def sync_priority_coins_from_exchange(coins: list[str]) -> int:
    """Borsa kapanışı sonrası acil coin senkronu (userTrades, throttling yok)."""
    if not mega_close_sync_enabled():
        return 0
    clean = sorted({str(c or "").upper().replace("USDT", "") for c in coins if c})
    if not clean:
        return 0
    return sync_missing_closes_from_exchange(force=True, coins=clean)


def sync_missing_closes_from_exchange(
    *, force: bool = False, coins: list[str] | None = None
) -> int:
    """Binance userTrades — diskte olmayan kapanışları ekle (batch, açık coin öncelik)."""
    from elite_trader import mega_live as ml

    if not mega_close_sync_enabled():
        return 0
    ml._ensure_mega_closed_loaded()
    now = time.time()
    priority = bool(coins)
    min_iv = max(6.0, _env_float("MEGA_CLOSE_SYNC_MIN_SEC", 10.0))
    if (
        not force
        and not priority
        and ml._mega_missing_close_sync_ts
        and (now - ml._mega_missing_close_sync_ts) < min_iv
    ):
        return 0
    if not ml.mega_live_enabled():
        return 0
    mc = ml.get_mega_client()
    if not mc or mc.paper:
        return 0
    if not priority:
        ml._mega_missing_close_sync_ts = now
    lookback_h = max(2.0, _env_float("MEGA_CLOSE_SYNC_LOOKBACK_H", 8.0))
    since_ms = _close_sync_since_ms(force=force or priority, lookback_h=lookback_h)
    seen = {ml._closed_dedupe_key(r) for r in ml._mega_closed}
    seen_oids = {
        str(r.get("exchange_close_order_id") or "").strip()
        for r in ml._mega_closed
        if str(r.get("exchange_close_order_id") or "").strip()
    }
    pid = max([int(r.get("id") or 0) for r in ml._mega_closed] + [ml._mega_position_id - 1]) + 1
    if coins:
        cap = max(1, _env_int("MEGA_CLOSE_SYNC_PRIORITY_MAX_COINS", 2))
        batch = sorted({str(c).upper().replace("USDT", "") for c in coins if c})[:cap]
    else:
        watch = _watch_coins(full=False)
        batch = _next_coin_batch(watch, force=force)
    trade_limit = max(30, _env_int("MEGA_CLOSE_SYNC_TRADE_LIMIT", 80))
    if priority:
        trade_limit = max(trade_limit, _env_int("MEGA_CLOSE_SYNC_TRADE_LIMIT_FORCE", 80))
    elif force:
        trade_limit = min(
            trade_limit,
            max(30, _env_int("MEGA_CLOSE_SYNC_TRADE_LIMIT_FORCE", 80)),
        )
    added = 0
    for coin in batch:
        try:
            trades = mc.user_trades(coin, start_ms=since_ms, limit=trade_limit) or []
        except Exception:
            continue
        by_order: dict[str, list[dict[str, Any]]] = {}
        for t in trades:
            if abs(float(t.get("realizedPnl") or 0)) < 1e-8:
                continue
            oid = str(t.get("orderId") or t.get("id") or "")
            by_order.setdefault(oid, []).append(t)
        for oid, fills in by_order.items():
            sym = f"{coin}USDT"
            realized = round(sum(float(f.get("realizedPnl") or 0) for f in fills), 4)
            exit_fee = round(sum(abs(float(f.get("commission") or 0)) for f in fills), 8)
            qty = round(sum(float(f.get("qty") or 0) for f in fills), 8)
            quote = sum(float(f.get("quoteQty") or 0) for f in fills)
            exit_px = round(quote / qty, 8) if qty > 0 else 0.0
            close_side = str(fills[0].get("side") or "SELL").upper()
            pos_side = "LONG" if close_side == "SELL" else "SHORT"
            exit_ms = max(int(f.get("time") or 0) for f in fills)
            exit_time_str = datetime.utcfromtimestamp(exit_ms / 1000.0).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            key = f"oid:{oid}"
            if key in seen or oid in seen_oids:
                continue
            if ml._position_still_open(sym, pos_side):
                continue
            entry_trades = [
                t
                for t in trades
                if int(t.get("time") or 0) < exit_ms
                and abs(float(t.get("realizedPnl") or 0)) < 1e-8
            ]
            entry_px = float(entry_trades[-1].get("price") or 0) if entry_trades else 0.0
            entry_fee = round(
                sum(abs(float(t.get("commission") or 0)) for t in entry_trades[-3:]),
                8,
            )
            total_fees = round(entry_fee + exit_fee, 8)
            wallet = round(realized - exit_fee, 4)
            from elite_trader.income_close import (
                aggregate_close_income_at_ms,
                apply_income_wallet_to_close_row,
                income_matches_realized,
            )

            income = aggregate_close_income_at_ms(
                mc, coin, exit_ms, since_ms=since_ms
            )
            sync_source = "exchange_userTrades"
            if income_matches_realized(income, realized):
                wallet = float(income.get("wallet_pnl") or wallet)
                total_fees = float(income.get("total_commission") or total_fees)
                exit_fee = total_fees
                sync_source = "exchange_income"
            else:
                wallet = round(realized - total_fees, 4)
            seen.add(key)
            seen_oids.add(oid)
            lev = 2
            stake = max(qty * entry_px / lev, 400.0) if entry_px > 0 else 400.0
            settled_stub: dict[str, Any] = {
                "wallet_pnl": wallet,
                "net_pnl": wallet,
                "pnl_usd": realized,
                "pnl_gross_usd": realized,
                "fee_source": "binance_api",
                "pnl_source": "binance_api",
                "trade_count_close": len(fills),
                "close_order_id": oid,
                "exit_price": exit_px,
                "entry_price": entry_px,
            }
            if sync_source == "exchange_income" and income:
                settled_stub["income_settled"] = True
                settled_stub["wallet_pnl"] = float(income.get("wallet_pnl") or wallet)
                settled_stub["net_pnl"] = settled_stub["wallet_pnl"]
            from elite_trader.fee_economics import (
                live_close_record_ok,
                settled_exit_record_reason,
            )

            if realized < -0.01 or wallet < -0.01:
                exit_reason = "SL"
            else:
                exit_reason = settled_exit_record_reason(
                    "TP", settled_stub, mode_id="mega"
                )
            ok_rec, record_reason, skip_detail = live_close_record_ok(
                exit_reason=exit_reason,
                exchange_settled=settled_stub,
                mode_id="mega",
                on_exchange=True,
            )
            if not ok_rec:
                if skip_detail and "kayıt yok" in skip_detail:
                    continue
                print(f"  ⛔ MEGA sync kayıt yok {sym}: {skip_detail}")
                continue
            exit_reason = record_reason or exit_reason
            if str(exit_reason).upper().startswith("SL") or wallet < -0.005:
                sl_tag = True
            else:
                sl_tag = False
            row = {
                "id": pid,
                "symbol": sym,
                "side": pos_side,
                "entry_price": entry_px,
                "exit_price": exit_px,
                "size": qty,
                "leverage": lev,
                "stake_usd": stake,
                "pnl_usd": realized,
                "pnl_gross_usd": realized,
                "entry_fee": entry_fee,
                "exit_fee": exit_fee,
                "total_fees": total_fees,
                "net_pnl": wallet,
                "wallet_pnl": wallet,
                "final_pnl": wallet,
                "net_pnl_pct": round(wallet / stake * 100, 4) if stake else 0,
                "exit_reason": exit_reason,
                "entry_time_str": exit_time_str,
                "exit_time": exit_ms / 1000.0,
                "exit_time_str": exit_time_str,
                "exit_time_iso": datetime.fromtimestamp(
                    exit_ms / 1000.0, tz=timezone.utc
                ).isoformat(),
                "duration_sec": 0.0,
                "duration": 0.0,
                "on_exchange": True,
                "exchange_settled": True,
                "exchange_close_order_id": oid,
                "exchange_realized_pnl": realized,
                "trade_count_close": len(fills),
                "settlement_detail": dict(settled_stub),
                "fee_source": "binance_api",
                "pnl_source": "binance_api",
                "data_source": "binance_api",
                "panel_mode": "mega",
                "execution_mode_at_close": "mega",
                "signal_source": "MEGA-LIVE",
                "backfilled": True,
                "sync_source": sync_source,
                "sl_close": sl_tag,
                "close_initiator": "exchange_sl" if sl_tag else "exchange_sync",
            }
            if sync_source == "exchange_income" and income:
                row = apply_income_wallet_to_close_row(row, income)
                wallet = float(row.get("wallet_pnl") or wallet)
            ml._append_mega_closed_record(row)
            print(
                f"  🔴 MEGA sync kapanış (API) {sym} {pos_side} "
                f"net=${wallet:.4f} ({exit_reason})"
            )
            pid += 1
            added += 1
    if added:
        ml._mega_position_id = max(ml._mega_position_id, pid)
        ml._dedupe_mega_closed(persist=True)
    return added


def _close_sync_tick(*, force: bool = False) -> None:
    global _last_run_ts, _last_added, _last_duration_ms, _inflight, _last_reconcile_error
    if _inflight:
        return
    from elite_trader import mega_live as ml

    if ml.mega_live_bot_only_closed() and not mega_close_sync_enabled():
        return
    _inflight = True
    t0 = time.perf_counter()
    reconcile_every = max(1, _env_int("MEGA_CLOSE_SYNC_RECONCILE_EVERY", 5))
    try:
        try:
            _last_added = sync_missing_closes_from_exchange(force=force)
        except Exception as exc:
            _record_error(f"sync: {exc}")
            print(f"  ⚠ MEGA close-sync sync: {exc}")
            _last_added = 0
        quiet_reset = ml.mega_closed_backfill_suppressed() and not (
            ml._mega_positions or ml._mega_positions_cache
        )
        do_reconcile = (
            _env_bool("MEGA_CLOSE_SYNC_RECONCILE", True)
            and _scan_pass > 0
            and (_scan_pass % reconcile_every == 0)
            and not quiet_reset
        )
        if force and _env_bool("MEGA_CLOSE_SYNC_RECONCILE_ON_FORCE", False):
            do_reconcile = True
        if do_reconcile or (
            _last_added > 0 and _env_bool("MEGA_CLOSE_SYNC_RECONCILE_ON_ADD", False)
        ):
            try:
                from elite_trader.mega_live import reconcile_mega_closed_with_exchange

                reconcile_mega_closed_with_exchange(force=force)
                _last_reconcile_error = None
            except Exception as exc:
                _record_error(f"reconcile: {exc}", reconcile=True)
                print(f"  ⚠ MEGA close-sync reconcile: {exc}")
        _last_run_ts = time.time()
    except Exception as exc:
        _record_error(str(exc))
        print(f"  ⚠ MEGA close-sync motor: {exc}")
    finally:
        _last_duration_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        _inflight = False


def _close_sync_loop() -> None:
    global _force
    while not _stop.is_set():
        force = bool(_force)
        _force = False
        _wake.clear()
        try:
            _close_sync_tick(force=force)
        except Exception as exc:
            print(f"  ⚠ MEGA close-sync motor: {exc}")
        _wake.wait(timeout=_interval_sec())


def start_mega_close_sync_motor() -> None:
    global _thread
    from elite_trader.mega_live import mega_live_enabled

    if not mega_live_enabled():
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_close_sync_loop, name="mega-close-sync", daemon=True
    )
    _thread.start()


def stop_mega_close_sync_motor() -> None:
    _stop.set()
    _wake.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=2.0)
