"""Elite tarayıcı giriş/kapanış korumaları — korelasyon, bracket, min tutma."""
from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime, timezone

import momentum_scanner as ms

_BOX_OFFICE_RE = re.compile(r'"([^"]{2,40})".*box office', re.IGNORECASE)
_BRACKET_RE = re.compile(
    r"\b(between|greater than|less than|at least|at most|"
    r"dip to|rise to|above \$|below \$|up or down)\b",
    re.IGNORECASE,
)
_TAIL_STRIKE_RE = re.compile(
    r"\b(dip to|above|below|between|greater than|less than|up or down on)\b",
    re.IGNORECASE,
)


def event_cluster_key(question: str) -> str:
    """Aynı olay farklı market metinleri — Michael bracket, BTC May 16, vb."""
    q = (question or "").strip()
    ql = q.lower()
    m = _BOX_OFFICE_RE.search(q)
    if m:
        return f"boxoffice:{m.group(1).strip().lower()}"
    if "box office" in ql:
        base = ql.split("box office")[0].strip()[:48]
        if len(base) > 8:
            return f"boxoffice:{base}"
    ck = ms._corr_key(q)
    if len(ck) >= 2:
        return "corr:" + "|".join(sorted(ck))
    ek = ms._live_event_key(q)
    if len(ek) >= 12:
        return f"ev:{ek}"
    return f"q:{ql[:56]}"


def is_bracket_or_strike_market(question: str) -> bool:
    """Çoklu sonuç / strike — aynı olaya yığın ve whipsaw riski."""
    if not question:
        return False
    ql = question.lower()
    if _BRACKET_RE.search(ql):
        return True
    if ms._is_crypto_strike_market(question):
        return True
    if any(a in ql for a in ms._CRYPTO_ASSETS) and _TAIL_STRIKE_RE.search(ql):
        return True
    return False


def entry_price_ok(side: str, entry_price: float) -> bool:
    """Ucuz kuyruk (23¢) — gürültüde anında SL."""
    try:
        lo = float(os.getenv("ELITE_MIN_ENTRY_PRICE", "0.32"))
        hi = float(os.getenv("ELITE_MAX_ENTRY_PRICE", "0.68"))
    except ValueError:
        lo, hi = 0.32, 0.68
    p = entry_price
    return lo <= p <= hi


def cluster_open(
    conn: sqlite3.Connection,
    question: str,
    *,
    extra_open: set[str] | None = None,
) -> bool:
    """Bu olay kümesinde zaten açık pozisyon var mı?"""
    if os.getenv("ELITE_ONE_CLUSTER", "1").strip().lower() not in ("1", "true", "yes"):
        return False
    key = event_cluster_key(question)
    if len(key) < 8:
        return False
    if extra_open and key in extra_open:
        return True
    for row in conn.execute(
        "SELECT question FROM positions WHERE closed_at IS NULL"
    ):
        if event_cluster_key(row["question"] or "") == key:
            return True
    return False


def market_on_cooldown(
    conn: sqlite3.Connection,
    market_id: str,
    question: str,
) -> bool:
    """Aynı market veya cluster — yakın zamanda SL / kapanış."""
    try:
        cd_min = int(os.getenv("ELITE_MARKET_COOLDOWN_MIN", "45"))
    except ValueError:
        cd_min = 45
    if cd_min <= 0:
        return False
    cutoff = datetime.now(timezone.utc).timestamp() - cd_min * 60
    cluster = event_cluster_key(question)
    for row in conn.execute(
        """
        SELECT market_id, question, closed_at, exit_reason
        FROM positions
        WHERE closed_at IS NOT NULL
        ORDER BY closed_at DESC
        LIMIT 80
        """
    ):
        try:
            ts = datetime.fromisoformat(
                str(row["closed_at"]).replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            continue
        if ts < cutoff:
            continue
        if str(row["market_id"]) == str(market_id):
            from elite_trader.stale_tp import exit_reason_blocks_reopen

            if exit_reason_blocks_reopen(row["exit_reason"]):
                continue
            return True
        if event_cluster_key(row["question"] or "") == cluster:
            ex = (row["exit_reason"] or "").upper()
            if ex.startswith("SL") or "SL" in ex:
                return True
    return False


def min_hold_seconds() -> int:
    try:
        return int(os.getenv("ELITE_MIN_HOLD_BEFORE_SL_SEC", "300"))
    except ValueError:
        return 300


def can_trigger_sl(
    opened_at: str | None,
    *,
    unrealized_usd: float = 0.0,
    sl_target_usd: float = 0.0,
) -> bool:
    """
    Planlı SL hedefine ulaşıldıysa bekleme yok (anında kapat).
    Hedefe ulaşılmadıysa: kısa min-hold ile gürültü SL engeli.
    """
    if sl_target_usd > 0 and unrealized_usd <= -sl_target_usd:
        return True
    if not opened_at:
        return True
    hold = min_hold_seconds()
    if hold <= 0:
        return True
    try:
        opened = datetime.fromisoformat(str(opened_at).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - opened).total_seconds()
        return age >= hold
    except Exception:
        return True


def should_veto_entry(
    conn: sqlite3.Connection,
    question: str,
    market_id: str,
    side: str,
    entry_price: float,
    *,
    opened_clusters: set[str] | None = None,
) -> str | None:
    """Veto nedeni veya None (giriş OK)."""
    if not entry_price_ok(side, entry_price):
        return "entry_price_band"
    if is_bracket_or_strike_market(question) and os.getenv(
        "ELITE_VETO_BRACKETS", "1"
    ).strip().lower() in ("1", "true", "yes"):
        return "bracket_strike"
    if ms._is_correlated_position(conn, question):
        return "correlated_asset_date"
    if ms._same_event_open(conn, question):
        return "same_event"
    if cluster_open(conn, question, extra_open=opened_clusters):
        return "event_cluster"
    if market_on_cooldown(conn, market_id, question):
        return "market_cooldown"
    return None
