#!/usr/bin/env python3
"""Raw positionRisk vs panel ticks — side-by-side."""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

env_path = ROOT / "scenarios" / "binance_elite_mega_9006_mainnet.env"
if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

os.environ.setdefault("MEGA_INSTANCE_ID", "9006")

from elite_trader.mega_live import get_mega_client

mc = get_mega_client()
print("client_paper", getattr(mc, "paper", None))
print("\n=== Binance positionRisk (raw) ===")
api_sum = 0.0
for p in mc._get("/fapi/v2/positionRisk", signed=True) or []:
    amt = float(p.get("positionAmt") or 0)
    if abs(amt) < 1e-12:
        continue
    u = float(p.get("unRealizedProfit") or 0)
    api_sum += u
    print(
        p["symbol"],
        f"amt={amt}",
        f"entry={p.get('entryPrice')}",
        f"mark={p.get('markPrice')}",
        f"uPnL={u}",
        f"pct={p.get('percentage')}",
        f"margin={p.get('isolatedMargin')}",
    )
print("api_sum", round(api_sum, 4))

auth = base64.b64encode(b"x:x369").decode()
req = urllib.request.Request(
    "http://127.0.0.1:9006/api/paper/mega/ticks",
    headers={"Authorization": "Basic " + auth},
)
with urllib.request.urlopen(req, timeout=45) as r:
    d = json.loads(r.read())

print("\n=== Panel ticks ===")
panel_sum = 0.0
for row in d.get("open") or []:
    ex = row.get("exchange_display") or {}
    u = float(ex.get("unRealizedProfit") or row.get("exchange_unrealized_pnl") or 0)
    panel_sum += u
    print(
        row.get("symbol"),
        f"uPnL={u}",
        f"mark={ex.get('markPrice')}",
        f"entry={ex.get('entryPrice')}",
        f"pct={ex.get('percentage')}",
        f"age={row.get('exchange_data_age_ms')}ms",
    )
print("panel_sum", round(panel_sum, 4))
print("diff", round(panel_sum - api_sum, 4))
