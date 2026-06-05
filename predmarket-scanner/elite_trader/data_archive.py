"""9005 veri silme — önce arşivle, manifest'e yaz (geri dönüş listesi)."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_ROOT = _ROOT / "data" / "deleted_archives"
MANIFEST_PATH = ARCHIVE_ROOT / "manifest.json"

# 9005 deney verisi — reset/silmede varsayılan korunur
BUNDLE_9005: list[tuple[str, Path]] = [
    ("state_db", _ROOT / "data" / "binance_elite_8300_9005_state.db"),
    ("trade_lessons", _ROOT / "data" / "elite_9005_trade_lessons.json"),
    ("learning_registry", _ROOT / "data" / "elite_9005_learning_registry.json"),
    ("proposals", _ROOT / "data" / "elite_9005_proposals.json"),
    ("sl_emergency_registry", _ROOT / "data" / "elite_sl_emergency_registry.json"),
    ("loss_postmortem_json", _ROOT / "data" / "elite_9005_loss_postmortem.json"),
    ("loss_postmortem_md", _ROOT / "data" / "elite_9005_loss_postmortem.md"),
    ("parallel_universes", _ROOT / "data" / "parallel_universes.json"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(s: str, max_len: int = 40) -> str:
    t = re.sub(r"[^a-zA-Z0-9]+", "_", (s or "no_reason").strip())[:max_len]
    return t.strip("_") or "no_reason"


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        return {"archives": [], "updated_at": None}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"archives": [], "updated_at": None}


def _save_manifest(data: dict[str, Any]) -> None:
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    archives = data.get("archives") or []
    if len(archives) > 80:
        data["archives"] = archives[-80:]
    MANIFEST_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def list_archives(*, limit: int = 30) -> list[dict[str, Any]]:
    data = _load_manifest()
    archives = list(data.get("archives") or [])
    archives.sort(key=lambda x: x.get("deleted_at") or "", reverse=True)
    return archives[:limit]


def archive_9005_bundle(
    *,
    reason: str,
    trigger: str = "user",
    extra_paths: list[Path] | None = None,
) -> dict[str, Any]:
    """
    Mevcut 9005 veri dosyalarını arşivle.
    trigger: user | reset_script | api
    """
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    archive_id = f"9005_{stamp}_{_slug(reason)}"
    dest = ARCHIVE_ROOT / archive_id
    dest.mkdir(parents=True, exist_ok=True)

    files_meta: list[dict[str, Any]] = []
    for label, path in BUNDLE_9005:
        if not path.is_file():
            continue
        target = dest / path.name
        shutil.copy2(path, target)
        size = target.stat().st_size
        extra: dict[str, Any] = {"label": label, "file": path.name, "bytes": size}
        if label == "state_db":
            try:
                import sqlite3

                conn = sqlite3.connect(str(path))
                n = conn.execute("SELECT COUNT(*) FROM closed_trades").fetchone()[0]
                conn.close()
                extra["closed_trades_count"] = int(n)
            except Exception:
                pass
        if label == "parallel_universes":
            try:
                pu = json.loads(path.read_text(encoding="utf-8"))
                n = sum(
                    len((u or {}).get("closed") or [])
                    for u in (pu.get("universes") or {}).values()
                    if isinstance(u, dict)
                )
                extra["parallel_closed_count"] = int(n)
            except Exception:
                pass
        files_meta.append(extra)
        for wal in (path.parent / f"{path.name}-wal", path.parent / f"{path.name}-shm"):
            if wal.is_file():
                shutil.copy2(wal, dest / wal.name)

    for ep in extra_paths or []:
        if ep.is_file():
            shutil.copy2(ep, dest / ep.name)
            files_meta.append({"label": "extra", "file": ep.name, "bytes": ep.stat().st_size})

    meta = {
        "archive_id": archive_id,
        "port": 9005,
        "deleted_at": _now_iso(),
        "reason": reason.strip() or "(neden belirtilmedi)",
        "trigger": trigger,
        "path": str(dest.relative_to(_ROOT)),
        "files": files_meta,
        "recover_hint": f"cp -a {dest}/* predmarket-scanner/data/  # dosya bazlı geri yükle",
    }
    (dest / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = _load_manifest()
    manifest.setdefault("archives", []).append(meta)
    _save_manifest(manifest)

    print(f"  📦 Arşiv: {archive_id}")
    print(f"      Neden: {meta['reason']}")
    print(f"      Dosya: {len(files_meta)} | Liste: data/deleted_archives/manifest.json")
    return meta


def archive_single_closed_trade(
    row: dict[str, Any],
    *,
    reason: str = "panel_row_delete",
    trigger: str = "panel",
) -> dict[str, Any]:
    """Panel satır silme — tek işlem JSON arşivi + manifest kaydı."""
    ts = datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    tid = int(row.get("id") or 0)
    sym = str(row.get("symbol") or "UNK").upper()
    archive_id = f"9005_trade_{tid}_{sym}_{stamp}"
    dest = ARCHIVE_ROOT / "single_trades" / archive_id
    dest.mkdir(parents=True, exist_ok=True)
    trade_path = dest / "closed_trade.json"
    trade_path.write_text(
        json.dumps(row, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    meta = {
        "archive_id": archive_id,
        "kind": "single_closed_trade",
        "port": 9005,
        "deleted_at": _now_iso(),
        "reason": (reason or "panel_row_delete").strip(),
        "trigger": trigger,
        "trade_id": tid,
        "symbol": sym,
        "exit_time": str(row.get("exit_time") or row.get("closed_at") or ""),
        "path": str(dest.relative_to(_ROOT)),
        "files": [{"label": "closed_trade", "file": "closed_trade.json", "bytes": trade_path.stat().st_size}],
    }
    (dest / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = _load_manifest()
    manifest.setdefault("archives", []).append(meta)
    _save_manifest(manifest)
    return meta


_ARCHIVE_ID_RE = re.compile(r"^9005_\d{8}T\d{6}Z_[A-Za-z0-9_]+$")


def archive_dir(archive_id: str) -> Path | None:
    aid = (archive_id or "").strip()
    if not _ARCHIVE_ID_RE.match(aid):
        return None
    dest = ARCHIVE_ROOT / aid
    return dest if dest.is_dir() else None


def load_archive_meta(archive_id: str) -> dict[str, Any] | None:
    dest = archive_dir(archive_id)
    if not dest:
        return None
    meta_path = dest / "meta.json"
    if meta_path.is_file():
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def load_archive_closed_trades(archive_id: str) -> list[dict[str, Any]]:
    """Arşivlenmiş state DB'den kapanmış işlemler."""
    dest = archive_dir(archive_id)
    if not dest:
        return []
    db = dest / "binance_elite_8300_9005_state.db"
    if not db.is_file():
        return []
    import sqlite3

    out: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT payload FROM closed_trades ORDER BY id ASC"
        ).fetchall()
        conn.close()
        for r in rows:
            try:
                out.append(json.loads(r[0]))
            except json.JSONDecodeError:
                continue
    except Exception:
        return []
    return out


def archive_detail(archive_id: str) -> dict[str, Any] | None:
    meta = load_archive_meta(archive_id)
    if not meta:
        return None
    trades = load_archive_closed_trades(archive_id)
    wins = sum(1 for t in trades if float(t.get("final_pnl") or 0) > 0)
    return {
        "meta": meta,
        "closed_trades": trades,
        "summary": {
            "count": len(trades),
            "wins": wins,
            "losses": len(trades) - wins,
            "total_final_pnl": round(
                sum(float(t.get("final_pnl") or 0) for t in trades), 2
            ),
        },
    }


def snapshot_archives_for_ui(*, limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for a in list_archives(limit=limit):
        ct = next(
            (
                f.get("closed_trades_count")
                for f in a.get("files") or []
                if f.get("closed_trades_count") is not None
            ),
            None,
        )
        out.append(
            {
                "archive_id": a.get("archive_id"),
                "deleted_at": a.get("deleted_at"),
                "reason": a.get("reason"),
                "trigger": a.get("trigger"),
                "closed_trades_count": ct,
            }
        )
    return out


def wipe_9005_with_archive(*, reason: str, trigger: str = "panel") -> dict[str, Any]:
    """Arşivle + dosyaları sil + paralel mod kitaplarını sıfırla."""
    meta = archive_9005_bundle(reason=reason, trigger=trigger)
    meta["removed_files"] = remove_9005_files_after_archive()
    meta["parallel_universes"] = _rebuild_parallel_universes_fresh()
    return meta


def _rebuild_parallel_universes_fresh() -> dict[str, Any]:
    import os

    from elite_trader.parallel_universe_engine import wipe_all_universes_fresh

    try:
        cap = float(os.getenv("STARTING_BALANCE", "5000"))
    except ValueError:
        cap = 5000.0
    out = wipe_all_universes_fresh(cap)
    print(
        f"  ✓ parallel_universes.json sıfırlandı "
        f"(başlangıç ${out.get('starting_capital', cap):,.2f}, "
        f"{out.get('modes_reset', 0)} mod)"
    )
    return out


def remove_9005_files_after_archive() -> list[str]:
    """Arşiv sonrası kaynak dosyaları sil (DB wal/shm dahil)."""
    removed: list[str] = []
    for _label, path in BUNDLE_9005:
        for p in (path, path.parent / f"{path.name}-wal", path.parent / f"{path.name}-shm"):
            if p.is_file():
                p.unlink()
                removed.append(str(p.relative_to(_ROOT)))
    return removed
