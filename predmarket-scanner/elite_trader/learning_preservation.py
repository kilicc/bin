"""Öğrenme modu — işlem silinse bile Evrim/LossLearner verisini korur."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
PRESERVE_DIR = _ROOT / "data" / "learning_preservation"
MASTER_PATH = PRESERVE_DIR / "evrim_master_learning.json"
LATEST_PATH = PRESERVE_DIR / "LATEST.json"

_COPY_LABELS: list[tuple[str, Path]] = [
    ("trade_lessons", _ROOT / "data" / "elite_9005_trade_lessons.json"),
    ("learning_registry", _ROOT / "data" / "elite_9005_learning_registry.json"),
    ("evrim_adaptive_state", _ROOT / "data" / "evrim_adaptive_state.json"),
    ("proposals", _ROOT / "data" / "elite_9005_proposals.json"),
    ("learned_formula", _ROOT / "data" / "learned_formula.json"),
    ("loss_postmortem_json", _ROOT / "data" / "elite_9005_loss_postmortem.json"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def export_learning_snapshot(*, reason: str = "") -> dict[str, Any]:
    """
    Tüm mod kapanışlarını + öğrenme dosyalarını tek pakette kaydet.
    Evrim bootstrap state güncellenir (silme sonrası okunabilir).
    """
    from elite_trader.evrim_cross_mode_learner import (
        bootstrap_evrim_from_history,
        collect_all_closed_trades,
    )
    from elite_trader.panel_strategy import mode_order

    PRESERVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = PRESERVE_DIR / f"snapshot_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)

    rows = collect_all_closed_trades()
    boot = bootstrap_evrim_from_history(rows)

    by_mode: dict[str, list[dict[str, Any]]] = {m: [] for m in mode_order()}
    for row in rows:
        mid = str(
            row.get("panel_mode")
            or row.get("universe_id")
            or row.get("execution_mode_at_close")
            or "evrim"
        )
        by_mode.setdefault(mid, []).append(row)

    copied: list[dict[str, Any]] = []
    for label, path in _COPY_LABELS:
        if not path.is_file():
            continue
        target = dest / path.name
        shutil.copy2(path, target)
        copied.append({"label": label, "file": path.name, "bytes": target.stat().st_size})

    trades_path = dest / "all_closed_trades.json"
    trades_path.write_text(
        json.dumps(
            {"closed": rows, "by_mode": {k: len(v) for k, v in by_mode.items()}},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    payload: dict[str, Any] = {
        "exported_at": _now_iso(),
        "reason": (reason or "").strip() or "learning_preservation",
        "closed_trades_total": len(rows),
        "closed_by_mode": {k: len(v) for k, v in by_mode.items()},
        "bootstrap": boot,
        "snapshot_dir": str(dest.relative_to(_ROOT)),
        "files": copied + [{"label": "all_closed_trades", "file": "all_closed_trades.json"}],
        "closed_trades": rows,
    }
    MASTER_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    LATEST_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (dest / "meta.json").write_text(
        json.dumps(
            {k: v for k, v in payload.items() if k != "closed_trades"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"  🧬 Öğrenme kaydı: {len(rows)} işlem · bootstrap {boot.get('ingested', 0)}"
    )
    print(f"      → {MASTER_PATH.relative_to(_ROOT)}")
    return payload


def load_preserved_closed_trades() -> list[dict[str, Any]]:
    """Silme sonrası öğrenme paketinden kapanışları oku."""
    path = MASTER_PATH if MASTER_PATH.is_file() else LATEST_PATH
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("closed_trades") or [])
    except Exception:
        return []


def reset_all_mode_books(*, reason: str = "") -> dict[str, Any]:
    """Tüm parallel mod kitaplarını sıfırla (ayar dosyalarına dokunmaz)."""
    from elite_trader.mode_data_archive import archive_mode, reset_parallel_universe
    from elite_trader.panel_strategy import mode_order

    archived: list[str] = []
    reset: list[dict[str, Any]] = []
    for mid in mode_order():
        try:
            meta = archive_mode(mid, reason=reason or "fresh_start", trigger="preserve_reset")
            archived.append(meta.get("archive_id") or mid)
        except Exception as exc:
            print(f"  ⚠ arşiv {mid}: {exc}")
        try:
            reset.append(reset_parallel_universe(mid))
        except Exception as exc:
            print(f"  ⚠ sıfırla {mid}: {exc}")
    return {"archived": archived, "resets": reset}
