#!/usr/bin/env python3
"""Eğitim tabanlı 6 ay backtest + rapor + (opsiyonel) en iyi stratejiyi env'e yaz."""
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

from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.historical_backtest import (
    REPORT_PATH,
    run_6m_backtest,
    variant_to_env_patch,
)
from binance_futures_trader.settings_backup import backup_before_change


def _apply_env_patch(env_path: Path, patch: dict[str, str], label: str) -> None:
    backups = backup_before_change([env_path], label=label)
    for b in backups:
        print(f"  💾 Yedek: {b}")
    text = env_path.read_text(encoding="utf-8")
    for key, val in patch.items():
        pat = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
        if pat.search(text):
            text = pat.sub(f"{key}={val}", text)
        else:
            text += f"\n{key}={val}\n"
    env_path.write_text(text, encoding="utf-8")
    print(f"  ✅ Güncellendi: {env_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Eğitim 6 ay backtest")
    p.add_argument("--days", type=int, default=int(os.getenv("BN_FUT_EDU_BT_DAYS", "180")))
    p.add_argument("--interval", default=os.getenv("BN_FUT_EDU_BT_INTERVAL", "15m"))
    p.add_argument(
        "--coins",
        default=os.getenv("BN_FUT_EDU_BT_COINS", "BTC,ETH,SOL,BNB,XRP,DOGE,AVAX,LINK"),
        help="Virgülle ayrılmış coin listesi",
    )
    p.add_argument(
        "--apply-best",
        action="store_true",
        help="En iyi varyantı scenarios/binance_futures_demo.env dosyasına yaz (önce yedek)",
    )
    args = p.parse_args()

    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    print(f"\n═══ Eğitim backtest {args.days}g {args.interval} — {len(coins)} coin ═══\n")

    client = BinanceFuturesClient()
    try:
        report = run_6m_backtest(
            client,
            days=args.days,
            interval=args.interval,
            coins=coins,
        )
    finally:
        client.close()

    print("\n═══ Sıralama (rank_score) ═══\n")
    for i, row in enumerate(report.get("ranking") or [], 1):
        print(
            f"  {i}. {row['variant_id']:<28} "
            f"WR={row['win_rate']:.1%}  trades={row['trades']:>4}  "
            f"PnL%={row['total_pnl_pct']:+.2f}  PF={row['profit_factor']:.2f}  "
            f"DD={row['max_drawdown_pct']:.3f}  score={row['rank_score']:.3f}"
        )

    best = report.get("best_variant_id")
    print(f"\n🏆 En iyi: {best}")
    print(f"📄 Rapor: {REPORT_PATH}")

    if args.apply_best and best:
        patch = variant_to_env_patch(str(best))
        patch["BN_FUT_EDU_STRATEGY_ID"] = str(best)
        env_path = ROOT / "scenarios" / "binance_futures_demo.env"
        _apply_env_patch(env_path, patch, label=f"pre_edu_best_{best}")

    print()


if __name__ == "__main__":
    main()
