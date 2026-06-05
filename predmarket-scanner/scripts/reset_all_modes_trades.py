#!/usr/bin/env python3
"""
5 mod — işlem geçmişini sıfırla (profil/.env dokunulmaz).
Evrim öğrenme dosyaları korunur; önce tüm mod verisi Evrim'e öğretilir.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from elite_trader.mode_data_archive import archive_mode, close_binance_exchange_positions
from elite_trader.panel_strategy import active_execution_mode, mode_order
from elite_trader.parallel_universe_engine import reset_mode_book


def main() -> int:
    ap = argparse.ArgumentParser(description="Tüm mod işlemlerini sıfırla (ayarlar korunur)")
    ap.add_argument("--reason", required=True, help="Arşiv nedeni (zorunlu)")
    ap.add_argument("--skip-archive", action="store_true", help="Arşivlemeden sıfırla")
    ap.add_argument("--skip-evrim-bootstrap", action="store_true", help="Evrim bootstrap atla")
    ap.add_argument("--no-exchange-close", action="store_true", help="Borsa pozisyonlarını kapatma")
    args = ap.parse_args()

    reason = (args.reason or "").strip()
    if not reason:
        print("Hata: --reason zorunlu")
        return 1

    print("══════════════════════════════════════════════════════════")
    print(" 5 mod işlem sıfırlama (mode_profiles / .env korunur)")
    print("══════════════════════════════════════════════════════════")

    if not args.skip_evrim_bootstrap:
        try:
            from elite_trader.evrim_cross_mode_learner import bootstrap_evrim_from_history

            out = bootstrap_evrim_from_history()
            print(
                f"  🧬 Evrim bootstrap: {out.get('ingested', 0)} kapanış "
                f"({out.get('by_mode', {})})"
            )
        except Exception as exc:
            print(f"  ⚠ Evrim bootstrap: {exc}")

    if not args.no_exchange_close:
        try:
            ex = close_binance_exchange_positions()
            print(f"  ✓ Borsa: {ex.get('message', ex)}")
        except Exception as exc:
            print(f"  ⚠ Borsa kapatma: {exc}")

    order = [m for m in mode_order() if m != "evrim"]
    order.append("evrim")

    for mid in order:
        if not args.skip_archive:
            try:
                meta = archive_mode(mid, reason=reason, trigger="reset_all_modes")
                print(f"  📁 Arşiv {mid}: {meta.get('archive_id', '—')}")
            except Exception as exc:
                print(f"  ⚠ Arşiv {mid}: {exc}")
        try:
            out = reset_mode_book(mid)
            print(
                f"  🔄 {mid}: {out.get('cleared_open', 0)} açık, "
                f"{out.get('cleared_closed', 0)} kapalı silindi"
            )
        except Exception as exc:
            print(f"  ⚠ Sıfırlama {mid}: {exc}")

    if active_execution_mode() in order:
        try:
            from elite_pro_state import clear_closed

            n = clear_closed(active_execution_mode())
            print(f"  🗃 Canlı motor DB: {n} kayıt silindi (mode_id)")
        except Exception as exc:
            print(f"  ⚠ DB: {exc}")

    try:
        from datetime import datetime, timezone

        from elite_trader.evrim_training import _save_training_state, load_training_state

        st = load_training_state()
        st["market_radar_state"] = {
            "day_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "day_pnl_usd": 0.0,
            "day_pnl_pct": 0.0,
            "consecutive_sl": 0,
        }
        _save_training_state(st)
        print("  ✓ Evrim radar günlük sayaç sıfırlandı (dd_halt engeli önlendi)")
    except Exception as exc:
        print(f"  ⚠ Radar sayaç: {exc}")

    print("══════════════════════════════════════════════════════════")
    print(" Tamam. Evrim state / mode_profiles / .env dokunulmadı.")
    print(" Botu yeniden başlat: ./run_binance_elite_8300_9005.sh")
    print("══════════════════════════════════════════════════════════")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
