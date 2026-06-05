"""
Evrim — tüm modlardan çapraz öğrenme (işlem kitapları sıfırlansa bile state korunur).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from elite_trader.panel_strategy import active_execution_mode, mode_order, resolve_mode_id

_ROOT = Path(__file__).resolve().parent.parent
_ARCHIVES = _ROOT / "data" / "mode_archives"
_MANIFEST = _ARCHIVES / "manifest.json"
_PARALLEL = _ROOT / "data" / "parallel_universes.json"
_STATE = _ROOT / "data" / "evrim_adaptive_state.json"

_seen_keys: set[str] = set()
_MAX_SEEN = 120_000


def _trade_key(mode_id: str, row: dict[str, Any]) -> str:
    return (
        f"{mode_id}:{row.get('id')}:{row.get('symbol')}:"
        f"{row.get('exit_time') or row.get('closed_at')}"
    )


def _pnl(row: dict[str, Any]) -> float:
    return float(row.get("final_pnl") or row.get("net_pnl") or 0)


def _load_state() -> dict[str, Any]:
    if not _STATE.is_file():
        return {}
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st: dict[str, Any]) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(
        json.dumps(st, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def collect_all_closed_trades() -> list[dict[str, Any]]:
    """Kitaplar + arşivler + SQLite — tüm modlar."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(mid: str, r: dict[str, Any]) -> None:
        key = _trade_key(mid, r)
        if key in seen:
            return
        seen.add(key)
        row = dict(r)
        row.setdefault("panel_mode", mid)
        row.setdefault("universe_id", mid)
        rows.append(row)

    try:
        from elite_trader.parallel_universe_engine import get_books

        for mid, book in (get_books() or {}).items():
            for c in book.get("closed") or []:
                add(mid, c)
    except Exception:
        pass

    if _PARALLEL.is_file():
        try:
            st = json.loads(_PARALLEL.read_text(encoding="utf-8"))
            for mid, book in (st.get("universes") or {}).items():
                for c in book.get("closed") or []:
                    add(mid, c)
        except Exception:
            pass

    if _MANIFEST.is_file():
        try:
            manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
            for ent in manifest.get("archives") or []:
                aid = ent.get("archive_id") or ""
                path = _ARCHIVES / aid / "trades.json"
                if not path.is_file():
                    continue
                mid = str(ent.get("mode_id") or aid.split("_")[0])
                data = json.loads(path.read_text(encoding="utf-8"))
                for c in data.get("closed") or []:
                    add(mid, c)
        except Exception:
            pass

    try:
        from elite_pro_state import load_closed

        for c in load_closed():
            mid = resolve_mode_id(
                str(
                    c.get("panel_mode")
                    or c.get("execution_mode_at_close")
                    or active_execution_mode()
                )
            )
            add(mid, c)
    except Exception:
        pass

    try:
        from elite_trader.learning_preservation import load_preserved_closed_trades

        for c in load_preserved_closed_trades():
            mid = resolve_mode_id(
                str(
                    c.get("panel_mode")
                    or c.get("universe_id")
                    or c.get("execution_mode_at_close")
                    or active_execution_mode()
                )
            )
            add(mid, c)
    except Exception:
        pass

    return rows


def _ingest_one(mode_id: str, closed: dict[str, Any]) -> bool:
    global _seen_keys
    key = _trade_key(mode_id, closed)
    if key in _seen_keys:
        return False
    _seen_keys.add(key)
    if len(_seen_keys) > _MAX_SEEN:
        _seen_keys.clear()
        _seen_keys.add(key)

    try:
        from elite_trader.evrim_opportunity import on_trade_closed_evrim

        on_trade_closed_evrim(
            closed,
            {"regime": closed.get("market_regime"), "source_mode": mode_id},
        )
    except Exception:
        pass
    return True


def observe_mode_trade_closed(mode_id: str, closed: dict[str, Any]) -> None:
    """Her mod kapanışında Evrim gözlemi (profil ayarlarına dokunmaz)."""
    mid = resolve_mode_id(mode_id)
    if not _ingest_one(mid, closed):
        return
    st = _load_state()
    obs = st.setdefault("cross_mode_observations", [])
    obs.append(
        {
            "mode_id": mid,
            "pnl": round(_pnl(closed), 4),
            "reason": str(closed.get("exit_reason") or "")[:24],
            "symbol": closed.get("symbol"),
        }
    )
    if len(obs) > 500:
        st["cross_mode_observations"] = obs[-500:]
    if mid == "berserk":
        try:
            from elite_trader.berserk_learning import get_suggestions

            st["berserk_suggestions"] = get_suggestions()
        except Exception:
            pass
    if mid == "hunter":
        try:
            from elite_trader.hunter_learning import get_suggestions

            st["hunter_suggestions"] = get_suggestions()
        except Exception:
            pass
    if mid == "chop_master":
        try:
            from elite_trader.chop_learning import get_suggestions

            st["chop_suggestions"] = get_suggestions()
        except Exception:
            pass
    if mid == "sentinel":
        try:
            from elite_trader.sentinel_benchmark import get_dashboard
            from elite_trader.sentinel_learning import snapshot_for_ui

            st["sentinel_suggestions"] = {
                "sentinel_learning_suggestions": snapshot_for_ui(),
                "sentinel_benchmark": get_dashboard().get("sentinel_benchmark") or {},
            }
        except Exception:
            pass
    _save_state(st)
    if mid == "evrim":
        try:
            from elite_trader.evrim_adaptive import on_trade_closed

            on_trade_closed(mid, closed)
        except Exception:
            pass
    try:
        from elite_trader.evrim_cross_strategy_lab import sync_trade_closed

        sync_trade_closed(mid, closed)
    except Exception:
        pass


def bootstrap_evrim_from_history(
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mevcut tüm mod verisini Evrim state'e işle (mode_profiles dokunulmaz)."""
    rows = rows if rows is not None else collect_all_closed_trades()
    n = 0
    by_mode: dict[str, int] = {}
    for row in rows:
        mid = resolve_mode_id(
            str(
                row.get("panel_mode")
                or row.get("universe_id")
                or row.get("execution_mode_at_close")
                or active_execution_mode()
            )
        )
        if _ingest_one(mid, row):
            n += 1
            by_mode[mid] = by_mode.get(mid, 0) + 1

    try:
        from elite_trader.evrim_adaptive import cross_mode_insights

        lessons = cross_mode_insights()
    except Exception:
        lessons = {"n": 0}

    st = _load_state()
    st["cross_mode_bootstrap"] = {
        "ingested": n,
        "by_mode": by_mode,
        "lessons_n": lessons.get("n", 0),
    }
    st["lessons"] = lessons
    _save_state(st)
    return {"ingested": n, "by_mode": by_mode, "lessons": lessons}


def ensure_evrim_session() -> None:
    """Bot açılışında öğrenme state'ini koru (sıfırlama yok)."""
    from datetime import datetime, timezone

    st = _load_state()
    if not st:
        st = {
            "session_started_at": datetime.now(timezone.utc).isoformat(),
            "tune_history": [],
            "lessons": {},
        }
    st.setdefault("tune_history", [])
    st.setdefault("lessons", {})
    st.setdefault("cross_mode_observations", [])
    try:
        from elite_trader.evrim_opportunity import _default_evolution
        from elite_trader.evrim_opportunity import _load_state as opp_load_state

        opp = opp_load_state()
        opp.setdefault("evolution", _default_evolution())
    except Exception:
        pass
    _save_state(st)


def read_cross_mode_summaries() -> dict[str, Any]:
    """Read-only cross-mode özetleri — yazma yok."""
    from elite_trader.evrim_meta_score import read_cross_mode_summaries as _read

    return _read()
