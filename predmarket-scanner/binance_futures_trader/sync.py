"""Binance testnet ↔ yerel DB senkronizasyonu (borsa = kaynak)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient


def sync_with_exchange(
    conn: sqlite3.Connection,
    client: BinanceFuturesClient,
    *,
    close_local: bool = True,
) -> dict[str, int]:
    """
    One-way modda borsa NET pozisyon gösterir; yerel hedge satırları drift yapar.
    - Borsada yok → yerel kapat
    - Ters yön (netlenmiş hedge) → yerel kapat
    - Aynı coin'de fazla satır → birini borsa verisiyle güncelle, diğerlerini kapat
    - Borsada var, DB'de yok → içe aktar
    """
    stats = {"closed": 0, "updated": 0, "imported": 0}
    if client.paper:
        return stats

    exch = client.exchange_positions()
    exch_by_coin = {p["coin"]: p for p in exch}
    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(
        "SELECT * FROM positions WHERE closed_at IS NULL ORDER BY id"
    ).fetchall()
    by_coin: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_coin.setdefault(str(r["coin"]), []).append(r)

    for coin, locals in by_coin.items():
        ep = exch_by_coin.get(coin)
        if ep is None:
            if close_local:
                for r in locals:
                    _close_local_row(conn, r, now, "no_exchange_position")
                    stats["closed"] += 1
            continue

        net_side = str(ep["side"])
        net_qty = float(ep["contracts"])
        net_entry = float(ep["entry_price"])
        mark = float(ep.get("mark_price") or net_entry)

        same = [r for r in locals if str(r["side"]) == net_side]
        opposite = [r for r in locals if str(r["side"]) != net_side]

        for r in opposite:
            if close_local:
                _close_local_row(conn, r, now, "netted_on_exchange")
                stats["closed"] += 1

        if not same:
            _import_exchange_row(conn, ep, now)
            stats["imported"] += 1
            continue

        keeper = max(same, key=lambda r: int(r["on_exchange"] or 0) * 1000 + int(r["id"]))
        conn.execute(
            """
            UPDATE positions SET
                entry_price=?, contracts=?, last_price=?, last_update=?,
                on_exchange=1, stake_usd=?, leverage=?
            WHERE id=?
            """,
            (
                net_entry,
                net_qty,
                mark,
                now,
                round(
                    net_qty * net_entry
                    / max(int(ep.get("leverage") or cfg.LEVERAGE_DEFAULT), 1),
                    2,
                ),
                int(ep.get("leverage") or cfg.LEVERAGE_DEFAULT),
                int(keeper["id"]),
            ),
        )
        stats["updated"] += 1
        for r in same:
            if int(r["id"]) != int(keeper["id"]) and close_local:
                _close_local_row(conn, r, now, "duplicate_merged")
                stats["closed"] += 1

    local_coins = set(by_coin.keys())
    for coin, ep in exch_by_coin.items():
        if coin in local_coins:
            continue
        _import_exchange_row(conn, ep, now)
        stats["imported"] += 1

    conn.commit()
    return stats


def _close_local_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    now: str,
    reason: str,
) -> None:
    entry = float(row["entry_price"])
    side = str(row["side"])
    contracts = float(row["contracts"])
    last = float(row["last_price"] or entry)
    from binance_futures_trader.fees import close_fee_breakdown

    entry_fee = float(row["entry_fee_usd"] or 0) if "entry_fee_usd" in row.keys() else 0.0
    fb = close_fee_breakdown(
        side=side,
        entry=entry,
        close=last,
        contracts=contracts,
        entry_fee=entry_fee,
    )
    pid = int(row["id"])
    strategies = str(row["strategies"] if "strategies" in row.keys() else "")
    conn.execute(
        """
        UPDATE positions SET closed_at=?, close_price=?, pnl_gross_usd=?, pnl_usd=?,
               entry_fee_usd=?, exit_fee_usd=?, funding_fee_usd=?, fees_usd=?,
               exit_reason=?, last_price=?, last_update=?
        WHERE id=?
        """,
        (
            now,
            last,
            fb["pnl_gross_usd"],
            fb["pnl_usd"],
            fb["entry_fee_usd"],
            fb["exit_fee_usd"],
            fb["funding_fee_usd"],
            fb["fees_usd"],
            reason,
            last,
            now,
            pid,
        ),
    )
    if cfg.LEARNING_ENABLED and strategies and strategies not in (
        "exchange_sync",
        "sync",
    ):
        try:
            from binance_futures_trader.learner import record_close

            record_close(
                conn,
                position_id=pid,
                coin=str(row["coin"]),
                side=side,
                exit_reason=reason,
                pnl_usd=fb["pnl_usd"],
                strategies=strategies,
                snapshot={"entry": entry, "close": last, "reason": reason, "sync": True},
            )
        except Exception:
            pass


def _import_exchange_row(
    conn: sqlite3.Connection,
    ep: dict,
    now: str,
) -> None:
    coin = str(ep["coin"])
    side = str(ep["side"])
    entry = float(ep["entry_price"])
    qty = float(ep["contracts"])
    lev = int(ep.get("leverage") or cfg.LEVERAGE_DEFAULT)
    stake = round(qty * entry / max(lev, 1), 2)
    conn.execute(
        """
        INSERT INTO positions (
            coin, side, entry_price, stake_usd, contracts, leverage,
            tp_frac, sl_frac, score, strategies, opened_at,
            leg_type, last_price, last_update, on_exchange, exchange_order_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            coin,
            side,
            entry,
            stake,
            qty,
            lev,
            cfg.TP_PCT,
            cfg.SL_PCT,
            0.0,
            "exchange_sync",
            now,
            "primary",
            float(ep.get("mark_price") or entry),
            now,
            1,
            "sync",
        ),
    )


def sync_status(
    conn: sqlite3.Connection,
    client: BinanceFuturesClient,
) -> dict:
    """Panel için drift özeti."""
    if client.paper:
        return {"in_sync": False, "paper": True, "exchange_count": 0, "local_count": 0, "drift": []}

    exch = client.exchange_positions()
    exch_map = {p["coin"]: p for p in exch}
    local = conn.execute(
        "SELECT id, coin, side, contracts, on_exchange, leg_type FROM positions WHERE closed_at IS NULL"
    ).fetchall()

    drift = []
    for r in local:
        coin = str(r["coin"])
        side = str(r["side"])
        ep = exch_map.get(coin)
        if ep is None:
            drift.append({"id": r["id"], "coin": coin, "side": side, "issue": "not_on_exchange"})
        elif str(ep["side"]) != side:
            drift.append({"id": r["id"], "coin": coin, "side": side, "issue": "netted_opposite"})
        elif abs(float(r["contracts"]) - float(ep["contracts"])) > max(0.001, float(ep["contracts"]) * 0.05):
            drift.append(
                {
                    "id": r["id"],
                    "coin": coin,
                    "side": side,
                    "issue": "qty_mismatch",
                    "local_qty": float(r["contracts"]),
                    "exchange_qty": float(ep["contracts"]),
                }
            )

    in_sync = len(drift) == 0 and len(local) == len(exch)
    return {
        "in_sync": in_sync,
        "paper": False,
        "exchange_count": len(exch),
        "local_count": len(local),
        "drift": drift,
    }
