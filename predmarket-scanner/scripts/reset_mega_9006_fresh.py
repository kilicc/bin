#!/usr/bin/env python3
"""9006 MEGA — arşivle, öğrenme/rejim kayıtlarını sil, borsayı flatten, gözlem penceresi ile yeniden başla."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    os.environ["BINANCE_ELITE_PORT"] = "9006"
    os.environ["MEGA_INSTANCE_ID"] = "9006"
    os.environ["MEGA_LIVE_ORDERS"] = "1"
    for name in (
        "scenarios/binance_elite_mega_9006_mainnet.env",
        "scenarios/.env.mega_9006",
        ".env",
    ):
        p = ROOT / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip()


def main() -> None:
    p = argparse.ArgumentParser(description="MEGA 9006 tam oturum sıfırlama")
    p.add_argument("--reason", "-r", required=True)
    p.add_argument("--capital", type=float, default=5000.0)
    p.add_argument(
        "--no-exchange-close",
        action="store_true",
        help="Borsa pozisyonlarını kapatma (yalnızca disk/RAM)",
    )
    p.add_argument("--yes", action="store_true")
    args = p.parse_args()
    reason = args.reason.strip()
    if not args.yes:
        ans = input(
            "9006 MEGA: açık pozisyonlar kapatılır, mega_9006/ arşivlenir, rejim/coin-watch silinir. [y/N]: "
        )
        if ans.strip().lower() not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return

    _load_env()
    from elite_trader.mega_live import reset_mega_session_data

    out = reset_mega_session_data(
        reason=reason,
        capital=args.capital,
        close_exchange=not args.no_exchange_close,
    )
    print("OK — arşiv:", out.get("archive"))
    print("  wallet_anchor:", out.get("wallet_anchor"))
    print("  aux_cleared:", out.get("aux_cleared"))
    print("  boot_observe_reset:", out.get("boot_observe_reset"))


if __name__ == "__main__":
    main()
