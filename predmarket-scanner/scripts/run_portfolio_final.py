#!/usr/bin/env python3
"""22 coin portföy backtest — düzeltilmiş risk + Calmar sıralama + env uygulama."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "scenarios" / "binance_futures_demo.env", override=True)

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.portfolio_backtest import (
    REPORT_PATH,
    _load_coin_data,
    load_advanced_variants,
    run_portfolio_backtest,
)
from binance_futures_trader.settings_backup import backup_before_change

FOCUS = [
    "adv_alpha_controlled_30",
    "adv_winner_coins_sniper",
    "adv_mtf_bb_rsi_atr",
    "adv_alpha_max",
]


def main() -> None:
    coins = list(cfg.WATCHLIST)
    balance = float(os.getenv("BN_FUT_START_BALANCE", "5000"))
    print(f"\n═══ Final portföy test | {len(coins)} coin | ${balance:.0f} ═══\n")

    client = BinanceFuturesClient()
    try:
        coin_data = _load_coin_data(client, coins, 180)
        all_v = load_advanced_variants()
        focus_v = [v for v in all_v if v.id in FOCUS]
        # Geçici: sadece odak varyantları test et
        import binance_futures_trader.portfolio_backtest as pb

        orig = pb.load_advanced_variants
        pb.load_advanced_variants = lambda: focus_v  # type: ignore[method-assign]
        report = run_portfolio_backtest(
            client, days=180, coins=coins, start_balance=balance, coin_data=coin_data
        )
        pb.load_advanced_variants = orig  # type: ignore[method-assign]
    finally:
        client.close()

    print("\n═══ Sonuç (Calmar sıralı) ═══\n")
    for i, row in enumerate(report.get("ranking") or [], 1):
        ok = "✓" if float(row.get("total_return_pct") or 0) >= 30 else " "
        print(
            f"  {ok}{i}. {row['variant_id']:<28} "
            f"getiri={row.get('total_return_pct', 0):+.1f}%  "
            f"Calmar={row.get('calmar_score', 0):.2f}  "
            f"WR={row.get('win_rate', 0):.1%}  DD={row.get('max_drawdown_pct', 0):.1f}%  "
            f"işlem={row.get('trades', 0)}"
        )

    best = report.get("best") or {}
    print(f"\n🏆 Seçilen: {best.get('variant_id')} → {best.get('total_return_pct', 0):+.1f}%")
    print(f"📄 {REPORT_PATH}")

    if best.get("variant_id"):
        env_path = ROOT / "scenarios" / "binance_futures_demo.env"
        for b in backup_before_change([env_path], label=f"pre_portfolio_final_{best['variant_id']}"):
            print(f"  💾 {b}")
        text = env_path.read_text(encoding="utf-8")
        patch = {
            "BN_FUT_EDU_STRATEGY_ID": str(best["variant_id"]),
            "BN_FUT_PORTFOLIO_ENGINE": "1",
            "BN_FUT_PORTFOLIO_RETURN_PCT": str(best.get("total_return_pct", 0)),
            "BN_FUT_STRATEGY_PROFILE": "standard",
            "BN_FUT_CANDLE_INTERVAL": "15m",
            "BN_FUT_LEVERAGE": str(int(min(8, float(best.get("leverage") or 4)))),
            "BN_FUT_MAX_OPEN": str(int(best.get("max_positions") or 6)),
            "BN_FUT_MIN_SCORE": "2.15",
            "BN_FUT_TP_PCT": "0.022",
            "BN_FUT_SL_PCT": "0.010",
            "BN_FUT_MIN_SIGNAL_PARTS": "2",
        }
        if best.get("variant_id") == "adv_winner_coins_sniper":
            coins_s = ",".join(best.get("coins_allowed") or ["WIF", "INJ", "APT", "LINK", "AVAX"])
            patch["BN_FUT_WATCHLIST"] = coins_s
        for k, v in patch.items():
            pat = re.compile(rf"^{re.escape(k)}=.*$", re.MULTILINE)
            text = pat.sub(f"{k}={v}", text) if pat.search(text) else text + f"\n{k}={v}\n"
        env_path.write_text(text, encoding="utf-8")
        print("  ✅ binance_futures_demo.env güncellendi")
    print()


if __name__ == "__main__":
    main()
