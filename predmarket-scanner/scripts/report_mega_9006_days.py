#!/usr/bin/env python3
"""MEGA 9006 kapanış raporu — TR takvim günü."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TR = ZoneInfo("Europe/Istanbul")


def parse_ts(r: dict) -> datetime | None:
    for k in ("exit_time_str", "closed_at", "exit_time", "close_time"):
        v = r.get(k)
        if not v:
            continue
        if isinstance(v, (int, float)):
            ts = float(v)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        s = str(v).strip()
        if s.isdigit():
            iv = int(s)
            if iv > 1e12:
                iv //= 1000
            return datetime.fromtimestamp(iv, tz=timezone.utc)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(s[:19], fmt).replace(tzinfo=TR)
                return dt.astimezone(timezone.utc)
            except ValueError:
                pass
    return None


def load_closed(path: Path) -> list[dict]:
    d = json.loads(path.read_text())
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return list(d.get("closed") or d.get("records") or [])
    return []


def wallet_pnl(r: dict) -> float:
    return float(r.get("wallet_pnl") or r.get("final_pnl") or r.get("net_pnl") or 0)


def gross_pnl(r: dict) -> float:
    return float(r.get("pnl_usd") or r.get("pnl_gross_usd") or 0)


def report(closed: list[dict], days: list[str]) -> None:
    by_day: dict[str, list[dict]] = {d: [] for d in days}
    for r in closed:
        dt = parse_ts(r)
        if not dt:
            continue
        dtr = dt.astimezone(TR).strftime("%Y-%m-%d")
        if dtr in by_day:
            by_day[dtr].append(r)

    grand_net = 0.0
    grand_gross = 0.0
    for day in days:
        rows = sorted(
            by_day[day],
            key=lambda x: parse_ts(x) or datetime.min.replace(tzinfo=timezone.utc),
        )
        print(f"=== {day} (TR) — {len(rows)} kapanış ===")
        wins, losses, flat = [], [], []
        for r in rows:
            wp, gr = wallet_pnl(r), gross_pnl(r)
            sym = r.get("symbol", "?")
            side = r.get("side", "?")
            reason = r.get("exit_reason", "?")
            ts = r.get("exit_time_str") or r.get("closed_at") or ""
            stake = float(r.get("stake_usd") or 0)
            bucket = wins if wp > 0.01 else losses if wp < -0.01 else flat
            bucket.append((sym, side, wp, gr, reason, ts, stake, r.get("id")))
            print(
                f"  {ts} | {sym:12} {str(side):5} | "
                f"net {wp:+.2f} USD brüt {gr:+.2f} | {reason} | "
                f"stake {stake:.0f} id={r.get('id')}"
            )
        net_sum = sum(wallet_pnl(r) for r in rows)
        gross_sum = sum(gross_pnl(r) for r in rows)
        w_net = sum(x[2] for x in wins)
        l_net = sum(x[2] for x in losses)
        print(
            f"  ÖZET: {len(wins)} kâr, {len(losses)} zarar, {len(flat)} nötr | "
            f"net {net_sum:+.2f} | brüt {gross_sum:+.2f} USD"
        )
        print(f"  Kârlar net: {w_net:+.2f} | Zararlar net: {l_net:+.2f}")
        print()
        grand_net += net_sum
        grand_gross += gross_sum

    print(f"=== İki gün toplamı === net {grand_net:+.2f} USD | brüt {grand_gross:+.2f} USD")


def main() -> None:
    path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "/opt/binancex/predmarket-scanner/data/mega_9006/mega_live_closed.json"
    )
    days = sys.argv[2:] if len(sys.argv) > 2 else ["2026-05-31", "2026-06-01"]
    closed = load_closed(path)
    print(f"Kaynak: {path} ({len(closed)} toplam kapanış)")
    report(closed, days)


if __name__ == "__main__":
    main()
