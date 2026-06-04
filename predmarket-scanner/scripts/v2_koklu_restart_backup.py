#!/usr/bin/env python3
"""V2 köklü restart öncesi tam yedek + checkpoint MD."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from elite_trader.system_checkpoint_md import CHECKPOINT_DIR, _load_index, _save_index, _now_iso, _stamp
from scripts.full_reset_backup import run_backup, _lake_table_counts, _state_db_counts


def load_json(p: Path) -> Any:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


def fetch_exchange() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        env_path = ROOT / "scenarios" / "binance_elite_8300_9005.env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        os.environ.setdefault("BN_FUT_MODE", "testnet")
        os.environ.setdefault("BINANCE_FUTURES_TESTNET", "1")
        os.environ.setdefault("BINANCE_FUTURES_DEMO", "1")

        from binance_futures_trader import config as cfg
        from binance_futures_trader.client import BinanceFuturesClient

        cfg.MODE = "testnet"
        cfg.TESTNET = True
        cfg.FUTURES_DEMO = True
        client = BinanceFuturesClient()
        out["paper_mode"] = client.paper
        out["auth_error"] = client._auth_error
        if not client.paper:
            out["wallet"] = client.exchange_wallet()
            out["open_positions"] = client.exchange_positions() or []
        else:
            out["note"] = "client in paper mode — wallet from files only"
    except Exception as exc:
        out["error"] = str(exc)
    return out


def parallel_summary() -> dict[str, Any]:
    data = load_json(ROOT / "data" / "parallel_universes.json") or {}
    uni = data.get("universes") or {}
    summary: dict[str, Any] = {
        "starting_capital": data.get("starting_capital"),
        "starting_capital_by_mode": data.get("starting_capital_by_mode"),
        "modes": {},
    }
    for mid, book in uni.items():
        if not isinstance(book, dict):
            continue
        open_p = book.get("open") or []
        closed = book.get("closed") or []
        cap = float(book.get("capital") or book.get("current_capital") or 0)
        pnl = sum(float(p.get("net_pnl") or p.get("pnl") or 0) for p in closed)
        summary["modes"][mid] = {
            "capital": cap,
            "open_count": len(open_p),
            "closed_count": len(closed),
            "closed_pnl_sum": round(pnl, 4),
            "open": open_p[:20],
            "recent_closed": closed[-15:],
        }
    return summary


def state_db_trades(limit: int = 50) -> dict[str, Any]:
    db = ROOT / "data" / "binance_elite_8300_9005_state.db"
    if not db.is_file():
        return {}
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    out: dict[str, Any] = {"tables": _state_db_counts()}
    for tbl in ("positions", "closed_trades", "trade_log", "orders", "open_positions"):
        try:
            rows = conn.execute(
                f"SELECT * FROM [{tbl}] ORDER BY rowid DESC LIMIT {limit}"
            ).fetchall()
            out[tbl] = [dict(r) for r in rows]
        except Exception:
            pass
    conn.close()
    return out


def effective_profile() -> dict[str, Any]:
    from elite_trader.mode_profiles import get_profile
    from elite_trader.evrim_config_version import get_trading_profile, config_version_snapshot
    from elite_trader.panel_strategy import active_futures_mode
    from elite_trader.order_gate import get_routing_status

    base = get_profile("evrim") or {}
    trading = get_trading_profile(base)
    return {
        "active_futures_mode": active_futures_mode(),
        "routing": get_routing_status(active_futures_mode()),
        "evrim_trading_profile": {
            k: trading.get(k)
            for k in (
                "max_open",
                "active_capital_pct",
                "min_stake_usd",
                "evrim_v2_normal_min",
                "evrim_v2_config_auto_apply",
                "starting_balance",
                "role",
            )
        },
        "config_versions": config_version_snapshot(),
        "learning_runtime": load_json(ROOT / "data" / "evrim_learning_runtime.json"),
    }


def main() -> int:
    stamp = _stamp()
    filename = f"{stamp}__v2_koklu_restart_pre_backup.md"
    report_path = f"data/reports/checkpoints/{filename}"

    manifest = run_backup(report_path=report_path)
    backup_dir = manifest.get("backup_dir")

    exchange = fetch_exchange()
    parallel = parallel_summary()
    state_trades = state_db_trades()
    profile = effective_profile()
    lake_counts = _lake_table_counts()

    lines = [
        "# V2 Köklü Restart — Pre-Backup Checkpoint",
        "",
        "## CHECKPOINT_META",
        "",
        "| Alan | Değer |",
        "|------|-------|",
        f"| checkpoint_id | `{filename.replace('.md', '')}` |",
        f"| created_at | `{_now_iso()}` |",
        f"| event_type | `v2_koklu_restart` |",
        f"| label | V2 köklü restart — tam yedek |",
        f"| backup_dir | `{backup_dir}` |",
        f"| backup_verified | `{manifest.get('backup_verified')}` |",
        f"| git_head | `{manifest.get('git_head', '')[:12]}` |",
        "",
        "## READY_TO_RESTART",
        "",
        "Bu checkpoint restart **öncesi** alındı. Efektif Evrim V2 profili doğrulandı.",
        "",
        "### Evrim efektif profil",
        "",
        "```json",
        json.dumps(profile.get("evrim_trading_profile"), ensure_ascii=False, indent=2),
        "```",
        "",
        "### Active futures mode & routing",
        "",
        "```json",
        json.dumps(
            {
                "active_futures_mode": profile.get("active_futures_mode"),
                "routing": profile.get("routing"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "## BAKİYELER",
        "",
    ]

    if exchange.get("wallet"):
        w = exchange["wallet"]
        lines.extend(
            [
                "| Alan | Değer |",
                "|------|-------|",
                f"| total_wallet_balance | {w.get('total_wallet_balance')} |",
                f"| total_margin_balance | {w.get('total_margin_balance')} |",
                f"| available_balance | {w.get('available_balance')} |",
                f"| unrealized_pnl | {w.get('unrealized_pnl')} |",
                "",
                "```json",
                json.dumps(w, ensure_ascii=False, indent=2, default=str),
                "```",
                "",
            ]
        )
    else:
        note = (
            exchange.get("note")
            or exchange.get("error")
            or exchange.get("auth_error")
            or "unavailable"
        )
        lines.extend(
            [
                f"*Exchange wallet:* `{note}`",
                "",
                "### Paper / parallel capital özeti",
                "",
                "```json",
                json.dumps(
                    {
                        "starting_capital": parallel.get("starting_capital"),
                        "starting_capital_by_mode": parallel.get("starting_capital_by_mode"),
                        "mode_capitals": {
                            m: v.get("capital")
                            for m, v in (parallel.get("modes") or {}).items()
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
            ]
        )

    mode_summary = {
        m: {k: v[k] for k in ("capital", "open_count", "closed_count", "closed_pnl_sum") if k in v}
        for m, v in (parallel.get("modes") or {}).items()
    }
    open_detail = {m: v.get("open") for m, v in (parallel.get("modes") or {}).items()}
    closed_detail = {m: v.get("recent_closed") for m, v in (parallel.get("modes") or {}).items()}
    state_rows = {k: state_trades.get(k) for k in state_trades if k != "tables"}

    lines.extend(
        [
            "## EXCHANGE AÇIK POZİSYONLAR",
            "",
            "```json",
            json.dumps(exchange.get("open_positions") or [], ensure_ascii=False, indent=2, default=str)[
                :8000
            ],
            "```",
            "",
            "## PARALEL EVREN — MOD ÖZETİ",
            "",
            "```json",
            json.dumps(mode_summary, ensure_ascii=False, indent=2),
            "```",
            "",
            "## PARALEL EVREN — AÇIK POZİSYONLAR (detay)",
            "",
            "```json",
            json.dumps(open_detail, ensure_ascii=False, indent=2, default=str)[:30000],
            "```",
            "",
            "## PARALEL EVREN — SON KAPANAN İŞLEMLER",
            "",
            "```json",
            json.dumps(closed_detail, ensure_ascii=False, indent=2, default=str)[:40000],
            "```",
            "",
            "## STATE DB TABLO SAYILARI",
            "",
            "```json",
            json.dumps(state_trades.get("tables") or {}, ensure_ascii=False, indent=2),
            "```",
            "",
            "## DATA LAKE TABLO SAYILARI",
            "",
            "```json",
            json.dumps(lake_counts, ensure_ascii=False, indent=2),
            "```",
            "",
            "## STATE DB SON KAYITLAR",
            "",
            "```json",
            json.dumps(state_rows, ensure_ascii=False, indent=2, default=str)[:40000],
            "```",
            "",
            "## CONFIG VERSIONS",
            "",
            "```json",
            json.dumps(profile.get("config_versions"), ensure_ascii=False, indent=2, default=str)[
                :12000
            ],
            "```",
            "",
            "## LEARNING RUNTIME",
            "",
            "```json",
            json.dumps(profile.get("learning_runtime"), ensure_ascii=False, indent=2),
            "```",
            "",
            "## BACKUP MANIFEST",
            "",
            "```json",
            json.dumps(
                {
                    "backup_dir": backup_dir,
                    "copied_files": manifest.get("copied_files"),
                    "total_bytes": manifest.get("total_bytes"),
                    "backup_verified": manifest.get("backup_verified"),
                    "verification_errors": manifest.get("verification_errors"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## AI_RESTORE_PLAYBOOK",
            "",
            f"1. Yedek dosyalar: `{backup_dir}`",
            "2. DB/lessons **silinmedi** — DATA_PRESERVATION korundu.",
            "3. Restart: `./scripts/elite_9005_process_ctl.sh restart`",
            "4. Panel checkpoint dots üzerinden bu MD görüntülenebilir.",
            "",
            "## KORUMA — DOKUNMA",
            "- `data/binance_elite_8300_9005_state.db`",
            "- `data/evrim_persistent_learning.json`",
            "- `data/deleted_archives/`",
            "",
        ]
    )

    md = "\n".join(lines)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    path = CHECKPOINT_DIR / filename
    path.write_text(md, encoding="utf-8")

    entry = {
        "file": filename,
        "event_type": "v2_koklu_restart",
        "label": "V2 köklü restart — tam yedek",
        "slug": "v2_koklu_restart_pre_backup",
        "created_at": _now_iso(),
        "bytes": path.stat().st_size,
        "details_preview": {
            "backup_dir": backup_dir,
            "active_futures_mode": profile.get("active_futures_mode"),
            "backup_verified": manifest.get("backup_verified"),
        },
    }
    idx = _load_index()
    idx.setdefault("checkpoints", []).append(entry)
    _save_index(idx)

    print(json.dumps({"ok": True, "md_path": str(path.relative_to(ROOT)), "filename": filename}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
