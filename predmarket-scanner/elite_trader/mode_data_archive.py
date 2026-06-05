"""Mod başına işlem arşivi ve bakiye/geçmiş sıfırlama."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.panel_strategy import mode_catalog, mode_order, resolve_mode_id
from elite_trader.parallel_universe_engine import (
    all_mode_ids,
    get_books,
    get_universe_book,
    reset_mode_book,
)

_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_ROOT = _ROOT / "data" / "mode_archives"
MANIFEST_PATH = ARCHIVE_ROOT / "manifest.json"
_LIVE_DB = _ROOT / "data" / "binance_elite_8300_9005_state.db"
_PARALLEL_STATE = _ROOT / "data" / "parallel_universes.json"

_ALL_MODES = tuple(mode_order())
_PARALLEL = set(all_mode_ids())
# Eski Ana Hat DB — canlı işlemler evrim motorunda
_LEGACY_LIVE_MODE = "evrim"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(s: str, max_len: int = 36) -> str:
    t = re.sub(r"[^a-zA-Z0-9]+", "_", (s or "no_reason").strip())[:max_len]
    return t.strip("_") or "no_reason"


def normalize_mode_id(mode_id: str | None) -> str:
    mid = (mode_id or "").strip()
    if mid in mode_catalog():
        return mid
    raise ValueError(f"Bilinmeyen mod: {mode_id}")


def _mode_label(mode_id: str) -> str:
    cat = mode_catalog()
    if mode_id in cat:
        return cat[mode_id].get("short_label") or cat[mode_id].get("label") or mode_id
    return mode_id


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        return {"archives": [], "updated_at": None}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"archives": [], "updated_at": None}


def _save_manifest(data: dict[str, Any]) -> None:
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    archives = data.get("archives") or []
    if len(archives) > 200:
        data["archives"] = archives[-200:]
    MANIFEST_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _collect_mode_trades(mode_id: str) -> dict[str, Any]:
    """Anlık mod kitabı (canlı için dışarıdan open/closed verilebilir)."""
    if mode_id in _PARALLEL:
        book = get_universe_book(mode_id)
        return {
            "open": list(book.get("open") or []),
            "closed": list(book.get("closed") or []),
        }
    book = get_universe_book(_LEGACY_LIVE_MODE)
    return {"open": list(book.get("open") or []), "closed": list(book.get("closed") or [])}


def collect_live_trades(
    *,
    open_positions: list[dict[str, Any]],
    closed_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {"open": list(open_positions), "closed": list(closed_positions)}


def archive_mode(
    mode_id: str,
    *,
    reason: str,
    trigger: str = "panel",
    live_trades: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mid = normalize_mode_id(mode_id)
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    archive_id = f"{mid}_{stamp}_{_slug(reason)}"
    dest = ARCHIVE_ROOT / archive_id
    dest.mkdir(parents=True, exist_ok=True)

    if live_trades is not None and mid == _LEGACY_LIVE_MODE:
        trades = live_trades
    else:
        trades = _collect_mode_trades(mid)

    trades_path = dest / "trades.json"
    trades_path.write_text(
        json.dumps(trades, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    files_meta: list[dict[str, Any]] = [
        {
            "label": "trades_json",
            "file": "trades.json",
            "bytes": trades_path.stat().st_size,
            "open_n": len(trades.get("open") or []),
            "closed_n": len(trades.get("closed") or []),
        }
    ]

    if mid == _LEGACY_LIVE_MODE and _LIVE_DB.is_file():
        db_copy = dest / _LIVE_DB.name
        shutil.copy2(_LIVE_DB, db_copy)
        extra: dict[str, Any] = {"label": "state_db", "file": db_copy.name}
        try:
            conn = sqlite3.connect(str(db_copy))
            n = conn.execute("SELECT COUNT(*) FROM closed_trades").fetchone()[0]
            conn.close()
            extra["closed_trades_count"] = int(n)
        except Exception:
            extra["closed_trades_count"] = len(trades.get("closed") or [])
        files_meta.append(extra)
    elif mid in _PARALLEL and _PARALLEL_STATE.is_file():
        shutil.copy2(_PARALLEL_STATE, dest / "parallel_universes_snapshot.json")
        files_meta.append(
            {
                "label": "parallel_snapshot",
                "file": "parallel_universes_snapshot.json",
                "bytes": (dest / "parallel_universes_snapshot.json").stat().st_size,
            }
        )

    closed_n = len(trades.get("closed") or [])
    meta = {
        "archive_id": archive_id,
        "mode_id": mid,
        "mode_label": _mode_label(mid),
        "is_live": mid == _LEGACY_LIVE_MODE,
        "archived_at": _now_iso(),
        "reason": (reason or "").strip() or "(neden belirtilmedi)",
        "trigger": trigger,
        "path": str(dest.relative_to(_ROOT)),
        "files": files_meta,
        "closed_trades_count": closed_n,
        "open_trades_count": len(trades.get("open") or []),
    }
    (dest / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = _load_manifest()
    manifest.setdefault("archives", []).append(meta)
    _save_manifest(manifest)
    return meta


def list_mode_archives(
    mode_id: str | None = None,
    *,
    limit: int = 30,
    include_legacy_live: bool = True,
) -> list[dict[str, Any]]:
    """Mod filtresi + eski global 9005 arşivleri (yalnızca Ana Hat görünümünde)."""
    out: list[dict[str, Any]] = []
    mid = (mode_id or "").strip() or None

    for a in _load_manifest().get("archives") or []:
        if mid and a.get("mode_id") != mid:
            continue
        out.append(
            {
                "archive_id": a.get("archive_id"),
                "mode_id": a.get("mode_id"),
                "mode_label": a.get("mode_label"),
                "archived_at": a.get("archived_at") or a.get("deleted_at"),
                "reason": a.get("reason"),
                "trigger": a.get("trigger"),
                "closed_trades_count": a.get("closed_trades_count"),
                "open_trades_count": a.get("open_trades_count"),
                "is_live": a.get("is_live"),
            }
        )

    if include_legacy_live and (mid is None or mid == _LEGACY_LIVE_MODE):
        try:
            from elite_trader.data_archive import list_archives as legacy_list

            for a in legacy_list(limit=limit):
                out.append(
                    {
                        "archive_id": a.get("archive_id"),
                        "mode_id": _LEGACY_LIVE_MODE,
                        "mode_label": _mode_label(_LEGACY_LIVE_MODE),
                        "archived_at": a.get("deleted_at"),
                        "reason": a.get("reason"),
                        "trigger": a.get("trigger"),
                        "closed_trades_count": a.get("closed_trades_count"),
                        "legacy": True,
                        "is_live": True,
                    }
                )
        except Exception:
            pass

    out.sort(key=lambda x: x.get("archived_at") or "", reverse=True)
    return out[:limit]


def archive_detail_mode(archive_id: str) -> dict[str, Any] | None:
    aid = (archive_id or "").strip()
    dest = ARCHIVE_ROOT / aid
    if not dest.is_dir():
        from elite_trader.data_archive import archive_detail as legacy_detail

        leg = legacy_detail(aid)
        if leg:
            leg["mode_id"] = _LEGACY_LIVE_MODE
            leg["legacy"] = True
        return leg

    meta_path = dest / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    trades: list[dict[str, Any]] = []
    tj = dest / "trades.json"
    if tj.is_file():
        try:
            data = json.loads(tj.read_text(encoding="utf-8"))
            trades = list(data.get("closed") or [])
        except Exception:
            trades = []

    if not trades and meta.get("is_live"):
        db = dest / _LIVE_DB.name
        if db.is_file():
            try:
                conn = sqlite3.connect(str(db))
                rows = conn.execute(
                    "SELECT payload FROM closed_trades ORDER BY id ASC"
                ).fetchall()
                conn.close()
                for r in rows:
                    try:
                        trades.append(json.loads(r[0]))
                    except json.JSONDecodeError:
                        continue
            except Exception:
                pass

    wins = sum(1 for t in trades if float(t.get("final_pnl") or 0) > 0)
    return {
        "ok": True,
        "meta": meta,
        "closed_trades": trades,
        "summary": {
            "count": len(trades),
            "wins": wins,
            "losses": len(trades) - wins,
            "total_final_pnl": round(
                sum(float(t.get("final_pnl") or 0) for t in trades), 2
            ),
        },
    }


def close_binance_exchange_positions() -> dict[str, Any]:
    """Demo/canlı Binance Futures — tüm açık pozisyonları reduce-only kapat."""
    import os

    os.environ.setdefault("BN_FUT_MODE", "testnet")
    from binance_futures_trader import config as cfg
    import importlib

    importlib.reload(cfg)
    from binance_futures_trader.client import BinanceFuturesClient

    c = BinanceFuturesClient()
    if c.paper:
        return {
            "ok": True,
            "closed_n": 0,
            "skipped": True,
            "message": "API paper modunda — borsa kapanışı atlandı",
        }

    closed: list[str] = []
    for ep in c.exchange_positions():
        coin = ep["coin"]
        side = "SHORT" if ep["side"] == "LONG" else "LONG"
        qty = c.round_qty(coin, float(ep["contracts"]))
        if qty > 0:
            c.market_order(coin, side, qty, reduce_only=True)
            closed.append(f"{ep['symbol']} {ep['side']} qty={qty}")
            time.sleep(0.2)

    wallet: dict[str, Any] = {}
    try:
        wallet = c.exchange_wallet() or {}
    except Exception:
        pass

    bal = float(
        wallet.get("total_margin_balance")
        or wallet.get("total_wallet_balance")
        or 0
    )
    avail = float(wallet.get("available_balance") or bal)
    return {
        "ok": True,
        "closed_n": len(closed),
        "closed": closed,
        "balance_usd": round(bal, 2),
        "available_usd": round(avail, 2),
        "message": (
            f"{len(closed)} borsa pozisyonu kapatıldı · bakiye ${bal:,.2f}"
            if closed
            else f"Borsada açık pozisyon yok · bakiye ${bal:,.2f}"
        ),
    }


def reset_parallel_universe(mode_id: str) -> dict[str, Any]:
    mid = normalize_mode_id(mode_id)
    out = reset_mode_book(mid)
    if mid == _LEGACY_LIVE_MODE:
        try:
            from elite_pro_state import clear_closed

            out["db_cleared"] = clear_closed(_LEGACY_LIVE_MODE)
        except Exception:
            out["db_cleared"] = 0
    out["starting_capital"] = out.get("session_start", 5000)
    return out


def reset_live_memory(
    *,
    positions: list[dict[str, Any]],
    closed_positions: list[dict[str, Any]],
    position_id_counter: int,
    wipe_db: bool = True,
) -> dict[str, Any]:
    """Ana Hat kitabı + motor bellek; tüm DB silinmez (mode_id=sentinel)."""
    o_n = len(positions)
    c_n = len(closed_positions)
    positions.clear()
    closed_positions.clear()
    book_out = reset_mode_book(_LEGACY_LIVE_MODE)
    removed_db = 0
    if wipe_db:
        try:
            from elite_pro_state import clear_closed

            removed_db = clear_closed(_LEGACY_LIVE_MODE)
        except Exception:
            pass
    return {
        "cleared_open": o_n + int(book_out.get("cleared_open") or 0),
        "cleared_closed": c_n + int(book_out.get("cleared_closed") or 0),
        "db_removed": removed_db > 0,
        "db_rows_cleared": removed_db,
        "next_id": 1,
    }
