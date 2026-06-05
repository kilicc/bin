#!/usr/bin/env python3
"""9006 MEGA demo-fapi — borsa açıklarını kapat, yerel açık/kapalı kayıtları arşivle/sil."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _wipe_legacy_root_data() -> list[str]:
    """data/mega_live_*.json kök dosyaları — reset sonrası sim ghost önlemi."""
    removed: list[str] = []
    for name in (
        "mega_live_closed.json",
        "mega_live_open.json",
        "mega_live_open_meta.json",
        "mega_live_session.json",
        ".mega_closed_suppress_backfill",
    ):
        p = ROOT / "data" / name
        if p.is_file():
            p.unlink(missing_ok=True)
            removed.append(str(p.relative_to(ROOT)))
    return removed


def _load_env() -> None:
    os.environ["BINANCE_ELITE_PORT"] = "9006"
    os.environ["MEGA_INSTANCE_ID"] = "9006"
    os.environ["MEGA_LIVE_ORDERS"] = "1"
    os.environ["ELITE_BINANCE_REST_ENABLED"] = "1"
    os.environ["ELITE_BINANCE_DATA_HUB"] = "0"
    for name in (
        "scenarios/binance_elite_mega_9006_mainnet.env",
        "scenarios/.env.mega_9006",
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


def _suppress_backfill_first() -> None:
    from elite_trader.mega_live import suppress_mega_closed_backfill

    suppress_mega_closed_backfill()


def _close_exchange_positions() -> list[dict]:
    _suppress_backfill_first()
    from elite_trader.mega_live import get_mega_client

    mc = get_mega_client()
    if not mc or mc.paper:
        return []
    closed: list[dict] = []
    for ep in mc.exchange_positions() or []:
        coin = str(ep.get("coin") or "").upper()
        side = str(ep.get("side") or "LONG").upper()
        qty = float(ep.get("contracts") or 0)
        if not coin or qty <= 0:
            continue
        close_side = "SHORT" if side == "LONG" else "LONG"
        try:
            mc.market_order(coin, close_side, qty, reduce_only=True)
            closed.append({"coin": coin, "side": side, "qty": qty})
            print(f"  ✓ Borsa kapatıldı {coin} {side} qty={qty}")
            time.sleep(0.25)
        except Exception as exc:
            print(f"  ⚠ Kapatma {coin}: {exc}")
    return closed


def main() -> None:
    p = argparse.ArgumentParser(description="9006 mega_9006 verisini arşivle/sil")
    p.add_argument("--reason", "-r", required=True)
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-api", action="store_true", help="Borsa kapatma/cüzdan okuma yok")
    p.add_argument(
        "--capital",
        type=float,
        default=5000.0,
        help="Oturum anchor (varsayılan 5000)",
    )
    p.add_argument(
        "--skip-exchange-close",
        action="store_true",
        help="Borsadaki açık pozisyonları kapatma",
    )
    args = p.parse_args()
    if not args.yes:
        ans = input(
            "9006 açık/kapalı + borsa pozisyonları sıfırlanacak. Onay? [y/N]: "
        )
        if ans.strip().lower() not in ("y", "yes", "evet", "e"):
            print("İptal.")
            return

    _load_env()
    legacy_removed = _wipe_legacy_root_data()
    _suppress_backfill_first()
    exchange_closed: list[dict] = []
    if not args.no_api and not args.skip_exchange_close:
        exchange_closed = _close_exchange_positions()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = ROOT / "data" / "deleted_archives" / f"mega_9006_{ts}"
    archive.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "reason": args.reason,
        "ts": ts,
        "paths": [],
        "port": 9006,
        "exchange_positions_closed": exchange_closed,
        "legacy_root_removed": legacy_removed,
    }

    mega_dir = ROOT / "data" / "mega_9006"
    mega_dir.mkdir(parents=True, exist_ok=True)
    if mega_dir.is_dir() and any(mega_dir.iterdir()):
        dest = archive / "mega_9006"
        shutil.copytree(mega_dir, dest)
        manifest["paths"].append(str(dest.relative_to(ROOT)))
        for child in sorted(mega_dir.iterdir()):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)

    global_cleared = 0
    try:
        from elite_trader.mega_live import (
            _mega_open_book_path,
            _mega_open_meta_path,
            _mega_session_path,
            clear_mega_closed_records,
            mega_instance_data_dir,
            suppress_mega_closed_backfill,
        )

        suppress_mega_closed_backfill()
        import elite_trader.mega_live as ml

        ml._mega_positions = []
        ml._mega_positions_cache = []
        ml._mega_position_id = 1
        ml._mega_closed = []
        ml._mega_closed_loaded = True
        ml._mega_open_book_loaded = True
        for path in (_mega_open_book_path(), _mega_open_meta_path()):
            if path.is_file():
                shutil.copy2(path, archive / path.name)
                path.unlink(missing_ok=True)
        global_cleared = clear_mega_closed_records(suppress_backfill=True)
        suppress_mega_closed_backfill()
        cap = float(args.capital or 5000.0)
        from elite_trader.mega_live import _save_session_anchor

        _save_session_anchor(cap, reason=args.reason)
        sess = _mega_session_path()
        sess.parent.mkdir(parents=True, exist_ok=True)
        sess.write_text(
            json.dumps(
                {
                    "wallet_anchor": cap,
                    "starting_balance": cap,
                    "set_at": datetime.now(timezone.utc).isoformat(),
                    "reason": args.reason[:200],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        manifest["wallet_anchor"] = cap
        manifest["data_dir"] = str(mega_instance_data_dir())
        try:
            from elite_trader import parallel_universe_engine as pe

            pe.reset_mode_book("mega")
            pe.set_mode_session_start("mega", cap)
        except Exception as exc:
            print(f"  ⚠ parallel book: {exc}")
    except Exception as exc:
        print(f"  ⚠ mega RAM/disk clear: {exc}")

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
                "port": 9006,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "reason": args.reason,
                "trigger": "reset_mega_9006_data",
                "path": str(archive.relative_to(ROOT)),
                "cleared_closed": global_cleared,
                "wallet_anchor": manifest.get("wallet_anchor"),
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
                "cleared_closed": global_cleared,
                **manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
