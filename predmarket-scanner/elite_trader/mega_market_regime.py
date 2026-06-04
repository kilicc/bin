"""MEGA — piyasa durumu kaydı + otomatik giriş eşiği seçimi (quiet / normal / active)."""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_boot_at = time.time()
_state: dict[str, Any] = {
    "regime": "normal",
    "since": 0.0,
    "samples": [],
    "history": [],
    "last_open_at": 0.0,
    "transition_active": False,
    "transition_since": 0.0,
    "transition_reason": "",
}

_ROOT = Path(__file__).resolve().parent.parent
_LEGACY_STATE_PATH = _ROOT / "data" / "mega_market_regime.json"
_MAX_SAMPLES = 120
_MAX_HISTORY = 200


def mega_sim_paper_only() -> bool:
    """9006 paper sim — canlı emir yok, rejim kilidi varsayılan kapalı."""
    sim = os.getenv("MEGA_SIM_ENABLED", "0").strip().lower() in ("1", "true", "yes")
    live = os.getenv("MEGA_LIVE_ORDERS", "0").strip().lower() in ("1", "true", "yes")
    return sim and not live


def _state_path() -> Path:
    """9006/9007 ayrı rejim dosyası — paylaşımlı global state çapraz kilitleme yapmasın."""
    try:
        from elite_trader.mega_live import mega_instance_data_dir, mega_instance_id

        iid = mega_instance_id()
        if iid in ("9006", "9007"):
            inst_dir = mega_instance_data_dir()
            inst_path = inst_dir / "mega_market_regime.json"
            legacy = _LEGACY_STATE_PATH
            if not inst_path.is_file():
                inst_dir.mkdir(parents=True, exist_ok=True)
                if iid == "9007" and legacy.is_file():
                    try:
                        inst_path.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
                    except Exception:
                        pass
            return inst_path
    except Exception:
        pass
    return _LEGACY_STATE_PATH


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return _env_bool("MEGA_REGIME_AUTO", True)


def transition_enabled() -> bool:
    return _env_bool("MEGA_IDLE_TRANSITION", True)


def idle_open_threshold_sec() -> float:
    return _env_float("MEGA_IDLE_OPEN_SEC", 300.0)


def _profiles() -> dict[str, dict[str, float]]:
    """Rejim profilleri — env ile override edilebilir."""
    return {
        "quiet": {
            "hot_min_move": _env_float("MEGA_REGIME_QUIET_HOT_MOVE", 0.022),
            "warm_min_move": _env_float("MEGA_REGIME_QUIET_WARM_MOVE", 0.032),
            "hot_min_score": _env_float("MEGA_REGIME_QUIET_HOT_SCORE", 40.0),
            "warm_min_score_delta": 5.0,
            "edge_hot": _env_float("MEGA_REGIME_QUIET_EDGE_HOT", 0.58),
            "edge_warm": _env_float("MEGA_REGIME_QUIET_EDGE_WARM", 0.72),
        },
        "normal": {
            "hot_min_move": _env_float("MEGA_VOL_HOT_MIN_MOVE_PCT", 0.032),
            "warm_min_move": _env_float("MEGA_VOL_WARM_MIN_MOVE_PCT", 0.044),
            "hot_min_score": _env_float("MEGA_VOL_HOT_MIN_SCORE", 42.0),
            "warm_min_score_delta": 5.0,
            "edge_hot": _env_float("MEGA_VOL_EDGE_RELAX_HOT", 0.70),
            "edge_warm": _env_float("MEGA_VOL_EDGE_RELAX_WARM", 0.82),
        },
        "active": {
            "hot_min_move": _env_float("MEGA_REGIME_ACTIVE_HOT_MOVE", 0.038),
            "warm_min_move": _env_float("MEGA_REGIME_ACTIVE_WARM_MOVE", 0.050),
            "hot_min_score": _env_float("MEGA_REGIME_ACTIVE_HOT_SCORE", 44.0),
            "warm_min_score_delta": 3.0,
            "edge_hot": _env_float("MEGA_REGIME_ACTIVE_EDGE_HOT", 0.75),
            "edge_warm": _env_float("MEGA_REGIME_ACTIVE_EDGE_WARM", 0.85),
        },
        "transition": {
            "hot_min_move": _env_float("MEGA_TRANSITION_HOT_MOVE", 0.018),
            "warm_min_move": _env_float("MEGA_TRANSITION_WARM_MOVE", 0.026),
            "hot_min_score": _env_float("MEGA_TRANSITION_HOT_SCORE", 36.0),
            "warm_min_score_delta": 6.0,
            "edge_hot": _env_float("MEGA_TRANSITION_EDGE_HOT", 0.28),
            "edge_warm": _env_float("MEGA_TRANSITION_EDGE_WARM", 0.38),
        },
        "seek": {
            "hot_min_move": _env_float("MEGA_SEEK_HOT_MOVE", 0.015),
            "warm_min_move": _env_float("MEGA_SEEK_WARM_MOVE", 0.022),
            "hot_min_score": _env_float("MEGA_SEEK_HOT_SCORE", 28.0),
            "warm_min_score_delta": 8.0,
            "edge_hot": _env_float("MEGA_SEEK_EDGE_HOT", 0.22),
            "edge_warm": _env_float("MEGA_SEEK_EDGE_WARM", 0.30),
        },
    }


def _load_disk() -> None:
    global _state
    path = _state_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _state.update(data)
    except Exception:
        pass


def _save_disk() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    snap = dict(_state)
    snap["updated_at"] = time.time()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _bootstrap_last_open_if_needed() -> None:
    """Diskte last_open_at yoksa son MEGA işlem zamanını kullan (geçiş modu için)."""
    with _lock:
        if float(_state.get("last_open_at") or 0) > 0:
            return
    best = 0.0
    closed_path = _ROOT / "data" / "mega_live_closed.json"
    if closed_path.is_file():
        try:
            raw = json.loads(closed_path.read_text(encoding="utf-8"))
            rows = raw if isinstance(raw, list) else list(raw.get("closed") or [])
            for row in rows:
                et = float(row.get("entry_time") or row.get("exit_time") or 0)
                if et > best:
                    best = et
        except Exception:
            pass
    if best <= 0:
        return
    with _lock:
        _state["last_open_at"] = best
        _save_disk()


_bootstrap_last_open_if_needed()


def _reject_mix() -> dict[str, float]:
    try:
        from elite_trader.mode_reject_buffer import get_rejects

        rows = get_rejects("mega", limit=80)
    except Exception:
        return {}
    if not rows:
        return {}
    ctr = Counter(str(r.get("reason") or "unknown") for r in rows)
    total = sum(ctr.values()) or 1
    return {k: v / total for k, v in ctr.items()}


def _last_open_at() -> float:
    with _lock:
        ts = float(_state.get("last_open_at") or 0)
    if ts > 0:
        return ts
    return _boot_at


def lock_until_full_enabled() -> bool:
    if mega_sim_paper_only() and not _env_bool("MEGA_REGIME_LOCK_SIM", False):
        return False
    return _env_bool("MEGA_REGIME_LOCK_UNTIL_FULL", True)


def lock_live_transition() -> bool:
    """Kilitliyken geçiş eşiklerini canlı red dağılımına göre güncelle."""
    return _env_bool("MEGA_REGIME_LOCK_LIVE_TRANSITION", True)


def _slot_counts() -> tuple[int, int]:
    try:
        from elite_trader.mega_live import max_open_slots, open_position_count

        return open_position_count(), max_open_slots()
    except Exception:
        return 0, 4


def _regime_locked() -> bool:
    if not lock_until_full_enabled():
        return False
    with _lock:
        return bool(_state.get("regime_locked"))


def _sync_regime_lock(*, open_count: int | None = None, max_open: int | None = None) -> None:
    """İlk slotta rejimi dondur; tüm slotlar boşalınca kilidi aç."""
    if not lock_until_full_enabled():
        return
    n = int(open_count if open_count is not None else _slot_counts()[0])
    with _lock:
        if n <= 0:
            if _state.get("regime_locked"):
                _state["regime_locked"] = False
                for k in (
                    "locked_regime",
                    "locked_transition",
                    "locked_transition_reason",
                    "locked_at",
                ):
                    _state.pop(k, None)
                _save_disk()
            return
        already_locked = bool(_state.get("regime_locked"))
    if n >= 1 and not already_locked:
        mix = _reject_mix()
        trans = _transition_status(mix)
        with _lock:
            if not _state.get("regime_locked"):
                _state["regime_locked"] = True
                _state["locked_regime"] = str(_state.get("regime") or "normal")
                _state["locked_transition"] = bool(trans.get("active"))
                _state["locked_transition_reason"] = str(trans.get("reason") or "")
                _state["locked_at"] = time.time()
                _save_disk()


def record_slots_empty() -> None:
    """Son pozisyon kapandı — rejim kilidini kaldır."""
    _sync_regime_lock(open_count=0)


def _locked_base_regime() -> str | None:
    if not _regime_locked():
        return None
    with _lock:
        return str(_state.get("locked_regime") or _state.get("regime") or "normal")


def _locked_transition_active() -> bool:
    if not _regime_locked():
        return False
    with _lock:
        return bool(_state.get("locked_transition"))


def _locked_transition_reason() -> str:
    with _lock:
        return str(_state.get("locked_transition_reason") or "idle_blend")


def record_open(
    *,
    symbol: str = "",
    side: str = "",
    open_count: int | None = None,
    max_open: int | None = None,
) -> None:
    """MEGA açılışı — slot dolana kadar tarama rejimini değiştirme."""
    n = int(open_count if open_count is not None else _slot_counts()[0])
    mx = int(max_open if max_open is not None else _slot_counts()[1])
    mx = max(1, mx)
    _sync_regime_lock(open_count=n, max_open=mx)

    # Slot dolana kadar idle/geçiş modunu koru (her açılışta seek kapanmasın)
    if lock_until_full_enabled() and 0 < n < mx:
        return

    now = time.time()
    with _lock:
        was_trans = bool(_state.get("transition_active"))
        _state["last_open_at"] = now
        _state["transition_active"] = False
        _state["transition_since"] = 0.0
        _state["transition_reason"] = ""
        if was_trans:
            hist = list(_state.get("history") or [])
            hist.append(
                {
                    "ts": now,
                    "from": "transition",
                    "to": "open_reset",
                    "symbol": symbol,
                    "side": side,
                    "open_count": n,
                    "max_open": mx,
                }
            )
            _state["history"] = hist[-_MAX_HISTORY:]
        _save_disk()


def _classify_regime(
    *,
    median_hot_move: float,
    max_hot_move: float,
    hot_n: int,
    reject_mix: dict[str, float],
) -> str:
    move_small = float(reject_mix.get("mega_move_too_small") or 0)
    edge_low = float(reject_mix.get("mega_edge_low") or 0)

    quiet_med = _env_float("MEGA_REGIME_QUIET_MEDIAN_PCT", 0.012)
    active_med = _env_float("MEGA_REGIME_ACTIVE_MEDIAN_PCT", 0.045)
    active_max = _env_float("MEGA_REGIME_ACTIVE_MAX_PCT", 0.080)

    if hot_n <= 0:
        if move_small >= 0.55:
            return "quiet"
        return "normal"

    if median_hot_move < quiet_med and (move_small >= 0.45 or median_hot_move < quiet_med * 0.7):
        return "quiet"
    if median_hot_move >= active_med or max_hot_move >= active_max:
        return "active"
    if edge_low >= 0.35 and median_hot_move >= quiet_med * 1.5:
        return "active"
    return "normal"


def _transition_reason(reject_mix: dict[str, float]) -> str:
    edge_low = float(reject_mix.get("mega_edge_low") or 0)
    move_small = float(reject_mix.get("mega_move_too_small") or 0)
    score_low = float(reject_mix.get("mega_score_low") or 0)
    if score_low >= 0.12 and score_low >= edge_low:
        return "score_pressure"
    if edge_low >= 0.22 and move_small >= 0.35:
        return "idle_blend"
    if edge_low >= max(move_small, 0.22):
        return "edge_pressure"
    if move_small >= 0.45:
        return "move_pressure"
    return "idle_blend"


def _merge_transition_profile(
    base: dict[str, float],
    trans: dict[str, float],
    reason: str,
) -> dict[str, float]:
    """Geçiş modu — piyasa/red profiline göre en gevşek eşikleri seç."""
    out = dict(base)
    if reason == "edge_pressure":
        out["edge_hot"] = min(float(base["edge_hot"]), float(trans["edge_hot"]))
        out["edge_warm"] = min(float(base["edge_warm"]), float(trans["edge_warm"]))
        out["hot_min_score"] = min(float(base["hot_min_score"]), float(trans["hot_min_score"]))
        out["warm_min_score_delta"] = max(
            float(base.get("warm_min_score_delta") or 5),
            float(trans.get("warm_min_score_delta") or 6),
        )
        return out
    if reason == "move_pressure":
        out["hot_min_move"] = min(float(base["hot_min_move"]), float(trans["hot_min_move"]))
        out["warm_min_move"] = min(float(base["warm_min_move"]), float(trans["warm_min_move"]))
        return out
    if reason == "score_pressure":
        out["hot_min_score"] = min(float(base["hot_min_score"]), float(trans["hot_min_score"]), 36.0)
        out["warm_min_score_delta"] = max(
            float(base.get("warm_min_score_delta") or 5),
            float(trans.get("warm_min_score_delta") or 6),
        )
        out["edge_hot"] = min(float(base["edge_hot"]), float(trans["edge_hot"]))
        out["edge_warm"] = min(float(base["edge_warm"]), float(trans["edge_warm"]))
        out["hot_min_move"] = min(float(base["hot_min_move"]), float(trans["hot_min_move"]))
        out["warm_min_move"] = min(float(base["warm_min_move"]), float(trans["warm_min_move"]))
        return out
    for key in ("hot_min_move", "warm_min_move", "hot_min_score", "edge_hot", "edge_warm"):
        out[key] = min(float(base[key]), float(trans[key]))
    out["warm_min_score_delta"] = max(
        float(base.get("warm_min_score_delta") or 5),
        float(trans.get("warm_min_score_delta") or 6),
    )
    return out


def _transition_status(reject_mix: dict[str, float]) -> dict[str, Any]:
    if _regime_locked() and not lock_live_transition():
        if _locked_transition_active():
            with _lock:
                trans_since = float(
                    _state.get("transition_since") or _state.get("locked_at") or 0
                )
            return {
                "active": True,
                "idle_sec": 0.0,
                "idle_threshold_sec": idle_open_threshold_sec(),
                "reason": _locked_transition_reason(),
                "since_sec": round(time.time() - trans_since, 1) if trans_since else None,
                "locked": True,
            }
        return {
            "active": False,
            "idle_sec": 0.0,
            "idle_threshold_sec": idle_open_threshold_sec(),
            "reason": None,
            "since_sec": None,
            "locked": True,
        }
    idle_sec = max(0.0, time.time() - _last_open_at())
    threshold = idle_open_threshold_sec()
    reason = _transition_reason(reject_mix) if transition_enabled() else None
    active = transition_enabled() and idle_sec >= threshold
    if _regime_locked() and lock_live_transition():
        open_n, _ = _slot_counts()
        pressure = reason in (
            "edge_pressure",
            "move_pressure",
            "score_pressure",
            "idle_blend",
        )
        active = transition_enabled() and (
            idle_sec >= threshold or (open_n > 0 and pressure)
        )
    with _lock:
        trans_since = float(_state.get("transition_since") or 0)
    out: dict[str, Any] = {
        "active": active,
        "idle_sec": round(idle_sec, 1),
        "idle_threshold_sec": threshold,
        "reason": reason if active else None,
        "since_sec": round(time.time() - trans_since, 1) if trans_since and active else None,
    }
    if _regime_locked():
        out["locked"] = True
        out["live"] = lock_live_transition()
    return out


def _persist_transition(trans: dict[str, Any], reject_mix: dict[str, float]) -> None:
    """Geçiş modu durumunu diske yaz (yalnızca vol sample turunda)."""
    if _regime_locked() and not lock_live_transition():
        return
    with _lock:
        prev_active = bool(_state.get("transition_active"))
        active = bool(trans.get("active"))
        if active:
            if not prev_active:
                _state["transition_since"] = time.time()
                hist = list(_state.get("history") or [])
                hist.append(
                    {
                        "ts": time.time(),
                        "from": str(_state.get("regime") or "normal"),
                        "to": "transition",
                        "reason": trans.get("reason"),
                        "idle_sec": trans.get("idle_sec"),
                        "reject_mix": {k: round(v, 3) for k, v in list(reject_mix.items())[:4]},
                    }
                )
                _state["history"] = hist[-_MAX_HISTORY:]
            _state["transition_active"] = True
            _state["transition_reason"] = str(trans.get("reason") or "idle_blend")
        else:
            _state["transition_active"] = False
            _state["transition_since"] = 0.0
            _state["transition_reason"] = ""
        _save_disk()


def _effective_profile(
    base_regime: str, reject_mix: dict[str, float]
) -> tuple[dict[str, float], str, dict[str, Any]]:
    profiles = _profiles()
    locked_base = _locked_base_regime()
    if locked_base is not None:
        base_regime = locked_base
    trans_info = _transition_status(reject_mix)
    if trans_info.get("active"):
        seek = dict(profiles["seek"])
        reason = str(trans_info.get("reason") or "idle_blend")
        suffix = " [locked]" if trans_info.get("locked") else ""
        label = f"seek+transition({reason}){suffix}"
        return seek, label, trans_info
    base = dict(profiles.get(base_regime) or profiles["normal"])
    return base, base_regime, trans_info


def record_sample(
    vol_rows: list[dict[str, Any]],
    *,
    reject_mix: dict[str, float] | None = None,
) -> str:
    """Volatilite satırları + red dağılımından rejim güncelle."""
    if not enabled():
        return str(_state.get("regime") or "normal")

    _sync_regime_lock()
    frozen = _regime_locked()

    hot = [r for r in vol_rows if r.get("tier") == "hot"]
    warm = [r for r in vol_rows if r.get("tier") == "warm"]
    hot_moves = [abs(float(r.get("change_pct") or 0)) for r in hot]
    warm_moves = [abs(float(r.get("change_pct") or 0)) for r in warm]
    med_hot = sorted(hot_moves)[len(hot_moves) // 2] if hot_moves else 0.0
    max_hot = max(hot_moves) if hot_moves else 0.0
    med_warm = sorted(warm_moves)[len(warm_moves) // 2] if warm_moves else 0.0
    mix = reject_mix if reject_mix is not None else _reject_mix()

    sample = {
        "ts": time.time(),
        "median_hot_move": round(med_hot, 5),
        "max_hot_move": round(max_hot, 5),
        "median_warm_move": round(med_warm, 5),
        "hot_n": len(hot),
        "reject_mix": {k: round(v, 3) for k, v in list(mix.items())[:6]},
    }
    candidate = _classify_regime(
        median_hot_move=med_hot,
        max_hot_move=max_hot,
        hot_n=len(hot),
        reject_mix=mix,
    )
    trans = _transition_status(mix)
    if not frozen:
        _persist_transition(trans, mix)

    with _lock:
        samples: list[dict[str, Any]] = list(_state.get("samples") or [])
        samples.append(
            {
                **sample,
                "regime_hint": candidate,
                "transition": trans.get("active"),
                "regime_frozen": frozen,
            }
        )
        if len(samples) > _MAX_SAMPLES:
            samples = samples[-_MAX_SAMPLES:]
        _state["samples"] = samples

        if not frozen:
            prev = str(_state.get("regime") or "normal")
            confirm_n = max(2, _env_int("MEGA_REGIME_CONFIRM_SAMPLES", 3))
            recent = [s.get("regime_hint") for s in samples[-confirm_n:]]
            if len(recent) >= confirm_n and all(r == candidate for r in recent):
                if candidate != prev:
                    hist = list(_state.get("history") or [])
                    hist.append(
                        {
                            "ts": time.time(),
                            "from": prev,
                            "to": candidate,
                            "median_hot_move": sample["median_hot_move"],
                            "reject_mix": sample["reject_mix"],
                        }
                    )
                    _state["history"] = hist[-_MAX_HISTORY:]
                    _state["since"] = time.time()
                _state["regime"] = candidate

        _state["last_sample"] = {**sample, "transition": trans, "regime_frozen": frozen}
        if frozen:
            locked_regime = str(_state.get("locked_regime") or _state.get("regime") or "normal")
            _state["regime_hint"] = locked_regime
        else:
            _state["regime_hint"] = candidate
        _save_disk()
        if frozen:
            return str(_state.get("locked_regime") or _state.get("regime") or "normal")
        return str(_state.get("regime") or "normal")


def current_regime() -> str:
    if not enabled():
        return "off"
    with _lock:
        base = str(_state.get("regime") or "normal")
        if _state.get("transition_active"):
            return f"{base}+transition"
        return base


def tier_thresholds(
    profile: dict[str, Any],
    tier: str,
) -> dict[str, Any]:
    """Rejim + geçiş modu + tier → min_move, min_score, edge."""
    base_move = float(profile.get("mega_min_move_pct") or 0.08)
    base_score = float(profile.get("mega_min_score") or 48)
    base_edge = float(profile.get("min_edge") or 0.04)
    top_move = float(profile.get("mega_top_mover_min_move_pct") or 0.05)

    if not enabled():
        return {
            "min_move": base_move,
            "min_score": base_score,
            "min_edge": base_edge,
            "regime": "off",
            "transition": {"active": False},
        }

    with _lock:
        base_regime = str(_state.get("regime") or "normal")
    locked = _locked_base_regime()
    if locked is not None:
        base_regime = locked
    mix = _reject_mix()
    prof, label, trans_info = _effective_profile(base_regime, mix)
    warm_delta = float(prof.get("warm_min_score_delta") or 5.0)

    if tier == "hot":
        return {
            "min_move": min(base_move, top_move, float(prof["hot_min_move"])),
            "min_score": min(base_score, float(prof["hot_min_score"])),
            "min_edge": base_edge * float(prof["edge_hot"]),
            "regime": label,
            "transition": trans_info,
        }
    if tier == "warm":
        return {
            "min_move": min(base_move, float(prof["warm_min_move"])),
            "min_score": min(base_score, base_score - warm_delta),
            "min_edge": base_edge * float(prof["edge_warm"]),
            "regime": label,
            "transition": trans_info,
        }
    return {
        "min_move": base_move,
        "min_score": base_score,
        "min_edge": base_edge,
        "regime": label,
        "transition": trans_info,
    }


def _sample_interval_sec() -> float:
    with _lock:
        samples = list(_state.get("samples") or [])
    if len(samples) >= 2:
        dt = float(samples[-1].get("ts") or 0) - float(samples[-2].get("ts") or 0)
        if dt > 0.5:
            return dt
    return max(1.0, _env_float("MEGA_REGIME_SAMPLE_INTERVAL_SEC", 4.0))


def regime_change_countdown() -> dict[str, Any]:
    """Panel — rejim/geçiş değişimine kalan süre veya kilit durumu."""
    mix = _reject_mix()
    open_n, open_mx = _slot_counts()
    frozen = _regime_locked()
    threshold = idle_open_threshold_sec()
    idle_sec = max(0.0, time.time() - _last_open_at())
    confirm_n = max(2, _env_int("MEGA_REGIME_CONFIRM_SAMPLES", 3))
    sample_iv = _sample_interval_sec()

    with _lock:
        regime = str(_state.get("regime") or "normal")
        hint = str(_state.get("regime_hint") or regime)
        samples = list(_state.get("samples") or [])
        locked_regime = str(_state.get("locked_regime") or regime) if frozen else None

    trans = _transition_status(mix)

    if frozen:
        slots_left = max(0, int(open_mx) - int(open_n))
        return {
            "kind": "locked",
            "remaining_sec": None,
            "remaining_samples": None,
            "remaining_label": f"{open_n}/{open_mx} slot · kilitli",
            "detail": f"{locked_regime or regime} — slotlar boşalana kadar sabit",
            "target_regime": locked_regime or regime,
            "open_count": open_n,
            "max_open": open_mx,
            "slots_until_full": slots_left,
        }

    if trans.get("active"):
        return {
            "kind": "transition_active",
            "remaining_sec": 0,
            "remaining_samples": 0,
            "remaining_label": "Seek aktif",
            "detail": str(trans.get("reason") or "idle_blend"),
            "target_regime": "seek+transition",
            "since_sec": trans.get("since_sec"),
        }

    transition_in_sec = max(0.0, threshold - idle_sec)

    candidate = hint
    if samples:
        candidate = str(samples[-1].get("regime_hint") or hint)

    class_remain_samples = 0
    if candidate != regime and samples:
        trail = 0
        for s in reversed(samples):
            if str(s.get("regime_hint") or "") == candidate:
                trail += 1
            else:
                break
        class_remain_samples = max(0, confirm_n - trail)

    if class_remain_samples > 0:
        class_eta = class_remain_samples * sample_iv
        return {
            "kind": "classification",
            "remaining_sec": round(class_eta, 1),
            "remaining_samples": class_remain_samples,
            "remaining_label": f"~{int(round(class_eta))}s · {class_remain_samples} tur",
            "detail": f"{regime} → {candidate}",
            "target_regime": candidate,
            "confirm_samples": confirm_n,
            "sample_interval_sec": round(sample_iv, 1),
            "transition_in_sec": round(transition_in_sec, 1),
        }

    return {
        "kind": "transition",
        "remaining_sec": round(transition_in_sec, 1),
        "remaining_samples": None,
        "remaining_label": f"~{int(round(transition_in_sec))}s",
        "detail": f"Seek/geçiş · idle {int(idle_sec)}/{int(threshold)}s",
        "target_regime": "seek+transition",
        "idle_sec": round(idle_sec, 1),
        "idle_threshold_sec": threshold,
    }


def snapshot() -> dict[str, Any]:
    mix = _reject_mix()
    with _lock:
        regime = str(_state.get("regime") or "normal")
        since = float(_state.get("since") or 0)
        last = dict(_state.get("last_sample") or {})
        hint = str(_state.get("regime_hint") or regime)
        hist = list(_state.get("history") or [])[-8:]
        last_open = float(_state.get("last_open_at") or 0)
    _, eff_label, trans_info = _effective_profile(regime, mix)
    profiles = _profiles()
    open_n, open_mx = _slot_counts()
    idle_sec = max(0.0, time.time() - _last_open_at())
    change_cd = regime_change_countdown()
    return {
        "enabled": enabled(),
        "regime": regime,
        "effective_regime": eff_label,
        "regime_hint": hint,
        "regime_locked": _regime_locked(),
        "lock_until_full": lock_until_full_enabled(),
        "open_count": open_n,
        "max_open": open_mx,
        "change_countdown": change_cd,
        "since_sec": round(time.time() - since, 1) if since else None,
        "last_open_at": last_open or None,
        "idle_open_sec": round(idle_sec, 1),
        "idle_open_threshold_sec": idle_open_threshold_sec(),
        "transition": trans_info,
        "last_sample": last,
        "profiles": {
            k: {
                "hot_min_move": v["hot_min_move"],
                "warm_min_move": v["warm_min_move"],
                "edge_hot": v["edge_hot"],
            }
            for k, v in profiles.items()
            if k != "transition"
        },
        "transition_profile": profiles.get("transition"),
        "active_profile": (
            profiles.get("seek")
            if trans_info.get("active")
            else (profiles.get(regime) or profiles["normal"])
        ),
        "recent_switches": hist,
    }


def reset_instance_state() -> None:
    """Oturum sıfırlama — rejim kilidi ve geçmiş örnekleri temizle."""
    global _state, _boot_at
    _boot_at = time.time()
    fresh: dict[str, Any] = {
        "regime": "normal",
        "since": time.time(),
        "samples": [],
        "history": [],
        "last_open_at": 0.0,
        "transition_active": False,
        "transition_since": 0.0,
        "transition_reason": "",
    }
    with _lock:
        _state.clear()
        _state.update(fresh)
    path = _state_path()
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def _boot_sync_regime() -> None:
    """Sim paper — paylaşımlı/stale kilit temizle; slot sayısı ile senkronize et."""
    if mega_sim_paper_only():
        with _lock:
            if _state.get("regime_locked"):
                _state["regime_locked"] = False
                for k in (
                    "locked_regime",
                    "locked_transition",
                    "locked_transition_reason",
                    "locked_at",
                ):
                    _state.pop(k, None)
    try:
        _sync_regime_lock()
    except Exception:
        pass


_load_disk()
_boot_sync_regime()
