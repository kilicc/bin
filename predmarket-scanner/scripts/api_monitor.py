#!/usr/bin/env python3
"""Binance demo API gecikme izleyici — env'den key okur."""
from __future__ import annotations

import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / "scenarios" / "binance_elite_8300_9005.env", override=True)
load_dotenv(_ROOT / ".env", override=True)
load_dotenv(_ROOT / "scenarios" / "binance_elite_8300_9005.env", override=True)

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

INTERVAL = float(os.getenv("ELITE_API_MONITOR_SEC", "2.0"))
BOT_API = os.getenv("ELITE_MONITOR_BOT_URL", "http://127.0.0.1:9005/api/live")

for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

# Tek client — TLS yeniden kurulmaz (ölçüm gerçek RTT)
_client = None


def _client_singleton():
    global _client
    if _client is None:
        from binance_futures_trader.client import BinanceFuturesClient

        _client = BinanceFuturesClient()
    return _client


def check_binance(*, warm: bool = True) -> tuple[bool, float, str, float | None, str]:
    """warm=False: ilk soğuk bağlantı; warm=True: tek REST çağrısı."""
    c = _client_singleton()
    t0 = time.perf_counter()
    if warm:
        try:
            c._get("/fapi/v2/balance", signed=True)
            ms = (time.perf_counter() - t0) * 1000.0
            w = c.exchange_wallet() or {}
            bal = float(w.get("total_wallet_balance") or 0)
            return True, ms, "", bal, "warm"
        except Exception as exc:
            return False, (time.perf_counter() - t0) * 1000.0, str(exc)[:80], None, "warm"
    ok, err = c._auth_ok()
    ms = (time.perf_counter() - t0) * 1000.0
    bal = None
    if ok:
        w = c.exchange_wallet() or {}
        bal = float(w.get("total_wallet_balance") or 0)
    return ok, ms, err or "", bal, "cold"


def check_bot() -> tuple[bool, bool]:
    try:
        r = httpx.get(BOT_API, timeout=2.0)
        if r.status_code != 200:
            return False, False
        d = r.json()
        return True, bool(d.get("api_connected"))
    except Exception:
        return False, False


def main() -> None:
    hist: deque[float] = deque(maxlen=300)
    fails = 0
    print("=" * 70)
    print("🔍 BINANCE DEMO API — gecikme izleyici (Ctrl+C durdur)")
    print(f"   aralık: {INTERVAL}s  |  key: {(os.getenv('BINANCE_FUTURES_API_KEY') or '')[:12]}…")
    print("   not: ilk satır soğuk bağlantı; sonrası warm RTT (~300-400ms TR normal)")
    print("=" * 70)
    cold_done = False
    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S")
            ok, ms, err, bal, kind = check_binance(warm=cold_done)
            cold_done = True
            bot_up, bot_api = check_bot()
            if ok:
                hist.append(ms)
                fails = 0
                avg = sum(hist) / len(hist)
                slow = ms > 800 if kind == "warm" else ms > 2500
                flag = "⚠️ YAVAŞ" if slow else ""
                print(
                    f"[{ts}] ✅ BN {ms:6.0f}ms ({kind}) ort {avg:5.0f}ms"
                    f"  bal=${bal or 0:,.2f}"
                    f"  bot={'UP' if bot_up else 'DOWN'}"
                    f"  api={'OK' if bot_api else '—'} {flag}"
                )
            else:
                fails += 1
                print(f"[{ts}] ❌ BN FAIL ({err})  fails={fails}  bot={'UP' if bot_up else 'DOWN'}")
                if fails >= 5:
                    print("  🚨 5 ardışık hata — key / demo futures hesabını kontrol edin")
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nDurduruldu.")


if __name__ == "__main__":
    main()
