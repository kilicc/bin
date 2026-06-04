#!/usr/bin/env python3
"""9007 MEGA desk verisini arşivle ve sıfırla (9005/9006 dokunulmaz)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    os.environ["BINANCE_ELITE_PORT"] = "9007"
    os.environ["MEGA_INSTANCE_ID"] = "9007"
    for name in (
        "scenarios/binance_elite_mega_9007_mainnet.env",
        "scenarios/binance_elite_mega_9007.env",
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
        break
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.startswith("MEGA_9007_"):
                os.environ[k.strip()] = v.strip()


def _fetch_demo_wallet() -> float:
    try:
        from binance_futures_trader.client import BinanceFuturesClient
        from elite_trader.mega_live import mega_binance_env

        key = mega_binance_env("BINANCE_API_KEY")
        secret = mega_binance_env("BINANCE_API_SECRET") or mega_binance_env(
            "BINANCE_FUTURES_API_SECRET"
        )
        if not key or not secret:
            return 0.0
        mc = BinanceFuturesClient(
            api_key=key,
            api_secret=secret,
            testnet=True,
            futures_demo=True,
            mode="testnet",
        )
        mc.sync_server_time(force=True)
        w = mc.exchange_wallet() or {}
        for k in ("total_wallet_balance", "total_margin_balance", "usdt_balance"):
            v = float(w.get(k) or 0)
            if v > 0:
                return v
    except Exception as exc:
        print(f"  ⚠ demo-fapi cüzdan okunamadı: {exc}")
    return 0.0


def main() -> None:
    p = argparse.ArgumentParser(description="9007 mega_9007/ verisini arşivle/sil")
    p.add_argument("--reason", "-r", required=True)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--keep-lab", action="store_true", help="data/lab_9007 koru")
    p.add_argument("--no-api", action="store_true", help="Demo cüzdan API çağrısı yapma")
    p.add_argument("--capital", type=float, default=0.0, help="Oturum anchor (0=API'den)")
    args = p.parse_args()
    if not args.yes:
        ans = input("9007 açık/kapalı kayıtları silinecek. Onay? [y/N]: ")
        if ans.strip().lower() not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = ROOT / "data" / "deleted_archives" / f"mega_9007_{ts}"
    archive.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"reason": args.reason, "ts": ts, "paths": [], "port": 9007}

    mega_dir = ROOT / "data" / "mega_9007"
    mega_dir.mkdir(parents=True, exist_ok=True)
    if mega_dir.is_dir() and any(mega_dir.iterdir()):
        dest = archive / "mega_9007"
        shutil.copytree(mega_dir, dest)
        manifest["paths"].append(str(dest))
        for child in sorted(mega_dir.iterdir()):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)

    if not args.keep_lab:
        lab = ROOT / "data" / "lab_9007"
        if lab.is_dir() and any(lab.iterdir()):
            dest = archive / "lab_9007"
            shutil.copytree(lab, dest)
            manifest["paths"].append(str(dest))
            shutil.rmtree(lab)

    _load_env()
    cleared = 0
    try:
        from elite_trader.mega_live import clear_mega_closed_records, _save_session_anchor

        cleared = clear_mega_closed_records(suppress_backfill=True)
    except Exception as exc:
        print(f"  ⚠ mega RAM/disk clear: {exc}")

    cap = float(args.capital or 0)
    if cap <= 0 and not args.no_api:
        cap = _fetch_demo_wallet()
    if cap > 0:
        try:
            from elite_trader.mega_live import _save_session_anchor

            _save_session_anchor(cap, reason=args.reason)
            manifest["wallet_anchor"] = cap
        except Exception as exc:
            print(f"  ⚠ session anchor: {exc}")

    (mega_dir / ".mega_closed_suppress_backfill").write_text(
        f"{datetime.now(timezone.utc).timestamp():.3f}\n",
        encoding="utf-8",
    )

    try:
        from elite_trader.data_archive import _load_manifest, _save_manifest

        data = _load_manifest()
        archives = list(data.get("archives") or [])
        archives.append(
            {
                "archive_id": archive.name,
                "port": 9007,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "reason": args.reason,
                "trigger": "reset_mega_9007_data",
                "path": str(archive.relative_to(ROOT)),
                "cleared_closed": cleared,
                "wallet_anchor": cap,
            }
        )
        data["archives"] = archives
        _save_manifest(data)
    except Exception:
        pass

    (archive / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "archive": str(archive),
                "cleared_closed": cleared,
                "wallet_anchor": cap,
                **manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
