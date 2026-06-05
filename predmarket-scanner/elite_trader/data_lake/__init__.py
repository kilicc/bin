"""SQLite data lake — 6 tablo, mod erişim kuralları."""
from elite_trader.data_lake.access import can_query_mode
from elite_trader.data_lake.db import get_conn, init_db
from elite_trader.data_lake.ingest import (
    ingest_decision,
    ingest_live_trade,
    ingest_market_snapshot,
    ingest_meta_learning,
    ingest_mode_metrics,
    ingest_paper_trade,
    persist_all_mode_metrics,
    query_decisions,
    query_metrics,
    summary_for_ui,
)

__all__ = [
    "can_query_mode",
    "get_conn",
    "init_db",
    "ingest_decision",
    "ingest_live_trade",
    "ingest_market_snapshot",
    "ingest_meta_learning",
    "ingest_mode_metrics",
    "ingest_paper_trade",
    "persist_all_mode_metrics",
    "query_decisions",
    "query_metrics",
    "summary_for_ui",
]
