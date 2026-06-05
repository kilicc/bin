"""MEGA — ayrı Binance hesabında canlı emir (berserk2 ayarlarından bağımsız)."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent


def mega_instance_id() -> str:
    iid = os.getenv("MEGA_INSTANCE_ID", "").strip()
    if iid:
        return iid
    port = os.getenv("BINANCE_ELITE_PORT", "").strip()
    return port if port in ("9006", "9007") else "9006"


def mega_instance_data_dir() -> Path:
    """9007 → data/mega_9007/; 9006 → data/mega_9006/; 9008 → data/mega_9008/; legacy → data/."""
    iid = mega_instance_id()
    if iid == "9007":
        d = _ROOT / "data" / "mega_9007"
    elif iid == "9006":
        d = _ROOT / "data" / "mega_9006"
    elif iid == "9008":
        d = _ROOT / "data" / "mega_9008"
    else:
        d = _ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _maybe_migrate_instance_data_files() -> None:
    """9006 legacy data/ kök dosyalarını data/mega_9006/ altına taşı."""
    iid = mega_instance_id()
    if iid not in ("9006", "9007", "9008"):
        return
    dest = _ROOT / "data" / f"mega_{iid}"
    dest.mkdir(parents=True, exist_ok=True)
    if mega_closed_backfill_suppressed():
        return
    for name in (
        "mega_live_closed.json",
        "mega_live_open.json",
        "mega_live_open_meta.json",
        "mega_live_session.json",
        ".mega_closed_suppress_backfill",
    ):
        src = _ROOT / "data" / name
        dst = dest / name
        if src.is_file() and not dst.is_file():
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass


def mega_binance_env(key: str, default: str = "") -> str:
    """9007 → MEGA_9007_*; 9006 canlı → MEGA_9006_* / MEGA_*; 9008 → MEGA_9008_* / MEGA_*; paper sim → anahtar yok."""
    iid = mega_instance_id()
    if iid == "9007":
        inst = os.getenv(f"MEGA_9007_{key}", "").strip()
        if inst:
            return inst
        if not _env_bool("MEGA_9007_ALLOW_SHARED", False):
            return default
    if iid == "9008":
        # 9008 LIVE: önce instance-specific, sonra genel MEGA_*
        for prefix in ("MEGA_9008_", "MEGA_"):
            inst = os.getenv(f"{prefix}{key}", "").strip()
            if inst:
                return inst
        return default
    if iid == "9006":
        if mega_sim_enabled() and not mega_live_orders_enabled():
            return default
        for prefix in ("MEGA_9006_", "MEGA_"):
            inst = os.getenv(f"{prefix}{key}", "").strip()
            if inst:
                return inst
        return default
    return os.getenv(f"MEGA_{key}", default).strip()


def _mega_session_path() -> Path:
    return mega_instance_data_dir() / "mega_live_session.json"


def _mega_closed_path() -> Path:
    return mega_instance_data_dir() / "mega_live_closed.json"


def _mega_closed_suppress_path() -> Path:
    return mega_instance_data_dir() / ".mega_closed_suppress_backfill"


def _mega_open_meta_path() -> Path:
    return mega_instance_data_dir() / "mega_live_open_meta.json"


def _mega_open_book_path() -> Path:
    return mega_instance_data_dir() / "mega_live_open.json"


_MEGA_CLOSED_RAM_MAX = 200
_MEGA_CLOSED_DISK_MAX = 500
_mega_closed_loaded = False
_mega_open_book_loaded = False
_mega_persist_open_book_ts: float = 0.0

_mega_client: Any | None = None
_mega_client_lock = threading.Lock()
_mega_outage_since: float | None = None
_mega_recovery_pending_fresh_start = False
_mega_last_recovery_attempt_ts: float = 0.0
_mega_recovery_thread: threading.Thread | None = None
_mega_recovery_stop = threading.Event()
_mega_outage_hook_registered = False
_mega_positions: list[dict[str, Any]] = []
_mega_closed: list[dict[str, Any]] = []
_mega_position_id = 1
_mega_positions_cache: list[dict[str, Any]] = []
_mega_cache_ts: float = 0.0
_mega_mark_overlay_ts: float = 0.0
_mega_cache_source: str = "rest"
_mega_open_lock = threading.Lock()
_mega_closing: set[int] = set()
# Kötü fill sonrası atlanan kapanış — vanished/sync ile tekrar yazılmasın
_phantom_close_guard: dict[str, float] = {}
_mega_wallet: dict[str, Any] = {}
_mega_sync_ts: float = 0.0
_mega_tp_verify_ts: float = 0.0
_mega_exit_heavy_ts: float = 0.0
_mega_entry_fee_attempt_ts: dict[int, float] = {}
_mega_tp_arm_attempt_ts: dict[int, float] = {}
_mega_algo_prune_ts: float = 0.0
_mega_missing_close_sync_ts: float = 0.0
_mega_tp_arms_total: int = 0
_mega_tp_adopts_total: int = 0
_mega_last_exit_tick_ms: float = 0.0
_mega_last_exit_eval_ms: float = 0.0
_mega_last_close_settle_ms: float = 0.0
_mega_last_exit_eval_ts: float = 0.0
_mega_exit_eval_cursor: int = 0
_mega_last_touch_tick_ms: float = 0.0
_mega_snapshot_busy: int = 0
_mega_last_full_snapshot_ts: float = 0.0
_mega_open_ui_cache: tuple[float, int, list[dict[str, Any]]] | None = None
_mega_closed_ui_cache: tuple[float, int, list[dict[str, Any]]] | None = None
_mega_scan_light_cache: tuple[float, dict[str, Any]] | None = None
_mega_wallet_fetch_ts: float = 0.0
_mega_persist_meta_ts: float = 0.0
_mega_server_time_ts: float = 0.0
_mega_api_ping_ts: float = 0.0
_mega_last_position_risk_ts: float = 0.0
_mega_position_risk_ok_ts: float = 0.0
_mega_margin_wait_logged_ts: float = 0.0
_mega_algo_orders_cache: list[dict[str, Any]] = []
_mega_algo_orders_ts: float = 0.0
_mega_last_tp_verify_ms: float = 0.0
_mega_tp_arm_inflight: set[str] = set()
_mega_lock_update_ts: dict[int, float] = {}
_mega_tp_update_ts: dict[int, float] = {}
_mega_tp_replace_ts: dict[int, float] = {}
_mega_lock_replace_ts: dict[int, float] = {}
_mega_lock_inflight: set[str] = set()
_mega_lock_updates_total: int = 0
_mega_rest_thread: threading.Thread | None = None
_mega_rest_stop = threading.Event()
_mega_rest_wake = threading.Event()
_mega_rest_force_sync = False
_state_lock = threading.RLock()
_scan_events: deque[dict[str, Any]] = deque(maxlen=80)
_scan_lock = threading.Lock()
_scan_seen: dict[str, float] = {}


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, str(default))))
    except (TypeError, ValueError):
        return default


def mega_exchange_tp_enabled() -> bool:
    return _env_bool("MEGA_EXCHANGE_TP", True)


def mega_exchange_trail_lock_enabled() -> bool:
    """Borsada STOP_MARKET ile kâr kilidi (SL değil, trailing)."""
    return mega_live_orders_enabled() and _env_bool("MEGA_EXCHANGE_TRAIL_LOCK", True)


def mega_exchange_dual_tp_enabled() -> bool:
    """İki borsa emri: STOP = tepe kâr kilidi, TAKE_PROFIT = makul tavan TP."""
    if not mega_exchange_tp_enabled() or not mega_exchange_trail_lock_enabled():
        return False
    return _env_bool("MEGA_EXCHANGE_DUAL_TP", True)


def mega_exchange_simple_dual_tp() -> bool:
    """Basit dual TP: $8 net kâr kilidi (STOP) + tam tp_net_target (TAKE_PROFIT)."""
    if not mega_exchange_dual_tp_enabled():
        return False
    return _env_bool("MEGA_EXCHANGE_SIMPLE_DUAL_TP", False)


def _mega_floor_lock_net() -> float:
    return max(1.0, _env_float("MEGA_EXCHANGE_FLOOR_NET", _env_float("MEGA_TRAIL_LOCK_MIN_NET", 8.0)))


def _mega_gross_for_wallet_net(pos: dict[str, Any], net_usd: float, mc: Any = None) -> float:
    from elite_trader.fee_economics import min_gross_for_final_net

    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    return min_gross_for_final_net(
        stake,
        lev,
        min_final_usd=net_usd,
        mode_id="mega",
        pos=pos,
        client=mc,
    )


def _mega_floor_net_armed(pos: dict[str, Any], mc: Any = None) -> bool:
    """Pozisyon en az bir kez floor net kâr gördü mü."""
    floor = _mega_floor_lock_net()
    peak = _mega_peak_wallet_net(pos, mc)
    cur = _mega_current_wallet_net(pos, mc)
    return max(peak, cur) >= floor - 0.05


def mega_sl_exit_disabled() -> bool:
    return _env_bool("MEGA_DISABLE_SL_EXIT", True)


def mega_underwater_cut_enabled() -> bool:
    return _env_bool("MEGA_UNDERWATER_CUT", False)


def _algo_row_type(row: dict[str, Any]) -> str:
    return str(row.get("orderType") or row.get("type") or "").upper()


def _algo_tp_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in orders if "TAKE_PROFIT" in _algo_row_type(r)]


def _algo_lock_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in orders:
        t = _algo_row_type(r)
        if t in ("STOP_MARKET", "STOP") or t.startswith("STOP"):
            out.append(r)
    return out


def _mega_tp_full_net(pos: dict[str, Any] | None) -> float:
    if not pos:
        return 0.0
    return float(pos.get("tp_net_target_usd") or pos.get("tp_target_usd") or 0)


def _mega_trail_lock_bounds(
    pos: dict[str, Any] | None = None,
) -> tuple[float, float, float]:
    min_net = max(0.5, _env_float("MEGA_TRAIL_LOCK_MIN_NET", 3.0))
    arm_net = max(min_net, _env_float("MEGA_TRAIL_LOCK_ARM_NET", min_net))
    tp_full = _mega_tp_full_net(pos)
    env_max = _env_float("MEGA_TRAIL_LOCK_MAX_NET", 0.0)
    if tp_full > 0:
        max_net = tp_full
    elif env_max > 0:
        max_net = env_max
    else:
        max_net = 9999.0
    max_net = max(min_net, max_net)
    return min_net, max_net, arm_net


def _mega_exchange_arm_net(pos: dict[str, Any] | None = None) -> float:
    if mega_exchange_dual_tp_enabled():
        return max(
            0.5,
            _env_float("MEGA_EXCHANGE_ARM_NET", _env_float("MEGA_TRAIL_LOCK_ARM_NET", 3.0)),
        )
    _, _, arm = _mega_trail_lock_bounds(pos)
    return arm


def _mega_exchange_arm_gross() -> float:
    """Dual TP — Binance uPnL tepe eşiği ($)."""
    return max(0.5, _env_float("MEGA_EXCHANGE_ARM_GROSS_USD", 1.5))


def _mega_is_flash_reversal_position(pos: dict[str, Any]) -> bool:
    return bool(
        pos.get("mega_flash_reversal")
        or pos.get("flash_reversal")
        or pos.get("mega_flash_pump")
        or pos.get("flash_pump_reversal")
    )


def _mega_exchange_require_bid_fill() -> bool:
    return _env_bool("MEGA_EXCHANGE_REQUIRE_BID_FILL", True)


def _mega_exchange_skip_flash_algos() -> bool:
    return _env_bool("MEGA_EXCHANGE_SKIP_FLASH_REV", True)


def _mega_disarm_exchange_algos(pos: dict[str, Any], mc: Any, *, reason: str = "") -> None:
    """Borsa TP + kâr kilidi iptal — mark↑ bid↓ veya flash (ZEC tipi)."""
    if not mc or mc.paper:
        return
    had = bool(pos.get("exchange_tp_order_id") or pos.get("exchange_lock_order_id"))
    if not had:
        return
    _cancel_exchange_tp(pos, mc)
    _cancel_exchange_trail_lock(pos, mc)
    sym = str(pos.get("symbol") or "")
    if reason:
        print(f"  ⛔ MEGA borsa algo iptal {sym}: {reason[:160]}")


def _mega_exchange_algo_safe(pos: dict[str, Any], mc: Any) -> bool:
    """Borsa emri kur/güncelle öncesi — flash yok, bid fill net+."""
    if not mc or mc.paper or not pos.get("on_exchange"):
        return True
    if not mega_exchange_tp_enabled() and not mega_exchange_trail_lock_enabled():
        return True
    if _mega_exchange_skip_flash_algos() and _mega_is_flash_reversal_position(pos):
        _mega_disarm_exchange_algos(pos, mc, reason="flash reversal — yalnızca bot+book")
        return False
    if not _mega_exchange_require_bid_fill():
        return True
    from elite_trader.exchange_fill_truth import exchange_bid_profit_ok

    min_net = max(_mega_min_close_net_usd(), _mega_exchange_arm_net(pos) * 0.85)
    ok, detail = exchange_bid_profit_ok(
        pos, mc, mode_id="mega", min_net=min_net
    )
    if ok:
        return True
    _mega_disarm_exchange_algos(pos, mc, reason=detail or "bid fill")
    return False


def _mega_min_profit_stop_price(
    pos: dict[str, Any], mc: Any = None, *, min_net: float | None = None
) -> float:
    """STOP tetik fiyatı — bu seviyede net ≥ min (giriş altına inmez)."""
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    side = str(pos.get("side") or "LONG").upper()
    if entry <= 0 or size <= 0:
        return 0.0
    from elite_trader.fee_economics import min_gross_for_final_net

    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    floor_net = float(min_net) if min_net is not None else _mega_exchange_arm_net(pos)
    gross = min_gross_for_final_net(
        stake,
        lev,
        min_final_usd=floor_net,
        mode_id="mega",
        pos=pos,
        client=mc,
    )
    if side == "LONG":
        return entry + gross / size
    return entry - gross / size


def _mega_trail_stop_exec_ok(
    pos: dict[str, Any], stop: float, mc: Any = None
) -> bool:
    """Kilit stop — tetik anında bid ile net kâr (slippage)."""
    if not _env_bool("MEGA_EXCHANGE_STOP_BID_CHECK", True):
        return True
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    side = str(pos.get("side") or "LONG").upper()
    if entry <= 0 or size <= 0 or stop <= 0:
        return False
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    from elite_trader.exchange_fill_truth import _book_ticker

    book = _book_ticker(coin, client=mc, max_age_ms=120.0)
    bid = float((book or {}).get("bid") or 0)
    ask = float((book or {}).get("ask") or 0)
    if side == "LONG":
        exec_px = bid if bid > 0 and bid < stop else stop
    else:
        exec_px = ask if ask > 0 and ask > stop else stop
    if side == "LONG":
        gross = (exec_px - entry) * size
    else:
        gross = (entry - exec_px) * size
    if gross <= 0:
        return False
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    net = _mega_estimated_wallet_net(pos, gross, stake=stake, lev=lev, mc=mc)
    return net >= _mega_exchange_arm_net(pos) * 0.9


def _mega_peak_gross(pos: dict[str, Any]) -> float:
    return max(0.0, float(pos.get("max_unreal_seen") or 0))


def _mega_stop_from_gross(pos: dict[str, Any], gross: float) -> float:
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    side = str(pos.get("side") or "LONG").upper()
    if entry <= 0 or size <= 0 or gross <= 0:
        return 0.0
    if side == "LONG":
        return entry + gross / size
    return entry - gross / size


def _mega_gross_at_stop(pos: dict[str, Any], stop: float) -> float:
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    side = str(pos.get("side") or "LONG").upper()
    if entry <= 0 or size <= 0 or stop <= 0:
        return 0.0
    if side == "LONG":
        return max(0.0, (stop - entry) * size)
    return max(0.0, (entry - stop) * size)


def _mega_current_wallet_net(pos: dict[str, Any], mc: Any = None) -> float:
    unreal = float(pos.get("unrealized_pnl") or 0)
    if unreal <= 0:
        return 0.0
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    return _mega_estimated_wallet_net(pos, unreal, stake=stake, lev=lev, mc=mc)


def _mega_peak_bump_usd() -> float:
    return max(0.15, _env_float("MEGA_EXCHANGE_PEAK_BUMP_USD", 0.35))


def _mega_exchange_replace_min_sec() -> float:
    return max(1.0, _env_float("MEGA_EXCHANGE_TP_REPLACE_MIN_SEC", 8.0))


def _mega_stop_price_bump_pct(kind: str = "tp") -> float:
    key = (
        "MEGA_EXCHANGE_TP_MIN_BUMP_PCT"
        if kind == "tp"
        else "MEGA_TRAIL_LOCK_MIN_BUMP_PCT"
    )
    default = 0.0015 if kind == "tp" else 0.0008
    return max(0.0003, _env_float(key, default))


def _mega_stop_materially_improved(
    pos: dict[str, Any], new_stop: float, old_stop: float, *, kind: str = "tp"
) -> bool:
    if old_stop <= 0:
        return True
    if new_stop <= 0:
        return False
    side = str(pos.get("side") or "LONG").upper()
    bump = _mega_stop_price_bump_pct(kind)
    if side == "LONG":
        return new_stop > old_stop * (1.0 + bump)
    return new_stop < old_stop * (1.0 - bump)


def _mega_stop_not_degraded(
    pos: dict[str, Any], new_stop: float, old_stop: float
) -> bool:
    """Kilit/tavan stop asla düşürülmez — mevcut borsa koruması korunur."""
    if old_stop <= 0 or new_stop <= 0:
        return True
    side = str(pos.get("side") or "LONG").upper()
    if side == "LONG":
        return new_stop >= old_stop - 1e-9
    return new_stop <= old_stop + 1e-9


def _mega_lock_net_not_degraded(pos: dict[str, Any], new_net: float) -> bool:
    prev = float(pos.get("exchange_lock_net") or 0)
    if prev <= 0:
        return True
    return new_net >= prev - 0.02


def _mega_lock_gross_not_degraded(pos: dict[str, Any], new_gross: float) -> bool:
    prev = float(pos.get("exchange_lock_gross") or 0)
    if prev <= 0:
        return True
    return new_gross >= prev - 0.02


def _mega_tp_net_not_degraded(pos: dict[str, Any], new_net: float) -> bool:
    prev = float(pos.get("exchange_tp_net") or 0)
    if prev <= 0:
        return True
    return new_net >= prev - 0.02


def _mega_lock_gross_candidate(pos: dict[str, Any], mc: Any = None) -> float | None:
    if mega_exchange_simple_dual_tp():
        if not _mega_floor_net_armed(pos, mc):
            return None
        gross = _mega_gross_for_wallet_net(pos, _mega_floor_lock_net(), mc)
        prev_gross = float(pos.get("exchange_lock_gross") or 0)
        return round(max(prev_gross, gross), 4)
    peak_gross = _mega_peak_gross(pos)
    if peak_gross < _mega_exchange_arm_gross():
        return None
    retrace = max(0.85, min(0.999, _env_float("MEGA_TRAIL_LOCK_RETRACE_FRAC", 0.97)))
    prev_gross = float(pos.get("exchange_lock_gross") or 0)
    return round(max(prev_gross, peak_gross * retrace), 4)


def _mega_tp_gross_candidate(pos: dict[str, Any], mc: Any = None) -> float | None:
    if not mega_exchange_dual_tp_enabled():
        return None
    tp_net = _mega_tp_full_net(pos)
    if tp_net <= 0:
        return None
    if mega_exchange_simple_dual_tp():
        gross = _mega_gross_for_wallet_net(pos, tp_net, mc)
        prev_gross = float(pos.get("exchange_tp_gross") or 0)
        return round(max(prev_gross, gross), 4)
    _, max_net, _ = _mega_trail_lock_bounds(pos)
    peak_gross = _mega_peak_gross(pos)
    if peak_gross < _mega_exchange_arm_gross() or max_net <= 0:
        return None
    full_gross = _mega_gross_for_wallet_net(pos, max_net, mc)
    runway = max(0.08, min(0.95, _env_float("MEGA_EXCHANGE_TP_RUNWAY_FRAC", 0.42)))
    remain = max(0.0, full_gross - peak_gross)
    ceil_gross = peak_gross + remain * runway
    lock_gross = _mega_lock_gross_candidate(pos, mc) or float(pos.get("exchange_lock_gross") or 0)
    gap_gross = max(0.25, _env_float("MEGA_EXCHANGE_TP_LOCK_GAP_USD", 1.0))
    floor_gross = max(lock_gross + gap_gross, peak_gross * 1.025) if lock_gross > 0 else peak_gross * 1.03
    prev_gross = float(pos.get("exchange_tp_gross") or 0)
    target_gross = max(prev_gross, ceil_gross, floor_gross)
    return round(min(target_gross, full_gross), 4)


def _mega_peak_wallet_net(pos: dict[str, Any], mc: Any = None) -> float:
    max_u = float(pos.get("max_unreal_seen") or 0)
    from_net = float(pos.get("max_net_seen") or 0)
    if max_u <= 0 and from_net <= 0:
        return 0.0
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    from_unreal = (
        _mega_estimated_wallet_net(pos, max_u, stake=stake, lev=lev, mc=mc)
        if max_u > 0
        else 0.0
    )
    return max(from_net, from_unreal)


def _mega_tp_lock_milestones(pos: dict[str, Any]) -> list[float]:
    """Geçilen her TP kademesi için net kilit seviyeleri."""
    min_net, max_net, _ = _mega_trail_lock_bounds(pos)
    tp_net = float(pos.get("tp_net_target_usd") or pos.get("tp_target_usd") or 0)
    if tp_net <= 0:
        return []
    raw = os.getenv("MEGA_TP_LOCK_MILESTONE_FRAC", "0.22,0.40,0.58,0.75,0.92")
    fracs: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            fracs.append(float(part))
        except ValueError:
            continue
    if not fracs:
        fracs = [0.22, 0.40, 0.58, 0.75, 0.92]
    levels: list[float] = []
    for f in fracs:
        lvl = min(max_net, max(min_net, tp_net * f))
        levels.append(round(lvl, 2))
    return sorted(set(levels))


def _mega_trail_lock_target_net(pos: dict[str, Any], mc: Any = None) -> float | None:
    min_net, max_net, arm_net = _mega_trail_lock_bounds(pos)
    retrace = max(0.85, min(0.999, _env_float("MEGA_TRAIL_LOCK_RETRACE_FRAC", 0.97)))
    if mega_exchange_dual_tp_enabled():
        if mega_exchange_simple_dual_tp():
            if not _mega_floor_net_armed(pos, mc):
                return None
            floor = _mega_floor_lock_net()
            prev = float(pos.get("exchange_lock_net") or 0)
            return round(max(prev, floor), 4)
        peak_gross = _mega_peak_gross(pos)
        if peak_gross < _mega_exchange_arm_gross():
            return None
        lock_gross = _mega_lock_gross_candidate(pos, mc)
        if lock_gross is None:
            return None
        stake = float(pos.get("stake_usd") or 1)
        lev = max(int(pos.get("leverage") or 2), 1)
        target = _mega_estimated_wallet_net(pos, lock_gross, stake=stake, lev=lev, mc=mc)
        prev = float(pos.get("exchange_lock_net") or 0)
        target = max(prev, target, min_net)
        if max_net > 0:
            target = min(target, max_net)
        return round(target, 4)
    peak_net = _mega_peak_wallet_net(pos, mc)
    if peak_net < _mega_exchange_arm_net(pos):
        return None
    milestones = _mega_tp_lock_milestones(pos)
    passed = [m for m in milestones if peak_net >= m]
    if not passed and peak_net < arm_net:
        return None
    if passed:
        milestone_floor = max(passed)
        target = max(milestone_floor, peak_net * retrace)
    else:
        target = peak_net * retrace
    prev = float(pos.get("exchange_lock_net") or 0)
    return min(max_net, max(min_net, target, prev))


def _mega_dynamic_tp_ceiling_net(pos: dict[str, Any], mc: Any = None) -> float | None:
    """Makul tavan TP — tepe kâr + kalan mesafenin bir kısmı, tam hedefi aşmaz."""
    if not mega_exchange_dual_tp_enabled():
        return None
    if mega_exchange_simple_dual_tp():
        tp_net = _mega_tp_full_net(pos)
        return round(tp_net, 4) if tp_net > 0 else None
    target_gross = _mega_tp_gross_candidate(pos, mc)
    if target_gross is None:
        return None
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    target = _mega_estimated_wallet_net(pos, target_gross, stake=stake, lev=lev, mc=mc)
    prev = float(pos.get("exchange_tp_net") or 0)
    return round(max(prev, target), 4)


def _mega_trail_milestone_advanced(pos: dict[str, Any], lock_net: float) -> bool:
    """Yeni bir TP kademesi geçildi mi — kilidi güncelle."""
    milestones = _mega_tp_lock_milestones(pos)
    passed = [m for m in milestones if lock_net >= m - 0.05]
    if not passed:
        return False
    best = max(passed)
    last = float(pos.get("exchange_lock_milestone") or 0)
    return best > last + 0.05


def _mega_trail_stop_from_lock_net(
    pos: dict[str, Any], lock_net: float, mc: Any = None
) -> float:
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    side = str(pos.get("side") or "LONG").upper()
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    if entry <= 0 or size <= 0 or lock_net <= 0:
        return 0.0
    from elite_trader.fee_economics import min_gross_for_final_net

    gross = min_gross_for_final_net(
        stake,
        lev,
        min_final_usd=lock_net,
        mode_id="mega",
        pos=pos,
        client=mc,
    )
    if side == "LONG":
        return entry + gross / size
    return entry - gross / size


def _mega_trail_lock_net_at_stop(
    pos: dict[str, Any], stop: float, mc: Any = None
) -> float:
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    side = str(pos.get("side") or "LONG").upper()
    if entry <= 0 or size <= 0 or stop <= 0:
        return 0.0
    if side == "LONG":
        gross = (stop - entry) * size
    else:
        gross = (entry - stop) * size
    if gross <= 0:
        return 0.0
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    return _mega_estimated_wallet_net(pos, gross, stake=stake, lev=lev, mc=mc)


def _mega_trail_stop_valid(pos: dict[str, Any], stop: float, mc: Any = None) -> bool:
    mark = float(pos.get("current_price") or pos.get("entry_price") or 0)
    entry = float(pos.get("entry_price") or 0)
    side = str(pos.get("side") or "LONG").upper()
    min_net, _, _ = _mega_trail_lock_bounds(pos)
    if stop <= 0 or mark <= 0 or entry <= 0:
        return False
    if mega_exchange_simple_dual_tp():
        floor = _mega_floor_lock_net()
        net = _mega_trail_lock_net_at_stop(pos, stop, mc)
        if net < floor * 0.95:
            return False
        if side == "LONG":
            return stop > entry and stop < mark * 0.9995
        return stop < entry and stop > mark * 1.0005
    if side == "LONG":
        if stop <= entry or stop >= mark * 0.9995:
            return False
    elif stop >= entry or stop <= mark * 1.0005:
        return False
    net = _mega_trail_lock_net_at_stop(pos, stop, mc)
    if mega_exchange_dual_tp_enabled():
        gross = _mega_gross_at_stop(pos, stop)
        if gross < _mega_exchange_arm_gross() * 0.85:
            return False
    elif net < min_net * 0.95:
        return False
    return _mega_trail_stop_exec_ok(pos, stop, mc)


def _mega_trail_stop_improved(
    pos: dict[str, Any], new_stop: float, old_stop: float, *, lock_net: float = 0.0
) -> bool:
    if mega_exchange_simple_dual_tp():
        return old_stop <= 0
    if mega_exchange_dual_tp_enabled():
        peak = _mega_peak_gross(pos)
        last_peak = float(pos.get("exchange_peak_lock_gross") or 0)
        bump = max(0.15, _env_float("MEGA_EXCHANGE_PEAK_BUMP_USD", 0.35))
        if peak > last_peak + bump - 0.01:
            return True
        prev_lock = float(pos.get("exchange_lock_gross") or pos.get("exchange_lock_net") or 0)
        lock_gross = float(pos.get("exchange_lock_gross") or 0)
        if lock_gross > prev_lock + 0.08:
            return True
    elif _mega_trail_milestone_advanced(pos, lock_net):
        return True
    if old_stop <= 0:
        return True
    side = str(pos.get("side") or "LONG").upper()
    bump = max(0.0002, _env_float("MEGA_TRAIL_LOCK_MIN_BUMP_PCT", 0.0008))
    if side == "LONG":
        return new_stop > old_stop * (1.0 + bump)
    return new_stop < old_stop * (1.0 - bump)


def _mega_ceiling_stop_valid(
    pos: dict[str, Any], stop: float, tp_net: float, mc: Any = None
) -> bool:
    mark = float(pos.get("current_price") or pos.get("entry_price") or 0)
    side = str(pos.get("side") or "LONG").upper()
    if stop <= 0 or mark <= 0 or tp_net <= 0:
        return False
    bump = max(0.001, _env_float("MEGA_EXCHANGE_TP_MARK_BUMP_PCT", 0.0025))
    if side == "LONG":
        if stop <= mark * (1.0 + bump):
            return False
    elif stop >= mark * (1.0 - bump):
        return False
    net = _mega_trail_lock_net_at_stop(pos, stop, mc)
    return net >= tp_net * 0.97


def _mega_tp_ceiling_improved(
    pos: dict[str, Any], new_stop: float, old_stop: float, *, tp_net: float = 0.0
) -> bool:
    if mega_exchange_simple_dual_tp():
        return old_stop <= 0
    if old_stop <= 0:
        return True
    peak = _mega_peak_gross(pos) if mega_exchange_dual_tp_enabled() else _mega_peak_wallet_net(pos)
    last_peak = float(
        pos.get("exchange_peak_tp_gross" if mega_exchange_dual_tp_enabled() else "exchange_peak_tp_net")
        or 0
    )
    if peak > last_peak + _mega_peak_bump_usd() - 0.01:
        return _mega_stop_materially_improved(pos, new_stop, old_stop, kind="tp")
    return _mega_stop_materially_improved(pos, new_stop, old_stop, kind="tp")


def _mega_lock_update_allowed(pos: dict[str, Any], *, now: float | None = None) -> bool:
    if mega_exchange_simple_dual_tp() and pos.get("exchange_lock_order_id"):
        return False
    pid = int(pos.get("id") or 0)
    if not pid:
        return True
    ts = now if now is not None else time.time()
    last = float(_mega_lock_replace_ts.get(pid) or 0)
    peak = _mega_peak_gross(pos)
    last_peak = float(pos.get("exchange_peak_lock_gross") or 0)
    if peak > last_peak + _mega_peak_bump_usd():
        return True
    return (ts - last) >= _mega_exchange_replace_min_sec()


def _mega_tp_update_allowed(pos: dict[str, Any], *, now: float | None = None) -> bool:
    if mega_exchange_simple_dual_tp() and pos.get("exchange_tp_order_id"):
        return False
    pid = int(pos.get("id") or 0)
    if not pid:
        return True
    ts = now if now is not None else time.time()
    last = float(_mega_tp_replace_ts.get(pid) or 0)
    peak = _mega_peak_gross(pos)
    last_peak = float(pos.get("exchange_peak_tp_gross") or 0)
    if peak > last_peak + _mega_peak_bump_usd():
        return True
    return (ts - last) >= _mega_exchange_replace_min_sec()


def _mega_sanitize_ceiling_stop(pos: dict[str, Any], stop: float, mc: Any) -> float:
    """Tavan TP — mark'ın kârlı tarafında kalmalı (-2021 önle)."""
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    mark = float(pos.get("current_price") or pos.get("entry_price") or 0)
    side = str(pos.get("side") or "LONG").upper()
    if stop <= 0 or mark <= 0 or not coin:
        return stop
    bump = max(0.001, _env_float("MEGA_EXCHANGE_TP_MARK_BUMP_PCT", 0.0025))
    if side == "LONG":
        floor = mark * (1.0 + bump)
        if stop <= floor:
            stop = floor
    else:
        cap = mark * (1.0 - bump)
        if stop >= cap:
            stop = cap
    return mc.round_price(coin, stop)


def _mega_sanitize_lock_stop(pos: dict[str, Any], stop: float, mc: Any) -> float:
    """Mark'a çok yakın stop — Binance -2021 immediate trigger önle."""
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    mark = float(pos.get("current_price") or pos.get("entry_price") or 0)
    side = str(pos.get("side") or "LONG").upper()
    old_stop = float(pos.get("exchange_lock_stop") or 0)
    if stop <= 0 or mark <= 0 or not coin:
        return stop
    bump = max(0.001, _env_float("MEGA_TRAIL_LOCK_MARK_BUMP_PCT", 0.0025))
    if side == "LONG":
        cap = mark * (1.0 - bump)
        if stop >= cap:
            stop = cap
    else:
        floor = mark * (1.0 + bump)
        if stop <= floor:
            stop = floor
    if old_stop > 0 and not _mega_stop_not_degraded(pos, stop, old_stop):
        stop = old_stop
    floor_px = _mega_min_profit_stop_price(pos, mc)
    if floor_px > 0:
        if side == "LONG":
            stop = max(stop, floor_px)
        else:
            stop = min(stop, floor_px)
    return mc.round_price(coin, stop)


def _refresh_pos_mark_from_cache(pos: dict[str, Any]) -> None:
    sym = str(pos.get("symbol") or "").upper()
    side = str(pos.get("side") or "LONG").upper()
    for ep in _mega_positions_cache or []:
        es = str(ep.get("symbol") or f"{ep.get('coin', '')}USDT").upper()
        if es != sym or str(ep.get("side") or "LONG").upper() != side:
            continue
        mark = float(ep.get("mark_price") or 0)
        if mark > 0:
            pos["current_price"] = mark
        unreal = float(ep.get("unrealized_pnl") or 0)
        pos["unrealized_pnl"] = unreal
        pos["max_unreal_seen"] = max(float(pos.get("max_unreal_seen") or unreal), unreal)
        pos["min_unreal_seen"] = min(float(pos.get("min_unreal_seen", unreal)), unreal)
        return


def _mega_tp_stop_price(pos: dict[str, Any]) -> float:
    """Borsa TP stop — hedefe %97 yakın (daha erken tetik)."""
    entry = float(pos.get("entry_price") or 0)
    tp = float(pos.get("tp_target") or 0)
    side = str(pos.get("side") or "LONG").upper()
    frac = max(0.85, min(1.0, _env_float("MEGA_EXCHANGE_TP_FRAC", 0.97)))
    if entry <= 0 or tp <= 0:
        return tp
    if side == "LONG":
        return entry + (tp - entry) * frac
    return entry - (entry - tp) * frac


def _mega_algo_auto_prune() -> bool:
    return _env_bool("MEGA_ALGO_AUTO_PRUNE", True)


def _mega_algo_prune_interval_sec() -> float:
    return max(15.0, _env_float("MEGA_ALGO_PRUNE_SEC", 45.0))


def _mega_open_exchange_symbols() -> set[str]:
    syms: set[str] = set()
    for p in _mega_positions:
        if p.get("on_exchange"):
            syms.add(str(p["symbol"]).upper())
    for ep in _mega_positions_cache:
        amt = abs(float(ep.get("contracts") or ep.get("positionAmt") or 0))
        if amt > 0:
            sym = str(ep.get("symbol") or f"{ep.get('coin', '')}USDT").upper()
            syms.add(sym)
    return syms


def _mega_known_algo_ids() -> set[str]:
    ids: set[str] = set()
    for p in _mega_positions:
        if p.get("exchange_tp_order_id"):
            ids.add(str(p["exchange_tp_order_id"]))
        if p.get("exchange_lock_order_id"):
            ids.add(str(p["exchange_lock_order_id"]))
    return ids


def _known_algo_ids_for_coin(coin: str) -> set[str]:
    sym = f"{str(coin).replace('USDT', '').upper()}USDT"
    ids: set[str] = set()
    for p in _mega_positions:
        if str(p.get("symbol") or "").upper() != sym:
            continue
        for key in ("exchange_tp_order_id", "exchange_lock_order_id"):
            v = str(p.get(key) or "").strip()
            if v:
                ids.add(v)
    return ids


def _prune_coin_algo_orders(
    mc: Any,
    coin: str,
    *,
    keep_algo_id: str | None = None,
    keep_algo_ids: set[str] | None = None,
) -> int:
    """Tek sembol — bilinen TP + kâr kilidi dışındaki algo emirleri iptal."""
    if not mc or mc.paper:
        return 0
    canceled = 0
    try:
        orders = mc.open_algo_orders(coin)
    except Exception:
        return 0
    keep = set(_known_algo_ids_for_coin(coin))
    if keep_algo_ids:
        keep |= {str(x).strip() for x in keep_algo_ids if str(x).strip()}
    extra = str(keep_algo_id or "").strip()
    if extra:
        keep.add(extra)
    for row in orders:
        aid = str(row.get("algoId") or "").strip()
        if not aid or aid in keep:
            continue
        try:
            mc.cancel_algo_order(coin, aid)
            canceled += 1
        except Exception:
            pass
    return canceled


def prune_mega_algo_orders(mc: Any, *, force: bool = False) -> int:
    """Hesaptaki yetim/çift algo TP emirlerini temizle (-4045 önleme)."""
    global _mega_algo_prune_ts
    if not _mega_algo_auto_prune() or not mc or mc.paper:
        return 0
    now = time.time()
    if not force and (now - float(_mega_algo_prune_ts or 0)) < _mega_algo_prune_interval_sec():
        return 0
    _mega_algo_prune_ts = now
    open_syms = _mega_open_exchange_symbols()
    known = _mega_known_algo_ids()
    canceled = 0
    try:
        all_orders = mc.open_algo_orders()
    except Exception as exc:
        print(f"  ⚠ MEGA algo listesi: {exc}")
        return 0
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for row in all_orders:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            by_sym.setdefault(sym, []).append(row)
    for sym, orders in by_sym.items():
        coin = sym.replace("USDT", "")
        if sym not in open_syms:
            try:
                mc.cancel_all_open_algo_orders(coin)
                canceled += len(orders)
            except Exception:
                canceled += _prune_coin_algo_orders(mc, coin)
            if orders:
                print(f"  🧹 MEGA algo yetim {sym}: {len(orders)} emir")
            continue
        known_for_sym = {
            str(p["exchange_tp_order_id"])
            for p in _mega_positions
            if str(p.get("symbol") or "").upper() == sym and p.get("exchange_tp_order_id")
        }
        known_for_sym |= {
            str(p["exchange_lock_order_id"])
            for p in _mega_positions
            if str(p.get("symbol") or "").upper() == sym and p.get("exchange_lock_order_id")
        }
        if not known_for_sym and orders:
            tp_only = _algo_tp_orders(orders)
            for p in _mega_positions:
                if str(p.get("symbol") or "").upper() != sym or p.get("exchange_tp_order_id"):
                    continue
                if tp_only and _bind_algo_tp_row(
                    p, max(tp_only, key=lambda r: int(r.get("algoId") or 0))
                ):
                    known_for_sym.add(str(p["exchange_tp_order_id"]))
                break
        keep_ids = known | known_for_sym
        for row in orders:
            aid = str(row.get("algoId") or "").strip()
            if not aid or aid in keep_ids:
                continue
            try:
                mc.cancel_algo_order(coin, aid)
                canceled += 1
            except Exception:
                pass
    if canceled:
        print(f"  🧹 MEGA algo temizlik: {canceled} emir iptal")
    return canceled


def _bind_algo_tp_row(pos: dict[str, Any], row: dict[str, Any]) -> bool:
    aid = str(row.get("algoId") or "").strip()
    if not aid:
        return False
    global _mega_tp_adopts_total
    pos["exchange_tp_order_id"] = aid
    pos["exchange_tp_is_algo"] = True
    stop = float(row.get("triggerPrice") or row.get("stopPrice") or 0)
    if stop > 0:
        pos["exchange_tp_stop"] = round(stop, 8)
    pos.pop("exchange_tp_arm_failed", None)
    pos.pop("exchange_tp_arm_fail_code", None)
    _mega_tp_adopts_total += 1
    _persist_open_meta()
    return True


def _adopt_exchange_tp(pos: dict[str, Any], mc: Any) -> bool:
    """Borsadaki mevcut algo TP'yi bağla — gereksiz yeniden arm önle."""
    if pos.get("exchange_tp_order_id") or pos.get("exchange_tp_arm_failed"):
        return bool(pos.get("exchange_tp_order_id"))
    if not mc or mc.paper:
        return False
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    sym = str(pos.get("symbol") or "").upper()
    try:
        orders = mc.open_algo_orders(coin)
    except Exception:
        return False
    return _adopt_exchange_tp_from_orders(pos, orders, sym=sym)


def _adopt_exchange_tp_from_orders(
    pos: dict[str, Any],
    orders: list[dict[str, Any]],
    *,
    sym: str | None = None,
) -> bool:
    sym_u = str(sym or pos.get("symbol") or "").upper()
    sym_orders = [r for r in orders if str(r.get("symbol") or sym_u).upper() == sym_u]
    tp_orders = _algo_tp_orders(sym_orders)
    if not tp_orders:
        return False
    picked = max(tp_orders, key=lambda r: int(r.get("algoId") or 0))
    return _bind_algo_tp_row(pos, picked)


def _adopt_all_exchange_tps(
    mc: Any, *, all_orders: list[dict[str, Any]] | None = None
) -> int:
    """Tek REST çağrısıyla tüm açık pozisyonlara algo TP bağla."""
    if not mc or mc.paper:
        return 0
    orders = all_orders if all_orders is not None else _fetch_open_algo_orders(mc)
    if not orders:
        return 0
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for row in orders:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            by_sym.setdefault(sym, []).append(row)
    adopted = 0
    for pos in _mega_positions:
        if not pos.get("on_exchange") or pos.get("exchange_tp_order_id"):
            continue
        sym = str(pos.get("symbol") or "").upper()
        if _adopt_exchange_tp_from_orders(pos, by_sym.get(sym) or [], sym=sym):
            adopted += 1
    return adopted


def _maybe_arm_exchange_tp(pos: dict[str, Any], mc: Any) -> None:
    if mega_exchange_dual_tp_enabled():
        _maybe_update_exchange_tp(pos, mc)
        return
    if not mega_exchange_tp_enabled() or not mc or mc.paper:
        return
    if pos.get("exchange_tp_order_id") or pos.get("exchange_tp_arm_failed"):
        return
    if _adopt_exchange_tp(pos, mc):
        return
    pid = int(pos.get("id") or 0)
    now = time.time()
    iv = max(30.0, _env_float("MEGA_TP_ARM_SEC", 60.0))
    if pid and (now - float(_mega_tp_arm_attempt_ts.get(pid) or 0)) < iv:
        return
    if pid:
        _mega_tp_arm_attempt_ts[pid] = now
    _arm_exchange_tp(pos, mc)


def _arm_exchange_tp(pos: dict[str, Any], mc: Any) -> None:
    if mega_exchange_dual_tp_enabled():
        _update_exchange_tp_dynamic(pos, mc)
        return
    if not _mega_exchange_algo_safe(pos, mc):
        return
    if not mega_exchange_tp_enabled() or not mc or mc.paper:
        return
    if pos.get("exchange_tp_order_id") or pos.get("exchange_tp_arm_failed"):
        return
    key = _tp_pos_key(pos)
    if key in _mega_tp_arm_inflight:
        return
    global _mega_tp_arms_total
    _mega_tp_arm_inflight.add(key)
    try:
        mc.sync_server_time(force=False)
        coin = str(pos.get("symbol") or "").replace("USDT", "")
        side = str(pos.get("side") or "LONG").upper()
        qty = float(pos.get("size") or 0)
        stop = _mega_tp_stop_price(pos)
        mark = float(pos.get("current_price") or pos.get("entry_price") or 0)
        if stop <= 0 or qty <= 0 or not coin:
            return
        if side == "LONG" and mark > 0 and stop <= mark:
            bumped = mark * 1.001
            if _mega_exchange_tp_net_ok(pos, bumped, mc):
                stop = bumped
        elif side == "SHORT" and mark > 0 and stop >= mark:
            bumped = mark * 0.999
            if _mega_exchange_tp_net_ok(pos, bumped, mc):
                stop = bumped
        if not _mega_exchange_tp_net_ok(pos, stop, mc):
            min_net = _mega_min_close_net_usd()
            print(
                f"  ⏸ MEGA borsa TP skip {pos.get('symbol')}: "
                f"stop=${stop:.6g} cüzdan net < min ${min_net:.2f}"
            )
            return
        if _mega_algo_auto_prune():
            prune_mega_algo_orders(mc, force=False)
        try:
            order = mc.take_profit_market_order(coin, side, qty, stop)
            oid = str(order.get("algoId") or order.get("orderId") or order.get("order_id") or "")
            _mega_tp_arms_total += 1
            pos["exchange_tp_order_id"] = oid
            pos["exchange_tp_is_algo"] = bool(order.get("is_algo_order") or order.get("algoId"))
            pos["exchange_tp_stop"] = round(stop, 8)
            pos.pop("exchange_tp_arm_failed", None)
            pos.pop("exchange_tp_arm_fail_code", None)
            _invalidate_algo_orders_cache()
            _persist_open_meta()
            print(
                f"  🎯 MEGA borsa TP {pos.get('symbol')} stop=${stop:.6g} oid={oid or 'paper'}"
            )
        except Exception as exc:
            msg = str(exc)
            if "-4045" in msg or "max stop order" in msg.lower():
                n = prune_mega_algo_orders(mc, force=True)
                if n <= 0:
                    n += _prune_coin_algo_orders(mc, coin)
                if n > 0:
                    try:
                        order = mc.take_profit_market_order(coin, side, qty, stop)
                        oid = str(
                            order.get("algoId") or order.get("orderId") or order.get("order_id") or ""
                        )
                        pos["exchange_tp_order_id"] = oid
                        pos["exchange_tp_is_algo"] = bool(
                            order.get("is_algo_order") or order.get("algoId")
                        )
                        pos["exchange_tp_stop"] = round(stop, 8)
                        pos.pop("exchange_tp_arm_failed", None)
                        pos.pop("exchange_tp_arm_fail_code", None)
                        _mega_tp_arms_total += 1
                        _persist_open_meta()
                        print(
                            f"  🎯 MEGA borsa TP {pos.get('symbol')} stop=${stop:.6g} "
                            f"oid={oid or 'paper'} (temizlik sonrası)"
                        )
                        return
                    except Exception as exc2:
                        msg = str(exc2)
                        exc = exc2
            if "-4120" in msg or "Algo Order" in msg or "-4045" in msg or "max stop order" in msg.lower():
                pos["exchange_tp_arm_failed"] = True
                pos["exchange_tp_arm_fail_code"] = (
                    "-4045" if "-4045" in msg else "-4120" if "-4120" in msg else "algo"
                )
                _persist_open_meta()
                if "-4045" in msg or "max stop order" in msg.lower():
                    prune_mega_algo_orders(mc, force=True)
                print(f"  ⚠ MEGA borsa TP {pos.get('symbol')}: {exc}")
                return
            if "-1021" in msg or "Timestamp" in msg:
                try:
                    mc.sync_server_time(force=True)
                except Exception:
                    pass
                pos["exchange_tp_arm_failed"] = True
                pos["exchange_tp_arm_fail_code"] = "-1021"
                _persist_open_meta()
                print(
                    f"  ⚠ MEGA borsa TP {pos.get('symbol')}: {exc} (yazılım TP devralır)"
                )
                return
            print(f"  ⚠ MEGA borsa TP {pos.get('symbol')}: {exc}")
    finally:
        _mega_tp_arm_inflight.discard(key)


def _bind_algo_lock_row(pos: dict[str, Any], row: dict[str, Any]) -> bool:
    aid = str(row.get("algoId") or "").strip()
    if not aid:
        return False
    pos["exchange_lock_order_id"] = aid
    pos["exchange_lock_is_algo"] = True
    stop = float(row.get("triggerPrice") or row.get("stopPrice") or 0)
    if stop > 0:
        pos["exchange_lock_stop"] = round(stop, 8)
    _persist_open_meta()
    return True


def _adopt_exchange_lock_from_orders(
    pos: dict[str, Any],
    orders: list[dict[str, Any]],
    *,
    sym: str | None = None,
) -> bool:
    sym_u = str(sym or pos.get("symbol") or "").upper()
    sym_orders = [r for r in orders if str(r.get("symbol") or sym_u).upper() == sym_u]
    lock_orders = _algo_lock_orders(sym_orders)
    if not lock_orders:
        return False
    tp_ids = {
        str(p.get("exchange_tp_order_id") or "").strip()
        for p in _mega_positions
        if str(p.get("symbol") or "").upper() == sym_u and p.get("exchange_tp_order_id")
    }
    lock_orders = [
        r for r in lock_orders if str(r.get("algoId") or "").strip() not in tp_ids
    ]
    if not lock_orders:
        return False
    picked = max(lock_orders, key=lambda r: int(r.get("algoId") or 0))
    return _bind_algo_lock_row(pos, picked)


def _adopt_exchange_lock(pos: dict[str, Any], mc: Any) -> bool:
    if pos.get("exchange_lock_order_id") or not mc or mc.paper:
        return bool(pos.get("exchange_lock_order_id"))
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    sym = str(pos.get("symbol") or "").upper()
    try:
        orders = mc.open_algo_orders(coin)
    except Exception:
        return False
    return _adopt_exchange_lock_from_orders(pos, orders, sym=sym)


def _cancel_exchange_trail_lock(pos: dict[str, Any], mc: Any) -> None:
    oid = pos.get("exchange_lock_order_id")
    if not oid or not mc or mc.paper:
        return
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    try:
        if pos.get("exchange_lock_is_algo"):
            mc.cancel_algo_order(coin, oid)
        else:
            mc.cancel_order(coin, oid)
    except Exception:
        pass
    pos.pop("exchange_lock_order_id", None)
    pos.pop("exchange_lock_is_algo", None)
    pos.pop("exchange_lock_stop", None)
    pos.pop("exchange_lock_net", None)


def _restore_exchange_trail_lock(
    pos: dict[str, Any],
    mc: Any,
    *,
    stop: float,
    lock_net: float,
    lock_gross: float | None = None,
) -> bool:
    """İptal sonrası başarısız replace — eski kilit seviyesini geri koy."""
    if stop <= 0 or not mc or mc.paper:
        return False
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    side = str(pos.get("side") or "LONG").upper()
    qty = float(pos.get("size") or 0)
    if qty <= 0 or not coin:
        return False
    try:
        order = mc.stop_market_order(coin, side, qty, stop)
        oid = str(order.get("algoId") or order.get("orderId") or order.get("order_id") or "")
        pos["exchange_lock_order_id"] = oid
        pos["exchange_lock_is_algo"] = bool(order.get("is_algo_order") or order.get("algoId"))
        pos["exchange_lock_stop"] = round(stop, 8)
        pos["exchange_lock_net"] = round(lock_net, 4)
        if lock_gross is not None:
            pos["exchange_lock_gross"] = round(lock_gross, 4)
        _invalidate_algo_orders_cache()
        _persist_open_meta()
        print(
            f"  ↩ MEGA kâr kilidi restore {pos.get('symbol')} stop=${stop:.6g} "
            f"net≈${lock_net:.2f}"
        )
        return True
    except Exception as exc:
        print(f"  ⚠ MEGA kâr kilidi restore {pos.get('symbol')}: {exc}")
        return False


def _update_exchange_trail_lock(pos: dict[str, Any], mc: Any) -> None:
    """Borsada STOP_MARKET — TP kademelerinde kâr kilidi ($8–15 net)."""
    if not mega_exchange_trail_lock_enabled() or not mc or mc.paper:
        return
    if not _mega_exchange_algo_safe(pos, mc):
        return
    if not pos.get("on_exchange"):
        return
    if not pos.get("exchange_lock_order_id"):
        _adopt_exchange_lock(pos, mc)
    _refresh_pos_mark_from_cache(pos)
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    _mega_touch_peak_net(pos, stake=stake, lev=lev, mc=mc)
    lock_net = _mega_trail_lock_target_net(pos, mc)
    if lock_net is None:
        return
    lock_gross_c = _mega_lock_gross_candidate(pos, mc) if mega_exchange_dual_tp_enabled() else None
    key = _tp_pos_key(pos)
    if key in _mega_lock_inflight:
        return
    if not _mega_lock_update_allowed(pos):
        return
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    if lock_gross_c is not None and lock_gross_c > 0:
        stop = _mega_stop_from_gross(pos, lock_gross_c)
    else:
        stop = _mega_trail_stop_from_lock_net(pos, lock_net, mc)
    stop = _mega_sanitize_lock_stop(pos, stop, mc)
    stop = mc.round_price(coin, stop)
    if stop <= 0 or not _mega_trail_stop_valid(pos, stop, mc):
        if lock_net is not None and mega_exchange_dual_tp_enabled():
            print(
                f"  ⏸ MEGA kâr kilidi skip {pos.get('symbol')}: "
                f"stop=${stop:.6g} mark=${float(pos.get('current_price') or 0):.6g} "
                f"(tepe kilidi mark dışında)"
            )
        return
    old_stop = float(pos.get("exchange_lock_stop") or 0)
    old_lock_net = float(pos.get("exchange_lock_net") or 0)
    old_lock_gross = float(pos.get("exchange_lock_gross") or 0)
    if lock_gross_c is not None and not _mega_lock_gross_not_degraded(pos, lock_gross_c):
        return
    if not _mega_lock_net_not_degraded(pos, lock_net):
        return
    if pos.get("exchange_lock_order_id") and not _mega_stop_not_degraded(pos, stop, old_stop):
        return
    if pos.get("exchange_lock_order_id") and not _mega_trail_stop_improved(
        pos, stop, old_stop, lock_net=lock_net
    ):
        return
    if pos.get("exchange_lock_order_id") and not _mega_stop_materially_improved(
        pos, stop, old_stop, kind="lock"
    ):
        return
    global _mega_lock_updates_total
    _mega_lock_inflight.add(key)
    had_lock = bool(pos.get("exchange_lock_order_id"))
    try:
        mc.sync_server_time(force=False)
        side = str(pos.get("side") or "LONG").upper()
        qty = float(pos.get("size") or 0)
        if qty <= 0 or not coin:
            return
        _cancel_exchange_trail_lock(pos, mc)
        order = mc.stop_market_order(coin, side, qty, stop)
        oid = str(order.get("algoId") or order.get("orderId") or order.get("order_id") or "")
        pos["exchange_lock_order_id"] = oid
        pos["exchange_lock_is_algo"] = bool(order.get("is_algo_order") or order.get("algoId"))
        pos["exchange_lock_stop"] = round(stop, 8)
        pos["exchange_lock_net"] = round(lock_net, 4)
        if lock_gross_c is not None:
            pos["exchange_lock_gross"] = round(lock_gross_c, 4)
        peak_net = _mega_peak_wallet_net(pos, mc)
        if peak_net > 0:
            pos["exchange_peak_lock_net"] = round(peak_net, 4)
        peak_gross = _mega_peak_gross(pos)
        if peak_gross > 0:
            pos["exchange_peak_lock_gross"] = round(peak_gross, 4)
        milestones = _mega_tp_lock_milestones(pos)
        passed = [m for m in milestones if lock_net >= m - 0.05]
        if passed:
            pos["exchange_lock_milestone"] = max(passed)
        _mega_lock_updates_total += 1
        pid = int(pos.get("id") or 0)
        if pid:
            _mega_lock_replace_ts[pid] = time.time()
        _invalidate_algo_orders_cache()
        _persist_open_meta()
        print(
            f"  🔒 MEGA kâr kilidi {pos.get('symbol')} stop=${stop:.6g} "
            f"net≈${lock_net:.2f} oid={oid or 'paper'}"
            + (" [floor]" if mega_exchange_simple_dual_tp() else "")
        )
    except Exception as exc:
        msg = str(exc)
        if had_lock and old_stop > 0:
            _restore_exchange_trail_lock(
                pos,
                mc,
                stop=old_stop,
                lock_net=old_lock_net,
                lock_gross=old_lock_gross or None,
            )
        if "-2021" in msg or "immediately trigger" in msg.lower():
            print(
                f"  ⏸ MEGA kâr kilidi skip {pos.get('symbol')}: "
                f"stop=${stop:.6g} mark=${float(pos.get('current_price') or 0):.6g}"
            )
        else:
            print(f"  ⚠ MEGA kâr kilidi {pos.get('symbol')}: {exc}")
    finally:
        _mega_lock_inflight.discard(key)


def _update_exchange_tp_dynamic(pos: dict[str, Any], mc: Any) -> None:
    """Borsada TAKE_PROFIT_MARKET — tepe kâra göre makul tavan TP."""
    if not mega_exchange_dual_tp_enabled() or not mc or mc.paper:
        return
    if not _mega_exchange_algo_safe(pos, mc):
        return
    if not pos.get("on_exchange"):
        return
    if not pos.get("exchange_tp_order_id"):
        _adopt_exchange_tp(pos, mc)
    _refresh_pos_mark_from_cache(pos)
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    _mega_touch_peak_net(pos, stake=stake, lev=lev, mc=mc)
    tp_net = _mega_dynamic_tp_ceiling_net(pos, mc)
    if tp_net is None:
        return
    tp_gross_c = _mega_tp_gross_candidate(pos, mc)
    key = _tp_pos_key(pos)
    if key in _mega_tp_arm_inflight:
        return
    if pos.get("exchange_tp_order_id") and not _mega_tp_update_allowed(pos):
        return
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    if tp_gross_c is not None and tp_gross_c > 0:
        stop = _mega_stop_from_gross(pos, tp_gross_c)
    else:
        stop = _mega_trail_stop_from_lock_net(pos, tp_net, mc)
    stop = _mega_sanitize_ceiling_stop(pos, stop, mc)
    stop = mc.round_price(coin, stop)
    if stop <= 0 or not _mega_ceiling_stop_valid(pos, stop, tp_net, mc):
        return
    if not _mega_exchange_tp_net_ok(pos, stop, mc):
        return
    old_stop = float(pos.get("exchange_tp_stop") or 0)
    old_tp_net = float(pos.get("exchange_tp_net") or 0)
    if not _mega_tp_net_not_degraded(pos, tp_net):
        return
    if pos.get("exchange_tp_order_id") and not _mega_stop_not_degraded(pos, stop, old_stop):
        return
    if pos.get("exchange_tp_order_id") and not _mega_tp_ceiling_improved(
        pos, stop, old_stop, tp_net=tp_net
    ):
        return
    global _mega_tp_arms_total
    _mega_tp_arm_inflight.add(key)
    try:
        mc.sync_server_time(force=False)
        side = str(pos.get("side") or "LONG").upper()
        qty = float(pos.get("size") or 0)
        if qty <= 0 or not coin:
            return
        if _mega_algo_auto_prune():
            prune_mega_algo_orders(mc, force=False)
        _cancel_exchange_tp(pos, mc)
        order = mc.take_profit_market_order(coin, side, qty, stop)
        oid = str(order.get("algoId") or order.get("orderId") or order.get("order_id") or "")
        pos["exchange_tp_order_id"] = oid
        pos["exchange_tp_is_algo"] = bool(order.get("is_algo_order") or order.get("algoId"))
        pos["exchange_tp_stop"] = round(stop, 8)
        pos["exchange_tp_net"] = round(tp_net, 4)
        if tp_gross_c is not None:
            pos["exchange_tp_gross"] = round(tp_gross_c, 4)
        peak_net = _mega_peak_wallet_net(pos, mc)
        if peak_net > 0:
            pos["exchange_peak_tp_net"] = round(peak_net, 4)
        peak_gross = _mega_peak_gross(pos)
        if peak_gross > 0:
            pos["exchange_peak_tp_gross"] = round(peak_gross, 4)
        pos.pop("exchange_tp_arm_failed", None)
        pos.pop("exchange_tp_arm_fail_code", None)
        _mega_tp_arms_total += 1
        pid = int(pos.get("id") or 0)
        if pid:
            _mega_tp_replace_ts[pid] = time.time()
        _invalidate_algo_orders_cache()
        _persist_open_meta()
        print(
            f"  🎯 MEGA TP {pos.get('symbol')} stop=${stop:.6g} "
            f"net≈${tp_net:.2f} oid={oid or 'paper'}"
            + (" [hedef]" if mega_exchange_simple_dual_tp() else "")
        )
    except Exception as exc:
        msg = str(exc)
        if "-2021" in msg or "immediately trigger" in msg.lower():
            print(
                f"  ⏸ MEGA tavan TP skip {pos.get('symbol')}: "
                f"stop=${stop:.6g} mark=${float(pos.get('current_price') or 0):.6g}"
            )
        elif "-4045" in msg or "max stop order" in msg.lower():
            prune_mega_algo_orders(mc, force=True)
            print(f"  ⚠ MEGA tavan TP {pos.get('symbol')}: {exc}")
        else:
            print(f"  ⚠ MEGA tavan TP {pos.get('symbol')}: {exc}")
    finally:
        _mega_tp_arm_inflight.discard(key)


def _maybe_update_exchange_tp(pos: dict[str, Any], mc: Any) -> None:
    if not mega_exchange_dual_tp_enabled() or not mc or mc.paper:
        return
    pid = int(pos.get("id") or 0)
    now = time.time()
    iv = max(0.5, _env_float("MEGA_EXCHANGE_TP_UPDATE_SEC", 2.0))
    if pid and (now - float(_mega_tp_update_ts.get(pid) or 0)) < iv:
        return
    if pid:
        _mega_tp_update_ts[pid] = now
    _update_exchange_tp_dynamic(pos, mc)


def _maybe_update_exchange_dual_tp(pos: dict[str, Any], mc: Any) -> None:
    """İki emir: STOP tepe kilidi + TAKE_PROFIT makul tavan."""
    _maybe_update_exchange_trail_lock(pos, mc)
    _maybe_update_exchange_tp(pos, mc)


def _maybe_update_exchange_trail_lock(pos: dict[str, Any], mc: Any) -> None:
    if not mega_exchange_trail_lock_enabled() or not mc or mc.paper:
        return
    pid = int(pos.get("id") or 0)
    now = time.time()
    iv = max(0.5, _env_float("MEGA_TRAIL_LOCK_UPDATE_SEC", 2.0))
    if pid and (now - float(_mega_lock_update_ts.get(pid) or 0)) < iv:
        return
    if pid:
        _mega_lock_update_ts[pid] = now
    _update_exchange_trail_lock(pos, mc)


def _cancel_exchange_tp(pos: dict[str, Any], mc: Any) -> None:
    oid = pos.get("exchange_tp_order_id")
    if not oid or not mc or mc.paper:
        return
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    try:
        if pos.get("exchange_tp_is_algo"):
            mc.cancel_algo_order(coin, oid)
        else:
            mc.cancel_order(coin, oid)
    except Exception:
        pass
    pos.pop("exchange_tp_order_id", None)
    pos.pop("exchange_tp_is_algo", None)
    pos.pop("exchange_tp_stop", None)
    pos.pop("exchange_tp_net", None)


def _purge_coin_algo_after_close(mc: Any, coin: str) -> None:
    """Kapanış sonrası sembolde kalan algo/stop emirleri."""
    if not mc or mc.paper or not _mega_algo_auto_prune():
        return
    try:
        mc.cancel_all_open_algo_orders(coin)
    except Exception:
        _prune_coin_algo_orders(mc, coin)


def _mega_peak_lock_reason(pos: dict[str, Any], tp_g: float) -> str | None:
    """Tepe görüldükten sonra geri çekilme — kârı kilitle (APT senaryosu)."""
    if _mega_peak_capture_until_tp_enabled():
        return None
    if not _env_bool("MEGA_TP_PEAK_LOCK", True):
        return None
    max_u = float(pos.get("max_unreal_seen") or 0)
    unreal = float(pos.get("unrealized_pnl") or 0)
    net_tp = float(pos.get("tp_net_target_usd") or 0)
    retrace = max(0.70, min(0.98, _env_float("MEGA_TP_PEAK_RETRACE_FRAC", 0.90)))
    lock_frac = max(0.85, min(1.0, _env_float("MEGA_NET_TP_LOCK_FRAC", 0.95)))
    net_retrace = max(0.85, min(0.99, _env_float("MEGA_NET_TP_RETRACE_FRAC", 0.94)))
    if net_tp > 0 and max_u >= net_tp * lock_frac:
        tight = max(0.80, min(net_retrace, retrace - 0.06))
        if unreal > 0 and unreal <= max_u * tight:
            return "TP-PEAK"
    if max_u < tp_g * 0.96:
        return None
    if unreal > 0 and unreal <= max_u * retrace:
        return "TP-PEAK"
    return None


def _mega_mark_spike_enabled() -> bool:
    """Paper MEGA — mark uPnL flash scalp (canlı)."""
    return _env_bool("MEGA_MARK_SPIKE", True)


def _mega_mark_flash_floor(stake: float, lev: int) -> float:
    from elite_trader.fee_economics import fast_scalp_min_gross_usd

    return fast_scalp_min_gross_usd(stake, lev, mode_id="mega")


def _mega_profit_tier_levels() -> list[float]:
    raw = os.getenv("MEGA_PROFIT_TIER_NET_USD", "5,10,20").strip()
    out: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
            if v > 0:
                out.append(v)
        except ValueError:
            continue
    return sorted(set(out)) if out else [5.0, 10.0, 20.0]


def _mega_profit_tier_lock_frac() -> float:
    return max(0.75, min(0.99, _env_float("MEGA_PROFIT_TIER_LOCK_FRAC", 0.92)))


def _mega_profit_tier_retrace_frac() -> float:
    return max(0.70, min(0.99, _env_float("MEGA_PROFIT_TIER_RETRACE_FRAC", 0.88)))


def _mega_update_profit_tier_lock(pos: dict[str, Any], mc: Any = None) -> None:
    """Net tepe kademeleri (+5/+10/+20) — yükseldikçe kilit tabanını yukarı taşı."""
    if not _env_bool("MEGA_PROFIT_TIER_LOCK", True):
        return
    tiers = _mega_profit_tier_levels()
    if not tiers:
        return
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    _mega_touch_peak_net(pos, stake=stake, lev=lev, mc=mc)
    max_net = float(pos.get("max_net_seen") or 0)
    if max_net <= 0:
        return
    lock_frac = _mega_profit_tier_lock_frac()
    prev_tier = float(pos.get("mega_locked_net_tier") or 0)
    prev_floor = float(pos.get("mega_locked_net_floor") or 0)
    for tier in tiers:
        if max_net < tier:
            break
        new_floor = round(tier * lock_frac, 4)
        if tier > prev_tier or new_floor > prev_floor + 0.01:
            prev_tier = tier
            prev_floor = new_floor
            pos["mega_locked_net_tier"] = tier
            pos["mega_locked_net_floor"] = new_floor
            pos["mega_locked_net_peak"] = round(max_net, 4)


def _mega_profit_tier_close_reason(
    pos: dict[str, Any], *, stake: float, lev: int, mc: Any = None
) -> str | None:
    """Kilitli net tabandan geri çekilince hızlı kâr al (+5 / +10 / +20)."""
    if not _env_bool("MEGA_PROFIT_TIER_LOCK", True):
        return None
    floor = float(pos.get("mega_locked_net_floor") or 0)
    tier = float(pos.get("mega_locked_net_tier") or 0)
    if floor <= 0 or tier <= 0:
        return None
    gross = float(pos.get("unrealized_pnl") or 0)
    if gross <= 0:
        return None
    cur_net = _mega_estimated_wallet_net(pos, gross, stake=stake, lev=lev, mc=mc)
    buf = max(0.1, _env_float("MEGA_PROFIT_TIER_EXIT_BUFFER", 0.35))
    if cur_net < floor - buf:
        return f"TIER-{int(tier)}"
    max_u = float(pos.get("max_unreal_seen") or 0)
    if max_u <= 0:
        return None
    retrace = _mega_profit_tier_retrace_frac()
    if gross <= max_u * retrace and cur_net < floor + max(0.5, buf):
        return f"TIER-{int(tier)}"
    return None


def mega_fast_profit_close_allowed(
    pos: dict[str, Any] | None,
    exit_reason: str,
    gross_unreal: float,
    stake_usd: float,
    leverage: int,
    mode_id: str | None = None,
    client: Any = None,
) -> bool:
    """Spike / kademeli net kilit — tam TP brüt ($47) beklemeden kapanış."""
    if not pos or gross_unreal <= 0:
        return False
    from elite_trader.fee_economics import min_gross_for_final_net

    mid = mode_id or "mega"
    r = str(exit_reason or "").upper()
    if r.startswith("TIER-"):
        floor_net = float(pos.get("mega_locked_net_floor") or 0)
        if floor_net <= 0:
            return False
        min_g = min_gross_for_final_net(
            stake_usd,
            leverage,
            min_final_usd=floor_net,
            mode_id=mid,
            pos=pos,
            client=client,
        )
        return gross_unreal >= min_g * 0.88
    if pos.get("mark_spike_close") or (
        _mega_is_spike_exit(r) and pos.get("tp_fast_close")
    ):
        spike_net = _mega_spike_min_close_net_usd()
        min_g = min_gross_for_final_net(
            stake_usd,
            leverage,
            min_final_usd=spike_net,
            mode_id=mid,
            pos=pos,
            client=client,
        )
        take_g = _mega_spike_take_gross_usd(stake_usd)
        return gross_unreal >= max(min_g * 0.88, take_g * 0.55)
    return False


def _mega_min_close_net_usd() -> float:
    """Kapanış için minimum cüzdan net kâr (fee + funding sonrası) — varsayılan $8."""
    raw_exit = os.getenv("MEGA_EXIT_MIN_NET_USD", "").strip()
    raw_min = os.getenv("MEGA_MIN_CLOSE_NET_USD", "").strip()
    vals: list[float] = []
    for raw in (raw_min, raw_exit):
        if raw:
            try:
                vals.append(float(raw))
            except ValueError:
                pass
    if vals:
        return max(0.0, max(vals))
    return max(0.0, _env_float("MEGA_MIN_CLOSE_NET_USD", 8.0))


def _mega_spike_min_close_net_usd() -> float:
    """SPIKE-FLASH / tepe kilidi — tam TP'den düşük, ~$15–20 brüt spike kaçmasın."""
    raw = os.getenv("MEGA_SPIKE_MIN_CLOSE_NET_USD", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return max(3.5, min(5.0, round(_mega_min_close_net_usd() * 0.5, 2)))


def _mega_spike_take_gross_usd(stake_usd: float | None = None) -> float:
    """Bu brüt uPnL ve üstü — anında SPIKE-FLASH (tam TP bekleme)."""
    floor_usd = 14.0
    raw = os.getenv("MEGA_SPIKE_TAKE_GROSS_USD", "").strip()
    if raw:
        try:
            floor_usd = max(8.0, float(raw))
        except ValueError:
            pass
    else:
        alt = os.getenv("MEGA_FAST_EXIT_GROSS_USD", "").strip()
        if alt:
            try:
                floor_usd = max(8.0, float(alt))
            except ValueError:
                pass
    pct_raw = os.getenv("MEGA_SPIKE_TAKE_STAKE_PCT", "0.015").strip()
    try:
        pct = max(0.008, min(0.03, float(pct_raw)))
    except ValueError:
        pct = 0.015
    if stake_usd is not None and float(stake_usd) > 0:
        return max(floor_usd, round(float(stake_usd) * pct, 2))
    return floor_usd


def _mega_spike_min_age_sec() -> float:
    raw = os.getenv("MEGA_SPIKE_MIN_AGE_SEC", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    try:
        from elite_trader.panel_strategy import mode_catalog

        m = mode_catalog().get("mega") or {}
        return max(0.0, float(m.get("spike_min_age_sec", 0.35)))
    except Exception:
        return 0.35


def _phantom_guard_key(symbol: Any, side: Any) -> str:
    sym = str(symbol or "").upper()
    sd = str(side or "LONG").upper()
    return f"{sym}:{sd}"


def _register_phantom_close_guard(pos: dict[str, Any], *, ttl_sec: float = 900.0) -> None:
    """Slippage phantom — sync/vanished ile aynı kapanışı tekrar kaydetme."""
    key = _phantom_guard_key(pos.get("symbol"), pos.get("side"))
    if key:
        _phantom_close_guard[key] = time.time() + max(60.0, ttl_sec)


def _phantom_guard_active(symbol: Any, side: Any) -> bool:
    key = _phantom_guard_key(symbol, side)
    if not key:
        return False
    until = float(_phantom_close_guard.get(key) or 0)
    if until <= time.time():
        _phantom_close_guard.pop(key, None)
        return False
    return True


def _mega_phantom_slippage_detected(
    pos: dict[str, Any],
    exit_reason: str,
    record_reason: str,
    exchange_settled: dict[str, Any] | None,
) -> bool:
    """API/spike kâr görünüp fill zarar — audit/Telegram/kapalı kitap; panel ayrı gizlenir."""
    if not _env_bool("MEGA_SKIP_SPIKE_NET_LOSS_CLOSED", True):
        return False
    wallet = float(
        (exchange_settled or {}).get("wallet_pnl")
        or (exchange_settled or {}).get("net_pnl")
        or (exchange_settled or {}).get("final_pnl")
        or pos.get("wallet_pnl")
        or pos.get("net_pnl")
        or 0
    )
    if wallet >= 0:
        return False
    floor = _mega_spike_min_close_net_usd()
    pre_net = float(pos.get("pre_send_net") or 0)
    pre_gross = float(pos.get("pre_send_gross") or 0)
    max_u = float(pos.get("max_unreal_seen") or 0)
    rr = str(record_reason or "").upper()
    er = str(exit_reason or "").upper()
    if pre_net >= floor and wallet < 0:
        return True
    if pre_gross >= floor and wallet < 0:
        return True
    if max_u >= floor * 1.5 and wallet < 0 and rr in (
        "EXCHANGE-SYNC",
        "SYNC-EXCHANGE",
        "NET-LOSS",
        "FEE-KILL",
        "BELOW-FLOOR",
    ):
        return True
    if _mega_is_spike_exit(exit_reason) and wallet < 0:
        return True
    if er in ("SYNC-EXCHANGE", "EXCHANGE-SYNC") and max_u >= floor and wallet < 0:
        return True
    if rr in ("NET-LOSS", "FEE-KILL", "BELOW-FLOOR") and max_u >= floor and wallet < 0:
        return True
    return False


def _mega_skip_phantom_closed_record(
    pos: dict[str, Any],
    exit_reason: str,
    record_reason: str,
    exchange_settled: dict[str, Any] | None,
) -> bool:
    """Tekrar kayıt guard; tam skip yalnızca MEGA_SKIP_PHANTOM_CLOSED_APPEND=1 (eski davranış)."""
    if _phantom_guard_active(pos.get("symbol"), pos.get("side")):
        return True
    if _env_bool("MEGA_SKIP_PHANTOM_CLOSED_APPEND", False):
        return _mega_phantom_slippage_detected(
            pos, exit_reason, record_reason, exchange_settled
        )
    return False


def _mega_skip_phantom_spike_closed_record(
    pos: dict[str, Any],
    exit_reason: str,
    record_reason: str,
    exchange_settled: dict[str, Any] | None,
) -> bool:
    return _mega_skip_phantom_closed_record(
        pos, exit_reason, record_reason, exchange_settled
    )


def _apply_phantom_slippage_meta(
    closed: dict[str, Any],
    pos: dict[str, Any],
    *,
    exit_reason: str,
    record_reason: str,
    exchange_settled: dict[str, Any] | None,
) -> dict[str, Any]:
    if not _mega_phantom_slippage_detected(
        pos, exit_reason, record_reason, exchange_settled
    ):
        return closed
    out = dict(closed)
    out["phantom_slippage"] = True
    out["panel_hide"] = _env_bool("MEGA_PHANTOM_PANEL_HIDE", True)
    out["pre_send_net"] = pos.get("pre_send_net") or out.get("pre_send_net")
    out["pre_send_gross"] = pos.get("pre_send_gross") or out.get("pre_send_gross")
    out["phantom_detail"] = (
        f"pre_send_net={float(pos.get('pre_send_net') or 0):.4f} "
        f"fill_net={float(out.get('wallet_pnl') or out.get('net_pnl') or 0):.4f}"
    )
    return out


def _remove_mega_closed_records(
    *,
    position_ids: list[int] | None = None,
    symbols: list[str] | None = None,
    reason: str = "user_remove",
) -> dict[str, Any]:
    """Kapalı tablodan kayıt çıkar — arşivle, panel temiz."""
    global _mega_closed
    _ensure_mega_closed_loaded()
    ids = {int(x) for x in (position_ids or []) if int(x) > 0}
    syms = {str(s or "").upper().replace("USDT", "") + "USDT" for s in (symbols or []) if s}
    if not ids and not syms:
        return {"removed": 0}
    keep: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for row in _mega_closed:
        sym = str(row.get("symbol") or "").upper()
        pid = int(row.get("id") or 0)
        if pid in ids or sym in syms:
            removed.append(row)
        else:
            keep.append(row)
    if not removed:
        return {"removed": 0}
    from datetime import datetime, timezone
    import json

    archive_dir = mega_instance_data_dir().parent / "deleted_archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"mega_closed_removed_{mega_instance_id()}_{stamp}.json"
    archive_path.write_text(
        json.dumps(
            {"reason": reason, "removed": removed, "kept_count": len(keep)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _mega_closed = keep
    _save_mega_closed_to_disk()
    _dedupe_mega_closed(persist=True)
    global _mega_closed_ui_cache
    _mega_closed_ui_cache = None
    for row in removed:
        try:
            from elite_trader import parallel_universe_engine as pe

            pe.remove_closed_trade(
                int(row.get("id") or 0),
                mode_id="mega",
                symbol=str(row.get("symbol") or ""),
                exit_time=str(row.get("exit_time_str") or ""),
            )
        except Exception:
            pass
    return {"removed": len(removed), "archive": str(archive_path)}


def _mega_is_spike_exit(exit_reason: str | None) -> bool:
    return str(exit_reason or "").upper() in (
        "SPIKE-FLASH",
        "SPIKE-QUICK",
        "SPIKE-PEAK",
        "TP-PEAK",
    )


def _mega_spike_exit_net_ok(
    pos: dict[str, Any],
    gross: float,
    net: float,
    *,
    stake: float,
    lev: int,
    mc: Any = None,
) -> bool:
    """Spike çıkış — tepe net veya güncel net ≥ spike tabanı (tam TP $8 ayrı)."""
    floor = _mega_spike_min_close_net_usd()
    if floor <= 0:
        return net > 0
    if net >= floor:
        return True
    take_gross = _mega_spike_take_gross_usd()
    if gross >= take_gross and net >= max(3.0, floor * 0.8):
        return True
    max_net = float(pos.get("max_net_seen") or 0)
    max_u = float(pos.get("max_unreal_seen") or 0)
    if max_net >= floor and max_u >= take_gross:
        return True
    if max_net >= floor and max_u > 0 and gross >= max_u * _mega_spike_peak_frac():
        return True
    if max_u > 0 and gross >= max_u * max(0.82, _mega_spike_peak_frac() - 0.06):
        peak_net = _mega_estimated_wallet_net(pos, max_u, stake=stake, lev=lev, mc=mc)
        if peak_net >= floor:
            return True
    return False


def _mega_bot_close_min_age_sec() -> float:
    """Bot kâr çıkışı min yaş — 0 = spike/quick; emir öncesi API net gate korur."""
    return max(0.0, _env_float("MEGA_MIN_CLOSE_AGE_SEC", 0.0))


def _mega_exchange_profit_at_send_ok(
    pos: dict[str, Any],
    exit_reason: str,
    mc: Any,
) -> tuple[bool, str]:
    """reduceOnly MARKET öncesi — taze positionRisk uPnL + cüzdan net ≥ min."""
    from elite_trader.fee_economics import is_profit_tp_exit, is_stop_loss_exit

    r = str(exit_reason or "").upper()
    if r in ("SYNC-EXCHANGE", "EXCHANGE-SYNC", "MODE-RESET") or r.startswith("RESCUE-"):
        return True, ""
    if r in ("MANUAL", "MANUAL CLOSE"):
        return True, ""
    if not is_profit_tp_exit(exit_reason):
        if is_stop_loss_exit(exit_reason) and mega_sl_exit_disabled():
            if r.startswith("SL-COIN25") or r.startswith("SWAP-FREE-SLOT"):
                return True, ""
            return False, "SL çıkış kapalı"
        return True, ""
    from elite_trader.panel_strategy import position_age_seconds

    age = position_age_seconds(pos)
    min_age = _mega_bot_close_min_age_sec()
    if min_age > 0 and age < min_age:
        return False, f"pozisyon yaşı {age:.1f}s < min {min_age:.1f}s"
    if not mc or mc.paper or not pos.get("on_exchange"):
        return True, ""
    demo_fast = _mega_demo_fast_close_eligible(pos, mc)
    if demo_fast:
        refresh_iv = max(0.04, _env_float("MEGA_DEMO_FAST_GROSS_REFRESH_SEC", 0.06))
    else:
        refresh_iv = max(0.08, _env_float("MEGA_SEND_GROSS_REFRESH_SEC", 0.14))
    last_sync = float(pos.get("_gross_sync_ts") or 0)
    if (time.time() - last_sync) >= refresh_iv:
        refresh_mega_positions_cache(
            force=True, skip_wallet=True, panel_critical=True
        )
        _sync_pos_from_exchange(pos, list(_mega_positions_cache), mode_id="mega")
        pos["_gross_sync_ts"] = time.time()
    gross = _mega_api_gross_unreal(pos)
    if demo_fast and gross >= _mega_demo_fast_close_gross_usd():
        ok_px, px_detail = _mega_demo_fast_close_price_ok(pos, mc)
        if ok_px:
            pos["demo_fast_close"] = True
            pos["tp_fast_close"] = True
            pos["unrealized_pnl"] = gross
            pos["pre_send_gross"] = gross
            pos["pre_send_net"] = _mega_api_wallet_net(pos, mc=mc, gross=gross)
            return True, "demo_fast_close"
        if gross >= _mega_demo_fast_close_gross_usd():
            return False, px_detail
    if gross <= 0:
        return False, f"REST uPnL ${gross:.4f} ≤ 0 — emir gönderilmedi"
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    net = _mega_api_wallet_net(pos, mc=mc, gross=gross)
    floor = _mega_min_close_net_usd()
    if _mega_is_spike_exit(r):
        if not _mega_spike_exit_net_ok(
            pos, gross, net, stake=stake, lev=lev, mc=mc
        ):
            spike_floor = _mega_spike_min_close_net_usd()
            max_net = float(pos.get("max_net_seen") or 0)
            return (
                False,
                f"REST net ${net:.2f} / tepe net ${max_net:.2f} < spike min ${spike_floor:.2f} — emir gönderilmedi",
            )
    elif net < floor:
        return False, f"REST net ${net:.2f} < min ${floor:.2f} — emir gönderilmedi"
    pos["unrealized_pnl"] = gross
    pos["pre_send_gross"] = gross
    pos["pre_send_net"] = net
    return True, ""


def _mega_panel_exchange_only() -> bool:
    """Canlı panel/tick — yalnızca demo-fapi positionRisk; hub/mark şişirme yok."""
    if not mega_live_enabled():
        return False
    return _env_bool("MEGA_PANEL_EXCHANGE_ONLY", True)


def _mega_mark_unreal_blend_enabled() -> bool:
    """Hub mark + positionRisk blend — panel exchange-only iken kapalı."""
    if _mega_panel_exchange_only():
        return False
    return _env_bool("MEGA_MARK_UNREAL_BLEND", False)


def _mega_open_upnl_exchange_first() -> bool:
    """Panel açık uPnL — positionRisk (borsa); mark yalnızca spike/tepe izleme."""
    if _mega_panel_exchange_only():
        return True
    return _env_bool("MEGA_OPEN_UPNL_EXCHANGE_FIRST", True)


def _panel_api_unreal(pos: dict[str, Any]) -> float | None:
    """Panel uPnL — yalnızca positionRisk / exchange_display (motor mark hesabı yok)."""
    ex = pos.get("exchange_display") or {}
    raw_u = ex.get("unRealizedProfit")
    if raw_u is not None and str(raw_u).strip() != "":
        try:
            return float(raw_u)
        except (TypeError, ValueError):
            pass
    eu = pos.get("exchange_unrealized_pnl")
    if eu is not None and str(eu).strip() != "":
        try:
            return float(eu)
        except (TypeError, ValueError):
            pass
    return None


def _mega_gross_unreal_from_mark(pos: dict[str, Any], mark_px: float) -> float:
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    if entry <= 0 or size <= 0 or mark_px <= 0:
        return 0.0
    side = str(pos.get("side") or "LONG").upper()
    if side == "LONG":
        return round((mark_px - entry) * size, 4)
    return round((entry - mark_px) * size, 4)


def _mega_refresh_unreal_from_mark(
    pos: dict[str, Any], *, mark_px: float | None = None
) -> float:
    """Taze mark → brüt uPnL; REST ile max (spike kaçırma önlemi)."""
    rest = float(
        pos.get("exchange_unrealized_pnl") or pos.get("unrealized_pnl") or 0
    )
    if not _mega_mark_unreal_blend_enabled() or not pos.get("on_exchange"):
        return rest
    px = float(
        mark_px
        or pos.get("current_price")
        or pos.get("mark_price")
        or 0
    )
    if px <= 0:
        return rest
    mark_g = _mega_gross_unreal_from_mark(pos, px)
    pos["mark_derived_unreal"] = mark_g
    pos["current_price"] = px
    if _mega_open_upnl_exchange_first() and pos.get("on_exchange"):
        display = rest
        pos["exchange_unrealized_pnl"] = rest
        pos["unrealized_pnl"] = display
        pos["max_exchange_unreal_seen"] = max(
            float(pos.get("max_exchange_unreal_seen") or 0), rest
        )
        pos["max_unreal_seen"] = pos["max_exchange_unreal_seen"]
        prev_min = float(
            pos.get("min_unreal_seen") if pos.get("min_unreal_seen") is not None else display
        )
        pos["min_unreal_seen"] = min(prev_min, rest)
        effective = display
    else:
        effective = max(rest, mark_g)
        pos["unrealized_pnl"] = effective
        pos["exchange_unrealized_pnl"] = effective
        pos["max_unreal_seen"] = max(float(pos.get("max_unreal_seen") or 0), effective)
        pos["min_unreal_seen"] = min(float(pos.get("min_unreal_seen", effective)), effective)
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    net = _mega_wallet_net_from_gross(pos, effective, stake=stake, lev=lev)
    pos["max_net_seen"] = max(float(pos.get("max_net_seen") or 0), net)
    return effective


def _mega_profit_zone_active() -> bool:
    """Spike/kâr bölgesi — positionRisk REST'i bayat bırakma."""
    take = _mega_spike_take_gross_usd()
    watch = take * max(0.65, min(0.95, _env_float("MEGA_SPIKE_TAKE_WATCH_FRAC", 0.72)))
    for pos in _mega_positions or []:
        g = max(
            float(pos.get("max_exchange_unreal_seen") or pos.get("max_unreal_seen") or 0),
            _mega_api_gross_unreal(pos),
        )
        if g >= watch:
            return True
    return mega_needs_fast_exit()


def _mega_api_gross_unreal(pos: dict[str, Any]) -> float:
    """Canlı pozisyon — positionRisk unRealizedProfit (blend yok)."""
    return float(
        pos.get("exchange_unrealized_pnl")
        or pos.get("unrealized_pnl")
        or 0
    )


def _mega_wallet_net_from_gross(
    pos: dict[str, Any],
    gross_unreal: float,
    *,
    stake: float | None = None,
    lev: int | None = None,
    mc: Any = None,
) -> float:
    stake_v = float(stake if stake is not None else pos.get("stake_usd") or 1)
    lev_v = max(int(lev if lev is not None else pos.get("leverage") or 2), 1)
    return _mega_estimated_wallet_net(
        pos, float(gross_unreal), stake=stake_v, lev=lev_v, mc=mc
    )


def _mega_api_wallet_net(
    pos: dict[str, Any], *, mc: Any = None, gross: float | None = None
) -> float:
    g = float(gross if gross is not None else _mega_api_gross_unreal(pos))
    return _mega_wallet_net_from_gross(pos, g, mc=mc)


def _mega_estimated_wallet_net(
    pos: dict[str, Any],
    gross_unreal: float,
    *,
    stake: float,
    lev: int,
    mc: Any = None,
) -> float:
    from elite_trader.fee_economics import estimate_close_pnl

    est = estimate_close_pnl(
        float(gross_unreal),
        stake,
        lev,
        entry_fee=float(pos.get("entry_fee") or 0) or None,
        pos=pos,
        client=mc,
    )
    return float(est.get("final_pnl") or 0)


def _mega_exchange_tp_net_ok(
    pos: dict[str, Any], stop: float, mc: Any = None
) -> bool:
    """Borsa TP stop fiyatında tahmini cüzdan net ≥ MEGA_MIN_CLOSE_NET_USD mi?"""
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    side = str(pos.get("side") or "LONG").upper()
    if entry <= 0 or size <= 0 or stop <= 0:
        return False
    if side == "LONG":
        gross = (stop - entry) * size
    else:
        gross = (entry - stop) * size
    if gross <= 0:
        return False
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    net = _mega_estimated_wallet_net(pos, gross, stake=stake, lev=lev, mc=mc)
    min_req = (
        _mega_exchange_arm_net(pos)
        if mega_exchange_dual_tp_enabled()
        else _mega_min_close_net_usd()
    )
    return net >= min_req


def _infer_exchange_sl_exit_reason(
    pos: dict[str, Any], exchange_settled: dict[str, Any] | None
) -> str | None:
    """Borsa STOP / yıldız SL fill — kapalı deftere SL etiketi."""
    if not exchange_settled:
        return None
    star = str(pos.get("star_sl_exit") or "").strip().upper()
    if star.startswith("SL"):
        return star
    close_oid = str(exchange_settled.get("close_order_id") or "").strip()
    for oid_key in (
        "exchange_lock_order_id",
        "exchange_sl_order_id",
        "exchange_stop_order_id",
    ):
        oid = str(pos.get(oid_key) or "").strip()
        if oid and close_oid and oid == close_oid:
            return "SL-EXCHANGE"
    exit_px = float(exchange_settled.get("exit_price") or 0)
    for stop_key in ("exchange_lock_stop", "exchange_sl_stop", "sl_stop_price"):
        stop = float(pos.get(stop_key) or 0)
        if exit_px > 0 and stop > 0:
            tol = max(0.0002, stop * 0.003)
            if abs(exit_px - stop) <= tol:
                return "SL-EXCHANGE"
    wallet = float(
        exchange_settled.get("wallet_pnl")
        or exchange_settled.get("net_pnl")
        or 0
    )
    gross = float(
        exchange_settled.get("pnl_gross_usd")
        or exchange_settled.get("pnl_usd")
        or 0
    )
    if wallet < -0.01 or gross < -0.01:
        return star if star.startswith("SL") else "SL"
    return None


def _infer_vanished_exit_reason(
    pos: dict[str, Any], exchange_settled: dict[str, Any] | None
) -> str:
    """Borsada kaybolan pozisyon — TP / SL / manuel."""
    if not exchange_settled:
        return "MANUAL"
    sl_reason = _infer_exchange_sl_exit_reason(pos, exchange_settled)
    if sl_reason:
        return sl_reason
    close_oid = str(exchange_settled.get("close_order_id") or "").strip()
    tp_oid = str(pos.get("exchange_tp_order_id") or "").strip()
    if close_oid and tp_oid and close_oid == tp_oid:
        return "TP"
    exit_px = float(exchange_settled.get("exit_price") or 0)
    tp_stop = float(pos.get("exchange_tp_stop") or 0)
    if exit_px > 0 and tp_stop > 0:
        tol = max(0.0002, tp_stop * 0.002)
        if abs(exit_px - tp_stop) <= tol:
            return "TP"
    return "SYNC-EXCHANGE"


def _mega_touch_peak_net(
    pos: dict[str, Any], *, stake: float, lev: int, mc: Any = None
) -> None:
    max_u = float(pos.get("max_unreal_seen") or pos.get("unrealized_pnl") or 0)
    if max_u <= 0:
        return
    net_at_peak = _mega_estimated_wallet_net(pos, max_u, stake=stake, lev=lev, mc=mc)
    prev = float(pos.get("max_net_seen") or 0)
    if net_at_peak > prev:
        pos["max_net_seen"] = net_at_peak


def _mega_spike_peak_frac() -> float:
    return max(0.82, min(1.0, _env_float("MEGA_SPIKE_PEAK_FRAC", 0.90)))


def _mega_peak_spike_ready(
    pos: dict[str, Any], *, stake: float, lev: int, mc: Any = None
) -> bool:
    """Tepeye yakın spike — max net ≥ spike tabanı, fiyat hâlâ tepede."""
    if not _mega_mark_spike_enabled():
        return False
    floor = _mega_spike_min_close_net_usd()
    if floor <= 0:
        return False
    max_u = float(pos.get("max_unreal_seen") or 0)
    unreal = float(pos.get("unrealized_pnl") or 0)
    max_net = float(pos.get("max_net_seen") or 0)
    if max_net < floor or max_u <= 0 or unreal <= 0:
        return False
    if unreal < max_u * _mega_spike_peak_frac():
        return False
    net_now = _mega_estimated_wallet_net(pos, unreal, stake=stake, lev=lev, mc=mc)
    return _mega_spike_exit_net_ok(
        pos, unreal, net_now, stake=stake, lev=lev, mc=mc
    )


def _mega_mark_spike_ready(
    pos: dict[str, Any], *, stake: float, lev: int, mc: Any = None
) -> bool:
    """API uPnL + fee sonrası spike tabanı (tam TP $8 değil)."""
    if not _mega_mark_spike_enabled():
        return False
    gross = _mega_api_gross_unreal(pos)
    if gross <= 0:
        return False
    flash = _mega_mark_flash_floor(stake, lev)
    if gross < flash:
        return False
    net = _mega_wallet_net_from_gross(pos, gross, stake=stake, lev=lev, mc=mc)
    return _mega_spike_exit_net_ok(
        pos, gross, net, stake=stake, lev=lev, mc=mc
    )


def _mega_spike_close_ready(
    pos: dict[str, Any], *, stake: float, lev: int, mc: Any = None
) -> bool:
    return _mega_mark_spike_ready(
        pos, stake=stake, lev=lev, mc=mc
    ) or _mega_peak_spike_ready(pos, stake=stake, lev=lev, mc=mc)


def _mega_instant_spike_reason(
    pos: dict[str, Any], *, stake: float, lev: int, mc: Any = None
) -> str | None:
    """$14–20+ brüt anlık kâr — tam TP beklemeden SPIKE-FLASH."""
    if not _mega_mark_spike_enabled():
        return None
    from elite_trader.panel_strategy import position_age_seconds

    if position_age_seconds(pos) < _mega_spike_min_age_sec():
        return None
    gross = _mega_api_gross_unreal(pos)
    take = _mega_spike_take_gross_usd(stake)
    if gross < take:
        return None
    net = _mega_estimated_wallet_net(pos, gross, stake=stake, lev=lev, mc=mc)
    if not _mega_spike_exit_net_ok(
        pos, gross, net, stake=stake, lev=lev, mc=mc
    ):
        return None
    return "SPIKE-FLASH"


def _mega_mark_spike_reason(
    pos: dict[str, Any], *, stake: float, lev: int, mc: Any = None
) -> str | None:
    """Mark/net ≥ min → SPIKE-FLASH; tepe spike — yüksekten anında kapat."""
    instant = _mega_instant_spike_reason(pos, stake=stake, lev=lev, mc=mc)
    if instant:
        return instant
    peak = _mega_peak_spike_ready(pos, stake=stake, lev=lev, mc=mc)
    mark = _mega_mark_spike_ready(pos, stake=stake, lev=lev, mc=mc)
    if not (peak or mark):
        return None
    from elite_trader.panel_strategy import position_age_seconds

    if position_age_seconds(pos) < _mega_spike_min_age_sec():
        return None
    return "SPIKE-FLASH"


def _mega_profit_seen_ok(
    pos: dict[str, Any], *, exit_reason: str | None = None, mc: Any = None
) -> bool:
    """API uPnL ile fee sonrası en az MEGA_MIN_CLOSE_NET_USD görülmüş mü."""
    floor = _mega_min_close_net_usd()
    if floor <= 0:
        return True
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    r = str(exit_reason or "").upper()
    if r.startswith("TIER-"):
        floor = float(pos.get("mega_locked_net_floor") or 0)
        if floor <= 0:
            return False
        cur_gross = _mega_api_gross_unreal(pos)
        if cur_gross <= 0:
            return False
        cur_net = _mega_wallet_net_from_gross(
            pos, cur_gross, stake=stake, lev=lev, mc=mc
        )
        buf = max(0.1, _env_float("MEGA_PROFIT_TIER_EXIT_BUFFER", 0.35))
        return cur_net >= floor - buf or float(pos.get("max_net_seen") or 0) >= floor
    if r == "SPIKE-FLASH" and _mega_mark_spike_enabled():
        return _mega_spike_close_ready(
            pos, stake=stake, lev=lev, mc=mc
        )
    max_net = float(pos.get("max_net_seen") or 0)
    if max_net >= floor:
        return True
    cur_gross = _mega_api_gross_unreal(pos)
    if cur_gross > 0 and _mega_wallet_net_from_gross(
        pos, cur_gross, stake=stake, lev=lev, mc=mc
    ) >= floor:
        return True
    max_u = float(pos.get("max_unreal_seen") or 0)
    if max_u > 0:
        return _mega_wallet_net_from_gross(pos, max_u, stake=stake, lev=lev, mc=mc) >= floor
    return False


def _mega_underwater_time_stop_reason(pos: dict[str, Any]) -> str | None:
    """
    Uzun süre su altında kalan pozisyonu kes — varsayılan kapalı (MEGA_UNDERWATER_CUT=0).
    """
    if not mega_underwater_cut_enabled():
        return None
    max_sec = max(30.0, _env_float("MEGA_UNDERWATER_MAX_SEC", 90.0))
    min_loss = max(0.5, _env_float("MEGA_UNDERWATER_MIN_LOSS_USD", 1.5))
    from elite_trader.panel_strategy import position_age_seconds

    age = position_age_seconds(pos)
    if age < max_sec:
        return None
    unreal = float(pos.get("unrealized_pnl") or 0)
    if unreal >= -min_loss:
        return None
    max_u = float(pos.get("max_unreal_seen") or 0)
    net_tp = float(pos.get("tp_net_target_usd") or 0)
    keep_frac = max(0.25, min(0.70, _env_float("MEGA_UNDERWATER_KEEP_PEAK_FRAC", 0.40)))
    if net_tp > 0 and max_u >= net_tp * keep_frac:
        return None
    return "TIME-STOP"


def _mega_peak_capture_until_tp_enabled() -> bool:
    """TP gelene kadar tepeden takip; tam TP'de TP kapat."""
    return _env_bool("MEGA_PEAK_CAPTURE_UNTIL_TP", False)


def _mega_peak_capture_close_reason(
    pos: dict[str, Any],
    *,
    stake: float,
    lev: int,
    mc: Any,
    tp_g: float,
) -> str | None:
    """
    Önce tam TP (hedef geldi → TP), değilse tepe geri çekilmesinde TP-PEAK.
    """
    if not _mega_peak_capture_until_tp_enabled():
        return None
    net_tp = float(pos.get("tp_net_target_usd") or 0)
    if net_tp <= 0:
        return None
    max_u = float(pos.get("max_unreal_seen") or 0)
    unreal = float(pos.get("unrealized_pnl") or 0)
    if unreal <= 0 and max_u <= 0:
        return None
    from elite_trader.fee_economics import (
        estimate_close_pnl,
        exit_net_passes,
        min_gross_for_final_net,
        round_trip_fee_usd,
    )

    est = estimate_close_pnl(
        unreal,
        stake,
        lev,
        entry_fee=float(pos.get("entry_fee") or 0) or None,
        pos=pos,
        client=mc,
    )
    final_net = float(est.get("final_pnl") or 0)
    min_g = min_gross_for_final_net(stake, lev, mode_id="mega", pos=pos, client=mc)
    net_ok = exit_net_passes(final_net, "mega") or unreal >= min_g
    if not net_ok:
        return None

    rt_fee = round_trip_fee_usd(stake, lev)
    tp_gross_need = round(net_tp + rt_fee, 4) if net_tp > 0 else float(tp_g or 0)
    tp_take = max(0.94, min(1.0, _env_float("MEGA_PEAK_TP_TAKE_FRAC", 1.0)))

    # Tam TP — hedef brüt/net görüldüyse beklemeden TP
    if tp_g > 0 and max_u >= tp_g * tp_take and unreal >= min_g:
        return "TP"
    if tp_gross_need > 0 and unreal >= tp_gross_need * tp_take:
        return "TP"
    peak_net = _mega_peak_wallet_net(pos, mc)
    if peak_net >= net_tp * tp_take:
        return "TP"

    # TP öncesi — tepe takibi (küçük geri çekilmede kilitle)
    arm_gross = max(
        1.0,
        _env_float("MEGA_PEAK_TRAIL_ARM_GROSS", _env_float("MEGA_EXCHANGE_ARM_GROSS_USD", 1.5)),
    )
    arm_net = max(2.0, _env_float("MEGA_PEAK_TRAIL_ARM_NET", 3.0))
    retrace = max(
        0.90,
        min(0.995, _env_float("MEGA_PEAK_TRAIL_RETRACE_FRAC", 0.97)),
    )
    if max_u >= arm_gross and unreal > 0 and unreal <= max_u * retrace:
        return "TP-PEAK"
    if peak_net >= arm_net and final_net > 0 and final_net <= peak_net * retrace:
        return "TP-PEAK"
    return None


def _mega_net_tp_close_reason(
    pos: dict[str, Any],
    *,
    stake: float,
    lev: int,
    mc: Any,
) -> str | None:
    """
    Net TP bölgesi görüldüyse market close — brüt TP beklemeden kârı kilitle (WLD fix).
    max_unreal >= net_tp*95% → take_frac veya retrace ile kapat.
    """
    if _mega_peak_capture_until_tp_enabled():
        return None
    if not _env_bool("MEGA_NET_TP_LOCK", True):
        return None
    net_tp = float(pos.get("tp_net_target_usd") or 0)
    if net_tp <= 0:
        return None
    max_u = float(pos.get("max_unreal_seen") or 0)
    unreal = float(pos.get("unrealized_pnl") or 0)
    if unreal <= 0:
        return None
    lock_frac = max(0.85, min(1.0, _env_float("MEGA_NET_TP_LOCK_FRAC", 0.95)))
    if max_u < net_tp * lock_frac:
        return None
    from elite_trader.fee_economics import (
        estimate_close_pnl,
        exit_net_passes,
        min_gross_for_final_net,
    )

    est = estimate_close_pnl(
        unreal,
        stake,
        lev,
        entry_fee=float(pos.get("entry_fee") or 0) or None,
        pos=pos,
        client=mc,
    )
    final_net = float(est.get("final_pnl") or 0)
    min_g = min_gross_for_final_net(stake, lev, mode_id="mega", pos=pos, client=mc)
    net_ok = exit_net_passes(final_net, "mega") or unreal >= min_g
    if not net_ok:
        return None
    take_frac = max(0.88, min(1.0, _env_float("MEGA_NET_TP_TAKE_FRAC", 0.92)))
    if unreal >= net_tp * take_frac or max_u >= net_tp * 0.98:
        return "TP"
    retrace = max(0.85, min(0.99, _env_float("MEGA_NET_TP_RETRACE_FRAC", 0.94)))
    if unreal <= max_u * retrace:
        return "TP-PEAK"
    return None


def mega_needs_fast_exit() -> bool:
    """Net TP / mark spike yakını — position worker interval düşür."""
    if not mega_live_enabled() or not _mega_positions:
        return False
    watch = max(0.80, min(0.98, _env_float("MEGA_FAST_EXIT_WATCH_FRAC", 0.88)))
    mark_frac = max(0.55, min(0.95, _env_float("MEGA_FAST_EXIT_MARK_FRAC", 0.78)))
    take_gross = _mega_spike_take_gross_usd()
    take_watch = max(0.65, min(0.95, _env_float("MEGA_SPIKE_TAKE_WATCH_FRAC", 0.72)))
    for pos in _mega_positions:
        net_tp = float(pos.get("tp_net_target_usd") or 0)
        stake = float(pos.get("stake_usd") or 1)
        lev = max(int(pos.get("leverage") or 2), 1)
        max_u = float(pos.get("max_unreal_seen") or 0)
        unreal = float(pos.get("unrealized_pnl") or 0)
        if take_gross > 0 and (
            max_u >= take_gross * take_watch or unreal >= take_gross * take_watch
        ):
            return True
        if net_tp > 0 and (max_u >= net_tp * watch or unreal >= net_tp * watch):
            return True
        if _mega_mark_spike_enabled():
            flash = _mega_mark_flash_floor(stake, lev)
            if flash > 0 and (max_u >= flash * mark_frac or unreal >= flash * mark_frac):
                return True
    return False


def _mega_scalp_hub_trusted(*, max_age_ms: float | None = None) -> bool:
    if not _env_bool("MEGA_SCALP_HUB_TRUST", True):
        return False
    try:
        from elite_trader.mega_async_hub import hub_mark_fresh, mega_hub_enabled

        if not mega_hub_enabled():
            return False
        ms = float(max_age_ms if max_age_ms is not None else _env_float("MEGA_HUB_MARK_FRESH_MS", 100.0))
        return hub_mark_fresh(max_age_ms=ms)
    except Exception:
        return False


def _mega_spike_bypass_fill_verify(exit_reason: str) -> bool:
    if not _env_bool("MEGA_SPIKE_BYPASS_FILL_VERIFY", False):
        return False
    return str(exit_reason or "").upper() == "SPIKE-FLASH"


def _mega_demo_fast_close_enabled() -> bool:
    """Demo-fapi — brüt ≥ eşikte slippage/IOC atla, REST uPnL + mark yönü."""
    if not _env_bool("MEGA_DEMO_FAST_CLOSE", True):
        return False
    if _env_bool("MEGA_BINANCE_FUTURES_DEMO", False) or _env_bool(
        "BINANCE_FUTURES_DEMO", False
    ):
        return True
    return _env_bool("MEGA_DEMO_FAST_CLOSE_ON_LIVE", False)


def _mega_demo_fast_close_gross_usd() -> float:
    return max(0.0, _env_float("MEGA_DEMO_FAST_CLOSE_GROSS_USD", 30.0))


def _mega_demo_fast_close_market() -> bool:
    return _env_bool("MEGA_DEMO_FAST_CLOSE_MARKET", True)


def _mega_demo_fast_close_eligible(
    pos: dict[str, Any], mc: Any | None = None
) -> bool:
    if not _mega_demo_fast_close_enabled():
        return False
    if not mc or mc.paper or not pos.get("on_exchange"):
        return False
    return _mega_api_gross_unreal(pos) >= _mega_demo_fast_close_gross_usd()


def _mega_demo_fast_close_price_ok(
    pos: dict[str, Any], mc: Any | None = None
) -> tuple[bool, str]:
    """Yalnızca mark/entry yönü — komisyon +$30 brüt ile zaten karşılanmış sayılır."""
    entry = float(pos.get("entry_price") or 0)
    side = str(pos.get("side") or "LONG").upper()
    sym = str(pos.get("symbol") or "")
    if entry <= 0:
        return False, "entry yok"
    mark = float(pos.get("mark_price") or pos.get("current_price") or 0)
    if mark <= 0 and sym:
        ep = _exchange_row(sym, side)
        if ep:
            mark = float(ep.get("mark_price") or 0)
    if mark <= 0:
        return False, "mark fiyat yok"
    if side == "LONG" and mark + 1e-12 < entry:
        return False, f"mark {mark:.6g} < entry {entry:.6g}"
    if side == "SHORT" and mark > entry + 1e-12:
        return False, f"mark {mark:.6g} > entry {entry:.6g}"
    return True, ""


def _mega_arm_demo_fast_close(pos: dict[str, Any], mc: Any | None) -> bool:
    if not _mega_demo_fast_close_eligible(pos, mc):
        pos.pop("demo_fast_close", None)
        return False
    ok_px, detail = _mega_demo_fast_close_price_ok(pos, mc)
    if not ok_px:
        pos.pop("demo_fast_close", None)
        return False
    gross = _mega_api_gross_unreal(pos)
    pos["demo_fast_close"] = True
    pos["tp_fast_close"] = True
    pos["pre_send_gross"] = gross
    pos["pre_send_net"] = _mega_api_wallet_net(pos, mc=mc, gross=gross)
    pos.pop("fill_verify_ok", None)
    pos.pop("fill_verify_detail", None)
    pos.pop("fill_verify_at_ms", None)
    return True


def _mega_settle_waits(
    exit_reason: str, pos: dict[str, Any] | None = None
) -> tuple[float, ...]:
    if pos and (pos.get("demo_fast_close") or pos.get("tp_fast_close")):
        raw = os.getenv("MEGA_DEMO_FAST_SETTLE_WAITS", "0.06,0.10,0.18").strip()
        try:
            vals = tuple(float(x.strip()) for x in raw.split(",") if x.strip())
            if vals:
                return vals
        except ValueError:
            pass
        return (0.06, 0.10, 0.18)
    r = str(exit_reason or "").upper()
    if r in ("SPIKE-FLASH", "SPIKE-QUICK", "SPIKE-PEAK") and _env_bool(
        "MEGA_SPIKE_FAST_SETTLE", True
    ):
        raw = os.getenv("MEGA_SPIKE_SETTLE_WAITS", "0.22,0.38,0.55").strip()
        try:
            vals = tuple(float(x.strip()) for x in raw.split(",") if x.strip())
            if vals:
                return vals
        except ValueError:
            pass
        return (0.22, 0.38, 0.55)
    if r == "SL" or r.startswith("SL-"):
        raw = os.getenv("MEGA_SL_SETTLE_WAITS", "0.35,0.7,1.2,2.0").strip()
        try:
            vals = tuple(float(x.strip()) for x in raw.split(",") if x.strip())
            if vals:
                return vals
        except ValueError:
            pass
        return (0.35, 0.7, 1.2, 2.0)
    raw = os.getenv("MEGA_SETTLE_WAITS", "0.45,0.85,1.35,2.0").strip()
    try:
        vals = tuple(float(x.strip()) for x in raw.split(",") if x.strip())
        if vals:
            return vals
    except ValueError:
        pass
    return (0.45, 0.85, 1.35, 2.0)


def _mega_settle_close_from_api(
    pos: dict[str, Any],
    mc: Any,
    *,
    exit_reason: str = "",
    close_order_id: str | int | None = None,
) -> dict[str, Any] | None:
    """Kapanış sonrası demo-fapi userTrades — yanlış TP orderId olsa bile son fill bul."""
    if not mc or mc.paper or not pos.get("on_exchange"):
        return None
    from elite_trader.exchange_settlement import (
        settle_position_close,
        settlement_has_api_close_fills,
    )

    sym = str(pos.get("symbol") or "")
    coin = sym.replace("USDT", "").upper()
    oid: str | int | None = close_order_id or pos.get("exchange_close_order_id")
    for i, wait in enumerate(_mega_settle_waits(exit_reason, pos)):
        try:
            settled = settle_position_close(
                mc,
                pos,
                close_order_id=oid if i == 0 else None,
                settle_wait_sec=wait,
            )
        except Exception:
            settled = None
        if settled and settlement_has_api_close_fills(settled):
            return settled
        oid = None
    try:
        from elite_trader.mega_close_sync import sync_priority_coins_from_exchange

        if coin:
            sync_priority_coins_from_exchange([coin])
    except Exception:
        pass
    try:
        return settle_position_close(
            mc,
            pos,
            close_order_id=None,
            settle_wait_sec=0.25,
        )
    except Exception:
        return None


def _mega_spike_trust_api_send() -> bool:
    """Kapalı — yalnızca hızlı book fill doğrulaması sonrası emir (slippage NET-LOSS fix)."""
    return _env_bool("MEGA_SPIKE_TRUST_API_SEND", False)


def _mega_profit_close_use_ioc() -> bool:
    return _env_bool("MEGA_PROFIT_CLOSE_IOC", True)


def _mega_profit_close_market_fallback() -> bool:
    return _env_bool("MEGA_PROFIT_CLOSE_MARKET_FALLBACK", False)


def _mega_order_executed_qty(order: dict[str, Any], target_qty: float) -> float:
    if not order:
        return 0.0
    for key in ("executedQty", "cumQty", "filled_qty", "qty"):
        raw = order.get(key)
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return float(target_qty) if order.get("paper") else 0.0


def _mega_send_profit_close_order(
    mc: Any,
    coin: str,
    pos: dict[str, Any],
    close_side: str,
    qty: float,
    *,
    exit_reason: str,
) -> tuple[dict[str, Any] | None, str]:
    """
    Kâr kilidi — önce bid/ask IOC limit (slippage yok); MARKET yalnızca fallback (varsayılan kapalı).
    """
    if not mc or mc.paper or qty <= 0:
        return None, "paper veya qty=0"
    sym = str(pos.get("symbol") or "")
    if pos.get("demo_fast_close") and _mega_demo_fast_close_market():
        order = mc.market_order(coin, close_side, qty, reduce_only=True)
        order["_close_exec_mode"] = "market_demo_fast"
        return order, ""
    if _mega_profit_close_use_ioc():
        from elite_trader.exchange_fill_truth import exit_fill_price

        book_ms = max(40.0, _env_float("MEGA_SEND_FILL_BOOK_MAX_MS", 60.0))
        fill_px, _meta = exit_fill_price(pos, client=mc, max_book_age_ms=book_ms)
        if fill_px and fill_px > 0:
            try:
                order = mc.limit_order(
                    coin,
                    close_side,
                    qty,
                    fill_px,
                    reduce_only=True,
                    time_in_force="IOC",
                )
                exec_qty = _mega_order_executed_qty(order, qty)
                min_frac = max(0.92, min(1.0, _env_float("MEGA_IOC_MIN_FILL_FRAC", 0.98)))
                if exec_qty >= qty * min_frac:
                    order["_close_exec_mode"] = "ioc_limit"
                    order["_close_limit_px"] = fill_px
                    return order, ""
                detail = (
                    f"IOC dolmadı {exec_qty:.4f}/{qty:.4f} @ {fill_px} "
                    f"({sym})"
                )
                if not _mega_profit_close_market_fallback():
                    return None, detail
            except Exception as exc:
                detail = f"IOC kapanış hata: {exc}"
                if not _mega_profit_close_market_fallback():
                    return None, detail
        elif not _mega_profit_close_market_fallback():
            return None, "bookTicker yok — MARKET kapalı"
    if not _mega_profit_close_market_fallback():
        return None, "MARKET fallback kapalı — IOC/book uygun değil"
    order = mc.market_order(coin, close_side, qty, reduce_only=True)
    order["_close_exec_mode"] = "market"
    return order, ""


def _mega_fast_fill_before_send(
    pos: dict[str, Any],
    exit_reason: str,
    mc: Any,
) -> tuple[bool, str]:
    """MARKET/IOC öncesi — taze book fill; eski fill_verify önbelleği kullanılmaz."""
    from elite_trader.fee_economics import is_profit_tp_exit

    if not mc or mc.paper or not pos.get("on_exchange"):
        return True, ""
    if not is_profit_tp_exit(exit_reason):
        return True, ""
    if pos.get("demo_fast_close") or _mega_arm_demo_fast_close(pos, mc):
        return True, "demo_fast_close"
    if _mega_spike_bypass_fill_verify(exit_reason) and pos.get("tp_fast_close"):
        return True, ""
    from elite_trader.exchange_fill_truth import mega_profit_fill_verify_fast

    ok, detail, _snap = mega_profit_fill_verify_fast(
        pos,
        exit_reason,
        client=mc,
        mode_id="mega",
        force_fresh=True,
        at_send=True,
    )
    if not ok:
        return False, detail
    return True, ""


def _mega_live_profit_send_ok(
    pos: dict[str, Any],
    exit_reason: str,
    mc: Any,
) -> tuple[bool, str]:
    """Canlı kâr çıkışı — tek hızlı fill doğrulama + hafif REST uPnL (SPIKE $4)."""
    ex_mid = "mega"
    if mc and not mc.paper and pos.get("on_exchange"):
        try:
            refresh_mega_positions_cache(
                force=True, skip_wallet=True, panel_critical=True
            )
            _sync_pos_from_exchange(pos, list(_mega_positions_cache), mode_id="mega")
        except Exception:
            pass
        ok_api, api_detail = _mega_exchange_profit_at_send_ok(pos, exit_reason, mc)
        if not ok_api:
            return False, api_detail
    if _mega_arm_demo_fast_close(pos, mc) or pos.get("demo_fast_close"):
        return True, "demo_fast_close"
    from elite_trader.exchange_fill_truth import mega_profit_fill_verify_fast

    ok, detail, snap = mega_profit_fill_verify_fast(
        pos,
        exit_reason,
        client=mc,
        mode_id=ex_mid,
        at_send=True,
        force_fresh=True,
    )
    if snap:
        pos["close_signal"] = snap
    if not ok:
        return False, detail
    return True, ""


def _persist_open_meta_throttled(*, force: bool = False) -> None:
    """Disk yazımını seyrekleştir — REST döngüsü <1s kalsın."""
    global _mega_persist_meta_ts
    now = time.time()
    iv = max(0.8, _env_float("MEGA_META_PERSIST_SEC", 1.5))
    if not force and _mega_persist_meta_ts and (now - _mega_persist_meta_ts) < iv:
        return
    _persist_open_meta()
    _mega_persist_meta_ts = now


def _fetch_open_algo_orders(mc: Any, *, force: bool = False) -> list[dict[str, Any]]:
    """open_algo_orders — kısa TTL önbellek (verify sık, API seyrek)."""
    global _mega_algo_orders_cache, _mega_algo_orders_ts
    if not mc or mc.paper:
        return []
    now = time.time()
    ttl = max(0.08, _env_float("MEGA_ALGO_ORDERS_CACHE_SEC", 0.14))
    if (
        not force
        and _mega_algo_orders_ts
        and (now - _mega_algo_orders_ts) < ttl
        and _mega_algo_orders_cache
    ):
        return list(_mega_algo_orders_cache)
    try:
        orders = mc.open_algo_orders() or []
    except Exception:
        return list(_mega_algo_orders_cache)
    _mega_algo_orders_cache = orders
    _mega_algo_orders_ts = now
    return orders


def _invalidate_algo_orders_cache() -> None:
    global _mega_algo_orders_ts
    _mega_algo_orders_ts = 0.0


def _verify_exchange_tps(mc: Any, *, all_orders: list[dict[str, Any]] | None = None) -> None:
    """Borsada olmayan algo TP id'lerini temizle — gereksiz re-arm önle."""
    if not mc or mc.paper:
        return
    orders = all_orders if all_orders is not None else _fetch_open_algo_orders(mc)
    if not orders and all_orders is None:
        return
    by_coin: dict[str, list[dict[str, Any]]] = {}
    for row in orders:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            by_coin.setdefault(sym.replace("USDT", ""), []).append(row)
    changed = False
    for pos in _mega_positions:
        oid = str(pos.get("exchange_tp_order_id") or "").strip()
        if not oid:
            continue
        coin = str(pos.get("symbol") or "").replace("USDT", "")
        ids = {str(r.get("algoId") or "") for r in by_coin.get(coin, [])}
        if oid not in ids:
            pos.pop("exchange_tp_order_id", None)
            pos.pop("exchange_tp_is_algo", None)
            pos.pop("exchange_tp_stop", None)
            pos.pop("exchange_tp_net", None)
            changed = True
    if changed:
        _persist_open_meta_throttled(force=True)


def _verify_and_adopt_exchange_tps(mc: Any, *, force_fetch: bool = False) -> int:
    """Tek open_algo_orders çağrısı — verify + adopt."""
    orders = _fetch_open_algo_orders(mc, force=force_fetch)
    if not orders and not _mega_positions:
        return 0
    _verify_exchange_tps(mc, all_orders=orders)
    if not orders:
        return 0
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for row in orders:
        sym = str(row.get("symbol") or "").upper()
        if sym:
            by_sym.setdefault(sym, []).append(row)
    adopted = 0
    for pos in _mega_positions:
        if not pos.get("on_exchange") or pos.get("exchange_tp_order_id"):
            continue
        sym = str(pos.get("symbol") or "").upper()
        if _adopt_exchange_tp_from_orders(pos, by_sym.get(sym) or [], sym=sym):
            adopted += 1
    if adopted:
        _invalidate_algo_orders_cache()
    return adopted


def _tp_pos_key(pos: dict[str, Any]) -> str:
    return f"{str(pos.get('symbol') or '').upper()}:{str(pos.get('side') or 'LONG').upper()}"


def _position_row_for_disk(pos: dict[str, Any]) -> dict[str, Any]:
    """JSON persist — açılış/kapanış kaydı için tam pozisyon satırı."""
    row = dict(pos)
    for key in ("entry_time",):
        val = row.get(key)
        if isinstance(val, (int, float)) and float(val) > 1e12:
            row[key] = float(val) / 1000.0 if float(val) > 1e15 else float(val)
    ph = row.get("price_history")
    if isinstance(ph, list) and len(ph) > 200:
        row["price_history"] = ph[-200:]
    th = row.get("time_history")
    if isinstance(th, list) and len(th) > 200:
        row["time_history"] = th[-200:]
    return row


def _open_rows_to_restore(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """9006 paper sim — restart sonrası açık pozisyonları geri yükle."""
    sim_book = mega_paper_sim_only() or (
        mega_sim_enabled() and not mega_live_orders_enabled()
    )
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        on_ex = bool(row.get("on_exchange"))
        if sim_book:
            if on_ex and mega_live_enabled():
                continue
            row.setdefault("sim", not on_ex)
            out.append(row)
        elif on_ex:
            out.append(row)
    return out


def _persist_open_book(*, force: bool = False) -> None:
    """Açık pozisyon defteri — restart sonrası panel/exit motoru kaybolmasın."""
    global _mega_persist_open_book_ts
    if not mega_motor_active():
        return
    now = time.time()
    iv = max(1.0, _env_float("MEGA_OPEN_BOOK_PERSIST_SEC", 5.0))
    if not force and (now - float(_mega_persist_open_book_ts or 0)) < iv:
        return
    _mega_persist_open_book_ts = now
    path = _mega_open_book_path()
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "instance_id": mega_instance_id(),
        "next_position_id": int(_mega_position_id),
        "open": [_position_row_for_disk(p) for p in _mega_positions],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(".json.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"  ⚠ MEGA açık kitap yazılamadı ({path.name}): {exc}")
        try:
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass


def _load_open_book_from_disk() -> None:
    global _mega_positions, _mega_position_id
    path = _mega_open_book_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    nxt = int(data.get("next_position_id") or 0)
    if nxt > _mega_position_id:
        _mega_position_id = nxt
    rows = _open_rows_to_restore([dict(r) for r in (data.get("open") or [])])
    if not rows:
        return
    if not _mega_positions:
        _mega_positions[:] = rows
        print(f"  📂 MEGA açık kitap yüklendi: {len(rows)} pozisyon")
        return
    live_ids = {int(p.get("id") or 0) for p in _mega_positions}
    added = 0
    for row in rows:
        pid = int(row.get("id") or 0)
        if pid and pid in live_ids:
            continue
        _mega_positions.append(row)
        live_ids.add(pid)
        added += 1
    if added:
        print(f"  📂 MEGA açık kitap birleştirildi: +{added} (toplam {len(_mega_positions)})")
    enrich_mega_positions_open_times(_mega_positions)


def _record_mega_open_ledger(pos: dict[str, Any]) -> None:
    """Açılış — disk + parallel mega kitabı."""
    _persist_open_book(force=True)
    try:
        from elite_trader import parallel_universe_engine as pe

        pe.record_live_open("mega", dict(pos))
    except Exception:
        pass


def _record_mega_close_ledger(closed: dict[str, Any]) -> None:
    """Kapanış — kapalı deftere (parallel sync _append_mega_closed_record içinde)."""
    _persist_open_book(force=True)


def _mega_close_audit_path() -> Path:
    return mega_instance_data_dir() / "mega_close_audit.jsonl"


def _mega_system_context_for_audit(
    phase: str,
    pos: dict[str, Any] | None,
    *,
    exit_reason: str | None = None,
    settlement: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not pos or not _env_bool("MEGA_SYSTEM_CONTEXT_AUDIT", True):
        return None
    try:
        from elite_trader.mega_system_context import build_system_context

        return build_system_context(
            phase,
            pos=pos,
            exit_reason=exit_reason,
            settlement=settlement,
        )
    except Exception:
        return None


def _audit_mega_close(event: str, **fields: Any) -> None:
    """Bot kapanış denemesi / emir / settlement — JSONL (Binance ile karşılaştırma)."""
    row: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "instance": mega_instance_id(),
    }
    for k, v in fields.items():
        if v is not None:
            row[k] = v
    ap = _mega_close_audit_path()
    ap.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ap.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        print(f"  ⚠ MEGA close audit yazılamadı: {exc}")


def load_mega_close_audit(*, limit: int = 100) -> list[dict[str, Any]]:
    """Son bot kapanış audit satırları (panel/API)."""
    p = _mega_close_audit_path()
    if not p.is_file():
        return []
    lim = max(1, min(int(limit), 500))
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-lim:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_open_meta() -> dict[str, Any]:
    if not _mega_open_meta_path().is_file():
        return {}
    try:
        return json.loads(_mega_open_meta_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _apply_open_meta_to_positions() -> None:
    meta = _load_open_meta()
    if not meta:
        return
    for pos in _mega_positions:
        row = meta.get(_tp_pos_key(pos))
        if not isinstance(row, dict):
            continue
        if not pos.get("exchange_tp_order_id"):
            oid = str(row.get("exchange_tp_order_id") or "").strip()
            if oid:
                pos["exchange_tp_order_id"] = oid
                pos["exchange_tp_is_algo"] = row.get("exchange_tp_is_algo")
                pos["exchange_tp_stop"] = row.get("exchange_tp_stop")
            if row.get("exchange_tp_arm_failed"):
                pos["exchange_tp_arm_failed"] = True
                pos["exchange_tp_arm_fail_code"] = row.get("exchange_tp_arm_fail_code")
        if not pos.get("exchange_lock_order_id"):
            lock_oid = str(row.get("exchange_lock_order_id") or "").strip()
            if lock_oid:
                pos["exchange_lock_order_id"] = lock_oid
                pos["exchange_lock_is_algo"] = row.get("exchange_lock_is_algo")
                pos["exchange_lock_stop"] = row.get("exchange_lock_stop")
                pos["exchange_lock_net"] = row.get("exchange_lock_net")
        if pos.get("exchange_lock_milestone") is None and row.get("exchange_lock_milestone") is not None:
            pos["exchange_lock_milestone"] = row.get("exchange_lock_milestone")
        if pos.get("exchange_tp_net") is None and row.get("exchange_tp_net") is not None:
            pos["exchange_tp_net"] = row.get("exchange_tp_net")
        if pos.get("exchange_peak_lock_net") is None and row.get("exchange_peak_lock_net") is not None:
            pos["exchange_peak_lock_net"] = row.get("exchange_peak_lock_net")
        if pos.get("exchange_peak_tp_net") is None and row.get("exchange_peak_tp_net") is not None:
            pos["exchange_peak_tp_net"] = row.get("exchange_peak_tp_net")
        for key in (
            "entry_time",
            "entry_time_str",
            "opened_at_iso",
            "exchange_update_ms",
            "entry_time_locked",
        ):
            if row.get(key) is not None and not pos.get(key):
                pos[key] = row[key]


def _persist_open_meta() -> None:
    rows: dict[str, Any] = {}
    for pos in _mega_positions:
        tp_oid = str(pos.get("exchange_tp_order_id") or "").strip()
        lock_oid = str(pos.get("exchange_lock_order_id") or "").strip()
        if (
            not tp_oid
            and not lock_oid
            and not pos.get("exchange_tp_arm_failed")
            and not float(pos.get("entry_time") or 0)
        ):
            continue
        rows[_tp_pos_key(pos)] = {
            "entry_time": pos.get("entry_time"),
            "entry_time_str": pos.get("entry_time_str"),
            "opened_at_iso": pos.get("opened_at_iso"),
            "exchange_update_ms": pos.get("exchange_update_ms"),
            "entry_time_locked": bool(pos.get("entry_time_locked")),
            "exchange_tp_order_id": tp_oid or None,
            "exchange_tp_is_algo": pos.get("exchange_tp_is_algo"),
            "exchange_tp_stop": pos.get("exchange_tp_stop"),
            "exchange_tp_arm_failed": bool(pos.get("exchange_tp_arm_failed")),
            "exchange_tp_arm_fail_code": pos.get("exchange_tp_arm_fail_code"),
            "exchange_lock_order_id": lock_oid or None,
            "exchange_lock_is_algo": pos.get("exchange_lock_is_algo"),
            "exchange_lock_stop": pos.get("exchange_lock_stop"),
            "exchange_lock_net": pos.get("exchange_lock_net"),
            "exchange_lock_milestone": pos.get("exchange_lock_milestone"),
            "exchange_tp_net": pos.get("exchange_tp_net"),
            "exchange_tp_gross": pos.get("exchange_tp_gross"),
            "exchange_lock_gross": pos.get("exchange_lock_gross"),
            "exchange_peak_lock_net": pos.get("exchange_peak_lock_net"),
            "exchange_peak_lock_gross": pos.get("exchange_peak_lock_gross"),
            "exchange_peak_tp_net": pos.get("exchange_peak_tp_net"),
            "exchange_peak_tp_gross": pos.get("exchange_peak_tp_gross"),
        }
    try:
        _mega_open_meta_path().parent.mkdir(parents=True, exist_ok=True)
        _mega_open_meta_path().write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _mega_hub_mark_hot() -> bool:
    """Mark WS taze — UDS şart değil; positionRisk REST'i seyrekleştir."""
    try:
        from elite_trader.mega_async_hub import hub_mark_fresh, mega_hub_enabled

        if not mega_hub_enabled() or not mega_positions_cache_nonempty():
            return False
        mark_ms = max(80.0, _env_float("MEGA_HUB_MARK_FRESH_MS", 120.0))
        return hub_mark_fresh(max_age_ms=mark_ms)
    except Exception:
        return False


def _mega_rest_interval_sec() -> float:
    safe = _mega_rate_limit_safe_mode()
    if _mega_hub_mark_hot():
        return max(30.0 if safe else 10.0, _env_float("MEGA_HUB_REST_IDLE_SEC", 45.0 if safe else 18.0))
    if _mega_positions or _mega_positions_cache:
        return max(8.0 if safe else 0.45, _env_float("MEGA_REST_POLL_SEC", 12.0 if safe else 1.0))
    return _mega_cache_ttl_idle_sec()


def _mega_rest_tick(*, force_sync: bool = False) -> None:
    """Hafif REST — yalnızca positionRisk cache + TP arm (sync motorları ayrı thread)."""
    global _mega_wallet_fetch_ts, _mega_server_time_ts, _mega_api_ping_ts
    if not mega_live_enabled():
        return
    try:
        from elite_trader.network_guard import binance_rest_enabled

        if not binance_rest_enabled() and not force_sync:
            return
    except Exception:
        pass
    mc = get_mega_client()
    if not mc or mc.paper:
        return
    if force_sync:
        from elite_trader.mega_position_sync import wake_mega_position_sync

        wake_mega_position_sync(force=True)
    now = time.time()
    time_iv = max(20.0, _env_float("MEGA_SERVER_TIME_SEC", 45.0))
    if force_sync or (now - float(_mega_server_time_ts or 0)) >= time_iv:
        try:
            mc.sync_server_time(force=force_sync)
            _mega_server_time_ts = now
        except Exception:
            pass
    _apply_open_meta_to_positions()
    hub_hot = False
    mark_hot = _mega_hub_mark_hot()
    try:
        from elite_trader.mega_async_hub import hub_cache_hot, mega_hub_enabled

        hub_hot = mega_hub_enabled() and hub_cache_hot()
    except Exception:
        pass
    if not (hub_hot and _env_bool("MEGA_TP_VERIFY_SKIP_WHEN_ARMED", True)):
        _maybe_verify_exchange_tps(mc, time.time())
    elif _mega_need_tp_verify():
        _maybe_verify_exchange_tps(mc, time.time())
    has_open = bool(_mega_positions) or bool(_mega_positions_cache)
    motor_stale = _mega_positions_list_stale(
        max_sec=max(_mega_cache_ttl_open_sec(), _env_float("MEGA_CACHE_MAX_STALE_SEC", 0.55))
    )
    force_cache = force_sync or motor_stale
    reconcile_sec = max(60.0, _env_float("MEGA_HUB_RECONCILE_SEC", 180.0))
    if (mark_hot or hub_hot) and not force_sync and not motor_stale and not force_cache:
        touch_mega_cache_from_hub_marks()
    elif (mark_hot or hub_hot) and not force_sync and not force_cache:
        touch_mega_cache_from_hub_marks()
        refresh_mega_positions_cache(
            force=False, skip_wallet=True, panel_critical=False
        )
    else:
        refresh_mega_positions_cache(
            force=force_cache, skip_wallet=True, panel_critical=False
        )
    if not _mega_positions and _mega_positions_cache:
        from elite_trader.mega_position_sync import wake_mega_position_sync

        wake_mega_position_sync(force=False)
    tp_arm_batch = max(1, int(_env_float("MEGA_TP_ARM_BATCH", 1)))
    armed = 0
    if mega_exchange_dual_tp_enabled():
        dual_batch = max(1, int(_env_float("MEGA_DUAL_TP_BATCH", 4)))
        updated = 0
        for row in _mega_positions:
            if row.get("on_exchange"):
                u = float(row.get("unrealized_pnl") or 0)
                fg = row.get("fill_gross_unreal")
                if (
                    u >= _mega_exchange_arm_gross()
                    and fg is not None
                    and float(fg) < 0
                    and (
                        row.get("exchange_tp_order_id")
                        or row.get("exchange_lock_order_id")
                    )
                ):
                    _mega_disarm_exchange_algos(
                        row,
                        mc,
                        reason=f"mark uPnL ${u:.2f} bid fill ${float(fg):.2f}",
                    )
                _maybe_update_exchange_dual_tp(row, mc)
                updated += 1
                if updated >= dual_batch:
                    break
    else:
        for row in _mega_positions:
            if row.get("on_exchange") and not row.get("exchange_tp_order_id"):
                if not row.get("exchange_tp_arm_failed"):
                    _maybe_arm_exchange_tp(row, mc)
                    armed += 1
                    if armed >= tp_arm_batch:
                        break
        if mega_exchange_trail_lock_enabled():
            lock_batch = max(1, int(_env_float("MEGA_TRAIL_LOCK_BATCH", 2)))
            updated = 0
            for row in _mega_positions:
                if row.get("on_exchange"):
                    _maybe_update_exchange_trail_lock(row, mc)
                    updated += 1
                    if updated >= lock_batch:
                        break
    fee_iv = max(3.0, _env_float("MEGA_ENTRY_FEE_REST_SEC", 6.0))
    for pos in _mega_positions:
        pid = int(pos.get("id") or 0)
        if not pid or (now - float(_mega_entry_fee_attempt_ts.get(pid) or 0)) < fee_iv:
            continue
        try:
            from elite_trader.exchange_trade_truth import enrich_open_entry_fee_api
            from elite_trader.fee_economics import entry_fee_api_ready

            enrich_open_entry_fee_api(pos, mc, allow_fetch=True)
            if entry_fee_api_ready(pos):
                _mega_entry_fee_attempt_ts[pid] = now
        except Exception:
            pass
        break
    wallet_iv = max(3.0, _env_float("MEGA_WALLET_REST_SEC", 6.0))
    if (time.time() - float(_mega_wallet_fetch_ts or 0)) >= wallet_iv:
        _fetch_wallet(force=False)
        _mega_wallet_fetch_ts = now
    ping_iv = max(25.0, _env_float("MEGA_CONNECTION_PING_SEC", 45.0))
    if (now - float(_mega_api_ping_ts or 0)) >= ping_iv:
        try:
            if mc.api_ping():
                from elite_trader.network_guard import note_success

                note_success()
                from elite_trader.connection_alerts import note_binance_success

                note_binance_success()
        except Exception:
            pass
        _mega_api_ping_ts = now
    if has_open and _mega_positions and mega_motor_active():
        now_eval = time.time()
        eval_iv = _mega_exit_eval_interval_sec()
        if force_sync or (now_eval - float(_mega_last_exit_eval_ts or 0)) >= eval_iv:
            bulk: dict[str, float] = {}
            try:
                from binance_futures_trader.mark_ws import get_mark_prices_bulk

                bulk = {
                    str(k).upper().replace("USDT", ""): float(v)
                    for k, v in (get_mark_prices_bulk(max_recv_age_sec=2.0) or {}).items()
                    if float(v or 0) > 0
                }
            except Exception:
                bulk = {}
            if not bulk:
                bulk = _mega_sim_price_bulk()
            evaluate_mega_exits(bulk)
    _persist_open_meta_throttled()


def _mega_need_tp_verify() -> bool:
    return any(
        p.get("on_exchange")
        and not p.get("exchange_tp_order_id")
        and not p.get("exchange_tp_arm_failed")
        for p in _mega_positions
    )


def _maybe_verify_exchange_tps(mc: Any, now: float) -> None:
    """TP verify/adopt — REST hot path; eksik TP varken ~150ms."""
    global _mega_tp_verify_ts, _mega_last_tp_verify_ms
    urgent = _mega_need_tp_verify()
    if urgent:
        iv = max(0.10, _env_float("MEGA_TP_VERIFY_URGENT_SEC", 0.15))
    else:
        iv = max(0.25, _env_float("MEGA_TP_VERIFY_SEC", 0.55))
    if not (urgent or (now - float(_mega_tp_verify_ts or 0)) >= iv):
        return
    t0 = time.perf_counter()
    _verify_and_adopt_exchange_tps(mc, force_fetch=urgent)
    _mega_tp_verify_ts = now
    _mega_last_tp_verify_ms = round((time.perf_counter() - t0) * 1000.0, 1)


def run_mega_position_sync_tick(*, force: bool = False) -> None:
    """positionRisk → yerel kitap (TP verify REST döngüsünde)."""
    global _mega_sync_ts
    if not mega_live_enabled():
        return
    try:
        from elite_trader.network_guard import binance_rest_enabled

        if not binance_rest_enabled() and not force:
            return
    except Exception:
        pass
    mc = get_mega_client()
    if not mc or mc.paper:
        return
    now = time.time()
    has_open = bool(_mega_positions) or bool(_mega_positions_cache)
    if not has_open and not force:
        return
    sync_iv = max(15.0, _env_float("MEGA_REST_SYNC_SEC", 25.0))
    if _mega_hub_mark_hot() and not force and _env_bool("MEGA_HUB_SLOW_POSITION_SYNC", False):
        sync_iv = max(sync_iv, _env_float("MEGA_HUB_RECONCILE_SEC", 180.0))
    bootstrap = bool(not _mega_positions and _mega_positions_cache)
    do_sync = force or bootstrap or (
        has_open and (now - float(_mega_sync_ts or 0)) >= sync_iv
    )
    if not do_sync:
        return
    stale_sec = max(sync_iv * 2.0, _env_float("MEGA_POSITION_SYNC_REST_MAX_AGE_SEC", 1.8))
    if _mega_hub_mark_hot() and not force:
        stale_sec = max(
            stale_sec,
            _env_float("MEGA_POSITION_SYNC_HUB_MAX_AGE_SEC", 4.5),
        )
    cache_stale = _mega_positions_list_stale(max_sec=stale_sec)
    if not force and not cache_stale:
        sync_positions_from_exchange(
            force=False, skip_close_scan=True, skip_refresh=True, skip_adopt=True
        )
        _mega_sync_ts = now
        return
    if _mega_rest_poll_allowed(force=force) and (force or cache_stale):
        refresh_mega_positions_cache(
            force=force, skip_wallet=True, panel_critical=has_open and not force
        )
    sync_positions_from_exchange(
        force=force, skip_close_scan=True, skip_refresh=True, skip_adopt=not force
    )
    _mega_sync_ts = now
    if has_open and _mega_algo_auto_prune() and (force or cache_stale):
        prune_mega_algo_orders(mc, force=False)
    _persist_open_meta_throttled()


def _mega_rest_worker_loop() -> None:
    global _mega_rest_force_sync
    while not _mega_rest_stop.is_set():
        force = bool(_mega_rest_force_sync)
        _mega_rest_force_sync = False
        _mega_rest_wake.clear()
        try:
            _mega_rest_tick(force_sync=force)
        except Exception as exc:
            print(f"  ⚠ MEGA REST: {exc}")
        _mega_rest_wake.wait(timeout=_mega_rest_interval_sec())


def _wake_mega_rest(*, force_sync: bool = False) -> None:
    global _mega_rest_force_sync
    if force_sync:
        _mega_rest_force_sync = True
    _mega_rest_wake.set()


def start_mega_rest_worker() -> None:
    global _mega_rest_thread
    if not mega_live_enabled():
        return
    if _mega_rest_thread and _mega_rest_thread.is_alive():
        return
    _mega_rest_stop.clear()
    _mega_rest_thread = threading.Thread(
        target=_mega_rest_worker_loop, name="mega-rest", daemon=True
    )
    _mega_rest_thread.start()
    from elite_trader.mega_close_sync import start_mega_close_sync_motor
    from elite_trader.mega_position_sync import start_mega_position_sync_motor

    start_mega_position_sync_motor()
    start_mega_close_sync_motor()
    try:
        from elite_trader.mega_async_hub import start_mega_async_hub

        start_mega_async_hub()
    except Exception as exc:
        print(f"  ⚠ MEGA async hub başlatılamadı: {exc}")
    start_mega_recovery_worker()
    try:
        from elite_trader.berserk2_btc_context import start_btc_regime_watcher

        start_btc_regime_watcher(get_mega_client())
    except Exception as exc:
        print(f"  ⚠ MEGA BTC rejim izleyici: {exc}")
    try:
        from elite_trader.btc_liq_feed import start_btc_liq_watcher

        start_btc_liq_watcher(get_mega_client())
    except Exception as exc:
        print(f"  ⚠ MEGA BTC liq izleyici: {exc}")
    try:
        from elite_trader.telegram_notify import (
            start_telegram_commands_loop,
            start_telegram_notifier,
            start_telegram_status_loop,
        )

        start_telegram_notifier()
        start_telegram_status_loop()
        start_telegram_commands_loop()
    except Exception as exc:
        print(f"  ⚠ Telegram bildirim başlatılamadı: {exc}")
    _wake_mega_rest(force_sync=True)


def stop_mega_rest_worker() -> None:
    _mega_rest_stop.set()
    _mega_rest_wake.set()
    if _mega_rest_thread and _mega_rest_thread.is_alive():
        _mega_rest_thread.join(timeout=2.0)
    _mega_recovery_stop.set()
    if _mega_recovery_thread and _mega_recovery_thread.is_alive():
        _mega_recovery_thread.join(timeout=2.0)
    try:
        from elite_trader.mega_async_hub import stop_mega_async_hub

        stop_mega_async_hub()
    except Exception:
        pass
    try:
        from elite_trader.berserk2_btc_context import stop_btc_regime_watcher

        stop_btc_regime_watcher()
    except Exception:
        pass
    from elite_trader.mega_close_sync import stop_mega_close_sync_motor
    from elite_trader.mega_position_sync import stop_mega_position_sync_motor

    stop_mega_position_sync_motor()
    stop_mega_close_sync_motor()


def mega_rest_worker_alive() -> bool:
    return bool(_mega_rest_thread and _mega_rest_thread.is_alive())


def _wake_mega_exit_poll(*, force_rest_sync: bool = False) -> None:
    """Sıcak çıkış — yalnızca position worker uyandır; REST sync her tick'te değil."""
    try:
        from binance_elite_pro import _wake_position_price

        _wake_position_price()
    except Exception:
        pass
    if force_rest_sync:
        try:
            from binance_elite_pro import _wake_exchange_position_poll

            _wake_exchange_position_poll()
        except Exception:
            pass
        _wake_mega_rest(force_sync=True)


def mega_live_orders_enabled() -> bool:
    return _env_bool("MEGA_LIVE_ORDERS", False)


def mega_sim_enabled() -> bool:
    return _env_bool("MEGA_SIM_ENABLED", False)


def mega_live_bot_only_closed() -> bool:
    """Canlı MEGA — kapalı tablo yalnızca bot tam kapanışında (sync backfill yok)."""
    if mega_live_orders_enabled() and not mega_sim_enabled():
        return _env_bool("MEGA_CLOSED_BOT_ONLY", True)
    return False


def _is_sync_backfill_close(row: dict[str, Any]) -> bool:
    if row.get("backfilled"):
        return True
    return str(row.get("sync_source") or "") in (
        "exchange_userTrades",
        "exchange_income",
    )


def _mega_closed_persist_allowed(closed: dict[str, Any]) -> bool:
    """Bot-only modda yalnızca SL / zararlı borsa kapanışı sync kaydı yazılsın."""
    if not mega_live_bot_only_closed():
        return True
    if not _is_sync_backfill_close(closed):
        return True
    from elite_trader.fee_economics import is_stop_loss_exit

    reason = str(closed.get("exit_reason") or closed.get("record_reason") or "")
    if is_stop_loss_exit(reason):
        return True
    wallet = float(
        closed.get("wallet_pnl") or closed.get("final_pnl") or closed.get("net_pnl") or 0
    )
    gross = float(closed.get("pnl_usd") or closed.get("pnl_gross_usd") or 0)
    if wallet < -0.005 or gross < -0.005:
        if not is_stop_loss_exit(reason):
            closed["exit_reason"] = "SL"
        closed["sl_close"] = True
        return True
    return False


def _position_still_open(symbol: str, side: str) -> bool:
    sym = str(symbol or "").upper()
    sd = str(side or "").upper()
    for p in _mega_positions:
        if str(p.get("symbol") or "").upper() == sym and str(p.get("side") or "").upper() == sd:
            return True
    return _exchange_row(sym, sd) is not None


def mega_paper_sim_only() -> bool:
    """Paper sim kitap (9006) — borsa emri ve canlı cüzdan marjin kapısı yok."""
    return mega_sim_enabled() and not mega_live_orders_enabled()


def _mega_sim_equity_usd() -> float:
    """Kelly stake yolu — REST cüzdan yokken sim sermayesi."""
    try:
        from elite_trader.paper_book import paper_book_equity_floor

        return paper_book_equity_floor("mega")
    except Exception:
        pass
    floor = max(
        1000.0,
        _env_float("MEGA_MIN_STAKE_USD", 1000.0) * max(1, _mega_max_open()),
    )
    return max(floor, _env_float("MEGA_SIM_EQUITY_USD", 10_000.0))


def mega_motor_active() -> bool:
    """Scan, çıkış, panel — canlı emir veya paper sim."""
    if mega_sim_enabled():
        return True
    return mega_live_enabled()


def mega_credentials_configured() -> bool:
    key = mega_binance_env("BINANCE_API_KEY")
    secret = mega_binance_env("BINANCE_API_SECRET") or mega_binance_env(
        "BINANCE_FUTURES_API_SECRET"
    )
    return bool(key and secret)


def mega_live_enabled() -> bool:
    return mega_live_orders_enabled() and mega_credentials_configured()


def get_mega_client():
    """Lazy singleton — MEGA_BINANCE_* anahtarları."""
    global _mega_client
    if not mega_credentials_configured():
        return None
    with _mega_client_lock:
        if _mega_client is not None:
            return _mega_client
        from binance_futures_trader.client import BinanceFuturesClient

        key = mega_binance_env("BINANCE_API_KEY")
        secret = mega_binance_env("BINANCE_API_SECRET") or mega_binance_env(
            "BINANCE_FUTURES_API_SECRET"
        )
        testnet = _env_bool(
            "MEGA_BINANCE_FUTURES_TESTNET",
            _env_bool("BINANCE_FUTURES_TESTNET", True),
        )
        demo = _env_bool(
            "MEGA_BINANCE_FUTURES_DEMO",
            _env_bool("BINANCE_FUTURES_DEMO", testnet),
        )
        mode = os.getenv("MEGA_BN_FUT_MODE", "testnet" if testnet else "live").strip()
        rest = mega_binance_env("BINANCE_FUTURES_REST_BASE")
        if mega_instance_id() == "9007":
            testnet = True
            demo = True
            mode = "testnet"
            rest = ""
        elif mega_instance_id() in ("9006", "9008"):  # 9008 LIVE eklendi
            if mega_live_orders_enabled():
                testnet = True
                demo = True
                mode = "testnet"
                rest = mega_binance_env("BINANCE_FUTURES_REST_BASE")
            else:
                testnet = False
                demo = False
                mode = "paper"
                rest = ""
        _mega_client = BinanceFuturesClient(
            api_key=key,
            api_secret=secret,
            testnet=testnet,
            futures_demo=demo,
            rest_base=rest or None,
            mode=mode,
        )
        if mega_live_orders_enabled() and not _mega_client.paper:
            try:
                _mega_client.sync_server_time(force=True)
            except Exception:
                pass
            try:
                _mega_client._warm_symbol_rules()
                n_trad = sum(
                    1 for r in _mega_client._symbol_rules.values() if r.get("valid")
                )
                print(
                    f"  ✓ MEGA canlı emir hesabı bağlandı "
                    f"({'demo-fapi' if demo else 'mainnet'}, {n_trad} sembol)"
                )
            except Exception:
                print(
                    f"  ✓ MEGA canlı emir hesabı bağlandı "
                    f"({'demo-fapi' if demo else 'mainnet'})"
                )
        elif _mega_client.paper:
            print("  ⚠ MEGA client paper modda — MEGA_LIVE_ORDERS=1 ve geçerli anahtar gerekir")
            mark_mega_api_outage(reason=_mega_client._auth_error or "paper_at_boot")
    _ensure_mega_closed_loaded()
    return _mega_client


def invalidate_mega_client() -> None:
    """Singleton MEGA client'ı kapat — re-auth için."""
    global _mega_client
    with _mega_client_lock:
        if _mega_client is not None:
            try:
                _mega_client.close()
            except Exception:
                pass
            _mega_client = None


def mega_api_outage_active() -> bool:
    """9007 canlı desk API kesintisi (429/ban/paper) — 9005/9006 etkilenmez."""
    if mega_instance_id() != "9007" or not mega_live_enabled():
        return False
    if _mega_outage_since is not None:
        return True
    try:
        from elite_trader.connection_alerts import ip_ban_active

        if ip_ban_active():
            return True
    except Exception:
        pass
    try:
        from elite_trader.network_guard import skip_rest

        if skip_rest():
            return True
    except Exception:
        pass
    mc = _mega_client
    return bool(mc and mc.paper)


def mark_mega_api_outage(*, reason: str = "") -> None:
    """429/ban veya paper fallback — recovery + fresh start kuyruğu (yalnızca 9007)."""
    global _mega_outage_since, _mega_recovery_pending_fresh_start
    if mega_instance_id() != "9007" or not mega_live_enabled():
        return
    if not _env_bool("MEGA_RECOVERY_ENABLED", True):
        return
    now = time.time()
    if _mega_outage_since is None:
        _mega_outage_since = now
        detail = (reason or "api_outage")[:120]
        print(
            f"  ⚠ MEGA API kesintisi — 9005/9006 devam eder; "
            f"9007 recovery bekliyor ({detail})"
        )
    if _env_bool("MEGA_FRESH_START_ON_RECOVERY", True):
        _mega_recovery_pending_fresh_start = True


def _register_mega_outage_hook() -> None:
    global _mega_outage_hook_registered
    if _mega_outage_hook_registered or mega_instance_id() != "9007":
        return
    try:
        from elite_trader.connection_alerts import register_outage_hook

        register_outage_hook(lambda msg: mark_mega_api_outage(reason=msg))
        _mega_outage_hook_registered = True
    except Exception:
        pass


def fresh_start_mega_9007_after_recovery(*, reason: str = "api_recovery") -> dict[str, Any]:
    """429/ban sonrası sıfır oturum — mega_9007/ arşivlenir (9005/9006 dokunulmaz)."""
    global _mega_positions, _mega_positions_cache, _mega_closed, _mega_position_id
    global _mega_closed_loaded, _mega_wallet, _mega_cache_ts

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = _ROOT / "data" / "deleted_archives" / f"mega_9007_{ts}"
    archive.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "reason": reason,
        "ts": ts,
        "port": 9007,
        "trigger": "mega_api_recovery",
        "paths": [],
    }

    inst_dir = mega_instance_data_dir()
    for child in sorted(inst_dir.iterdir()):
        if not child.is_file():
            continue
        try:
            shutil.copy2(child, archive / child.name)
            manifest["paths"].append(child.name)
            child.unlink()
        except OSError:
            pass

    cleared_closed = clear_mega_closed_records(suppress_backfill=True)
    suppress_mega_closed_backfill()

    _mega_positions = []
    _mega_positions_cache = []
    _mega_wallet = {}
    _mega_cache_ts = 0.0
    _mega_position_id = 1
    _mega_closed = []
    _mega_closed_loaded = True

    try:
        from elite_trader import parallel_universe_engine as pe

        pe.reset_mode_book("mega")
        st = pe._load()
        st.setdefault("starting_capital_by_mode", {}).pop("mega", None)
        pe._save(st)
    except Exception:
        pass

    wallet: dict[str, Any] = {}
    bal = 0.0
    try:
        mc = get_mega_client()
        if mc and not mc.paper:
            wallet = _fetch_wallet(force=True)
            bal = _wallet_balance(wallet)
    except Exception:
        wallet = {}

    if bal > 0:
        _save_session_anchor(bal, reason=reason)
        try:
            from elite_trader import parallel_universe_engine as pe

            pe.set_mode_session_start("mega", bal)
        except Exception:
            pass
    manifest["wallet_anchor"] = bal
    manifest["cleared_closed"] = cleared_closed

    try:
        from elite_trader.data_archive import _load_manifest, _save_manifest

        data = _load_manifest()
        archives = list(data.get("archives") or [])
        archives.append(
            {
                "archive_id": archive.name,
                "port": 9007,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "trigger": "mega_api_recovery",
                "path": str(archive.relative_to(_ROOT)),
                "cleared_closed": cleared_closed,
                "wallet_anchor": bal,
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
    try:
        from elite_trader.mega_control import audit_log

        audit_log("recovery_fresh_start", wallet_anchor=bal, archive=archive.name)
    except Exception:
        pass
    print(
        f"  ✓ MEGA 9007 fresh start — arşiv={archive.name} "
        f"anchor=${bal:.2f} cleared={cleared_closed}"
    )
    return {
        "ok": True,
        "archive": str(archive),
        "wallet_anchor": bal,
        "cleared_closed": cleared_closed,
        "wallet": wallet,
    }


def try_recover_mega_client(*, force: bool = False) -> dict[str, Any]:
    """Ban/429 sonrası paper'dan çık — başarılı olunca isteğe bağlı fresh start."""
    global _mega_outage_since, _mega_recovery_pending_fresh_start, _mega_last_recovery_attempt_ts

    if not mega_live_enabled() or mega_instance_id() != "9007":
        return {"ok": False, "reason": "not_9007_live"}
    if not _env_bool("MEGA_RECOVERY_ENABLED", True):
        return {"ok": False, "reason": "recovery_disabled"}

    now = time.time()
    min_iv = max(30.0, _env_float("MEGA_RECOVERY_ATTEMPT_SEC", 90.0))
    if not force and (now - float(_mega_last_recovery_attempt_ts or 0)) < min_iv:
        return {"ok": False, "skipped": "cooldown"}
    _mega_last_recovery_attempt_ts = now

    try:
        from elite_trader.connection_alerts import ip_ban_active

        if ip_ban_active():
            mark_mega_api_outage(reason="ip_ban")
            return {"ok": False, "reason": "ip_ban"}
    except Exception:
        pass
    try:
        from elite_trader.network_guard import skip_rest

        if skip_rest():
            mark_mega_api_outage(reason="rest_paused")
            return {"ok": False, "reason": "rest_paused"}
    except Exception:
        pass

    mc = get_mega_client()
    if mc and not mc.paper:
        if _mega_outage_since is not None:
            _mega_outage_since = None
            _mega_recovery_pending_fresh_start = False
        return {"ok": True, "already_live": True}

    if mc and mc.paper:
        mark_mega_api_outage(reason=mc._auth_error or "paper_fallback")
        ok, err = mc.try_restore_live(max_attempts=1)
        if ok:
            print("  ✓ MEGA canlı mod geri yüklendi (re-auth)")
        else:
            invalidate_mega_client()
            mc = get_mega_client()
            if not mc or mc.paper:
                return {
                    "ok": False,
                    "reason": "still_paper",
                    "auth": (err or getattr(mc, "_auth_error", None) if mc else err),
                }
            print("  ✓ MEGA canlı mod geri yüklendi (yeni client)")

    fresh: dict[str, Any] | None = None
    if _mega_recovery_pending_fresh_start and _env_bool("MEGA_FRESH_START_ON_RECOVERY", True):
        fresh = fresh_start_mega_9007_after_recovery(reason="api_recovery_fresh_start")
        _mega_recovery_pending_fresh_start = False

    _mega_outage_since = None
    try:
        from elite_trader.mega_async_hub import start_mega_async_hub, stop_mega_async_hub

        stop_mega_async_hub()
        start_mega_async_hub()
    except Exception:
        pass
    _wake_mega_rest(force_sync=True)
    try:
        from elite_trader.mega_control import audit_log

        audit_log("api_recovery_ok", fresh_start=bool(fresh))
    except Exception:
        pass
    return {"ok": True, "recovered": True, "fresh_start": fresh}


def _mega_recovery_worker_loop() -> None:
    while not _mega_recovery_stop.is_set():
        try:
            if mega_api_outage_active():
                try_recover_mega_client(force=False)
        except Exception as exc:
            print(f"  ⚠ MEGA recovery: {exc}")
        wait = max(30.0, _env_float("MEGA_RECOVERY_ATTEMPT_SEC", 90.0))
        _mega_recovery_stop.wait(timeout=wait)


def start_mega_recovery_worker() -> None:
    global _mega_recovery_thread
    if not mega_live_enabled() or mega_instance_id() != "9007":
        return
    if not _env_bool("MEGA_RECOVERY_ENABLED", True):
        return
    _register_mega_outage_hook()
    if _mega_recovery_thread and _mega_recovery_thread.is_alive():
        return
    _mega_recovery_stop.clear()
    _mega_recovery_thread = threading.Thread(
        target=_mega_recovery_worker_loop, name="mega-recovery", daemon=True
    )
    _mega_recovery_thread.start()


def _mega_closed_suppress_ts() -> float:
    """`.mega_closed_suppress_backfill` zaman damgası (0 = yok)."""
    try:
        p = _mega_closed_suppress_path()
        if not p.is_file():
            return 0.0
        raw = p.read_text(encoding="utf-8").strip()
        if not raw:
            return 0.0
        return float(raw.split()[0])
    except Exception:
        return 0.0


def mega_closed_backfill_suppressed() -> bool:
    """Panel temizliği sonrası borsa backfill'i geçici durdur."""
    if not _mega_closed_suppress_path().is_file():
        return False
    try:
        raw = _mega_closed_suppress_path().read_text(encoding="utf-8").strip()
        if not raw:
            return False
        ts = float(raw.split()[0])
        hours = max(1.0, _env_float("MEGA_CLOSED_SUPPRESS_H", 24.0))
        return (time.time() - ts) < hours * 3600.0
    except Exception:
        return False


def suppress_mega_closed_backfill() -> None:
    _mega_closed_suppress_path().parent.mkdir(parents=True, exist_ok=True)
    _mega_closed_suppress_path().write_text(f"{time.time():.3f}\n", encoding="utf-8")


def clear_mega_closed_records(*, suppress_backfill: bool = True) -> int:
    """Kapalı işlem listesini sıfırla (açık pozisyonlara dokunmaz)."""
    global _mega_closed, _mega_closed_loaded
    _ensure_mega_closed_loaded()
    removed = len(_mega_closed)
    _mega_closed = []
    if _mega_closed_path().is_file():
        _mega_closed_path().unlink(missing_ok=True)
    try:
        from elite_trader import parallel_universe_engine as pe

        st = pe._load()
        mega = (st.get("universes") or {}).get("mega")
        if isinstance(mega, dict):
            mega["closed"] = []
            pe._save(st)
    except Exception:
        pass
    if suppress_backfill:
        suppress_mega_closed_backfill()
        touch_closed_panel_epoch(reason="clear_mega_closed_records")
    _mega_closed_loaded = True
    return removed


def _wipe_legacy_root_data_files() -> list[str]:
    removed: list[str] = []
    for name in (
        "mega_live_closed.json",
        "mega_live_open.json",
        "mega_live_open_meta.json",
        "mega_live_session.json",
        ".mega_closed_suppress_backfill",
    ):
        p = _ROOT / "data" / name
        if p.is_file():
            p.unlink(missing_ok=True)
            removed.append(str(p.relative_to(_ROOT)))
    return removed


def _flatten_exchange_positions_raw(mc: Any) -> list[dict[str, Any]]:
    """Borsa pozisyonları — reduceOnly; kapalı tabloya yazılmaz."""
    closed: list[dict[str, Any]] = []
    if not mc or mc.paper:
        return closed
    for ep in mc.exchange_positions() or []:
        coin = str(ep.get("coin") or "").upper()
        side = str(ep.get("side") or "LONG").upper()
        qty = float(ep.get("contracts") or 0)
        if not coin or qty <= 0:
            continue
        close_side = "SHORT" if side == "LONG" else "LONG"
        try:
            order = mc.market_order(coin, close_side, qty, reduce_only=True)
            closed.append(
                {
                    "coin": coin,
                    "side": side,
                    "qty": qty,
                    "order_id": str(order.get("orderId") or ""),
                }
            )
            time.sleep(0.22)
        except Exception as exc:
            closed.append({"coin": coin, "side": side, "qty": qty, "error": str(exc)[:120]})
    return closed


def reset_mega_session_data(
    *,
    reason: str,
    capital: float = 5000.0,
    close_exchange: bool = True,
) -> dict[str, Any]:
    """Panel/script — arşivle, RAM+disk sıfırla, $anchor; borsa flatten (kayıt yok)."""
    global _mega_positions, _mega_positions_cache, _mega_position_id, _mega_closed
    global _mega_closed_loaded, _mega_open_book_loaded, _mega_closed_ui_cache

    suppress_mega_closed_backfill()
    legacy_removed = _wipe_legacy_root_data_files()
    exchange_closed: list[dict[str, Any]] = []
    if close_exchange and mega_live_enabled():
        mc = get_mega_client()
        if mc and not mc.paper:
            exchange_closed = _flatten_exchange_positions_raw(mc)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    iid = mega_instance_id()
    archive = _ROOT / "data" / "deleted_archives" / f"mega_{iid}_{ts}"
    archive.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "ok": True,
        "reason": reason[:200],
        "ts": ts,
        "instance": iid,
        "paths": [],
        "exchange_positions_closed": exchange_closed,
        "legacy_root_removed": legacy_removed,
    }

    mega_dir = mega_instance_data_dir()
    if mega_dir.is_dir() and any(mega_dir.iterdir()):
        dest = archive / mega_dir.name
        shutil.copytree(mega_dir, dest)
        manifest["paths"].append(str(dest.relative_to(_ROOT)))
        for child in sorted(mega_dir.iterdir()):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)

    _mega_positions = []
    _mega_positions_cache = []
    _mega_position_id = 1
    _mega_closed = []
    _mega_closed_loaded = True
    _mega_open_book_loaded = True
    _mega_closed_ui_cache = None
    cleared_closed = clear_mega_closed_records(suppress_backfill=True)
    for path in (_mega_open_book_path(), _mega_open_meta_path()):
        if path.is_file():
            shutil.copy2(path, archive / path.name)
            path.unlink(missing_ok=True)
    suppress_mega_closed_backfill()

    cap = float(capital or 5000.0)
    now_iso = datetime.now(timezone.utc).isoformat()
    _save_session_anchor(cap, reason=reason)
    touch_closed_panel_epoch(reason=reason)
    sess = _mega_session_path()
    sess.parent.mkdir(parents=True, exist_ok=True)
    sess.write_text(
        json.dumps(
            {
                "wallet_anchor": cap,
                "starting_balance": cap,
                "set_at": now_iso,
                "closed_panel_epoch": now_iso,
                "reason": reason[:200],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest["wallet_anchor"] = cap
    manifest["cleared_closed"] = cleared_closed
    manifest["archive"] = str(archive.relative_to(_ROOT))

    aux_cleared: list[str] = []
    for name in (
        "mega_market_regime.json",
        "mega_coin_watch_registry.json",
        "mega_coin_rank_24h.json",
        "mega_system_report_latest.json",
        "mega_control_state.json",
        "control_audit.jsonl",
    ):
        p = mega_dir / name
        if p.is_file():
            shutil.copy2(p, archive / name)
            p.unlink(missing_ok=True)
            aux_cleared.append(name)
    manifest["aux_cleared"] = aux_cleared
    try:
        from elite_trader.mega_boot_observe import reset_boot_clock

        reset_boot_clock()
        manifest["boot_observe_reset"] = True
    except Exception as exc:
        manifest["boot_observe_reset_error"] = str(exc)[:80]
    try:
        from elite_trader.mega_market_regime import reset_instance_state

        reset_instance_state()
        manifest["regime_reset"] = True
    except Exception as exc:
        manifest["regime_reset_error"] = str(exc)[:80]
    try:
        from elite_trader.mode_reject_buffer import clear_mode

        clear_mode("mega")
        manifest["reject_buffer_cleared"] = True
    except Exception as exc:
        manifest["reject_buffer_error"] = str(exc)[:80]

    try:
        from elite_trader import parallel_universe_engine as pe

        pe._state_cache = None
        pe.reset_mode_book("mega")
        pe.set_mode_session_start("mega", cap)
    except Exception as exc:
        manifest["parallel_error"] = str(exc)[:120]

    (mega_dir / ".mega_closed_suppress_backfill").write_text(
        f"{datetime.now(timezone.utc).timestamp():.3f}\n",
        encoding="utf-8",
    )
    (archive / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        from elite_trader.data_archive import _load_manifest, _save_manifest

        data = _load_manifest()
        archives = list(data.get("archives") or [])
        archives.append(
            {
                "archive_id": archive.name,
                "port": int(iid) if iid.isdigit() else iid,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason[:200],
                "trigger": "reset_mega_session_data",
                "path": str(archive.relative_to(_ROOT)),
                "cleared_closed": cleared_closed,
                "wallet_anchor": cap,
            }
        )
        data["archives"] = archives
        _save_manifest(data)
    except Exception:
        pass

    print(
        f"  🧹 MEGA oturum sıfırlandı anchor=${cap:.0f} "
        f"borsa_kapat={len(exchange_closed)} arşiv={archive.name}"
    )
    return manifest


def _normalize_closed_row(row: dict[str, Any]) -> dict[str, Any]:
    """settlement_detail içindeki close order id → üst alan (panel filtresi)."""
    sd = row.get("settlement_detail")
    oid = str(row.get("exchange_close_order_id") or "").strip()
    if not oid and isinstance(sd, dict):
        oid = str(sd.get("exchange_close_order_id") or "").strip()
    if oid:
        row["exchange_close_order_id"] = oid
    return row


def _closed_exchange_order_id(row: dict[str, Any]) -> str:
    return str(_normalize_closed_row(dict(row)).get("exchange_close_order_id") or "").strip()


def _load_mega_closed_from_disk() -> None:
    global _mega_closed, _mega_position_id
    if not _mega_closed_path().is_file():
        return
    try:
        data = json.loads(_mega_closed_path().read_text(encoding="utf-8"))
        rows = [_normalize_closed_row(dict(r)) for r in (data.get("closed") or [])]
        if rows:
            _mega_closed = rows[-_MEGA_CLOSED_RAM_MAX:]
        nxt = int(data.get("next_position_id") or 0)
        if nxt > _mega_position_id:
            _mega_position_id = nxt
        removed = _dedupe_mega_closed(persist=True)
        if removed:
            print(f"  🧹 MEGA kapalı kayıt dedupe: {removed} çift silindi")
    except Exception:
        pass


def _save_mega_closed_to_disk() -> None:
    path = _mega_closed_path()
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "next_position_id": _mega_position_id,
        "closed": _mega_closed[-_MEGA_CLOSED_DISK_MAX:],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        print(f"  ⚠ MEGA kapalı kayıt yazılamadı ({path.name}): {exc}")
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc2:
            print(f"  ⛔ MEGA kapalı kayıt yedek yazım da başarısız: {exc2}")
            raise


def _append_mega_closed_record(closed: dict[str, Any]) -> None:
    global _mega_closed, _mega_closed_ui_cache
    _ensure_mega_closed_loaded()
    closed = _normalize_closed_row(dict(closed))
    if not _closed_row_after_panel_epoch(closed):
        print(
            f"  ↷ MEGA kapalı kayıt atlandı {closed.get('symbol')} "
            f"— oturum kesiminden önce"
        )
        return
    if (
        mega_live_enabled()
        and closed.get("on_exchange")
        and not closed.get("sim")
        and _env_bool("MEGA_CLOSED_REQUIRE_API_FILLS", True)
    ):
        from elite_trader.exchange_settlement import settlement_has_api_close_fills

        fill_src = closed.get("settlement_detail") or closed
        has_fills = bool(int(closed.get("trade_count_close") or 0) > 0) or (
            isinstance(fill_src, dict) and settlement_has_api_close_fills(fill_src)
        )
        if not has_fills:
            print(
                f"  ⛔ MEGA kapalı kayıt reddedildi {closed.get('symbol')} "
                f"— Binance userTrades doğrulaması yok"
            )
            return
    settled = closed.get("settlement_detail")
    if isinstance(settled, dict):
        stub = settled
    else:
        stub = {
            k: closed.get(k)
            for k in (
                "wallet_pnl",
                "net_pnl",
                "final_pnl",
                "pnl_usd",
                "pnl_gross_usd",
            )
        }
    if _phantom_guard_active(closed.get("symbol"), closed.get("side")):
        print(
            f"  ↷ MEGA kapalı kayıt atlandı {closed.get('symbol')} "
            f"— phantom guard (tekrar)"
        )
        return
    if not closed.get("phantom_slippage"):
        closed = _apply_phantom_slippage_meta(
            closed,
            closed,
            exit_reason=str(closed.get("exit_reason") or ""),
            record_reason=str(closed.get("exit_reason") or ""),
            exchange_settled=stub if stub else None,
        )
    if not _mega_closed_persist_allowed(closed):
        print(
            f"  ↷ MEGA sync kayıt atlandı (bot-only) "
            f"{closed.get('symbol')} {closed.get('side')}"
        )
        return
    if _is_sync_backfill_close(closed):
        from elite_trader.fee_economics import is_stop_loss_exit

        er = str(closed.get("exit_reason") or "")
        if is_stop_loss_exit(er) or closed.get("sl_close"):
            closed["close_initiator"] = "exchange_sl"
            closed["exchange_settled"] = bool(
                closed.get("exchange_settled") or closed.get("exchange_close_order_id")
            )
            closed.setdefault("fee_source", "binance_api")
            closed.setdefault("pnl_source", "binance_api")
    key = _closed_dedupe_key(closed)
    if key:
        for i, existing in enumerate(_mega_closed):
            if _closed_dedupe_key(existing) == key or _closed_same_trade(existing, closed):
                merged = _merge_closed_records(existing, closed)
                _mega_closed[i] = merged
                _save_mega_closed_to_disk()
                try:
                    from elite_trader import parallel_universe_engine as pe

                    pe.record_live_close("mega", merged)
                except Exception:
                    pass
                return
    if isinstance(closed.get("settlement_detail"), dict):
        sd = closed["settlement_detail"]
        closed.setdefault(
            "trade_count_close", int(sd.get("trade_count_close") or 0)
        )
        closed.setdefault("fee_source", sd.get("fee_source") or closed.get("fee_source"))
        closed.setdefault("pnl_source", sd.get("pnl_source") or closed.get("pnl_source"))
    _mega_closed.append(closed)
    if len(_mega_closed) > _MEGA_CLOSED_RAM_MAX:
        del _mega_closed[: len(_mega_closed) - _MEGA_CLOSED_RAM_MAX]
    _save_mega_closed_to_disk()
    _mega_closed_ui_cache = None
    try:
        from elite_trader import parallel_universe_engine as pe

        pe.record_live_close("mega", closed)
    except Exception:
        pass
    try:
        from elite_trader.mega_close_sync import wake_mega_close_sync

        wake_mega_close_sync(force=True)
    except Exception:
        pass
    try:
        from elite_trader.telegram_notify import notify_position_closed

        notify_position_closed(
            closed,
            exit_reason=str(closed.get("exit_reason") or ""),
            settlement=closed.get("settlement_detail")
            if isinstance(closed.get("settlement_detail"), dict)
            else None,
        )
    except Exception:
        pass


def _closed_exit_ts(row: dict[str, Any]) -> float | None:
    raw = row.get("exit_time")
    if raw is not None:
        try:
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            if ts > 0:
                return ts
        except (TypeError, ValueError):
            pass
    for key in ("exit_time_iso", "exit_time_str"):
        raw = row.get(key)
        if not raw:
            continue
        try:
            s = str(raw).strip().replace("Z", "+00:00")
            if "T" in s:
                dt = datetime.fromisoformat(s)
            else:
                dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            return dt.timestamp()
        except Exception:
            continue
    return None


def _sync_mega_closed_from_disk_if_stale() -> None:
    """Disk > bellek (restart/reconcile dışı yazım) — panel eksik satır fix."""
    global _mega_closed, _mega_closed_ui_cache
    path = _mega_closed_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        disk_rows = [_normalize_closed_row(dict(r)) for r in (data.get("closed") or [])]
    except Exception:
        return
    if not disk_rows:
        return
    disk_keys = {_closed_dedupe_key(r) for r in disk_rows}
    ram_keys = {_closed_dedupe_key(r) for r in _mega_closed}
    if not (disk_keys - ram_keys) and len(disk_rows) <= len(_mega_closed):
        return
    _mega_closed = disk_rows[-_MEGA_CLOSED_RAM_MAX:]
    _dedupe_mega_closed(persist=False)
    _mega_closed_ui_cache = None


def _closed_dedupe_key(row: dict[str, Any]) -> str:
    """Tek kapanış = tek satır; borsa close order id birincil anahtar."""
    oid = _closed_exchange_order_id(row)
    if oid:
        return f"oid:{oid}"
    pid = int(row.get("id") or 0)
    if pid > 0:
        return f"pos:{pid}"
    sym = str(row.get("symbol") or "")
    side = str(row.get("side") or "").upper()
    net = round(float(row.get("final_pnl") or row.get("net_pnl") or 0), 2)
    entry = round(float(row.get("entry_price") or 0), 4)
    exit_px = round(float(row.get("exit_price") or 0), 4)
    exit_ts = _closed_exit_ts(row)
    exit_bucket = int(exit_ts // 60) if exit_ts else 0
    return f"trade:{sym}|{side}|{entry}|{exit_px}|{net}|{exit_bucket}"


_closed_panel_meta: dict[str, Any] = {}


def mega_closed_panel_meta() -> dict[str, Any]:
    return dict(_closed_panel_meta)


def _mega_panel_closed_max_rows() -> int:
    try:
        n = int(_env_float("MEGA_PANEL_CLOSED_MAX", 0))
    except (TypeError, ValueError):
        n = 0
    return 99999 if n <= 0 else max(50, n)


def _load_archived_closed_rows() -> list[dict[str, Any]]:
    """Silinen oturumlar — panel kapalı tablo (salt okunur)."""
    if not _env_bool("MEGA_PANEL_CLOSED_INCLUDE_ARCHIVES", True):
        return []
    iid = mega_instance_id()
    archive_dir = mega_instance_data_dir().parent / "deleted_archives"
    if not archive_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(archive_dir.glob(f"mega_{iid}_*"), reverse=True):
        for rel in (
            d / "mega_live_closed.json",
            d / f"mega_{iid}" / "mega_live_closed.json",
            d / "mega_live_closed_history.json",
        ):
            if not rel.is_file():
                continue
            try:
                raw = json.loads(rel.read_text(encoding="utf-8"))
            except Exception:
                continue
            rows = raw if isinstance(raw, list) else list(raw.get("closed") or [])
            for row in rows:
                if not isinstance(row, dict) or not row.get("symbol"):
                    continue
                r = dict(row)
                r["_archive"] = True
                r["archive_source"] = d.name
                out.append(r)
    return out


def _merge_panel_closed_rows(
    primary: list[dict[str, Any]],
    archived: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in primary + archived:
        key = _closed_dedupe_key(row)
        prev = merged.get(key)
        if prev is None:
            merged[key] = dict(row)
            continue
        score = lambda r: (  # noqa: E731
            (100 if not r.get("backfilled") else 0)
            + (50 if float(r.get("duration_sec") or r.get("duration") or 0) > 1 else 0)
            + (20 if r.get("exchange_close_order_id") else 0)
            + (10 if not r.get("_archive") else 0)
        )
        if score(row) >= score(prev):
            merged[key] = dict(row)
    return list(merged.values())


def _mega_panel_closed_verified_only() -> bool:
    """Kapalı tablo — yalnızca userTrades+income doğrulanmış borsa kapanışları."""
    return _env_bool("MEGA_PANEL_CLOSED_VERIFIED_ONLY", True)


def _filter_closed_rows_for_panel(
    rows: list[dict[str, Any]],
    *,
    live_desk: bool,
    mc: Any,
    light: bool,
) -> list[dict[str, Any]]:
    archived = [dict(r) for r in rows if r.get("_archive")]
    active = [dict(r) for r in rows if not r.get("_archive")]
    if not active:
        return archived
    if not live_desk:
        filtered = [
            r
            for r in active
            if not (
                r.get("sim")
                and not r.get("on_exchange")
                and not r.get("exchange_settled")
            )
        ]
        return filtered + archived
    skip_index = bool(light)
    if not skip_index:
        try:
            from elite_trader.network_guard import is_degraded, skip_rest

            skip_index = skip_rest() or is_degraded()
        except Exception:
            pass
    if skip_index:
        filtered = [
            r
            for r in active
            if not (
                r.get("sim")
                and not r.get("on_exchange")
                and not r.get("exchange_settled")
            )
        ]
        return filtered + archived
    try:
        from elite_trader.exchange_trade_truth import (
            build_exchange_close_index,
            closed_has_exchange_fill,
        )

        coins: set[str] = set()
        for r in active:
            sym = str(r.get("symbol") or "").replace("USDT", "").upper()
            if sym:
                coins.add(sym.replace("USDT", ""))
        close_index = build_exchange_close_index(mc, coins=sorted(coins)) if mc else {}
        if close_index:
            filtered = [
                r
                for r in active
                if (r.get("income_settled") and r.get("exchange_settled"))
                or (
                    r.get("exchange_settled")
                    and str(r.get("fee_source") or "") == "binance_api"
                    and (
                        _closed_exchange_order_id(r)
                        or r.get("sync_source")
                        or int(r.get("trade_count_close") or 0) > 0
                    )
                )
                or closed_has_exchange_fill(r, mc, close_index=close_index)
            ]
        else:
            filtered = [
                r
                for r in active
                if r.get("exchange_settled") or r.get("income_settled")
            ]
    except Exception:
        filtered = [
            r
            for r in active
            if r.get("exchange_settled") or r.get("income_settled")
        ]
    filtered = [
        r
        for r in filtered
        if not (
            r.get("sim") and not r.get("on_exchange") and not r.get("exchange_settled")
        )
    ]
    if _mega_panel_closed_verified_only():
        try:
            from elite_trader.exchange_trade_truth import is_verified_exchange_trade

            def _panel_closed_visible(r: dict[str, Any]) -> bool:
                if is_verified_exchange_trade(r):
                    return True
                if r.get("exchange_settled") and int(r.get("trade_count_close") or 0) > 0:
                    return str(r.get("fee_source") or "") == "binance_api"
                return False

            filtered = [r for r in filtered if _panel_closed_visible(r)]
            archived = [r for r in archived if _panel_closed_visible(r)]
        except Exception:
            pass
    return filtered + archived


def _closed_same_trade(
    a: dict[str, Any], b: dict[str, Any], *, max_exit_delta_sec: float = 180.0
) -> bool:
    """Bot kaydı + borsa sync aynı kapanış mı (farklı id / oid olsa bile)."""
    if str(a.get("symbol") or "") != str(b.get("symbol") or ""):
        return False
    if str(a.get("side") or "").upper() != str(b.get("side") or "").upper():
        return False
    oid_a = str(a.get("exchange_close_order_id") or "").strip()
    oid_b = str(b.get("exchange_close_order_id") or "").strip()
    if oid_a and oid_b and oid_a != oid_b:
        return False
    pid_a = int(a.get("id") or 0)
    pid_b = int(b.get("id") or 0)
    if pid_a > 0 and pid_a == pid_b:
        return True
    ta = _closed_exit_ts(a)
    tb = _closed_exit_ts(b)
    if ta is not None and tb is not None and abs(ta - tb) > max_exit_delta_sec:
        return False
    net_a = round(float(a.get("final_pnl") or a.get("net_pnl") or 0), 2)
    net_b = round(float(b.get("final_pnl") or b.get("net_pnl") or 0), 2)
    if abs(net_a - net_b) > 0.25:
        return False
    entry_a = float(a.get("entry_price") or 0)
    entry_b = float(b.get("entry_price") or 0)
    exit_a = float(a.get("exit_price") or 0)
    exit_b = float(b.get("exit_price") or 0)
    if entry_a > 0 and entry_b > 0:
        if abs(entry_a - entry_b) / max(entry_a, entry_b) > 0.004:
            return False
    if exit_a > 0 and exit_b > 0:
        if abs(exit_a - exit_b) / max(exit_a, exit_b) > 0.004:
            return False
    return True


def _closed_record_score(row: dict[str, Any]) -> int:
    score = 0
    if str(row.get("close_initiator") or "") == "bot":
        score += 500
    if row.get("backfilled"):
        score -= 200
    if not row.get("backfilled") and row.get("sync_source") != "exchange_userTrades":
        score += 100
    if float(row.get("duration_sec") or row.get("duration") or 0) > 1.0:
        score += 50
    if row.get("opened_at_iso") or row.get("entry_time"):
        score += 20
    if row.get("execution_mode_at_open"):
        score += 10
    if row.get("max_unreal_seen") is not None:
        score += 10
    if row.get("tp_net_target_usd") is not None:
        score += 5
    return score


def _merge_closed_records(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    primary, secondary = (
        (a, b) if _closed_record_score(a) >= _closed_record_score(b) else (b, a)
    )
    out = dict(primary)
    for k in (
        "pnl_usd",
        "pnl_gross_usd",
        "net_pnl",
        "wallet_pnl",
        "final_pnl",
        "exchange_realized_pnl",
        "entry_fee",
        "exit_fee",
        "total_fees",
        "exit_price",
        "entry_price",
        "size",
        "fee_source",
        "pnl_source",
        "data_source",
    ):
        sec_v = secondary.get(k)
        if sec_v is None:
            continue
        if out.get(k) is None or (out.get("backfilled") and not secondary.get("backfilled")):
            out[k] = sec_v
    oid = str(
        out.get("exchange_close_order_id") or secondary.get("exchange_close_order_id") or ""
    ).strip()
    if oid:
        out["exchange_close_order_id"] = oid
    out["exchange_settled"] = bool(
        out.get("exchange_settled") or secondary.get("exchange_settled")
    )
    if str(out.get("close_initiator") or "") == "bot":
        out.pop("backfilled", None)
        if out.get("sync_source") in ("exchange_userTrades", "exchange_income"):
            out.pop("sync_source", None)
    stake = float(out.get("stake_usd") or 1)
    net = float(out.get("net_pnl") or out.get("wallet_pnl") or out.get("final_pnl") or 0)
    out["net_pnl_pct"] = round(net / stake * 100, 4) if stake else 0.0
    pnl_g = float(out.get("pnl_usd") or out.get("pnl_gross_usd") or 0)
    out["pnl_pct"] = round(pnl_g / stake * 100, 4) if stake else 0.0
    return out


def _purge_open_position_phantom_closes(*, persist: bool = True) -> int:
    """Açık pozisyon varken eklenmiş sync/backfill kapalı satırlarını sil."""
    global _mega_closed
    if not mega_live_bot_only_closed():
        return 0
    keep: list[dict[str, Any]] = []
    removed = 0
    for row in _mega_closed:
        if _is_sync_backfill_close(row) and _position_still_open(
            str(row.get("symbol") or ""), str(row.get("side") or "")
        ):
            removed += 1
            print(
                f"  🗑 MEGA erken sync silindi {row.get('symbol')} "
                f"{row.get('side')} net=${float(row.get('net_pnl') or 0):.4f}"
            )
            continue
        keep.append(row)
    if removed:
        _mega_closed = keep
        if persist:
            _save_mega_closed_to_disk()
    return removed


def _dedupe_mega_closed(*, persist: bool = False) -> int:
    """Aynı kapanış — tek satır; bot + borsa sync çiftlerini birleştir."""
    global _mega_closed
    if not _mega_closed:
        return 0
    before = len(_mega_closed)
    kept: list[dict[str, Any]] = []
    used = [False] * len(_mega_closed)
    for i, row in enumerate(_mega_closed):
        if used[i]:
            continue
        merged = dict(row)
        used[i] = True
        for j in range(i + 1, len(_mega_closed)):
            if used[j]:
                continue
            other = _mega_closed[j]
            if _closed_dedupe_key(merged) == _closed_dedupe_key(other) or _closed_same_trade(
                merged, other
            ):
                merged = _merge_closed_records(merged, other)
                used[j] = True
        kept.append(merged)
    _mega_closed = kept
    removed = before - len(_mega_closed)
    if removed and persist:
        _save_mega_closed_to_disk()
    return removed


def _sync_missing_closes_from_exchange(*, force: bool = False) -> int:
    from elite_trader.mega_close_sync import sync_missing_closes_from_exchange

    return sync_missing_closes_from_exchange(force=force)


def _backfill_mega_closed_if_empty() -> None:
    """Disk/kitap boşsa — son oturum Binance kapanış fill'lerini geri yükle."""
    global _mega_closed
    if mega_closed_backfill_suppressed():
        return
    if mega_instance_id() == "9007" and mega_sim_enabled() and not mega_live_orders_enabled():
        return
    live_only = mega_live_orders_enabled() and not mega_sim_enabled()
    if _mega_closed:
        try:
            from elite_trader.mega_close_sync import mega_close_sync_enabled

            if mega_close_sync_enabled() and not mega_live_bot_only_closed():
                _sync_missing_closes_from_exchange(force=True)
        except Exception:
            if not mega_live_bot_only_closed():
                _sync_missing_closes_from_exchange(force=True)
        _purge_open_position_phantom_closes()
        return
    if not live_only:
        try:
            from elite_trader import parallel_universe_engine as pe

            book = pe.get_universe_book("mega")
            for row in book.get("closed") or []:
                r = dict(row)
                key = _closed_dedupe_key(r)
                if key and key not in {_closed_dedupe_key(x) for x in _mega_closed}:
                    _mega_closed.append(r)
        except Exception:
            pass
    try:
        from elite_trader.mega_close_sync import mega_close_sync_enabled

        if mega_close_sync_enabled() and not mega_live_bot_only_closed():
            _sync_missing_closes_from_exchange(force=True)
    except Exception:
        if not mega_live_bot_only_closed():
            _sync_missing_closes_from_exchange(force=True)


def _ensure_mega_closed_loaded() -> None:
    global _mega_closed_loaded, _mega_open_book_loaded
    if _mega_closed_loaded:
        return
    _mega_closed_loaded = True
    _mega_open_book_loaded = True
    _maybe_migrate_instance_data_files()
    _load_mega_closed_from_disk()
    _load_open_book_from_disk()
    if mega_instance_id() == "9007" and mega_sim_enabled() and not mega_live_orders_enabled():
        return
    if _mega_client is None:
        get_mega_client()
    _backfill_mega_closed_if_empty()
    _purge_open_position_phantom_closes()
    _dedupe_mega_closed(persist=True)


def _build_mega_closed_record(
    pos: dict[str, Any],
    record_reason: str,
    *,
    exchange_settled: dict[str, Any] | None,
    close_order_id: str | None,
    close_exec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    exit_ts = time.time()
    entry_ts = float(pos.get("entry_time") or exit_ts)
    duration = max(0.0, exit_ts - entry_ts)
    stake = float(pos.get("stake_usd") or 1)
    close_exec = dict(close_exec or pos.get("close_signal") or {})

    if exchange_settled:
        from elite_trader.exchange_trade_truth import settlement_to_closed_fields

        api = settlement_to_closed_fields(exchange_settled)
        pnl_gross = float(
            exchange_settled.get("pnl_usd")
            or exchange_settled.get("pnl_gross_usd")
            or 0
        )
        wallet_pnl = float(
            exchange_settled.get("wallet_pnl") or api.get("wallet_pnl") or 0
        )
        net_pnl = float(api.get("net_pnl") or wallet_pnl)
        exit_px = float(api.get("exit_price") or pos.get("current_price") or 0)
        entry_px = float(api.get("entry_price") or pos.get("entry_price") or 0)
        size_out = float(api.get("size") or pos.get("size") or 0)
        exit_fee = float(api.get("exit_fee") or 0)
        total_fees = float(api.get("total_fees") or 0)
        net_pnl_pct = float(
            api.get("net_pnl_pct") or (net_pnl / stake * 100 if stake else 0)
        )
    else:
        pnl_gross = float(pos.get("unrealized_pnl") or 0)
        wallet_pnl = pnl_gross
        net_pnl = pnl_gross
        exit_px = float(pos.get("current_price") or 0)
        entry_px = float(pos.get("entry_price") or 0)
        size_out = float(pos.get("size") or 0)
        exit_fee = 0.0
        total_fees = float(pos.get("entry_fee") or 0)
        net_pnl_pct = (net_pnl / stake * 100) if stake else 0.0
        api = {}

    row = {
        "id": pos["id"],
        "symbol": pos["symbol"],
        "side": pos["side"],
        "entry_price": entry_px,
        "exit_price": exit_px,
        "size": size_out,
        "leverage": pos.get("leverage"),
        "stake_usd": stake,
        "pnl_usd": pnl_gross,
        "pnl_gross_usd": pnl_gross,
        "pnl_pct": (pnl_gross / stake * 100) if stake else 0,
        "entry_fee": exchange_settled.get("entry_fee")
        if exchange_settled
        else pos.get("entry_fee"),
        "exit_fee": exit_fee,
        "total_fees": total_fees,
        "net_pnl": net_pnl,
        "net_pnl_pct": net_pnl_pct,
        "tax": 0.0,
        "final_pnl": wallet_pnl,
        "wallet_pnl": wallet_pnl,
        "exit_reason": record_reason,
        "entry_time": pos.get("entry_time_str"),
        "entry_time_str": pos.get("entry_time_str"),
        "opened_at_iso": pos.get("opened_at_iso"),
        "exit_time": exit_ts,
        "exit_time_str": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "exit_time_iso": datetime.now(timezone.utc).isoformat(),
        "duration_sec": duration,
        "duration": duration,
        "hold_sec": duration,
        "tp_target_usd": pos.get("tp_target_usd"),
        "tp_net_target_usd": pos.get("tp_net_target_usd"),
        "sl_target_usd": pos.get("sl_target_usd"),
        "max_unreal_seen": pos.get("max_unreal_seen"),
        "min_unreal_seen": pos.get("min_unreal_seen"),
        "on_exchange": bool(pos.get("on_exchange")),
        "exchange_order_id": str(pos.get("order_id") or pos.get("exchange_order_id") or ""),
        "exchange_close_order_id": str(
            close_order_id or pos.get("exchange_close_order_id") or ""
        ),
        "exchange_settled": bool(exchange_settled),
        "exchange_realized_pnl": (
            exchange_settled.get("exchange_realized_pnl") if exchange_settled else None
        ),
        "fee_source": api.get("fee_source")
        or ("binance_api" if exchange_settled else None),
        "pnl_source": api.get("pnl_source")
        or ("binance_api" if exchange_settled else "local"),
        "data_source": api.get("data_source")
        or ("binance_api" if exchange_settled else "local"),
        "panel_mode": "mega",
        "execution_mode_at_close": "mega",
        "execution_mode_at_open": pos.get("execution_mode_at_open") or "mega",
        "signal_source": pos.get("signal_source") or "MEGA-LIVE",
        "signal_strength": pos.get("signal_strength"),
        "close_execution": close_exec or None,
        "signal_fill_px": close_exec.get("signal_fill_px"),
        "signal_est_net": close_exec.get("signal_est_net"),
        "signal_mark_unreal": close_exec.get("signal_mark_unreal"),
        "close_initiator": "bot" if exchange_settled else "local",
        "pre_send_gross": pos.get("pre_send_gross"),
        "pre_send_net": pos.get("pre_send_net"),
        "settlement_detail": (
            {
                k: exchange_settled.get(k)
                for k in (
                    "entry_price",
                    "exit_price",
                    "size",
                    "pnl_usd",
                    "pnl_gross_usd",
                    "entry_fee",
                    "exit_fee",
                    "total_fees",
                    "funding_fee",
                    "wallet_pnl",
                    "net_pnl",
                    "exchange_close_order_id",
                    "exchange_realized_pnl",
                    "exchange_commission",
                    "trade_count_close",
                    "fee_source",
                    "pnl_source",
                    "income_settled",
                )
                if exchange_settled.get(k) is not None
            }
            if exchange_settled
            else None
        ),
    }
    try:
        from elite_trader.mega_system_context import attach_exit_context

        attach_exit_context(
            row,
            pos=pos,
            exit_reason=record_reason,
            settlement=exchange_settled,
        )
    except Exception:
        pass
    return row


def _ensure_panel_closed_rows(*, force: bool = False) -> int:
    """Kapalı tablo boşsa veya seyrek — Binance userTrades ile doldur (panel)."""
    if not mega_live_enabled():
        return 0
    mc = get_mega_client()
    if not mc or mc.paper:
        return 0
    _ensure_mega_closed_loaded()
    now = time.time()
    last = float(getattr(_ensure_panel_closed_rows, "_last_ts", 0))
    min_iv = max(8.0, _env_float("MEGA_PANEL_CLOSED_SYNC_SEC", 15.0))
    if not force and len(_mega_closed) > 0 and (now - last) < min_iv:
        return 0
    if not force and len(_mega_closed) == 0 and (now - last) < 4.0:
        return 0
    _ensure_panel_closed_rows._last_ts = now  # type: ignore[attr-defined]
    added = 0
    try:
        from elite_trader.mega_close_sync import sync_missing_closes_from_exchange

        added = int(
            sync_missing_closes_from_exchange(
                force=force or len(_mega_closed) == 0
            )
            or 0
        )
    except Exception:
        pass
    if len(_mega_closed) == 0 or force:
        try:
            reconcile_mega_closed_with_exchange(force=force and len(_mega_closed) == 0)
        except Exception:
            pass
    global _mega_closed_ui_cache
    _mega_closed_ui_cache = None
    return added


def _build_mega_closed_for_ui(*, light: bool = False) -> list[dict[str, Any]]:
    global _mega_closed_ui_cache, _closed_panel_meta
    _ensure_mega_closed_loaded()
    _sync_mega_closed_from_disk_if_stale()
    if light:
        now = time.time()
        ttl = max(0.8, _env_float("MEGA_SNAPSHOT_CLOSED_CACHE_SEC", 2.0))
        rev = len(_mega_closed)
        if _mega_closed_ui_cache:
            c_ts, c_rev, c_rows = _mega_closed_ui_cache
            if (now - c_ts) < ttl and c_rev == rev:
                return [dict(r) for r in c_rows]
    _dedupe_mega_closed(persist=False)
    session_rows = [dict(r) for r in _mega_closed]
    archived = _load_archived_closed_rows()
    rows = _merge_panel_closed_rows(session_rows, archived)
    mc = get_mega_client()
    live_desk = mega_live_enabled() and mc and not getattr(mc, "paper", True)
    rows = _filter_closed_rows_for_panel(rows, live_desk=live_desk, mc=mc, light=light)
    show_phantom = _env_bool("MEGA_PANEL_CLOSED_SHOW_PHANTOM", True)
    if _env_bool("MEGA_PHANTOM_PANEL_HIDE", True) and not show_phantom:
        rows = [r for r in rows if not r.get("panel_hide")]
    if _env_bool("MEGA_PANEL_CLOSED_SESSION_ONLY", True):
        rows = [r for r in rows if _closed_row_after_panel_epoch(r)]
    rows = sorted(rows, key=lambda r: _closed_exit_ts(r) or 0.0, reverse=True)
    total_merged = len(rows)
    max_n = _mega_panel_closed_max_rows()
    rows = rows[:max_n]
    _closed_panel_meta = {
        "includes_archives": _env_bool("MEGA_PANEL_CLOSED_INCLUDE_ARCHIVES", True),
        "session_rows": len(session_rows),
        "archive_rows_loaded": len(archived),
        "total_merged": total_merged,
        "shown": len(rows),
        "max_rows": max_n,
        "truncated": total_merged > len(rows),
    }
    if light:
        _mega_closed_ui_cache = (time.time(), len(_mega_closed), [dict(r) for r in rows])
    return rows


def reconcile_mega_closed_with_exchange(*, force: bool = False) -> dict[str, Any]:
    """Kapalı tablo = Binance userTrades (hayalet kayıt sil, eksik ekle)."""
    global _mega_closed
    import json
    from datetime import datetime, timezone

    _ensure_mega_closed_loaded()
    mc = get_mega_client()
    if not mc or mc.paper or not mega_live_enabled():
        return {"ok": False, "reason": "paper_or_off"}
    now = time.time()
    min_iv = max(15.0, _env_float("MEGA_CLOSED_RECONCILE_SEC", 45.0))
    if not force and (now - float(getattr(reconcile_mega_closed_with_exchange, "_last_ts", 0))) < min_iv:
        return {"ok": True, "skipped": "rate_limit"}
    try:
        from elite_trader.network_guard import binance_rest_enabled

        if not binance_rest_enabled() and not force:
            return {"ok": True, "skipped": "rest_paused"}
    except Exception:
        pass
    reconcile_mega_closed_with_exchange._last_ts = now  # type: ignore[attr-defined]

    from elite_trader.exchange_trade_truth import (
        build_exchange_close_index,
        invalidate_exchange_close_index,
        prune_phantom_mega_closed,
        reconcile_mega_closed_rows_from_index,
    )
    from elite_trader.mega_close_sync import sync_missing_closes_from_exchange

    coins: set[str] = set()
    for p in _mega_positions:
        sym = str(p.get("symbol") or "").replace("USDT", "").upper()
        if sym:
            coins.add(sym)
    for ep in _mega_positions_cache or []:
        c = str(ep.get("coin") or "").upper()
        if c:
            coins.add(c)
    for row in _mega_closed:
        sym = str(row.get("symbol") or "").replace("USDT", "").upper()
        if sym:
            coins.add(sym)
    lookback_h = max(24.0, _env_float("MEGA_CLOSE_RECONCILE_LOOKBACK_H", 168.0))
    since_ms = int((time.time() - lookback_h * 3600) * 1000)
    epoch_ms = int(_closed_panel_epoch_sec() * 1000)
    if epoch_ms > 0:
        since_ms = max(since_ms, epoch_ms)
    trade_limit = 1000 if force else 120
    close_index = build_exchange_close_index(
        mc,
        since_ms=since_ms,
        coins=sorted(coins) if coins else None,
        trade_limit=trade_limit,
        force=True,
    )
    keep, removed = prune_phantom_mega_closed(mc, list(_mega_closed), close_index=close_index)
    if not mega_live_bot_only_closed():
        keep = reconcile_mega_closed_rows_from_index(
            keep, close_index, client=mc, since_ms=since_ms
        )
    _mega_closed = keep
    _dedupe_mega_closed(persist=False)
    added = 0
    try:
        from elite_trader.mega_close_sync import mega_close_sync_enabled

        if mega_close_sync_enabled() and not mega_live_bot_only_closed():
            added = sync_missing_closes_from_exchange(force=force)
    except Exception:
        if not mega_live_bot_only_closed():
            added = sync_missing_closes_from_exchange(force=force)
    _purge_open_position_phantom_closes(persist=False)
    _dedupe_mega_closed(persist=True)
    invalidate_exchange_close_index()

    archive_path = ""
    if removed:
        archive_dir = mega_instance_data_dir().parent / "deleted_archives"
        archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_path = str(archive_dir / f"mega_phantom_closed_{mega_instance_id()}_{stamp}.json")
        Path(archive_path).write_text(
            json.dumps(
                {
                    "instance": mega_instance_id(),
                    "removed_count": len(removed),
                    "removed": removed,
                    "kept_count": len(_mega_closed),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        for r in removed:
            print(
                f"  🗑 MEGA hayalet kapalı silindi {r.get('symbol')} "
                f"{r.get('side')} ({r.get('exit_reason')})"
            )
    return {
        "ok": True,
        "removed": len(removed),
        "kept": len(_mega_closed),
        "added_from_exchange": added,
        "archive": archive_path,
    }


def _read_session_json() -> dict[str, Any]:
    if not _mega_session_path().is_file():
        return {}
    try:
        st = json.loads(_mega_session_path().read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def _load_session_anchor() -> float | None:
    try:
        v = float(_read_session_json().get("wallet_anchor") or 0)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _closed_panel_epoch_sec() -> float:
    """Panel + borsa sync — bu andan önceki kapanışlar eklenmez / gösterilmez.

    Yalnızca ``closed_panel_epoch`` (reset/temizlik) ve backfill suppress kullanılır;
    ``set_at`` (wallet_sync) panel kesimini ilerletmez — aksi halde her cüzdan
    senkronunda eski kapanışlar tablodan kaybolur.
    """
    epoch = 0.0
    st = _read_session_json()
    try:
        from elite_trader.exchange_settlement import _parse_iso_ms

        raw = st.get("closed_panel_epoch")
        if raw:
            ms = _parse_iso_ms(str(raw))
            if ms:
                epoch = ms / 1000.0
    except Exception:
        pass
    if mega_closed_backfill_suppressed():
        epoch = max(epoch, _mega_closed_suppress_ts())
    return epoch


def touch_closed_panel_epoch(*, reason: str = "") -> None:
    """Kapalı tablo sıfırlandı — yalnızca bu andan sonraki kapanışlar."""
    now_iso = datetime.now(timezone.utc).isoformat()
    st = dict(_read_session_json())
    st["closed_panel_epoch"] = now_iso
    if reason:
        st["closed_panel_epoch_reason"] = reason[:200]
    _mega_session_path().parent.mkdir(parents=True, exist_ok=True)
    _mega_session_path().write_text(
        json.dumps(st, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _closed_row_after_panel_epoch(row: dict[str, Any]) -> bool:
    if not _env_bool("MEGA_PANEL_CLOSED_SESSION_ONLY", True):
        return True
    epoch = _closed_panel_epoch_sec()
    if epoch <= 0:
        return True
    ex = _closed_exit_ts(row)
    return ex is None or ex >= epoch - 1.0


def _save_session_anchor(wallet_balance: float, *, reason: str = "") -> None:
    if wallet_balance <= 0:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    st = dict(_read_session_json())
    st["wallet_anchor"] = round(wallet_balance, 4)
    st["starting_balance"] = round(wallet_balance, 4)
    st["reason"] = reason[:200]
    rlow = reason.lower()
    if "wallet_sync" not in rlow:
        st["set_at"] = now_iso
    elif not st.get("set_at"):
        st["set_at"] = now_iso
    if "reset" in rlow or "fresh" in rlow or "sıfır" in rlow:
        st["closed_panel_epoch"] = now_iso
    _mega_session_path().parent.mkdir(parents=True, exist_ok=True)
    _mega_session_path().write_text(
        json.dumps(st, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fetch_wallet(*, force: bool = False) -> dict[str, Any]:
    global _mega_wallet
    mc = get_mega_client()
    if not mc or mc.paper:
        return dict(_mega_wallet)
    wallet_iv = max(2.0, _env_float("MEGA_WALLET_REST_SEC", 4.0))
    if _mega_wallet and not force:
        age = time.time() - float(_mega_wallet.get("_ts") or 0)
        if age < wallet_iv:
            return dict(_mega_wallet)
    try:
        bal = mc.exchange_wallet() or {}
        if bal:
            bal["_ts"] = time.time()
            _mega_wallet = dict(bal)
            try:
                from elite_trader.network_guard import note_success

                note_success()
            except Exception:
                pass
            if _env_bool("MEGA_WALLET_SYNC_ANCHOR", True):
                wb = _wallet_balance(bal)
                if wb > 0:
                    _save_session_anchor(wb, reason="wallet_sync")
    except Exception:
        pass
    return dict(_mega_wallet)


def _wallet_balance(wallet: dict[str, Any]) -> float:
    for k in ("total_wallet_balance", "wallet_balance", "usdt_balance"):
        v = float(wallet.get(k) or 0)
        if v > 0:
            return v
    return 0.0


def _mega_ts_from_ms(ms: int | float) -> float:
    m = float(ms or 0)
    if m <= 0:
        return 0.0
    return m / 1000.0 if m > 1e12 else m


def _mega_entry_fields_from_ts(ts: float) -> tuple[float, str, str]:
    ts = float(ts)
    if ts <= 0:
        ts = time.time()
    dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    return ts, dt_utc.strftime("%Y-%m-%d %H:%M:%S"), dt_utc.isoformat()


def _mega_entry_fields_from_order(order: dict[str, Any] | None) -> tuple[float, str, str] | None:
    if not order:
        return None
    raw = order.get("transactTime") or order.get("updateTime")
    if raw is None:
        return None
    try:
        ts = _mega_ts_from_ms(int(raw))
        if ts > 0:
            return _mega_entry_fields_from_ts(ts)
    except (TypeError, ValueError):
        return None
    return None


def _mega_entry_fields_from_ep(
    ep: dict[str, Any], existing: dict[str, Any] | None
) -> tuple[float, str, str]:
    """Kayıtlı/kilitli açılış korunur — updateTime pozisyon güncellemesidir, açılış değil."""
    if existing:
        cur = float(existing.get("entry_time") or 0)
        if cur > 0 or existing.get("entry_time_locked"):
            ets = str(existing.get("entry_time_str") or "").strip()
            oai = str(existing.get("opened_at_iso") or "").strip()
            if cur > 0:
                if not ets or not oai:
                    return _mega_entry_fields_from_ts(cur)
                return cur, ets, oai
    return _mega_entry_fields_from_ts(time.time())


def _mega_entry_time_suspect(pos: dict[str, Any]) -> bool:
    """Gece yarısı placeholder veya bozuk ISO — borsa sync artefaktı."""
    if pos.get("entry_time_locked"):
        return False
    ets = str(pos.get("entry_time_str") or "").strip()
    if ets.endswith("00:00:00"):
        return True
    oai = str(pos.get("opened_at_iso") or "")
    if "T00:00:00" in oai:
        return True
    try:
        et = float(pos.get("entry_time") or 0)
        if et > 0 and et < 1e6:
            return True
    except (TypeError, ValueError):
        pass
    return False


def _mega_open_time_from_user_trades(
    mc: Any, symbol: str, side: str, *, lookback_sec: float = 14 * 86400
) -> tuple[float, str, str] | None:
    """Mevcut pozisyon döngüsünün açılış fill'i — en son sıfırlanmadan sonraki ilk açılış."""
    if not mc or mc.paper:
        return None
    coin = str(symbol or "").replace("USDT", "").upper()
    sd = str(side or "LONG").upper()
    start_ms = int((time.time() - max(3600.0, lookback_sec)) * 1000)
    try:
        trades = sorted(
            mc.user_trades(coin, limit=1000) or [],
            key=lambda t: int(t.get("time") or 0),
        )
        if not trades:
            trades = sorted(
                mc.user_trades(coin, start_ms=start_ms, limit=1000) or [],
                key=lambda t: int(t.get("time") or 0),
            )
        if start_ms > 0:
            trades = [t for t in trades if int(t.get("time") or 0) >= start_ms] or trades
    except Exception:
        return None
    if not trades:
        return None
    open_side = "BUY" if sd == "LONG" else "SELL"
    close_side = "SELL" if sd == "LONG" else "BUY"
    last_close_ms = max(
        (
            int(t.get("time") or 0)
            for t in trades
            if str(t.get("side") or "").upper() == close_side
        ),
        default=0,
    )
    leg_opens = [
        int(t.get("time") or 0)
        for t in trades
        if str(t.get("side") or "").upper() == open_side
        and int(t.get("time") or 0) > last_close_ms
    ]
    if not leg_opens:
        leg_opens = [
            int(t.get("time") or 0)
            for t in trades
            if str(t.get("side") or "").upper() == open_side
            and abs(float(t.get("realizedPnl") or 0)) < 1e-8
            and int(t.get("time") or 0) > 0
        ]
    if not leg_opens:
        return None
    return _mega_entry_fields_from_ts(_mega_ts_from_ms(min(leg_opens)))


def _mega_apply_open_time_from_order(
    pos: dict[str, Any],
    mc: Any | None,
    order: dict[str, Any] | None = None,
) -> None:
    """Açılış zamanı — userTrades döngüsü / emir transactTime (updateTime değil)."""
    if not pos:
        return
    if pos.get("entry_time_locked") and not _mega_entry_time_suspect(pos):
        return
    coin = str(pos.get("symbol") or "").replace("USDT", "")
    sym = str(pos.get("symbol") or "").upper()
    side = str(pos.get("side") or "LONG").upper()
    oid = str(pos.get("order_id") or pos.get("exchange_order_id") or "").strip()
    times = None
    if mc and not mc.paper:
        times = _mega_open_time_from_user_trades(mc, sym, side)
    if not times:
        times = _mega_entry_fields_from_order(order if isinstance(order, dict) else None)
    if not times and mc and oid:
        try:
            raw = mc.query_order(coin, oid)
            times = _mega_entry_fields_from_order(raw)
        except Exception:
            times = None
    if not times and mc and oid:
        try:
            fills = mc.user_trades(coin, order_id=oid, limit=50) or []
            fill_ms = [int(t.get("time") or 0) for t in fills if int(t.get("time") or 0) > 0]
            if fill_ms:
                times = _mega_entry_fields_from_ts(_mega_ts_from_ms(min(fill_ms)))
        except Exception:
            pass
    if times and not _mega_entry_time_suspect(
        {"entry_time_str": times[1], "opened_at_iso": times[2]}
    ):
        pos["entry_time"], pos["entry_time_str"], pos["opened_at_iso"] = times
        pos["entry_time_locked"] = True


def _mega_copy_entry_fields(dst: dict[str, Any], src: dict[str, Any]) -> bool:
    if not src:
        return False
    if _mega_entry_time_suspect(src) and not src.get("entry_time_locked"):
        return False
    et = float(src.get("entry_time") or 0)
    if et <= 0 and not src.get("entry_time_locked"):
        return False
    if et > 0:
        dst["entry_time"] = et
    ets = src.get("entry_time_str")
    oai = src.get("opened_at_iso")
    if ets:
        dst["entry_time_str"] = ets
    if oai:
        dst["opened_at_iso"] = oai
    if src.get("entry_time_locked"):
        dst["entry_time_locked"] = True
    return bool(dst.get("entry_time") or dst.get("entry_time_str"))


def _mega_open_book_entry_map() -> dict[str, dict[str, Any]]:
    path = _mega_open_book_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in data.get("open") or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper()
        side = str(row.get("side") or "LONG").upper()
        if sym:
            out[f"{sym}:{side}"] = row
    return out


def enrich_mega_positions_open_times(rows: list[dict[str, Any]] | None = None) -> None:
    """Telegram/panel — borsa userTrades ile gerçek açılış; placeholder (03:00) atlanır."""
    targets = list(rows if rows is not None else _mega_positions)
    if not targets:
        return
    meta = _load_open_meta()
    book = _mega_open_book_entry_map()
    mc = get_mega_client()
    changed = False
    for pos in targets:
        key = _tp_pos_key(pos)
        if pos.get("entry_time_locked") and not _mega_entry_time_suspect(pos):
            continue
        if mc and not mc.paper:
            _mega_apply_open_time_from_order(pos, mc)
            if pos.get("entry_time_locked") and not _mega_entry_time_suspect(pos):
                changed = True
                continue
        best: dict[str, Any] | None = None
        for src in (book.get(key), meta.get(key)):
            if not isinstance(src, dict):
                continue
            if src.get("entry_time_locked") and not _mega_entry_time_suspect(src):
                best = src
                break
            if _mega_entry_time_suspect(src):
                continue
            et = float(src.get("entry_time") or 0)
            if et <= 0:
                continue
            if best is None or et < float(best.get("entry_time") or 1e18):
                best = src
        if best and _mega_copy_entry_fields(pos, best):
            changed = True
        if (not pos.get("entry_time_locked") or _mega_entry_time_suspect(pos)) and mc and not mc.paper:
            _mega_apply_open_time_from_order(pos, mc)
            if pos.get("entry_time_locked") and not _mega_entry_time_suspect(pos):
                changed = True
    if changed and targets is _mega_positions:
        _persist_open_meta()
        _persist_open_book(force=True)


def mega_position_open_ts(pos: dict[str, Any]) -> float | None:
    """Telegram/panel — pozisyonun gerçek açılış unix (UTC)."""
    if pos.get("entry_time_locked"):
        for key in ("entry_time", "opened_at_iso", "entry_time_str", "entry_time_iso"):
            raw = pos.get(key)
            if raw is None:
                continue
            try:
                if key == "entry_time":
                    et = float(raw)
                    if et > 0:
                        return et / 1000.0 if et > 1e12 else et
                else:
                    s = str(raw).strip()
                    if not s:
                        continue
                    if s.endswith("Z"):
                        s = s[:-1] + "+00:00"
                    if "T" in s:
                        dt = datetime.fromisoformat(s)
                    else:
                        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(
                            tzinfo=timezone.utc
                        )
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
            except Exception:
                continue
    try:
        et = float(pos.get("entry_time") or 0)
        if et > 0:
            return et / 1000.0 if et > 1e12 else et
    except (TypeError, ValueError):
        pass
    for key in ("opened_at_iso", "entry_time_str", "entry_time_iso"):
        raw = pos.get(key)
        if not raw:
            continue
        s = str(raw).strip()
        if not s:
            continue
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            if "T" in s:
                dt = datetime.fromisoformat(s)
            else:
                dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            continue
    return None


def _exchange_pos_to_local(ep: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    sym = str(ep.get("symbol") or f"{ep.get('coin', '')}USDT").upper()
    side = str(ep.get("side") or "LONG").upper()
    entry = float(ep.get("entry_price") or 0)
    mark = float(ep.get("mark_price") or entry)
    size = abs(float(ep.get("contracts") or 0))
    lev = max(int(ep.get("leverage") or 2), 1)
    notional = abs(float(ep.get("notional_usd") or 0))
    stake = float((existing or {}).get("stake_usd") or 0)
    if stake <= 0 and notional > 0 and lev > 0:
        stake = notional / lev
    if stake <= 0:
        stake = max(float(_mega_profile().get("min_stake_usd") or 400), 1.0)
    from elite_trader.fee_economics import tp_sl_gross_triggers

    tp_usd, sl_usd, net_tp, rt_fee = tp_sl_gross_triggers(stake, lev, "mega")
    if side == "LONG":
        tp_price = entry + tp_usd / size if size > 0 else entry
        sl_price = entry - sl_usd / size if size > 0 else entry
    else:
        tp_price = entry - tp_usd / size if size > 0 else entry
        sl_price = entry + sl_usd / size if size > 0 else entry
    pos_id = int((existing or {}).get("id") or 0)
    entry_ts, entry_str, opened_iso = _mega_entry_fields_from_ep(ep, existing)
    return {
        "id": pos_id,
        "symbol": sym,
        "side": side,
        "entry_price": entry,
        "current_price": mark,
        "size": size,
        "leverage": lev,
        "stake_usd": stake,
        "position_value": size * mark,
        "unrealized_pnl": float(ep.get("unrealized_pnl") or 0),
        "pnl_pct": (float(ep.get("unrealized_pnl") or 0) / max(stake, 1)) * 100,
        "entry_time": entry_ts,
        "entry_time_str": entry_str,
        "opened_at_iso": opened_iso,
        "exchange_update_ms": int(ep.get("exchange_update_ms") or 0),
        "tp_target": (existing or {}).get("tp_target") or tp_price,
        "sl_target": (existing or {}).get("sl_target") or sl_price,
        "tp_target_usd": float((existing or {}).get("tp_target_usd") or tp_usd),
        "sl_target_usd": float((existing or {}).get("sl_target_usd") or sl_usd),
        "tp_net_target_usd": float((existing or {}).get("tp_net_target_usd") or net_tp),
        "round_trip_fee_est_usd": rt_fee,
        "entry_fee": (existing or {}).get("entry_fee"),
        "on_exchange": True,
        "panel_mode": "mega",
        "execution_mode_at_open": "mega",
        "exchange_synced": True,
        "signal_source": "MEGA-LIVE",
        "min_unreal_seen": float((existing or {}).get("min_unreal_seen") or ep.get("unrealized_pnl") or 0),
        "max_unreal_seen": float((existing or {}).get("max_unreal_seen") or ep.get("unrealized_pnl") or 0),
        "price_history": (existing or {}).get("price_history") or [entry, mark],
        "time_history": (existing or {}).get("time_history") or [datetime.now(timezone.utc).isoformat()],
        "exchange_tp_order_id": (existing or {}).get("exchange_tp_order_id"),
        "exchange_tp_is_algo": (existing or {}).get("exchange_tp_is_algo"),
        "exchange_tp_stop": (existing or {}).get("exchange_tp_stop"),
        "exchange_tp_arm_failed": (existing or {}).get("exchange_tp_arm_failed"),
        "exchange_tp_arm_fail_code": (existing or {}).get("exchange_tp_arm_fail_code"),
        "entry_time_locked": bool((existing or {}).get("entry_time_locked")),
    }


def _exchange_open_count() -> int:
    n = 0
    for ep in _mega_positions_cache or []:
        if float(ep.get("contracts") or ep.get("positionAmt") or 0) != 0:
            n += 1
    return n


def _exchange_open_keys() -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for ep in _mega_positions_cache or []:
        sym = str(ep.get("symbol") or f"{ep.get('coin', '')}USDT").upper()
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        side = str(ep.get("side") or "LONG").upper()
        if float(ep.get("contracts") or ep.get("positionAmt") or 0) != 0:
            keys.add((sym, side))
    return keys


def _book_open_keys() -> set[tuple[str, str]]:
    return {
        (str(p.get("symbol") or "").upper(), str(p.get("side") or "LONG").upper())
        for p in _mega_positions
    }


_panel_exchange_sync_ts: float = 0.0
_panel_exchange_sync_inflight = False


def panel_exchange_sync_meta() -> dict[str, Any]:
    """Snapshot sıcak yol — REST/sync yok; önbellekten uyum metası."""
    cache_age = _mega_positions_list_age_sec()
    out: dict[str, Any] = {
        "book_n": len(_mega_positions),
        "exchange_n": 0,
        "mismatch": False,
        "synced": False,
        "cache_age_sec": round(cache_age, 2),
    }
    if not mega_live_enabled():
        return out
    mc = get_mega_client()
    if not mc or mc.paper:
        return out
    iv = max(30.0, _env_float("MEGA_PANEL_EXCHANGE_SYNC_SEC", 60.0))
    out["sync_iv_sec"] = iv
    stale_limit = max(90.0, _env_float("MEGA_PANEL_SYNC_STALE_SEC", iv * 2))
    if cache_age > iv * 2 and not (_mega_positions or _exchange_open_count()):
        schedule_panel_exchange_sync()
    if cache_age > stale_limit and (_mega_positions or _exchange_open_count()):
        out["stale"] = True
        return out
    ex_keys = _exchange_open_keys()
    book_keys = _book_open_keys()
    out["exchange_n"] = len(ex_keys)
    out["book_n"] = len(book_keys)
    out["mismatch"] = book_keys != ex_keys
    only_ex = ex_keys - book_keys
    only_book = book_keys - ex_keys
    if only_ex or only_book:
        out["only_exchange"] = [f"{s} {d}" for s, d in sorted(only_ex)]
        out["only_book"] = [f"{s} {d}" for s, d in sorted(only_book)]
    return out


def schedule_panel_exchange_sync() -> None:
    """Uyumsuzluk — arka planda tam sync (snapshot bloklamaz)."""
    global _panel_exchange_sync_inflight
    if _panel_exchange_sync_inflight:
        return
    _panel_exchange_sync_inflight = True

    def _run() -> None:
        global _panel_exchange_sync_inflight
        try:
            panel_exchange_sync(force=True)
        finally:
            _panel_exchange_sync_inflight = False

    threading.Thread(target=_run, name="mega-panel-ex-sync", daemon=True).start()


def panel_exchange_sync(*, force: bool = False) -> dict[str, Any]:
    """Tam uyum — arka plan veya zorunlu; snapshot doğrudan çağırmamalı."""
    global _panel_exchange_sync_ts, _mega_scan_light_cache
    out = panel_exchange_sync_meta()
    if not mega_live_enabled():
        return out
    mc = get_mega_client()
    if not mc or mc.paper:
        return out
    now = time.time()
    iv = max(30.0, _env_float("MEGA_PANEL_EXCHANGE_SYNC_SEC", 60.0))
    due = force or (now - float(_panel_exchange_sync_ts or 0)) >= iv
    ex_keys = _exchange_open_keys()
    book_keys = _book_open_keys()
    if due or force:
        refresh_mega_positions_cache(force=True, skip_wallet=True)
        ex_keys = _exchange_open_keys()
        book_keys = _book_open_keys()
        out["exchange_n"] = len(ex_keys)
        out["book_n"] = len(book_keys)
        out["mismatch"] = book_keys != ex_keys
    if not due and not out.get("mismatch") and not force:
        return out
    only_ex = ex_keys - book_keys
    only_book = book_keys - ex_keys
    if not ex_keys and book_keys:
        prune_ghost_open_positions(force=True)
        out["synced"] = True
    elif only_book and not only_ex:
        prune_book_positions_not_on_exchange()
        out["synced"] = True
    elif out["mismatch"] or len(book_keys) != len(ex_keys):
        sync_positions_from_exchange(
            force=True,
            skip_close_scan=True,
            skip_refresh=True,
            skip_adopt=True,
        )
        out["synced"] = True
    _panel_exchange_sync_ts = now
    _mega_scan_light_cache = None
    book_keys = _book_open_keys()
    ex_keys = _exchange_open_keys()
    out["book_n"] = len(book_keys)
    out["exchange_n"] = len(ex_keys)
    out["mismatch"] = book_keys != ex_keys
    only_ex = ex_keys - book_keys
    only_book = book_keys - ex_keys
    if only_ex or only_book:
        out["only_exchange"] = [f"{s} {d}" for s, d in sorted(only_ex)]
        out["only_book"] = [f"{s} {d}" for s, d in sorted(only_book)]
    return out


def prune_ghost_open_positions(*, force: bool = False) -> int:
    """
    Borsada açık yok ama yerel kitapta satır var → hayalet temizle (panel/bot uyumu).
    """
    global _mega_positions
    if not mega_live_enabled():
        return 0
    mc = get_mega_client()
    if not mc or mc.paper:
        return 0
    refresh_mega_positions_cache(force=True, skip_wallet=True)
    if _exchange_open_count() > 0:
        return prune_book_positions_not_on_exchange()
    ghosts = list(_mega_positions)
    if not ghosts:
        return 0
    _mega_positions.clear()
    _persist_open_book(force=True)
    print(
        f"  🧹 MEGA hayalet açık kitap: {len(ghosts)} satır silindi "
        f"(borsa açık=0)"
    )
    return len(ghosts)


def prune_book_positions_not_on_exchange() -> int:
    """Kitapta olup borsada (positionRisk) olmayan hayalet satırları kaldır."""
    global _mega_positions
    if not mega_live_enabled():
        return 0
    mc = get_mega_client()
    if not mc or mc.paper:
        return 0
    refresh_mega_positions_cache(force=True, skip_wallet=True)
    ex_keys = _exchange_open_keys()
    if not ex_keys:
        return 0
    vanished: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for p in list(_mega_positions):
        key = (
            str(p.get("symbol") or "").upper(),
            str(p.get("side") or "LONG").upper(),
        )
        if key in ex_keys:
            kept.append(p)
        else:
            vanished.append(p)
    if not vanished:
        return 0
    _mega_positions[:] = kept
    try:
        _reconcile_vanished_mega_positions(vanished)
    except Exception as exc:
        print(f"  ⚠ MEGA hayalet reconcile: {exc}")
    _persist_open_book(force=True)
    _mega_scan_light_cache = None
    syms = ", ".join(
        f"{p.get('symbol')} {p.get('side')}" for p in vanished[:6]
    )
    print(f"  🧹 MEGA kitap≠borsa hayalet: {len(vanished)} silindi ({syms})")
    return len(vanished)


def sync_positions_from_exchange(
    *,
    force: bool = False,
    skip_close_scan: bool = False,
    skip_refresh: bool = False,
    skip_adopt: bool = False,
) -> None:
    """Borsa positionRisk → yerel MEGA kitap (yeniden başlatma + manuel kapanış)."""
    global _mega_positions, _mega_position_id
    if not mega_live_enabled():
        return
    if not skip_refresh:
        refresh_mega_positions_cache(force=force, skip_wallet=not force)
    if _exchange_open_count() == 0 and _mega_positions:
        prune_ghost_open_positions()
        if not _mega_positions:
            return
    old_map = {
        (str(p["symbol"]).upper(), str(p["side"]).upper()): p for p in _mega_positions
    }
    synced: list[dict[str, Any]] = []
    max_id = _mega_position_id - 1
    for ep in _mega_positions_cache:
        sym = str(ep.get("symbol") or f"{ep.get('coin', '')}USDT").upper()
        side = str(ep.get("side") or "LONG").upper()
        key = (sym, side)
        existing = old_map.pop(key, None)
        row = _exchange_pos_to_local(ep, existing)
        if row["id"] <= 0:
            max_id += 1
            row["id"] = max_id
        synced.append(row)
    vanished = list(old_map.values())
    if vanished:
        _reconcile_vanished_mega_positions(vanished)
    _mega_positions = synced
    _mega_position_id = max(max_id + 1, _mega_position_id)
    if _exchange_open_count() == 0 and _mega_positions:
        prune_ghost_open_positions()
    _apply_open_meta_to_positions()
    enrich_mega_positions_open_times(_mega_positions)
    mc = get_mega_client()
    if mc and not mc.paper and not skip_adopt:
        _adopt_all_exchange_tps(mc)
    _persist_open_meta()
    if not skip_close_scan:
        try:
            from elite_trader.mega_close_sync import mega_close_sync_enabled

            if mega_close_sync_enabled() and not mega_live_bot_only_closed():
                _sync_missing_closes_from_exchange(force=force)
        except Exception:
            if not mega_live_bot_only_closed():
                _sync_missing_closes_from_exchange(force=force)
        _purge_open_position_phantom_closes()


def _reconcile_vanished_mega_positions(vanished: list[dict[str, Any]]) -> None:
    """Binance'te kapanmış (manuel/UI) pozisyonları userTrades ile kapanan listesine al."""
    mc = get_mega_client()
    for pos in vanished:
        if not pos.get("on_exchange"):
            continue
        sym = str(pos.get("symbol") or "")
        side = str(pos.get("side") or "LONG").upper()
        if mc and not mc.paper and _exchange_row(sym, side):
            continue
        exchange_settled: dict[str, Any] | None = None
        if mc and not mc.paper:
            exchange_settled = _mega_settle_close_from_api(
                pos,
                mc,
                exit_reason=str(pos.get("exit_reason") or "SL"),
                close_order_id=None,
            )
        exit_reason = _infer_vanished_exit_reason(pos, exchange_settled)
        from elite_trader.fee_economics import live_close_record_ok

        ok_rec, record_reason, skip_detail = live_close_record_ok(
            exit_reason=exit_reason,
            exchange_settled=exchange_settled,
            mode_id="mega",
            on_exchange=bool(pos.get("on_exchange") and mc and not mc.paper),
        )
        if not ok_rec:
            from elite_trader.exchange_settlement import settlement_has_api_close_fills
            from elite_trader.fee_economics import settled_exit_record_reason

            if exchange_settled and settlement_has_api_close_fills(exchange_settled):
                ok_rec = True
                record_reason = settled_exit_record_reason(
                    exit_reason, exchange_settled, mode_id="mega"
                )
            else:
                print(f"  ⛔ MEGA sync kayıt yok {sym}: {skip_detail}")
                try:
                    from elite_trader.mega_close_sync import (
                        sync_priority_coins_from_exchange,
                        wake_mega_close_sync,
                    )

                    coin = sym.replace("USDT", "").upper()
                    sync_priority_coins_from_exchange([coin])
                    wake_mega_close_sync(force=True)
                except Exception:
                    pass
                continue
        if _phantom_guard_active(sym, side):
            continue
        closed = _build_mega_closed_record(
            pos,
            record_reason or "EXCHANGE-MANUAL",
            exchange_settled=exchange_settled,
            close_order_id=(
                str(exchange_settled.get("close_order_id") or "")
                if exchange_settled
                else None
            ),
        )
        closed = _apply_phantom_slippage_meta(
            closed,
            pos,
            exit_reason=exit_reason,
            record_reason=record_reason or "",
            exchange_settled=exchange_settled,
        )
        if closed.get("phantom_slippage"):
            _register_phantom_close_guard(pos)
            print(
                f"  ⚠ MEGA phantom sync {sym} — tepe uPnL "
                f"${float(pos.get('max_unreal_seen') or 0):.2f}, "
                f"fill net ${float((exchange_settled or {}).get('wallet_pnl') or 0):.2f} "
                f"(panel gizli, kayıt+Telegram)"
            )
        _append_mega_closed_record(closed)
        gross = float(closed.get("pnl_usd") or closed.get("pnl_gross_usd") or 0)
        wallet = float(closed.get("wallet_pnl") or closed.get("final_pnl") or 0)
        print(
            f"  🔴 MEGA sync kapanış {sym} {record_reason} "
            f"brüt=${gross:.4f} cüzdan=${wallet:.4f}"
        )


def reset_mega_history(*, reason: str = "user_reset", fetch_wallet: bool = True) -> dict[str, Any]:
    """MEGA paper kitabı + yerel oturum kayıtlarını sıfırla; bakiye çapasını API'den al."""
    global _mega_positions, _mega_closed, _mega_position_id, _mega_closed_loaded
    from elite_trader import parallel_universe_engine as pe

    try:
        st = pe._load()
        st.setdefault("starting_capital_by_mode", {}).pop("mega", None)
        pe._save(st)
    except Exception:
        pass
    book_out = pe.reset_mode_book("mega")
    try:
        st = pe._load()
        mega_book = st.get("universes", {}).get("mega")
        if mega_book is not None:
            mega_book["session_start"] = 0.0
        pe._save(st)
    except Exception:
        pass
    _mega_positions = []
    _mega_closed = []
    _mega_position_id = 1
    _mega_closed_loaded = True
    if _mega_closed_path().is_file():
        _mega_closed_path().unlink(missing_ok=True)

    wallet: dict[str, Any] = {}
    bal = 0.0
    if fetch_wallet:
        try:
            wallet = _fetch_wallet(force=True)
            bal = _wallet_balance(wallet)
        except Exception:
            wallet = {}
    if bal > 0:
        _save_session_anchor(bal, reason=reason)
        pe.set_mode_session_start("mega", bal)
    else:
        if _mega_session_path().is_file():
            _mega_session_path().unlink(missing_ok=True)

    return {
        "ok": True,
        "reason": reason,
        "paper_cleared_open": book_out.get("cleared_open"),
        "paper_cleared_closed": book_out.get("cleared_closed"),
        "wallet_anchor": bal,
        "wallet": wallet,
    }


def _mega_profile() -> dict[str, Any]:
    from elite_trader.mode_profiles import get_profile

    return get_profile("mega") or {}


def _mega_max_open() -> int:
    """Profil tavanı — tam marjin modunda yalnızca hard cap."""
    from elite_trader.capital_slots import slot_config, wallet_full_balance_mode

    if wallet_full_balance_mode("mega"):
        return int(slot_config("mega")["hard_cap"])
    prof = _mega_profile()
    return int(prof.get("entry_max_open") or prof.get("max_open") or 4)


def _mega_stake_use_available_margin() -> bool:
    return _env_bool("MEGA_STAKE_USE_AVAILABLE_MARGIN", True)


def _mega_open_margin_buffer() -> float:
    return max(5.0, _env_float("MEGA_OPEN_MARGIN_BUFFER_USD", 30.0))


def _mega_min_slot_stake_usd() -> float:
    from elite_trader.capital_slots import slot_config

    return float(slot_config("mega")["slot_unit_usd"])


def _mega_deployable_margin() -> float:
    return max(0.0, _mega_available_margin() - _mega_open_margin_buffer())


def _mega_slot_budget_usd() -> float:
    """
    Slot tavanı bütçesi — kullanılabilir + açık pozisyon marjini (cross ≈ equity).
    Örn. $2 488 serbest + ~$2 430 bağlı → ~$4 900 → en fazla 4×$1000 slot.
    """
    buf = _mega_open_margin_buffer()
    avail = max(0.0, _mega_available_margin())
    committed = _mega_open_margin_committed()
    wallet = _fetch_wallet() if mega_live_enabled() and not mega_paper_sim_only() else {}
    margin_bal = float(
        wallet.get("total_margin_balance")
        or wallet.get("margin_balance")
        or wallet.get("totalWalletBalance")
        or 0
    )
    equity = _wallet_balance(wallet)
    mode = os.getenv("MEGA_SLOT_BUDGET_MODE", "equity").strip().lower()
    if mode in ("available", "avail", "free"):
        budget = avail
    elif mode in ("available_plus_committed", "sum", "expand"):
        budget = avail + committed
    else:
        budget = margin_bal if margin_bal > 0 else equity
        if budget <= 0:
            budget = avail + committed
        elif budget < avail + committed * 0.85:
            budget = max(budget, avail + committed)
    return max(0.0, budget - buf)


def _mega_available_is_net_on_exchange() -> bool:
    """Binance availableBalance açık pozisyon marjini zaten düşmüş."""
    return mega_live_enabled() and not mega_paper_sim_only() and _env_bool(
        "MEGA_AVAILABLE_IS_NET", True
    )


def _mega_deployable_for_new_stake() -> float:
    """
    Yeni açılış stake kaynağı.
    Canlıda: kullanılabilir bakiye (çift düşüm yok — ~$2488 tam kullanılır).
    """
    net = _mega_deployable_margin()
    if _mega_available_is_net_on_exchange():
        return net
    committed = (
        _mega_open_margin_committed()
        if _env_bool("MEGA_COMMIT_USE_EXCHANGE_MARGIN", True)
        else _mega_open_stake_committed()
    )
    return max(0.0, net - committed)


def _mega_total_slot_cap() -> int:
    """Kullanılabilir bakiye + bağlı marjin (equity) ile genişleyen slot tavanı."""
    from elite_trader.capital_slots import (
        effective_max_open,
        slot_allocator_enabled,
        wallet_full_balance_mode,
    )

    prof_cap = _mega_max_open()
    if mega_paper_sim_only() and not _mega_stake_use_available_margin():
        return prof_cap
    if not slot_allocator_enabled("mega") or not _env_bool("MEGA_DYNAMIC_MAX_OPEN", True):
        return prof_cap
    if wallet_full_balance_mode("mega"):
        budget = _mega_slot_budget_usd()
        if budget <= 0 and mega_live_enabled() and not mega_paper_sim_only():
            return 0
        cap_equity = effective_max_open(
            budget,
            profile_cap=prof_cap,
            mode_id="mega",
            dynamic=True,
        )
        if (
            mega_live_enabled()
            and not mega_paper_sim_only()
            and _env_bool("MEGA_SLOT_EXPAND_WITH_AVAILABLE", True)
        ):
            avail_net = _mega_deployable_margin()
            extra = effective_max_open(
                avail_net,
                profile_cap=prof_cap,
                mode_id="mega",
                dynamic=True,
            )
            return min(
                prof_cap,
                max(cap_equity, len(_mega_positions) + extra),
            )
        return cap_equity
    deploy_new = _mega_deployable_for_new_stake()
    if deploy_new <= 0 and mega_live_enabled() and not mega_paper_sim_only():
        return 0
    return effective_max_open(
        deploy_new,
        profile_cap=prof_cap,
        mode_id="mega",
        dynamic=True,
    )


def _mega_effective_max_open() -> int:
    """Panel / kapı — toplam slot tavanı (açık sayısı ayrı kontrol edilir)."""
    return _mega_total_slot_cap()


def _mega_slots_remaining() -> int:
    return max(0, _mega_total_slot_cap() - len(_mega_positions))


def _mega_boot_observe_snapshot() -> dict[str, Any]:
    try:
        from elite_trader.mega_boot_observe import snapshot

        return snapshot()
    except Exception:
        return {}


def _mega_entry_block_reason() -> str:
    """Panel — neden yeni MEGA / Flash açılmıyor."""
    try:
        from elite_trader.mega_boot_observe import boot_entry_block_reason

        boot_br = boot_entry_block_reason()
        if boot_br:
            return boot_br
    except Exception:
        pass
    cap = _mega_total_slot_cap()
    open_n = len(_mega_positions)
    avail = _mega_available_margin()
    budget = _mega_slot_budget_usd()
    committed = _mega_open_margin_committed()
    unit = int(_mega_min_slot_stake_usd())
    if open_n >= cap:
        over = open_n - cap
        return (
            f"Açık {open_n}/{cap} slot — bütçe ${budget:,.0f} "
            f"(kullanılabilir ${avail:,.0f} + bağlı marjin ${committed:,.0f}). "
            f"{'En az ' + str(over) + ' kapatın' if over > 0 else 'Slot dolu'}; "
            f"MEGA ve Flash reversal bekler."
        )
    deploy = _mega_deployable_for_new_stake()
    if deploy < 100.0:
        return (
            f"Serbest marjin ${deploy:.0f} — ${unit} pozisyon için yetersiz "
            f"(açıkta ~${_mega_open_margin_committed():.0f} bağlı)."
        )
    return ""


def _mega_stake_for_slot(*, is_flash: bool = False) -> float:
    """Kalan serbest marjini kalan slot sayısına böl ($1000 birim / küçük cüzdan)."""
    from elite_trader.capital_slots import plan_stake

    flash_min = max(100.0, _env_float("MEGA_FLASH_REVERSAL_STAKE_MIN_USD", 100.0))
    flash_max = max(flash_min, _env_float("MEGA_FLASH_REVERSAL_STAKE_MAX_USD", 700.0))
    deploy = _mega_deployable_for_new_stake()
    if deploy <= 0:
        return 0.0
    return plan_stake(
        deploy,
        len(_mega_positions),
        mode_id="mega",
        max_open=_mega_effective_max_open(),
        profile_cap=_mega_max_open(),
        is_flash=is_flash,
        flash_min=flash_min,
        flash_max=flash_max,
    )


def _mega_extra_slot_balance_ok() -> bool:
    """Eski 5–6. slot overflow — tam marjin modunda kapalı."""
    from elite_trader.capital_slots import wallet_full_balance_mode

    if wallet_full_balance_mode("mega"):
        return False
    min_free = max(100.0, _env_float("MEGA_EXTRA_SLOT_MIN_FREE_USD", 500.0))
    avail = _mega_available_margin()
    return avail >= min_free


def _mega_elite_extra_slots() -> int:
    from elite_trader.capital_slots import wallet_full_balance_mode

    if wallet_full_balance_mode("mega"):
        return 0
    if not _mega_extra_slot_balance_ok():
        return 0
    return max(0, min(2, _env_int("MEGA_ELITE_EXTRA_SLOTS", 0)))


def _mega_elite_open_count() -> int:
    return sum(1 for p in _mega_positions if p.get("mega_elite_entry"))


def _mega_flash_open_count() -> int:
    return sum(
        1
        for p in _mega_positions
        if p.get("mega_flash_reversal")
        or p.get("flash_reversal")
        or p.get("mega_flash_pump")
        or p.get("flash_pump_reversal")
    )


def _mega_overflow_extra_slots() -> int:
    if not _mega_extra_slot_balance_ok():
        return 0
    return _mega_elite_extra_slots()


def _mega_open_slot_limit(signal: dict[str, Any]) -> int:
    """Serbest marjine göre dinamik tavan — sabit 4+2 flash yok."""
    del signal
    return _mega_effective_max_open()


def _mega_elite_overflow_entry(signal: dict[str, Any]) -> bool:
    """Eski elit overflow — tam marjin modunda her zaman kapalı."""
    from elite_trader.capital_slots import wallet_full_balance_mode

    if wallet_full_balance_mode("mega"):
        return False
    if len(_mega_positions) < _mega_effective_max_open():
        return False
    extra = _mega_overflow_extra_slots()
    if extra <= 0:
        return False
    try:
        from elite_trader.mode_engines.mega_scoring import is_mega_elite_signal

        return bool(
            is_mega_elite_signal(signal)
            and _mega_elite_open_count() < extra
        )
    except Exception:
        return False


def _mega_flash_overflow_entry(signal: dict[str, Any]) -> bool:
    """Eski flash overflow — tam marjin modunda kapalı."""
    from elite_trader.capital_slots import wallet_full_balance_mode

    if wallet_full_balance_mode("mega"):
        return False
    if len(_mega_positions) < _mega_effective_max_open():
        return False
    if not (
        signal.get("mega_flash_reversal")
        or signal.get("flash_reversal")
        or signal.get("mega_flash_pump")
        or signal.get("flash_pump_reversal")
    ):
        return False
    extra = _mega_overflow_extra_slots()
    return extra > 0 and _mega_flash_open_count() < extra


def _mega_scan_slot_meta() -> dict[str, Any]:
    from elite_trader.capital_slots import plan_stake, stake_policy_label

    avail = _mega_available_margin()
    budget = _mega_slot_budget_usd()
    deploy = _mega_deployable_for_new_stake()
    max_o = _mega_total_slot_cap()
    open_n = len(_mega_positions)
    remaining = _mega_slots_remaining()
    over_cap = open_n > max_o
    return {
        "max_open": max_o,
        "slot_base": max_o,
        "slot_extra": 0,
        "open_count": open_n,
        "slots_remaining": remaining,
        "over_slot_cap": over_cap,
        "margin_committed_usd": round(_mega_open_margin_committed(), 2),
        "slot_budget_usd": round(budget, 2),
        "available_balance_usd": round(avail, 2),
        "deployable_margin": round(_mega_deployable_margin(), 2),
        "deployable_new_usd": round(deploy, 2),
        "available_is_net": _mega_available_is_net_on_exchange(),
        "stake_policy": stake_policy_label(budget, "mega"),
        "entry_block_reason": _mega_entry_block_reason(),
        "boot_observe": _mega_boot_observe_snapshot(),
        "next_stake_usd": plan_stake(
            deploy,
            open_n,
            mode_id="mega",
            max_open=max_o,
            profile_cap=_mega_max_open(),
        )
        if remaining > 0
        else 0.0,
    }


def open_position_count() -> int:
    """Açık MEGA pozisyon sayısı (rejim kilidi için)."""
    return len(_mega_positions)


def max_open_slots() -> int:
    return _mega_effective_max_open()


def _maybe_unlock_regime() -> None:
    if _mega_positions:
        return
    try:
        from elite_trader.mega_market_regime import record_slots_empty

        record_slots_empty()
    except Exception:
        pass


def _mega_exit_heavy_interval_sec() -> float:
    """Çıkış döngüsü REST — positionRisk / fee / borsa TP (sıcak yol)."""
    return max(0.12, min(0.55, _env_float("MEGA_EXIT_REST_SEC", 0.28)))


def _mega_rate_limit_safe_mode() -> bool:
    return _env_bool("MEGA_RATE_LIMIT_SAFE", True)


def _mega_cache_ttl_idle_sec() -> float:
    return max(15.0, _env_float("MEGA_REST_IDLE_SEC", 30.0))


def _mega_cache_ttl_open_sec() -> float:
    safe = _mega_rate_limit_safe_mode()
    try:
        from elite_trader.mega_async_hub import hub_cache_hot, mega_hub_enabled

        if mega_hub_enabled() and hub_cache_hot():
            default_hub = 20.0 if safe else 0.08
            return max(1.0 if safe else 0.05, _env_float("MEGA_HUB_CACHE_TTL_SEC", default_hub))
    except Exception:
        pass
    default_open = 12.0 if safe else 0.11
    return max(1.0 if safe else 0.08, _env_float("MEGA_CACHE_TTL_OPEN_SEC", default_open))


def _mega_position_risk_min_interval_sec(
    *,
    has_open: bool = False,
    panel: bool = False,
    force: bool = False,
) -> float:
    if panel:
        return max(8.0, _env_float("MEGA_PANEL_POS_RISK_SEC", 20.0))
    if has_open:
        if force:
            return max(3.0, _env_float("MEGA_REST_FORCE_MIN_SEC", 5.0))
        return max(6.0, _env_float("MEGA_REST_POLL_SEC", 12.0))
    return _mega_cache_ttl_idle_sec()


def _mega_profit_zone_rest_min_sec() -> float:
    """Kâr bölgesi exit — positionRisk min aralık (panel tick fırtınasını kes)."""
    return max(5.0, _env_float("MEGA_PROFIT_ZONE_REST_MIN_SEC", 8.0))


def _mega_position_risk_throttled(
    *,
    has_open: bool = False,
    panel: bool = False,
    force: bool = False,
) -> bool:
    global _mega_last_position_risk_ts
    if not _mega_last_position_risk_ts:
        return False
    min_iv = max(
        _env_float("MEGA_REST_MIN_INTERVAL_SEC", 8.0),
        _mega_position_risk_min_interval_sec(
            has_open=has_open, panel=panel, force=force
        ),
    )
    return (time.time() - _mega_last_position_risk_ts) < min_iv


def _uds_row_to_exchange(row: dict[str, Any]) -> dict[str, Any]:
    coin = str(row.get("coin") or "").upper()
    sym = str(row.get("symbol") or f"{coin}USDT").upper()
    contracts = abs(float(row.get("contracts") or 0))
    return {
        "coin": coin,
        "symbol": sym,
        "side": str(row.get("side") or "LONG").upper(),
        "contracts": contracts,
        "entry_price": float(row.get("entry_price") or 0),
        "mark_price": float(row.get("mark_price") or 0),
        "unrealized_pnl": float(row.get("unrealized_pnl") or 0),
        "source": "uds",
    }


def apply_mega_uds_wallet(wallet: dict[str, Any]) -> None:
    global _mega_wallet, _mega_wallet_fetch_ts
    if not wallet:
        return
    _mega_wallet.update(wallet)
    _mega_wallet["source"] = "uds"
    _mega_wallet_fetch_ts = time.time()


def apply_mega_uds_positions(rows: list[dict[str, Any]]) -> None:
    global _mega_positions_cache, _mega_cache_ts, _mega_cache_source
    parsed = [_uds_row_to_exchange(r) for r in (rows or []) if r]
    _mega_positions_cache = parsed
    _mega_cache_ts = time.time()
    _mega_cache_source = "uds"
    try:
        from elite_trader.mega_async_hub import overlay_hub_marks

        overlay_hub_marks(_mega_positions_cache)
    except Exception:
        pass


def mega_positions_cache_nonempty() -> bool:
    return bool(_mega_positions_cache)


def _exchange_row_to_uds(ep: dict[str, Any]) -> dict[str, Any]:
    coin = str(ep.get("coin") or "").upper()
    sym = str(ep.get("symbol") or f"{coin}USDT").upper()
    return {
        "coin": coin,
        "symbol": sym,
        "side": str(ep.get("side") or "LONG").upper(),
        "contracts": abs(float(ep.get("contracts") or 0)),
        "entry_price": float(ep.get("entry_price") or 0),
        "mark_price": float(ep.get("mark_price") or 0),
        "unrealized_pnl": float(ep.get("unrealized_pnl") or 0),
    }


def bootstrap_mega_hub_positions() -> int:
    """Hub açılış — REST snapshot → UDS state + cache (UDS event beklemeden)."""
    mc = get_mega_client()
    if not mc or mc.paper or not mega_live_enabled():
        return 0
    try:
        rows = mc.exchange_positions() or []
    except Exception as exc:
        print(f"  ⚠ MEGA hub bootstrap REST: {exc}")
        return 0
    uds_rows = [_exchange_row_to_uds(ep) for ep in rows if ep]
    try:
        from elite_trader.mega_async_hub import get_mega_hub

        hub = get_mega_hub()
        if hub and hub._uds:
            hub._uds.load_positions(uds_rows)
        else:
            apply_mega_uds_positions(uds_rows)
    except Exception:
        apply_mega_uds_positions(uds_rows)
    if uds_rows:
        print(f"  ✓ MEGA hub bootstrap: {len(uds_rows)} pozisyon (REST→cache)")
    return len(uds_rows)


def _mega_positions_list_age_sec() -> float:
    """Pozisyon listesi yaşı — mark overlay ile karıştırılmaz."""
    now = time.time()
    # Panel exchange-only: yaş = son REST positionRisk (_mega_cache_ts), hub UDS değil
    if _mega_panel_exchange_only():
        if _mega_cache_ts:
            return max(0.0, now - float(_mega_cache_ts))
        return 999.0
    try:
        from elite_trader.mega_async_hub import get_mega_hub, mega_hub_enabled

        if mega_hub_enabled():
            hub = get_mega_hub()
            if hub and hub._last_positions_ts:
                hub_age = max(0.0, now - float(hub._last_positions_ts))
                if _mega_cache_ts:
                    rest_age = max(0.0, now - float(_mega_cache_ts))
                    return min(hub_age, rest_age)
                return hub_age
    except Exception:
        pass
    if _mega_cache_ts:
        return max(0.0, now - float(_mega_cache_ts))
    return 999.0


def _mega_panel_pos_risk_max_age_sec() -> float:
    """Panel açık pozisyon — demo-fapi positionRisk yenileme (hub 120s değil)."""
    return max(0.25, _env_float("MEGA_PANEL_POS_RISK_SEC", 0.85))


def _mega_positions_list_stale(*, max_sec: float | None = None) -> bool:
    limit = max_sec
    if limit is None:
        limit = max(15.0, _env_float("MEGA_HUB_POS_FRESH_MS", 120_000) / 1000.0)
    return _mega_positions_list_age_sec() > float(limit)


def _mega_panel_positions_stale() -> bool:
    return _mega_positions_list_age_sec() > _mega_panel_pos_risk_max_age_sec()


def _mega_tick_positions_stale() -> bool:
    """Panel /ticks — uPnL REST yenileme (mark hub overlay ile ayrı)."""
    sec = _env_float("MEGA_TICK_POS_RISK_SEC", 0.0)
    if sec <= 0:
        sec = _mega_panel_pos_risk_max_age_sec()
    return _mega_positions_list_age_sec() > float(sec)


def _panel_overlay_hub_mark_on_rows(
    rows: list[dict[str, Any]], *, hub_meta: dict[str, Any] | None = None
) -> None:
    """Panel Mark — hub bookTicker (ms); uPnL/unRealizedProfit positionRisk'te kalır."""
    if not _env_bool("MEGA_PANEL_MARK_HUB_OVERLAY", True):
        return
    marks: dict[str, float] = {}
    meta = hub_meta or {}
    try:
        from elite_trader.mega_async_hub import hub_marks_snapshot

        marks, meta = hub_marks_snapshot(max_recv_age_sec=1.2)
    except Exception:
        marks = {}
    if not marks:
        return
    max_drift = max(0.0, _env_float("MEGA_PANEL_MARK_HUB_MAX_DRIFT_PCT", 0.35))
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        coin = sym.replace("USDT", "")
        px = marks.get(coin) or marks.get(sym)
        if not px or float(px) <= 0:
            continue
        px = float(px)
        ex0 = row.get("exchange_display") or {}
        rest_mark = float(ex0.get("markPrice") or row.get("mark_price") or 0)
        if max_drift > 0 and rest_mark > 0:
            drift_pct = abs(px - rest_mark) / rest_mark * 100.0
            if drift_pct > max_drift:
                continue
        row["mark_price"] = px
        row["current_price"] = px
        row["price_source"] = "hub_mark"
        ex = dict(row.get("exchange_display") or {})
        ex["markPrice"] = f"{px:.8f}".rstrip("0").rstrip(".")
        row["exchange_display"] = ex
        row["mark_age_ms"] = int(meta.get("mark_lag_ms") or meta.get("lag_ms") or 0)


def _mega_panel_rest_priority() -> bool:
    return _env_bool("MEGA_PANEL_REST_PRIORITY", True)


def _mega_rest_poll_allowed(*, force: bool = False, panel: bool = False) -> bool:
    """Ban/degraded iken positionRisk fırtınasını kes; panel tick bütçe dışı."""
    panel_ok = panel and _mega_panel_rest_priority()
    if panel_ok and _mega_panel_exchange_only():
        try:
            from elite_trader.connection_alerts import ip_ban_active

            if ip_ban_active():
                return False
        except Exception:
            pass
        if not force:
            try:
                from elite_trader.binance_rest_budget import near_limit
                from elite_trader.network_guard import binance_rest_enabled

                if not binance_rest_enabled() or near_limit():
                    return False
            except Exception:
                pass
        return True
    if force or panel_ok:
        try:
            from elite_trader.connection_alerts import ip_ban_active

            if ip_ban_active():
                return False
        except Exception:
            pass
        if panel_ok:
            return True
    try:
        from elite_trader.network_guard import binance_rest_enabled

        return bool(binance_rest_enabled())
    except Exception:
        return True


def touch_mega_cache_from_hub_marks() -> bool:
    """Mark WS tick — uPnL overlay (pozisyon listesi zaman damgasını değiştirme)."""
    global _mega_mark_overlay_ts, _mega_cache_source
    if _mega_panel_exchange_only():
        return False
    if not _mega_positions_cache:
        return False
    try:
        from elite_trader.mega_async_hub import (
            hub_mark_fresh,
            mega_hub_enabled,
            note_hub_mark_touch,
            overlay_hub_marks,
        )

        if not mega_hub_enabled():
            return False
        overlay_hub_marks(_mega_positions_cache)
        mark_ms = max(50.0, _env_float("MEGA_HUB_MARK_FRESH_MS", 120.0))
        if hub_mark_fresh(max_age_ms=mark_ms):
            _mega_mark_overlay_ts = time.time()
            if _mega_cache_source == "rest":
                _mega_cache_source = "hub_mark"
            note_hub_mark_touch()
            return True
    except Exception:
        pass
    return False


def mega_open_coins_for_hub() -> list[str]:
    coins: set[str] = set()
    for ep in _mega_positions_cache:
        c = str(ep.get("coin") or "").upper().strip()
        if c:
            coins.add(c)
    for pos in _mega_positions:
        sym = str(pos.get("symbol") or "")
        c = sym.replace("USDT", "").upper().strip()
        if c:
            coins.add(c)
    return sorted(coins)


def refresh_mega_positions_cache(
    *,
    force: bool = False,
    skip_wallet: bool = False,
    panel_critical: bool = False,
) -> bool:
    global _mega_positions_cache, _mega_cache_ts, _mega_cache_source, _mega_position_risk_ok_ts
    global _mega_last_position_risk_ts
    mc = get_mega_client()
    if not mc or mc.paper or not mega_live_enabled():
        return False
    panel_critical = panel_critical and _mega_panel_rest_priority()
    try:
        from elite_trader.network_guard import binance_rest_enabled

        if not panel_critical and not binance_rest_enabled() and not force:
            return bool(_mega_positions_cache)
    except Exception:
        pass
    if not force and _mega_positions_list_stale() and _mega_rest_poll_allowed(
        panel=panel_critical
    ):
        force = True
    if panel_critical and _mega_panel_exchange_only() and _mega_panel_positions_stale():
        force = True
        panel_critical = True
    if not _mega_rest_poll_allowed(force=force, panel=panel_critical):
        return bool(_mega_positions_cache)
    now = time.time()
    has_open = bool(_mega_positions) or _exchange_open_count() > 0
    if _mega_position_risk_throttled(
        has_open=has_open, panel=panel_critical, force=force
    ):
        if panel_critical:
            return bool(_mega_positions_cache)
        if force and has_open and _mega_profit_zone_active():
            if (time.time() - float(_mega_last_position_risk_ts or 0)) < _mega_profit_zone_rest_min_sec():
                return bool(_mega_positions_cache)
        else:
            return bool(_mega_positions_cache)
    age = now - float(_mega_cache_ts or 0) if _mega_cache_ts else 999.0
    default_stale = 25.0 if _mega_rate_limit_safe_mode() else 0.55
    max_stale = max(1.0 if _mega_rate_limit_safe_mode() else 0.35, _env_float("MEGA_CACHE_MAX_STALE_SEC", default_stale))
    if panel_critical and _mega_panel_exchange_only():
        max_stale = min(
            max_stale,
            max(0.35, _mega_panel_pos_risk_max_age_sec()),
        )
    mark_hot = _mega_hub_mark_hot()
    if _mega_panel_exchange_only() and panel_critical:
        mark_hot = False
    profit_hot = _mega_profit_zone_active()
    hub_hot = False
    if not force:
        touch_mega_cache_from_hub_marks()
        now = time.time()
        age = now - float(_mega_cache_ts or 0) if _mega_cache_ts else 999.0
        try:
            from elite_trader.mega_async_hub import hub_cache_hot, mega_hub_enabled

            if mega_hub_enabled() and hub_cache_hot():
                hub_hot = True
                ttl = (
                    _mega_cache_ttl_open_sec()
                    if has_open
                    else _mega_cache_ttl_idle_sec()
                )
                if age < ttl and age < max_stale and not profit_hot:
                    return bool(_mega_positions_cache)
        except Exception:
            pass
        if mark_hot and not profit_hot:
            reconcile_sec = max(120.0, _env_float("MEGA_HUB_RECONCILE_SEC", 300.0))
            if _mega_positions_list_age_sec() < reconcile_sec:
                return bool(_mega_positions_cache)
        if profit_hot and not panel_critical:
            force = True
    if not force and _mega_cache_ts and not hub_hot and not mark_hot:
        ttl = (
            _mega_cache_ttl_open_sec()
            if has_open
            else _mega_cache_ttl_idle_sec()
        )
        if age < ttl and age < max_stale:
            return bool(_mega_positions_cache)
    if not force and age >= max_stale and not hub_hot and not mark_hot:
        force = True
    if (hub_hot or mark_hot) and not force and not profit_hot:
        return bool(_mega_positions_cache)
    try:
        _mega_positions_cache = mc.exchange_positions() or []
        _mega_cache_ts = time.time()
        _mega_last_position_risk_ts = _mega_cache_ts
        _mega_position_risk_ok_ts = _mega_cache_ts
        _mega_cache_source = "rest"
        touch_mega_cache_from_hub_marks()
        if not skip_wallet:
            _fetch_wallet(force=force)
        return True
    except Exception as exc:
        if age >= max_stale or panel_critical:
            print(f"  ⚠ MEGA positionRisk yenileme: {exc}")
        return bool(_mega_positions_cache)


def _position_health_status(
    pos: dict[str, Any],
    *,
    list_age_ms: int = 99999,
    mark_age_ms: int = 99999,
    hub_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Panel — pozisyon/fiyat/kapanış emri durumu (yeşil/kırmızı göstergeler)."""
    sym = str(pos.get("symbol") or "").upper()
    side = str(pos.get("side") or "LONG").upper()
    on_ex = bool(pos.get("on_exchange"))
    unreal = float(pos.get("unrealized_pnl") or pos.get("exchange_unrealized_pnl") or 0)
    items: list[dict[str, Any]] = []

    in_cache = False
    for ep in _mega_positions_cache or []:
        es = str(ep.get("symbol") or f"{ep.get('coin', '')}USDT").upper()
        ed = str(ep.get("side") or "LONG").upper()
        if es == sym and ed == side:
            in_cache = True
            break
    list_warn = max(1500.0, _env_float("MEGA_HEALTH_POS_LIST_MS", 6000.0))
    pos_ok = (not on_ex) or (in_cache and list_age_ms <= list_warn)
    pos_detail = (
        f"sync {list_age_ms}ms"
        if in_cache
        else ("borsada yok" if on_ex else "yerel/sim")
    )
    items.append(
        {"id": "position", "label": "Pozisyon", "ok": pos_ok, "detail": pos_detail}
    )

    hub = hub_meta or {}
    mark_lim = max(
        250.0,
        _env_float("MEGA_HUB_MARK_FRESH_MS", 100.0) * 2.5,
    )
    hub_lag = hub.get("mark_lag_ms")
    hub_alive = bool(hub.get("alive"))
    if on_ex:
        price_ok = mark_age_ms <= mark_lim or (
            hub_alive and hub_lag is not None and float(hub_lag) <= mark_lim
        )
        price_detail = f"mark {mark_age_ms}ms" + (
            f" · hub {int(hub_lag)}ms" if hub_lag is not None else ""
        )
    else:
        price_ok = float(pos.get("current_price") or pos.get("mark_price") or 0) > 0
        price_detail = "sim mark"
    items.append(
        {"id": "price", "label": "Fiyat", "ok": price_ok, "detail": price_detail}
    )

    arm_gross = max(1.0, _env_float("MEGA_EXCHANGE_ARM_GROSS_USD", 1.5))
    tp_need = on_ex and (
        mega_exchange_tp_enabled() or mega_exchange_dual_tp_enabled()
    )
    has_tp = bool(str(pos.get("exchange_tp_order_id") or "").strip())
    tp_fail = bool(pos.get("exchange_tp_arm_failed"))
    if not tp_need:
        tp_ok, tp_detail = True, "TP kapalı/yerel"
    elif has_tp:
        tp_ok, tp_detail = True, f"TP #{str(pos.get('exchange_tp_order_id'))[:10]}"
    elif tp_fail:
        tp_ok, tp_detail = (
            False,
            f"TP hata {pos.get('exchange_tp_arm_fail_code') or 'arm'}",
        )
    elif unreal < arm_gross * 0.35:
        tp_ok, tp_detail = True, "TP bekle (düşük kâr)"
    else:
        tp_ok, tp_detail = False, "TP emri yok"
    items.append({"id": "tp_order", "label": "TP emri", "ok": tp_ok, "detail": tp_detail})

    lock_need = on_ex and mega_exchange_trail_lock_enabled()
    has_lock = bool(str(pos.get("exchange_lock_order_id") or "").strip())
    if not lock_need:
        lock_ok, lock_detail = True, "Kilit kapalı/yerel"
    elif has_lock:
        lock_ok, lock_detail = (
            True,
            f"Kilit #{str(pos.get('exchange_lock_order_id'))[:10]}",
        )
    elif unreal < arm_gross * 0.35:
        lock_ok, lock_detail = True, "Kilit bekle"
    else:
        lock_ok, lock_detail = False, "Kâr kilidi yok"
    items.append(
        {"id": "profit_lock", "label": "Kâr kilidi", "ok": lock_ok, "detail": lock_detail}
    )

    exit_iv = max(0.35, _env_float("MEGA_HEALTH_EXIT_EVAL_SEC", 1.2))
    last_eval = float(_mega_last_exit_eval_ts or 0)
    if last_eval <= 0:
        exit_ok = mega_motor_active()
        exit_detail = "motor aktif"
    else:
        exit_age = time.time() - last_eval
        exit_ok = mega_motor_active() and exit_age <= exit_iv
        exit_detail = f"eval {int(exit_age * 1000)}ms önce"
    items.append(
        {
            "id": "exit_motor",
            "label": "Çıkış motoru",
            "ok": exit_ok,
            "detail": exit_detail,
        }
    )

    pos_key = _tp_pos_key(pos)
    close_busy = pos_key in _mega_lock_inflight or pos_key in _mega_tp_arm_inflight
    items.append(
        {
            "id": "close_process",
            "label": "Kapanış işlemi",
            "ok": not close_busy,
            "detail": "emir güncelleniyor" if close_busy else "boşta",
        }
    )

    return {
        "items": items,
        "all_ok": all(bool(it.get("ok")) for it in items),
    }


def _attach_position_health_to_row(
    p: dict[str, Any],
    *,
    list_age_ms: int,
    mark_age_ms: int,
    hub_meta: dict[str, Any] | None = None,
) -> None:
    p["health_status"] = _position_health_status(
        p,
        list_age_ms=list_age_ms,
        mark_age_ms=mark_age_ms,
        hub_meta=hub_meta,
    )


def _finalize_open_ui_rows(
    rows: list[dict[str, Any]],
    *,
    list_age_ms: int,
    mark_age_ms: int,
    hub_meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Panel satırları — meta birleştir (REST yok)."""
    now = time.time()
    meta_map = {
        (str(m.get("symbol")), str(m.get("side"))): m for m in _mega_positions
    }
    if hub_meta is None:
        try:
            _, hub_meta = _panel_hub_marks()
        except Exception:
            hub_meta = {}
    for p in rows:
        p["panel_mode"] = "mega"
        p["data_source"] = "binance"
        p["signal_source"] = p.get("signal_source") or "MEGA-LIVE"
        et = float(p.get("entry_time") or 0)
        if et > 0:
            p["duration_sec"] = max(0.0, now - et)
        ex = dict(p.get("exchange_display") or {})
        unreal = _panel_api_unreal(p)
        if unreal is not None:
            p["exchange_unrealized_pnl"] = unreal
            p["unrealized_pnl"] = unreal
            ex["unRealizedProfit"] = str(unreal)
            p["exchange_display"] = ex
            p["upnl_source"] = "binance_positionRisk"
        else:
            p["exchange_unrealized_pnl"] = None
            p["unrealized_pnl"] = None
            ex.pop("unRealizedProfit", None)
            p["exchange_display"] = ex
            p["upnl_source"] = "missing"
            p["upnl_missing"] = True
        net_tp = float(p.get("tp_net_target_usd") or 0)
        max_u = float(
            p.get("max_exchange_unreal_seen") or p.get("max_unreal_seen") or 0
        )
        if net_tp > 0 and unreal is not None and unreal > 0:
            p["tp_progress_pct"] = round(min(100.0, unreal / net_tp * 100.0), 1)
        else:
            p["tp_progress_pct"] = 0.0
        if net_tp > 0 and max_u > 0:
            p["tp_peak_progress_pct"] = round(min(150.0, max_u / net_tp * 100.0), 1)
        else:
            p["tp_peak_progress_pct"] = p.get("tp_progress_pct") or 0.0
        p["positions_cache_age_ms"] = list_age_ms
        p["exchange_data_age_ms"] = mark_age_ms
        meta = meta_map.get((str(p.get("symbol")), str(p.get("side"))))
        if meta:
            for key in (
                "exchange_tp_order_id",
                "exchange_tp_stop",
                "exchange_tp_net",
                "exchange_lock_order_id",
                "exchange_lock_stop",
                "exchange_lock_net",
                "exchange_lock_milestone",
                "exchange_peak_lock_net",
                "exchange_peak_tp_net",
            ):
                if meta.get(key) is not None:
                    p[key] = meta.get(key)
        _attach_position_health_to_row(
            p, list_age_ms=list_age_ms, mark_age_ms=mark_age_ms, hub_meta=hub_meta
        )
    return rows


def _open_ticks_rows_fast(*, hub_meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Panel /ticks — yalnızca positionRisk önbelleği (reconcile/enrich yok, <100ms hedef)."""
    from elite_trader.exchange_open_display import (
        _filter_exchange_rows_for_panel,
        _minimal_position_from_exchange,
    )

    local_map: dict[tuple[str, str], dict[str, Any]] = {}
    for p in _mega_positions:
        if p.get("on_exchange") or p.get("exchange_synced"):
            local_map[(str(p.get("symbol") or "").upper(), str(p.get("side") or "LONG").upper())] = p
    list_age_ms, mark_age_ms = _open_ui_age_ms()
    rows: list[dict[str, Any]] = []
    for ep in _filter_exchange_rows_for_panel(list(_mega_positions_cache or [])):
        sym = str(ep.get("symbol") or f"{ep.get('coin', '')}USDT").upper()
        side = str(ep.get("side") or "LONG").upper()
        meta = local_map.get((sym, side))
        pid = int(meta["id"]) if meta and meta.get("id") is not None else 0
        row = _minimal_position_from_exchange(ep, position_id=pid, local_meta=meta)
        if meta:
            for key in (
                "tp_net_target_usd",
                "tp_target_usd",
                "entry_time",
                "entry_time_str",
                "opened_at_iso",
                "exchange_tp_order_id",
            ):
                if meta.get(key) is not None:
                    row[key] = meta[key]
        rows.append(row)
    return _finalize_open_ui_rows(
        rows, list_age_ms=list_age_ms, mark_age_ms=mark_age_ms, hub_meta=hub_meta or {}
    )


def _panel_upnl_audit(open_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Panel — pozisyon uPnL toplamı vs cüzdan unrealized (Binance tutarlılık)."""
    pos_sum = 0.0
    n = 0
    for r in open_rows:
        u = _panel_api_unreal(r)
        if u is None:
            continue
        pos_sum += float(u)
        n += 1
    wallet_u = float(_mega_wallet.get("total_unrealized_pnl") or 0)
    if wallet_u == 0 and open_rows:
        wallet_u = sum(
            float(r.get("unrealized_pnl") or r.get("exchange_unrealized_pnl") or 0)
            for r in open_rows
        )
    delta = round(pos_sum - wallet_u, 4) if wallet_u else 0.0
    return {
        "positions_sum": round(pos_sum, 4),
        "wallet_unrealized": round(wallet_u, 4),
        "delta": delta,
        "position_count": n,
        "ok": abs(delta) < max(1.5, abs(wallet_u) * 0.05) if wallet_u else True,
    }


def _open_ui_age_ms() -> tuple[int, int]:
    now = time.time()
    list_age_ms = max(0, int(_mega_positions_list_age_sec() * 1000))
    if _mega_panel_exchange_only():
        return list_age_ms, list_age_ms
    mark_age_ms = max(
        0,
        int((now - float(_mega_mark_overlay_ts or _mega_cache_ts or now)) * 1000),
    )
    return list_age_ms, mark_age_ms


def _build_mega_open_rows_light() -> list[dict[str, Any]]:
    """Light snapshot — panel için taze positionRisk (≤~1s), mark yalnızca fiyat."""
    mc = get_mega_client()
    if mega_sim_enabled() and not mega_live_enabled() and _mega_positions:
        refresh_mega_sim_marks()
        return [_mega_sim_row_for_ui(p) for p in _mega_positions]
    if mega_live_enabled() and mc and not mc.paper:
        if _mega_panel_positions_stale():
            refresh_mega_positions_cache(
                force=True, skip_wallet=True, panel_critical=True
            )
        if not _mega_panel_exchange_only():
            touch_mega_cache_from_hub_marks()
        if not _mega_positions_cache:
            try:
                prune_ghost_open_positions(force=True)
            except Exception:
                pass
            return []
        from elite_trader.exchange_open_display import (
            build_open_positions_for_ui,
            reconcile_local_positions,
        )

        reconcile_local_positions(_mega_positions, _mega_positions_cache)
        list_age_ms, mark_age_ms = _open_ui_age_ms()
        rows = build_open_positions_for_ui(
            _mega_positions,
            list(_mega_positions_cache),
            mc,
            allow_chart_fetch=False,
            enrich_fill=False,
        )
        return _finalize_open_ui_rows(rows, list_age_ms=list_age_ms, mark_age_ms=mark_age_ms)
    if not mc or mc.paper or not _mega_positions_cache:
        refresh_mega_sim_marks()
        return [_mega_sim_row_for_ui(p) for p in _mega_positions if not p.get("on_exchange")]
    from elite_trader.exchange_open_display import build_open_positions_for_ui

    list_age_ms, mark_age_ms = _open_ui_age_ms()
    rows = build_open_positions_for_ui(
        _mega_positions,
        list(_mega_positions_cache),
        mc,
        allow_chart_fetch=False,
        enrich_fill=False,
    )
    return _finalize_open_ui_rows(rows, list_age_ms=list_age_ms, mark_age_ms=mark_age_ms)


def _build_mega_open_for_ui(
    *,
    light: bool = False,
    allow_chart_fetch: bool | None = None,
) -> list[dict[str, Any]]:
    """Panel — Binance positionRisk + mark (9005 ile aynı yol)."""
    if light and allow_chart_fetch is not True:
        return _build_mega_open_rows_light()
    mc = get_mega_client()
    if mega_sim_enabled() and not mega_live_enabled() and _mega_positions:
        refresh_mega_sim_marks()
        return [_mega_sim_row_for_ui(p) for p in _mega_positions]
    if mega_live_enabled() and mc and not mc.paper:
        ui_reconcile = max(
            _mega_panel_pos_risk_max_age_sec(),
            _env_float("MEGA_UI_POS_RECONCILE_SEC", 2.0),
        )
        stale_ui = _mega_positions_list_age_sec() > ui_reconcile
        if (not light or stale_ui) and _mega_rest_poll_allowed(force=stale_ui):
            refresh_mega_positions_cache(force=stale_ui, skip_wallet=light)
        if not _mega_positions_cache:
            try:
                prune_ghost_open_positions(force=True)
            except Exception:
                pass
            return []
    elif not mc or mc.paper or not _mega_positions_cache:
        refresh_mega_sim_marks()
        return [_mega_sim_row_for_ui(p) for p in _mega_positions if not p.get("on_exchange")]

    ui_reconcile = max(
        _mega_panel_pos_risk_max_age_sec(),
        _env_float("MEGA_UI_POS_RECONCILE_SEC", 2.0),
    )
    stale_ui = _mega_positions_list_age_sec() > ui_reconcile
    if (not light or stale_ui) and _mega_rest_poll_allowed(force=stale_ui):
        refresh_mega_positions_cache(force=stale_ui, skip_wallet=light)

    from elite_trader.exchange_open_display import (
        build_open_positions_for_ui,
        reconcile_local_positions,
    )

    reconcile_local_positions(_mega_positions, _mega_positions_cache)
    charts = allow_chart_fetch if allow_chart_fetch is not None else not light
    rows = build_open_positions_for_ui(
        _mega_positions,
        list(_mega_positions_cache),
        mc,
        allow_chart_fetch=charts,
        enrich_fill=not light,
    )
    list_age_ms, mark_age_ms = _open_ui_age_ms()
    return _finalize_open_ui_rows(rows, list_age_ms=list_age_ms, mark_age_ms=mark_age_ms)


def _exchange_row(symbol: str, side: str) -> dict[str, Any] | None:
    sym = str(symbol).upper()
    sd = str(side).upper()
    for ep in _mega_positions_cache:
        coin = str(ep.get("coin") or sym.replace("USDT", "")).upper()
        if coin + "USDT" != sym and coin != sym.replace("USDT", ""):
            continue
        if str(ep.get("side") or "LONG").upper() == sd:
            amt = abs(float(ep.get("contracts") or ep.get("positionAmt") or 0))
            if amt > 0:
                return ep
    return None


def _exchange_any_for_symbol(symbol: str) -> dict[str, Any] | None:
    """Sembolde herhangi bir borsa pozisyonu (flip önlemi)."""
    sym = str(symbol).upper()
    for ep in _mega_positions_cache:
        coin = str(ep.get("coin") or sym.replace("USDT", "")).upper()
        if coin + "USDT" != sym and coin != sym.replace("USDT", ""):
            continue
        amt = abs(float(ep.get("contracts") or ep.get("positionAmt") or 0))
        if amt > 0:
            return ep
    return None


def _mega_is_reduce_only_rejected(exc: BaseException) -> bool:
    err = str(exc)
    return "-2022" in err or "ReduceOnly Order is rejected" in err


def _mega_is_order_timeout(exc: BaseException) -> bool:
    from elite_trader.binance_order_reconcile import is_order_timeout_error

    return is_order_timeout_error(exc)


def _mega_recover_close_after_timeout(
    idx: int,
    pos: dict[str, Any],
    exit_reason: str,
    *,
    mc: Any,
    close_order_id: str | None = None,
) -> bool:
    """-1007: borsa flat ise settlement; açıksa False (çift MARKET yok)."""
    from elite_trader.binance_order_reconcile import recover_close_after_order_timeout

    sym = str(pos.get("symbol") or "")
    print(
        f"  ⚠ MEGA kapanış timeout {sym} (-1007) — "
        f"positionRisk/userTrades doğrulanıyor"
    )
    refresh_mega_positions_cache(force=True)
    if not _exchange_row(sym, str(pos.get("side") or "LONG")):
        return _mega_finalize_flat_exchange_close(idx, pos, exit_reason, mc=mc)
    settled, oid = recover_close_after_order_timeout(mc, pos, settle_wait_sec=0.5)
    if not settled:
        print(
            f"  ⛔ MEGA kapanış timeout {sym}: pozisyon hâlâ açık — "
            f"tekrar MARKET gönderilmedi"
        )
        return False
    oid_use = str(oid or close_order_id or "")
    from elite_trader.fee_economics import live_close_record_ok

    ok_rec, record_reason, skip_detail = live_close_record_ok(
        exit_reason=exit_reason,
        exchange_settled=settled,
        mode_id="mega",
        on_exchange=True,
    )
    if not ok_rec:
        print(f"  ⛔ MEGA kayıt yok {sym} ({exit_reason}): {skip_detail}")
        return False
    closed = _build_mega_closed_record(
        pos,
        record_reason,
        exchange_settled=settled,
        close_order_id=oid_use or None,
    )
    if 0 <= idx < len(_mega_positions) and _mega_positions[idx].get("id") == pos.get("id"):
        _mega_positions.pop(idx)
    _append_mega_closed_record(closed)
    _maybe_unlock_regime()
    wp = float(closed.get("wallet_pnl") or closed.get("final_pnl") or 0)
    print(
        f"  🔴 MEGA kapanış {sym} {record_reason} "
        f"cüzdan=${wp:.4f} (timeout kurtarıldı)"
    )
    refresh_mega_positions_cache(force=True)
    _wake_mega_rest(force_sync=True)
    return True


def _mega_finalize_flat_exchange_close(
    idx: int,
    pos: dict[str, Any],
    exit_reason: str,
    *,
    mc: Any | None = None,
) -> bool:
    """Borsada pozisyon yok (TP/flat) — hayalet yerel kaydı temizle, userTrades sync."""
    global _mega_positions
    sym = str(pos.get("symbol") or "")
    coin = sym.replace("USDT", "")
    mc = mc or get_mega_client()
    if mc and not mc.paper:
        _cancel_exchange_tp(pos, mc)
        _cancel_exchange_trail_lock(pos, mc)
        _purge_coin_algo_after_close(mc, coin)
    exchange_settled: dict[str, Any] | None = None
    if mc and not mc.paper:
        exchange_settled = _mega_settle_close_from_api(
            pos,
            mc,
            exit_reason=exit_reason,
            close_order_id=pos.get("exchange_close_order_id")
            or pos.get("exchange_tp_order_id"),
        )
    ex_reason = (
        "TP"
        if str(exit_reason).upper()
        in ("TP", "TP-PEAK", "SPIKE-FLASH", "SPIKE-QUICK", "SPIKE-PEAK")
        else str(exit_reason)
    )
    from elite_trader.fee_economics import live_close_record_ok

    ok_rec, record_reason, _ = live_close_record_ok(
        exit_reason=ex_reason,
        exchange_settled=exchange_settled,
        mode_id="mega",
        on_exchange=bool(pos.get("on_exchange") and mc and not mc.paper),
    )
    sim_row = bool(pos.get("sim")) or (
        mega_paper_sim_only() and not pos.get("on_exchange")
    )
    if exchange_settled:
        from elite_trader.exchange_settlement import settlement_has_api_close_fills
        from elite_trader.fee_economics import (
            is_stop_loss_exit,
            settled_exit_record_reason,
        )

        if not ok_rec or not settlement_has_api_close_fills(exchange_settled):
            record_reason = settled_exit_record_reason(
                ex_reason, exchange_settled, mode_id="mega"
            )
            if is_stop_loss_exit(ex_reason) or float(
                exchange_settled.get("wallet_pnl")
                or exchange_settled.get("net_pnl")
                or 0
            ) < -0.005:
                ok_rec = True
        if ok_rec or settlement_has_api_close_fills(exchange_settled):
            closed = _build_mega_closed_record(
                pos,
                record_reason
                if ok_rec
                else settled_exit_record_reason(
                    ex_reason, exchange_settled, mode_id="mega"
                ),
                exchange_settled=exchange_settled,
                close_order_id=str(
                    exchange_settled.get("exchange_close_order_id")
                    or exchange_settled.get("close_order_id")
                    or ""
                )
                or pos.get("exchange_tp_order_id"),
            )
            if is_stop_loss_exit(ex_reason):
                closed["sl_close"] = True
            if sim_row:
                closed["sim"] = True
            if 0 <= idx < len(_mega_positions) and _mega_positions[idx].get("id") == pos.get("id"):
                _mega_positions.pop(idx)
            _append_mega_closed_record(closed)
            _record_mega_close_ledger(closed)
            wp = float(closed.get("wallet_pnl") or closed.get("final_pnl") or 0)
            print(
                f"  🔴 MEGA kapanış {sym} {closed.get('exit_reason')} "
                f"cüzdan=${wp:.4f} (borsa API)"
            )
    elif sim_row:
        closed = _build_mega_closed_record(
            pos,
            str(exit_reason or "FLAT"),
            exchange_settled=None,
            close_order_id="",
        )
        closed["sim"] = True
        from elite_trader.fee_economics import estimate_close_pnl

        gross = float(pos.get("unrealized_pnl") or 0)
        stake = float(pos.get("stake_usd") or 1)
        lev = max(int(pos.get("leverage") or 2), 1)
        est = estimate_close_pnl(gross, stake, lev, pos=pos)
        net = float(est.get("final_pnl") or est.get("net_pnl") or gross)
        closed["final_pnl"] = net
        closed["wallet_pnl"] = net
        if 0 <= idx < len(_mega_positions) and _mega_positions[idx].get("id") == pos.get("id"):
            _mega_positions.pop(idx)
        _append_mega_closed_record(closed)
        _record_mega_close_ledger(closed)
        print(f"  🔴 MEGA SIM kapanış {sym} {exit_reason} net=${net:.4f} (flat)")
    else:
        try:
            from elite_trader.mega_close_sync import (
                sync_priority_coins_from_exchange,
                wake_mega_close_sync,
            )

            sync_priority_coins_from_exchange([coin])
            wake_mega_close_sync(force=True)
        except Exception:
            pass
        if 0 <= idx < len(_mega_positions) and _mega_positions[idx].get("id") == pos.get("id"):
            _mega_positions.pop(idx)
        print(f"  ↻ MEGA yerel hayalet silindi {sym} ({exit_reason}) — borsa flat")
    _persist_open_meta()
    _persist_open_book(force=True)
    _maybe_unlock_regime()
    refresh_mega_positions_cache(force=True)
    _wake_mega_rest(force_sync=True)
    return True


def _mega_equity() -> float:
    wallet = _fetch_wallet()
    bal = _wallet_balance(wallet)
    if bal > 0:
        return bal
    if mega_paper_sim_only():
        return _mega_sim_equity_usd()
    return 0.0


def _mega_open_stake_committed() -> float:
    """Açık pozisyonlara bağlı margin (stake_usd toplamı)."""
    return sum(float(p.get("stake_usd") or 0) for p in _mega_positions)


def _mega_open_margin_committed() -> float:
    """Canlıda borsa positionRisk marjini; yoksa stake_usd."""
    if mega_paper_sim_only() or not mega_live_enabled():
        return _mega_open_stake_committed()
    by_key: dict[tuple[str, str], float] = {}
    for ep in _mega_positions_cache or []:
        sym = str(ep.get("symbol") or "").upper()
        amt = float(ep.get("contracts") or ep.get("positionAmt") or 0)
        side = "LONG" if amt > 0 else "SHORT"
        im = float(
            ep.get("margin_used")
            or ep.get("isolatedMargin")
            or ep.get("positionInitialMargin")
            or 0
        )
        if im <= 0:
            notional = abs(float(ep.get("notional_usd") or 0))
            lev = max(int(ep.get("leverage") or 10), 1)
            if notional > 0:
                im = notional / lev
        if im > 0:
            by_key[(sym, side)] = max(by_key.get((sym, side), 0.0), im)
    if by_key:
        return sum(by_key.values())
    total = 0.0
    for p in _mega_positions:
        im = float(p.get("margin_used") or 0)
        if im > 0:
            total += im
        else:
            total += float(p.get("stake_usd") or 0)
    return total if total > 0 else _mega_open_stake_committed()


def _mega_available_margin() -> float:
    """Önbellekli cüzdan — UDS veya son REST (canlıda anchor fallback yok)."""
    if mega_paper_sim_only():
        return _mega_sim_equity_usd()
    wallet = _fetch_wallet()
    avail = float(
        wallet.get("available_balance")
        or wallet.get("usdt_available")
        or wallet.get("available_net")
        or 0
    )
    if avail > 0:
        return avail
    if mega_live_enabled() and not mega_paper_sim_only():
        return 0.0
    anchor = _load_session_anchor()
    if anchor and anchor > 0:
        return float(anchor)
    return 0.0


def _mega_open_margin_ok(stake_usd: float) -> tuple[bool, str]:
    """Yeterli serbest marjin yoksa açılış denemesi yapma — kapanış bekle."""
    if stake_usd <= 0:
        return False, "stake=0"
    if mega_paper_sim_only():
        return True, ""
    cap = _mega_total_slot_cap()
    open_n = len(_mega_positions)
    if open_n >= cap:
        avail = _mega_available_margin()
        budget = _mega_slot_budget_usd()
        return (
            False,
            f"slot tavanı {open_n}/{cap} (bütçe ${budget:.0f}, kullanılabilir ${avail:.0f})",
        )
    free = _mega_deployable_for_new_stake()
    buf = _mega_open_margin_buffer()
    need = float(stake_usd) + buf
    if free + 0.01 >= need:
        return True, ""
    committed = _mega_open_stake_committed()
    avail = _mega_available_margin()
    return (
        False,
        f"free=${free:.0f} < need=${need:.0f} "
        f"(avail=${avail:.0f} committed=${committed:.0f} cap={cap})",
    )


def _log_mega_margin_wait(reason: str) -> None:
    global _mega_margin_wait_logged_ts
    now = time.time()
    iv = max(30.0, _env_float("MEGA_MARGIN_WAIT_LOG_SEC", 90.0))
    if now - float(_mega_margin_wait_logged_ts or 0) < iv:
        return
    _mega_margin_wait_logged_ts = now
    print(f"  ⏸ MEGA açılış bekliyor: {reason} (serbest marjin / kapanış)")


def _plan_open(signal: dict[str, Any], price: float) -> dict[str, Any] | None:
    from elite_trader import parallel_universe_engine as pe
    from elite_trader.capital_allocator import compute_stake
    from elite_trader.panel_strategy import mode_catalog

    prof = _mega_profile()
    m = mode_catalog().get("mega") or prof
    sym = str(signal.get("symbol") or "")
    side = str(signal.get("type") or "LONG")
    if any(p["symbol"] == sym for p in _mega_positions):
        return None
    try:
        from elite_trader.mega_slot_swap import maybe_swap_for_entry

        maybe_swap_for_entry(
            signal,
            slots_remaining=_mega_slots_remaining(),
            positions=list(_mega_positions),
        )
    except Exception:
        pass
    slot_cap = _mega_open_slot_limit(signal)
    if len(_mega_positions) >= slot_cap:
        return None
    elite_overflow = _mega_elite_overflow_entry(signal)
    ch = float(signal.get("change") or 0)
    strength = str(signal.get("strength") or "Medium")
    from elite_trader.mode_engines.mega_scoring import mega_leverage

    is_flash_signal = bool(
        signal.get("mega_flash_reversal")
        or signal.get("flash_reversal")
        or signal.get("mega_flash_pump")
        or signal.get("flash_pump_reversal")
    )
    is_flash_pump = bool(signal.get("mega_flash_pump") or signal.get("flash_pump_reversal"))

    if is_flash_signal:
        fr_min = max(100.0, _env_float("MEGA_FLASH_REVERSAL_STAKE_MIN_USD", 100.0))
        deploy_new = _mega_deployable_for_new_stake()
        if deploy_new < fr_min:
            _log_mega_margin_wait(
                f"flash marjin yetersiz deploy=${deploy_new:.0f} < ${fr_min:.0f}"
            )
            return None
        if _mega_stake_use_available_margin():
            stake = _mega_stake_for_slot(is_flash=True)
        else:
            avail = _mega_available_margin()
            fr_max = max(fr_min, _env_float("MEGA_FLASH_REVERSAL_STAKE_MAX_USD", 700.0))
            stake = round(min(fr_max, max(fr_min, avail * 0.25)), 2)
        lev = _env_int("MEGA_FLASH_REVERSAL_LEVERAGE", 10)
        if is_flash_pump:
            signal["mega_flash_pump"] = True
        else:
            signal["mega_flash_reversal"] = True
    elif elite_overflow:
        stake = _env_float("MEGA_ELITE_STAKE_USD", 1000.0)
        lev = max(5, min(20, _env_int("MEGA_ELITE_LEVERAGE", 10)))
        signal["mega_elite_entry"] = True
    else:
        fixed_stake = _env_float("MEGA_FIXED_STAKE_USD", 0)
        fixed_lev = _env_int("MEGA_FIXED_LEVERAGE", 0)
        if _mega_stake_use_available_margin():
            stake = _mega_stake_for_slot(is_flash=False)
            lev = int(signal.get("leverage") or mega_leverage(signal, strength, m))
        elif fixed_stake > 0 and fixed_lev > 0:
            stake = fixed_stake
            lev = fixed_lev
        else:
            kelly = pe._kelly_fn(ch, side) if pe._kelly_fn else abs(ch) * 10
            min_s, max_s = pe._stake_bounds_fn() if pe._stake_bounds_fn else (600.0, 1500.0)
            if prof.get("min_stake_usd") is not None:
                min_s = max(min_s, float(prof["min_stake_usd"]))
            if prof.get("max_stake_usd") is not None:
                max_s = float(prof["max_stake_usd"])
            min_s = max(min_s, _env_float("MEGA_MIN_STAKE_USD", min_s))
            max_s = max(min_s, _env_float("MEGA_MAX_STAKE_USD", max_s))
            stake_mult = float(prof.get("stake_mult") or 1.0)
            meta = signal.get("mega_meta") or {}
            stake_mult *= float(meta.get("combined_stake_mult") or 1.0)
            equity = _mega_equity()
            open_stakes = [float(p["stake_usd"]) for p in _mega_positions]
            wr = pe._wr_fn() if pe._wr_fn else None
            active_pct = float(prof.get("active_capital_pct") or 0.55)
            pct_override = (
                1.0
                if _mega_stake_use_available_margin()
                else active_pct
            )
            stake = compute_stake(
                _mega_deployable_for_new_stake() if _mega_stake_use_available_margin() else equity,
                open_stakes,
                kelly_stake=kelly * stake_mult,
                max_open=_mega_effective_max_open(),
                min_stake=min_s,
                max_stake=max_s,
                win_rate=wr,
                active_capital_pct_override=pct_override,
            )
            if _mega_stake_use_available_margin():
                slot_stake = _mega_stake_for_slot(is_flash=False)
                if slot_stake > 0:
                    stake = slot_stake
            lev = int(signal.get("leverage") or mega_leverage(signal, strength, m))
    if stake <= 0:
        return None
    if not is_flash_signal:
        ok_margin, margin_reason = _mega_open_margin_ok(stake)
        if not ok_margin:
            _log_mega_margin_wait(margin_reason)
            return None
    from elite_trader.fee_economics import tp_sl_gross_triggers

    tp_usd, sl_usd, net_tp, rt_fee = tp_sl_gross_triggers(stake, lev, "mega")

    # ── Flash Reversal: TP düşüşün %72'sini geri alma hedefi ────────────────
    if is_flash_signal:
        try:
            from elite_trader.mode_profiles import get_profile as _get_profile

            _prof_fr = _get_profile("mega") or _get_profile("berserk2") or {}
            if is_flash_pump:
                from elite_trader.berserk2_flash_reversal import (
                    flash_pump_reversal_dynamic_exit,
                )

                _fr_exit = flash_pump_reversal_dynamic_exit(
                    signal, _prof_fr, stake_usd=stake, leverage=lev
                )
            else:
                from elite_trader.berserk2_flash_reversal import (
                    flash_reversal_dynamic_exit,
                )

                _fr_exit = flash_reversal_dynamic_exit(
                    signal, _prof_fr, stake_usd=stake, leverage=lev
                )
            _fr_tp_pct = float(_fr_exit.get("tp_stake_pct") or 0)
            if _fr_tp_pct > 0:
                tp_usd = round(stake * _fr_tp_pct, 4)
                from elite_trader.fee_economics import round_trip_fee_usd

                rt_fee = round_trip_fee_usd(stake, lev)
                net_tp = max(0.0, tp_usd - rt_fee)
                signal["mega_flash_tp_usd"] = tp_usd
                signal["mega_flash_tp_pct"] = _fr_tp_pct
        except Exception:
            pass
    # ────────────────────────────────────────────────────────────────────────

    min_close = _mega_min_close_net_usd()
    entry_min = max(min_close, _env_float("MEGA_ENTRY_MIN_NET_USD", min_close))
    if float(net_tp) < entry_min - 0.01:
        return None
    size = stake * lev / price
    if side == "LONG":
        tp_price = price + tp_usd / size if size > 0 else price
        sl_price = price - sl_usd / size if size > 0 else price
    else:
        tp_price = price - tp_usd / size if size > 0 else price
        sl_price = price + sl_usd / size if size > 0 else price
    return {
        "symbol": sym,
        "side": side,
        "entry_price": price,
        "size": size,
        "leverage": lev,
        "stake_usd": stake,
        "tp_target": tp_price,
        "sl_target": sl_price,
        "tp_target_usd": tp_usd,
        "sl_target_usd": sl_usd,
        "tp_net_target_usd": net_tp,
        "round_trip_fee_est_usd": rt_fee,
        "strength": strength,
        "mega_elite_entry": bool(signal.get("mega_elite_entry")),
        "mega_flash_reversal": bool(is_flash_signal and not is_flash_pump),
        "mega_flash_pump": bool(is_flash_pump),
        "mega_coin_star": bool(signal.get("mega_coin_star")),
        "mega_coin_playbook": (signal.get("mega_meta") or {}).get(
            "coin_star_playbook"
        ),
        "mega_coin_open_behavior": (signal.get("mega_meta") or {}).get(
            "coin_open_behavior"
        ),
        "mega_coin_star_alignment": (signal.get("mega_meta") or {}).get(
            "coin_star_alignment"
        ),
    }


def _scan_row(
    signal: dict[str, Any],
    price: float,
    *,
    status: str,
    allowed: bool | None = None,
    reason: str = "",
) -> dict[str, Any]:
    meta = signal.get("mega_meta") or {}
    sym = str(signal.get("symbol") or "")
    side = str(signal.get("type") or "LONG")
    return {
        "ts": time.time(),
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "symbol": sym,
        "side": side,
        "price": float(price or signal.get("price") or 0),
        "change": round(float(signal.get("change") or 0), 4),
        "strength": str(signal.get("strength") or "Medium"),
        "mega_score": meta.get("mega_score"),
        "status": status,
        "allowed": allowed,
        "reason": str(reason or "")[:80],
        "mover_rank": signal.get("berserk2_mover_rank"),
        "vol_tier": signal.get("mega_vol_tier")
        or (signal.get("mega_meta") or {}).get("vol_tier"),
        "vol_rank": signal.get("mega_vol_rank")
        or (signal.get("mega_meta") or {}).get("vol_rank"),
        "market_regime": (signal.get("mega_meta") or {}).get("market_regime"),
    }


def _record_scan(row: dict[str, Any]) -> None:
    with _scan_lock:
        _scan_events.appendleft(row)


def scan_feed(*, limit: int = 40) -> list[dict[str, Any]]:
    with _scan_lock:
        return [dict(r) for r in list(_scan_events)[: max(1, min(limit, 80))]]


def _mega_flash_watch_rows(*, limit: int = 20) -> list[dict[str, Any]]:
    """Flash reversal izleme — vol evreni, açık MEGA sembolleri hariç."""
    if not _env_bool("MEGA_FLASH_REVERSAL_ENABLED", True):
        return []
    try:
        from elite_trader.berserk2_flash_reversal import (
            flash_reversal_enabled,
            flash_reversal_watch_list,
        )
        from elite_trader.mode_profiles import get_profile

        prof = get_profile("mega") or get_profile("berserk2") or {}
        if not flash_reversal_enabled(prof):
            return []
    except Exception:
        return []

    open_syms = {str(p.get("symbol") or "").upper() for p in _mega_positions}
    symbols: list[str] = []
    prices: dict[str, float] = {}
    try:
        from elite_trader.mega_volatility import enabled as vol_on, snapshot as vol_snapshot

        if vol_on():
            for c in vol_snapshot().get("coins") or []:
                sym = str(c.get("symbol") or "")
                if not sym or sym.upper() in open_syms:
                    continue
                symbols.append(sym)
                px = float(c.get("price") or 0)
                if px > 0:
                    prices[sym] = px
    except Exception:
        pass

    price_history: dict[str, list] = {}
    bulk: dict[str, float] = {}
    try:
        import binance_elite_pro as bep

        price_history = bep.price_history
        bulk = bep._bulk_prices_cached_fast() or {}
    except Exception:
        pass

    if not symbols and price_history:
        symbols = [
            s
            for s in price_history.keys()
            if str(s).upper() not in open_syms and len(price_history.get(s) or []) >= 3
        ][:48]

    for sym in symbols:
        if sym not in prices or prices[sym] <= 0:
            prices[sym] = float(
                bulk.get(sym)
                or bulk.get(sym.replace("USDT", ""))
                or 0
            )

    try:
        return flash_reversal_watch_list(
            symbols,
            prices,
            price_history,
            prof,
            exclude_symbols=open_syms,
            limit=limit,
        )
    except Exception:
        return []


def scan_summary_light() -> dict[str, Any]:
    """Light snapshot — bellek içi scan_feed; ağır tarama yok."""
    global _mega_scan_light_cache
    now = time.time()
    ttl = max(0.8, _env_float("MEGA_SCAN_LIGHT_CACHE_SEC", 2.5))
    if _mega_scan_light_cache and (now - _mega_scan_light_cache[0]) < ttl:
        return dict(_mega_scan_light_cache[1])
    feed = scan_feed(limit=30)
    candidates = [r for r in feed if r.get("status") in ("candidate", "opened")]
    rejects = [r for r in feed if r.get("status") == "reject"]
    slot_meta = _mega_scan_slot_meta()
    out: dict[str, Any] = {
        "feed": feed,
        "candidates": candidates[:12],
        "recent_rejects": rejects[:12],
        "reject_total": 0,
        "reject_top": [],
        "scanned_recent": len(feed),
        "candidates_recent": len(candidates),
        "flash_watch": _mega_flash_watch_rows(limit=20),
        **slot_meta,
    }
    try:
        from elite_trader.mode_reject_buffer import summary as reject_summary

        rb = reject_summary("mega")
        out["reject_buffer"] = rb
        out["reject_total"] = int(rb.get("reject_count") or 0)
    except Exception:
        pass
    try:
        from elite_trader.mega_volatility import snapshot as vol_snapshot

        out["volatility"] = vol_snapshot()
    except Exception:
        pass
    try:
        from elite_trader.mega_market_regime import snapshot as regime_snapshot

        out["market_regime"] = regime_snapshot()
    except Exception:
        pass
    try:
        from elite_trader.mega_direction_guard import (
            _price_history,
            btc_context_snapshot,
        )

        mc = get_mega_client()
        out["btc_context"] = btc_context_snapshot(
            _price_history(),
            binance_client=mc if mc and not mc.paper else None,
        )
    except Exception:
        pass
    _mega_scan_light_cache = (now, out)
    return out


def scan_summary(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Tarama özeti — reject buffer + canlı feed."""
    from elite_trader import parallel_universe_engine as pe
    from elite_trader.mode_reject_buffer import summary as reject_summary

    feed = scan_feed(limit=40)
    candidates = [r for r in feed if r.get("status") in ("candidate", "opened")]
    rejects = [r for r in feed if r.get("status") == "reject"]
    pr = (pe.paper_reject_stats().get("mega") or {}) if hasattr(pe, "paper_reject_stats") else {}
    top_reject = sorted(pr.items(), key=lambda x: -x[1])[:5]
    rb = reject_summary("mega")
    slot_meta = _mega_scan_slot_meta()
    out: dict[str, Any] = {
        "feed": feed,
        "candidates": candidates[:16],
        "recent_rejects": rejects[:16],
        "reject_total": sum(pr.values()) if pr else int(rb.get("reject_count") or 0),
        "reject_top": [{"reason": k, "count": v} for k, v in top_reject],
        "reject_buffer": rb,
        "scanned_recent": len(feed),
        "candidates_recent": len(candidates),
        "flash_watch": _mega_flash_watch_rows(limit=20),
        **slot_meta,
    }
    try:
        from elite_trader.mega_volatility import snapshot as vol_snapshot

        out["volatility"] = vol_snapshot()
    except Exception:
        pass
    try:
        from elite_trader.mega_market_regime import snapshot as regime_snapshot

        out["market_regime"] = regime_snapshot()
    except Exception:
        pass
    try:
        from elite_trader.mega_direction_guard import (
            _price_history,
            btc_context_snapshot,
        )

        mc = get_mega_client()
        out["btc_context"] = btc_context_snapshot(
            _price_history(),
            binance_client=mc if mc and not mc.paper else None,
        )
    except Exception:
        pass
    return out


def _mega_live_symbol_ok(sym: str) -> bool:
    """Demo-fapi'de işlem göremeyen sembolleri taramadan önce ele (ICP vb. -1121)."""
    if not sym or not mega_live_orders_enabled():
        return True
    mc = get_mega_client()
    if not mc or mc.paper:
        return True
    coin = sym.replace("USDT", "").upper()
    return mc.symbol_tradable(coin)


def process_scan_candidate(signal: dict[str, Any], price: float) -> bool:
    """Berserk2 taramasından gelen aday — MEGA kapısı + kayıt + açılış."""
    if not mega_motor_active() or price <= 0:
        return False
    sig = dict(signal)
    try:
        from elite_trader.btc_liq_feed import liquidation_proxy

        sig["liquidation_proxy"] = liquidation_proxy()
    except Exception:
        pass
    sym = str(sig.get("symbol") or "")
    if not _mega_live_symbol_ok(sym):
        _record_scan(
            _scan_row(
                sig,
                price,
                status="skip",
                allowed=False,
                reason="demo_invalid_symbol",
            )
        )
        return False
    side = str(sig.get("type") or "LONG")
    dedupe_key = f"{sym}:{side}"
    now = time.time()
    if now - float(_scan_seen.get(dedupe_key) or 0) < 2.5:
        return False
    _scan_seen[dedupe_key] = now
    if len(_scan_seen) > 200:
        stale = [k for k, t in _scan_seen.items() if now - t > 120]
        for k in stale:
            _scan_seen.pop(k, None)

    _record_scan(_scan_row(sig, price, status="scan", allowed=None))

    try:
        from elite_trader.mega_boot_observe import boot_observe_active

        if boot_observe_active():
            _record_scan(
                _scan_row(
                    sig,
                    price,
                    status="reject",
                    allowed=False,
                    reason="mega_boot_observe",
                )
            )
            return False
    except Exception:
        pass

    is_flash = bool(
        sig.get("mega_flash_reversal")
        or sig.get("flash_reversal")
        or sig.get("mega_flash_pump")
        or sig.get("flash_pump_reversal")
    )
    try:
        from elite_trader.mega_direction_guard import mega_entry_allowed

        ok_dir, dir_reason = mega_entry_allowed(sig)
        if not ok_dir:
            _record_scan(
                _scan_row(sig, price, status="reject", allowed=False, reason=dir_reason)
            )
            return False
    except Exception:
        pass
    try:
        from elite_trader.mega_system_score import mega_system_entry_allowed

        ok_sys, sys_reason, sys_score = mega_system_entry_allowed(sig)
        if not ok_sys:
            _record_scan(
                _scan_row(
                    sig,
                    price,
                    status="reject",
                    allowed=False,
                    reason=sys_reason or "system_score_block",
                )
            )
            return False
        if sys_reason and sys_score:
            sig["mega_system_score"] = sys_score
    except Exception:
        pass
    if is_flash:
        if len(_mega_positions) >= _mega_open_slot_limit(sig):
            _record_scan(
                _scan_row(sig, price, status="skip", allowed=False, reason="flash_slots_full")
            )
            return False
        _record_scan(
            _scan_row(sig, price, status="candidate", allowed=True, reason="flash_gate_skip")
        )
    else:
        from elite_trader import parallel_universe_engine as pe

        ok, reason = pe.entry_gate_for_mode("mega", sig)
        if not ok:
            _record_scan(_scan_row(sig, price, status="reject", allowed=False, reason=reason))
            return False
        _record_scan(_scan_row(sig, price, status="candidate", allowed=True, reason="gate_ok"))
    opened = try_open_from_signal(sig, price, skip_gate=True)
    if opened:
        reason_open = "mega_sim" if mega_paper_sim_only() else "live_order"
        _record_scan(
            _scan_row(sig, price, status="opened", allowed=True, reason=reason_open)
        )
    else:
        skip_reason = "plan_or_slots"
        if is_flash:
            if not _mega_extra_slot_balance_ok():
                skip_reason = "flash_margin"
            elif len(_mega_positions) >= _mega_effective_max_open():
                skip_reason = "wallet_slots_full"
            elif any(
                str(p.get("symbol") or "").upper() == sym.upper() for p in _mega_positions
            ):
                skip_reason = "flash_symbol_open"
            else:
                skip_reason = "flash_plan_fail"
        elif mega_paper_sim_only() and len(_mega_positions) >= _mega_effective_max_open():
            skip_reason = "max_open"
        _record_scan(
            _scan_row(sig, price, status="skip", allowed=True, reason=skip_reason)
        )
    return opened


def try_open_from_signal(
    signal: dict[str, Any], price: float, *, skip_gate: bool = False
) -> bool:
    """MEGA giriş — canlı emir veya paper sim."""
    if not mega_motor_active() or price <= 0:
        return False
    try:
        from elite_trader.mega_boot_observe import boot_observe_active

        if boot_observe_active():
            return False
    except Exception:
        pass
    try:
        from elite_trader.mega_control import allow_new_entries

        if not allow_new_entries():
            return False
    except Exception:
        pass
    if mega_sim_enabled() and not mega_live_orders_enabled():
        return _try_open_sim_from_signal(signal, price, skip_gate=skip_gate)
    if not mega_live_enabled():
        return False
    mc = get_mega_client()
    if not mc or mc.paper:
        return False
    from elite_trader import parallel_universe_engine as pe

    sig = dict(signal)
    is_flash = bool(
        sig.get("mega_flash_reversal")
        or sig.get("flash_reversal")
        or sig.get("mega_flash_pump")
        or sig.get("flash_pump_reversal")
    )
    if not skip_gate and not is_flash:
        ok, reason = pe.entry_gate_for_mode("mega", sig)
        if not ok:
            return False
    elif not skip_gate and is_flash:
        # Flash sinyal — yalnızca slot ve marjin kontrolü, skor kapısı atla
        if len(_mega_positions) >= _mega_open_slot_limit(sig):
            return False
    plan = _plan_open(sig, price)
    if not plan:
        return False
    sym = plan["symbol"]
    side = plan["side"]
    coin = sym.replace("USDT", "")
    lev = int(plan["leverage"])
    pos: dict[str, Any] | None = None
    with _mega_open_lock:
        cache_age = _mega_positions_list_age_sec()
        refresh_mega_positions_cache(
            force=cache_age > max(8.0, _mega_position_risk_min_interval_sec(has_open=True)),
            skip_wallet=True,
        )
        ex_any = _exchange_any_for_symbol(sym)
        if ex_any:
            ex_side = str(ex_any.get("side") or "LONG").upper()
            req_side = str(side).upper()
            if ex_side != req_side:
                # Ters yön — flip önlemi
                print(
                    f"  🚫 MEGA açılış engellendi {sym} {req_side} — "
                    f"borsada {ex_side} açık (flip/zarar önlemi)"
                )
            # Her halükarda aynı sembolde ikinci pozisyon açma
            return False
        if _exchange_row(sym, side):
            return False
        if len(_mega_positions) >= _mega_open_slot_limit(sig):
            return False
        if not mc.symbol_tradable(coin):
            print(
                f"  🚫 MEGA açılış {sym}: sembol bu demo/canlı API listesinde yok "
                f"(exchangeInfo — ICP vb. demo'da olmayabilir)"
            )
            return False
        mc.ensure_margin_type(coin)
        mc.ensure_leverage(coin, lev)
        qty = mc.round_qty(coin, plan["size"], for_market=True)
        if qty <= 0:
            return False
        try:
            order = mc.market_order(coin, side, qty, reduce_only=False)
        except Exception as exc:
            print(f"  ⛔ MEGA açılış {sym}: {exc}")
            return False
        global _mega_position_id
        entry_ts, entry_str, opened_iso = _mega_entry_fields_from_ts(time.time())
        order_times = _mega_entry_fields_from_order(order)
        if order_times:
            entry_ts, entry_str, opened_iso = order_times
        pos = {
            "id": _mega_position_id,
            "symbol": sym,
            "side": side,
            "entry_price": float(plan["entry_price"]),
            "current_price": float(plan["entry_price"]),
            "size": qty,
            "leverage": lev,
            "stake_usd": float(plan["stake_usd"]),
            "position_value": qty * float(plan["entry_price"]),
            "unrealized_pnl": 0.0,
            "pnl_pct": 0.0,
            "entry_time": entry_ts,
            "entry_time_str": entry_str,
            "opened_at_iso": opened_iso,
            "tp_target": plan["tp_target"],
            "sl_target": plan["sl_target"],
            "tp_target_usd": plan["tp_target_usd"],
            "sl_target_usd": plan["sl_target_usd"],
            "tp_net_target_usd": plan["tp_net_target_usd"],
            "round_trip_fee_est_usd": plan["round_trip_fee_est_usd"],
            "on_exchange": True,
            "panel_mode": "mega",
            "execution_mode_at_open": "mega",
            "signal_strength": plan["strength"],
            "signal_source": (
                "MEGA-FLASH"
                if plan.get("mega_flash_reversal")
                else ("MEGA-ELITE" if plan.get("mega_elite_entry") else "MEGA-LIVE")
            ),
            "mega_elite_entry": bool(plan.get("mega_elite_entry")),
            "mega_flash_reversal": bool(plan.get("mega_flash_reversal")),
            "mega_coin_star": bool(plan.get("mega_coin_star")),
            "mega_coin_playbook": plan.get("mega_coin_playbook"),
            "mega_coin_open_behavior": plan.get("mega_coin_open_behavior"),
            "mega_coin_star_alignment": plan.get("mega_coin_star_alignment"),
            "order_id": str(order.get("orderId") or ""),
            "min_unreal_seen": 0.0,
            "max_unreal_seen": 0.0,
            "price_history": [float(plan["entry_price"])],
            "time_history": [opened_iso],
            "entry_time_locked": True,
        }
        try:
            from elite_trader.mega_system_context import attach_entry_context

            attach_entry_context(pos, signal=sig)
        except Exception:
            pass
        _mega_position_id += 1
        _mega_positions.append(pos)
        if plan.get("mega_flash_reversal"):
            print(
                f"  ⚡ MEGA FLASH {sym} {side} stake=${plan['stake_usd']:.0f} "
                f"lev={lev}x (ek slot)"
            )
        elif plan.get("mega_elite_entry"):
            print(
                f"  🟣 MEGA ELİTE {sym} {side} stake=${plan['stake_usd']:.0f} "
                f"lev={lev}x (slot overflow)"
            )
        else:
            print(
                f"  🟢 MEGA CANLI {sym} {side} stake=${plan['stake_usd']:.0f} "
                f"lev={lev}x qty={qty}"
            )
        try:
            from elite_trader.mega_market_regime import record_open

            record_open(
                symbol=sym,
                side=side,
                open_count=len(_mega_positions),
                max_open=_mega_max_open(),
            )
        except Exception:
            pass
    if not pos:
        return False
    pruned = _prune_coin_algo_orders(mc, coin)
    if pruned:
        print(f"  🧹 MEGA giriş öncesi {sym}: {pruned} algo iptal")
    _arm_exchange_tp(pos, mc)
    refresh_mega_positions_cache(force=True, skip_wallet=True)
    _mega_apply_open_time_from_order(pos, mc, order)
    _wake_mega_rest(force_sync=False)
    _record_mega_open_ledger(pos)
    _persist_open_meta()
    _persist_open_book(force=True)
    try:
        from elite_trader.telegram_notify import notify_position_opened

        notify_position_opened(pos)
    except Exception:
        pass
    return True


def _try_open_sim_from_signal(
    signal: dict[str, Any], price: float, *, skip_gate: bool = False
) -> bool:
    """Paper sim — gerçek fiyat, kitaba yaz, borsa emri yok."""
    from elite_trader import parallel_universe_engine as pe

    sig = dict(signal)
    if not skip_gate:
        ok, _reason = pe.entry_gate_for_mode("mega", sig)
        if not ok:
            return False
    plan = _plan_open(sig, price)
    if not plan:
        return False
    sym = plan["symbol"]
    side = plan["side"]
    lev = int(plan["leverage"])
    qty = float(plan["size"])
    if qty <= 0:
        qty = (float(plan["stake_usd"]) * lev) / max(float(plan["entry_price"]), 1e-9)
    global _mega_position_id
    with _mega_open_lock:
        if len(_mega_positions) >= _mega_open_slot_limit(sig):
            return False
        for p in _mega_positions:
            if str(p.get("symbol")) == sym and str(p.get("side")) == side:
                return False
        opened_iso = datetime.now(timezone.utc).isoformat()
        pos = {
            "id": _mega_position_id,
            "symbol": sym,
            "side": side,
            "entry_price": float(plan["entry_price"]),
            "current_price": float(plan["entry_price"]),
            "size": qty,
            "leverage": lev,
            "stake_usd": float(plan["stake_usd"]),
            "position_value": qty * float(plan["entry_price"]),
            "unrealized_pnl": 0.0,
            "pnl_pct": 0.0,
            "entry_time": time.time(),
            "entry_time_str": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "opened_at_iso": opened_iso,
            "tp_target": plan["tp_target"],
            "sl_target": plan["sl_target"],
            "tp_target_usd": plan["tp_target_usd"],
            "sl_target_usd": plan["sl_target_usd"],
            "tp_net_target_usd": plan["tp_net_target_usd"],
            "round_trip_fee_est_usd": plan["round_trip_fee_est_usd"],
            "on_exchange": False,
            "sim": True,
            "panel_mode": "mega",
            "execution_mode_at_open": "mega",
            "signal_strength": plan["strength"],
            "signal_source": "MEGA-SIM",
            "mega_elite_entry": bool(plan.get("mega_elite_entry")),
            "mega_coin_star": bool(plan.get("mega_coin_star")),
            "mega_coin_playbook": plan.get("mega_coin_playbook"),
            "mega_coin_open_behavior": plan.get("mega_coin_open_behavior"),
            "mega_coin_star_alignment": plan.get("mega_coin_star_alignment"),
            "order_id": "",
            "min_unreal_seen": 0.0,
            "max_unreal_seen": 0.0,
            "price_history": [float(plan["entry_price"])],
            "time_history": [opened_iso],
        }
        try:
            from elite_trader.mega_system_context import attach_entry_context

            attach_entry_context(pos, signal=sig)
        except Exception:
            pass
        _mega_position_id += 1
        _mega_positions.append(pos)
        print(
            f"  🔵 MEGA SIM {sym} {side} stake=${plan['stake_usd']:.0f} lev={lev}x"
        )
        _record_mega_open_ledger(pos)
        try:
            from elite_trader.telegram_notify import notify_position_opened

            notify_position_opened(pos)
        except Exception:
            pass
    _persist_open_meta()
    return True


def _close_mega_sim_position(
    pos: dict[str, Any], idx: int, exit_reason: str
) -> bool:
    """Sim pozisyon kapat — kitaptan sil, realize et."""
    global _mega_positions
    from elite_trader.fee_economics import estimate_close_pnl

    sym = pos["symbol"]
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 2), 1)
    gross = float(pos.get("unrealized_pnl") or 0)
    est = estimate_close_pnl(gross, stake, lev, pos=pos)
    net = float(est.get("final_pnl") or est.get("net_pnl") or gross)
    closed = _build_mega_closed_record(
        pos,
        exit_reason,
        exchange_settled=None,
        close_order_id="",
    )
    closed["sim"] = True
    closed["final_pnl"] = net
    closed["wallet_pnl"] = net
    if 0 <= idx < len(_mega_positions) and _mega_positions[idx].get("id") == pos.get("id"):
        _mega_positions.pop(idx)
    _append_mega_closed_record(closed)
    _record_mega_close_ledger(closed)
    _maybe_unlock_regime()
    _persist_open_meta()
    print(f"  🔴 MEGA SIM kapanış {sym} {exit_reason} net=${net:.4f}")
    return True


def _sync_pos_from_exchange(
    pos: dict[str, Any],
    exch: list[dict[str, Any]],
    *,
    mode_id: str = "mega",
) -> None:
    """Canlı pozisyon — giriş/mark/uPnL yalnızca Binance positionRisk."""
    from elite_trader.exchange_position_sync import (
        apply_exchange_snapshot,
        exchange_map_by_symbol_side,
    )

    sym = str(pos.get("symbol") or "").upper()
    side = str(pos.get("side") or "LONG").upper()
    ep = exchange_map_by_symbol_side(exch).get((sym, side))
    if ep:
        apply_exchange_snapshot(pos, ep, mode_id)
        if not _mega_panel_exchange_only():
            _mega_refresh_unreal_from_mark(
                pos,
                mark_px=float(pos.get("current_price") or pos.get("mark_price") or 0),
            )
        return
    _apply_cache_unreal(pos, exch)
    if not _mega_panel_exchange_only():
        _mega_refresh_unreal_from_mark(pos)


def _apply_price_tick(pos: dict[str, Any], bulk: dict[str, float]) -> None:
    if pos.get("on_exchange"):
        # WS last ≠ mark; canlı uPnL ve çıkış kararları positionRisk ile hizalanır.
        return
    coin = pos["symbol"].replace("USDT", "")
    px = bulk.get(coin) or bulk.get(pos["symbol"])
    if not px or px <= 0:
        return
    entry = float(pos["entry_price"])
    size = float(pos["size"])
    side = pos["side"]
    if side == "LONG":
        unreal = (px - entry) * size
    else:
        unreal = (entry - px) * size
    pos["current_price"] = px
    pos["unrealized_pnl"] = unreal
    pos["pnl_pct"] = (unreal / max(float(pos["stake_usd"]), 1)) * 100
    pos["max_unreal_seen"] = max(float(pos.get("max_unreal_seen", unreal)), unreal)
    pos["min_unreal_seen"] = min(float(pos.get("min_unreal_seen", unreal)), unreal)
    hist = pos.setdefault("price_history", [entry])
    times = pos.setdefault(
        "time_history",
        [pos.get("opened_at_iso") or datetime.now(timezone.utc).isoformat()],
    )
    if not hist or abs(float(hist[-1]) - px) > 1e-12:
        hist.append(px)
        times.append(datetime.now(timezone.utc).isoformat())
        if len(hist) > 160:
            pos["price_history"] = hist[-160:]
            pos["time_history"] = times[-160:]


def close_mega_position(position_id: int, exit_reason: str = "Manual") -> bool:
    global _mega_positions, _mega_closed
    if position_id in _mega_closing:
        return False
    for i, pos in enumerate(_mega_positions):
        if pos["id"] != position_id:
            continue
        if pos.get("sim") or (mega_sim_enabled() and not pos.get("on_exchange")):
            _mega_closing.add(position_id)
            try:
                return _close_mega_sim_position(pos, i, exit_reason)
            finally:
                _mega_closing.discard(position_id)
        break
    mc = get_mega_client()
    if not mc:
        return False
    for i, pos in enumerate(_mega_positions):
        if pos["id"] != position_id:
            continue
        _mega_closing.add(position_id)
        try:
            sym = pos["symbol"]
            side = pos["side"]
            coin = sym.replace("USDT", "")
            if not mc.paper and pos.get("on_exchange"):
                cache_age = time.time() - float(_mega_cache_ts or 0)
                cache_max = max(
                    0.10, _env_float("MEGA_CLOSE_CACHE_MAX_SEC", 0.18)
                )
                if cache_age >= cache_max:
                    refresh_mega_positions_cache(force=True, skip_wallet=True)
                exch_snap = list(_mega_positions_cache)
                _sync_pos_from_exchange(pos, exch_snap, mode_id="mega")
            from elite_trader.fee_economics import (
                allow_position_close,
                exit_tp_only,
                is_profit_tp_exit,
                is_stop_loss_exit,
                report_exit_gate_block,
            )
            from elite_trader.mega_live import mega_sl_exit_disabled

            ex_mid = "mega"
            gross = _mega_api_gross_unreal(pos)
            pos["unrealized_pnl"] = gross
            _mega_arm_demo_fast_close(pos, mc)
            r_upper = str(exit_reason).upper()
            sl_ok = is_stop_loss_exit(exit_reason) and not mega_sl_exit_disabled()
            uw_ok = (
                r_upper == "TIME-STOP" and mega_underwater_cut_enabled()
            )
            star_sl_ok = r_upper.startswith("SL-COIN25") or r_upper.startswith(
                "SWAP-FREE-SLOT"
            )
            if exit_tp_only(ex_mid) and not (
                is_profit_tp_exit(exit_reason)
                or sl_ok
                or star_sl_ok
                or uw_ok
                or r_upper in ("MODE-RESET", "MANUAL", "MANUAL CLOSE")
            ):
                report_exit_gate_block(
                    kind="blocked_non_tp",
                    symbol=sym,
                    reason=exit_reason,
                    detail=f"API uPnL=${gross:.4f}",
                )
                return False
            if is_profit_tp_exit(exit_reason):
                wallet_net = _mega_api_wallet_net(pos, mc=mc, gross=gross)
                stake_g = float(pos.get("stake_usd") or 1)
                lev_g = max(int(pos.get("leverage") or 2), 1)
                if _mega_is_spike_exit(exit_reason):
                    if not _mega_spike_exit_net_ok(
                        pos, gross, wallet_net, stake=stake_g, lev=lev_g, mc=mc
                    ):
                        spike_floor = _mega_spike_min_close_net_usd()
                        max_net = float(pos.get("max_net_seen") or 0)
                        report_exit_gate_block(
                            kind="blocked_spike_premature",
                            symbol=sym,
                            reason=exit_reason,
                            detail=(
                                f"API brüt ${gross:.2f} → net ${wallet_net:.2f} "
                                f"tepe net ${max_net:.2f} < spike min ${spike_floor:.2f}"
                            ),
                        )
                        _audit_mega_close(
                            "close_blocked",
                            position_id=position_id,
                            symbol=sym,
                            exit_reason=exit_reason,
                            detail=(
                                f"spike net ${wallet_net:.2f} tepe ${max_net:.2f} "
                                f"< ${spike_floor:.2f}"
                            ),
                        )
                        return False
                else:
                    min_net = _mega_min_close_net_usd()
                    if wallet_net < min_net:
                        report_exit_gate_block(
                            kind="blocked_net_negative",
                            symbol=sym,
                            reason=exit_reason,
                            detail=(
                                f"API uPnL ${gross:.2f} → tahmini cüzdan net ${wallet_net:.2f} "
                                f"< min ${min_net:.2f}"
                            ),
                        )
                        return False
            if is_profit_tp_exit(exit_reason) and gross <= 0:
                report_exit_gate_block(
                    kind="blocked_net_negative",
                    symbol=sym,
                    reason=exit_reason,
                    detail=f"mark uPnL ${gross:.4f} ≤ 0 — kapanış yok",
                )
                return False
            if is_profit_tp_exit(exit_reason):
                pos["tp_fast_close"] = True
                if _mega_is_spike_exit(exit_reason):
                    pos["mark_spike_close"] = True
            if is_profit_tp_exit(exit_reason) and not _mega_profit_seen_ok(
                pos, exit_reason=exit_reason, mc=mc
            ):
                stake_g = float(pos.get("stake_usd") or 1)
                lev_g = max(int(pos.get("leverage") or 2), 1)
                min_net = (
                    _mega_spike_min_close_net_usd()
                    if _mega_is_spike_exit(exit_reason)
                    else _mega_min_close_net_usd()
                )
                max_net = float(pos.get("max_net_seen") or 0)
                cur_net = _mega_estimated_wallet_net(
                    pos, gross, stake=stake_g, lev=lev_g, mc=mc
                )
                if _mega_is_spike_exit(exit_reason):
                    max_u = float(pos.get("max_unreal_seen") or 0)
                    unreal_u = float(pos.get("unrealized_pnl") or gross or 0)
                    peak_need = max_u * _mega_spike_peak_frac()
                    if (
                        max_u > 0
                        and unreal_u < peak_need
                        and not _mega_spike_close_ready(
                            pos,
                            stake=stake_g,
                            lev=lev_g,
                            mc=mc,
                        )
                    ):
                        detail = (
                            f"tepe geri çekildi uPnL=${unreal_u:.2f} "
                            f"< tepe×{_mega_spike_peak_frac():.2f} (${peak_need:.2f})"
                        )
                    else:
                        detail = (
                            f"spike hazır değil net=${cur_net:.2f} "
                            f"(tepe net ${max_net:.2f}, min ${_mega_spike_min_close_net_usd():.2f})"
                        )
                else:
                    detail = (
                        f"tepe net ${max_net:.2f} < min ${min_net:.2f} (cüzdan)"
                    )
                report_exit_gate_block(
                    kind="blocked_spike_premature",
                    symbol=sym,
                    reason=exit_reason,
                    detail=detail,
                )
                _audit_mega_close(
                    "close_blocked",
                    position_id=position_id,
                    symbol=sym,
                    exit_reason=exit_reason,
                    detail=detail,
                )
                return False
            mark_spike = bool(pos.get("mark_spike_close")) or (
                str(exit_reason).upper() == "SPIKE-FLASH"
                and _mega_spike_close_ready(
                    pos,
                    stake=float(pos.get("stake_usd") or 1),
                    lev=max(int(pos.get("leverage") or 2), 1),
                    mc=mc,
                )
            )
            if mark_spike:
                pos["tp_fast_close"] = True
            if not allow_position_close(
                gross_unreal=gross,
                stake_usd=float(pos.get("stake_usd") or 1),
                leverage=max(int(pos.get("leverage") or 2), 1),
                exit_reason=exit_reason,
                mode_id=ex_mid,
                pos=pos,
                client=mc,
            ):
                from elite_trader.fee_economics import tp_sl_gross_triggers

                tp_g, _, _, _ = tp_sl_gross_triggers(
                    float(pos.get("stake_usd") or 1),
                    max(int(pos.get("leverage") or 2), 1),
                    ex_mid,
                )
                detail = f"uPnL=${gross:.4f} tp_brüt=${tp_g:.4f}"
                print(f"  🚫 MEGA kapanış engellendi {sym} {exit_reason} {detail}")
                _audit_mega_close(
                    "close_blocked",
                    position_id=position_id,
                    symbol=sym,
                    side=side,
                    exit_reason=exit_reason,
                    detail=detail,
                )
                return False
            from elite_trader.panel_strategy import position_age_seconds

            _audit_mega_close(
                "close_attempt",
                position_id=position_id,
                symbol=sym,
                side=side,
                exit_reason=exit_reason,
                stake_usd=float(pos.get("stake_usd") or 0),
                leverage=int(pos.get("leverage") or 0),
                entry_price=float(pos.get("entry_price") or 0),
                api_gross=gross,
                age_sec=round(position_age_seconds(pos), 2),
                open_order_id=str(pos.get("order_id") or pos.get("exchange_order_id") or ""),
                system_context=_mega_system_context_for_audit(
                    "close_attempt", pos, exit_reason=exit_reason
                ),
            )
            if not mc.paper and pos.get("on_exchange") and is_profit_tp_exit(exit_reason):
                ok_send, send_detail = _mega_live_profit_send_ok(pos, exit_reason, mc)
                if not ok_send:
                    kind = (
                        "blocked_upnl_mismatch"
                        if "fill" in send_detail.lower()
                        or "slippage" in send_detail.lower()
                        or "mark" in send_detail.lower()
                        else "blocked_spike_premature"
                    )
                    report_exit_gate_block(
                        kind=kind,
                        symbol=sym,
                        reason=exit_reason,
                        detail=send_detail,
                    )
                    _audit_mega_close(
                        "close_blocked",
                        position_id=position_id,
                        symbol=sym,
                        exit_reason=exit_reason,
                        detail=send_detail[:240],
                    )
                    return False
                gross = float(
                    pos.get("exchange_unrealized_pnl")
                    or pos.get("unrealized_pnl")
                    or pos.get("pre_send_gross")
                    or 0
                )
                pos["unrealized_pnl"] = gross
                if gross <= 0:
                    report_exit_gate_block(
                        kind="blocked_net_negative",
                        symbol=sym,
                        reason=exit_reason,
                        detail=f"doğrulama sonrası uPnL ${gross:.4f} ≤ 0",
                    )
                    return False
            if not mc.paper and pos.get("on_exchange") and not _exchange_row(sym, side):
                exit_reason = (
                    "TP"
                    if str(exit_reason).upper() in ("TP", "TP-PEAK", "SPIKE-FLASH")
                    else str(exit_reason)
                )
                exchange_settled: dict[str, Any] | None = None
                exchange_settled = _mega_settle_close_from_api(
                    pos,
                    mc,
                    exit_reason=exit_reason,
                    close_order_id=pos.get("exchange_close_order_id")
                    or pos.get("exchange_tp_order_id"),
                )
                from elite_trader.fee_economics import live_close_record_ok

                ok_rec, record_reason, skip_detail = live_close_record_ok(
                    exit_reason=exit_reason,
                    exchange_settled=exchange_settled,
                    mode_id=ex_mid,
                    on_exchange=True,
                )
                if ok_rec:
                    closed = _build_mega_closed_record(
                        pos,
                        record_reason,
                        exchange_settled=exchange_settled,
                        close_order_id=(
                            str(exchange_settled.get("close_order_id") or "")
                            if exchange_settled
                            else pos.get("exchange_tp_order_id")
                        ),
                    )
                    _mega_positions.pop(i)
                    _append_mega_closed_record(closed)
                    _maybe_unlock_regime()
                    wp = float(closed.get("wallet_pnl") or closed.get("final_pnl") or 0)
                    gross = float(closed.get("pnl_usd") or closed.get("pnl_gross_usd") or 0)
                    print(
                        f"  🔴 MEGA kapanış {sym} {record_reason} "
                        f"brüt=${gross:.4f} cüzdan=${wp:.4f} (borsa TP)"
                    )
                    refresh_mega_positions_cache(force=True)
                    return True
                return _mega_finalize_flat_exchange_close(i, pos, exit_reason, mc=mc)
            if not mc.paper and pos.get("on_exchange"):
                refresh_mega_positions_cache(force=True)
                if not _exchange_row(sym, side):
                    return _mega_finalize_flat_exchange_close(i, pos, exit_reason, mc=mc)
            close_order_id: str | None = None
            if not mc.paper:
                close_side = "SHORT" if side == "LONG" else "LONG"
                ep = _exchange_row(sym, side)
                qty_src = float(ep.get("contracts") or pos["size"]) if ep else float(pos["size"])
                qty = mc.round_qty(coin, qty_src, for_market=True)
                ok_fill, fill_detail = _mega_fast_fill_before_send(
                    pos, exit_reason, mc
                )
                if not ok_fill:
                    report_exit_gate_block(
                        kind="blocked_upnl_mismatch",
                        symbol=sym,
                        reason=exit_reason,
                        detail=fill_detail,
                    )
                    _audit_mega_close(
                        "close_blocked",
                        position_id=position_id,
                        symbol=sym,
                        exit_reason=exit_reason,
                        detail=fill_detail[:240],
                    )
                    return False
                _audit_mega_close(
                    "close_pre_send_ok",
                    position_id=position_id,
                    symbol=sym,
                    exit_reason=exit_reason,
                    pre_send_gross=float(pos.get("pre_send_gross") or 0),
                    pre_send_net=float(pos.get("pre_send_net") or 0),
                    close_side=close_side,
                    qty=qty,
                    system_context=_mega_system_context_for_audit(
                        "close_attempt", pos, exit_reason=exit_reason
                    ),
                )
                if qty > 0:
                    _cancel_exchange_tp(pos, mc)
                    _cancel_exchange_trail_lock(pos, mc)
                    try:
                        order, send_err = _mega_send_profit_close_order(
                            mc,
                            coin,
                            pos,
                            close_side,
                            qty,
                            exit_reason=exit_reason,
                        )
                        if not order:
                            report_exit_gate_block(
                                kind="blocked_upnl_mismatch",
                                symbol=sym,
                                reason=exit_reason,
                                detail=send_err or "kapanış emri gönderilmedi",
                            )
                            _audit_mega_close(
                                "close_blocked",
                                position_id=position_id,
                                symbol=sym,
                                exit_reason=exit_reason,
                                detail=(send_err or "no_order")[:240],
                            )
                            return False
                    except Exception as exc:
                        if _mega_is_reduce_only_rejected(exc):
                            return _mega_finalize_flat_exchange_close(
                                i, pos, exit_reason, mc=mc
                            )
                        if _mega_is_order_timeout(exc):
                            return _mega_recover_close_after_timeout(
                                i,
                                pos,
                                exit_reason,
                                mc=mc,
                                close_order_id=pos.get("exchange_close_order_id"),
                            )
                        raise
                    close_order_id = str(order.get("orderId") or order.get("order_id") or "")
                    pos["exchange_close_order_id"] = close_order_id
                    _audit_mega_close(
                        "close_order_sent",
                        position_id=position_id,
                        symbol=sym,
                        close_order_id=close_order_id,
                        close_side=close_side,
                        qty=qty,
                        order_status=order.get("status"),
                        detail=str(order.get("_close_exec_mode") or "market"),
                    )
            _cancel_exchange_tp(pos, mc)
            _cancel_exchange_trail_lock(pos, mc)
            if not mc.paper:
                _purge_coin_algo_after_close(mc, coin)

            exchange_settled: dict[str, Any] | None = None
            close_exec = dict(pos.get("close_signal") or {})
            if not mc.paper and pos.get("on_exchange"):
                exchange_settled = _mega_settle_close_from_api(
                    pos,
                    mc,
                    exit_reason=exit_reason,
                    close_order_id=close_order_id,
                )

            if exchange_settled:
                _audit_mega_close(
                    "close_settled",
                    position_id=position_id,
                    symbol=sym,
                    exit_reason=exit_reason,
                    close_order_id=close_order_id,
                    settlement=exchange_settled,
                )

            from elite_trader.fee_economics import live_close_record_ok

            ok_rec, record_reason, skip_detail = live_close_record_ok(
                exit_reason=exit_reason,
                exchange_settled=exchange_settled,
                mode_id=ex_mid,
                on_exchange=bool(pos.get("on_exchange") and not mc.paper),
            )
            if not ok_rec:
                from elite_trader.fee_economics import (
                    is_stop_loss_exit,
                    settled_exit_record_reason,
                )

                force_sl = is_stop_loss_exit(exit_reason)
                if force_sl:
                    record_reason = (
                        settled_exit_record_reason(
                            exit_reason, exchange_settled, mode_id=ex_mid
                        )
                        if exchange_settled
                        else str(exit_reason or "SL")
                    )
                    closed = _build_mega_closed_record(
                        pos,
                        record_reason,
                        exchange_settled=exchange_settled,
                        close_order_id=close_order_id,
                        close_exec=close_exec,
                    )
                    closed["sl_close"] = True
                    if 0 <= i < len(_mega_positions) and _mega_positions[i].get("id") == pos.get("id"):
                        _mega_positions.pop(i)
                    _append_mega_closed_record(closed)
                    _record_mega_close_ledger(closed)
                    _persist_open_meta()
                    _maybe_unlock_regime()
                    wp = float(closed.get("wallet_pnl") or closed.get("final_pnl") or 0)
                    print(
                        f"  🔴 MEGA SL kapanış {sym} {record_reason} "
                        f"cüzdan=${wp:.4f} (kayıt zorunlu)"
                    )
                    refresh_mega_positions_cache(force=True)
                    return True
                print(f"  ⛔ MEGA kayıt yok {sym} ({exit_reason}): {skip_detail}")
                _audit_mega_close(
                    "close_record_skipped",
                    position_id=position_id,
                    symbol=sym,
                    exit_reason=exit_reason,
                    detail=skip_detail,
                    settlement=exchange_settled,
                    close_order_id=close_order_id,
                )
                if 0 <= i < len(_mega_positions) and _mega_positions[i].get("id") == pos.get("id"):
                    _mega_positions.pop(i)
                _persist_open_meta()
                refresh_mega_positions_cache(force=True)
                return True
            closed = _build_mega_closed_record(
                pos,
                record_reason,
                exchange_settled=exchange_settled,
                close_order_id=close_order_id,
                close_exec=close_exec,
            )
            closed = _apply_phantom_slippage_meta(
                closed,
                pos,
                exit_reason=exit_reason,
                record_reason=record_reason,
                exchange_settled=exchange_settled,
            )
            if closed.get("phantom_slippage"):
                _register_phantom_close_guard(pos)
                print(
                    f"  ⚠ MEGA phantom spike {sym} ({record_reason}) — "
                    f"pre_send_net=${float(pos.get('pre_send_net') or 0):.2f} "
                    f"fill_net=${float(closed.get('wallet_pnl') or 0):.2f} "
                    f"(panel gizli, kayıt+Telegram)"
                )
            if 0 <= i < len(_mega_positions) and _mega_positions[i].get("id") == pos.get("id"):
                _mega_positions.pop(i)
            _append_mega_closed_record(closed)
            _record_mega_close_ledger(closed)
            _persist_open_meta()
            _maybe_unlock_regime()
            wp = float(closed.get("wallet_pnl") or closed.get("final_pnl") or 0)
            gross = float(closed.get("pnl_usd") or closed.get("pnl_gross_usd") or 0)
            from elite_trader.exchange_trade_truth import format_close_log_api

            print(
                format_close_log_api(
                    pos_id=position_id,
                    symbol=sym,
                    settled=exchange_settled,
                    record_reason=record_reason,
                    fallback_final=wp,
                )
            )
            _audit_mega_close(
                "close_recorded",
                position_id=position_id,
                symbol=sym,
                side=side,
                exit_reason=record_reason,
                wallet_pnl=wp,
                pnl_gross=gross,
                close_order_id=close_order_id,
                settlement=exchange_settled,
                closed_row=closed.get("settlement_detail"),
                detail=closed.get("phantom_detail") if closed.get("phantom_slippage") else None,
                phantom_slippage=bool(closed.get("phantom_slippage")),
                panel_hide=bool(closed.get("panel_hide")),
                system_context=closed.get("exit_context")
                or _mega_system_context_for_audit(
                    "exit",
                    pos,
                    exit_reason=record_reason,
                    settlement=exchange_settled,
                ),
            )
            refresh_mega_positions_cache(force=True)
            _wake_mega_rest(force_sync=True)
            return True
        except Exception as exc:
            if _mega_is_reduce_only_rejected(exc):
                return _mega_finalize_flat_exchange_close(i, pos, exit_reason, mc=mc)
            if _mega_is_order_timeout(exc):
                return _mega_recover_close_after_timeout(
                    i,
                    pos,
                    exit_reason,
                    mc=mc,
                    close_order_id=pos.get("exchange_close_order_id"),
                )
            print(f"  ⛔ MEGA kapanış hatası {pos.get('symbol')}: {exc}")
            return False
        finally:
            _mega_closing.discard(position_id)
    return False


def mega_has_open() -> bool:
    """Sıcak yol — borsa sync tetiklemeden açık pozisyon var mı."""
    if not mega_motor_active():
        return False
    return bool(_mega_positions) or bool(_mega_positions_cache)


def _mega_sim_price_bulk(bulk: dict[str, float] | None = None) -> dict[str, float]:
    """MEGA sim mark — 9007 hub (paper) veya WS/bookTicker."""
    out = {str(k).upper(): float(v) for k, v in (bulk or {}).items() if float(v or 0) > 0}
    coins: list[str] = []
    for p in _mega_positions:
        if p.get("on_exchange"):
            continue
        c = str(p.get("symbol") or "").replace("USDT", "").upper()
        if c and c not in coins:
            coins.append(c)
    if not coins:
        return out
    missing = [c for c in coins if c not in out and f"{c}USDT" not in out]
    if not missing:
        return out
    try:
        from elite_trader.binance_data_hub import hub_consumer_mode, hub_prices_for_coins

        if hub_consumer_mode():
            for c, px in hub_prices_for_coins(missing).items():
                key = str(c).upper().replace("USDT", "")
                if px and float(px) > 0:
                    out[key] = float(px)
            missing = [c for c in coins if c not in out]
            if not missing:
                return out
    except ImportError:
        pass
    try:
        from binance_futures_trader.fast_price_ws import get_all_fast_prices, get_fast_price

        bulk_fast = get_all_fast_prices(max_age_ms=8000)
        for c in missing:
            d = bulk_fast.get(c)
            if d and float(d.get("mid") or 0) > 0:
                out[c] = float(d["mid"])
    except Exception:
        pass
    missing = [c for c in coins if c not in out]
    if missing:
        try:
            from binance_futures_trader.mark_ws import get_mark_prices_bulk

            marks = get_mark_prices_bulk(max_recv_age_sec=90)
            for c in missing:
                px = marks.get(c) or marks.get(f"{c}USDT")
                if px and float(px) > 0:
                    out[c] = float(px)
        except Exception:
            pass
    return out


def refresh_mega_sim_marks(bulk: dict[str, float] | None = None) -> None:
    """Paper sim — WS mark ile uPnL güncelle (positionRisk yok)."""
    if not _mega_positions:
        return
    prices = _mega_sim_price_bulk(bulk)
    if not prices:
        return
    for pos in _mega_positions:
        if pos.get("on_exchange"):
            continue
        _apply_price_tick(pos, prices)


def _mega_sim_row_for_ui(pos: dict[str, Any]) -> dict[str, Any]:
    p = dict(pos)
    ep = float(p.get("entry_price") or 0)
    cp = float(p.get("current_price") or ep)
    unreal = float(p.get("unrealized_pnl") or 0)
    stake = max(float(p.get("stake_usd") or 1), 0.01)
    net_tp = float(p.get("tp_net_target_usd") or p.get("tp_target_usd") or 0)
    et = float(p.get("entry_time") or 0)
    p["entry_price"] = ep
    p["current_price"] = cp
    p["mark_price"] = cp
    p["unrealized_pnl"] = round(unreal, 4)
    p["exchange_unrealized_pnl"] = round(unreal, 4)
    p["pnl_pct"] = round(unreal / stake * 100, 4) if stake > 0 else 0.0
    p["data_source"] = "sim"
    p["panel_mode"] = "mega"
    p["signal_source"] = p.get("signal_source") or "MEGA-SIM"
    if et > 0:
        p["duration_sec"] = max(0.0, time.time() - et)
    max_u = float(p.get("max_unreal_seen") or unreal)
    if net_tp > 0 and unreal > 0:
        p["tp_progress_pct"] = round(min(100.0, unreal / net_tp * 100.0), 1)
    else:
        p["tp_progress_pct"] = 0.0
    if net_tp > 0 and max_u > 0:
        p["tp_peak_progress_pct"] = round(min(150.0, max_u / net_tp * 100.0), 1)
    p["exchange_display"] = {
        "symbol": p.get("symbol"),
        "side": p.get("side"),
        "entryPrice": ep,
        "markPrice": cp,
        "unRealizedProfit": unreal,
        "leverage": p.get("leverage"),
    }
    _attach_position_health_to_row(p, list_age_ms=0, mark_age_ms=0, hub_meta={})
    return p


def _touch_live_positions_from_cache() -> bool:
    """Canlı pozisyon mark/uPnL — positionRisk önbellek (hub overlay yok)."""
    if not _mega_positions or not _mega_positions_cache:
        return False
    mc = get_mega_client()
    if not mc or mc.paper or not mega_live_enabled():
        return False
    if not _mega_panel_exchange_only():
        touch_mega_cache_from_hub_marks()
    exch = list(_mega_positions_cache)
    touched = False
    for pos in _mega_positions:
        if pos.get("on_exchange") or pos.get("exchange_synced"):
            _sync_pos_from_exchange(pos, exch, mode_id="mega")
            touched = True
    return touched


def _panel_hub_marks() -> tuple[dict[str, float], dict[str, Any]]:
    marks: dict[str, float] = {}
    meta: dict[str, Any] = {"enabled": False, "alive": False, "mark_lag_ms": None}
    try:
        from elite_trader.mega_async_hub import hub_marks_snapshot

        marks, meta = hub_marks_snapshot(max_recv_age_sec=2.0)
    except Exception:
        pass
    if not marks:
        bulk = _mega_sim_price_bulk()
        if bulk:
            marks = {str(k).upper(): float(v) for k, v in bulk.items() if float(v or 0) > 0}
    return marks, meta


def _apply_panel_hub_marks_to_positions(marks: dict[str, float]) -> None:
    """Panel tick — canlı: positionRisk REST; sim: WS mark."""
    if not _mega_positions:
        return
    mc = get_mega_client()
    live_desk = mega_live_enabled() and mc and not mc.paper
    if live_desk and _mega_panel_exchange_only():
        refresh_mega_positions_cache(
            force=_mega_panel_positions_stale(),
            skip_wallet=True,
            panel_critical=True,
        )
        _touch_live_positions_from_cache()
        return
    if not _mega_panel_exchange_only():
        touch_mega_cache_from_hub_marks()
    _touch_live_positions_from_cache()
    for pos in _mega_positions:
        if pos.get("on_exchange") or pos.get("exchange_synced"):
            continue
        _apply_price_tick(pos, marks)


def open_ticks_for_ui() -> dict[str, Any]:
    """Panel hafif poll — canlı: positionRisk; sim: mark WS."""
    ts = datetime.now(timezone.utc).isoformat()
    hub_meta: dict[str, Any] = {}
    marks: dict[str, float] = {}
    if not mega_motor_active():
        return {"ok": True, "ts": ts, "open": [], "marks": marks, "hub": hub_meta}
    mc = get_mega_client()
    live_desk = mega_live_enabled() and mc and not mc.paper
    if live_desk and _mega_panel_exchange_only():
        marks, hub_meta = _panel_hub_marks()
        refresh_mega_positions_cache(
            force=_mega_tick_positions_stale(),
            skip_wallet=True,
            panel_critical=False,
        )
        if not _mega_positions_cache:
            return {"ok": True, "ts": ts, "open": [], "marks": {}, "hub": hub_meta}
        rows = _open_ticks_rows_fast(hub_meta=hub_meta)
        _panel_overlay_hub_mark_on_rows(rows, hub_meta=hub_meta)
        audit = _panel_upnl_audit(rows)
        return {
            "ok": True,
            "ts": ts,
            "open": rows,
            "marks": {},
            "hub": hub_meta,
            "upnl_audit": audit,
            "positions_cache_age_ms": max(
                0, int(_mega_positions_list_age_sec() * 1000)
            ),
        }
    if live_desk and not _mega_positions_cache:
        return {"ok": True, "ts": ts, "open": [], "marks": marks, "hub": hub_meta}
    if not _mega_positions:
        return {"ok": True, "ts": ts, "open": [], "marks": marks, "hub": hub_meta}
    marks, hub_meta = _panel_hub_marks()
    _apply_panel_hub_marks_to_positions(marks)
    refresh_mega_sim_marks(marks)
    rows: list[dict[str, Any]] = []
    tick_positions = _mega_positions
    if live_desk and _mega_positions_cache:
        ex_keys = {
            (
                str(ep.get("symbol") or f"{ep.get('coin', '')}USDT").upper(),
                str(ep.get("side") or "LONG").upper(),
            )
            for ep in _mega_positions_cache
        }
        tick_positions = [
            p
            for p in _mega_positions
            if (str(p.get("symbol") or "").upper(), str(p.get("side") or "LONG").upper())
            in ex_keys
        ]
    for p in tick_positions:
        ex = dict(p.get("exchange_display") or {})
        cp = float(ex.get("markPrice") or p.get("current_price") or p.get("entry_price") or 0)
        unreal = _panel_api_unreal(p)
        stake = max(float(p.get("stake_usd") or 1), 0.01)
        net_tp = float(p.get("tp_net_target_usd") or p.get("tp_target_usd") or 0)
        max_u = float(
            p.get("max_exchange_unreal_seen") or p.get("max_unreal_seen") or (unreal or 0)
        )
        row: dict[str, Any] = {
            "id": p.get("id"),
            "symbol": p.get("symbol"),
            "side": p.get("side"),
            "entry_price": p.get("entry_price"),
            "current_price": cp,
            "mark_price": cp,
            "unrealized_pnl": round(unreal, 4) if unreal is not None else None,
            "exchange_unrealized_pnl": round(unreal, 4) if unreal is not None else None,
            "pnl_pct": round(unreal / stake * 100, 4) if stake and unreal is not None else None,
            "tp_net_target_usd": p.get("tp_net_target_usd"),
            "tp_target_usd": p.get("tp_target_usd"),
            "stake_usd": p.get("stake_usd"),
            "leverage": p.get("leverage"),
            "entry_time": p.get("entry_time"),
            "max_unreal_seen": max_u,
            "data_source": p.get("data_source") or "binance",
            "tp_progress_pct": round(min(100.0, unreal / net_tp * 100.0), 1)
            if net_tp > 0 and unreal is not None and unreal > 0
            else 0.0,
            "tp_peak_progress_pct": round(min(100.0, max_u / net_tp * 100.0), 1)
            if net_tp > 0 and max_u > 0
            else 0.0,
            "upnl_missing": unreal is None,
        }
        if unreal is not None:
            ex["unRealizedProfit"] = str(unreal)
        else:
            ex.pop("unRealizedProfit", None)
        row["exchange_display"] = ex
        list_age_ms, mark_age_ms = _open_ui_age_ms()
        _attach_position_health_to_row(
            row, list_age_ms=list_age_ms, mark_age_ms=mark_age_ms, hub_meta=hub_meta
        )
        row["positions_cache_age_ms"] = list_age_ms
        row["exchange_data_age_ms"] = mark_age_ms
        rows.append(row)
    return {"ok": True, "ts": ts, "open": rows, "marks": marks, "hub": hub_meta}


def _apply_cache_unreal(pos: dict[str, Any], exch: list[dict[str, Any]]) -> None:
    sym = str(pos.get("symbol") or "").upper()
    side = str(pos.get("side") or "LONG").upper()
    coin = sym.replace("USDT", "")
    for ep in exch:
        ec = str(ep.get("coin") or "").upper()
        es = str(ep.get("side") or "LONG").upper()
        if (ec + "USDT" != sym and ec != coin) or es != side:
            continue
        eu = float(ep.get("unrealized_pnl") or pos.get("unrealized_pnl") or 0)
        pos["exchange_unrealized_pnl"] = eu
        pos["unrealized_pnl"] = eu
        pos["max_unreal_seen"] = max(float(pos.get("max_unreal_seen", eu)), eu)
        stake = float(pos.get("stake_usd") or 1)
        lev = max(int(pos.get("leverage") or 2), 1)
        net = _mega_wallet_net_from_gross(pos, eu, stake=stake, lev=lev)
        pos["max_net_seen"] = max(float(pos.get("max_net_seen") or 0), net)
        return


def touch_mega_open_from_cache(bulk: dict[str, float] | None = None) -> None:
    """Hızlı yol — WS/cache mark + positionRisk önbellek; REST/çıkış yok (~ms)."""
    global _mega_last_touch_tick_ms
    if not mega_motor_active() or not _mega_positions:
        return
    t0 = time.perf_counter()
    touch_mega_cache_from_hub_marks()
    if bulk:
        for pos in _mega_positions:
            if not pos.get("on_exchange") and not pos.get("exchange_synced"):
                _apply_price_tick(pos, bulk)
    exch = list(_mega_positions_cache)
    if exch:
        for pos in _mega_positions:
            if pos.get("on_exchange") or pos.get("exchange_synced"):
                _sync_pos_from_exchange(pos, exch, mode_id="mega")
    _mega_last_touch_tick_ms = round((time.perf_counter() - t0) * 1000.0, 2)


def _mega_exit_eval_interval_sec() -> float:
    take = _mega_spike_take_gross_usd()
    for pos in _mega_positions or []:
        g = max(
            float(pos.get("max_unreal_seen") or 0),
            _mega_api_gross_unreal(pos),
        )
        if g >= take * 0.85:
            return max(0.05, _env_float("MEGA_EXIT_EVAL_FAST_SEC", 0.06))
    if mega_needs_fast_exit():
        return max(0.06, _env_float("MEGA_EXIT_EVAL_FAST_SEC", 0.08))
    return max(0.12, _env_float("MEGA_EXIT_EVAL_SEC", 0.20))


def evaluate_mega_exits(bulk: dict[str, float]) -> None:
    """Tam çıkış değerlendirmesi — REST yenile + TP/spike (200ms+ aralık)."""
    if not mega_motor_active():
        return
    try:
        from elite_trader.mega_control import apply_pause_exits, control_state

        apply_pause_exits(bulk, close_fn=close_mega_position)
        if control_state() in ("PAUSED", "RESTARTING"):
            return
    except Exception:
        pass
    touch_mega_cache_from_hub_marks()
    from elite_trader.exchange_position_sync import process_position_exit

    global _mega_last_exit_tick_ms, _mega_last_exit_eval_ms, _mega_last_close_settle_ms
    global _mega_last_exit_eval_ts, _mega_exit_eval_cursor
    t0 = time.perf_counter()
    t_close = 0.0
    closes_done = 0
    max_closes = max(1, int(_env_float("MEGA_EXIT_MAX_CLOSES_PER_TICK", 1)))
    _mega_last_exit_eval_ts = time.time()
    mc = get_mega_client()
    if not _mega_positions:
        return
    hub_fresh = False
    try:
        from elite_trader.mega_async_hub import hub_cache_hot

        hub_fresh = hub_cache_hot() and _mega_hub_mark_hot()
    except Exception:
        pass
    if mc and not mc.paper and not hub_fresh:
        cache_age = time.time() - float(_mega_cache_ts or 0)
        refresh_iv = max(
            0.45,
            _env_float("MEGA_EXIT_POS_REFRESH_SEC", 0.55),
            _mega_cache_ttl_open_sec() * 0.85,
        )
        if cache_age >= refresh_iv and _mega_positions_list_stale(
            max_sec=refresh_iv
        ):
            refresh_mega_positions_cache(
                force=False, skip_wallet=True, panel_critical=False
            )
    exch = list(_mega_positions_cache)
    from elite_trader.fee_economics import (
        estimate_close_pnl,
        exit_net_passes,
        min_gross_for_final_net,
        tp_sl_gross_triggers,
    )

    def _try_close_mega(pid: int, reason: str) -> bool:
        nonlocal closes_done, t_close
        if closes_done >= max_closes:
            return False
        tc0 = time.perf_counter()
        ok = close_mega_position(pid, reason)
        t_close += time.perf_counter() - tc0
        if ok:
            closes_done += 1
        return ok

    all_pos = list(_mega_positions)
    batch_n = _env_int("MEGA_EXIT_EVAL_BATCH", 0)
    if batch_n > 0 and len(all_pos) > batch_n:
        start = _mega_exit_eval_cursor % len(all_pos)
        eval_pos = [
            all_pos[(start + i) % len(all_pos)] for i in range(batch_n)
        ]
        _mega_exit_eval_cursor = (start + batch_n) % len(all_pos)
    else:
        eval_pos = all_pos
    take_gross_arm = _mega_spike_take_gross_usd()
    for pos in eval_pos:
        if closes_done >= max_closes:
            break
        if pos.get("on_exchange"):
            _sync_pos_from_exchange(pos, exch, mode_id="mega")
        else:
            _apply_price_tick(pos, bulk)
        stake = float(pos.get("stake_usd") or 0)
        lev = max(int(pos.get("leverage") or 2), 1)
        unreal = _mega_api_gross_unreal(pos)
        pos["unrealized_pnl"] = unreal
        max_u = float(pos.get("max_unreal_seen") or unreal)
        tp_g, _, _, _ = tp_sl_gross_triggers(stake, lev, "mega")
        in_spike = max_u >= take_gross_arm * 0.72 or unreal >= take_gross_arm * 0.72
        near_tp = unreal >= tp_g * 0.45 or max_u >= tp_g * 0.45
        if not in_spike and not near_tp and unreal <= 0:
            continue
        _mega_touch_peak_net(pos, stake=stake, lev=lev, mc=mc if in_spike else None)
        _mega_update_profit_tier_lock(pos, mc=mc if in_spike else None)
        profit_seen = _mega_profit_seen_ok(pos, mc=mc if in_spike else None)

        tier_reason = _mega_profit_tier_close_reason(
            pos, stake=stake, lev=lev, mc=mc
        )
        if tier_reason:
            pos["tp_fast_close"] = True
            pos["mega_tier_close"] = True
            if _try_close_mega(int(pos["id"]), tier_reason):
                continue

        mark_reason = _mega_mark_spike_reason(pos, stake=stake, lev=lev, mc=mc)
        if mark_reason:
            pos["mark_spike_close"] = True
            pos["tp_fast_close"] = True
            if _try_close_mega(int(pos["id"]), mark_reason):
                continue

        # Orta spike ($14–20 brüt) — tam TP beklemeden kilitle
        take_gross = _mega_spike_take_gross_usd(stake)
        if (
            _env_bool("MEGA_MID_SPIKE_LOCK", True)
            and max_u >= take_gross
            and unreal >= take_gross * max(0.82, _mega_spike_peak_frac())
            and unreal > 0
        ):
            est_mid = estimate_close_pnl(
                unreal,
                stake,
                lev,
                entry_fee=float(pos.get("entry_fee") or 0) or None,
                pos=pos,
                client=mc,
            )
            if _mega_spike_exit_net_ok(
                pos,
                unreal,
                float(est_mid.get("final_pnl") or 0),
                stake=stake,
                lev=lev,
                mc=mc,
            ):
                pos["tp_fast_close"] = True
                pos["mark_spike_close"] = True
                if _try_close_mega(int(pos["id"]), "SPIKE-FLASH"):
                    continue

        if profit_seen:
            peak_cap = _mega_peak_capture_close_reason(
                pos, stake=stake, lev=lev, mc=mc, tp_g=tp_g
            )
            if peak_cap:
                pos["tp_fast_close"] = True
                if _try_close_mega(int(pos["id"]), peak_cap):
                    continue

            net_reason = _mega_net_tp_close_reason(
                pos, stake=stake, lev=lev, mc=mc
            )
            if net_reason:
                pos["tp_fast_close"] = True
                if _try_close_mega(int(pos["id"]), net_reason):
                    continue

            peak_reason = _mega_peak_lock_reason(pos, tp_g)
            if peak_reason:
                pos["tp_fast_close"] = True
                if _try_close_mega(int(pos["id"]), peak_reason):
                    continue

        uw_reason = _mega_underwater_time_stop_reason(pos)
        if uw_reason:
            pos["mega_underwater_close"] = True
            if _try_close_mega(int(pos["id"]), uw_reason):
                continue

        if not profit_seen and not in_spike and unreal < tp_g * 0.35:
            continue

        trigger_gross = max(unreal, max_u if max_u >= tp_g else unreal)
        if profit_seen and trigger_gross >= tp_g and unreal > 0:
            est = estimate_close_pnl(
                unreal,
                stake,
                lev,
                entry_fee=float(pos.get("entry_fee") or 0) or None,
                pos=pos,
                client=mc,
            )
            min_g = min_gross_for_final_net(stake, lev, mode_id="mega", pos=pos, client=mc)
            if exit_net_passes(float(est["final_pnl"]), "mega") or (
                _env_bool("MEGA_TP_FAST_PATH", True)
                and max_u >= tp_g
                and unreal >= min_g
            ):
                pos["tp_fast_close"] = max_u >= tp_g
                if _try_close_mega(int(pos["id"]), "TP"):
                    continue
        exit_reason = process_position_exit(
            pos,
            exchange_positions=exch,
            bulk_prices=bulk,
            exec_mode="mega",
            live_orders=True,
            client_paper=False,
            api_client=mc,
        )
        if exit_reason:
            if str(exit_reason).upper() == "SPIKE-FLASH" and _mega_spike_close_ready(
                pos, stake=stake, lev=lev, mc=mc
            ):
                pos["mark_spike_close"] = True
                pos["tp_fast_close"] = True
            elif str(exit_reason).upper() in ("TP", "SPIKE-FLASH", "SPIKE-QUICK", "SPIKE-PEAK"):
                if not _mega_profit_seen_ok(pos, exit_reason=exit_reason, mc=mc):
                    exit_reason = None
            if exit_reason and str(exit_reason).upper() in (
                "TP",
                "SPIKE-FLASH",
                "SPIKE-QUICK",
                "SPIKE-PEAK",
            ):
                pos["tp_fast_close"] = pos.get("tp_fast_close") or max_u >= tp_g * 0.94
            if exit_reason:
                _try_close_mega(int(pos["id"]), exit_reason)
    _persist_open_book(force=False)
    if mega_needs_fast_exit():
        _wake_mega_exit_poll(force_rest_sync=False)
        _wake_mega_rest(force_sync=False)
    total_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    close_ms = round(t_close * 1000.0, 1)
    _mega_last_close_settle_ms = close_ms
    _mega_last_exit_tick_ms = total_ms
    _mega_last_exit_eval_ms = max(0.0, round(total_ms - close_ms, 1))


def mega_position_tick(bulk: dict[str, float]) -> None:
    """Position worker — yalnızca cache/mark sync (çıkış REST worker'da)."""
    try:
        from elite_trader.mega_system_report import tick_scheduled_report

        tick_scheduled_report()
    except Exception:
        pass
    try:
        from elite_trader.mega_coin_rank import tick_coin_rank

        tick_coin_rank()
    except Exception:
        pass
    touch_mega_open_from_cache(bulk)


def check_mega_exits(bulk: dict[str, float]) -> None:
    """Tam çıkış yolu — REST worker veya acil durum."""
    touch_mega_open_from_cache(bulk)
    evaluate_mega_exits(bulk)


def mega_health() -> dict[str, Any]:
    """MEGA worker / borsa API sağlık — heartbeat ve izleme."""
    now = time.time()
    if _mega_cache_ts:
        cache_age_ms = max(0, int((now - float(_mega_cache_ts)) * 1000))
    else:
        cache_age_ms = 999_999
    try:
        from elite_trader.mega_async_hub import hub_cache_hot, mega_hub_status

        if hub_cache_hot():
            hc = (mega_hub_status().get("cache") or {}) if mega_hub_status else {}
            lag = int(hc.get("mark_lag_ms") or hc.get("lag_ms") or 0)
            if lag > 0:
                cache_age_ms = min(cache_age_ms, lag)
    except Exception:
        pass
    pos_risk_age_sec = round(_mega_positions_list_age_sec(), 2)
    api_ok = False
    api_last_ok_ago: float | None = None
    try:
        from elite_trader.connection_alerts import ip_ban_active, last_ok_age_sec

        api_last_ok_ago = last_ok_age_sec()
        stale = max(12.0, _env_float("ELITE_API_STALE_SEC", 35.0))
        api_ok = (
            not ip_ban_active()
            and api_last_ok_ago is not None
            and api_last_ok_ago <= stale
        )
    except Exception:
        pass
    out: dict[str, Any] = {
        "open": len(_mega_positions),
        "api_ok": api_ok,
        "api_last_ok_ago_sec": api_last_ok_ago,
        "position_risk_age_sec": pos_risk_age_sec,
        "position_risk_ok": pos_risk_age_sec
        <= max(3.0, _mega_panel_pos_risk_max_age_sec() * 2),
        "cache_age_ms": cache_age_ms,
        "cache_source": _mega_cache_source,
        "fast_poll": bool(
            _mega_positions and _env_bool("MEGA_OPEN_FAST_POLL", True)
        ),
        "tp_armed": sum(1 for p in _mega_positions if p.get("exchange_tp_order_id")),
        "tp_arm_failed": sum(1 for p in _mega_positions if p.get("exchange_tp_arm_failed")),
        "trail_lock_armed": sum(
            1 for p in _mega_positions if p.get("exchange_lock_order_id")
        ),
        "trail_lock_updates_total": _mega_lock_updates_total,
        "tp_arms_total": _mega_tp_arms_total,
        "tp_adopts_total": _mega_tp_adopts_total,
        "last_exit_tick_ms": _mega_last_exit_tick_ms,
        "last_exit_eval_ms": _mega_last_exit_eval_ms,
        "last_close_settle_ms": _mega_last_close_settle_ms,
        "last_touch_tick_ms": _mega_last_touch_tick_ms,
        "exit_eval_interval_sec": _mega_exit_eval_interval_sec(),
        "snapshot_busy": _mega_snapshot_busy,
        "rest_worker": mega_rest_worker_alive(),
        "sync_ago_sec": round(now - _mega_sync_ts, 1) if _mega_sync_ts else None,
        "tp_verify_ago_ms": max(
            0, int((now - float(_mega_tp_verify_ts or now)) * 1000)
        ),
        "last_tp_verify_ms": _mega_last_tp_verify_ms,
        "tp_verify_urgent": _mega_need_tp_verify(),
    }
    try:
        from elite_trader.mega_close_sync import close_sync_health
        from elite_trader.mega_position_sync import position_sync_health

        out["position_sync"] = position_sync_health()
        out["close_sync"] = close_sync_health()
    except Exception:
        pass
    try:
        from elite_trader.mega_async_hub import mega_hub_status

        out["async_hub"] = mega_hub_status()
    except Exception:
        pass
    return out


def _mega_positions_revision() -> int:
    """Yapısal rev — uPnL/mark değişimi light snapshot önbelleğini bozmasın."""
    return hash(
        tuple(
            (
                p.get("id"),
                p.get("symbol"),
                str(p.get("side") or "").upper(),
            )
            for p in _mega_positions
        )
    )


def _refresh_open_ui_marks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {int(p["id"]): p for p in _mega_positions if p.get("id") is not None}
    out: list[dict[str, Any]] = []
    list_age_ms, mark_age_ms = _open_ui_age_ms()
    for row in rows:
        r = dict(row)
        loc = by_id.get(int(r.get("id") or 0))
        if not loc:
            out.append(r)
            continue
        api_row = bool(r.get("on_exchange") or r.get("exchange_synced"))
        overlay_keys = (
            ("current_price", "unrealized_pnl", "exchange_unrealized_pnl", "pnl_pct", "duration_sec")
            if api_row
            else ("current_price", "unrealized_pnl", "pnl_pct", "duration_sec")
        )
        for key in overlay_keys:
            if key in loc:
                r[key] = loc[key]
        if api_row:
            unreal = _panel_api_unreal(loc) if loc else _panel_api_unreal(r)
            if unreal is not None:
                r["exchange_unrealized_pnl"] = unreal
                r["unrealized_pnl"] = unreal
                r.pop("upnl_missing", None)
            else:
                r["exchange_unrealized_pnl"] = None
                r["unrealized_pnl"] = None
                r["upnl_missing"] = True
        else:
            unreal = float(r.get("unrealized_pnl") or 0)
            r["exchange_unrealized_pnl"] = unreal
        net_tp = float(loc.get("tp_net_target_usd") or r.get("tp_net_target_usd") or 0)
        if net_tp > 0 and unreal is not None and unreal > 0:
            r["tp_progress_pct"] = round(min(100.0, unreal / net_tp * 100.0), 1)
        max_u = float(loc.get("max_unreal_seen") or 0)
        if net_tp > 0 and max_u > 0:
            r["tp_peak_progress_pct"] = round(min(150.0, max_u / net_tp * 100.0), 1)
        if api_row and loc and loc.get("exchange_display"):
            ex = dict(loc["exchange_display"])
            if unreal is not None:
                ex["unRealizedProfit"] = str(unreal)
            else:
                ex.pop("unRealizedProfit", None)
            r["exchange_display"] = ex
        elif not api_row:
            ex = dict(r.get("exchange_display") or {})
            mark = loc.get("current_price")
            if mark:
                ex["markPrice"] = mark
                if unreal is not None:
                    ex["unRealizedProfit"] = unreal
            r["exchange_display"] = ex
        r["positions_cache_age_ms"] = list_age_ms
        r["exchange_data_age_ms"] = mark_age_ms
        out.append(r)
    return out


def _open_rows_for_snapshot(*, light: bool, allow_charts: bool) -> list[dict[str, Any]]:
    """Panel open satırları — light poll'da kısa önbellek (position worker GIL rahatlasın)."""
    global _mega_open_ui_cache
    open_rows = [dict(p) for p in _mega_positions]
    if not open_rows:
        return open_rows
    if mega_sim_enabled() and not mega_live_enabled():
        refresh_mega_sim_marks()
        return [_mega_sim_row_for_ui(p) for p in _mega_positions]
    if not _mega_positions_cache:
        refresh_mega_sim_marks()
        return [_mega_sim_row_for_ui(p) for p in _mega_positions]
    now = time.time()
    rev = _mega_positions_revision()
    ttl = (
        max(0.12, _env_float("MEGA_SNAPSHOT_UI_CACHE_SEC", 0.32))
        if light and not allow_charts
        else 0.0
    )
    list_age_sec = _mega_positions_list_age_sec()
    if list_age_sec > max(3.0, _mega_panel_pos_risk_max_age_sec() * 2):
        _mega_open_ui_cache = None
    if ttl > 0 and _mega_open_ui_cache:
        c_ts, c_rev, c_rows = _mega_open_ui_cache
        max_row_age = 0.0
        for r in c_rows:
            max_row_age = max(
                max_row_age,
                float(r.get("positions_cache_age_ms") or r.get("exchange_data_age_ms") or 0),
            )
        stale_row_ms = max(2500.0, _mega_panel_pos_risk_max_age_sec() * 1000.0 * 2)
        cache_hit = (
            (now - c_ts) < ttl
            and c_rev == rev
            and max_row_age < stale_row_ms
            and list_age_sec <= max(3.0, _mega_panel_pos_risk_max_age_sec() * 2)
        )
        if cache_hit:
            return _refresh_open_ui_marks(c_rows)
    try:
        rows = _build_mega_open_rows_light() if light and not allow_charts else _build_mega_open_for_ui(
            light=light,
            allow_chart_fetch=allow_charts,
        )
    except Exception:
        return open_rows
    if light and not allow_charts:
        _mega_open_ui_cache = (now, rev, [dict(r) for r in rows])
    return rows


def _mega_snapshot_allow_charts(*, light: bool) -> bool:
    """Grafik kline fetch — hybrid: yalnızca full snapshot; light önbellekten okur."""
    if _env_bool("MEGA_SNAPSHOT_CHARTS", False):
        return True
    if not _env_bool("MEGA_SNAPSHOT_CHARTS_HYBRID", True):
        return False
    return not light


def _closed_net_pnl_row(row: dict[str, Any]) -> float:
    for key in ("wallet_pnl", "final_pnl", "net_pnl"):
        val = row.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    try:
        return float(row.get("pnl_usd") or 0)
    except (TypeError, ValueError):
        return 0.0


def _build_exchange_account_summary(
    wallet: dict[str, Any],
    closed_rows: list[dict[str, Any]],
    open_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Demo Binance — tek satır panel özeti (net, komisyon/vergi düşülmüş)."""
    net_realized = round(sum(_closed_net_pnl_row(r) for r in closed_rows), 4)
    total_fees = round(
        sum(float(r.get("total_fees") or 0) for r in closed_rows),
        4,
    )
    gross_realized = round(
        sum(
            float(
                r.get("exchange_realized_pnl")
                or r.get("pnl_gross_usd")
                or r.get("pnl_usd")
                or _closed_net_pnl_row(r)
            )
            for r in closed_rows
        ),
        4,
    )
    settled_n = sum(
        1
        for r in closed_rows
        if r.get("exchange_settled") or r.get("income_settled")
    )
    equity = _wallet_balance(wallet)
    avail = float(wallet.get("available_balance") or wallet.get("usdt_available") or 0)
    unreal = float(wallet.get("total_unrealized_pnl") or 0)
    if unreal == 0 and open_rows:
        unreal = sum(float(p.get("unrealized_pnl") or 0) for p in open_rows)
    open_stake = sum(float(p.get("stake_usd") or 0) for p in open_rows)
    anchor = _load_session_anchor()
    wallet_session_pnl = (
        round(equity - float(anchor), 4)
        if anchor and equity and float(anchor) > 0
        else None
    )
    settled_realized = round(
        sum(
            _closed_net_pnl_row(r)
            for r in closed_rows
            if r.get("exchange_settled") or r.get("income_settled")
        ),
        4,
    )
    return {
        "source": wallet.get("source") or "binance_api",
        "api_base": wallet.get("api_base"),
        "can_trade": wallet.get("can_trade"),
        "equity_net": round(equity, 2),
        "available_net": round(avail, 2),
        "unrealized_net": round(unreal, 4),
        "open_stake": round(open_stake, 2),
        "session_anchor": anchor,
        "wallet_session_pnl": wallet_session_pnl,
        "realized_net_settled": settled_realized,
        "closed_count": len(closed_rows),
        "closed_settled_count": settled_n,
        "realized_net": net_realized,
        "realized_gross": gross_realized,
        "total_fees": total_fees,
        "open_count": len(open_rows),
        "sync_ts": wallet.get("_ts"),
        "label": "Demo Binance (net · komisyon düşülmüş)",
    }


def _snapshot_from_cache(*, stale: bool = False, light: bool = True) -> dict[str, Any]:
    mc = get_mega_client()
    cache_age = time.time() - float(_mega_cache_ts or 0) if _mega_cache_ts else 999.0
    if cache_age >= max(0.35, _env_float("MEGA_SNAPSHOT_HUB_TOUCH_SEC", 0.55)):
        touch_mega_cache_from_hub_marks()
    hub_hot = False
    try:
        from elite_trader.mega_async_hub import hub_cache_hot, mega_hub_enabled

        hub_hot = mega_hub_enabled() and hub_cache_hot()
    except Exception:
        pass
    if not hub_hot and cache_age >= max(0.5, _env_float("MEGA_CACHE_MAX_STALE_SEC", 0.85)):
        _wake_mega_rest(force_sync=False)
    if mega_live_enabled() and mc and not mc.paper:
        try:
            prune_ghost_open_positions()
        except Exception:
            pass
    wallet = dict(_mega_wallet)
    allow_charts = _mega_snapshot_allow_charts(light=light)
    open_rows: list[dict[str, Any]] = []
    if mega_sim_enabled() and not mega_live_enabled() and _mega_positions:
        refresh_mega_sim_marks()
        open_rows = [_mega_sim_row_for_ui(p) for p in _mega_positions]
    elif mega_live_enabled() and mc and not mc.paper:
        if _mega_panel_exchange_only() and _mega_positions:
            list_age = _mega_positions_list_age_sec()
            force_refresh = _mega_panel_positions_stale()
            refresh_mega_positions_cache(
                force=force_refresh,
                skip_wallet=True,
                panel_critical=True,
            )
        if _mega_positions_cache:
            open_rows = _open_rows_for_snapshot(light=light, allow_charts=allow_charts)
    elif _mega_positions_cache:
        open_rows = _open_rows_for_snapshot(light=light, allow_charts=allow_charts)
    if mega_sim_enabled():
        paper_mode = True
    elif mega_live_orders_enabled():
        # Canlı desk — API ban/auth geçici hatalarında parallel paper kitaba düşme.
        paper_mode = False
    else:
        paper_mode = True
    anchor = _load_session_anchor() or _env_float("STARTING_BALANCE", 5000.0)
    if mega_live_enabled() and mc and not mc.paper:
        if len(_mega_closed) == 0:
            _ensure_panel_closed_rows(force=True)
    closed_rows = _build_mega_closed_for_ui(light=True)
    closed_sum = sum(
        float(r.get("final_pnl") or r.get("wallet_pnl") or r.get("net_pnl") or r.get("pnl_usd") or 0)
        for r in closed_rows
    )
    sim_only = mega_sim_enabled() and not mega_live_enabled()
    wallet_session_pnl: float | None = None
    settled_realized = 0.0
    if paper_mode and sim_only:
        open_stake = sum(float(p.get("stake_usd") or 0) for p in open_rows)
        unreal = sum(float(p.get("unrealized_pnl") or 0) for p in open_rows)
        realized = closed_sum
        equity = anchor + realized + unreal
        avail = max(0.0, equity - open_stake)
        session_pnl = realized + unreal
        total_equity_pnl = session_pnl
        summary_source = "mega_sim"
    elif paper_mode:
        from elite_trader import parallel_universe_engine as pe

        ps = pe.build_summary("mega")
        equity = float(ps.get("current_capital") or anchor)
        avail = float(ps.get("available_capital") or ps.get("session_available_est") or equity)
        unreal = float(ps.get("unrealized_pnl") or 0)
        if unreal == 0 and open_rows:
            unreal = sum(float(p.get("unrealized_pnl") or 0) for p in open_rows)
        realized = float(ps.get("realized_pnl") or closed_sum or 0)
        session_pnl = realized
        total_equity_pnl = float(ps.get("total_pnl") or 0)
        summary_source = "paper_book"
    else:
        equity = _wallet_balance(wallet)
        if equity <= 0 and (closed_sum or open_rows):
            equity = anchor + closed_sum + sum(
                float(p.get("unrealized_pnl") or p.get("exchange_unrealized_pnl") or 0)
                for p in open_rows
            )
        if not anchor and equity > 0:
            anchor = equity
        unreal = float(wallet.get("total_unrealized_pnl") or 0)
        if unreal == 0 and open_rows:
            unreal = sum(float(p.get("unrealized_pnl") or 0) for p in open_rows)
        settled_rows = [
            r
            for r in closed_rows
            if r.get("exchange_settled") or r.get("income_settled")
        ]
        settled_realized = sum(_closed_net_pnl_row(r) for r in settled_rows)
        wallet_session_pnl = (
            round(equity - float(anchor), 4)
            if anchor and equity and float(anchor) > 0
            else None
        )
        realized = settled_realized if settled_rows else closed_sum
        session_pnl = (
            wallet_session_pnl
            if wallet_session_pnl is not None
            else settled_realized + unreal
        )
        total_equity_pnl = (
            wallet_session_pnl
            if wallet_session_pnl is not None
            else (equity - anchor if equity > 0 and anchor > 0 else closed_sum)
        )
        avail = float(wallet.get("available_balance") or wallet.get("usdt_available") or 0)
        open_stake_sum = sum(float(p.get("stake_usd") or 0) for p in open_rows)
        if avail <= 0 and equity > 0:
            avail = max(0.0, equity - open_stake_sum)
        summary_source = "binance_api"
    closed_n = len(closed_rows)
    wins = sum(
        1 for r in closed_rows if float(r.get("final_pnl") or r.get("net_pnl") or 0) > 0
    )
    win_rate = (wins / closed_n * 100.0) if closed_n else None
    out: dict[str, Any] = {
        "ok": True,
        "live": mega_live_enabled() and bool(mc and not mc.paper),
        "mode_id": "mega",
        "summary": {
            "source": summary_source,
            "current_capital": equity,
            "balance": equity,
            "available_balance": avail,
            "available_capital": avail,
            "equity": equity,
            "starting_capital": anchor,
            "session_anchor": anchor,
            "total_pnl": total_equity_pnl,
            "session_pnl": session_pnl,
            "realized_pnl": realized,
            "wallet_session_pnl": wallet_session_pnl,
            "realized_pnl_settled": round(settled_realized, 4),
            "total_pnl_pct": (session_pnl / anchor * 100.0) if anchor > 0 else 0.0,
            "unrealized_pnl": unreal,
            "open_count": len(open_rows),
            "open_trades": len(open_rows),
            "closed_trades": closed_n,
            "win_rate": win_rate,
        },
        "open": open_rows,
        "closed": closed_rows,
        "closed_meta": mega_closed_panel_meta(),
        "wallet": wallet,
        "scan": scan_summary_light() if light or _env_bool("MEGA_PANEL_SCAN_LIGHT", True) else scan_summary(),
    }
    if _env_bool("MEGA_SNAPSHOT_CHARTS_HYBRID", True) and not _env_bool(
        "MEGA_SNAPSHOT_CHARTS", False
    ):
        out["chart_mode"] = "hybrid_light" if light else "hybrid_full"
    elif allow_charts:
        out["chart_mode"] = "always"
    else:
        out["chart_mode"] = "off"
    if stale and not light:
        out["stale"] = True
    if mega_live_enabled() and not paper_mode and not sim_only:
        out["exchange_account"] = _build_exchange_account_summary(
            wallet, closed_rows, open_rows
        )
        # KPI'lar borsa cüzdanını esas alsın
        ex = out["exchange_account"]
        if ex.get("equity_net"):
            out["summary"]["current_capital"] = ex["equity_net"]
            out["summary"]["balance"] = ex["equity_net"]
            out["summary"]["equity"] = ex["equity_net"]
        if ex.get("available_net") is not None:
            out["summary"]["available_balance"] = ex["available_net"]
            out["summary"]["available_capital"] = ex["available_net"]
        if ex.get("unrealized_net") is not None:
            out["summary"]["unrealized_pnl"] = ex["unrealized_net"]
        if ex.get("realized_net") is not None:
            out["summary"]["realized_pnl"] = ex["realized_net"]
            out["summary"]["session_pnl"] = ex["realized_net"]
        out["upnl_audit"] = _panel_upnl_audit(open_rows)
    elif open_rows and mega_live_enabled() and mc and not mc.paper:
        out["upnl_audit"] = _panel_upnl_audit(open_rows)
    return out


def snapshot(*, force: bool = False, light: bool = False) -> dict[str, Any]:
    """Panel snapshot — light=önbellek; full=arka plan REST + kısa bekleme."""
    global _mega_last_full_snapshot_ts, _mega_snapshot_busy
    if light and not force:
        return _snapshot_from_cache(stale=False, light=True)
    now = time.time()
    full_iv = max(4.0, _env_float("MEGA_SNAPSHOT_FULL_SEC", 5.0))
    if not force and (now - float(_mega_last_full_snapshot_ts or 0)) < full_iv:
        return _snapshot_from_cache(stale=True, light=True)
    _mega_last_full_snapshot_ts = now
    cache_before = float(_mega_cache_ts or 0)
    hub_hot = False
    try:
        from elite_trader.mega_async_hub import hub_cache_hot, mega_hub_enabled

        hub_hot = mega_hub_enabled() and hub_cache_hot()
    except Exception:
        pass
    if not hub_hot:
        _wake_mega_rest(force_sync=True)
    wait_s = min(0.6, _env_float("MEGA_SNAPSHOT_WAIT_SEC", 0.45))
    if hub_hot:
        wait_s = min(wait_s, _env_float("MEGA_SNAPSHOT_HUB_WAIT_SEC", 0.08))
    deadline = now + wait_s
    while time.time() < deadline:
        if _mega_cache_ts and _mega_cache_ts > cache_before:
            break
        time.sleep(0.04)
    stale = not _mega_cache_ts or (time.time() - float(_mega_cache_ts)) > 2.5
    if stale and not force:
        _mega_snapshot_busy += 1
    else:
        _mega_snapshot_busy = max(0, _mega_snapshot_busy - 1)
    if not light and mega_live_enabled() and _env_bool("MEGA_SNAPSHOT_SYNC_WALLET", False):
        try:
            from elite_trader.network_guard import is_degraded, skip_rest

            if not skip_rest() and not is_degraded():
                reconcile_mega_closed_with_exchange(force=False)
                _fetch_wallet(force=False)
        except Exception:
            pass
    return _snapshot_from_cache(stale=stale, light=light)


def mega_open_coins(*, sync_if_missing: bool = True) -> list[str]:
    if (
        sync_if_missing
        and mega_live_enabled()
        and not _mega_positions
        and _mega_positions_cache
    ):
        _wake_mega_rest(force_sync=True)
    if _mega_positions:
        return [p["symbol"].replace("USDT", "") for p in _mega_positions]
    if _mega_positions_cache:
        out: list[str] = []
        for ep in _mega_positions_cache:
            coin = str(ep.get("coin") or "").upper()
            if not coin:
                sym = str(ep.get("symbol") or "")
                coin = sym.replace("USDT", "")
            if coin:
                out.append(coin)
        return out
    return []

