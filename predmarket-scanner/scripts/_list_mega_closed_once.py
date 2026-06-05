#!/usr/bin/env python3
"""Tek seferlik — 9006 kapanış listesi + zararlar."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    os.environ["BINANCE_ELITE_PORT"] = "9006"
    os.environ["MEGA_INSTANCE_ID"] = "9006"
    for name in ("scenarios/binance_elite_mega_9006_mainnet.env", "scenarios/.env.mega_9006"):
        p = ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip()


def load_closed(path: Path) -> list:
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    return list(raw.get("closed") or [])


def main() -> None:
    _load_env()
    rows: list = []
    base = ROOT / "data" / "mega_9006"
    rows.extend(load_closed(base / "mega_live_closed.json"))
    rows.extend(load_closed(base / "mega_live_closed_history.json"))
    for d in sorted((ROOT / "data" / "deleted_archives").glob("mega_9006_*")):
        for fp in (d / "mega_live_closed.json", d / "mega_9006" / "mega_live_closed.json"):
            rows.extend(load_closed(fp))

    seen: set = set()
    uniq: list = []
    for r in rows:
        key = (
            r.get("id"),
            r.get("symbol"),
            r.get("side") or r.get("direction"),
            r.get("exit_time"),
            round(float(r.get("net_pnl") or r.get("pnl") or 0), 2),
        )
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    uniq.sort(key=lambda x: float(x.get("exit_time") or 0))

    print(f"TOPLAM benzersiz kapanış: {len(uniq)}\n")
    print("--- TÜM LİSTE (kronolojik) ---")
    for r in uniq:
        et = float(r.get("exit_time") or 0)
        ts = (
            datetime.fromtimestamp(et, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            if et
            else "?"
        )
        net = float(r.get("net_pnl") or r.get("pnl") or 0)
        sym = r.get("symbol") or "?"
        side = r.get("side") or r.get("direction") or "?"
        reason = r.get("exit_reason") or r.get("reason") or "?"
        hide = ""
        if r.get("phantom_slippage") or r.get("panel_hide"):
            hide = " [panel gizli/phantom]"
        print(f"{ts}  {sym:12s} {str(side):5s}  net={net:+9.2f}  {reason}{hide}")

    losses = [r for r in uniq if float(r.get("net_pnl") or r.get("pnl") or 0) < -0.5]
    print(f"\n--- ZARARLI (net < -0.50): {len(losses)} ---")
    for r in losses:
        et = float(r.get("exit_time") or 0)
        ts = (
            datetime.fromtimestamp(et, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            if et
            else "?"
        )
        net = float(r.get("net_pnl") or r.get("pnl") or 0)
        print(
            f"{ts}  {r.get('symbol','?'):12s}  net={net:+9.2f}  "
            f"{r.get('exit_reason')}  hide={bool(r.get('panel_hide'))}"
        )

    cut = datetime(2026, 6, 3, 19, 0, tzinfo=timezone.utc).timestamp()
    post = [r for r in uniq if float(r.get("exit_time") or 0) >= cut]
    print(f"\n--- Sıfırlama sonrası (03 Haz 19:00 UTC+): {len(post)} ---")


if __name__ == "__main__":
    main()
