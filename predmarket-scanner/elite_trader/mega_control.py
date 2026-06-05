"""MEGA desk control — pause / start / restart state machine."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from elite_trader.mega_live import (
    clear_mega_closed_records,
    close_mega_position,
    mega_instance_data_dir,
    mega_motor_active,
)

_STATE_FILE = "mega_control_state.json"
_lock = threading.RLock()
_state: str = "RUNNING"
_pausing_since: float | None = None
_restart_in_progress = False


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def pause_closes_positions() -> bool:
    """True → PAUSING sırasında kâr/breakeven pozisyonları kapat (eski davranış)."""
    return _env_bool("MEGA_PAUSE_CLOSE_POSITIONS", False)


def soft_pause_enabled() -> bool:
    """True → Pause: yalnızca yeni giriş durur; açık pozisyonlara dokunulmaz."""
    return _env_bool("MEGA_PAUSE_SOFT", True)


def _state_path():
    return mega_instance_data_dir() / _STATE_FILE


def _audit_path():
    return mega_instance_data_dir() / "control_audit.jsonl"


def _load_persisted() -> None:
    global _state, _pausing_since
    p = _state_path()
    if not p.is_file():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        _state = str(data.get("state") or "RUNNING").upper()
        ps = data.get("pausing_since")
        _pausing_since = float(ps) if ps is not None else None
    except Exception:
        pass


def _save_persisted() -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "state": _state,
                "pausing_since": _pausing_since,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


_load_persisted()


def audit_log(event: str, **fields: Any) -> None:
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    ap = _audit_path()
    ap.parent.mkdir(parents=True, exist_ok=True)
    with ap.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def control_state() -> str:
    with _lock:
        return _state


def allow_new_entries() -> bool:
    return control_state() == "RUNNING"


def entry_block_reason() -> str:
    """Panel uyarısı — neden yeni giriş kapalı (rejim kilidi değilse belirt)."""
    try:
        from elite_trader.mega_boot_observe import boot_entry_block_reason

        boot_br = boot_entry_block_reason()
        if boot_br:
            return boot_br
    except Exception:
        pass
    st = control_state()
    if st == "RUNNING":
        try:
            from elite_trader.mega_direction_guard import btc_context_ready

            ready, tag = btc_context_ready()
            if not ready:
                return tag or "btc_context_not_ready"
        except Exception:
            pass
        return ""
    if st == "PAUSED":
        return "control_paused"
    if st == "PAUSING":
        return "control_pausing"
    if st == "RESTARTING":
        return "control_restarting"
    return f"control_{st.lower()}"


def _position_net(pos: dict[str, Any]) -> float:
    from elite_trader.fee_economics import estimate_close_pnl

    gross = float(pos.get("unrealized_pnl") or 0)
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    est = estimate_close_pnl(gross, stake, lev, pos=pos)
    return float(est.get("final_pnl") or est.get("net_pnl") or gross)


def _pending_losers() -> int:
    from elite_trader.mega_live import _mega_positions

    n = 0
    for pos in _mega_positions:
        if _position_net(pos) < 0:
            n += 1
    return n


def get_status() -> dict[str, Any]:
    st = control_state()
    pause_max = _env_float("MEGA_PAUSE_MAX_SEC", 86400.0)
    pause_warn = False
    if _pausing_since and st == "PAUSING":
        pause_warn = (time.time() - _pausing_since) > pause_max
    return {
        "state": st,
        "pausing_since": _pausing_since,
        "pausing_since_iso": (
            datetime.fromtimestamp(_pausing_since, tz=timezone.utc).isoformat()
            if _pausing_since
            else None
        ),
        "pending_losers": _pending_losers() if st in ("PAUSING", "PAUSED") else 0,
        "pause_warn": pause_warn,
        "buttons": {
            "pause": st == "RUNNING",
            "start": st == "PAUSED",
            "restart": st in ("RUNNING", "PAUSING", "PAUSED"),
        },
        "motor_active": mega_motor_active(),
    }


def request_pause() -> dict[str, Any]:
    global _state, _pausing_since
    with _lock:
        if _state == "RUNNING":
            if soft_pause_enabled() and not pause_closes_positions():
                _state = "PAUSED"
                _pausing_since = None
                audit_log("pause_soft", note="no_position_closes")
            else:
                _state = "PAUSING"
                _pausing_since = time.time()
                audit_log("pause_started")
            _save_persisted()
        return get_status()


def request_start() -> dict[str, Any]:
    global _state, _pausing_since
    with _lock:
        if _state == "PAUSED":
            _state = "RUNNING"
            _pausing_since = None
            _save_persisted()
            audit_log("start")
        return get_status()


def _force_close_all(reason: str = "CONTROL-RESTART") -> int:
    from elite_trader.mega_live import _mega_positions

    closed = 0
    for pos in list(_mega_positions):
        pid = int(pos["id"])
        if close_mega_position(pid, reason):
            closed += 1
            audit_log("force_close", position_id=pid, symbol=pos.get("symbol"), reason=reason)
    return closed


def request_restart() -> dict[str, Any]:
    global _state, _pausing_since, _restart_in_progress
    with _lock:
        if _restart_in_progress:
            return get_status()
        _restart_in_progress = True
        _state = "RESTARTING"
        _save_persisted()
        audit_log("restart_started")
    try:
        n = _force_close_all("CONTROL-RESTART")
        try:
            from elite_trader.mode_data_archive import archive_mode

            archive_mode("mega", reason="9007_control_restart")
        except Exception:
            pass
        clear_mega_closed_records(suppress_backfill=True)
        try:
            sp = mega_instance_data_dir() / "mega_live_session.json"
            if sp.is_file():
                sp.unlink(missing_ok=True)
        except Exception:
            pass
        audit_log("restart_done", closed=n)
        try:
            from elite_trader.mega_boot_observe import reset_boot_clock
            from elite_trader.mega_market_regime import reset_instance_state

            reset_boot_clock()
            reset_instance_state()
        except Exception:
            pass
    finally:
        with _lock:
            _state = "RUNNING"
            _pausing_since = None
            _restart_in_progress = False
            _save_persisted()
    return get_status()


def request_data_wipe(
    *,
    reason: str = "panel_reset",
    capital: float = 5000.0,
    close_exchange: bool = True,
) -> dict[str, Any]:
    """Durdur → borsa flatten (kayıtsız) → arşivle/sil → PAUSED."""
    global _state, _pausing_since, _restart_in_progress
    with _lock:
        _state = "PAUSED"
        _pausing_since = None
        _restart_in_progress = False
        _save_persisted()
        audit_log("data_wipe_started", reason=reason[:120])
    try:
        from elite_trader.mega_live import reset_mega_session_data

        reset_result = reset_mega_session_data(
            reason=reason,
            capital=capital,
            close_exchange=close_exchange,
        )
        audit_log("data_wipe_done", archive=reset_result.get("archive"))
    except Exception as exc:
        audit_log("data_wipe_error", error=str(exc)[:200])
        raise
    return {**get_status(), "reset": reset_result}


def apply_pause_exits(
    bulk: dict[str, float],
    *,
    close_fn: Callable[[int, str], bool] | None = None,
) -> None:
    """İsteğe bağlı — PAUSING: kâr/breakeven kapat (varsayılan kapalı, MEGA_PAUSE_SOFT)."""
    global _state, _pausing_since
    if not pause_closes_positions():
        st = control_state()
        if st == "PAUSING" and soft_pause_enabled():
            with _lock:
                _state = "PAUSED"
                _pausing_since = None
                _save_persisted()
                audit_log("pause_complete", mode="soft_skip_exits")
        return
    from elite_trader.mega_live import _apply_price_tick, _mega_positions

    st = control_state()
    if st != "PAUSING":
        return
    _close = close_fn or close_mega_position
    for pos in list(_mega_positions):
        _apply_price_tick(pos, bulk)
        net = _position_net(pos)
        sym = str(pos.get("symbol") or "")
        if net > 0:
            if _close(int(pos["id"]), "CONTROL-PAUSE-WIN"):
                audit_log("pause_closed_winner", symbol=sym, net=round(net, 4))
        elif net >= 0:
            if _close(int(pos["id"]), "CONTROL-PAUSE-BE"):
                audit_log("pause_closed_breakeven", symbol=sym, net=round(net, 4))
    if not _mega_positions and control_state() == "PAUSING":
        with _lock:
            _state = "PAUSED"
            _pausing_since = None
            _save_persisted()
            audit_log("pause_complete")
