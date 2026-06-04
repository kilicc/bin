#!/usr/bin/env python3
"""Demo cüzdan vs panel — zarar analizi."""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TR = ZoneInfo("Europe/Istanbul")
ROOT = Path(os.environ.get("MEGA_ROOT", str(Path(__file__).resolve().parents[1])))


def wp(r: dict) -> float:
    return float(r.get("wallet_pnl") or r.get("final_pnl") or r.get("net_pnl") or 0)


def main() -> None:
    sys.path.insert(0, str(ROOT))
    now = datetime.now(TR)
    start_today = datetime(now.year, now.month, now.day, tzinfo=TR)
    st_ms = int(start_today.astimezone(timezone.utc).timestamp() * 1000)
    ustart = start_today.astimezone(timezone.utc)
    uend = (start_today + timedelta(days=1)).astimezone(timezone.utc)

    data_dir = ROOT / "data" / "mega_9006"
    sess = json.loads((data_dir / "mega_live_session.json").read_text())
    anchor = float(sess.get("wallet_anchor") or 5000)
    closed_raw = json.loads((data_dir / "mega_live_closed.json").read_text())
    closed = closed_raw if isinstance(closed_raw, list) else list(closed_raw.get("closed") or [])
    closed_net = sum(wp(r) for r in closed)

    from elite_trader.mega_live import get_mega_client

    mc = get_mega_client()
    if not mc:
        print("NO_CLIENT")
        sys.exit(1)

    acc = mc._get("/fapi/v2/account", signed=True)
    wallet = float(acc.get("totalWalletBalance") or 0)
    upnl = float(acc.get("totalUnrealizedProfit") or 0)
    avail = float(acc.get("availableBalance") or 0)
    margin = float(acc.get("totalMarginBalance") or 0)

    print("=== DEMO CÜZDAN (Binance API) ===")
    print(f"totalWalletBalance      {wallet:>11.2f} USDT")
    print(f"totalUnrealizedProfit   {upnl:>+11.2f} USDT")
    print(f"availableBalance        {avail:>11.2f} USDT")
    print(f"marginBalance           {margin:>11.2f} USDT")
    print(f"equity (wallet+uPnL)    {wallet + upnl:>11.2f} USDT")

    print("=== PANEL HESABI ===")
    print(f"Oturum anchor (wipe)      {anchor:.2f}")
    print(f"Kapalı tablo net        {closed_net:+.2f}  ({len(closed)} işlem)")
    neg_panel = [r for r in closed if wp(r) < -0.01]
    print(f"Panel zarar satırı        {len(neg_panel)} adet")
    print(f"anchor + closed           {anchor + closed_net:.2f}  (panel 'beklenen' — YANLIŞ)")
    print(f"GERÇEK wallet - anchor    {wallet - anchor:+.2f}  (doğru oturum realized)")
    print(f"GERÇEK equity - anchor    {wallet + upnl - anchor:+.2f}  (açık dahil)")

    pos = [p for p in acc.get("positions", []) if abs(float(p.get("positionAmt") or 0)) > 0]
    print(f"=== AÇIK {len(pos)} ===")
    for p in sorted(pos, key=lambda x: float(x.get("unrealizedProfit") or 0)):
        sym = p.get("symbol", "?")
        u = float(p.get("unrealizedProfit") or 0)
        print(f"  {sym:14} uPnL {u:+9.2f}")

    by: dict[str, dict[str, float]] = defaultdict(lambda: {"r": 0, "c": 0, "f": 0})
    neg_events: list[tuple] = []
    for itype in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE"):
        rows = mc._get(
            "/fapi/v1/income",
            {"incomeType": itype, "startTime": st_ms, "limit": 1000},
            signed=True,
        )
        if not isinstance(rows, list):
            continue
        for r in rows:
            sym = r.get("symbol") or "—"
            inc = float(r.get("income") or 0)
            ms = int(r.get("time") or 0)
            tr = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(TR)
            if itype == "REALIZED_PNL":
                by[sym]["r"] += inc
                if inc < -0.01:
                    neg_events.append((tr, sym, inc))
            elif itype == "COMMISSION":
                by[sym]["c"] += inc
            else:
                by[sym]["f"] += inc

    tr = tc = tf = 0.0
    print("=== BUGÜN BİNANCE GERÇEK (income) ===")
    for sym, v in sorted(by.items(), key=lambda x: x[1]["r"] + x[1]["c"] + x[1]["f"]):
        net = v["r"] + v["c"] + v["f"]
        tr += v["r"]
        tc += v["c"]
        tf += v["f"]
        flag = " ZARAR" if net < -0.5 else ""
        print(
            f"  {sym:14} r{v['r']:+8.2f} c{v['c']:+8.2f} f{v['f']:+6.2f} => {net:+8.2f}{flag}"
        )
    print(f"  TOPLAM realized {tr:+.2f} comm {tc:+.2f} fund {tf:+.2f} NET {tr + tc + tf:+.2f}")

    print("=== PANEL ZARAR SATIRLARI (tüm zaman) ===")
    for r in neg_panel:
        print(
            f"  {r.get('exit_time_str')} {r.get('symbol')} {wp(r):+.2f} "
            f"{r.get('exit_reason')} id={r.get('id')}"
        )

    pids = {int(r.get("id") or 0) for r in closed}
    audit_path = data_dir / "mega_close_audit.jsonl"
    print("=== AUDIT ZARAR (bugün TR, settlement) ===")
    if audit_path.is_file():
        for line in audit_path.read_text().splitlines():
            o = json.loads(line)
            if o.get("event") != "close_settled":
                continue
            ts = datetime.fromisoformat(o["ts"].replace("Z", "+00:00"))
            if not (ustart <= ts < uend):
                continue
            st = o.get("settlement") or {}
            w = float(st.get("wallet_pnl") or 0)
            if w >= -0.5:
                continue
            pid = int(o.get("position_id") or 0)
            in_p = "VAR" if pid in pids else "YOK"
            print(
                f"  {ts.astimezone(TR).strftime('%H:%M:%S')} {o.get('symbol')} "
                f"net {w:+.2f} id={pid} panel={in_p}"
            )

    neg_events.sort(reverse=True)
    print(f"=== REALIZED<0 bugün ({len(neg_events)} olay) ===")
    for tr, sym, inc in neg_events[:20]:
        print(f"  {tr.strftime('%H:%M:%S')} {sym:12} {inc:+.4f}")


if __name__ == "__main__":
    main()
