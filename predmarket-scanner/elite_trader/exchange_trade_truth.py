"""Demo Binance — işlem ücreti/PnL yalnızca REST userTrades + income (tahmin yok)."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from elite_trader.exchange_settlement import (
    exchange_truth_enabled,
    fetch_order_fills,
    fetch_symbol_trades_since,
    settle_position_close,
)
from elite_trader.income_close import (
    aggregate_close_income_at_ms,
    apply_income_wallet_to_close_row,
    income_matches_realized,
)

_API_SOURCE = "binance_api"


def is_exchange_sync_close(row: dict[str, Any] | None) -> bool:
    """Borsa senkronu ile kapanmış hayalet kayıt (panelden çıkarılır)."""
    if not row:
        return False
    reason = str(row.get("exit_reason") or "").upper()
    return reason in ("EXCHANGE-SYNC", "SYNC-EXCHANGE")


def is_verified_exchange_trade(row: dict[str, Any] | None) -> bool:
    """Gerçek borsa emri + settlement — ExchangeSync/hayalet kopya değil."""
    if not row or not row.get("exchange_settled"):
        return False
    if str(row.get("fee_source") or "") != _API_SOURCE:
        return False
    if str(row.get("pnl_source") or "") != _API_SOURCE:
        return False
    if is_exchange_sync_close(row):
        return False
    if str(row.get("signal_source") or "") == "ExchangeSync":
        return False
    if int(row.get("trade_count_close") or 0) > 0:
        return True
    detail = row.get("settlement_detail")
    if isinstance(detail, dict):
        from elite_trader.exchange_settlement import settlement_has_api_close_fills

        if settlement_has_api_close_fills(detail):
            return True
    oid = str(row.get("exchange_close_order_id") or "").strip()
    if oid:
        from elite_trader.exchange_settlement import settlement_has_api_close_fills

        return settlement_has_api_close_fills(row)
    return bool(row.get("income_settled"))


_close_index_cache: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})
_CLOSE_INDEX_TTL_SEC = 120.0


def invalidate_exchange_close_index() -> None:
    global _close_index_cache
    _close_index_cache = (0.0, {})


def build_exchange_close_index(
    client: Any,
    *,
    since_ms: int | None = None,
    coins: list[str] | None = None,
    trade_limit: int = 120,
    force: bool = False,
) -> dict[str, dict[str, Any]]:
    """Binance userTrades — realizedPnl≠0 kapanış emirleri (orderId anahtar)."""
    global _close_index_cache
    now = time.time()
    if (
        not force
        and _close_index_cache[1]
        and (now - float(_close_index_cache[0] or 0)) < _CLOSE_INDEX_TTL_SEC
    ):
        return dict(_close_index_cache[1])
    if not force:
        try:
            from elite_trader.network_guard import is_degraded, skip_rest

            if skip_rest() or is_degraded():
                if _close_index_cache[1]:
                    return dict(_close_index_cache[1])
                return {}
        except Exception:
            pass
    if client is None or getattr(client, "paper", True):
        return {}
    if since_ms is None:
        since_ms = int((time.time() - 48 * 3600) * 1000)
    watch = [c.strip().upper() for c in (coins or []) if c.strip()]
    if not watch:
        watch = [
            "AVAX", "LINK", "SOL", "ETH", "XRP", "ARB", "WIF", "DOT", "BTC",
            "BNB", "DOGE", "NEAR", "APT", "ADA", "ONDO", "SEI", "INJ",
        ]
    max_coins = max(4, min(24, int(os.getenv("MEGA_CLOSE_INDEX_MAX_COINS", "8"))))
    watch = watch[:max_coins]
    index: dict[str, dict[str, Any]] = {}
    for coin in watch:
        try:
            from elite_trader.binance_rest_budget import acquire_rest_slot

            if not acquire_rest_slot(timeout=2.0):
                break
        except ImportError:
            pass
        try:
            trades = client.user_trades(coin, start_ms=since_ms, limit=trade_limit) or []
        except Exception:
            continue
        by_order: dict[str, list[dict[str, Any]]] = {}
        for t in trades:
            if abs(float(t.get("realizedPnl") or 0)) < 1e-8:
                continue
            oid = str(t.get("orderId") or t.get("id") or "").strip()
            if not oid:
                continue
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
            wallet = round(realized - exit_fee, 4)
            row = {
                "exchange_close_order_id": oid,
                "symbol": sym,
                "side": pos_side,
                "exit_price": exit_px,
                "size": qty,
                "pnl_usd": realized,
                "pnl_gross_usd": realized,
                "net_pnl": wallet,
                "wallet_pnl": wallet,
                "final_pnl": wallet,
                "exit_fee": exit_fee,
                "exit_ms": exit_ms,
                "trade_count_close": len(fills),
            }
            income = aggregate_close_income_at_ms(
                client, coin, exit_ms, since_ms=since_ms
            )
            if income_matches_realized(income, realized):
                row = apply_income_wallet_to_close_row(row, income)
            index[oid] = row
    _close_index_cache = (time.time(), dict(index))
    return index


def _row_exit_ms(row: dict[str, Any]) -> int | None:
    raw_exit = row.get("exit_time")
    if isinstance(raw_exit, (int, float)) and float(raw_exit) > 0:
        v = float(raw_exit)
        return int(v * 1000) if v < 1e12 else int(v)
    return _parse_exit_ms(str(row.get("exit_time_str") or row.get("exit_time_iso") or ""))


def find_close_index_hit(
    row: dict[str, Any],
    close_index: dict[str, dict[str, Any]],
    *,
    max_time_delta_ms: int = 900_000,
) -> dict[str, Any] | None:
    """orderId → symbol+side+exit zamanı (demo userTrades hizalama)."""
    oid = str(row.get("exchange_close_order_id") or "").strip()
    if oid:
        hit = close_index.get(oid)
        if hit and str(hit.get("symbol") or "").upper() == str(row.get("symbol") or "").upper():
            return hit
    sym = str(row.get("symbol") or "").upper()
    side = str(row.get("side") or "").upper()
    exit_ms = _row_exit_ms(row)
    best: dict[str, Any] | None = None
    best_delta = max_time_delta_ms + 1
    for hit in close_index.values():
        if str(hit.get("symbol") or "").upper() != sym:
            continue
        if str(hit.get("side") or "").upper() != side:
            continue
        hms = int(hit.get("exit_ms") or 0)
        if exit_ms and hms:
            delta = abs(hms - exit_ms)
            if delta <= max_time_delta_ms and delta < best_delta:
                best = hit
                best_delta = delta
        elif not exit_ms:
            return hit
    return best


def closed_has_exchange_fill(
    row: dict[str, Any],
    client: Any,
    *,
    close_index: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Kapalı kayıt Binance userTrades'te doğrulanmış mı."""
    if not row:
        return False
    if not row.get("on_exchange"):
        return True
    if client is None or getattr(client, "paper", True):
        return False
    if is_exchange_sync_close(row):
        return False
    if close_index is None:
        close_index = build_exchange_close_index(client)
    return find_close_index_hit(row, close_index) is not None


def prune_phantom_mega_closed(
    client: Any,
    rows: list[dict[str, Any]],
    *,
    close_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Borsada fill'i olmayan kapalı kayıtları ayır."""
    if client is None or getattr(client, "paper", True):
        return list(rows), []
    if close_index is None:
        close_index = build_exchange_close_index(client)
    if not close_index:
        # REST ban/418 — boş indeksle toplu silme yapma
        return list(rows), []
    keep: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for row in rows:
        # Sim / paper kapanış — borsa indeksi ile silinmez
        if not row.get("on_exchange") and not row.get("exchange_settled"):
            keep.append(row)
            continue
        if row.get("income_settled") and row.get("exchange_settled"):
            keep.append(row)
            continue
        if closed_has_exchange_fill(row, client, close_index=close_index):
            keep.append(row)
        else:
            removed.append(row)
    return keep, removed


def reconcile_mega_closed_rows_from_index(
    rows: list[dict[str, Any]],
    close_index: dict[str, dict[str, Any]],
    *,
    client: Any | None = None,
    since_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Doğrulanmış kayıtları borsa fill + income verisiyle hizala."""
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        hit = find_close_index_hit(r, close_index) if close_index else None
        if hit:
            for k in (
                "exit_price",
                "size",
                "pnl_usd",
                "pnl_gross_usd",
                "net_pnl",
                "wallet_pnl",
                "final_pnl",
                "exit_fee",
                "total_fees",
                "exchange_close_order_id",
                "income_settled",
                "commission_lines",
            ):
                if hit.get(k) is not None:
                    r[k] = hit[k]
            r["exchange_settled"] = True
            r["exchange_realized_pnl"] = hit.get("pnl_usd")
            r["trade_count_close"] = hit.get("trade_count_close")
            r["fee_source"] = _API_SOURCE
            r["pnl_source"] = _API_SOURCE
            r["data_source"] = _API_SOURCE
            r["sync_source"] = hit.get("sync_source") or "exchange_userTrades"
            r["backfilled"] = True
            stake = float(r.get("stake_usd") or 1)
            net = float(r.get("net_pnl") or 0)
            r["net_pnl_pct"] = round(net / stake * 100, 4) if stake else 0.0
            r["pnl_pct"] = r["net_pnl_pct"]
            if hit.get("total_fees") is not None:
                r["total_fees"] = hit["total_fees"]
            else:
                ef = float(r.get("exit_fee") or hit.get("exit_fee") or 0)
                entf = float(r.get("entry_fee") or 0)
                r["total_fees"] = round(entf + ef, 8)
        elif client is not None and not getattr(client, "paper", True):
            coin = _coin(str(r.get("symbol") or ""))
            exit_ms = _row_exit_ms(r)
            if coin and exit_ms:
                income = aggregate_close_income_at_ms(
                    client, coin, exit_ms, since_ms=since_ms
                )
                gross = float(
                    r.get("exchange_realized_pnl")
                    or r.get("pnl_usd")
                    or r.get("pnl_gross_usd")
                    or 0
                )
                if income_matches_realized(income, gross):
                    r = apply_income_wallet_to_close_row(r, income)
                    r["sync_source"] = "exchange_income"
                    r["fee_source"] = _API_SOURCE
                    r["pnl_source"] = _API_SOURCE
                    r["data_source"] = _API_SOURCE
        out.append(r)
    return out


def purge_exchange_sync_closed_trades(*, reason: str = "") -> dict[str, Any]:
    """Yalnızca EXCHANGE-SYNC / SYNC-EXCHANGE kapalı kayıtları sil."""
    import json
    from datetime import datetime, timezone

    from elite_pro_state import init_db, load_closed, save_closed, state_db_path
    from elite_trader.parallel_universe_engine import _load as _pu_load
    from elite_trader.parallel_universe_engine import _save as _pu_save
    from elite_trader.parallel_universe_engine import all_mode_ids

    init_db()
    rows = load_closed()
    keep = [dict(r) for r in rows if not is_exchange_sync_close(r)]
    removed = [dict(r) for r in rows if is_exchange_sync_close(r)]

    archive_dir = Path(__file__).resolve().parent.parent / "data" / "deleted_archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"exchange_sync_purge_{stamp}.json"
    archive_path.write_text(
        json.dumps(
            {
                "reason": reason or "exchange_sync_purge",
                "removed_count": len(removed),
                "kept_count": len(keep),
                "removed": removed,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if len(removed) != len(rows):
        from elite_pro_state import clear_closed

        clear_closed()
        for row in keep:
            save_closed(row)

    pu_removed = 0
    st = _pu_load()
    for mid in all_mode_ids():
        book = st.get("universes", {}).get(mid) or {}
        closed = list(book.get("closed") or [])
        if not closed:
            continue
        filtered = [c for c in closed if not is_exchange_sync_close(c)]
        pu_removed += len(closed) - len(filtered)
        book["closed"] = filtered
        st["universes"][mid] = book
    _pu_save(st)

    mega_removed = 0
    root = Path(__file__).resolve().parent.parent / "data"
    for mega_path in (
        root / "mega_live_closed.json",
        root / "mega_9007" / "mega_live_closed.json",
    ):
        if not mega_path.is_file():
            continue
        try:
            payload = json.loads(mega_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        closed = list(payload.get("closed") or [])
        if not closed:
            continue
        filtered = [c for c in closed if not is_exchange_sync_close(c)]
        n_removed = len(closed) - len(filtered)
        if n_removed <= 0:
            continue
        mega_removed += n_removed
        payload["closed"] = filtered
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        tmp = mega_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(mega_path)

    return {
        "ok": True,
        "reason": reason,
        "state_db": str(state_db_path()),
        "archive": str(archive_path),
        "removed_db": len(removed),
        "kept_db": len(keep),
        "removed_parallel_closed": pu_removed,
        "removed_mega_closed": mega_removed,
    }


def purge_copy_closed_trades(*, reason: str = "") -> dict[str, Any]:
    """Kopya kapalı işlemleri sil — yalnızca is_verified_exchange_trade kalır."""
    import json
    from datetime import datetime, timezone

    from elite_pro_state import clear_closed, init_db, load_closed, save_closed, state_db_path
    from elite_trader.parallel_universe_engine import _load as _pu_load
    from elite_trader.parallel_universe_engine import _save as _pu_save
    from elite_trader.parallel_universe_engine import all_mode_ids

    init_db()
    rows = load_closed()
    keep = [dict(r) for r in rows if is_verified_exchange_trade(r)]
    removed = [dict(r) for r in rows if not is_verified_exchange_trade(r)]

    archive_dir = Path(__file__).resolve().parent.parent / "data" / "deleted_archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"copy_purge_{stamp}.json"
    archive_path.write_text(
        json.dumps(
            {
                "reason": reason or "copy_purge",
                "removed_count": len(removed),
                "kept_count": len(keep),
                "removed": removed,
                "kept_ids": [r.get("id") for r in keep],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    clear_closed()
    for row in keep:
        save_closed(row)

    pu_removed = 0
    st = _pu_load()
    for mid in all_mode_ids():
        book = st.get("universes", {}).get(mid) or {}
        closed = list(book.get("closed") or [])
        if not closed:
            continue
        filtered = [c for c in closed if is_verified_exchange_trade(c)]
        pu_removed += len(closed) - len(filtered)
        book["closed"] = filtered
        st["universes"][mid] = book
    _pu_save(st)

    return {
        "ok": True,
        "reason": reason,
        "state_db": str(state_db_path()),
        "archive": str(archive_path),
        "removed_db": len(removed),
        "kept_db": len(keep),
        "removed_parallel_closed": pu_removed,
    }


_cache_lock = threading.Lock()
_closed_truth_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_open_entry_cache: dict[str, tuple[float, float]] = {}
_CACHE_TTL_SEC = 600.0
_MAX_BACKFILL_PER_CALL = 3
_BACKFILL_INTERVAL_SEC = 45.0
_backfill_lock = threading.Lock()
_backfill_running = False
_backfill_pending: set[str] = set()
_last_backfill_schedule_ts = 0.0


def api_truth_enabled() -> bool:
    return exchange_truth_enabled()


def _coin(symbol: str) -> str:
    return str(symbol or "").replace("USDT", "").upper()


def _parse_exit_ms(exit_time: str | None) -> int | None:
    if not exit_time:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(str(exit_time).strip()[:19], fmt)
            return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    try:
        s = str(exit_time).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _trade_side_match(side: str, trade: dict[str, Any]) -> bool:
    side_u = str(side or "LONG").upper()
    raw_side = str(trade.get("side") or "").upper()
    if raw_side in ("BUY", "SELL"):
        want = "BUY" if side_u == "LONG" else "SELL"
        return raw_side == want
    buyer = bool(trade.get("buyer"))
    if side_u == "LONG":
        return buyer
    return not buyer


def _close_side_match(side: str, trade: dict[str, Any]) -> bool:
    side_u = str(side or "LONG").upper()
    raw_side = str(trade.get("side") or "").upper()
    if raw_side in ("BUY", "SELL"):
        want = "SELL" if side_u == "LONG" else "BUY"
        return raw_side == want
    buyer = bool(trade.get("buyer"))
    if side_u == "LONG":
        return not buyer
    return buyer


def _entry_trades_for_open(
    client: Any,
    coin: str,
    opened_at_iso: str | None,
    *,
    lookback_hours: float = 12.0,
) -> list[dict[str, Any]]:
    """ExchangeSync opened_at geç yazılabilir — giriş fill'inden önce pencere aç."""
    trades = fetch_symbol_trades_since(client, coin, opened_at_iso, pre_buffer_ms=7_200_000)
    if trades:
        return trades
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    return fetch_symbol_trades_since(client, coin, since)


def fetch_entry_fee_api(
    client: Any,
    *,
    symbol: str,
    side: str,
    entry_order_id: str | int | None = None,
    opened_at_iso: str | None = None,
) -> float:
    """Giriş commission — orderId userTrades; yoksa açılış penceresi."""
    if client is None or getattr(client, "paper", True):
        return 0.0
    coin = _coin(symbol)
    if entry_order_id:
        row = fetch_order_fills(client, coin, entry_order_id)
        if row.get("commission", 0) > 0:
            return round(float(row["commission"]), 8)
    trades = _entry_trades_for_open(client, coin, opened_at_iso, lookback_hours=24.0)
    if not trades:
        return 0.0
    entry_comm = 0.0
    for t in sorted(trades, key=lambda x: int(x.get("time") or 0)):
        if not _trade_side_match(side, t):
            continue
        entry_comm += abs(float(t.get("commission") or 0))
        if float(t.get("realizedPnl") or 0) != 0:
            break
    return round(entry_comm, 8)


def discover_entry_order_id_api(
    client: Any,
    *,
    symbol: str,
    side: str,
    entry_price: float,
    size: float,
    opened_at_iso: str | None = None,
    lookback_hours: float = 12.0,
) -> str:
    """ExchangeSync — userTrades'ten giriş orderId (fiyat/miktar eşleşmesi)."""
    if client is None or getattr(client, "paper", True):
        return ""
    entry = float(entry_price or 0)
    qty = abs(float(size or 0))
    if entry <= 0 or qty <= 0:
        return ""
    coin = _coin(symbol)
    trades = _entry_trades_for_open(
        client, coin, opened_at_iso, lookback_hours=lookback_hours
    )
    if not trades:
        return ""
    best_oid = ""
    best_score = 999.0
    for t in sorted(trades, key=lambda x: int(x.get("time") or 0), reverse=True):
        if not _trade_side_match(side, t):
            continue
        px = float(t.get("price") or 0)
        tqty = abs(float(t.get("qty") or 0))
        if px <= 0 or tqty <= 0:
            continue
        px_err = abs(px - entry) / entry
        qty_err = abs(tqty - qty) / max(qty, 1e-9)
        if px_err > 0.004 or qty_err > 0.12:
            continue
        score = px_err * 1000.0 + qty_err * 100.0
        oid = str(t.get("orderId") or "")
        if oid and score < best_score:
            best_score = score
            best_oid = oid
    return best_oid


def reconcile_closed_from_api(
    client: Any,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Kapalı işlem — userTrades ile gerçek entry/exit fee, realized, wallet.
    Tahmin veya formül kullanılmaz.
    """
    if client is None or getattr(client, "paper", True) or not api_truth_enabled():
        return None
    if not row.get("on_exchange") and not row.get("exchange_order_id"):
        return None

    pos_like = {
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "entry_price": row.get("entry_price"),
        "size": row.get("size"),
        "stake_usd": row.get("stake_usd") or 1,
        "leverage": row.get("leverage") or 5,
        "opened_at_iso": row.get("opened_at_iso"),
        "entry_time_str": row.get("entry_time") or row.get("entry_time_str"),
        "on_exchange": True,
        "exchange_order_id": row.get("exchange_order_id"),
        "exchange_close_order_id": row.get("exchange_close_order_id"),
    }
    settled = settle_position_close(
        client,
        pos_like,
        close_order_id=row.get("exchange_close_order_id"),
        settle_wait_sec=0.0,
    )
    if not settled:
        return None
    return {
        "entry_price": settled.get("entry_price"),
        "exit_price": settled.get("exit_price"),
        "size": settled.get("size"),
        "entry_fee": settled.get("entry_fee"),
        "exit_fee": settled.get("exit_fee"),
        "total_fees": settled.get("total_fees"),
        "pnl_usd": settled.get("pnl_usd") or settled.get("pnl_gross_usd"),
        "pnl_gross_usd": settled.get("pnl_gross_usd"),
        "net_pnl": settled.get("net_pnl"),
        "wallet_pnl": settled.get("wallet_pnl"),
        "final_pnl": settled.get("wallet_pnl"),
        "net_pnl_pct": settled.get("net_pnl_pct"),
        "exchange_settled": True,
        "exchange_realized_pnl": settled.get("exchange_realized_pnl"),
        "exchange_commission": settled.get("exchange_commission"),
        "exchange_close_order_id": settled.get("exchange_close_order_id"),
        "fee_source": _API_SOURCE,
        "pnl_source": _API_SOURCE,
        "data_source": _API_SOURCE,
    }


def _closed_cache_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("id")),
            str(row.get("symbol")),
            str(row.get("side")),
            str(row.get("exit_time") or row.get("closed_at") or ""),
        ]
    )


def apply_api_truth_to_closed(row: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.update(patch)
    out["fee_source"] = _API_SOURCE
    out["pnl_source"] = _API_SOURCE
    out["data_source"] = _API_SOURCE
    return out


def apply_closed_cache_only(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Panel hot path — yalnızca bellek önbelleği (REST yok)."""
    if not rows:
        return rows
    out: list[dict[str, Any]] = []
    now = time.time()
    for row in rows:
        r = dict(row)
        if r.get("fee_source") == _API_SOURCE and r.get("exchange_settled"):
            out.append(r)
            continue
        key = _closed_cache_key(r)
        with _cache_lock:
            cached = _closed_truth_cache.get(key)
        if cached and (now - cached[0]) < _CACHE_TTL_SEC:
            out.append(apply_api_truth_to_closed(r, cached[1]))
        else:
            out.append(r)
    return out


def _backfill_one(client: Any, row: dict[str, Any]) -> None:
    key = _closed_cache_key(row)
    patch = reconcile_closed_from_api(client, row)
    if not patch:
        with _cache_lock:
            _backfill_pending.discard(key)
        return
    merged = apply_api_truth_to_closed(row, patch)
    with _cache_lock:
        _closed_truth_cache[key] = (time.time(), patch)
        _backfill_pending.discard(key)
    try:
        from elite_pro_state import save_closed

        save_closed(merged, mode_id=str(row.get("panel_mode") or ""))
    except Exception:
        pass
    print(
        f"  📡 API backfill {row.get('symbol')} #{row.get('id')} "
        f"wallet=${float(patch.get('wallet_pnl') or 0):.4f} "
        f"realized=${float(patch.get('exchange_realized_pnl') or patch.get('pnl_usd') or 0):.4f}"
    )


def _closed_backfill_worker(client: Any, rows: list[dict[str, Any]]) -> None:
    global _backfill_running
    try:
        fetched = 0
        for row in rows:
            if fetched >= _MAX_BACKFILL_PER_CALL:
                break
            r = dict(row)
            if r.get("fee_source") == _API_SOURCE and r.get("exchange_settled"):
                continue
            key = _closed_cache_key(r)
            with _cache_lock:
                cached = _closed_truth_cache.get(key)
                if cached and (time.time() - cached[0]) < _CACHE_TTL_SEC:
                    continue
                if key in _backfill_pending:
                    continue
                _backfill_pending.add(key)
            try:
                _backfill_one(client, r)
                fetched += 1
            except Exception as exc:
                with _cache_lock:
                    _backfill_pending.discard(key)
                print(f"  ⚠ API backfill {r.get('symbol')}: {exc}")
    finally:
        with _backfill_lock:
            _backfill_running = False


def schedule_closed_backfill(
    rows: list[dict[str, Any]],
    client: Any,
) -> None:
    """Geçmiş işlemler — arka planda userTrades (panel bloklamaz)."""
    global _backfill_running, _last_backfill_schedule_ts
    if not rows or client is None or getattr(client, "paper", True):
        return
    now = time.time()
    if now - _last_backfill_schedule_ts < _BACKFILL_INTERVAL_SEC:
        return
    with _backfill_lock:
        if _backfill_running:
            return
        _backfill_running = True
        _last_backfill_schedule_ts = now
    th = threading.Thread(
        target=_closed_backfill_worker,
        args=(client, list(rows)),
        name="closed-api-backfill",
        daemon=True,
    )
    th.start()


def enrich_closed_list_api(
    rows: list[dict[str, Any]],
    client: Any,
    *,
    max_fetch: int = _MAX_BACKFILL_PER_CALL,
    persist: bool = False,
    allow_network: bool = False,
) -> list[dict[str, Any]]:
    """Kapalı tablo — varsayılan cache-only; ağ yalnızca allow_network=True."""
    if not rows or client is None or getattr(client, "paper", True):
        return rows
    if not allow_network:
        schedule_closed_backfill(rows, client)
        return apply_closed_cache_only(rows)
    out: list[dict[str, Any]] = []
    fetched = 0
    for row in rows:
        r = dict(row)
        if r.get("fee_source") == _API_SOURCE and r.get("exchange_settled"):
            out.append(r)
            continue
        key = _closed_cache_key(r)
        now = time.time()
        with _cache_lock:
            cached = _closed_truth_cache.get(key)
        if cached and (now - cached[0]) < _CACHE_TTL_SEC:
            out.append(apply_api_truth_to_closed(r, cached[1]))
            continue
        if fetched >= max_fetch:
            out.append(r)
            continue
        patch = reconcile_closed_from_api(client, r)
        fetched += 1
        if patch:
            merged = apply_api_truth_to_closed(r, patch)
            with _cache_lock:
                _closed_truth_cache[key] = (now, patch)
            if persist:
                try:
                    from elite_pro_state import save_closed

                    save_closed(merged, mode_id=str(r.get("panel_mode") or ""))
                except Exception:
                    pass
            out.append(merged)
        else:
            out.append(r)
    return out


def enrich_open_entry_fee_api(
    pos: dict[str, Any],
    client: Any,
    *,
    allow_fetch: bool = True,
) -> None:
    """Açık pozisyon — entry_fee yalnızca userTrades commission."""
    if client is None or getattr(client, "paper", True):
        return
    if not pos.get("on_exchange"):
        return
    from elite_trader.fee_economics import entry_fee_api_ready

    if entry_fee_api_ready(pos):
        return
    oid = str(pos.get("exchange_order_id") or "").strip()
    cache_key = f"{pos.get('symbol')}|{pos.get('side')}|{oid or 'discover'}"
    now = time.time()
    with _cache_lock:
        hit = _open_entry_cache.get(cache_key)
    if hit and (now - hit[0]) < 120.0:
        pos["entry_fee"] = hit[1]
        pos["total_fees"] = hit[1]
        pos["fee_source"] = _API_SOURCE
        return
    if not allow_fetch:
        return
    if not oid:
        oid = discover_entry_order_id_api(
            client,
            symbol=str(pos.get("symbol") or ""),
            side=str(pos.get("side") or "LONG"),
            entry_price=float(pos.get("entry_price") or 0),
            size=float(pos.get("size") or 0),
            opened_at_iso=pos.get("opened_at_iso") or pos.get("entry_time_str"),
        )
        if oid:
            pos["exchange_order_id"] = oid
    fee = fetch_entry_fee_api(
        client,
        symbol=str(pos.get("symbol") or ""),
        side=str(pos.get("side") or "LONG"),
        entry_order_id=oid or None,
        opened_at_iso=pos.get("opened_at_iso") or pos.get("entry_time_str"),
    )
    if fee > 0:
        pos["entry_fee"] = fee
        pos["total_fees"] = fee
        pos["fee_source"] = _API_SOURCE
        with _cache_lock:
            _open_entry_cache[cache_key] = (now, fee)


def enrich_open_list_api(
    rows: list[dict[str, Any]],
    client: Any,
    *,
    allow_fetch: bool = False,
) -> None:
    for p in rows:
        if p.get("on_exchange") or p.get("exchange_synced"):
            enrich_open_entry_fee_api(p, client, allow_fetch=allow_fetch)


def settlement_to_closed_fields(settled: dict[str, Any]) -> dict[str, Any]:
    """Kapanış settlement → kapalı kayıt alanları (API only)."""
    wp = float(settled.get("wallet_pnl") or settled.get("net_pnl") or 0)
    gross = float(settled.get("pnl_usd") or settled.get("pnl_gross_usd") or 0)
    return {
        "entry_price": settled.get("entry_price"),
        "exit_price": settled.get("exit_price"),
        "size": settled.get("size"),
        "entry_fee": settled.get("entry_fee"),
        "exit_fee": settled.get("exit_fee"),
        "total_fees": settled.get("total_fees"),
        "pnl_usd": gross,
        "net_pnl": wp,
        "wallet_pnl": wp,
        "final_pnl": wp,
        "net_pnl_pct": settled.get("net_pnl_pct"),
        "tax": 0.0,
        "exchange_settled": True,
        "exchange_realized_pnl": settled.get("exchange_realized_pnl"),
        "exchange_commission": settled.get("exchange_commission"),
        "exchange_close_order_id": settled.get("exchange_close_order_id"),
        "fee_source": _API_SOURCE,
        "pnl_source": _API_SOURCE,
        "data_source": _API_SOURCE,
    }


def format_open_log_api(pos: dict[str, Any]) -> str:
    sym = pos.get("symbol") or "?"
    side = pos.get("side") or "?"
    ep = float(pos.get("entry_price") or 0)
    ef = pos.get("entry_fee")
    oid = pos.get("exchange_order_id") or "—"
    if ef is not None and float(ef) > 0 and pos.get("fee_source") == _API_SOURCE:
        return (
            f"✅ Open {sym} {side} | Binance API | entry=${ep:.4f} "
            f"entryFee=${float(ef):.4f} order=#{oid}"
        )
    return f"✅ {side} {sym} @ ${ep:.2f} | order=#{oid} (fee API bekleniyor)"


def format_close_log_api(
    *,
    pos_id: int | str,
    symbol: str,
    settled: dict[str, Any] | None,
    record_reason: str,
    fallback_final: float | None = None,
) -> str:
    if settled and settled.get("exchange_settled"):
        wp = float(settled.get("wallet_pnl") or settled.get("net_pnl") or 0)
        gross = float(
            settled.get("exchange_realized_pnl")
            or settled.get("pnl_usd")
            or settled.get("pnl_gross_usd")
            or 0
        )
        tf = float(settled.get("total_fees") or 0)
        ef = float(settled.get("entry_fee") or 0)
        xf = float(settled.get("exit_fee") or 0)
        xp = float(settled.get("exit_price") or 0)
        return (
            f"✅ Closed #{pos_id}: {symbol} | Binance API | "
            f"realized=${gross:.4f} entryFee=${ef:.4f} exitFee=${xf:.4f} "
            f"totalFee=${tf:.4f} wallet=${wp:.4f} exit=${xp:.6f} | {record_reason}"
        )
    if fallback_final is not None:
        return f"✅ Closed #{pos_id}: {symbol} | ${fallback_final:.2f} (API yok — paper/yerel)"
    return f"✅ Closed #{pos_id}: {symbol} | settlement yok"
