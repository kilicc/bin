"""Data lake ingest + sorgular."""
from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any

from elite_trader.data_lake.access import assert_can_query
from elite_trader.data_lake.db import get_conn, init_db, queue_write
from elite_trader.mode_registry import MODE_IDS, resolve_mode_id

init_db()


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def ingest_market_snapshot(
    symbol: str,
    price: float,
    *,
    change_pct: float = 0.0,
    regime: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    # Kuyruğa ekle — yüksek frekanslı çağrıda senkron commit yok
    queue_write(
        """INSERT INTO market_snapshots (ts, symbol, price, change_pct, regime, payload_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (time.time(), symbol, price, change_pct, regime, _j(extra or {})),
    )


def ingest_decision(
    mode_id: str,
    *,
    symbol: str = "",
    side: str = "",
    allowed: bool,
    reason: str = "",
    signal_passed: bool | None = None,
    risk_passed: bool | None = None,
    execution_passed: bool | None = None,
    order_sent: bool | None = None,
    exchange_accepted: bool | None = None,
    execution_path: str = "paper",
    extra: dict[str, Any] | None = None,
) -> None:
    mid = resolve_mode_id(mode_id)
    # Kuyruğa ekle — yüksek frekanslı çağrıda senkron commit yok
    queue_write(
        """INSERT INTO mode_decisions
           (ts, mode_id, symbol, side, allowed, reason,
            signal_passed, risk_passed, execution_passed, order_sent,
            exchange_accepted, execution_path, payload_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            time.time(),
            mid,
            symbol,
            side,
            1 if allowed else 0,
            reason[:240],
            None if signal_passed is None else int(signal_passed),
            None if risk_passed is None else int(risk_passed),
            None if execution_passed is None else int(execution_passed),
            None if order_sent is None else int(order_sent),
            None if exchange_accepted is None else int(exchange_accepted),
            execution_path,
            _j(extra or {}),
        ),
    )


def ingest_paper_trade(mode_id: str, trade: dict[str, Any], *, closing: bool = False) -> None:
    mid = resolve_mode_id(mode_id)
    if closing:
        queue_write(
            """INSERT INTO paper_trades
               (ts_open, ts_close, mode_id, symbol, side, stake_usd, pnl_usd,
                exit_reason, order_sent, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (
                trade.get("opened_at_ts") or time.time() - 60,
                time.time(),
                mid,
                trade.get("symbol"),
                trade.get("side") or trade.get("type"),
                float(trade.get("stake_usd") or 0),
                float(trade.get("final_pnl") or trade.get("net_pnl") or 0),
                str(trade.get("exit_reason") or "")[:48],
                _j(trade),
            ),
        )
    else:
        queue_write(
            """INSERT INTO paper_trades
               (ts_open, mode_id, symbol, side, stake_usd, order_sent, payload_json)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (
                time.time(),
                mid,
                trade.get("symbol"),
                trade.get("side") or trade.get("type"),
                float(trade.get("stake_usd") or 0),
                _j(trade),
            ),
        )


def ingest_live_trade(
    mode_id: str,
    trade: dict[str, Any],
    *,
    closing: bool = False,
    active_futures_mode: str | None = None,
) -> None:
    mid = resolve_mode_id(mode_id)
    if active_futures_mode is not None:
        active = resolve_mode_id(active_futures_mode)
        if mid != active:
            raise PermissionError(
                f"live trade for {mid} blocked: active_futures_mode is {active}"
            )
    conn = get_conn()
    conn.execute(
        """INSERT INTO live_trades
           (ts_open, ts_close, mode_id, symbol, side, stake_usd, pnl_usd,
            exit_reason, order_sent, exchange_accepted, on_exchange, payload_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
        (
            trade.get("opened_at_ts") or time.time() - 60,
            time.time() if closing else None,
            mid,
            trade.get("symbol"),
            trade.get("side") or trade.get("type"),
            float(trade.get("stake_usd") or 0),
            float(trade.get("final_pnl") or trade.get("pnl_usd") or 0) if closing else None,
            str(trade.get("exit_reason") or "")[:48] if closing else None,
            1 if trade.get("exchange_accepted") else 0,
            1 if trade.get("on_exchange") else 0,
            _j(trade),
        ),
    )
    conn.commit()


def ingest_mode_metrics(mode_id: str, metrics: dict[str, Any]) -> None:
    mid = resolve_mode_id(mode_id)
    conn = get_conn()
    conn.execute(
        """INSERT INTO mode_metrics
           (ts, mode_id, trades, wins, profit_factor, win_rate,
            fee_gross_ratio, pnl_per_min, top_reject_json, payload_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            time.time(),
            mid,
            metrics.get("trades"),
            metrics.get("wins"),
            metrics.get("profit_factor"),
            metrics.get("win_rate"),
            metrics.get("fee_gross_ratio"),
            metrics.get("pnl_per_min"),
            _j(metrics.get("top_rejects") or []),
            _j(metrics),
        ),
    )
    conn.commit()


# Aşama 1 MD: 32 zorunlu log alanı
_DECISION_LOG_COLS = (
    "ts", "mode_id", "mode_name", "active_futures_mode",
    "symbol", "side", "market_regime",
    "score_total", "score_breakdown",
    "entry_reason", "reject_reason", "veto_reason", "risk_level",
    "expected_net_pnl", "spread", "slippage_estimate", "expected_fee", "expected_funding",
    "order_route", "is_paper", "order_sent", "exchange_accepted",
    "entry_price", "exit_price", "gross_pnl", "fee", "funding", "net_pnl",
    "hold_time", "result", "learning_tag", "payload_json",
)


def _b(v: Any) -> int | None:
    if v is None:
        return None
    return 1 if bool(v) else 0


def ingest_decision_log(
    mode_id: str,
    *,
    mode_name: str = "",
    active_futures_mode: str = "",
    symbol: str = "",
    side: str = "",
    market_regime: str = "",
    score_total: float = 0.0,
    score_breakdown: Any = None,
    entry_reason: str = "",
    reject_reason: str = "",
    veto_reason: str = "",
    risk_level: str = "",
    expected_net_pnl: float = 0.0,
    spread: float = 0.0,
    slippage_estimate: float = 0.0,
    expected_fee: float = 0.0,
    expected_funding: float = 0.0,
    order_route: str = "",
    is_paper: bool | None = None,
    order_sent: bool | None = None,
    exchange_accepted: bool | None = None,
    entry_price: float | None = None,
    exit_price: float | None = None,
    gross_pnl: float | None = None,
    fee: float | None = None,
    funding: float | None = None,
    net_pnl: float | None = None,
    hold_time: float | None = None,
    result: str = "",
    learning_tag: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    """MD 32 alanını decision_log tablosuna açık kolon olarak yaz."""
    mid = resolve_mode_id(mode_id)
    conn = get_conn()
    placeholders = ", ".join("?" for _ in _DECISION_LOG_COLS)
    cols_sql = ", ".join(_DECISION_LOG_COLS)
    score_breakdown_str = (
        _j(score_breakdown) if isinstance(score_breakdown, (dict, list)) else str(score_breakdown or "")
    )
    payload = dict(extra or {})
    conn.execute(
        f"INSERT INTO decision_log ({cols_sql}) VALUES ({placeholders})",
        (
            time.time(),
            mid,
            str(mode_name or "")[:80],
            str(active_futures_mode or "")[:32],
            str(symbol or "")[:32],
            str(side or "")[:16],
            str(market_regime or "")[:48],
            float(score_total or 0),
            score_breakdown_str[:2000],
            str(entry_reason or "")[:240],
            str(reject_reason or "")[:240],
            str(veto_reason or "")[:240],
            str(risk_level or "")[:32],
            float(expected_net_pnl or 0),
            float(spread or 0),
            float(slippage_estimate or 0),
            float(expected_fee or 0),
            float(expected_funding or 0),
            str(order_route or "")[:32],
            _b(is_paper),
            _b(order_sent),
            _b(exchange_accepted),
            None if entry_price is None else float(entry_price),
            None if exit_price is None else float(exit_price),
            None if gross_pnl is None else float(gross_pnl),
            None if fee is None else float(fee),
            None if funding is None else float(funding),
            None if net_pnl is None else float(net_pnl),
            None if hold_time is None else float(hold_time),
            str(result or "")[:32],
            str(learning_tag or "")[:120],
            _j(payload),
        ),
    )
    conn.commit()


def query_decision_log(
    mode_id: str,
    *,
    reader_id: str = "evrim",
    limit: int = 100,
    only_rejects: bool = False,
) -> list[dict[str, Any]]:
    mid = resolve_mode_id(mode_id)
    assert_can_query(reader_id, mid)
    conn = get_conn()
    where = "mode_id = ?"
    params: list[Any] = [mid]
    if only_rejects:
        where += " AND (reject_reason != '' OR veto_reason != '')"
    rows = conn.execute(
        f"SELECT * FROM decision_log WHERE {where} ORDER BY id DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def reject_summary(mode_id: str, *, reader_id: str = "evrim", limit: int = 500) -> list[dict[str, Any]]:
    mid = resolve_mode_id(mode_id)
    assert_can_query(reader_id, mid)
    conn = get_conn()
    rows = conn.execute(
        """SELECT reject_reason, veto_reason FROM decision_log
           WHERE mode_id = ? AND (reject_reason != '' OR veto_reason != '')
           ORDER BY id DESC LIMIT ?""",
        (mid, limit),
    ).fetchall()
    c: Counter[str] = Counter()
    for r in rows:
        rej = (r["reject_reason"] or "").strip() or (r["veto_reason"] or "").strip()
        if rej:
            c[rej[:64]] += 1
    return [{"reason": k, "count": v} for k, v in c.most_common(10)]


def route_distribution(mode_id: str, *, reader_id: str = "evrim", limit: int = 1000) -> dict[str, int]:
    mid = resolve_mode_id(mode_id)
    assert_can_query(reader_id, mid)
    conn = get_conn()
    rows = conn.execute(
        """SELECT order_route, COUNT(*) AS n FROM decision_log
           WHERE mode_id = ? GROUP BY order_route""",
        (mid,),
    ).fetchall()
    return {(r["order_route"] or "unknown"): int(r["n"]) for r in rows}


def learning_record_count(mode_id: str, *, reader_id: str = "evrim") -> int:
    mid = resolve_mode_id(mode_id)
    assert_can_query(reader_id, mid)
    conn = get_conn()
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM decision_log
           WHERE mode_id = ? AND learning_tag != ''""",
        (mid,),
    ).fetchone()
    return int(row["n"]) if row else 0


def ingest_meta_learning(cycle: int, summary: dict[str, Any], proposals: dict[str, Any]) -> None:
    queue_write(
        """INSERT INTO evrim_meta_learning (ts, cycle, summary_json, proposals_json)
           VALUES (?, ?, ?, ?)""",
        (time.time(), cycle, _j(summary), _j(proposals)),
    )


def query_decisions(
    mode_id: str,
    *,
    reader_id: str = "evrim",
    limit: int = 100,
) -> list[dict[str, Any]]:
    mid = resolve_mode_id(mode_id)
    assert_can_query(reader_id, mid)
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM mode_decisions WHERE mode_id = ?
           ORDER BY id DESC LIMIT ?""",
        (mid, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def query_metrics(mode_id: str, *, reader_id: str = "evrim", limit: int = 20) -> list[dict[str, Any]]:
    mid = resolve_mode_id(mode_id)
    assert_can_query(reader_id, mid)
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM mode_metrics WHERE mode_id = ?
           ORDER BY id DESC LIMIT ?""",
        (mid, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _rollup_mode(mode_id: str) -> dict[str, Any]:
    from elite_trader.data_lake.db import db_session

    mid = resolve_mode_id(mode_id)
    with db_session() as conn:
        dec = conn.execute(
            """SELECT allowed, reason FROM mode_decisions
               WHERE mode_id = ? ORDER BY id DESC LIMIT 500""",
            (mid,),
        ).fetchall()
        rejects = Counter(
            str(r["reason"] or "unknown") for r in dec if not int(r["allowed"])
        )
        pt = conn.execute(
            """SELECT pnl_usd FROM paper_trades
               WHERE mode_id = ? AND pnl_usd IS NOT NULL ORDER BY id DESC LIMIT 200""",
            (mid,),
        ).fetchall()
        pnls = [float(r["pnl_usd"]) for r in pt if r["pnl_usd"] is not None]
        wins = sum(1 for p in pnls if p > 0)
        gross_win = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0)) or 1e-9
        fee_sum = 0.0
        gross_abs = gross_win + gross_loss
        try:
            fee_rows = conn.execute(
                """SELECT payload_json FROM paper_trades
                   WHERE mode_id = ? AND pnl_usd IS NOT NULL ORDER BY id DESC LIMIT 100""",
                (mid,),
            ).fetchall()
            for fr in fee_rows:
                try:
                    p = json.loads(fr["payload_json"] or "{}")
                    fee_sum += float(p.get("total_fees") or 0)
                except Exception:
                    pass
        except Exception:
            pass
    fee_gross = round(fee_sum / gross_abs, 3) if gross_abs > 1e-6 else 0.0
    return {
        "mode_id": mid,
        "decisions": len(dec),
        "profit_factor": round(gross_win / gross_loss, 3) if pnls else 0.0,
        "win_rate": round(wins / len(pnls), 3) if pnls else 0.0,
        "trades": len(pnls),
        "fee_gross_ratio": fee_gross,
        "top_rejects": rejects.most_common(5),
    }


def summary_for_ui() -> dict[str, Any]:
    return {mid: _rollup_mode(mid) for mid in MODE_IDS}


def persist_all_mode_metrics() -> dict[str, int]:
    """Periyodik rollup → mode_metrics tablosu."""
    n = 0
    for mid in MODE_IDS:
        m = _rollup_mode(mid)
        ingest_mode_metrics(
            mid,
            {
                "trades": m.get("trades"),
                "wins": int((m.get("win_rate") or 0) * (m.get("trades") or 0)),
                "profit_factor": m.get("profit_factor"),
                "win_rate": m.get("win_rate"),
                "fee_gross_ratio": m.get("fee_gross_ratio", 0),
                "pnl_per_min": m.get("pnl_per_min", 0),
                "top_rejects": m.get("top_rejects"),
            },
        )
        n += 1
    return {"modes": n}


def export_decisions_jsonl(limit: int = 500) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM mode_decisions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
