"""8190 — az fırsat penceresinde sermayenin %50'sini az sayıda pozisyona dağıt."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone


def _enabled() -> bool:
    if os.getenv("ELITE_SPARSE_STAKE_ENABLED", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    port = (os.getenv("DASHBOARD_PORT") or "").strip()
    label = (os.getenv("SCENARIO_LABEL") or os.getenv("PROFILE_NAME") or "").strip()
    db = (os.getenv("PAPER_DB_PATH") or "").lower()
    return (
        port == "8190"
        or label == "elite_formula_8190_fresh"
        or "8190_fresh" in db
    )


def _window_minutes() -> float:
    try:
        return float(os.getenv("ELITE_SPARSE_WINDOW_MIN", "10"))
    except ValueError:
        return 10.0


def _min_opens_threshold() -> int:
    try:
        return int(os.getenv("ELITE_SPARSE_MIN_OPENS", "3"))
    except ValueError:
        return 3


def _capital_pct() -> float:
    try:
        return float(os.getenv("ELITE_SPARSE_CAPITAL_PCT", "0.50"))
    except ValueError:
        return 0.50


def _sparse_max_stake() -> float:
    raw = (os.getenv("ELITE_SPARSE_MAX_STAKE_USD") or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return float("inf")


def opens_in_window(conn: sqlite3.Connection, *, minutes: float | None = None) -> int:
    mins = minutes if minutes is not None else _window_minutes()
    since = (datetime.now(timezone.utc) - timedelta(minutes=mins)).isoformat()
    row = conn.execute(
        """
        SELECT COUNT(*) FROM positions
        WHERE opened_at >= ?
        """,
        (since,),
    ).fetchone()
    return int(row[0]) if row else 0


def stakes_in_window(conn: sqlite3.Connection, *, minutes: float | None = None) -> float:
    mins = minutes if minutes is not None else _window_minutes()
    since = (datetime.now(timezone.utc) - timedelta(minutes=mins)).isoformat()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(stake_usd), 0) FROM positions
        WHERE opened_at >= ?
        """,
        (since,),
    ).fetchone()
    return float(row[0]) if row else 0.0


def sparse_mode_active(conn: sqlite3.Connection) -> bool:
    if not _enabled():
        return False
    return opens_in_window(conn) < _min_opens_threshold()


def compute_sparse_stake(
    equity: float,
    conn: sqlite3.Connection,
    *,
    min_stake: float,
    max_stake: float,
) -> float | None:
    """
    Son N dakikada <3 açılış → kalan %50 bütçeyi kalan slotlara böl.
    Tek pozisyon: tüm %50 (max cap'e kadar).
    """
    if not sparse_mode_active(conn):
        return None

    threshold = _min_opens_threshold()
    opens = opens_in_window(conn)
    if opens >= threshold:
        return None

    budget = equity * _capital_pct()
    used = stakes_in_window(conn)
    remaining_budget = max(0.0, budget - used)
    # İlk açılış: tüm %50 havuz; 2./3. açılış: kalanı eşit böl
    if opens == 0:
        slots_left = 1
    else:
        slots_left = max(1, threshold - opens)

    stake = remaining_budget / slots_left
    cap = min(_max_stake_cap(max_stake), _sparse_max_stake())
    stake = max(min_stake, min(cap, stake))

    if stake <= 0 or remaining_budget < min_stake:
        return None
    return round(stake, 2)


def _max_stake_cap(max_stake: float) -> float:
    if max_stake <= 0:
        return float("inf")
    return max_stake


def status_line(conn: sqlite3.Connection, equity: float) -> str | None:
    if not _enabled():
        return None
    opens = opens_in_window(conn)
    if opens >= _min_opens_threshold():
        return None
    budget = equity * _capital_pct()
    used = stakes_in_window(conn)
    return (
        f"SPARSE {opens}/{_min_opens_threshold()} açılış "
        f"({_window_minutes():.0f}dk) | bütçe ${budget:.0f} kullanılan ${used:.0f}"
    )
