#!/usr/bin/env python3
"""POST_RESTART_DATA_FLOW_DIAGNOSIS — read-only mod veri akışı teşhisi."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESTART_TS = datetime(2026, 5, 23, 14, 50, 7, tzinfo=timezone.utc).timestamp()
MODES = ["evrim", "berserk", "hunter", "chop_master", "sentinel"]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _read_jsonl(path: Path, since_ts: float = 0) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts = float(r.get("ts") or 0)
            if not ts and r.get("timestamp"):
                try:
                    ts = datetime.fromisoformat(str(r["timestamp"]).replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts = 0
            if since_ts and ts and ts < since_ts:
                continue
            rows.append(r)
        except Exception:
            pass
    return rows


def _mode_metrics(mode_id: str, since_ts: float) -> dict[str, Any]:
    from elite_trader.parallel_universe_engine import get_universe_book

    book = get_universe_book(mode_id)
    open_p = book.get("open") or []
    closed = book.get("closed") or []
    paper_open = len(open_p)
    paper_closed = len(closed)

    db = ROOT / "data" / "data_lake.db"
    decisions: list[dict[str, Any]] = []
    live_open = live_closed = 0
    if db.is_file():
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        decisions = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM mode_decisions WHERE mode_id = ? AND ts >= ? ORDER BY id DESC LIMIT 5000",
                (mode_id, since_ts),
            ).fetchall()
        ]
        live_row = conn.execute(
            "SELECT COUNT(*) n FROM live_trades WHERE mode_id = ? AND ts_open >= ?",
            (mode_id, since_ts),
        ).fetchone()
        live_closed_row = conn.execute(
            "SELECT COUNT(*) n FROM live_trades WHERE mode_id = ? AND ts_close >= ? AND ts_close IS NOT NULL",
            (mode_id, since_ts),
        ).fetchone()
        live_open = int(live_row[0]) if live_row else 0
        live_closed = int(live_closed_row[0]) if live_closed_row else 0
        conn.close()

    reject_rows = [d for d in decisions if not int(d.get("allowed") or 0)]
    allow_rows = [d for d in decisions if int(d.get("allowed") or 0)]
    rc: Counter[str] = Counter(str(r.get("reason") or "unknown")[:64] for r in reject_rows)

    scores: list[float] = []
    pnls: list[float] = []
    spreads: list[float] = []
    for d in decisions:
        try:
            extra = json.loads(d.get("payload_json") or "{}")
        except Exception:
            extra = {}
        if extra.get("final_score") is not None:
            scores.append(float(extra["final_score"]))
        if extra.get("expected_net_pnl") is not None:
            pnls.append(float(extra["expected_net_pnl"]))
        if extra.get("spread_pct") is not None:
            spreads.append(float(extra["spread_pct"]))

    last_dec = [
        {
            "symbol": d.get("symbol"),
            "allowed": bool(d.get("allowed")),
            "reason": d.get("reason"),
            "execution_path": d.get("execution_path"),
        }
        for d in decisions[:20]
    ]
    last_rej = [
        {
            "symbol": d.get("symbol"),
            "reason": d.get("reason"),
            "execution_path": d.get("execution_path"),
        }
        for d in reject_rows[:20]
    ]

    extra_rejects: list[dict[str, Any]] = []
    if mode_id == "hunter":
        extra_rejects = _read_jsonl(ROOT / "data" / "hunter_reject_log.jsonl", since_ts)
    elif mode_id == "sentinel":
        extra_rejects = _read_jsonl(ROOT / "data" / "sentinel_reject_log.jsonl", since_ts)

    if extra_rejects:
        for r in extra_rejects:
            rc[str(r.get("reason") or "unknown")[:64]] += 1

    return {
        "signal_received_count": len(decisions) + len(extra_rejects),
        "candidate_count": len(decisions),
        "decision_count": len(decisions),
        "paper_open_count": paper_open,
        "paper_closed_count": paper_closed,
        "live_open_count": live_open if mode_id == "evrim" else 0,
        "live_closed_count": live_closed if mode_id == "evrim" else 0,
        "reject_count": len(reject_rows) + len(extra_rejects),
        "top_10_reject_reasons": [{"reason": k, "count": v} for k, v in rc.most_common(10)],
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "avg_expected_net_pnl": round(sum(pnls) / len(pnls), 4) if pnls else None,
        "avg_spread": round(sum(spreads) / len(spreads), 4) if spreads else None,
        "avg_fee_gross": None,
        "last_20_decisions": last_dec,
        "last_20_rejects": last_rej,
    }


def _diagnosis_qa(metrics: dict[str, dict[str, Any]]) -> str:
    lines = ["## Soru-Cevap Analizi", ""]
    h, c, s, e = metrics["hunter"], metrics["chop_master"], metrics["sentinel"], metrics["evrim"]
    top_h = (h.get("top_10_reject_reasons") or [{}])[0].get("reason", "—")
    top_c = (c.get("top_10_reject_reasons") or [{}])[0].get("reason", "—")
    top_s = (s.get("top_10_reject_reasons") or [{}])[0].get("reason", "—")
    top_e = (e.get("top_10_reject_reasons") or [{}])[0].get("reason", "—")

    lines += [
        "### A) Hunter neden 0 işlem?",
        f"- Karar sayısı: {h['decision_count']}, paper closed: {h['paper_closed_count']}",
        f"- Dominant reject: `{top_h}`",
        "- Muhtemel: fake_breakout_risk, spike_await_confirmation, strength/edge/formula veya cooldown.",
        "",
        "### B) Chop neden 0 işlem?",
        f"- Karar sayısı: {c['decision_count']}, paper closed: {c['paper_closed_count']}",
        f"- Dominant reject: `{top_c}`",
        "- Muhtemel: chop_score düşük, trend_guard, hunter breakout veto.",
        "",
        "### C) Sentinel neden 0 işlem?",
        f"- Karar sayısı: {s['decision_count']}, paper closed: {s['paper_closed_count']}",
        f"- Dominant reject: `{top_s}`",
        "- Muhtemel: sentinel_watch, quality/execution eşik, spread_strict.",
        "",
        "### D) Evrim live görünürlük",
        f"- Live karar (DB): {e['decision_count']}, reject dominant: `{top_e}`",
        f"- Parallel paper open: {e['paper_open_count']} (beklenen: 0 — live motor)",
        "- Evrim kararları live/demo panel + order_route_log; parallel tabloda görünmemesi normal.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    metrics = {m: _mode_metrics(m, RESTART_TS) for m in MODES}
    out_path = ROOT / "data" / "reports" / f"POST_RESTART_DATA_FLOW_DIAGNOSIS_{_stamp()}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# POST_RESTART_DATA_FLOW_DIAGNOSIS",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Since restart checkpoint:** 2026-05-23T14:50:07Z",
        "",
        _diagnosis_qa(metrics),
        "## Mod Metrikleri",
        "",
    ]
    for mid, m in metrics.items():
        lines += [
            f"### {mid}",
            "",
            "```json",
            json.dumps(m, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
