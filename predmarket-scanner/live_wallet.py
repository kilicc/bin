"""Polymarket CLOB collateral — dashboard ve canlı tarayıcı için (paper.db'ye dokunmaz)."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"

_cache: dict[str, Any] = {"ts": 0.0, "payload": None}
_CACHE_TTL = float(os.getenv("POLY_WALLET_CACHE_SEC", "25"))


def get_collateral_usdc() -> float | None:
    """CLOB USDC collateral (6 ondalık → USD). Anahtar yoksa None."""
    try:
        import live_clob as lc

        client = lc.build_trading_client()
        if client is None:
            return None
        return lc.get_collateral_usdc(client)
    except Exception:
        return None


def fetch_wallet_snapshot() -> dict[str, Any]:
    """Dashboard için cache'li cüzdan özeti."""
    now = time.time()
    if _cache["payload"] is not None and (now - float(_cache["ts"])) < _CACHE_TTL:
        return dict(_cache["payload"])

    usdc = get_collateral_usdc()
    armed = os.getenv("POLYMARKET_LIVE_TRADING", "0").strip().lower() in ("1", "true", "yes")
    confirm = os.getenv("POLYMARKET_LIVE_CONFIRM", "").strip() == "I_UNDERSTAND_REAL_MONEY_LOSS"
    payload = {
        "configured": bool((os.getenv("POLYMARKET_PRIVATE_KEY") or "").strip()),
        "live_armed": armed and confirm,
        "usdc": round(usdc, 2) if usdc is not None else None,
        "deposit_wallet": (os.getenv("POLYMARKET_DEPOSIT_WALLET") or "").strip() or None,
        "signer": (os.getenv("SIGNER_ADDRESS") or os.getenv("RELAYER_API_KEY_ADDRESS") or "").strip() or None,
        "max_position_usd": float(os.getenv("MAX_POSITION_USD", "2")),
    }
    _cache["ts"] = now
    _cache["payload"] = payload
    return dict(payload)


def read_live_db_summary() -> dict[str, Any] | None:
    """data/live.db özeti — panel paper equity'yi değiştirmez."""
    path = Path(os.getenv("LIVE_DB_PATH", str(DATA_DIR / "live.db")))
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        open_n = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE closed_at IS NULL"
        ).fetchone()[0]
        agg = conn.execute(
            """SELECT COUNT(*) n, COALESCE(SUM(pnl_usd),0) pnl
               FROM positions WHERE closed_at IS NOT NULL
                 AND ABS(COALESCE(pnl_usd,0)) > 0.0001"""
        ).fetchone()
        conn.close()
        return {
            "db_path": str(path.name),
            "open_trades": int(open_n),
            "closed_trades": int(agg["n"]),
            "realized_pnl": round(float(agg["pnl"]), 4),
        }
    except Exception:
        return None
