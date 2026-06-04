#!/usr/bin/env python3
"""22 coin portföy backtest — gelişmiş MTF + coin alpha."""
from __future__ import annotations

import argparse
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
    run_optimized_portfolio,
    run_param_grid,
    run_portfolio_backtest,
)
from binance_futures_trader.settings_backup import backup_before_change


def _apply_best(report: dict) -> None:
    best = report.get("best") or {}
    vid = best.get("variant_id")
    if not vid:
        return
    ret = float(best.get("total_return_pct") or 0)
    env_path = ROOT / "scenarios" / "binance_futures_demo.env"
    backups = backup_before_change([env_path], label=f"pre_portfolio_{vid}")
    for b in backups:
        print(f"  💾 Yedek: {b}")
    text = env_path.read_text(encoding="utf-8")
    patch = {
        "BN_FUT_EDU_STRATEGY_ID": vid,
        "BN_FUT_PORTFOLIO_ENGINE": "1",
        "BN_FUT_PORTFOLIO_RETURN_PCT": f"{ret:.2f}",
        "BN_FUT_MIN_SCORE": "2.2",
        "BN_FUT_STRATEGY_PROFILE": "standard",
        "BN_FUT_CANDLE_INTERVAL": "15m",
        "BN_FUT_LEVERAGE": str(int(min(8, float(best.get("leverage") or 3)))),
        "BN_FUT_MAX_OPEN": str(int(best.get("max_positions") or 6)),
    }
    for key, val in patch.items():
        pat = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pat.search(text):
            text = pat.sub(f"{key}={val}", text)
        else:
            text += f"\n{key}={val}\n"
    env_path.write_text(text, encoding="utf-8")
    print(f"  ✅ Env güncellendi → {vid} (backtest getiri {ret:+.1f}%)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=180)
    p.add_argument("--balance", type=float, default=float(os.getenv("BN_FUT_START_BALANCE", "5000")))
    p.add_argument(
        "--coins",
        default=",".join(cfg.WATCHLIST),
        help="Tam watchlist (varsayılan 22 coin)",
    )
    p.add_argument("--apply-best", action="store_true")
    p.add_argument("--grid", action="store_true", help="Parametre taraması (27 kombinasyon)")
    p.add_argument("--optimize", action="store_true", help="Per-coin optimize (30%% hedef)")
    args = p.parse_args()

    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    print(f"\n═══ Portföy backtest {args.days}g | {len(coins)} coin | ${args.balance:.0f} ═══\n")

    grid_out: dict = {}
    client = BinanceFuturesClient()
    try:
        from binance_futures_trader.portfolio_backtest import _load_coin_data

        print(f"  📦 {len(coins)} coin veri yükleniyor…")
        coin_data = _load_coin_data(client, coins, args.days)
        report = run_portfolio_backtest(
            client,
            days=args.days,
            coins=coins,
            start_balance=args.balance,
            coin_data=coin_data,
        )
        if args.grid:
            print("\n═══ Parametre grid (adv_mtf tabanlı) ═══\n")
            grid_out = run_param_grid(
                client,
                days=args.days,
                coins=coins,
                start_balance=args.balance,
                coin_data=coin_data,
            )
        if args.optimize:
            print("\n═══ Per-coin optimize portföy ═══\n")
            opt = run_optimized_portfolio(
                client,
                days=args.days,
                coins=coins,
                start_balance=args.balance,
                coin_data=coin_data,
            )
            if opt and float(opt.get("total_return_pct") or 0) > float(
                (report.get("best") or {}).get("total_return_pct") or -999
            ):
                report["best"] = opt
                report["ranking"].insert(0, opt)
    finally:
        client.close()

    if args.grid and grid_out:
        best_g = grid_out.get("best") or {}
        if best_g:
            print(f"  Grid en iyi: getiri={best_g.get('total_return_pct')}% params={best_g.get('params')}")
            if float(best_g.get("total_return_pct") or 0) > float(
                (report.get("best") or {}).get("total_return_pct") or 0
            ):
                report["best"] = {
                    "variant_id": "adv_mtf_bb_rsi_atr_optimized",
                    "total_return_pct": best_g.get("total_return_pct"),
                    "win_rate": best_g.get("win_rate"),
                    "profit_factor": best_g.get("profit_factor"),
                    "params": best_g.get("params"),
                }
                report["ranking"].insert(0, report["best"])

    print("\n═══ Sıralama (6 ay getiri %) ═══\n")
    for i, row in enumerate(report.get("ranking") or [], 1):
        hit = "✓" if float(row.get("total_return_pct") or 0) >= 30 else " "
        print(
            f"  {hit}{i}. {row['variant_id']:<26} "
            f"getiri={row['total_return_pct']:+.1f}%  "
            f"WR={row['win_rate']:.1%}  işlem={row['trades']}  "
            f"PF={row['profit_factor']:.2f}  DD={row['max_drawdown_pct']:.1f}%  "
            f"coin={len(row.get('coins_allowed') or [])}"
        )

    best = report.get("best") or {}
    print(f"\n🏆 En iyi: {best.get('variant_id')} → {best.get('total_return_pct', 0):+.1f}%")
    print(f"📄 Rapor: {REPORT_PATH}")

    target = 30.0
    if float(best.get("total_return_pct") or 0) >= target:
        print(f"\n🎯 Hedef %{target:.0f} aşıldı!")
    else:
        print(f"\n⚠ Hedef %{target:.0f} henüz yok — en iyi: {best.get('total_return_pct', 0):+.1f}%")

    if args.apply_best and best.get("variant_id"):
        _apply_best(report)

    print()


if __name__ == "__main__":
    main()
