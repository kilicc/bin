#!/usr/bin/env python3
"""Panel uPnL vs Binance positionRisk — satır satır mutabakat."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from base64 import b64encode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _fetch_json(url: str, user: str, password: str) -> dict:
    auth = b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(
        url, headers={"Authorization": f"Basic {auth}"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    base = os.getenv("PANEL_AUDIT_BASE", "http://127.0.0.1:9086")
    user = os.getenv("PANEL_AUDIT_USER", "x")
    password = os.getenv("PANEL_AUDIT_PASS", "x369")
    tick = _fetch_json(f"{base}/api/paper/mega/ticks", user, password)
    open_rows = tick.get("open") or []
    audit = tick.get("upnl_audit") or {}
    print("panel open rows:", len(open_rows))
    print("upnl_audit:", json.dumps(audit, ensure_ascii=False))

    try:
        from elite_trader.mega_live import get_mega_client, refresh_mega_positions_cache

        mc = get_mega_client()
        if not mc or getattr(mc, "paper", True):
            print("mega client yok veya paper — doğrudan API atlandı")
            return 0
        refresh_mega_positions_cache(force=True, skip_wallet=False, panel_critical=True)
        raw = mc.exchange_positions()
    except Exception as exc:
        print("exchange_positions:", exc)
        raw = []

    emap: dict[tuple[str, str], dict] = {}
    for ep in raw:
        sym = str(ep.get("symbol") or f"{ep.get('coin')}USDT").upper()
        side = str(ep.get("side") or "LONG").upper()
        emap[(sym, side)] = ep

    print("\n--- satır karşılaştırma (panel vs positionRisk) ---")
    ok_all = True
    for r in open_rows:
        sym = str(r.get("symbol") or "").upper()
        side = str(r.get("side") or "LONG").upper()
        ex_disp = r.get("exchange_display") or {}
        panel_u = r.get("unrealized_pnl") or ex_disp.get("unRealizedProfit")
        try:
            panel_f = float(panel_u)
        except (TypeError, ValueError):
            panel_f = None
        ep = emap.get((sym, side))
        api_u = float(ep.get("unrealized_pnl") or 0) if ep else None
        delta = None
        if panel_f is not None and api_u is not None:
            delta = round(panel_f - api_u, 4)
        match = delta is not None and abs(delta) < 0.02
        if not match:
            ok_all = False
        flag = "OK" if match else "MISMATCH"
        print(
            f"{flag} {sym} {side} panel={panel_f} api={api_u} Δ={delta} src={r.get('upnl_source')}"
        )
    if ok_all and open_rows:
        print("\nTüm satırlar Binance positionRisk ile uyumlu.")
    elif not open_rows:
        print("\nAçık pozisyon yok.")
    else:
        print("\nUyumsuz satır var — panel tick/snapshot veya tarayıcı önbelleği kontrol edin.")
    return 0 if ok_all or not open_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
