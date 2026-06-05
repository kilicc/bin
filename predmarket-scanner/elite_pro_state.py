"""Elite Pro (9005) kapanmış işlem kalıcılığı — restart sonrası win rate / geçmiş korunur."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent

# Logdan kurtarılan 9 kazanan işlem (%100 WR oturumu, restart öncesi)
SEED_WINS_9005: list[dict[str, Any]] = [
    {"id": 4, "symbol": "UBUSDT", "side": "LONG", "stake_usd": 772.0, "final_pnl": 6.68, "leverage": 3},
    {"id": 5, "symbol": "SXPUSDT", "side": "LONG", "stake_usd": 250.0, "final_pnl": 4.0, "leverage": 3},
    {"id": 6, "symbol": "SXTUSDT", "side": "SHORT", "stake_usd": 250.0, "final_pnl": 1.19, "leverage": 3},
    {"id": 8, "symbol": "WLFIUSDT", "side": "LONG", "stake_usd": 772.0, "final_pnl": 4.42, "leverage": 3},
    {"id": 10, "symbol": "SCRTUSDT", "side": "LONG", "stake_usd": 486.0, "final_pnl": 5.48, "leverage": 3},
    {"id": 11, "symbol": "COLLECTUSDT", "side": "SHORT", "stake_usd": 250.0, "final_pnl": 4.02, "leverage": 3},
    {"id": 12, "symbol": "SYSUSDT", "side": "SHORT", "stake_usd": 250.0, "final_pnl": 5.41, "leverage": 3},
    {"id": 13, "symbol": "PLAYUSDT", "side": "LONG", "stake_usd": 486.0, "final_pnl": 3.03, "leverage": 3},
    {"id": 14, "symbol": "MLNUSDT", "side": "LONG", "stake_usd": 486.0, "final_pnl": 3.1, "leverage": 3},
]


def state_db_path() -> Path:
    custom = os.environ.get("ELITE_STATE_DB", "").strip()
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else _ROOT / p
    port = os.environ.get("BINANCE_ELITE_PORT", "9003")
    profile = os.environ.get("PROFILE_NAME", f"elite_{port}")
    return _ROOT / "data" / f"{profile}_state.db"


def _connect() -> sqlite3.Connection:
    path = state_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS closed_trades (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                mode_id TEXT,
                payload TEXT NOT NULL,
                closed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(closed_trades)").fetchall()
        }
        if "mode_id" not in cols:
            conn.execute("ALTER TABLE closed_trades ADD COLUMN mode_id TEXT")
            conn.commit()


def _mode_from_row(closed: dict[str, Any]) -> str:
    from elite_trader.panel_strategy import active_execution_mode, resolve_mode_id

    return resolve_mode_id(
        str(
            closed.get("panel_mode")
            or closed.get("execution_mode_at_close")
            or closed.get("universe_id")
            or active_execution_mode()
        )
    )


def count_closed() -> int:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM closed_trades").fetchone()
        return int(row["n"]) if row else 0


def delete_closed_by_id(trade_id: int) -> dict[str, Any] | None:
    """Tek kapanmış işlemi sil; silinen payload döner."""
    init_db()
    tid = int(trade_id)
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload FROM closed_trades WHERE id = ?",
            (tid,),
        ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["payload"])
        except Exception:
            payload = {"id": tid}
        conn.execute("DELETE FROM closed_trades WHERE id = ?", (tid,))
        conn.commit()
        return payload


def clear_closed(mode_id: str | None = None) -> int:
    """Dahili — doğrudan silme. mode_id verilirse yalnızca o mod."""
    init_db()
    with _connect() as conn:
        if mode_id:
            n = conn.execute(
                "SELECT COUNT(*) FROM closed_trades WHERE mode_id = ?",
                (mode_id,),
            ).fetchone()[0]
            conn.execute(
                "DELETE FROM closed_trades WHERE mode_id = ?",
                (mode_id,),
            )
        else:
            n = conn.execute("SELECT COUNT(*) FROM closed_trades").fetchone()[0]
            conn.execute("DELETE FROM closed_trades")
        conn.commit()
        return int(n)


def archive_and_clear_closed(*, reason: str, trigger: str = "user") -> dict[str, Any]:
    """Önce arşivle, sonra DB kapanmış işlemleri sil."""
    from elite_trader.data_archive import archive_9005_bundle

    n = count_closed()
    meta = archive_9005_bundle(reason=reason, trigger=trigger)
    if n > 0:
        clear_closed()
    meta["cleared_closed_trades"] = n
    return meta


def _enrich_closed(row: dict[str, Any]) -> dict[str, Any]:
    """Panel / win-rate için minimum tam kayıt."""
    final = float(row.get("final_pnl") or 0)
    stake = float(row.get("stake_usd") or 250)
    net = final / 0.9 if final > 0 else final
    tax = max(0.0, net * 0.10)
    fees = max(0.5, abs(net - final) + stake * 0.0008)
    pnl_gross = net + fees * 0.5
    ts = row.get("exit_time") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id": int(row["id"]),
        "symbol": str(row["symbol"]),
        "side": str(row.get("side") or "LONG"),
        "entry_price": float(row.get("entry_price") or 0),
        "exit_price": float(row.get("exit_price") or 0),
        "size": float(row.get("size") or 0),
        "leverage": int(row.get("leverage") or 3),
        "stake_usd": stake,
        "pnl_usd": round(pnl_gross, 2),
        "pnl_pct": round((pnl_gross / stake) * 100, 2) if stake else 0,
        "entry_fee": round(fees * 0.4, 2),
        "exit_fee": round(fees * 0.6, 2),
        "total_fees": round(fees, 2),
        "net_pnl": round(net, 2),
        "net_pnl_pct": round((net / stake) * 100, 2) if stake else 0,
        "tax": round(tax, 2),
        "final_pnl": round(final, 2),
        "exit_reason": str(row.get("exit_reason") or "TP"),
        "entry_time": str(row.get("entry_time") or ts),
        "exit_time": ts,
        "duration": float(row.get("duration") or 0),
        "signal_strength": row.get("signal_strength") or "Medium",
        "restored_from_log": bool(row.get("restored_from_log")),
    }


def save_closed(closed: dict[str, Any], *, mode_id: str | None = None) -> None:
    init_db()
    mid = mode_id or _mode_from_row(closed)
    closed = dict(closed)
    closed.setdefault("panel_mode", mid)
    db_id = int(closed["id"])
    payload = json.dumps(closed, ensure_ascii=False)
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload FROM closed_trades WHERE id = ?",
            (db_id,),
        ).fetchone()
        if row:
            try:
                prev = json.loads(row["payload"])
            except json.JSONDecodeError:
                prev = {}
            if (
                str(prev.get("symbol") or "").upper()
                != str(closed.get("symbol") or "").upper()
            ):
                alt = conn.execute("SELECT MAX(id) AS m FROM closed_trades").fetchone()
                db_id = max(int(alt["m"] or 0), 9_000_000) + 1
        conn.execute(
            """
            INSERT OR REPLACE INTO closed_trades (id, symbol, mode_id, payload, closed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                db_id,
                str(closed["symbol"]),
                mid,
                payload,
                str(closed.get("exit_time") or datetime.now(timezone.utc).isoformat()),
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("last_save_ts", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def _backfill_mode_ids(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(closed_trades)").fetchall()}
    if "mode_id" not in cols:
        return
    nulls = conn.execute(
        "SELECT id, payload FROM closed_trades WHERE mode_id IS NULL OR mode_id = ''"
    ).fetchall()
    for r in nulls:
        try:
            p = json.loads(r["payload"])
            mid = _mode_from_row(p)
            conn.execute(
                "UPDATE closed_trades SET mode_id = ? WHERE id = ?",
                (mid, int(r["id"])),
            )
        except Exception:
            pass
    if nulls:
        conn.commit()


def load_closed(mode_id: str | None = None) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        _backfill_mode_ids(conn)
        if mode_id:
            rows = conn.execute(
                "SELECT payload FROM closed_trades WHERE mode_id = ? ORDER BY id ASC",
                (mode_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT payload FROM closed_trades ORDER BY id ASC"
            ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            out.append(json.loads(r["payload"]))
        except json.JSONDecodeError:
            continue
    return out


def max_closed_id(mode_id: str | None = None) -> int:
    init_db()
    with _connect() as conn:
        if mode_id:
            row = conn.execute(
                "SELECT MAX(id) AS m FROM closed_trades WHERE mode_id = ?",
                (mode_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT MAX(id) AS m FROM closed_trades").fetchone()
        return int(row["m"] or 0)


def import_seed_if_empty(seed: list[dict[str, Any]] | None = None) -> int:
    """DB boşsa logdan kurtarılan kazanan işlemleri yükle."""
    if count_closed() > 0:
        return 0
    seed = seed or SEED_WINS_9005
    n = 0
    for raw in seed:
        row = dict(raw)
        row["restored_from_log"] = True
        row["exit_reason"] = row.get("exit_reason") or "TP (log restore)"
        save_closed(_enrich_closed(row))
        n += 1
    return n


def import_closed_batch(
    rows: list[dict[str, Any]],
    *,
    merge: bool = True,
    overwrite: bool = False,
) -> int:
    """Toplu DB import — ayar dosyasına dokunmaz."""
    init_db()
    existing: dict[int, dict[str, Any]] = {}
    if merge and not overwrite:
        for r in load_closed():
            existing[int(r["id"])] = r
    n = 0
    for raw in rows:
        rid = int(raw["id"])
        if merge and not overwrite and rid in existing:
            continue
        if raw.get("net_pnl") is not None and raw.get("final_pnl") is not None:
            row = dict(raw)
            row.setdefault("restored_from_log", True)
        else:
            row = _enrich_closed({**raw, "restored_from_log": True})
        save_closed(row)
        n += 1
    return n


def bootstrap_closed(
    *,
    clear: bool = False,
    auto_seed: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """
    Uygulama açılışında: isteğe bağlı sil, yükle, boşsa seed.
    Returns (closed_list, next_position_id).
    """
    if clear:
        port = os.environ.get("BINANCE_ELITE_PORT", "")
        profile = os.environ.get("PROFILE_NAME", "")
        if port == "9005" or "9005" in profile or "8300_9005" in profile:
            reason = os.getenv("ELITE_CLEAR_REASON", "bootstrap_clear").strip()
            from elite_trader.data_archive import (
                archive_9005_bundle,
                remove_9005_files_after_archive,
            )

            archive_9005_bundle(reason=reason or "bootstrap_clear", trigger="code")
            removed = len(remove_9005_files_after_archive())
            print(f"  🗑 9005 veri arşivlendi ve silindi ({removed} dosya)")
        else:
            removed = clear_closed()
            if removed:
                print(f"  🗑 Kapanmış işlem geçmişi silindi ({removed} kayıt)")
    loaded = load_closed()
    if not loaded and auto_seed:
        seeded = import_seed_if_empty()
        if seeded:
            print(f"  📥 Logdan {seeded} kazanan işlem DB'ye geri yüklendi")
            loaded = load_closed()
    next_id = max(max_closed_id(), 0) + 1
    return loaded, next_id


def _closed_merge_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(row.get("id") or -1),
        str(row.get("symbol") or "").upper(),
        str(row.get("exit_time") or row.get("closed_at") or ""),
    )


def _load_closed_from_sqlite(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(db_path), timeout=10)
        try:
            rows = conn.execute("SELECT payload FROM closed_trades ORDER BY id ASC").fetchall()
        except sqlite3.OperationalError:
            return []
        for (payload,) in rows:
            try:
                out.append(json.loads(payload))
            except json.JSONDecodeError:
                continue
        conn.close()
    except Exception:
        return []
    return out


def ensure_cutover_closed_merged(mode_id: str = "berserk2") -> dict[str, Any]:
    """GCP taşıma öncesi yedek DB'den eksik kapalı işlemleri kitap + DB'ye ekle (idempotent)."""
    data_dir = _ROOT / "data"
    cutover_dbs = sorted(data_dir.glob("pre_gcp_cutover_*.db"), reverse=True)
    if not cutover_dbs:
        return {"ok": True, "merged_cutover": 0, "backfilled_db": 0, "reason": "no_cutover_db"}

    from elite_trader.parallel_universe_engine import get_universe_book, record_live_close

    book = get_universe_book(mode_id)
    existing_keys = {_closed_merge_key(c) for c in (book.get("closed") or [])}

    merged = 0
    for cutover_path in cutover_dbs[:2]:
        for row in _load_closed_from_sqlite(cutover_path):
            key = _closed_merge_key(row)
            if key in existing_keys:
                continue
            r = dict(row)
            r.setdefault("restored_from_cutover", True)
            r.setdefault("panel_mode", mode_id)
            record_live_close(mode_id, r)
            save_closed(r, mode_id=mode_id)
            existing_keys.add(key)
            merged += 1

    backfilled = 0
    db_keys = {_closed_merge_key(r) for r in load_closed(mode_id)}
    book = get_universe_book(mode_id)
    for row in book.get("closed") or []:
        k = _closed_merge_key(row)
        if k in db_keys:
            continue
        save_closed(dict(row), mode_id=mode_id)
        db_keys.add(k)
        backfilled += 1

    if merged or backfilled:
        print(
            f"  📥 Cutover birleştirme: +{merged} kitap/DB | "
            f"DB backfill: {backfilled} (mode={mode_id})"
        )
    return {
        "ok": True,
        "merged_cutover": merged,
        "backfilled_db": backfilled,
        "cutover_db": str(cutover_dbs[0]),
    }
