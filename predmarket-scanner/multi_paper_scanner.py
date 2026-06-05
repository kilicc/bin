#!/usr/bin/env python3
"""
Üç paper senaryosu ($110 / $220 / $2200) — tek tarama, aynı işlemler, TP %1 / SL %5.

Panel: http://127.0.0.1:8010 | 8020 | 8030
Başlat: ./run_paper_scenarios.sh
"""
from __future__ import annotations

import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)
_insane = ROOT / "scenarios" / "insane_24h.env"
if _insane.is_file():
    load_dotenv(_insane, override=True)

os.environ.pop("POLYMARKET_LIVE_TRADING", None)
os.environ.pop("POLYMARKET_LIVE_CONFIRM", None)

import httpx
import momentum_scanner as ms
from paper_scenarios import DEFAULT_SCENARIOS, apply_scenario, init_scenario_db, load_scenarios


def _write_multi_heartbeat(scenarios: list, conns: list, cycle: int) -> None:
    try:
        from scanner_runtime import write_heartbeat_atomic
    except ImportError:
        return
    for sc, conn in zip(scenarios, conns):
        open_n = ms.open_position_count(conn)
        closed = conn.execute(
            "SELECT COUNT(*) n FROM positions WHERE closed_at IS NOT NULL"
        ).fetchone()["n"]
        pnl = conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) t FROM positions WHERE closed_at IS NOT NULL"
        ).fetchone()["t"]
        path = ROOT / "data" / f"polymarket_scanner_{sc.name}.heartbeat.json"
        write_heartbeat_atomic(
            path,
            {
                "engine": "polymarket_scanner",
                "mode": "paper",
                "scenario": sc.name,
                "db": str(sc.db_path.relative_to(ROOT)),
                "ts": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "loop": cycle,
                "live_armed": False,
                "open_positions": int(open_n),
                "closed_trades": int(closed),
                "realized_pnl": round(float(pnl), 4),
                "starting_balance": sc.starting_balance,
                "tp_pct": sc.take_profit_pct,
                "sl_pct": sc.stop_loss_pct,
            },
        )


def main() -> None:
    scenarios = load_scenarios()
    if not scenarios:
        print("Senaryo yok — PAPER_SCENARIOS kontrol edin.")
        sys.exit(1)

    print("=" * 65)
    print(" Multi Paper Scanner — INSANE 24H senkron (hızlı TP / agresif Kelly)")
    for sc in scenarios:
        print(
            f"  {sc.label:14}  ${sc.starting_balance:,.0f}  "
            f"hedef≈${sc.target_stake_usd:.0f}/pos  port :{sc.port}  → {sc.db_path.name}"
        )
    print("=" * 65)

    for sc in scenarios:
        init_scenario_db(sc)

    conns: list[sqlite3.Connection] = []
    for sc in scenarios:
        c = sqlite3.connect(str(sc.db_path))
        c.row_factory = sqlite3.Row
        conns.append(c)

    client = httpx.Client(
        timeout=20.0,
        headers={"User-Agent": "predmarket-multi-paper/0.1", "Accept": "application/json"},
    )

    if not ms.CALIBRATION:
        snap = __import__("self_improver").load_learned_snapshot()
        if snap.get("calibration"):
            ms.CALIBRATION = snap["calibration"]

    stopped = False

    def _stop(*_):
        nonlocal stopped
        stopped = True
        print("\n[Ctrl+C] Multi paper durduruluyor…")

    signal.signal(signal.SIGINT, _stop)

    pos_cycle = 0
    scan_cycle = 0
    last_scan_t = 0.0
    scan_interval = ms.SCAN_INTERVAL
    position_check = ms.POSITION_CHECK

    while not stopped:
        loop_start = time.time()
        pos_cycle += 1
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now_str}] Multi kontrol #{pos_cycle}")

        total_closed = 0
        for sc, conn in zip(scenarios, conns):
            with apply_scenario(sc):
                n = ms.check_and_close_positions(conn, client)
                total_closed += n
                if n:
                    print(f"  [{sc.name}] {n} pozisyon kapatıldı")

        markets: list | None = None
        if loop_start - last_scan_t >= scan_interval:
            scan_cycle += 1
            markets = ms.fetch_active_markets(client)
            print(f"  [tarama #{scan_cycle}] {len(markets)} market — 3 senaryoya uygulanıyor…")
            last_scan_t = loop_start

        if markets is not None:
            for sc, conn in zip(scenarios, conns):
                with apply_scenario(sc):
                    opened = ms.scan_markets(conn, client, markets=markets)
                    if opened:
                        print(f"  [{sc.name}] +{opened} yeni pozisyon")

        for sc, conn in zip(scenarios, conns):
            open_n = ms.open_position_count(conn)
            pnl = conn.execute(
                "SELECT COALESCE(SUM(pnl_usd),0) t FROM positions WHERE closed_at IS NOT NULL"
            ).fetchone()["t"]
            print(f"  {sc.name}: açık={open_n}  P&L=${float(pnl):+.2f}")

        _write_multi_heartbeat(scenarios, conns, pos_cycle)

        sleep_end = loop_start + position_check
        while not stopped and time.time() < sleep_end:
            time.sleep(0.1)

    for c in conns:
        c.close()
    client.close()
    print("Multi paper scanner kapandı.")


if __name__ == "__main__":
    main()
