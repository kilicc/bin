"""Plan panosu — mod kimlikleri, günlük hedefler, analiz ufukları."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from elite_trader.mode_registry import DEFAULT_ACTIVE_FUTURES_MODE
from elite_trader.panel_strategy import mode_catalog, mode_order

_ROOT = Path(__file__).resolve().parent.parent
_GOALS_PATH = _ROOT / "data/plan_mode_goals.json"

LIVE_ID = DEFAULT_ACTIVE_FUTURES_MODE
PARALLEL_IDS = tuple(mode_order())

# Analiz pencereleri (saniye) — Cursor her döngüde hepsini özetler
ANALYSIS_HORIZONS: list[tuple[str, str, int]] = [
    ("1h", "Son 1 saat", 3600),
    ("24h", "Son 24 saat", 86400),
    ("7d", "Son 7 gün", 7 * 86400),
    ("30d", "Son 30 gün", 30 * 86400),
    ("365d", "Son 1 yıl", 365 * 86400),
]

INSIGHTS_CHAT_ID = "__insights__"
INSIGHTS_TITLE = "Anlık öneriler ve teklifler"

_DEFAULT_GOALS: dict[str, dict[str, Any]] = {
    "evrim": {
        "label": "Evrim",
        "daily_pnl_target_usd": 80,
        "daily_max_loss_usd": -120,
        "win_rate_target_pct": 78,
        "max_loss_trades_day": 8,
        "daily_equity_mult_target": 2.0,
        "hourly_pnl_velocity_pct": 4.0,
    },
    "hunter": {
        "label": "Avcı",
        "daily_pnl_target_usd": 40,
        "daily_max_loss_usd": -80,
        "win_rate_target_pct": 75,
        "max_loss_trades_day": 10,
    },
    "berserk": {
        "label": "Berserk",
        "daily_pnl_target_usd": 35,
        "daily_max_loss_usd": -70,
        "win_rate_target_pct": 72,
        "max_loss_trades_day": 12,
    },
    "chop_master": {
        "label": "Chop Master",
        "daily_pnl_target_usd": 25,
        "daily_max_loss_usd": -60,
        "win_rate_target_pct": 68,
        "max_loss_trades_day": 8,
    },
    "sentinel": {
        "label": "Sentinel",
        "daily_pnl_target_usd": 50,
        "daily_max_loss_usd": -50,
        "win_rate_target_pct": 80,
        "max_loss_trades_day": 6,
    },
}


def all_plan_mode_ids() -> list[str]:
    return list(PARALLEL_IDS)


def normalize_mode_id(mode_id: str | None) -> str:
    from elite_trader.mode_registry import resolve_mode_id

    mid = resolve_mode_id(str(mode_id or LIVE_ID).strip())
    if mid in all_plan_mode_ids():
        return mid
    return LIVE_ID


def mode_label(mode_id: str) -> str:
    cat = mode_catalog()
    if mode_id in cat:
        return cat[mode_id].get("label") or mode_id
    g = load_goals().get(mode_id) or {}
    return g.get("label") or mode_id


def insights_chat_id(mode_id: str | None = None) -> str:
    """Mod başına kalıcı öneri sohbeti (aynı id, farklı klasör)."""
    return INSIGHTS_CHAT_ID


def load_goals() -> dict[str, dict[str, Any]]:
    if _GOALS_PATH.is_file():
        try:
            data = json.loads(_GOALS_PATH.read_text(encoding="utf-8"))
            modes = data.get("modes") or data
            if isinstance(modes, dict):
                return {**_DEFAULT_GOALS, **modes}
        except Exception:
            pass
    return dict(_DEFAULT_GOALS)


def save_goals(goals: dict[str, dict[str, Any]]) -> None:
    _GOALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GOALS_PATH.write_text(
        json.dumps({"modes": goals}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def cycle_interval_sec() -> int:
    return int(os.getenv("ELITE_PLAN_CYCLE_MIN", "45") or "45") * 60
