#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚀 BINANCE FUTURES — ELITE PRO DASHBOARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Elite APEX Pro - Advanced Trading Dashboard
- Professional charts with TP/SL markers
- Real-time signal scanner
- Fee & tax tracking
- Leverage display
- Comprehensive trade history

RUN: python binance_elite_pro.py  (varsayılan port 9003, scenarios/elite_apex_2x_24h.env)
     veya BINANCE_ELITE_PORT / BINANCE_ELITE_SCENARIO ile özelleştir
ACCESS: http://localhost:<BINANCE_ELITE_PORT>
"""

from __future__ import annotations
import asyncio, faulthandler, json, math, os, signal, sys, threading, time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from dotenv import load_dotenv
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_UNIVERSE_CACHE_PATH = _ROOT / "data" / "universe_cache.json"
_PRICE_CACHE_PATH = _ROOT / "data" / "price_cache.json"
_scenario_arg = os.environ.get("BINANCE_ELITE_SCENARIO", "").strip()
if _scenario_arg:
    _scenario_path = Path(_scenario_arg)
    if not _scenario_path.is_absolute():
        _scenario_path = _ROOT / _scenario_path
else:
    _scenario_path = _ROOT / "scenarios" / "elite_apex_2x_24h.env"

if _scenario_path.is_file():
    load_dotenv(_scenario_path, override=True)
load_dotenv(_ROOT / ".env", override=True)
# 9005: senaryo API anahtarları .env ezmesinden sonra geri yükle
def _is_mega_mainnet() -> bool:
    if not _scenario_path.is_file():
        return False
    name = _scenario_path.name.lower()
    return "mega" in name and "mainnet" in name


if _scenario_path.is_file() and (
    "8300_9005" in _scenario_path.name or _is_mega_mainnet()
):
    load_dotenv(_scenario_path, override=True)
_sk = os.getenv("BINANCE_FUTURES_SECRET_KEY", "").strip()
if _sk and not os.getenv("BINANCE_FUTURES_API_SECRET", "").strip():
    os.environ["BINANCE_FUTURES_API_SECRET"] = _sk


def _is_9005_mainnet() -> bool:
    if os.environ.get("ELITE_MAINNET", "").strip().lower() in ("1", "true", "yes"):
        return True
    return "9005_mainnet" in _scenario_path.name


def _is_9007_process() -> bool:
    port = os.environ.get("BINANCE_ELITE_PORT", "").strip()
    iid = os.environ.get("MEGA_INSTANCE_ID", "").strip()
    return port == "9007" or iid == "9007"


def _is_9006_process() -> bool:
    port = os.environ.get("BINANCE_ELITE_PORT", "").strip()
    iid = os.environ.get("MEGA_INSTANCE_ID", "").strip()
    return port == "9006" or iid == "9006"


def _is_9005_process() -> bool:
    return os.environ.get("BINANCE_ELITE_PORT", "").strip() == "9005"


def _lock_9005_paper_env() -> None:
    """9005 — paper berserk2; demo/mainnet emir yok."""
    if not _is_9005_process():
        return
    for key, val in (
        ("BINANCE_LIVE_ORDERS", "0"),
        ("BINANCE_FUTURES_DEMO", "0"),
        ("BINANCE_FUTURES_TESTNET", "0"),
        ("BN_FUT_MODE", "paper"),
        ("BERSERK2_PAPER_ONLY", "1"),
        ("MEGA_LIVE_ORDERS", "0"),
        ("ELITE_LIVE_ONLY", "0"),
        ("ELITE_PAPER_PARALLEL", "1"),
    ):
        os.environ[key] = val


def _lock_9006_paper_env() -> None:
    """9006 — MEGA paper sim; demo emir yalnızca 9007."""
    if not _is_9006_process():
        return
    for key, val in (
        ("BINANCE_LIVE_ORDERS", "0"),
        ("BINANCE_FUTURES_DEMO", "0"),
        ("BINANCE_FUTURES_TESTNET", "0"),
        ("BN_FUT_MODE", "paper"),
        ("MEGA_BN_FUT_MODE", "paper"),
        ("MEGA_LIVE_ORDERS", "0"),
        ("MEGA_SIM_ENABLED", "1"),
        ("ELITE_LIVE_ONLY", "0"),
        ("ELITE_PAPER_PARALLEL", "1"),
    ):
        os.environ[key] = val


def _lock_9007_demo_futures_env() -> None:
    """9007 — yalnızca demo-fapi.binance.com (mainnet REST/WS yok)."""
    if not _is_9007_process():
        return
    for key, val in (
        ("BINANCE_FUTURES_DEMO", "1"),
        ("BINANCE_FUTURES_TESTNET", "1"),
        ("BN_FUT_MODE", "testnet"),
        ("MEGA_BINANCE_FUTURES_DEMO", "1"),
        ("MEGA_BINANCE_FUTURES_TESTNET", "1"),
        ("MEGA_BN_FUT_MODE", "testnet"),
        ("MEGA_9007_BINANCE_FUTURES_DEMO", "1"),
        ("MEGA_9007_BINANCE_FUTURES_TESTNET", "1"),
        ("MEGA_9007_BN_FUT_MODE", "testnet"),
        ("ELITE_PUBLIC_MAINNET_FALLBACK", "0"),
        ("BINANCE_LIVE_ORDERS", "0"),
        ("MEGA_LIVE_ORDERS", "1"),
        ("MEGA_SIM_ENABLED", "0"),
    ):
        os.environ[key] = val


def _reinit_binance_client_from_env() -> None:
    """Env kilidi sonrası global Binance client yenile."""
    global client
    import importlib

    from binance_futures_trader import config as bcfg
    import binance_futures_trader.client as bcl

    importlib.reload(bcfg)
    importlib.reload(bcl)
    try:
        client.close()
    except Exception:
        pass
    client = bcl.BinanceFuturesClient()


def _reinit_clients_after_9007_env() -> None:
    """Senaryo reload sonrası global + MEGA client'ı demo-fapi ile yenile."""
    if not _is_9007_process():
        return
    _lock_9007_demo_futures_env()
    _reinit_binance_client_from_env()
    try:
        from elite_trader import mega_live as ml

        ml._mega_client = None
    except Exception:
        pass


if _is_9007_process():
    _lock_9007_demo_futures_env()


def _is_9005_demo() -> bool:
    if not (
        os.environ.get("BINANCE_ELITE_PORT") == "9005"
        or (_scenario_path.is_file() and "8300_9005" in _scenario_path.name)
    ):
        return False
    return not _is_9005_mainnet()


try:
    from binance_futures_trader.network_ssl import apply_cert_env

    apply_cert_env()
except Exception:
    pass

# Senaryo 9005 demo: kök .env STARTING_BALANCE=22000 ezmesin
if _is_9005_demo():
    os.environ["STARTING_BALANCE"] = "5000"
    os.environ["BINANCE_LIVE_ORDERS"] = "1"
    os.environ["BN_FUT_MODE"] = "testnet"
    os.environ["BINANCE_FUTURES_DEMO"] = "1"
    os.environ["BINANCE_FUTURES_TESTNET"] = "1"
elif _is_9005_mainnet():
    _lock_9005_paper_env()
elif _is_mega_mainnet():
    os.environ.setdefault("ELITE_BIND_HOST", "127.0.0.1")
    if _is_9007_process():
        _lock_9007_demo_futures_env()
    elif _is_9006_process():
        _lock_9006_paper_env()
    else:
        os.environ.setdefault("BINANCE_FUTURES_DEMO", "0")
        os.environ.setdefault("BINANCE_FUTURES_TESTNET", "0")
        os.environ.setdefault("ELITE_DEMO_ONLY_DATA", "0")
        _mega_port = os.environ.get("BINANCE_ELITE_PORT", "").strip()
        if _mega_port == "9006":
            _lock_9006_paper_env()
# Demo futures — config importundan ÖNCE (mainnet senaryosu hariç)
os.environ.setdefault("AGGRESSIVE_HIGH_GROWTH", "1")
if not _is_9005_mainnet() and not _is_mega_mainnet():
    os.environ.setdefault("BN_FUT_MODE", "testnet")
    os.environ.setdefault("BINANCE_FUTURES_TESTNET", "1")
    os.environ.setdefault("BINANCE_FUTURES_DEMO", "1")
LIVE_ORDERS = os.environ.get("BINANCE_LIVE_ORDERS", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

ELITE_PORT = int(os.environ.get("BINANCE_ELITE_PORT", "9003"))
MEGA_PRIMARY_PORTS = frozenset({"9006", "9007"})
SCENARIO_FILE = str(_scenario_path.name) if _scenario_path.is_file() else "missing"
ELITE_BIND_HOST = os.environ.get("ELITE_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0"


def _create_binance_client() -> "BinanceFuturesClient":
    import importlib

    from binance_futures_trader import config as bcfg
    import binance_futures_trader.client as bcl

    importlib.reload(bcfg)
    importlib.reload(bcl)
    return bcl.BinanceFuturesClient()

import momentum_scanner as ms

ms._reload_paper_env_globals()

# elite_trader.scanner ile birebir aynı stake sınırları, max açık ve TP/SL çarpanları (import anındaki env)
from elite_trader.scanner import (
    TP_PCT,
    SL_PCT,
    TP_TRIGGER,
    max_open_positions,
    stake_bounds,
)
from elite_trader.capital_allocator import (
    active_capital_pct,
    compute_stake,
    snapshot as capital_snapshot,
)
from elite_trader.panel_strategy import (
    active_execution_mode,
    active_futures_mode,
    active_view_mode,
    evaluate_position_exit,
    execution_active_capital_pct,
    execution_max_open,
    execution_min_stake,
    execution_profile,
    mode_catalog,
    parallel_mode_ids,
    parallel_universe_report,
    position_age_seconds,
    set_execution_mode,
    set_view_mode,
    shadow_action,
    signal_passes_execution_mode,
    signal_passes_mode,
    entry_risk_for_execution,
    is_live_binance_motor,
    live_only_execution,
    mode_order,
    snapshot_for_ui as panel_strategy_snapshot,
    stake_targets,
)
from elite_trader import parallel_universe_engine as parallel_engine
from elite_trader.proposal_auto_apply import (
    apply_proposal_to_scenario,
    ensure_spike_quick_proposal,
    maybe_auto_apply_pending,
    proposal_satisfied,
)
from elite_trader.market_guards import can_trigger_sl
from elite_trader.sl_emergency_guard import (
    entry_risk_check,
    record_sl_emergency_close,
    snapshot_for_ui as sl_emergency_snapshot,
)
from elite_trader.loss_learner import (
    enqueue_loss_analysis,
    get_proposal,
    maybe_periodic_scan,
    set_proposal_status,
    snapshot_for_ui as loss_learner_snapshot,
    start_background as loss_learner_start,
)
from elite_trader.data_archive import snapshot_archives_for_ui
from elite_trader.mode_data_archive import (
    archive_detail_mode,
    archive_mode,
    close_binance_exchange_positions,
    collect_live_trades,
    list_mode_archives,
    reset_live_memory,
    reset_parallel_universe,
)
from elite_trader.trades_export import build_csv_export, build_zip_export
from elite_trader.settings_registry import restart_live_bot

from fastapi import Body, Cookie, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from binance_futures_trader.client import BinanceFuturesClient

client = _create_binance_client()
_wallet_cache: dict[str, Any] = {}
_positions_cache: list[dict[str, Any]] = []
_exchange_cache_ts: float = 0.0
_exchange_last_attempt_ts: float = 0.0
_exchange_refresh_lock = threading.Lock()
_exchange_positions_lock = threading.Lock()
_exchange_reconcile_lock = threading.Lock()
_exchange_poll_stop = threading.Event()
_exchange_poll_wake = threading.Event()
_exchange_poll_thread: threading.Thread | None = None
_exchange_fetch_executor: ThreadPoolExecutor | None = None
_exchange_position_poll_executor: ThreadPoolExecutor | None = None
_exchange_position_poll_last: float = 0.0
_exchange_position_poll_ms: float = 0.0
_exchange_position_poll_timeouts: int = 0
_exchange_api_ms_min: float = 0.0
_exchange_api_ms_ema: float = 0.0
_exchange_api_ms_last: float = 0.0
_exchange_api_ms_samples: int = 0
_wallet_cache_ts: float = 0.0
_positions_closing: set[int] = set()
_live_open_lock = threading.Lock()
_monitor_events: deque[dict[str, Any]] = deque(maxlen=80)
_monitor_events_lock = threading.Lock()


def _push_monitor_event(kind: str, **fields: Any) -> None:
    """position_monitor.py — demo açılış/kapanış olay günlüğü."""
    row: dict[str, Any] = {
        "ts_ms": int(time.time() * 1000),
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "kind": str(kind).upper(),
    }
    for k, v in fields.items():
        if v is not None and v != "":
            row[k] = v
    with _monitor_events_lock:
        _monitor_events.appendleft(row)


def _count_exchange_open_positions() -> int:
    """Borsa positionRisk — gerçek açık sayısı."""
    if not LIVE_ORDERS or client.paper:
        return 0
    n = 0
    for ep in _positions_cache:
        if abs(float(ep.get("contracts") or ep.get("positionAmt") or 0)) > 0:
            n += 1
    return n


def _live_slots_used(*, include_rescue: bool = True) -> int:
    n_local = len(positions)
    if not include_rescue:
        n_local = sum(1 for p in positions if not p.get("rescue_leg"))
    return max(n_local, _count_exchange_open_positions())


def _assert_live_open_slot(
    symbol: str = "", *, rescue: bool = False, hedge: bool = False
) -> bool:
    """BERSERK2 — eşzamanlı max açık (hedge/kurtarma ek slot)."""
    cap = execution_max_open()
    if rescue:
        from elite_trader.position_rescue import rescue_max_open_cap

        cap = rescue_max_open_cap(cap)
    elif hedge:
        from elite_trader.position_hedge import hedge_max_open_cap

        cap = hedge_max_open_cap(cap)
    used = _live_slots_used(include_rescue=rescue or hedge)
    if used >= cap:
        from elite_trader.fee_economics import report_exit_gate_block

        report_exit_gate_block(
            kind="blocked_max_open",
            symbol=symbol,
            reason="max_open",
            detail=(
                f"açık={used}/{cap} rescue={rescue} hedge={hedge} "
                f"(borsa={_count_exchange_open_positions()} yerel={len(positions)})"
            ),
        )
        return False
    return True


def _enforce_exchange_max_open() -> None:
    """Borsada cap aşımı varsa fazla pozisyonları kapat (kurtarma slotları hariç)."""
    if not LIVE_ORDERS or client.paper:
        return
    from elite_trader.position_rescue import is_rescue_position, rescue_max_open_cap
    from elite_trader.position_hedge import hedge_max_open_cap, is_hedge_leg

    cap = hedge_max_open_cap(rescue_max_open_cap(execution_max_open()))
    _refresh_positions_cache_only(force=True)
    eps = [
        ep
        for ep in (_positions_cache or [])
        if abs(float(ep.get("contracts") or 0)) > 0
    ]
    if len(eps) <= cap:
        return
    excess = eps[cap:]
    print(
        f"  ⚠ MAX_AÇIK aşımı borsada: {len(eps)}/{cap} — "
        f"{len(excess)} pozisyon kapatılıyor"
    )
    from elite_trader.fee_economics import no_loss_close_required

    skip_loss = no_loss_close_required(active_execution_mode())
    for ep in excess:
        unreal = float(ep.get("unrealized_pnl") or 0)
        sym = str(ep.get("symbol") or "")
        side = str(ep.get("side") or "")
        skip_rescue = any(
            is_rescue_position(p) or is_hedge_leg(p)
            for p in positions
            if p.get("symbol") == sym and p.get("side") == side
        )
        if skip_rescue:
            continue
        if skip_loss and unreal <= 0:
            print(
                f"  ↷ Cap düzeltme atlandı {ep.get('symbol')} "
                f"(uPnL=${unreal:.4f}, net- kapanış yok)"
            )
            continue
        coin = ep["coin"]
        close_side = "SHORT" if ep["side"] == "LONG" else "LONG"
        qty = client.round_qty(coin, float(ep["contracts"]))
        if qty <= 0:
            continue
        try:
            client.market_order(coin, close_side, qty, reduce_only=True)
            print(f"  ✓ Cap düzeltme: kapattı {ep.get('symbol')} {ep['side']}")
        except Exception as exc:
            print(f"  ⛔ Cap düzeltme {ep.get('symbol')}: {exc}")
        time.sleep(0.2)
    _refresh_positions_cache_only(force=True)


def _exchange_cache_ttl_sec() -> float:
    try:
        return float(os.getenv("ELITE_EXCHANGE_CACHE_TTL_SEC", "12"))
    except ValueError:
        return 12.0


def _exchange_position_refresh_sec() -> float:
    try:
        return float(os.getenv("ELITE_EXCHANGE_POSITION_REFRESH_SEC", "0.4"))
    except ValueError:
        return 0.4


def _exchange_position_timeout_sec() -> float:
    try:
        return float(os.getenv("ELITE_EXCHANGE_POSITION_TIMEOUT_SEC", "0.75"))
    except ValueError:
        return 0.75


def _exchange_wallet_refresh_sec() -> float:
    try:
        return float(os.getenv("ELITE_EXCHANGE_WALLET_REFRESH_SEC", "5.0"))
    except ValueError:
        return 5.0


def _exchange_wallet_timeout_sec() -> float:
    try:
        return float(os.getenv("ELITE_EXCHANGE_WALLET_TIMEOUT_SEC", "0.75"))
    except ValueError:
        return 0.75


def _record_position_risk_ms(ms: float) -> None:
    """Başarılı positionRisk süresi — poll aralığı/timeout otomatik ayar."""
    global _exchange_api_ms_min, _exchange_api_ms_ema, _exchange_api_ms_last
    global _exchange_api_ms_samples
    _exchange_api_ms_last = ms
    _exchange_api_ms_samples += 1
    if _exchange_api_ms_min <= 0:
        _exchange_api_ms_min = ms
    else:
        _exchange_api_ms_min = min(_exchange_api_ms_min, ms)
    if _exchange_api_ms_ema <= 0:
        _exchange_api_ms_ema = ms
    else:
        _exchange_api_ms_ema = _exchange_api_ms_ema * 0.88 + ms * 0.12
    if _exchange_api_ms_samples in (1, 5, 20) or _exchange_api_ms_samples % 50 == 0:
        print(
            f"  📡 positionRisk {ms:.0f}ms "
            f"(min={_exchange_api_ms_min:.0f} ema={_exchange_api_ms_ema:.0f}) "
            f"iv={_effective_position_poll_interval_sec() * 1000:.0f}ms "
            f"timeout={_effective_position_timeout_sec() * 1000:.0f}ms"
        )


def _effective_position_poll_interval_sec() -> float:
    """positionRisk poll aralığı — sabit taban (demo-fapi min ~323ms)."""
    return max(_exchange_position_refresh_sec(), 0.32)


def _position_risk_cache_age_sec() -> float:
    if not _exchange_cache_ts:
        return 9999.0
    return max(0.0, time.time() - float(_exchange_cache_ts))


def _position_risk_adaptive_enabled() -> bool:
    try:
        from elite_trader.position_risk_scheduler import adaptive_enabled

        return adaptive_enabled()
    except Exception:
        return False


def _position_risk_poll_plan(
    bulk: dict[str, float] | None = None,
) -> dict[str, Any]:
    from elite_trader.position_risk_scheduler import poll_plan

    has_open = bool(_positions_cache) or bool(positions)
    live_open = [p for p in positions if p.get("on_exchange")] if positions else []
    return poll_plan(
        positions=live_open or list(_positions_cache or []),
        cache_age_sec=_position_risk_cache_age_sec(),
        bulk=bulk,
        has_open=has_open,
    )


def _wake_exchange_position_poll() -> None:
    _exchange_poll_wake.set()


def _effective_position_timeout_sec(*, critical: bool = False) -> float:
    base = _exchange_position_timeout_sec()
    if critical:
        return max(base, 3.5)
    if _exchange_api_ms_min > 0:
        # Tek httpx lock — önde cüzdan/bookTicker varsa kuyruk 2× RTT olabilir
        live = max(_exchange_api_ms_ema * 2.5, _exchange_api_ms_min * 2.2) / 1000.0
        return max(base, live, 2.0)
    return max(base, 2.5)


def _async_hub_enabled() -> bool:
    try:
        from binance_futures_trader.async_hub import is_async_hub_enabled

        return is_async_hub_enabled()
    except Exception:
        return False


def _on_uds_wallet(wallet: dict[str, Any]) -> None:
    global _wallet_cache, _wallet_cache_ts
    if wallet:
        _wallet_cache = wallet
        _wallet_cache_ts = time.time()


def _on_uds_positions(pos: list[dict[str, Any]]) -> None:
    """Devre dışı — mark/uPnL yalnızca REST positionRisk (UDS/WS ile ezilmez)."""
    del pos
    return


def _hub_reconcile_exchange() -> None:
    _refresh_positions_cache_only(force=True)
    _schedule_exchange_reconcile(force=True)


def _exchange_fetch_executor_get() -> ThreadPoolExecutor:
    global _exchange_fetch_executor
    if _exchange_fetch_executor is None:
        _exchange_fetch_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="exchange-fetch"
        )
    return _exchange_fetch_executor


def _reset_exchange_fetch_executor() -> None:
    global _exchange_fetch_executor
    old = _exchange_fetch_executor
    _exchange_fetch_executor = None
    if old is not None:
        try:
            old.shutdown(wait=False)
        except Exception:
            pass


def _exchange_position_poll_executor_get() -> ThreadPoolExecutor:
    global _exchange_position_poll_executor
    if _exchange_position_poll_executor is None:
        _exchange_position_poll_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="exchange-pos-poll"
        )
    return _exchange_position_poll_executor


def _apply_positions_cache(pos: list[dict[str, Any]]) -> None:
    """positionRisk → önbellek; max/min unreal korunur."""
    global _positions_cache, _exchange_cache_ts
    old_map = {
        (
            str(ep.get("coin") or f"{ep.get('symbol', '')}").upper(),
            str(ep.get("side") or "LONG"),
        ): ep
        for ep in _positions_cache
    }
    for ep in pos:
        sym = str(ep.get("coin") or f"{ep.get('symbol', '')}").upper()
        side = str(ep.get("side") or "LONG")
        key = (sym, side)
        if key in old_map:
            old_ep = old_map[key]
            ep["max_unreal_seen"] = old_ep.get(
                "max_unreal_seen", float(ep.get("unrealized_pnl") or 0)
            )
            ep["min_unreal_seen"] = old_ep.get(
                "min_unreal_seen", float(ep.get("unrealized_pnl") or 0)
            )
    _positions_cache = pos
    _exchange_cache_ts = time.time()


def _refresh_positions_cache_only(
    *,
    force: bool = False,
    timeout_sec: float | None = None,
    min_interval_sec: float | None = None,
) -> bool:
    """Pozisyon motoru — yalnızca REST positionRisk; panel/cüzdan ile paylaşılmaz."""
    global _exchange_position_poll_last, _exchange_position_poll_ms
    global _exchange_position_poll_timeouts
    if not LIVE_ORDERS or client.paper:
        return False
    try:
        from elite_trader.network_guard import binance_rest_enabled

        if not binance_rest_enabled() and not force:
            return bool(_positions_cache)
    except Exception:
        pass
    now = time.time()
    iv = (
        min_interval_sec
        if min_interval_sec is not None
        else _effective_position_poll_interval_sec()
    )
    cache_age = (now - _exchange_cache_ts) if _exchange_cache_ts else 9999.0
    critical = force or cache_age > 30.0
    if (
        not force
        and _exchange_cache_ts
        and (now - _exchange_cache_ts) < iv
    ):
        return True
    if not force and now - _exchange_position_poll_last < iv * 0.45:
        return bool(_positions_cache)
    try:
        from elite_trader.network_guard import skip_rest

        if skip_rest() and not force:
            return bool(_positions_cache)
    except Exception:
        pass
    if critical:
        lock_ok = _exchange_positions_lock.acquire(blocking=True, timeout=2.5)
    else:
        lock_ok = _exchange_positions_lock.acquire(blocking=False)
    if not lock_ok:
        return bool(_positions_cache)
    _exchange_position_poll_last = now
    tout = timeout_sec if timeout_sec is not None else _effective_position_timeout_sec(
        critical=critical
    )
    t0 = time.perf_counter()
    try:
        fut = _exchange_position_poll_executor_get().submit(
            lambda: client.exchange_positions() or []
        )
        try:
            pos = fut.result(timeout=tout)
        except FuturesTimeoutError:
            _exchange_position_poll_timeouts += 1
            if _exchange_position_poll_timeouts in (1, 10, 50):
                print(
                    f"  ⚠ positionRisk timeout ({tout:.1f}s) — önbellek kullanılıyor"
                )
            try:
                from elite_trader.network_guard import note_failure

                note_failure(kind="exchange_positions_timeout")
            except Exception:
                pass
            return bool(_positions_cache)
        _exchange_position_poll_ms = (time.perf_counter() - t0) * 1000.0
        _record_position_risk_ms(_exchange_position_poll_ms)
        try:
            from elite_trader.network_guard import note_success

            note_success()
        except Exception:
            pass
        _apply_positions_cache(pos)
        return True
    except Exception:
        try:
            from elite_trader.network_guard import note_failure

            note_failure(kind="exchange_positions")
        except Exception:
            pass
        return bool(_positions_cache)
    finally:
        _exchange_positions_lock.release()


def _schedule_exchange_reconcile(*, force: bool = False) -> None:
    """Dust + yerel↔borsa eşleme — positionRisk hot path dışında."""
    if not LIVE_ORDERS or client.paper:
        return
    now = time.time()
    if not force and now - _exchange_reconcile_last < 60.0:
        return
    if not _exchange_reconcile_lock.acquire(blocking=False):
        return

    def _run() -> None:
        try:
            _reconcile_exchange_dust_positions(force=force)
            _reconcile_positions_with_exchange(force=force)
        except Exception:
            pass
        finally:
            _exchange_reconcile_lock.release()

    threading.Thread(target=_run, name="exchange-reconcile", daemon=True).start()


def _api_heavy_executor_get() -> ThreadPoolExecutor:
    global _api_heavy_executor
    if _api_heavy_executor is None:
        _api_heavy_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="api-heavy"
        )
    return _api_heavy_executor


def _reset_api_heavy_executor() -> None:
    global _api_heavy_executor
    old = _api_heavy_executor
    _api_heavy_executor = None
    if old is not None:
        try:
            old.shutdown(wait=False)
        except Exception:
            pass


def refresh_exchange_cache(
    *,
    force: bool = False,
    timeout_sec: float | None = None,
    min_interval_sec: float | None = None,
) -> None:
    """Cüzdan (+ gerekiyorsa positionRisk) — panel yolu; pozisyon motoru ayrı."""
    global _wallet_cache, _positions_cache, _exchange_cache_ts, _exchange_last_attempt_ts
    global _wallet_cache_ts
    if not LIVE_ORDERS or client.paper:
        return
    if _async_hub_enabled() and not force:
        try:
            from binance_futures_trader.async_hub import get_orchestrator

            orch = get_orchestrator()
            if orch:
                w = orch.uds.get_wallet()
                if w:
                    _wallet_cache = w
                    _wallet_cache_ts = time.time()
        except Exception:
            pass
    now = time.time()
    has_open = bool(_positions_cache)
    positions_fresh = bool(
        has_open
        and _exchange_cache_ts
        and (now - _exchange_cache_ts) < _effective_position_poll_interval_sec() * 1.4
    )
    wallet_ttl = _exchange_wallet_refresh_sec() if has_open else _exchange_cache_ttl_sec()
    if not force and _wallet_cache_ts and (now - _wallet_cache_ts) < wallet_ttl:
        if positions_fresh or not has_open:
            return
    min_iv = (
        min_interval_sec
        if min_interval_sec is not None
        else (_exchange_wallet_refresh_sec() if has_open else 5.0)
    )
    if force and now - _exchange_last_attempt_ts < min_iv:
        return
    try:
        from elite_trader.network_guard import is_degraded, skip_rest

        if skip_rest() and not force:
            return
    except Exception:
        pass
    if not _exchange_refresh_lock.acquire(blocking=False):
        return
    _exchange_last_attempt_ts = now
    tout = timeout_sec if timeout_sec is not None else _exchange_wallet_timeout_sec()

    def _fetch() -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
        # positionRisk ayrı exchange-poll thread — cüzdan yolunda birleştirme timeout yapar
        w = client.exchange_wallet()
        return w, None

    try:
        fut = _exchange_fetch_executor_get().submit(_fetch)
        try:
            w, pos = fut.result(timeout=tout)
        except FuturesTimeoutError:
            try:
                from elite_trader.network_guard import note_failure

                note_failure(kind="exchange_timeout")
            except Exception:
                pass
            print("  ⚠ exchange wallet timeout — önbellek kullanılıyor")
            return
        if w:
            try:
                from elite_trader.network_guard import note_success

                note_success()
            except Exception:
                pass
            _wallet_cache = w
            _wallet_cache_ts = time.time()
            if pos is not None:
                _apply_positions_cache(pos)
                _schedule_exchange_reconcile()
    except Exception:
        try:
            from elite_trader.network_guard import note_failure

            note_failure(kind="exchange_fetch")
        except Exception:
            pass
    finally:
        _exchange_refresh_lock.release()


_dust_reconcile_last: float = 0.0
_exchange_reconcile_last: float = 0.0


def _reconcile_exchange_dust_positions(*, force: bool = False) -> None:
    """Borsada kalan toz pozisyonları (min lot altı / düşük notional) kapat."""
    global _dust_reconcile_last, _positions_cache, _exchange_cache_ts
    if not LIVE_ORDERS or client.paper:
        return
    now = time.time()
    if not force and now - _dust_reconcile_last < 45.0:
        return
    try:
        thr = float(os.getenv("ELITE_DUST_NOTIONAL_USD", "8"))
    except ValueError:
        thr = 8.0
    closed_any = False
    for ep in list(_positions_cache):
        qty_raw = abs(float(ep.get("contracts") or 0))
        if qty_raw <= 0:
            continue
        coin = ep["coin"]
        rounded = client.round_qty(coin, qty_raw)
        mark = float(ep.get("mark_price") or ep.get("entry_price") or 0)
        notional = qty_raw * mark if mark > 0 else 0.0
        is_dust = rounded <= 0 or (notional > 0 and notional < thr)
        if not is_dust:
            continue
        close_qty = rounded if rounded > 0 else qty_raw
        close_side = "SHORT" if ep["side"] == "LONG" else "LONG"
        try:
            client.market_order(coin, close_side, close_qty, reduce_only=True)
            print(
                f"  🧹 Dust kapandı {ep.get('symbol')} qty={close_qty} "
                f"(~${notional:.2f})"
            )
            closed_any = True
        except Exception as exc:
            print(f"  ⚠ dust reconcile {ep.get('symbol')}: {exc}")
    _dust_reconcile_last = now
    if closed_any:
        time.sleep(0.25)
        _refresh_positions_cache_only(force=True)


_reconnect_in_progress: bool = False


def _try_reconnect_demo_api() -> bool:
    """SSL timeout sonrası arka planda demo API'ye tekrar bağlan."""
    global client, STARTING_CAPITAL, _wallet_cache, _positions_cache, _exchange_cache_ts
    global _reconnect_in_progress
    if not LIVE_ORDERS or not client.paper:
        return False
    if _reconnect_in_progress:
        return False
    _reconnect_in_progress = True
    new_c = None
    try:
        os.environ["BINANCE_AUTH_QUICK"] = "0"
        try:
            new_c = _create_binance_client()
        except Exception:
            new_c = None
    finally:
        _reconnect_in_progress = False
        os.environ["BINANCE_AUTH_QUICK"] = "1"
    if new_c is None or new_c.paper:
        if new_c:
            err = new_c._auth_error or "bağlantı yok"
            print(f"  ↻ Demo API denemesi başarısız: {err}")
            new_c.close()
        return False
    try:
        client.close()
    except Exception:
        pass
    client = new_c
    w = client.exchange_wallet()
    if not w:
        client.paper = True
        return False
    _wallet_cache = w
    _positions_cache = client.exchange_positions() or []
    _exchange_cache_ts = time.time()
    STARTING_CAPITAL = float(
        w.get("total_margin_balance")
        or w.get("total_wallet_balance")
        or STARTING_CAPITAL
    )
    print(
        f"  ✓ Demo API yeniden bağlandı — ${STARTING_CAPITAL:,.2f} USDT | canlı emir AÇIK"
    )
    return True

# 9003 modül düzeyi (polymarket db/portlarına dokunulmaz)
_symbol_last_close: dict[str, float] = {}
_symbol_last_loss_close: dict[str, float] = {}
last_avg_latency_ms: float = 0.0
last_scan_ms: float = 0.0
last_tick_ms: float = 0.0
last_position_price_ms: float = 0.0
_last_tick_at: float = 0.0
_last_motor_at: float = 0.0
_last_position_price_at: float = 0.0
_last_snapshot_build_ms: float = 0.0
_last_snapshot_at: float = 0.0
_paper_open_coins_cache: tuple[float, list[str]] = (0.0, [])
_last_fast_feed_coins: frozenset[str] = frozenset()
_paper_patch_counter: int = 0
_last_metrics_rollup_ts: float = 0.0
_position_price_stop = threading.Event()
_position_price_thread: threading.Thread | None = None
_fast_tick_stop = threading.Event()
_fast_tick_thread: threading.Thread | None = None
_fast_tick_counter: int = 0
_position_ts_cache: tuple[float, str] = (0.0, "")
_last_ws_snapshot: dict[str, Any] | None = None
_ticker_prices_cache: dict[str, Any] = {}
_elite_template_path = Path(__file__).parent / "elite_pro_template.html"
_panel_v2_dir = Path(__file__).parent / "panel" / "elite_v2"
_panel_v2_index = _panel_v2_dir / "index.html"
_panel_v2_paper_index = _panel_v2_dir / "paper.html"
_panel_v2_paper_9007 = _panel_v2_dir / "paper-9007.html"
def _panel_v2_enabled() -> bool:
    return os.getenv("ELITE_PANEL_V2", "1").strip().lower() in ("1", "true", "yes")


_html_template_cache = (
    _elite_template_path.read_text(encoding="utf-8")
    if _elite_template_path.exists()
    else "<h1>Elite Pro Dashboard</h1><p>Template not found.</p>"
)
_api_heavy_executor: ThreadPoolExecutor | None = None
_snapshot_refresh_stop = threading.Event()
_snapshot_refresh_thread: threading.Thread | None = None
_heavy_snap_cache: dict[str, Any] = {}
_heavy_snap_cache_ts: float = 0.0
_HEAVY_SNAP_TTL_SEC = 8.0
_modes_overview_cache: dict[str, Any] | None = None
_modes_overview_cache_ts: float = 0.0
_MODES_OVERVIEW_TTL_SEC = 12.0
_reversal_watch_cache: list[dict[str, Any]] = []
_reversal_watch_cache_ts: float = 0.0
_REVERSAL_WATCH_TTL_SEC = 2.5
_motor_scan_lock = threading.Lock()
_motor_stop = threading.Event()
_motor_scan_thread: threading.Thread | None = None
_motor_eval_cursor: int = 0
_motor_eval_executor: ThreadPoolExecutor | None = None
_entry_eval_cache: tuple[float, list[tuple[str, float]]] = (0.0, [])
_last_motor_eval_n: int = 0
_last_motor_candidates_n: int = 0
_motor_live_gate_left: int = 0
_last_paper_coin_count: int = 0
_position_price_wake = threading.Event()
_position_stall_events: list[dict[str, Any]] = []
_position_stalls_total: int = 0
_last_position_stall_log: float = 0.0
_last_position_missing_n: int = 0
_position_tick_seq: int = 0
_last_position_stall_by_kind: dict[str, float] = {}
_position_thread_generation: int = 0
_position_stuck_restarts: int = 0
_position_worker_grace_until: float = 0.0
_motor_recoveries: int = 0
_last_motor_recovery_ts: float = 0.0
_motor_thread_generation: int = 0
_fast_tick_generation: int = 0
_motor_stuck_restarts: int = 0
_watchdog_stop = threading.Event()
_watchdog_thread: threading.Thread | None = None
_connection_keeper_stop = threading.Event()
_connection_keeper_thread: threading.Thread | None = None
_last_demo_reconnect_try: float = 0.0
_last_api_warm_at: float = 0.0


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


def _position_price_budget_ms() -> float:
    return min(45.0, max(20.0, _env_float("ELITE_POSITION_PRICE_BUDGET_MS", 35.0)))


def _position_exit_budget_ms() -> float:
    return min(250.0, max(40.0, _env_float("ELITE_POSITION_EXIT_BUDGET_MS", 120.0)))


def _position_exit_every_n() -> int:
    return max(1, min(8, _env_int("ELITE_POSITION_EXIT_EVERY_N", 1)))


def _panel_refresh_sec() -> float:
    if _panel_api_only_mode():
        return max(0.30, min(0.60, _effective_position_poll_interval_sec()))
    return max(0.12, min(0.45, _env_float("ELITE_PANEL_REFRESH_SEC", 0.18)))


def _panel_api_only_mode() -> bool:
    """Panel yalnızca Binance REST (positionRisk/wallet) — WS overlay ve get_snapshot yok."""
    return os.getenv("ELITE_PANEL_API_ONLY", "0").strip().lower() in ("1", "true", "yes")


def _panel_uses_exchange_snapshot() -> bool:
    """API-only snapshot yalnızca canlı emir modunda; paper kitap panelde görünür."""
    return bool(_panel_api_only_mode() and LIVE_ORDERS and not client.paper)


def _position_stuck_threshold_sec() -> float:
    return max(2.0, _env_float("ELITE_POSITION_STUCK_SEC", 3.0))


def _position_price_max_age_ms() -> float:
    return max(60.0, min(800.0, _env_float("ELITE_POSITION_PRICE_MAX_AGE_MS", 450)))


def _position_check_interval(*, has_open: bool = True) -> float:
    # 9006 MEGA — açık pozisyon varken her zaman hızlı poll (su altında olsa bile)
    if os.environ.get("BINANCE_ELITE_PORT") in MEGA_PRIMARY_PORTS:
        try:
            from elite_trader.mega_live import mega_has_open, mega_motor_active

            if mega_motor_active() and mega_has_open():
                return max(0.008, _env_float("MEGA_FAST_EXIT_SEC", 0.010))
        except Exception:
            pass
    try:
        from elite_trader.mega_live import mega_has_open, mega_motor_active, mega_needs_fast_exit

        if mega_motor_active() and mega_has_open():
            if mega_needs_fast_exit() or _env_bool("MEGA_OPEN_FAST_POLL", True):
                return max(0.008, _env_float("MEGA_FAST_EXIT_SEC", 0.012))
    except Exception:
        pass
    if has_open:
        try:
            from elite_trader.mega_live import mega_needs_fast_exit

            if mega_needs_fast_exit():
                return max(0.010, _env_float("MEGA_FAST_EXIT_SEC", 0.012))
        except Exception:
            pass
        try:
            prof_val = execution_profile().get("position_check_sec")
            if prof_val is not None:
                return max(0.015, min(0.10, float(prof_val)))
        except Exception:
            pass
        return max(0.025, min(0.10, _env_float("ELITE_POSITION_CHECK_SEC", 0.03)))
    return max(0.25, _env_float("ELITE_POSITION_IDLE_SEC", 0.5))


def _any_open_positions_for_worker() -> bool:
    """Paper + ana live + MEGA canlı — position worker interval için."""
    if positions:
        return True
    try:
        if parallel_engine.open_position_coins():
            return True
    except Exception:
        pass
    try:
        from elite_trader.mega_live import mega_has_open

        if mega_has_open():
            return True
    except Exception:
        pass
    return False


def _position_stall_log_sec() -> float:
    return max(8.0, _env_float("ELITE_POSITION_STALL_LOG_SEC", 12.0))


def _position_stall_loop_mult() -> float:
    if os.environ.get("BINANCE_ELITE_PORT") in MEGA_PRIMARY_PORTS:
        return max(4.0, _env_float("MEGA_POSITION_STALL_LOOP_MULT", 10.0))
    return 4.0


def _note_position_stall(kind: str, detail: str) -> None:
    """Pozisyon fiyat/TP-SL gecikmesi — log + panel uyarısı."""
    global _position_stalls_total, _last_position_stall_log, _position_stall_events
    global _last_position_stall_by_kind
    now = time.time()
    _position_stalls_total += 1
    evt = {
        "ts": now,
        "kind": kind,
        "detail": detail[:120],
    }
    _position_stall_events = ([evt] + _position_stall_events)[:8]
    kind_last = _last_position_stall_by_kind.get(kind, 0.0)
    if now - kind_last < max(4.0, _position_stall_log_sec() * 0.5):
        return
    _last_position_stall_by_kind[kind] = now
    if now - _last_position_stall_log >= _position_stall_log_sec():
        _last_position_stall_log = now
        print(f"  ⚠ Pozisyon takip [{kind}]: {detail}")


def _wake_position_price() -> None:
    """Yeni açılış — position-price thread anında uyansın."""
    _position_price_wake.set()


MIN_EDGE = _env_float("ELITE_MIN_EDGE", 0.048)
MIN_FORMULA_SCORE = _env_float("ELITE_MIN_FORMULA_SCORE", 0.52)


def _scan_eval_top_n() -> int:
    """Global tarama top-N — stabil üst sınır 32."""
    base = max(16, min(32, _env_int("SCAN_EVAL_TOP_N", 24)))
    try:
        prof = execution_profile()
        n = prof.get("trade_top_n")
        if n is not None:
            base = max(base, min(32, int(n)))
    except Exception:
        pass
    return min(base, 32)


def _motor_scan_budget_sec() -> float:
    return max(0.2, min(1.5, _env_float("MOTOR_SCAN_BUDGET_MS", 600) / 1000.0))


def _motor_cycle_hard_timeout_sec() -> float:
    return _motor_scan_budget_sec() + max(0.35, _env_float("MOTOR_CYCLE_HARD_TIMEOUT_SEC", 0.5))


def _motor_stuck_threshold_sec() -> float:
    return max(6.0, _env_float("ELITE_MOTOR_STUCK_SEC", 10.0))


def _motor_gate_timeout_sec() -> float:
    return max(0.05, min(0.35, _env_float("ELITE_MOTOR_GATE_TIMEOUT_MS", 120) / 1000.0))


def _paper_signal_budget_sec() -> float:
    return max(0.05, min(0.5, _env_float("ELITE_PAPER_SIGNAL_BUDGET_MS", 150) / 1000.0))


def _worker_recovery_cooldown_sec() -> float:
    return max(5.0, min(20.0, _env_float("ELITE_WORKER_RECOVERY_COOLDOWN_SEC", 8.0)))


def _motor_symbols_per_cycle() -> int:
    return max(3, min(12, _env_int("MOTOR_SYMBOLS_PER_CYCLE", 6)))


def _motor_eval_executor_get() -> ThreadPoolExecutor:
    global _motor_eval_executor
    if _motor_eval_executor is None:
        _motor_eval_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="motor-eval"
        )
    return _motor_eval_executor


def _reset_motor_eval_executor() -> None:
    global _motor_eval_executor
    old = _motor_eval_executor
    _motor_eval_executor = None
    if old is not None:
        try:
            # cancel_futures=True yerel SSL/SQLite çağrılarında segfault riski — yeni executor hemen açılır.
            old.shutdown(wait=False)
        except Exception:
            pass


def _run_timed(fn: Callable[[], Any], timeout_sec: float, default: Any = None) -> Any:
    """Tek iş — süre aşımında varsayılan dön; executor sıfırlama (segfault riski)."""
    fut = _motor_eval_executor_get().submit(fn)
    try:
        return fut.result(timeout=max(0.05, timeout_sec))
    except FuturesTimeoutError:
        try:
            from elite_trader.network_guard import note_failure

            note_failure(kind="motor_gate_timeout")
        except Exception:
            pass
        return default
    except Exception:
        return default


def _entry_gate_timed(mode_id: str, candidate: dict[str, Any]) -> tuple[bool, str]:
    """Süre sınırlı gate — motor thread uzun hybrid değerlendirmede bloklanmaz."""
    out = _run_timed(
        lambda: parallel_engine.entry_gate_for_mode(mode_id, candidate),
        max(0.12, min(0.35, _motor_gate_timeout_sec() * 2.5)),
        default=(False, "gate_timeout"),
    )
    if isinstance(out, tuple) and len(out) == 2:
        return bool(out[0]), str(out[1] or "")
    return False, "gate_timeout"


def _force_restart_position_worker(*, reason: str) -> None:
    global _position_price_thread, _position_thread_generation, _position_stuck_restarts
    global _last_position_price_at, _position_worker_grace_until
    _position_stuck_restarts += 1
    _position_thread_generation += 1
    _position_price_stop.set()
    _position_price_wake.set()
    _position_price_thread = None
    _position_price_stop.clear()
    _last_position_price_at = time.time()
    _position_worker_grace_until = time.time() + max(
        8.0, _env_float("ELITE_POSITION_RESTART_GRACE_SEC", 12.0)
    )
    _start_position_price_worker()
    print(f"  🔄 Pozisyon fiyat thread yeniden başlatıldı (#{_position_stuck_restarts}): {reason}")


def _force_restart_motor_worker(*, reason: str) -> None:
    """Takılı/ölü motor-scan — yeni nesil thread (eski orphan bloklamaz)."""
    global _motor_scan_thread, _motor_thread_generation, _motor_stuck_restarts, _last_motor_at
    _motor_stuck_restarts += 1
    _motor_thread_generation += 1
    _motor_stop.set()
    _motor_scan_thread = None
    _motor_stop.clear()
    _last_motor_at = time.time()
    _start_motor_scan_worker()
    print(f"  🔄 Motor thread yeniden başlatıldı (#{_motor_stuck_restarts}): {reason}")


def _force_restart_fast_tick_worker(*, reason: str) -> None:
    global _fast_tick_thread, _fast_tick_generation, _last_tick_at
    _fast_tick_generation += 1
    _fast_tick_stop.set()
    _fast_tick_thread = None
    _fast_tick_stop.clear()
    _last_tick_at = time.time()
    _start_fast_tick_worker()
    print(f"  🔄 Evren tick yeniden başlatıldı: {reason}")


def _recover_motor_pipeline(*, reason: str, force_restart: bool = False) -> None:
    global _motor_recoveries, _last_motor_at, _last_motor_recovery_ts
    now = time.time()
    try:
        from elite_trader.network_guard import is_degraded

        if is_degraded() and not force_restart:
            return
    except Exception:
        pass
    if now - _last_motor_recovery_ts < _worker_recovery_cooldown_sec():
        return
    _last_motor_recovery_ts = now
    _motor_recoveries += 1
    print(f"  ⚠ Pipeline motor kurtarma #{_motor_recoveries}: {reason}")
    alive = bool(_motor_scan_thread and _motor_scan_thread.is_alive())
    if force_restart or not alive:
        _force_restart_motor_worker(reason=reason)
    else:
        _last_motor_at = now


def _momentum_flex_score(symbol: str, price: float) -> float:
    """build_raw_momentum_candidate_flex ile aynı pencereler — aday sıralama."""
    hist = price_history.get(symbol) or []
    if len(hist) < 3:
        return 0.0
    ui_lb = max(2, min(10, _env_int("UI_APPROACHING_LOOKBACK", 3)))
    short_pct = _env_float("ENTRY_SHORT_MOMENTUM_PCT", 0.025)
    best = 0.0
    for min_ticks, min_pct in ((20, 0.05), (10, 0.04), (ui_lb, short_pct)):
        if len(hist) <= min_ticks:
            continue
        old = float(hist[-min_ticks]["price"])
        if old <= 0:
            continue
        ch = abs((float(price) - old) / old * 100.0)
        if ch >= min_pct:
            best = max(best, ch)
    if best <= 0 and len(hist) >= 2:
        old = float(hist[-2]["price"])
        if old > 0:
            ch = abs((float(price) - old) / old * 100.0)
            if ch >= short_pct * 0.4:
                best = ch
    return best


def _fallback_volatile_candidates(
    prices: dict[str, float],
    *,
    limit: int = 16,
) -> list[tuple[str, float]]:
    """price_history — bulk fiyat eşleşmese bile volatil adaylar."""
    ui_lb = max(2, min(10, _env_int("UI_APPROACHING_LOOKBACK", 3)))
    min_pct = _env_float("UI_APPROACHING_MIN_PCT", 0.005)
    universe = set(watchlist) | tradable_symbols
    ranked: list[tuple[str, float, float]] = []
    for sym in universe:
        hist = price_history.get(sym) or []
        if len(hist) <= ui_lb:
            continue
        coin = sym.replace("USDT", "")
        fp = float(
            prices.get(coin) or prices.get(sym) or hist[-1].get("price") or 0
        )
        if fp <= 0:
            continue
        old = float(hist[-ui_lb]["price"])
        if old <= 0:
            continue
        ch = abs((fp - old) / old * 100.0)
        if ch >= min_pct:
            ranked.append((sym, fp, ch))
    ranked.sort(key=lambda x: -x[2])
    return [(s, fp) for s, fp, _ in ranked[:limit]]


def _collect_entry_eval_symbols_cached(
    prices: dict[str, float],
) -> list[tuple[str, float]]:
    global _entry_eval_cache
    now = time.time()
    if now - _entry_eval_cache[0] < 0.25 and _entry_eval_cache[1]:
        return _entry_eval_cache[1]
    ranked = _collect_entry_eval_symbols(prices)
    if not ranked:
        ranked = _fallback_volatile_candidates(prices, limit=_scan_eval_top_n())
    _entry_eval_cache = (now, ranked)
    return ranked


def _ui_tick_interval_sec() -> float:
    """527 evren fiyat tick — motor taramadan bağımsız, hızlı."""
    return max(0.15, min(1.0, _env_float("ELITE_UI_TICK_INTERVAL_SEC", 0.35)))


def _effective_motor_scan_interval_sec() -> float:
    """Motor eval aralığı — bütçeden büyük olmalı (üst üste binmesin)."""
    env_iv = _env_float("ELITE_SCAN_INTERVAL_SEC", 1.0)
    if env_iv <= 0:
        env_iv = 1.0
    prof_iv = env_iv
    try:
        prof = execution_profile()
        ex_iv = prof.get("scan_interval_sec")
        if ex_iv is not None and float(ex_iv) > 0:
            prof_iv = float(ex_iv)
    except Exception:
        pass
    floor_iv = _motor_scan_budget_sec() + 0.15
    return max(floor_iv, 0.25, min(env_iv, prof_iv))


def _effective_scan_interval_sec() -> float:
    return _effective_motor_scan_interval_sec()


def _normalize_universe_symbol(key: str, universe: set[str]) -> str | None:
    if key in universe:
        sym = key
    else:
        sym = key if str(key).endswith("USDT") else f"{key}USDT"
    return sym if sym in universe else None


def _market_cooldown_minutes() -> float:
    m = execution_profile()
    if m.get("market_cooldown_min") is not None:
        return float(m["market_cooldown_min"])
    return _env_float("ELITE_MARKET_COOLDOWN_MIN", 22)


def _market_cooldown_ok(symbol: str) -> bool:
    """Motor profili veya .env cooldown — aynı sembolden çok sık giriş önleme."""
    cool_min = _market_cooldown_minutes()
    t = _symbol_last_close.get(symbol)
    if t is not None and (time.time() - t) < cool_min * 60.0:
        return False
    loss_min = _env_float("ELITE_LOSS_SYMBOL_COOLDOWN_MIN", 8.0)
    lt = _symbol_last_loss_close.get(symbol)
    if lt is not None and (time.time() - lt) < loss_min * 60.0:
        return False
    return True


def _edge_from_signal(change_pct: float) -> float:
    """Momentum yüzdesini elite 'edge' ölçeğine map et (scanner ELITE_MIN_EDGE ile uyumlu)."""
    move = abs(float(change_pct)) / 100.0
    return min(0.35, move * 40.0)


def _formula_score_from_signal(change_pct: float) -> float:
    """ELITE_MIN_FORMULA_SCORE tabanlı sözde formül skoru."""
    move = abs(float(change_pct)) / 100.0
    return MIN_FORMULA_SCORE + min(0.23, move * 15.0)


def _crypto_kelly_from_signal(change_pct: float, side: str) -> float:
    """
    momentum_scanner.kelly_stake — Polymarket'teki ile aynı fonksiyon;
    sinyal LONG/SHORT için 0.30–0.70 fiyat bandına map edilir.
    """
    move = abs(float(change_pct)) / 100.0
    edge_like = min(0.35, move * 40.0)
    lo = _env_float("ELITE_MIN_ENTRY_PRICE", 0.30)
    hi = _env_float("ELITE_MAX_ENTRY_PRICE", 0.70)
    mid = (lo + hi) / 2.0
    if side == "LONG":
        entry_price = mid - edge_like * 0.15
        true_prob = mid + edge_like
    else:
        entry_price = mid + edge_like * 0.15
        true_prob = mid - edge_like
    entry_price = max(lo, min(hi, entry_price))
    true_prob = max(0.01, min(0.99, true_prob))
    yes_price = entry_price + (0.01 if side == "LONG" else -0.01)
    yes_price = max(lo, min(hi, yes_price))
    return ms.kelly_stake(true_prob, entry_price, yes_price=yes_price)


if ELITE_PORT == 9005:
    os.environ["STARTING_BALANCE"] = "5000"
    if _scenario_path.is_file():
        load_dotenv(_scenario_path, override=True)
    _lock_9005_paper_env()
    _reinit_binance_client_from_env()
elif ELITE_PORT in (9006, 9007) and _scenario_path.is_file():
    load_dotenv(_scenario_path, override=True)
    if ELITE_PORT == 9007:
        os.environ["MEGA_INSTANCE_ID"] = "9007"
        _lock_9007_demo_futures_env()
        _reinit_clients_after_9007_env()
    elif ELITE_PORT == 9006:
        os.environ["MEGA_INSTANCE_ID"] = "9006"
        _lock_9006_paper_env()
        _reinit_binance_client_from_env()
        try:
            from elite_trader import mega_live as ml

            ml._mega_client = None
        except Exception:
            pass
STARTING_CAPITAL = _env_float("STARTING_BALANCE", 5000.0)
_use_env_session = os.getenv("ELITE_SESSION_START_FROM_ENV", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
if LIVE_ORDERS and not client.paper and not _use_env_session:
    refresh_exchange_cache(force=True)
    if _wallet_cache:
        STARTING_CAPITAL = float(
            _wallet_cache.get("total_margin_balance")
            or _wallet_cache.get("total_wallet_balance")
            or STARTING_CAPITAL
        )
position_id_counter = 1
_exchange_synced = False
_recent_signal_keys: set[str] = set()
_sl_em_skip_logged: set[str] = set()

# Clear all state - no demo positions
positions = []
closed_positions = []


def _elite_state_enabled() -> bool:
    port = str(ELITE_PORT)
    profile = os.environ.get("PROFILE_NAME", "")
    return port == "9005" or "9005" in profile or "8300_9005" in profile


def _restore_closed_from_db() -> None:
    """Ana Hat: DB → closed_positions (eski yol). Paralel: kitaplara dağıt."""
    global closed_positions, position_id_counter, positions
    if not _elite_state_enabled():
        return
    try:
        from elite_pro_state import bootstrap_closed, load_closed

        loaded, next_id = bootstrap_closed(clear=False, auto_seed=False)
        all_rows = list(loaded or load_closed())
        exec_mid = active_execution_mode()
        parallel_rows = [
            c
            for c in all_rows
            if str(c.get("panel_mode") or c.get("execution_mode_at_close") or "")
            in parallel_mode_ids()
        ]
        if parallel_rows:
            mig = parallel_engine.migrate_legacy_live_trades(closed_rows=parallel_rows)
            if mig.get("moved_closed"):
                print(
                    f"  📦 Paralel kitaplara: {mig.get('moved_closed', 0)} kapalı"
                )
        closed_positions.clear()
        if is_live_binance_motor(exec_mid):
            closed_positions.extend(all_rows)
            _trim_closed_positions_ram()
        else:
            closed_positions.extend(
                [
                    c
                    for c in all_rows
                    if str(c.get("panel_mode") or exec_mid) == exec_mid
                    or str(c.get("execution_mode_at_close") or "") == exec_mid
                ]
            )
            book = parallel_engine.get_universe_book(exec_mid)
            for c in book.get("closed") or []:
                if c not in closed_positions:
                    closed_positions.append(c)
        position_id_counter = max(position_id_counter, next_id)
        all_ids = [
            int(p["id"])
            for p in closed_positions + positions
            if p.get("id") is not None
        ]
        if all_ids:
            position_id_counter = max(position_id_counter, max(all_ids) + 1)
        if closed_positions:
            print(
                f"  📥 Kapanmış işlem: {len(closed_positions)} "
                f"(motor={exec_mid})"
            )
    except Exception as exc:
        print(f"  ⚠ DB geçmiş yükleme: {exc}")


def _save_universe_cache(wl: list[str], tradable: set[str]) -> None:
    if len(wl) < 20:
        return
    try:
        _UNIVERSE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _UNIVERSE_CACHE_PATH.write_text(
            json.dumps(
                {
                    "watchlist": wl,
                    "tradable": sorted(tradable),
                    "saved_at": time.time(),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _load_universe_cache() -> dict[str, Any] | None:
    if not _UNIVERSE_CACHE_PATH.is_file():
        return None
    try:
        data = json.loads(_UNIVERSE_CACHE_PATH.read_text(encoding="utf-8"))
        wl = list(data.get("watchlist") or [])
        if len(wl) >= 20:
            return data
    except Exception:
        pass
    return None


def _apply_universe_fallback(reason: str) -> None:
    """API/SSL yokken tarama durmasın — önbellek veya varsayılan liste."""
    global watchlist, tradable_symbols, _watchlist_last_refresh
    cached = _load_universe_cache()
    if cached:
        watchlist = [str(s).upper() for s in cached["watchlist"]]
        tradable_symbols = set(cached.get("tradable") or watchlist)
    else:
        watchlist = list(_def_watch)
        top_n = _env_int("BINANCE_TRADE_TOP_N", 90)
        tradable_symbols = set(watchlist[:top_n] if top_n > 0 else watchlist)
    _watchlist_last_refresh = time.time()
    print(
        f"  ↻ Evren yedek ({reason}): {len(watchlist)} tarama | "
        f"çekirdek {len(tradable_symbols)}"
    )
    _save_universe_cache(watchlist, tradable_symbols)
    _init_parallel_engine()


def _maybe_expand_watchlist(base: list[str]) -> list[str]:
    """BINANCE_FULL_UNIVERSE=1 → tüm USDT perpetual tarama (Binance exchangeInfo)."""
    v = os.getenv("BINANCE_FULL_UNIVERSE", "").strip().lower()
    if v not in ("1", "true", "yes"):
        return base
    try:
        full = client.list_tradeable_usdt_perpetuals()
        if len(full) >= 100:
            print(f"📊 BINANCE_FULL_UNIVERSE: {len(full)} USDT-M perpetual")
            return full
    except Exception as exc:
        print(f"⚠️ BINANCE_FULL_UNIVERSE yedek liste: {exc}")
        cached = _load_universe_cache()
        if cached and len(cached.get("watchlist") or []) >= 50:
            wl = [str(s).upper() for s in cached["watchlist"]]
            print(f"  ↻ Evren önbellek: {len(wl)} sembol")
            return wl
    if base:
        return base
    return list(_def_watch)


def _session_wr() -> float | None:
    """Kapalı işlemlerden kazanma oranı (elite ELITE_WR_MIN_TRADES kadar örnek)."""
    n = _env_int("ELITE_WR_MIN_TRADES", 6)
    if len(closed_positions) < n:
        return None
    wins = sum(
        1 for p in closed_positions if p.get("final_pnl", p.get("net_pnl", 0)) > 0
    )
    return wins / len(closed_positions) if closed_positions else None


price_history = {}
_last_tick_price_at: dict[str, float] = {}  # coin → unix ts (scan/tick fiyat yaşı)
capital_history = []
signals = []
# Paralel motor (Evrim/Avcı/…) seçiliyken canlı emir kuyruğu — Ana Hat .env edge kapısından bağımsız
motor_signals: list[dict] = []
_motor_reject_stats: dict[str, int] = {}
_motor_queue_added: int = 0
_motor_orders_opened: int = 0
_last_motor_diag_log_ts: float = 0.0
_last_demo_order_ts: float = 0.0
# Geniş USDT-M perpetual universe (Polymarket'teki "çok market tarama" eşleniği; aynı elite giriş kuralları)
_def_watch = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'DOTUSDT',
    'AVAXUSDT', 'LINKUSDT', 'UNIUSDT', 'ATOMUSDT', 'LTCUSDT', 'NEARUSDT', 'AAVEUSDT', 'FILUSDT',
    'TRXUSDT', 'ETCUSDT', 'XLMUSDT', 'APTUSDT', 'ARBUSDT', 'OPUSDT', 'INJUSDT', 'SUIUSDT',
    'TIAUSDT', 'SEIUSDT', 'WLDUSDT', 'FETUSDT', 'ALGOUSDT', 'ICPUSDT', 'SANDUSDT', 'MANAUSDT',
    'THETAUSDT', 'EGLDUSDT', 'ZECUSDT', 'XTZUSDT', 'EOSUSDT', 'BCHUSDT', 'HBARUSDT', 'VETUSDT',
    'CRVUSDT', 'LDOUSDT', 'MKRUSDT', 'SNXUSDT', 'RUNEUSDT', 'CHZUSDT', 'APEUSDT', 'GMTUSDT',
]
_wl_raw = os.getenv("BINANCE_WATCHLIST", "").strip()
if _wl_raw:
    watchlist = [s.strip().upper() for s in _wl_raw.split(",") if s.strip()]
elif os.getenv("BINANCE_FULL_UNIVERSE", "").strip().lower() in ("1", "true", "yes"):
    watchlist = []
else:
    watchlist = list(_def_watch)
watchlist = _maybe_expand_watchlist(watchlist)
_watchlist_last_refresh: float = 0.0
tradable_symbols: set[str] = set()


def _use_full_universe() -> bool:
    return os.getenv("BINANCE_FULL_UNIVERSE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _evrim_runtime_enabled() -> bool:
    try:
        from elite_trader.mode_registry import enabled_mode_ids

        return "evrim" in enabled_mode_ids()
    except Exception:
        return False


def _watchlist_coin_set() -> set[str]:
    coins: set[str] = set()
    for s in watchlist or []:
        coins.add(str(s).upper().replace("USDT", ""))
    for s in tradable_symbols or []:
        coins.add(str(s).upper().replace("USDT", ""))
    try:
        from elite_trader.berserk2_movers import iter_tracked_symbols

        for s in iter_tracked_symbols():
            coins.add(str(s).upper().replace("USDT", ""))
    except Exception:
        pass
    try:
        for s in parallel_engine.open_position_coins():
            coins.add(str(s).upper().replace("USDT", ""))
    except Exception:
        pass
    return {c for c in coins if c}


def _filter_price_map(px: dict[str, float]) -> dict[str, float]:
    """527 coin REST yanıtını watchlist+top10 ile sınırla — RAM sızıntısı önleme."""
    if not px:
        return px
    if _use_full_universe():
        cap = max(80, _env_int("ELITE_PRICE_CACHE_MAX_COINS", 520))
        if len(px) <= cap:
            return px
        keep = _watchlist_coin_set()
        if keep:
            return {
                k: v
                for k, v in px.items()
                if str(k).upper().replace("USDT", "") in keep
            }
        return px
    allow = _watchlist_coin_set()
    if not allow:
        return px
    return {
        k: v
        for k, v in px.items()
        if str(k).upper().replace("USDT", "") in allow
    }


def _trim_global_price_caches() -> None:
    """_price_cache / mark_ws / deltas — yalnızca izlenen coinler."""
    if _use_full_universe():
        return
    coins = _watchlist_coin_set()
    if not coins:
        return
    sym_allow = coins | {f"{c}USDT" for c in coins}
    for k in list(price_history.keys()):
        ku = str(k).upper()
        if ku.replace("USDT", "") not in coins and ku not in sym_allow:
            price_history.pop(k, None)
    with _price_cache_lock:
        for store in (_price_cache, _price_cache_prev):
            for k in list(store.keys()):
                if str(k).upper().replace("USDT", "") not in coins:
                    store.pop(k, None)
    with _price_deltas_lock:
        for k in list(_price_deltas.keys()):
            if str(k).upper().replace("USDT", "") not in coins:
                _price_deltas.pop(k, None)
    try:
        from binance_futures_trader.mark_ws import trim_to_coins

        trim_to_coins(coins)
    except Exception:
        pass
    try:
        if _async_hub_enabled():
            from binance_futures_trader.async_hub import get_orchestrator

            orch = get_orchestrator()
            if orch and getattr(orch, "cache", None):
                orch.cache.trim_to_coins(coins)
    except Exception:
        pass


def _demo_trade_full_watchlist() -> bool:
    """Demo canlı — tarama evrenindeki tüm coinler emir çekirdeğine dahil."""
    if not LIVE_ORDERS:
        return False
    if os.getenv("BINANCE_FUTURES_DEMO", "").strip().lower() not in ("1", "true", "yes"):
        return False
    return os.getenv("ELITE_DEMO_TRADE_FULL_WATCHLIST", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def refresh_tradeable_universe(*, force: bool = False) -> list[str]:
    """Tüm perpetual tara; emir açma likit çekirdek (BINANCE_TRADE_TOP_N)."""
    global watchlist, tradable_symbols, _watchlist_last_refresh
    if not _use_full_universe():
        tradable_symbols = set(watchlist)
        return watchlist
    refresh_sec = _env_int("BINANCE_UNIVERSE_REFRESH_SEC", 3600)
    now = time.time()
    if (
        not force
        and now - _watchlist_last_refresh < refresh_sec
        and len(watchlist) >= 100
    ):
        return watchlist
    min_vol = _env_float("BINANCE_UNIVERSE_MIN_VOLUME_USDT", 3_000_000)
    top_n = _env_int("BINANCE_TRADE_TOP_N", 90)
    scan_all = os.getenv("BINANCE_SCAN_ALL_PERPETUALS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    try:
        ranked = client.usdt_perpetuals_by_volume(
            min_quote_volume_usd=min_vol,
            max_symbols=0,
        )
        if scan_all:
            full = client.list_tradeable_usdt_perpetuals()
            watchlist = full if len(full) >= 50 else ranked
        else:
            watchlist = ranked
        tradable_symbols = set(ranked[:top_n] if top_n > 0 else ranked)
        if _demo_trade_full_watchlist():
            tradable_symbols = set(watchlist)
        _watchlist_last_refresh = now
        if len(watchlist) < 50:
            _apply_universe_fallback("empty_ranked")
        else:
            _save_universe_cache(watchlist, tradable_symbols)
            print(
                f"📊 Evren: {len(watchlist)} perpetual taranıyor | "
                f"emir çekirdeği: {len(tradable_symbols)} (hacim≥${min_vol:,.0f}/24s)"
            )
    except Exception as exc:
        print(f"⚠️ Evren yenileme: {exc}")
        if len(watchlist) < 50:
            _apply_universe_fallback("api_fail")
    _init_parallel_engine()
    return watchlist


try:
    from elite_trader.sl_emergency_guard import bootstrap_from_disk as _bootstrap_sl_em

    _bootstrap_sl_em()
except Exception:
    pass

_scan_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scan")

_price_cache: dict[str, float] = {}
_price_cache_prev: dict[str, float] = {}   # önceki tur fiyatları — flash için
_price_cache_ts: float = 0.0
_PRICE_CACHE_TTL   = 60.0   # 60 sn — eski fiyat yavaş taramadan iyidir
_PRICE_CACHE_STALE_TTL = 600.0  # ağ kopukluğunda eski fiyat > tarama yok
_REST_REFRESH_INTERVAL = 0.5  # WS yokken REST — <1 sn fiyat hedefi
_price_cache_lock  = threading.Lock()
_rest_refresh_stop = threading.Event()
_price_deltas: dict[str, float] = {}  # coin → delta% (flash için)
_price_deltas_lock = threading.Lock()


def _save_price_cache() -> None:
    try:
        with _price_cache_lock:
            if len(_price_cache) < 5:
                return
            payload = {
                "prices": _price_cache,
                "saved_at": _price_cache_ts or time.time(),
            }
        _PRICE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PRICE_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _load_price_cache() -> None:
    global _price_cache_ts
    if not _PRICE_CACHE_PATH.is_file():
        return
    try:
        data = json.loads(_PRICE_CACHE_PATH.read_text(encoding="utf-8"))
        px = data.get("prices") or {}
        if len(px) < 5:
            return
        saved_at = float(data.get("saved_at") or 0)
        with _price_cache_lock:
            _price_cache.update({str(k).upper(): float(v) for k, v in px.items() if v})
            _price_cache_ts = saved_at or time.time()
        print(f"  ↻ Fiyat önbellek (disk): {len(_price_cache)} sembol")
    except Exception:
        pass


def _apply_price_bulk(px: dict[str, float], *, note_ok: bool = False) -> bool:
    """Fiyat haritasını bellek önbelleği + mark_ws'e yaz (REST/WS/tick ortak)."""
    global _price_cache_ts
    if not px:
        return False
    now = time.time()
    filtered = _filter_price_map(px)
    if not filtered:
        return False
    deltas2: dict[str, float] = {}
    with _price_cache_lock:
        for coin, price in filtered.items():
            old = _price_cache.get(coin, 0)
            if old and old > 0:
                deltas2[coin] = (price - old) / old * 100
        _price_cache_prev.update(_price_cache)
        _price_cache.update(filtered)
        _price_cache_ts = now
    if deltas2:
        with _price_deltas_lock:
            _price_deltas.update(deltas2)
    try:
        from binance_futures_trader.mark_ws import ingest_rest_prices

        ingest_rest_prices(filtered)
    except Exception:
        pass
    _trim_global_price_caches()
    try:
        _save_price_cache()
    except Exception:
        pass
    if note_ok:
        try:
            from elite_trader.network_guard import note_success

            note_success()
        except Exception:
            pass
    return True


def _prices_from_local_ticks(
    coins: list[str], *, max_age_sec: float | None = None
) -> dict[str, float]:
    """Fast-tick / scan kaydı — SSL kopuk olsa bile yerel taze fiyat."""
    if not coins:
        return {}
    now = time.time()
    max_age = max(
        0.4,
        float(max_age_sec or _env_float("ELITE_TICK_PRICE_MAX_AGE_SEC", 2.5)),
    )
    out: dict[str, float] = {}
    for raw in coins:
        coin = str(raw).upper().replace("USDT", "")
        ts = _last_tick_price_at.get(coin, 0.0)
        if ts <= 0 or (now - ts) > max_age:
            continue
        sym = f"{coin}USDT"
        hist = price_history.get(sym) or price_history.get(coin) or []
        px = 0.0
        if hist:
            px = float(hist[-1].get("price") or 0)
        if px <= 0:
            with _price_cache_lock:
                px = float(_price_cache.get(coin) or 0)
        if px > 0:
            out[coin] = px
    return out


def _ensure_ws_price_feeds(*, force_reconnect: bool = False) -> None:
    """Mark WS + bookTicker — demo REST'ten bağımsız canlı fiyat."""
    if _async_hub_enabled():
        return
    try:
        from binance_futures_trader.mark_ws import (
            ensure_mark_feed_started,
            feed_status,
            force_reconnect as mark_force_reconnect,
        )

        ensure_mark_feed_started()
        if force_reconnect:
            st = feed_status()
            lag = int(st.get("lag_ms") or 0)
            max_lag = _env_int("ELITE_WS_MAX_LAG_MS", 3500)
            if not st.get("connected") or lag > max_lag:
                mark_force_reconnect()
    except Exception:
        pass
    try:
        from binance_futures_trader.fast_price_ws import (
            ensure_fast_feed_started,
            fast_feed_status,
            force_reconnect as fast_force_reconnect,
        )

        coins: list[str] = []
        for c in _watchlist_coin_set():
            coins.append(str(c).replace("USDT", ""))
        try:
            from elite_trader.berserk2_movers import iter_tracked_symbols

            for sym in iter_tracked_symbols():
                c = sym.replace("USDT", "")
                if c and c not in coins:
                    coins.append(c)
        except Exception:
            pass
        for c in _all_open_position_coins(refresh_paper=True):
            if c and c not in coins:
                coins.append(c)
        ensure_fast_feed_started(_fast_feed_coin_list() or coins[:50])
        if force_reconnect:
            ff = fast_feed_status()
            if ff.get("enabled"):
                lag = int(ff.get("lag_ms") or 0)
                max_lag = _env_int("ELITE_WS_MAX_LAG_MS", 3500)
                if not ff.get("connected") or lag > max_lag:
                    fast_force_reconnect()
    except Exception:
        pass


def _demo_only_data_enabled() -> bool:
    """Yalnızca demo-fapi REST + resmi fstream WS — kamu mainnet yedek kapalı."""
    if os.getenv("ELITE_PUBLIC_MAINNET_FALLBACK", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    if os.getenv("ELITE_DEMO_ONLY_DATA", "1").strip().lower() in ("0", "false", "no"):
        return False
    return os.getenv("BINANCE_FUTURES_DEMO", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ) or os.getenv("BINANCE_LIVE_ORDERS", "").strip() in ("1", "true")


def _fetch_demo_fapi_prices(client: Any) -> dict[str, float]:
    """demo-fapi.binance.com — premiumIndex / ticker (mainnet yedek yok)."""
    px: dict[str, float] = {}
    try:
        from concurrent.futures import ThreadPoolExecutor

        from elite_trader.network_guard import rest_timeout_sec

        to = rest_timeout_sec(2.5)
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(client._get_price, "/fapi/v1/premiumIndex")
            raw = fut.result(timeout=to)
        if isinstance(raw, list):
            for row in raw:
                try:
                    sym = str(row.get("symbol", ""))
                    mp = row.get("markPrice") or row.get("price")
                    if sym.endswith("USDT") and mp:
                        px[sym.replace("USDT", "")] = float(mp)
                except Exception:
                    pass
    except Exception:
        pass
    if len(px) >= 5:
        return _filter_price_map(px)
    try:
        from concurrent.futures import ThreadPoolExecutor

        from elite_trader.network_guard import rest_timeout_sec

        to = rest_timeout_sec(2.5)
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(client._get_price, "/fapi/v1/ticker/price")
            raw2 = fut.result(timeout=to)
        if isinstance(raw2, list):
            for row in raw2:
                try:
                    sym = str(row["symbol"])
                    if sym.endswith("USDT"):
                        px[sym.replace("USDT", "")] = float(row["price"])
                except Exception:
                    pass
    except Exception:
        pass
    return _filter_price_map(px)


def _apply_demo_rest_prices(px: dict[str, float]) -> None:
    if len(px) < 5:
        return
    _apply_price_bulk(px)
    try:
        from binance_futures_trader.mark_ws import ingest_rest_prices

        ingest_rest_prices(px)
    except Exception:
        pass


def _fetch_public_mainnet_prices() -> dict[str, float]:
    """Kamu mainnet yedek — ELITE_DEMO_ONLY_DATA=1 iken kullanılmaz."""
    if _demo_only_data_enabled():
        return {}
    try:
        import urllib.request

        req = urllib.request.Request(
            "https://fapi.binance.com/fapi/v1/ticker/price",
            headers={"User-Agent": "elite-pro-price-fallback/1"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        out: dict[str, float] = {}
        if isinstance(raw, list):
            for row in raw:
                try:
                    sym = str(row["symbol"])
                    if sym.endswith("USDT"):
                        out[sym.replace("USDT", "")] = float(row["price"])
                except Exception:
                    pass
        return _filter_price_map(out)
    except Exception:
        return {}


def _rest_price_refresh_loop() -> None:
    """REST fiyat poller — her zaman çalışır, WS olsa da fiyat önbelleğini canlı tutar."""
    _last_px_update: float = 0.0

    while not _rest_refresh_stop.is_set():
        try:
            from elite_trader.network_guard import is_degraded, skip_rest

            wait_iv = _REST_REFRESH_INTERVAL
            if skip_rest() or is_degraded():
                wait_iv = max(
                    0.8,
                    _env_float("ELITE_PUBLIC_PRICE_INTERVAL_SEC", 1.5),
                )
        except Exception:
            wait_iv = _REST_REFRESH_INTERVAL
        _rest_refresh_stop.wait(wait_iv)
        if _rest_refresh_stop.is_set():
            break

        ws_ok = False
        if _async_hub_enabled():
            try:
                from binance_futures_trader.async_hub import get_orchestrator

                orch = get_orchestrator()
                if orch:
                    live = orch.get_all_prices_bulk(max_recv_age_sec=30)
                    if len(live) >= 5:
                        now = time.time()
                        live = _filter_price_map(live)
                        with _price_cache_lock:
                            _price_cache_prev.update(_price_cache)
                            _price_cache.update(live)
                            _price_cache_ts = now
                        _trim_global_price_caches()
                        _save_price_cache()
                        continue
            except Exception:
                pass
        if not ws_ok:
            try:
                from binance_futures_trader.mark_ws import feed_status

                ws_ok = feed_status().get("connected", False)
            except Exception:
                pass

        # WS aktifse mark_ws toplu önbellek — coin başı 2s filtresi düşük hacimli sembolleri düşürür
        if ws_ok and not _async_hub_enabled():
            try:
                from binance_futures_trader.mark_ws import get_mark_prices_bulk
                ws_px = get_mark_prices_bulk(max_recv_age_sec=30)
                if len(ws_px) >= 5:
                    now = time.time()
                    ws_px = _filter_price_map(ws_px)
                    with _price_cache_lock:
                        deltas: dict[str, float] = {}
                        for coin, price in ws_px.items():
                            old = _price_cache.get(coin, 0)
                            if old and old > 0:
                                deltas[coin] = (price - old) / old * 100
                        _price_cache_prev.update(_price_cache)
                        _price_cache.update(ws_px)
                        _price_cache_ts = now
                    if deltas:
                        with _price_deltas_lock:
                            _price_deltas.update(deltas)
                    _trim_global_price_caches()
                    _last_px_update = now
                    continue
            except Exception:
                pass

        # WS yok — REST ile tüm fiyatları çek (demo-only: yalnızca demo-fapi)
        try:
            try:
                from elite_trader.network_guard import skip_rest

                if skip_rest():
                    if _demo_only_data_enabled():
                        px = _fetch_demo_fapi_prices(client)
                        if len(px) >= 5:
                            _apply_demo_rest_prices(px)
                    else:
                        px = _fetch_public_mainnet_prices()
                        if len(px) >= 5:
                            _apply_price_bulk(px)
                    continue
            except Exception:
                pass
            px: dict[str, float] = {}
            if _demo_only_data_enabled():
                px = _fetch_demo_fapi_prices(client)
            elif client.paper or os.getenv("BINANCE_FUTURES_DEMO", "").strip() in (
                "1",
                "true",
                "yes",
            ):
                px = _fetch_public_mainnet_prices()
            if len(px) < 5 and not _demo_only_data_enabled():
                px = _fetch_demo_fapi_prices(client)
            if len(px) < 5 and not _demo_only_data_enabled():
                px = _fetch_public_mainnet_prices()
            if len(px) < 5:
                try:
                    from elite_trader.network_guard import rest_timeout_sec

                    to = rest_timeout_sec(3.0)
                    with ThreadPoolExecutor(max_workers=1) as ex:
                        fut = ex.submit(client.all_prices)
                        px = fut.result(timeout=to) or {}
                except Exception:
                    try:
                        from elite_trader.network_guard import note_failure

                        note_failure(kind="rest_all_prices")
                    except Exception:
                        pass
            if len(px) >= 5:
                if _demo_only_data_enabled():
                    _apply_demo_rest_prices(px)
                else:
                    _apply_price_bulk(px, note_ok=True)
        except Exception:
            try:
                from elite_trader.network_guard import note_failure

                note_failure(kind="rest_price")
            except Exception:
                pass


def _start_rest_price_refresher() -> None:
    t = threading.Thread(target=_rest_price_refresh_loop, name="rest-price-refresh", daemon=True)
    t.start()


def get_price_deltas() -> dict[str, float]:
    """Son REST turu fiyat değişimleri (%). Flash için."""
    with _price_deltas_lock:
        d = dict(_price_deltas)
        _price_deltas.clear()
    return d


def _bulk_prices_cached() -> dict[str, float]:
    """En güncel fiyatları döner: mark_ws önbellekten (WS veya REST enjekte).
    Fiyatlar biraz eski olsa bile döner — boş dönmez (82s yavaş taramayı önler)."""
    global _price_cache_ts
    now = time.time()

    # mark_ws önbelleği her zaman en taze — REST poller oraya da yazar
    if _async_hub_enabled():
        try:
            from binance_futures_trader.async_hub import get_orchestrator

            orch = get_orchestrator()
            if orch:
                ws = orch.get_all_marks_if_fresh(max_recv_age_sec=60)
                if len(ws) >= 5:
                    with _price_cache_lock:
                        _price_cache.update(ws)
                        _price_cache_ts = now
                    return dict(_price_cache)
        except Exception:
            pass
    try:
        from binance_futures_trader.mark_ws import get_mark_prices_bulk
        ws = get_mark_prices_bulk(max_recv_age_sec=60)
        if len(ws) >= 5:
            with _price_cache_lock:
                _price_cache.update(ws)
                _price_cache_ts = now
            return dict(_price_cache)
    except Exception:
        pass

    # Fallback: lokal önbellek (TTL içindeyse — 60s)
    with _price_cache_lock:
        if _price_cache and (now - _price_cache_ts) < _PRICE_CACHE_TTL:
            return dict(_price_cache)

    # Son çare: doğrudan REST (non-blocking: son bilinen değeri döndür)
    try:
        px = client.all_prices()
        if len(px) >= 5:
            with _price_cache_lock:
                _price_cache.update(px)
                _price_cache_ts = now
            return dict(_price_cache)
    except Exception:
        pass

    # Kesinlikle son çare: TTL süresi dolmuş olsa da döndür
    with _price_cache_lock:
        if _price_cache:
            return dict(_price_cache)
    return {}


def _stale_price_cache_ttl() -> float:
    try:
        from elite_trader.network_guard import is_degraded

        return _PRICE_CACHE_STALE_TTL if is_degraded() else _PRICE_CACHE_TTL
    except Exception:
        return _PRICE_CACHE_TTL


def _bulk_prices_cached_fast() -> dict[str, float]:
    """Motor/tick hot path — WS + bellek; ağ yoksa eski önbellek."""
    global _price_cache_ts
    now = time.time()
    if _async_hub_enabled():
        try:
            from binance_futures_trader.async_hub import get_orchestrator

            orch = get_orchestrator()
            if orch:
                live = orch.get_all_prices_bulk(max_recv_age_sec=60)
                if len(live) >= 5:
                    with _price_cache_lock:
                        _price_cache.update(live)
                        _price_cache_ts = now
                    return dict(_price_cache)
        except Exception:
            pass
    try:
        from binance_futures_trader.mark_ws import get_mark_prices_bulk

        ws = get_mark_prices_bulk(max_recv_age_sec=60)
        if len(ws) >= 5:
            with _price_cache_lock:
                _price_cache.update(ws)
                _price_cache_ts = now
            return dict(_price_cache)
    except Exception:
        pass
    stale_ttl = _stale_price_cache_ttl()
    with _price_cache_lock:
        if _price_cache:
            if not _price_cache_ts or (now - _price_cache_ts) < stale_ttl:
                return dict(_price_cache)
            try:
                from elite_trader.network_guard import is_degraded

                if is_degraded():
                    return dict(_price_cache)
            except Exception:
                return dict(_price_cache)
    return {}


def fetch_price(symbol: str) -> tuple[float, float]:
    bulk = _bulk_prices_cached()
    coin = symbol.replace("USDT", "")
    if coin in bulk:
        return float(bulk[coin]), 1.0
    if symbol in bulk:
        return float(bulk[symbol]), 1.0
    try:
        start = time.time()
        price = client.mark_price(coin)
        latency = (time.time() - start) * 1000
        if price:
            return float(price), latency
    except Exception as e:
        print(f"❌ {symbol}: {e}")
    return 0.0, 0.0

def _motor_session_start() -> float:
    m = execution_profile()
    return float(m.get("starting_balance") or _env_float("STARTING_BALANCE", 5000.0))


def get_current_capital() -> float:
    if LIVE_ORDERS and not client.paper and _wallet_cache:
        return float(
            _wallet_cache.get("total_margin_balance")
            or _wallet_cache.get("total_wallet_balance")
            or _wallet_cache.get("available_balance")
            or STARTING_CAPITAL
        )
    total_pnl = sum(p['unrealized_pnl'] for p in positions)
    realized_pnl = sum(p.get('final_pnl', p.get('pnl_usd', 0)) for p in closed_positions)
    return _motor_session_start() + realized_pnl + total_pnl


def _is_mega_primary_process() -> bool:
    """9006/9007 veya yalnızca MEGA canlı/sim — ana panel MEGA API'sini gösterir."""
    if str(os.environ.get("BINANCE_ELITE_PORT", "")).strip() in MEGA_PRIMARY_PORTS:
        return True
    try:
        from elite_trader.mega_live import mega_motor_active
        from elite_trader.mode_registry import enabled_mode_ids

        modes = list(enabled_mode_ids())
        return mega_motor_active() and modes == ["mega"]
    except Exception:
        return False


def _mega_motor_enabled() -> bool:
    try:
        from elite_trader.mega_live import mega_motor_active

        return mega_motor_active()
    except Exception:
        return False


def _mega_api_client():
    try:
        from elite_trader.mega_live import mega_live_enabled, get_mega_client

        if not mega_live_enabled():
            return None
        mc = get_mega_client()
        if mc and not mc.paper:
            return mc
    except Exception:
        pass
    return None


def _api_healthy() -> bool:
    if LIVE_ORDERS and not client.paper:
        try:
            if _wallet_cache:
                return True
            return bool(client)
        except Exception:
            return False
    if _mega_api_client() is not None:
        return True
    return False


def _try_execute_signal(signal: dict) -> bool:
    """Yakalanan sinyali demo borsaya MARKET emir olarak gönder (seçili motor profili)."""
    if not LIVE_ORDERS or client.paper:
        return False
    try:
        from elite_trader.mode_registry import berserk2_paper_only

        if active_execution_mode() == "berserk2" and berserk2_paper_only():
            return False
    except Exception:
        pass
    from elite_trader.order_gate import (
        build_order_intent,
        route_order,
        run_live_preflight_checks,
    )

    ex_mid = active_execution_mode()
    intent = build_order_intent(ex_mid, signal=signal)
    gate = route_order(
        ex_mid,
        intent,
        active_futures_mode=active_futures_mode(),
        api_healthy=_api_healthy(),
        live_orders_enabled=LIVE_ORDERS and not client.paper,
    )
    if not gate.send_live:
        return False
    exec_mid = active_execution_mode()
    # Evrim hybrid skor >= 55 ise "Weak" raw momentumı geç; aksi halde Strong/Medium gerekli
    _hybrid_ok = bool(
        (signal.get("evrim_hybrid") or {}).get("total_score", 0) >= 55
    )
    if exec_mid not in ("berserk", "berserk2"):
        if signal.get("strength") not in ("Strong", "Medium") and not _hybrid_ok:
            _motor_reject("weak_no_hybrid")
            return False
    symbol = str(signal.get("symbol") or "")
    _evrim_exec_log = exec_mid == "evrim"

    def _elog(**kw: Any) -> None:
        if not _evrim_exec_log:
            return
        try:
            from elite_trader.evrim_risk_policy import log_execution_stage

            log_execution_stage(symbol, **kw)
        except Exception:
            pass

    if _evrim_exec_log:
        _elog(signal_passed=True, reason="signal_strength_ok")

    ok_ex, ex_reason = parallel_engine.entry_gate_for_mode(exec_mid, signal)
    if not ok_ex:
        _motor_reject(str(ex_reason or "hybrid_fail")[:48])
        sym = symbol or "?"
        _elog(risk_passed=False, reason=str(ex_reason or "hybrid_fail")[:120])
        key = f"{sym}:{ex_reason}"
        if key not in _sl_em_skip_logged:
            _sl_em_skip_logged.add(key)
            if len(_sl_em_skip_logged) > 80:
                _sl_em_skip_logged.clear()
            print(f"  ⛔ Motor filtresi {sym}: {ex_reason} [{active_execution_mode()}]")
        return False
    _elog(risk_passed=True, reason="hybrid_gate_ok")
    ch = float(signal.get("change") or 0)
    in_core = not tradable_symbols or symbol in tradable_symbols
    if not in_core and exec_mid == "evrim":
        try:
            from elite_trader.evrim_risk_policy import (
                maybe_temp_universe,
                temp_universe_symbols,
            )

            sc = float(signal.get("evrim_hybrid_score") or 0)
            ctx_u = {"vol_ratio": 1.5, "spread_pct": 0.06, "price": 1.0}
            if sc >= 70 or maybe_temp_universe(
                symbol, sc, ctx_u, tradable_symbols, execution_profile()
            ):
                in_core = symbol in tradable_symbols or symbol in temp_universe_symbols()
        except Exception:
            pass
    if tradable_symbols and not in_core:
        _motor_reject("not_in_universe")
        _elog(execution_passed=False, reason="not_in_universe")
        return False
    side = signal["type"]
    fs = _formula_score_from_signal(ch)
    ok_risk, risk_reason, risk_tier = entry_risk_for_execution(
        symbol, side, str(signal.get("strength") or ""), ch, fs
    )
    if not ok_risk:
        _motor_reject(risk_tier or "risk")
        _elog(execution_passed=False, reason=str(risk_reason or risk_tier)[:120])
        key = f"{symbol}:{risk_tier}:{risk_reason[:40]}"
        if key not in _sl_em_skip_logged:
            _sl_em_skip_logged.add(key)
            if len(_sl_em_skip_logged) > 80:
                _sl_em_skip_logged.clear()
            print(f"  ⛔ Giriş atlandı {symbol} {side}: {risk_reason}")
        return False
    _elog(execution_passed=True, reason="entry_risk_ok")
    if risk_tier == "cautious":
        print(f"  ⚠ Temkinli giriş {symbol} {side}: {risk_reason}")
    if any(p["symbol"] == symbol for p in positions):
        _elog(execution_passed=False, reason="already_open")
        return False
    max_open = execution_max_open()
    if exec_mid == "evrim":
        try:
            chop_cap = int(execution_profile().get("evrim_chop_max_open") or 0)
            if chop_cap > 0:
                max_open = min(max_open, chop_cap)
        except Exception:
            pass
    with _live_open_lock:
        _refresh_positions_cache_only(force=True)
        slots_used = _live_slots_used()
        if slots_used >= max_open or _emergency_equity_block():
            if slots_used >= max_open:
                from elite_trader.fee_economics import report_exit_gate_block

                report_exit_gate_block(
                    kind="blocked_max_open",
                    symbol=symbol,
                    reason="max_open",
                    detail=(
                        f"açık={slots_used}/{max_open} "
                        f"(borsa={_count_exchange_open_positions()} "
                        f"yerel={len(positions)})"
                    ),
                )
            _elog(execution_passed=False, reason="max_open_or_emergency")
            return False
    key = f"{symbol}:{side}:{signal.get('time')}"
    if key in _recent_signal_keys:
        return False
    _elog(order_sent=True, reason="open_position_call")
    pos = open_position(
        symbol,
        side,
        ch,
        leverage=0,
        signal_source=f"Signal-{signal.get('strength')}",
        signal_row=signal,
    )
    if pos:
        global _last_demo_order_ts, _motor_orders_opened
        _last_demo_order_ts = time.time()
        _motor_orders_opened += 1
        _recent_signal_keys.add(key)
        if len(_recent_signal_keys) > 200:
            _recent_signal_keys.clear()
        if _evrim_exec_log:
            try:
                from elite_trader.evrim_risk_policy import record_exchange_open

                record_exchange_open()
            except Exception:
                pass
            _elog(
                exchange_accepted=True,
                execution_passed=True,
                reason="exchange_open_ok",
            )
        return True
    _elog(exchange_accepted=False, reason="open_position_failed")
    return False


def _leverage_for_signal(strength: str, requested: int) -> int:
    base = _env_int("BINANCE_DEFAULT_LEVERAGE", 5)
    lev_min = _env_int("BINANCE_LEVERAGE_MIN", 3)
    lev_max = _env_int("BINANCE_LEVERAGE_MAX", 8)
    if requested > 0:
        lev = max(lev_min, min(lev_max, requested))
    elif strength == "Strong":
        lev = min(lev_max, base + 2)
    elif strength == "Medium":
        lev = base
    else:
        lev = max(lev_min, base - 1)
    if active_execution_mode() == "berserk2":
        cap = _env_int("BERSERK2_MAX_LEVERAGE", 3)
        if cap > 0:
            lev = min(lev, cap)
    return lev


def _reconcile_positions_with_exchange(*, force: bool = False) -> dict[str, Any]:
    """
    Borsa ↔ yerel liste ↔ mod kitabı — hayalet açıkları temizle, eksikleri al.
    Canlı emir modunda panel sayısı Binance ile eşit kalmalı.
    """
    global positions, position_id_counter, _exchange_reconcile_last
    out: dict[str, Any] = {"removed_local": 0, "imported": 0, "book": {}}
    if not LIVE_ORDERS or client.paper:
        return out
    now = time.time()
    if not force and now - _exchange_reconcile_last < 60.0:
        return out
    _exchange_reconcile_last = now

    if not _positions_cache:
        _refresh_positions_cache_only(force=True)
    exch = list(_positions_cache)
    from elite_trader.exchange_position_sync import exchange_map_by_symbol_side

    emap = exchange_map_by_symbol_side(exch)

    removed = 0
    for pos in list(positions):
        if not pos.get("on_exchange"):
            continue
        key = (str(pos["symbol"]), str(pos["side"]))
        if key not in emap:
            absent = _exchange_position_absent_confirmed(pos["symbol"], pos["side"])
            if absent is not True:
                continue
            if close_position(int(pos["id"]), "SYNC-EXCHANGE"):
                removed += 1
    out["removed_local"] = removed

    try:
        book_out = parallel_engine.reconcile_books_with_exchange(
            exch, mode_id=active_execution_mode(), force=force
        )
        out["book"] = book_out
        if book_out.get("removed"):
            print(
                f"  ↻ Kitap senkron: borsa={book_out.get('exchange_open', 0)} "
                f"kitap={book_out.get('book_open_after', 0)} "
                f"silinen={len(book_out.get('removed') or [])}"
            )
    except Exception as exc:
        out["book_error"] = str(exc)

    if not exch:
        return out

    local_keys = {
        (str(p["symbol"]), str(p["side"]))
        for p in positions
        if p.get("on_exchange")
    }
    cap = execution_max_open()
    imported = 0
    for ep in exch:
        sym = str(ep.get("symbol") or f"{ep.get('coin')}USDT")
        side = str(ep.get("side") or "LONG")
        if (sym, side) in local_keys:
            continue
        if len(positions) >= cap:
            break
        entry = float(ep.get("entry_price") or 0)
        size = float(ep.get("contracts") or 0)
        if size <= 0 or entry <= 0:
            continue
        lev = int(ep.get("leverage") or _env_int("BINANCE_DEFAULT_LEVERAGE", 5))
        from elite_trader.exchange_position_sync import live_tp_sl_usd

        stake = size * entry / max(lev, 1)
        notional = float(ep.get("notional_usd") or 0)
        if notional > 0 and lev > 0:
            stake = notional / lev
        tp_usd, sl_usd = live_tp_sl_usd(stake, lev)
        if side == "LONG":
            tp_price = entry + tp_usd / size if size > 0 else entry
            sl_price = entry - sl_usd / size if size > 0 else entry
        else:
            tp_price = entry - tp_usd / size if size > 0 else entry
            sl_price = entry + sl_usd / size if size > 0 else entry
        opened_iso = datetime.now(timezone.utc).isoformat()
        row = {
            "id": position_id_counter,
            "symbol": sym,
            "side": side,
            "entry_price": entry,
            "current_price": float(ep.get("mark_price") or entry),
            "size": size,
            "leverage": lev,
            "stake_usd": stake,
            "position_value": size * entry,
            "unrealized_pnl": float(ep.get("unrealized_pnl") or 0),
            "exchange_synced": True,
            "pnl_pct": 0.0,
            "entry_time": time.time(),
            "entry_time_str": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "opened_at_iso": opened_iso,
            "tp_target": tp_price,
            "sl_target": sl_price,
            "tp_target_usd": tp_usd,
            "sl_target_usd": sl_usd,
            "price_history": [entry],
            "time_history": [datetime.utcnow().isoformat()],
            "entry_fee": 0.0,
            "total_fees": 0.0,
            "edge": 0.0,
            "formula_score": MIN_FORMULA_SCORE,
            "signal_source": "ExchangeSync",
            "signal_strength": "Medium",
            "on_exchange": True,
            "panel_mode": active_execution_mode(),
        }
        positions.append(row)
        position_id_counter += 1
        imported += 1
        local_keys.add((sym, side))
        try:
            from elite_trader.exchange_trade_truth import enrich_open_entry_fee_api

            enrich_open_entry_fee_api(row, client, allow_fetch=True)
        except Exception:
            pass
        try:
            parallel_engine.record_live_open(active_execution_mode(), row)
        except Exception:
            pass
        print(f"  ↻ Borsadan alındı: {side} {sym} qty={size} lev={lev}x")
        _push_monitor_event(
            "SYNC",
            symbol=sym,
            side=side,
            entry_price=entry,
            size=size,
            leverage=lev,
            stake_usd=stake,
            source="ExchangeSync",
        )
    out["imported"] = imported
    if len(positions) > cap:
        print(
            f"  ⚠ MAX_AÇIK aşımı: {len(positions)} açık pozisyon "
            f"(limit {cap}) — yeni giriş kapalı, mevcutlar yalnızca TP ile kapanır"
        )
    _enforce_exchange_max_open()
    return out


def _sync_positions_from_exchange() -> None:
    """Borsadaki açık pozisyonları yerel listeye al (yeniden başlatma sonrası)."""
    global _exchange_synced, _positions_cache, _exchange_cache_ts
    if not LIVE_ORDERS or client.paper or _exchange_synced:
        return
    _exchange_synced = True
    try:
        _refresh_positions_cache_only(force=True)
        refresh_exchange_cache(force=True, min_interval_sec=0)
    except Exception as exc:
        print(f"  ⚠ Borsa pozisyon senkronu: {exc}")
    out = _reconcile_positions_with_exchange(force=True)
    if not _positions_cache:
        print("  ↻ Senkron: borsa açık pozisyon yok")
    elif out.get("imported"):
        print(f"  ↻ Senkron: {out['imported']} pozisyon içe aktarıldı")


def _emergency_equity_block() -> bool:
    """Öz sermaye agresif düşerse yeni giriş yok (varsayılan STARTING_BALANCE altı %35)."""
    frac = _env_float("BINANCE_EMERGENCY_EQUITY_FRAC", 0.35)
    return get_current_capital() < STARTING_CAPITAL * frac


def _init_parallel_engine() -> None:
    from elite_trader.mode_registry import enabled_mode_ids

    tradable = set(tradable_symbols or watchlist or [])
    if _demo_trade_full_watchlist() and watchlist:
        tradable = set(watchlist)
    scan_u: set[str] | None = set(watchlist) if watchlist else None
    enabled = enabled_mode_ids()
    if enabled == ("berserk2",) or (
        "mega" not in enabled and len(enabled) == 1
    ):
        scan_u = None
    elif "mega" in enabled:
        scan_u = None
    parallel_engine.configure(
        edge_fn=_edge_from_signal,
        formula_fn=_formula_score_from_signal,
        kelly_fn=_crypto_kelly_from_signal,
        risk_fn=entry_risk_check,
        min_edge=MIN_EDGE,
        min_formula=MIN_FORMULA_SCORE,
        session_start=_env_float("STARTING_BALANCE", 5000.0),
        stake_bounds_fn=stake_bounds,
        max_open_fn=max_open_positions,
        wr_fn=_session_wr,
        leverage_fn=_leverage_for_signal,
        tradable_symbols=tradable,
        scan_universe=scan_u,
    )
    parallel_engine.set_paper_open_callback(_wake_position_price)
    if live_only_execution():
        n = parallel_engine.clear_paper_open_positions()
        if n:
            print(f"  ↻ Live-only: {n} paper/gölge açık pozisyon kitaptan silindi")
    else:
        parallel_engine.start_paper_signal_worker()
    if _use_env_session:
        from elite_trader.mode_registry import enabled_mode_ids

        cap = _env_float("STARTING_BALANCE", 5000.0)
        if cap > 0:
            for mid in enabled_mode_ids():
                parallel_engine.sync_session_start(cap, mode_id=mid)
    else:
        parallel_engine.sync_session_start(_env_float("STARTING_BALANCE", 5000.0))


_init_parallel_engine()

_load_price_cache()

if _use_full_universe():
    refresh_tradeable_universe(force=True)
    if len(watchlist) < 50:
        _apply_universe_fallback("boot")
else:
    tradable_symbols = set(watchlist)
    _init_parallel_engine()

def _place_live_entry_order(
    coin: str,
    side: str,
    qty: float,
    entry_price: float,
    *,
    signal_row: dict | None,
) -> dict[str, Any]:
    """Evrim execution optimizer planına göre market/limit/maker giriş."""
    exec_plan = (signal_row or {}).get("evrim_execution") or {}
    order_type = str(exec_plan.get("order_type") or "market").lower()
    if bool(exec_plan.get("partial_entry")):
        qty = client.round_qty(coin, qty * 0.5)

    if order_type in ("limit", "maker") and entry_price > 0:
        slip = 0.0005 if order_type == "maker" else 0.001
        if side == "LONG":
            limit_px = entry_price * (1.0 - slip)
        else:
            limit_px = entry_price * (1.0 + slip)
        return client.limit_order(
            coin,
            side,
            qty,
            limit_px,
            post_only=(order_type == "maker"),
        )
    return client.market_order(coin, side, qty, reduce_only=False)

def open_position(
    symbol: str,
    side: str,
    signal_change_pct: float,
    *,
    leverage: int = 2,
    signal_source: str = "AUTO",
    signal_row: dict | None = None,
    rescue_bypass: bool = False,
) -> dict | None:
    """Açılış: momentum_scanner.kelly_stake + elite_trader.compute_stake (Elite APEX ile aynı mantık)."""
    global positions, position_id_counter
    try:
        from elite_trader.order_gate import (
            assert_binance_send_allowed,
            build_order_intent,
            mark_order_sent,
            route_order,
            run_live_preflight_checks,
        )

        ex_mid = active_execution_mode()
        with _live_open_lock:
            _refresh_positions_cache_only(force=True)
            if LIVE_ORDERS and not client.paper:
                if not _assert_live_open_slot(symbol, rescue=rescue_bypass):
                    return None
            elif len(positions) >= execution_max_open():
                from elite_trader.fee_economics import report_exit_gate_block

                report_exit_gate_block(
                    kind="blocked_max_open",
                    symbol=symbol,
                    reason="max_open",
                    detail=f"açık={len(positions)}/{execution_max_open()}",
                )
                return None
        intent = build_order_intent(
            ex_mid,
            symbol=symbol,
            side=side,
            signal=signal_row,
        )
        gate = route_order(
            ex_mid,
            intent,
            active_futures_mode=active_futures_mode(),
            api_healthy=_api_healthy(),
            live_orders_enabled=LIVE_ORDERS and not client.paper,
        )
        if ex_mid == "evrim":
            try:
                from elite_trader.evrim_live_decisions import record_order_attempt

                sig = signal_row or {}
                v2 = sig.get("evrim_v2") or {}
                record_order_attempt(
                    symbol=symbol,
                    side=side,
                    allowed=gate.send_live,
                    reason=gate.reason,
                    final_score=v2.get("final_score"),
                    expected_net_pnl=sig.get("expected_net_pnl"),
                    order_route=gate.order_route,
                )
            except Exception:
                pass
        if not gate.send_live:
            return None
        evrim_preflight_ok = True
        evrim_preflight_reason = ""
        if ex_mid == "evrim" and signal_row:
            from elite_trader.evrim_v2 import evrim_v2_live_preflight

            evrim_preflight_ok, evrim_preflight_reason = evrim_v2_live_preflight(signal_row)
        gate = run_live_preflight_checks(
            gate,
            api_healthy=_api_healthy(),
            symbol_tradable=True,
            balance_ok=not _emergency_equity_block(),
            exposure_ok=_market_cooldown_ok(symbol),
            risk_filter_ok=evrim_preflight_ok,
            expected_net_ok=evrim_preflight_ok,
        )
        if not gate.allow_binance_send:
            if evrim_preflight_reason:
                print(f"  ⛔ Evrim V2 preflight {symbol}: {evrim_preflight_reason}")
            if ex_mid == "evrim":
                try:
                    from elite_trader.evrim_live_decisions import record_decision

                    sig = signal_row or {}
                    v2 = sig.get("evrim_v2") or {}
                    record_decision(
                        symbol=symbol,
                        side=side,
                        allowed=False,
                        reason=evrim_preflight_reason or gate.reason,
                        final_score=v2.get("final_score"),
                        expected_net_pnl=sig.get("expected_net_pnl"),
                        order_route=gate.order_route,
                        preflight_ok=False,
                    )
                except Exception:
                    pass
            return None

        strength = (
            "Strong"
            if abs(signal_change_pct) > 0.5
            else "Medium"
            if abs(signal_change_pct) > 0.25
            else "Weak"
        )
        fs_pre = _formula_score_from_signal(signal_change_pct)
        ok_risk, risk_reason, risk_tier = entry_risk_for_execution(
            symbol, side, strength, signal_change_pct, fs_pre
        )
        if not ok_risk:
            print(f"  ⛔ Açılış engellendi {symbol}: {risk_reason}")
            return None
        if risk_tier == "cautious":
            print(f"  ⚠ Temkinli açılış {symbol}: {risk_reason}")

        entry_price, _ = fetch_price(symbol)
        if entry_price <= 0:
            return None

        kelly_raw = _crypto_kelly_from_signal(signal_change_pct, side)
        wr = _session_wr()
        ex_mode = active_execution_mode()
        min_s = max(stake_bounds()[0], execution_min_stake())
        max_s = stake_bounds()[1]
        equity = get_current_capital()
        open_stakes = [float(p["stake_usd"]) for p in positions]
        avail_margin = None
        if LIVE_ORDERS and not client.paper and _wallet_cache:
            avail_margin = float(_wallet_cache.get("available_balance") or 0)
        prof = execution_profile()
        entry_stake_mult = float(prof.get("entry_stake_mult") or 1.0)
        if ex_mode == "evrim" and signal_row:
            hybrid = signal_row.get("evrim_hybrid") or {}
            tier_mult = float(hybrid.get("stake_mult") or 1.0)
            if tier_mult > 0:
                entry_stake_mult *= min(tier_mult, 1.30)
            risk = signal_row.get("evrim_risk") or {}
            rm = float(risk.get("risk_stake_mult") or 0)
            if rm > 0:
                entry_stake_mult *= min(rm, 1.0)
        if ex_mode == "sentinel" and signal_row:
            meta = signal_row.get("sentinel_meta") or {}
            sm = float(meta.get("sentinel_stake_mult") or 0)
            if sm > 0:
                entry_stake_mult *= sm
        stake_usd = compute_stake(
            equity,
            open_stakes,
            kelly_stake=kelly_raw * entry_stake_mult,
            max_open=execution_max_open(),
            min_stake=min_s,
            max_stake=max_s,
            win_rate=wr,
            active_capital_pct_override=execution_active_capital_pct(),
        )
        if stake_usd <= 0 and avail_margin and avail_margin >= _env_float(
            "ELITE_MIN_STAKE_FLOOR_USD", 80
        ):
            pct = execution_active_capital_pct()
            deployable = equity * pct
            used = sum(open_stakes)
            if used < deployable and len(open_stakes) < execution_max_open():
                stake_usd = min(
                    avail_margin * 0.35,
                    max_s if max_s < float("inf") else avail_margin * 0.35,
                    _env_float("ELITE_MIN_STAKE_FLOOR_USD", 80) * 4,
                )
                stake_usd = max(_env_float("ELITE_MIN_STAKE_FLOOR_USD", 80), stake_usd)
        if stake_usd <= 0:
            alloc = capital_snapshot(equity, open_stakes, win_rate=wr)
            print(
                f"⚠️  {symbol}: stake=0 | kalan=${alloc.get('remaining_usd', 0):.0f} "
                f"deploy={alloc.get('deployed_usd', 0):.0f}/{alloc.get('deployable_usd', 0):.0f} "
                f"açık={len(open_stakes)}/{execution_max_open()}"
            )
            return None

        if ex_mode == "evrim" and signal_row:
            exec_plan = signal_row.get("evrim_execution") or {}
            if exec_plan.get("partial_entry"):
                stake_usd *= 0.5

        strength = (
            "Strong"
            if abs(signal_change_pct) > 0.5
            else "Medium"
            if abs(signal_change_pct) > 0.25
            else "Weak"
        )
        leverage = _leverage_for_signal(strength, leverage)

        from elite_trader.fee_economics import (
            apply_net_targets_to_position,
            entry_gate,
            fee_rate_per_side,
            tp_sl_gross_triggers,
        )

        ok_fee, fee_reason = entry_gate(
            stake_usd, leverage, mode_id=ex_mode, client=client
        )
        if not ok_fee:
            _motor_reject("fee_net_tp")
            print(f"  ⛔ Ücret/net-TP kapısı {symbol}: {fee_reason}")
            return None

        size = stake_usd * leverage / entry_price
        entry_fee_est = size * entry_price * fee_rate_per_side()

        edge = _edge_from_signal(signal_change_pct)
        formula_score = _formula_score_from_signal(signal_change_pct)
        opened_iso = datetime.now(timezone.utc).isoformat()

        tp_usd, sl_usd, net_tp, rt_fee = tp_sl_gross_triggers(
            stake_usd, leverage, ex_mode
        )
        fr_de: dict[str, Any] | None = None
        if signal_row:
            bm = signal_row.get("berserk_meta") or {}
            fr_de = bm.get("berserk_dynamic_exit") if signal_row.get("flash_reversal") else None
            if not fr_de and str(signal_row.get("signal_source") or "") == "FlashReversal-LONG":
                fr_de = bm.get("berserk_dynamic_exit")
        if fr_de and fr_de.get("flash_reversal_tp_usd"):
            tp_usd = max(tp_usd, float(fr_de["flash_reversal_tp_usd"]))
            net_tp = max(net_tp, tp_usd * 0.55)

        if side == "LONG":
            tp_price = entry_price + tp_usd / size if size > 0 else entry_price
            sl_price = entry_price - sl_usd / size if size > 0 else entry_price
        else:
            tp_price = entry_price - tp_usd / size if size > 0 else entry_price
            sl_price = entry_price + sl_usd / size if size > 0 else entry_price

        position = {
            'id': position_id_counter,
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'current_price': entry_price,
            'size': size,
            'leverage': leverage,
            'stake_usd': stake_usd,
            'position_value': size * entry_price,
            'unrealized_pnl': 0.0,
            'pnl_pct': 0.0,
            'entry_time': time.time(),
            'entry_time_str': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'opened_at_iso': opened_iso,
            'tp_target': tp_price,
            'sl_target': sl_price,
            'tp_target_usd': tp_usd,
            'sl_target_usd': sl_usd,
            'tp_net_target_usd': net_tp,
            'round_trip_fee_est_usd': rt_fee,
            'price_history': [entry_price],
            'time_history': [datetime.utcnow().isoformat()],
            'entry_fee_est': entry_fee_est,
            'entry_fee': None,
            'total_fees': None,
            'fee_source': None,
            'edge': edge,
            'formula_score': formula_score,
            'signal_source': signal_source,
            'signal_strength': strength,
            'on_exchange': False,
            'min_unreal_seen': 0.0,
            'max_unreal_seen': 0.0,
            'panel_mode': active_execution_mode(),
            'execution_mode_at_open': active_execution_mode(),
            'entry_risk_tier': risk_tier,
            'entry_risk_note': risk_reason,
        }
        if signal_row and (
            signal_row.get("flash_reversal")
            or str(signal_row.get("signal_source") or "") == "FlashReversal-LONG"
        ):
            position["flash_reversal"] = True
            position["flash_drop_pct"] = signal_row.get("flash_drop_pct")
            position["flash_bounce_pct"] = signal_row.get("flash_bounce_pct")
            position["flash_target_price"] = signal_row.get("flash_target_price")
            position["flash_peak_price"] = signal_row.get("flash_peak_price")
            position["flash_low_price"] = signal_row.get("flash_low_price")
            if fr_de:
                position["dynamic_exit"] = fr_de
        if ex_mode == "evrim" and signal_row:
            exec_plan = signal_row.get("evrim_execution") or {}
            if exec_plan:
                position["evrim_execution"] = exec_plan
            hybrid = signal_row.get("evrim_hybrid") or {}
            if hybrid:
                position["hybrid_score"] = hybrid.get("total_score")
                position["hybrid_tier"] = hybrid.get("tier")
                position["hybrid_components"] = hybrid.get("components")
                position["expected_net_pnl_usd"] = hybrid.get("expected_net_pnl_usd")
                print(
                    f"  🧬 Evrim [{hybrid.get('tier')}] {symbol} {side} "
                    f"skor={hybrid.get('total_score')} "
                    f"net≈${hybrid.get('expected_net_pnl_usd', 0):.2f} "
                    f"stake=${stake_usd:.0f}"
                )

        if ex_mode == "evrim":
            try:
                from elite_trader.evrim_unified_engine import assert_evrim_live_allowed

                ok_ev, ev_msg = assert_evrim_live_allowed()
                if LIVE_ORDERS and not client.paper and not ok_ev:
                    print(
                        f"  ⛔ Evrim canlı kapalı ({ev_msg}) — "
                        "paper/demo veya /api/evrim/unified/risk-report"
                    )
                    return None
            except Exception:
                pass

        if LIVE_ORDERS and not client.paper:
            with _live_open_lock:
                _refresh_positions_cache_only(force=True)
                if not _assert_live_open_slot(symbol, rescue=rescue_bypass):
                    return None
            assert_binance_send_allowed(ex_mid, active_futures_mode())
            coin = symbol.replace("USDT", "")
            client.ensure_margin_type(coin)
            client.ensure_leverage(coin, leverage)
            qty = client.round_qty(coin, size)
            if qty <= 0:
                print(f"⚠️  {symbol}: geçersiz miktar qty={size}")
                return None
            from elite_trader.entry_book_gate import entry_book_gate

            sig_px = float(
                (signal_row or {}).get("price")
                or entry_price
                or 0
            )
            ok_book, book_reason, book_meta = entry_book_gate(
                client,
                symbol=symbol,
                side=side,
                stake_usd=stake_usd,
                leverage=leverage,
                signal_price=sig_px if sig_px > 0 else None,
                mode_id=ex_mode,
            )
            if not ok_book:
                from elite_trader.fee_economics import report_exit_gate_block

                report_exit_gate_block(
                    kind="blocked_entry_spread",
                    symbol=symbol,
                    reason="entry_book_gate",
                    detail=book_reason,
                )
                print(f"  ⛔ Giriş book kapısı {symbol} {side}: {book_reason}")
                return None
            position["entry_book_meta"] = book_meta
            position["instant_upnl_est"] = book_meta.get("instant_upnl_est")
            position["entry_spread_pct"] = book_meta.get("spread_pct")
            try:
                order = _place_live_entry_order(
                    coin,
                    side,
                    qty,
                    entry_price,
                    signal_row=signal_row,
                )
                mark_order_sent(ex_mid, exchange_accepted=True)
                position["on_exchange"] = True
                position["exchange_order_id"] = str(order.get("orderId") or "")
                if position["exchange_order_id"]:
                    from elite_trader.exchange_settlement import fetch_order_fills

                    ef = fetch_order_fills(client, coin, position["exchange_order_id"])
                    if ef.get("commission", 0) > 0:
                        position["entry_fee"] = ef["commission"]
                        position["total_fees"] = position["entry_fee"]
                        position["fee_source"] = "binance_api"
                    if ef.get("avg_price", 0) > 0:
                        position["entry_price"] = ef["avg_price"]
                if position.get("fee_source") != "binance_api":
                    from elite_trader.exchange_fill_truth import fetch_entry_fee_from_exchange

                    ef2 = fetch_entry_fee_from_exchange(
                        client,
                        symbol,
                        side,
                        entry_order_id=position.get("exchange_order_id"),
                        opened_at_iso=position.get("opened_at_iso"),
                    )
                    if ef2 > 0:
                        position["entry_fee"] = ef2
                        position["total_fees"] = ef2
                        position["fee_source"] = "binance_api"
                time.sleep(0.15)  # fill sonrası positionRisk güncellenmesi
                _refresh_positions_cache_only(force=True)
                for ep in _positions_cache:
                    if ep.get("coin") == coin and ep.get("side") == side:
                        position["entry_price"] = float(ep["entry_price"])
                        position["size"] = float(ep["contracts"])
                        position["leverage"] = int(
                            ep.get("leverage") or leverage
                        )
                        position["current_price"] = float(
                            ep.get("mark_price") or position["entry_price"]
                        )
                        position["position_value"] = (
                            position["size"] * position["entry_price"]
                        )
                        sz = position["size"]
                        if sz > 0:
                            if side == "LONG":
                                position["tp_target"] = (
                                    position["entry_price"] + tp_usd / sz
                                )
                                position["sl_target"] = (
                                    position["entry_price"] - sl_usd / sz
                                )
                            else:
                                position["tp_target"] = (
                                    position["entry_price"] - tp_usd / sz
                                )
                                position["sl_target"] = (
                                    position["entry_price"] + sl_usd / sz
                                )
                        break
                apply_net_targets_to_position(position, ex_mode)
                ok2, fee_reason2 = entry_gate(
                    float(position["stake_usd"]),
                    int(position["leverage"]),
                    mode_id=ex_mode,
                    observed_entry_fee=float(position.get("entry_fee") or 0) or None,
                    client=client,
                )
                if not ok2:
                    print(
                        f"  ⚠ Borsa açıldı ama net-TP planı zayıf — TP bekleniyor "
                        f"{symbol}: {fee_reason2}"
                    )
                    positions.append(position)
                    position_id_counter += 1
                    return position
                print(
                    f"  ✓ Borsa emri #{position.get('exchange_order_id')} "
                    f"{side} {symbol} {leverage}x qty={position['size']} "
                    f"| netTP≈${position.get('tp_net_target_usd', 0):.2f} "
                    f"fee≈${position.get('round_trip_fee_est_usd', 0):.2f}"
                )
                if position.get("fee_source") == "binance_api":
                    from elite_trader.exchange_trade_truth import format_open_log_api

                    print(f"  {format_open_log_api(position)}")
                _refresh_positions_cache_only(force=True)
            except Exception as exc:
                print(f"  ⛔ Borsa açılış başarısız {symbol}: {exc}")
                return None
        else:
            apply_net_targets_to_position(position, ex_mode)

        positions.append(position)
        position_id_counter += 1
        try:
            parallel_engine.record_live_open(ex_mode, position)
        except Exception:
            pass
        print(
            f"✅ {side} {symbol} @ ${entry_price:.2f} | {leverage}x | "
            f"stake=${stake_usd:.0f} | kelly_raw=${kelly_raw:.0f} | score={formula_score:.2f} "
            f"| slot {len(positions)}/{execution_max_open()}"
        )
        _push_monitor_event(
            "OPEN",
            symbol=symbol,
            side=side,
            entry_price=position.get("entry_price", entry_price),
            size=position.get("size"),
            stake_usd=position.get("stake_usd", stake_usd),
            leverage=position.get("leverage", leverage),
            order_id=position.get("exchange_order_id"),
            signal=position.get("signal_source"),
            pos_id=position.get("id"),
            entry_fee=position.get("entry_fee"),
            mode=ex_mode,
        )
        _sync_position_fast_feed()
        _wake_position_price()
        return position
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def _exchange_position_row(
    sym: str, side: str, *, force_fresh: bool = False
) -> dict[str, Any] | None:
    """Ana Hat — borsada (symbol, side) satırı var mı."""
    if not LIVE_ORDERS or client.paper:
        return None
    from elite_trader.exchange_position_sync import exchange_map_by_symbol_side

    cache_age = time.time() - float(_exchange_cache_ts or 0)
    if (
        force_fresh
        or not _positions_cache
        or cache_age > _exchange_position_refresh_sec() * 2
        or cache_age > 30.0
    ):
        _refresh_positions_cache_only(
            force=True,
            timeout_sec=_effective_position_timeout_sec(critical=True),
        )
    return exchange_map_by_symbol_side(list(_positions_cache)).get((sym, side))


def _exchange_position_absent_confirmed(sym: str, side: str) -> bool | None:
    """
    REST positionRisk ile pozisyon kapalı mı?
    True=yok, False=açık, None=API doğrulanamadı (kapatma yok).
    """
    if not LIVE_ORDERS or client.paper:
        return None
    from elite_trader.exchange_position_sync import exchange_map_by_symbol_side

    before_ts = float(_exchange_cache_ts or 0)
    refreshed = _refresh_positions_cache_only(
        force=True,
        timeout_sec=_effective_position_timeout_sec(critical=True),
    )
    row = exchange_map_by_symbol_side(list(_positions_cache)).get((sym, side))
    if row:
        return False
    after_ts = float(_exchange_cache_ts or 0)
    if refreshed and after_ts >= before_ts:
        return True
    return None


def _drop_local_exchange_position(i: int, pos: dict[str, Any], reason: str) -> bool:
    """Borsada yok — yerel hayalet; eski userTrades ile kapalı kayıt oluşturma."""
    print(f"  ↻ Yerel hayalet silindi {pos['symbol']} ({reason})")
    positions.pop(i)
    _refresh_positions_cache_only(
        force=True,
        timeout_sec=_effective_position_timeout_sec(critical=True),
    )
    return True


def _execute_exchange_market_close(
    pos: dict[str, Any],
    exit_reason: str,
    close_exec: dict[str, Any],
    *,
    qty_override: float | None = None,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    """Reduce-only market kapanış + order-id ile settlement."""
    from elite_trader.exchange_settlement import settle_position_close

    coin = pos["symbol"].replace("USDT", "")
    close_side = "SHORT" if pos["side"] == "LONG" else "LONG"
    qty_src = qty_override if qty_override is not None else float(pos["size"])
    qty = client.round_qty(coin, qty_src)
    if qty <= 0:
        return None, None, close_exec
    t_order0 = time.perf_counter()
    close_order = client.market_order(coin, close_side, qty, reduce_only=True)
    close_exec["order_ack_ms"] = round(
        (time.perf_counter() - t_order0) * 1000.0, 2
    )
    close_order_id = str(close_order.get("orderId") or "")
    t_settle0 = time.perf_counter()
    exchange_settled = _settle_close_with_retry(pos, close_order_id)
    close_exec["settle_ms"] = round(
        (time.perf_counter() - t_settle0) * 1000.0, 2
    )
    if close_exec.get("signal_at_ms"):
        close_exec["total_close_ms"] = round(
            time.time() * 1000.0 - float(close_exec["signal_at_ms"]),
            2,
        )
    print(
        f"  ✓ Borsa kapanış {pos['symbol']} {exit_reason} "
        f"order={close_order_id} qty={qty} "
        f"ack={close_exec.get('order_ack_ms')}ms "
        f"settle={close_exec.get('settle_ms')}ms"
    )
    return exchange_settled, close_order_id, close_exec


def _settle_close_with_retry(
    pos: dict[str, Any],
    close_order_id: str | int | None,
    *,
    waits: tuple[float, ...] = (0.35, 0.55, 0.85, 1.2),
) -> dict[str, Any] | None:
    """Kapanış emri sonrası userTrades settlement — birkaç deneme."""
    from elite_trader.exchange_settlement import (
        settle_position_close,
        settlement_has_api_close_fills,
    )

    if not close_order_id:
        return None
    settled: dict[str, Any] | None = None
    for w in waits:
        settled = settle_position_close(
            client,
            pos,
            close_order_id=close_order_id,
            settle_wait_sec=w,
        )
        if settled and settlement_has_api_close_fills(settled):
            return settled
    return settled


def _always_save_order_close() -> bool:
    return os.getenv("ELITE_ALWAYS_SAVE_ORDER_CLOSE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def close_all_exchange_positions(*, save: bool = True) -> dict[str, Any]:
    """Tüm borsa pozisyonlarını kapat; save=False → DB/kapalı tabloya yazma."""
    global positions
    out: dict[str, Any] = {
        "save": bool(save),
        "exchange_closed": 0,
        "local_cleared": 0,
        "local_saved": 0,
        "errors": [],
    }
    if not LIVE_ORDERS or client.paper:
        out["errors"].append("live_orders_disabled")
        return out

    if save:
        for pos in list(positions):
            try:
                if close_position(int(pos["id"]), "Manual Close"):
                    out["local_saved"] += 1
            except Exception as exc:
                out["errors"].append(f"{pos.get('symbol')}: {exc}")
        _refresh_positions_cache_only(force=True)
        for ep in list(_positions_cache or []):
            if abs(float(ep.get("contracts") or ep.get("positionAmt") or 0)) <= 0:
                continue
            coin = str(ep.get("coin") or "")
            sym = str(ep.get("symbol") or f"{coin}USDT")
            close_side = "SHORT" if str(ep.get("side") or "LONG").upper() == "LONG" else "LONG"
            qty = client.round_qty(coin, abs(float(ep.get("contracts") or 0)))
            if qty <= 0:
                continue
            try:
                client.market_order(coin, close_side, qty, reduce_only=True)
                out["exchange_closed"] += 1
                print(f"  ✓ Bulk orphan kapat {sym} qty={qty}")
                time.sleep(0.15)
            except Exception as exc:
                out["errors"].append(f"{sym}: {exc}")
        _refresh_positions_cache_only(force=True)
        return out

    _refresh_positions_cache_only(force=True)
    eps = [
        ep
        for ep in list(_positions_cache or [])
        if abs(float(ep.get("contracts") or ep.get("positionAmt") or 0)) > 0
    ]
    for ep in eps:
        coin = str(ep.get("coin") or "")
        sym = str(ep.get("symbol") or f"{coin}USDT")
        close_side = "SHORT" if str(ep.get("side") or "LONG").upper() == "LONG" else "LONG"
        qty_raw = abs(float(ep.get("contracts") or ep.get("positionAmt") or 0))
        qty = client.round_qty(coin, qty_raw)
        if qty <= 0:
            qty = qty_raw
        if qty <= 0:
            continue
        try:
            client.market_order(coin, close_side, qty, reduce_only=True)
            out["exchange_closed"] += 1
            print(f"  ✓ Bulk kapat kayıtsız {sym} {ep.get('side')} qty={qty}")
            time.sleep(0.18)
        except Exception as exc:
            msg = f"{sym}: {exc}"
            out["errors"].append(msg)
            print(f"  ⛔ Bulk kapat {msg}")
    time.sleep(0.35)
    out["local_cleared"] = len(positions)
    positions.clear()
    _refresh_positions_cache_only(force=True)
    return out


def close_position(position_id: int, exit_reason: str = 'Manual'):
    global positions, closed_positions
    if position_id in _positions_closing:
        return False
    for i, pos in enumerate(positions):
        if pos['id'] == position_id:
            _positions_closing.add(position_id)
            try:
                return _close_position_inner(i, pos, exit_reason)
            finally:
                _positions_closing.discard(position_id)
    return False


def _close_position_inner(i: int, pos: dict[str, Any], exit_reason: str) -> bool:
    global positions, closed_positions
    if str(exit_reason or "").upper() == "SYNC-EXCHANGE" and pos.get("on_exchange"):
        from elite_trader.panel_strategy import position_age_seconds

        grace = _env_float("ELITE_SYNC_EXCHANGE_GRACE_SEC", 8.0)
        opened_at = pos.get("opened_at_iso") or pos.get("entry_time_str")
        age = position_age_seconds(
            {"opened_at_iso": opened_at, "entry_time_str": opened_at}
        )
        if age < grace:
            _refresh_positions_cache_only(force=True)
            if _exchange_position_row(pos["symbol"], pos["side"]):
                return False
    on_ex_live = LIVE_ORDERS and not client.paper and pos.get("on_exchange")
    ghost_sync = (
        str(exit_reason or "").upper() == "SYNC-EXCHANGE"
        and on_ex_live
        and not _exchange_position_row(pos["symbol"], pos["side"])
    )

    if on_ex_live and not ghost_sync:
        from elite_trader.fee_economics import (
            allow_position_close,
            exit_ops_allowed,
            exit_tp_only,
            is_profit_tp_exit,
            report_exit_gate_block,
        )

        ex_mid = str(pos.get("panel_mode") or active_execution_mode())
        from elite_trader.exchange_fill_truth import fill_gross_unreal

        fg = pos.get("fill_gross_unreal")
        if fg is None:
            fg = fill_gross_unreal(pos, client=client)
        gross_for_gate = float(
            fg if fg is not None else pos.get("unrealized_pnl") or 0
        )
        from elite_trader.fee_economics import is_stop_loss_exit

        if exit_tp_only(ex_mid) and not (
            is_profit_tp_exit(exit_reason)
            or is_stop_loss_exit(exit_reason)
            or exit_ops_allowed(exit_reason)
        ):
            report_exit_gate_block(
                kind="blocked_non_tp",
                symbol=pos["symbol"],
                reason=exit_reason,
                detail=f"fill brüt=${gross_for_gate:.4f}",
            )
            return False
        if not allow_position_close(
            gross_unreal=gross_for_gate,
            stake_usd=float(pos.get("stake_usd") or 1),
            leverage=max(int(pos.get("leverage") or 5), 1),
            exit_reason=exit_reason,
            mode_id=ex_mid,
            entry_fee=float(pos.get("entry_fee") or 0) or None,
            pos=pos,
            client=client,
        ):
            report_exit_gate_block(
                kind="blocked_net_negative",
                symbol=pos["symbol"],
                reason=exit_reason,
                detail=f"fill brüt=${gross_for_gate:.4f}",
            )
            return False
        from elite_trader.fee_economics import profit_exit_send_ok

        ok_send, send_detail = profit_exit_send_ok(
            pos, exit_reason, mode_id=ex_mid, client=client
        )
        if not ok_send:
            report_exit_gate_block(
                kind="blocked_spike_premature",
                symbol=pos["symbol"],
                reason=exit_reason,
                detail=send_detail,
            )
            return False
        from elite_trader.exchange_position_sync import pre_close_upnl_verify_ok

        close_exec: dict[str, Any] = dict(pos.get("close_signal") or {})
        ok_upnl, upnl_detail = pre_close_upnl_verify_ok(
            pos, exit_reason, client=client, mode_id=ex_mid
        )
        if not ok_upnl:
            spike_retry_key = f"spike_retry_{pos['id']}"
            if exit_reason in ("SPIKE-FLASH", "SPIKE-QUICK", "SPIKE-PEAK"):
                _spike_retry_count = _symbol_last_close.get(spike_retry_key, 0)
                max_spike_retries = int(os.getenv("ELITE_SPIKE_MAX_RETRIES", "5"))
                _symbol_last_close[spike_retry_key] = _spike_retry_count + 1
                report_exit_gate_block(
                    kind="blocked_upnl_mismatch",
                    symbol=pos["symbol"],
                    reason=exit_reason,
                    detail=f"{upnl_detail} (retry {_spike_retry_count+1}/{max_spike_retries})",
                )
            else:
                report_exit_gate_block(
                    kind="blocked_upnl_mismatch",
                    symbol=pos["symbol"],
                    reason=exit_reason,
                    detail=upnl_detail,
                )
            return False
        if exit_reason in ("SPIKE-FLASH", "SPIKE-QUICK", "SPIKE-PEAK"):
            _symbol_last_close[f"spike_retry_{pos['id']}"] = 0
        close_exec = {**close_exec, **dict(pos.get("close_signal") or {})}
        pos["_close_exec_pending"] = close_exec
    exchange_settled: dict[str, Any] | None = None
    close_order_id: str | None = None
    close_exec: dict[str, Any] = dict(pos.pop("_close_exec_pending", None) or pos.get("close_signal") or {})
    if ghost_sync:
        from elite_trader.exchange_settlement import (
            settle_position_close,
            settlement_has_api_close_fills,
        )

        if _exchange_position_row(pos["symbol"], pos["side"], force_fresh=True):
            print(
                f"  ⛔ SYNC-EXCHANGE iptal {pos['symbol']}: "
                f"borsada hâlâ açık (REST positionRisk)"
            )
            return False
        absent = _exchange_position_absent_confirmed(pos["symbol"], pos["side"])
        if absent is not True:
            print(
                f"  ⛔ SYNC-EXCHANGE iptal {pos['symbol']}: "
                f"positionRisk doğrulanamadı — pozisyon açık kalır"
            )
            return False
        print(f"  ↻ Hayalet temizlik {pos['symbol']} — borsada yok (SYNC-EXCHANGE)")
        exchange_settled = settle_position_close(
            client,
            pos,
            close_order_id=None,
            settle_wait_sec=0.15,
        )
        if not exchange_settled:
            exchange_settled = settle_position_close(
                client,
                pos,
                close_order_id=None,
                settle_wait_sec=0.45,
            )
        if not settlement_has_api_close_fills(exchange_settled):
            print(
                f"  ⛔ SYNC-EXCHANGE iptal {pos['symbol']}: "
                f"Binance userTrades kapanış fill yok — pozisyon açık kalır"
            )
            return False
        if exchange_settled:
            wp = float(exchange_settled.get("wallet_pnl") or 0)
            rp = float(exchange_settled.get("exchange_realized_pnl") or 0)
            print(
                f"  ↻ Borsa trade senkronu {pos['symbol']} "
                f"realized=${rp:.4f} wallet=${wp:.4f}"
            )
            from elite_trader.position_hedge import has_hedge_for

            recent_hedge = float(pos.get("hedge_last_attempt_ts") or 0) > (
                time.time() - 300.0
            )
            if has_hedge_for(pos, positions) or recent_hedge:
                exit_reason = "HEDGE-NET"
            else:
                exit_reason = "EXCHANGE-SYNC"
    elif on_ex_live:
        from elite_trader.order_gate import assert_binance_send_allowed

        ex_mid = str(pos.get("panel_mode") or active_execution_mode())
        assert_binance_send_allowed(ex_mid, active_futures_mode())

        coin = pos["symbol"].replace("USDT", "")
        qty = client.round_qty(coin, float(pos["size"]))
        ep_row = _exchange_position_row(pos["symbol"], pos["side"], force_fresh=True)
        if ep_row:
            qty = client.round_qty(coin, float(ep_row.get("contracts") or pos["size"]))
        if ep_row and qty > 0:
            try:
                exchange_settled, close_order_id, close_exec = (
                    _execute_exchange_market_close(
                        pos, exit_reason, close_exec, qty_override=qty
                    )
                )
            except Exception as exc:
                err = str(exc)
                if "-2022" in err or "ReduceOnly" in err:
                    ep_live = _exchange_position_row(
                        pos["symbol"], pos["side"], force_fresh=True
                    )
                    if ep_live and float(ep_live.get("contracts") or 0) > 0:
                        qty2 = client.round_qty(
                            coin, float(ep_live.get("contracts") or 0)
                        )
                        if qty2 > 0:
                            try:
                                exchange_settled, close_order_id, close_exec = (
                                    _execute_exchange_market_close(
                                        pos,
                                        exit_reason,
                                        close_exec,
                                        qty_override=qty2,
                                    )
                                )
                            except Exception as exc2:
                                print(
                                    f"  ⛔ Borsa kapanış retry başarısız "
                                    f"{pos['symbol']}: {exc2}"
                                )
                                return False
                        else:
                            return _drop_local_exchange_position(
                                i, pos, exit_reason
                            )
                    else:
                        return _drop_local_exchange_position(i, pos, exit_reason)
                else:
                    print(
                        f"  ⛔ Borsa kapanış başarısız {pos['symbol']}: {exc}"
                    )
                    return False
        else:
            return _drop_local_exchange_position(i, pos, exit_reason)

    if (
        not exchange_settled
        and close_order_id
        and _always_save_order_close()
    ):
        exchange_settled = _settle_close_with_retry(
            pos, close_order_id, waits=(0.5, 0.85, 1.2, 1.6)
        )

    if exchange_settled:
        from elite_trader.exchange_trade_truth import settlement_to_closed_fields

        api_fields = settlement_to_closed_fields(exchange_settled)
        exit_price = api_fields["exit_price"]
        pnl = api_fields["pnl_usd"]
        exit_fee = api_fields["exit_fee"]
        total_fees = api_fields["total_fees"]
        net_pnl = api_fields["net_pnl"]
        net_pnl_pct = api_fields["net_pnl_pct"]
        tax = 0.0
        final_pnl = api_fields["final_pnl"]
        size_out = api_fields["size"]
        entry_px = api_fields["entry_price"]
    elif on_ex_live and pos.get("on_exchange"):
        if str(exit_reason or "").upper() == "SYNC-EXCHANGE":
            print(
                f"  ⛔ SYNC-EXCHANGE iptal {pos['symbol']}: "
                f"Binance API settlement alınamadı — pozisyon açık kalır"
            )
            return False
        print(
            f"  ⛔ Kapalı kayıt yok {pos['symbol']} ({exit_reason}): "
            f"Binance API settlement alınamadı"
        )
        positions.pop(i)
        _refresh_positions_cache_only(force=True)
        return True
    else:
        exit_price = pos["current_price"]
        pnl = pos["unrealized_pnl"]
        exit_fee = 0.0
        total_fees = float(pos.get("entry_fee") or 0)
        net_pnl = float(pnl or 0) - total_fees
        net_pnl_pct = (net_pnl / pos["stake_usd"]) * 100 if pos.get("stake_usd") else 0
        tax = 0.0
        final_pnl = net_pnl
        size_out = pos["size"]
        entry_px = pos["entry_price"]

    _symbol_last_close[pos['symbol']] = time.time()
    if float(final_pnl) < -0.01:
        _symbol_last_loss_close[pos['symbol']] = time.time()

    from elite_trader.fee_economics import live_close_record_ok

    ex_mid = str(pos.get("panel_mode") or active_execution_mode())
    wallet_pnl = float(
        exchange_settled.get("wallet_pnl", net_pnl)
        if exchange_settled
        else final_pnl
    )
    ok_rec, record_reason, skip_detail = live_close_record_ok(
        exit_reason=exit_reason,
        exchange_settled=exchange_settled,
        mode_id=ex_mid,
        on_exchange=bool(pos.get("on_exchange")),
    )
    if not ok_rec:
        if close_order_id and _always_save_order_close():
            exchange_settled = exchange_settled or _settle_close_with_retry(
                pos, close_order_id, waits=(0.85, 1.4, 2.0)
            )
            if exchange_settled:
                ok_rec, record_reason, skip_detail = live_close_record_ok(
                    exit_reason=exit_reason,
                    exchange_settled=exchange_settled,
                    mode_id=ex_mid,
                    on_exchange=bool(pos.get("on_exchange")),
                )
                if ok_rec:
                    from elite_trader.exchange_trade_truth import settlement_to_closed_fields

                    api_fields = settlement_to_closed_fields(exchange_settled)
                    exit_price = api_fields["exit_price"]
                    pnl = api_fields["pnl_usd"]
                    exit_fee = api_fields["exit_fee"]
                    total_fees = api_fields["total_fees"]
                    net_pnl = api_fields["net_pnl"]
                    net_pnl_pct = api_fields["net_pnl_pct"]
                    final_pnl = api_fields["final_pnl"]
                    size_out = api_fields["size"]
                    entry_px = api_fields["entry_price"]
                    wallet_pnl = float(exchange_settled.get("wallet_pnl") or net_pnl)
        if not ok_rec:
            print(
                f"  ⛔ Kayıt yok {pos['symbol']} ({exit_reason}): {skip_detail}"
            )
            positions.pop(i)
            _refresh_positions_cache_only(force=True)
            return True

    if exchange_settled:
        final_pnl = wallet_pnl
        net_pnl = wallet_pnl
        pnl = float(
            exchange_settled.get("pnl_usd")
            or exchange_settled.get("pnl_gross_usd")
            or pnl
        )
        net_pnl_pct = round(net_pnl / float(pos.get("stake_usd") or 1) * 100, 4)

    closed = {
        'id': pos['id'],
        'symbol': pos['symbol'],
        'side': pos['side'],
        'entry_price': entry_px,
        'exit_price': exit_price,
        'size': size_out,
        'leverage': pos['leverage'],
        'stake_usd': pos['stake_usd'],
        'pnl_usd': pnl,
        'pnl_pct': (pnl / pos['stake_usd']) * 100 if pos['stake_usd'] else 0,
        'entry_fee': exchange_settled["entry_fee"] if exchange_settled else pos.get('entry_fee', 0),
        'exit_fee': exit_fee,
        'total_fees': total_fees,
        'net_pnl': net_pnl,
        'net_pnl_pct': net_pnl_pct,
        'tax': tax,
        'final_pnl': final_pnl,
        'exit_reason': record_reason,
        'entry_time': pos['entry_time_str'],
        'opened_at_iso': pos.get('opened_at_iso'),
        'exit_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        'duration': time.time() - pos['entry_time'],
        'on_exchange': bool(pos.get('on_exchange')),
        'exchange_order_id': str(pos.get('exchange_order_id') or ''),
        'signal_strength': pos.get('signal_strength'),
        'formula_score': pos.get('formula_score'),
        'edge': pos.get('edge'),
        'panel_mode': pos.get('panel_mode') or active_execution_mode(),
        'execution_mode_at_close': active_execution_mode(),
        'entry_risk_tier': pos.get('entry_risk_tier'),
        'entry_risk_note': pos.get('entry_risk_note'),
        'signal_source': pos.get('signal_source'),
        'exchange_settled': bool(exchange_settled),
        'exchange_close_order_id': close_order_id or '',
        'exchange_realized_pnl': (
            exchange_settled.get('exchange_realized_pnl') if exchange_settled else None
        ),
        'fee_source': (
            exchange_settled.get("fee_source") or ("binance_api" if exchange_settled else None)
        ),
        'pnl_source': (
            exchange_settled.get("pnl_source") or ("binance_api" if exchange_settled else None)
        ),
        'data_source': (
            exchange_settled.get("data_source") or ("binance_api" if exchange_settled else "local")
        ),
        'wallet_pnl': wallet_pnl if exchange_settled else final_pnl,
        'close_execution': close_exec if close_exec else None,
        'signal_fill_px': close_exec.get('signal_fill_px'),
        'signal_est_net': close_exec.get('signal_est_net'),
        'signal_mark_unreal': close_exec.get('signal_mark_unreal'),
        'order_ack_ms': close_exec.get('order_ack_ms'),
        'settle_ms': close_exec.get('settle_ms'),
        'total_close_ms': close_exec.get('total_close_ms'),
    }
    
    closed_positions.append(closed)
    _trim_closed_positions_ram()
    positions.pop(i)
    ex_mode = str(closed.get("panel_mode") or active_execution_mode())
    try:
        parallel_engine.record_live_close(ex_mode, closed)
    except Exception:
        pass
    from elite_trader.fee_economics import live_close_learning_ok

    learn_ok = live_close_learning_ok(wallet_pnl=wallet_pnl, mode_id=ex_mode)
    if learn_ok:
        try:
            from elite_trader.data_lake.ingest import ingest_live_trade

            ingest_live_trade(
                ex_mode, closed, closing=True, active_futures_mode=active_futures_mode()
            )
        except Exception:
            pass
        try:
            from elite_trader.evrim_cross_mode_learner import (
                observe_mode_trade_closed,
            )

            observe_mode_trade_closed(ex_mode, closed)
        except Exception:
            pass
        enqueue_loss_analysis(closed)
    elif exchange_settled:
        from elite_trader.exchange_trade_truth import format_close_log_api

        print(
            f"  📋 Tabloya yazıldı (öğrenme yok) {pos['symbol']} | Binance API "
            f"wallet=${wallet_pnl:.4f} realized=${float(exchange_settled.get('exchange_realized_pnl') or pnl):.4f} "
            f"| {record_reason}"
        )
    if _elite_state_enabled():
        try:
            from elite_pro_state import save_closed

            save_closed(closed, mode_id=ex_mode)
        except Exception as exc:
            print(f"  ⚠ DB kayıt: {exc}")
    record_sl_emergency_close(closed)
    from elite_trader.exchange_trade_truth import format_close_log_api

    print(
        format_close_log_api(
            pos_id=pos["id"],
            symbol=pos["symbol"],
            settled=exchange_settled,
            record_reason=record_reason,
            fallback_final=final_pnl if not exchange_settled else None,
        )
    )
    _push_monitor_event(
        "CLOSE",
        symbol=pos.get("symbol"),
        side=pos.get("side"),
        pos_id=pos.get("id"),
        exit_reason=record_reason,
        final_pnl=wallet_pnl if exchange_settled else final_pnl,
        exit_price=exit_price,
        order_id=close_order_id,
        order_ack_ms=close_exec.get("order_ack_ms") if close_exec else None,
        settle_ms=close_exec.get("settle_ms") if close_exec else None,
        entry_price=entry_px,
    )
    _sync_position_fast_feed()
    return True

def _get_fast_price_for_coin(coin: str) -> float | None:
    """bookTicker'dan sub-saniye fiyat; yoksa None."""
    try:
        from binance_futures_trader.fast_price_ws import get_fast_price
        d = get_fast_price(coin, max_age_ms=2000)
        if d:
            return d["mid"]
    except Exception:
        pass
    return None


def _all_open_position_coins(*, refresh_paper: bool = False) -> list[str]:
    """Live + paper açık pozisyon coinleri (USDT hariç)."""
    global _paper_open_coins_cache
    coins: set[str] = {p["symbol"].replace("USDT", "") for p in positions}
    if live_only_execution():
        return sorted(coins)
    now = time.time()
    if refresh_paper or now - _paper_open_coins_cache[0] > 0.15:
        try:
            extra = set(parallel_engine.open_position_coins())
        except Exception:
            extra = set(_paper_open_coins_cache[1])
        _paper_open_coins_cache = (now, sorted(extra))
    coins.update(_paper_open_coins_cache[1])
    return sorted(coins)


def _fast_feed_coin_list(*, max_n: int = 50) -> list[str]:
    """bookTicker — tam watchlist + açık pozisyonlar (demo giriş fill)."""
    out: list[str] = []
    seen: set[str] = set()
    for c in sorted(_watchlist_coin_set()):
        key = str(c).upper().replace("USDT", "")
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    for c in _all_open_position_coins(refresh_paper=True):
        key = str(c).upper().replace("USDT", "")
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out[:max_n]


def _sync_position_fast_feed() -> None:
    """Watchlist + açık pozisyon sembollerini bookTicker akışına abone et."""
    _ensure_ws_price_feeds()
    if _async_hub_enabled():
        return
    global _last_fast_feed_coins
    coins = _fast_feed_coin_list()
    if not coins:
        _last_fast_feed_coins = frozenset()
        return
    key = frozenset(coins)
    if key == _last_fast_feed_coins:
        return
    _last_fast_feed_coins = key
    try:
        from binance_futures_trader.fast_price_ws import ensure_fast_feed_started

        ensure_fast_feed_started(coins)
    except Exception:
        pass


def _refresh_paper_open_coins_cache(*, force: bool = False, fast: bool = False) -> list[str]:
    """Paper açık coin listesi — pozisyon varken sık güncelle."""
    global _paper_open_coins_cache
    now = time.time()
    ttl = 0.05 if fast else 0.15
    if not force and now - _paper_open_coins_cache[0] < ttl:
        return list(_paper_open_coins_cache[1])
    try:
        extra = sorted(set(parallel_engine.open_position_coins()))
    except Exception:
        extra = list(_paper_open_coins_cache[1])
    _paper_open_coins_cache = (now, extra)
    return extra


def _mark_price_bulk(*, max_recv_age_sec: float = 120) -> dict[str, float]:
    """Mark WS/REST toplu fiyat — pozisyon tick ve panel için."""
    try:
        from binance_futures_trader.mark_ws import get_mark_prices_bulk

        bulk = get_mark_prices_bulk(max_recv_age_sec=max_recv_age_sec)
        if bulk:
            return bulk
    except Exception:
        pass
    try:
        from binance_futures_trader.mark_ws import get_mark_prices

        return get_mark_prices(max_age_sec=max(max_recv_age_sec, 30))
    except Exception:
        return {}


def _live_prices_for_open_coins(coins: list[str], *, max_age_ms: float = 800) -> dict[str, float]:
    """Açık pozisyon coinleri — bookTicker önce (sub-s), mark yedek."""
    if not coins:
        return {}
    out: dict[str, float] = {}
    age_ms = int(max(80, max_age_ms))
    try:
        from binance_futures_trader.fast_price_ws import get_all_fast_prices, get_fast_price

        bulk_fast = get_all_fast_prices(max_age_ms=age_ms)
        for coin in coins:
            key = str(coin).upper()
            d = bulk_fast.get(key)
            if d and float(d.get("mid") or 0) > 0:
                out[coin] = float(d["mid"])
        for coin in coins:
            if coin in out:
                continue
            d = get_fast_price(coin, max_age_ms=age_ms)
            if d and float(d.get("mid") or 0) > 0:
                out[coin] = float(d["mid"])
    except Exception:
        pass
    missing = [c for c in coins if c not in out]
    if missing:
        bulk = _mark_price_bulk(max_recv_age_sec=45)
        for coin in missing:
            key = str(coin).upper()
            px = bulk.get(key) or bulk.get(coin)
            if px and float(px) > 0:
                out[coin] = float(px)
    return out


def _is_binance_truth_row(p: dict[str, Any]) -> bool:
    """Canlı borsa satırı — mark/uPnL yalnızca REST positionRisk."""
    return bool(
        p.get("on_exchange")
        or p.get("exchange_synced")
        or str(p.get("data_source") or "") == "binance"
    )


def _apply_live_mark_to_open_rows(open_ui: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Paper/mode_book satırlarına WS fiyat — Binance satırlarına dokunma."""
    if not open_ui:
        return open_ui
    paper_rows = [p for p in open_ui if not _is_binance_truth_row(p)]
    if not paper_rows:
        return open_ui
    coins = sorted(
        {str(p.get("symbol") or "").replace("USDT", "") for p in paper_rows if p.get("symbol")}
    )
    bulk = _live_prices_for_open_coins(coins, max_age_ms=900)
    if len(bulk) < 5:
        with _price_cache_lock:
            if _price_cache and (time.time() - _price_cache_ts) < 30:
                bulk = {**_price_cache, **bulk}
    if not bulk:
        return open_ui
    for p in paper_rows:
        sym = str(p.get("symbol") or "")
        coin = sym.replace("USDT", "")
        px = float(bulk.get(coin) or bulk.get(sym) or bulk.get(coin.upper()) or 0)
        if px <= 0:
            continue
        ep = float(p.get("entry_price") or px)
        size = float(p.get("size") or 0)
        side = str(p.get("side") or "LONG")
        stake = max(float(p.get("stake_usd") or 1), 0.01)
        p["current_price"] = px
        if size > 0 and ep > 0:
            if side == "LONG":
                p["unrealized_pnl"] = round((px - ep) * size, 4)
            else:
                p["unrealized_pnl"] = round((ep - px) * size, 4)
            p["pnl_pct"] = round(float(p["unrealized_pnl"]) / stake * 100, 4)
            p["position_value"] = round(size * px, 4)
    return open_ui


def _overlay_ws_marks_on_binance_open_ui(
    open_ui: list[dict[str, Any]],
    *,
    stale_after_ms: float = 5000,
) -> list[dict[str, Any]]:
    """positionRisk gecikince panel mark — bookTicker/mark WS (canlı flash için)."""
    if not open_ui:
        return open_ui
    rows = [p for p in open_ui if _is_binance_truth_row(p)]
    if not rows:
        return open_ui
    now_ms = int(time.time() * 1000)
    exch_stale = (
        not _exchange_cache_ts
        or (time.time() - float(_exchange_cache_ts)) > max(8.0, stale_after_ms / 1000.0)
    )
    if exch_stale:
        target_rows = rows
    else:
        target_rows = [
            p
            for p in rows
            if (now_ms - int(p.get("exchange_update_ms") or 0)) > stale_after_ms
        ]
    if not target_rows:
        return open_ui
    coins = sorted(
        {str(p.get("symbol") or "").replace("USDT", "") for p in target_rows if p.get("symbol")}
    )
    bulk = _prices_for_coins(coins, max_age_ms=1200)
    if not bulk:
        return open_ui
    for p in target_rows:
        sym = str(p.get("symbol") or "")
        coin = sym.replace("USDT", "")
        px = float(bulk.get(coin) or bulk.get(sym) or bulk.get(coin.upper()) or 0)
        if px <= 0:
            continue
        disp = dict(p.get("exchange_display") or {})
        prev_str = str(disp.get("markPrice") or p.get("current_price") or "")
        new_str = f"{px:.8f}"
        if prev_str == new_str:
            continue
        p["current_price"] = px
        disp["markPrice"] = new_str
        entry = float(p.get("entry_price") or 0)
        size = float(p.get("size") or 0)
        side = str(p.get("side") or "LONG")
        if size > 0 and entry > 0:
            if side == "LONG":
                unreal = (px - entry) * size
            else:
                unreal = (entry - px) * size
            unreal = round(unreal, 8)
            p["unrealized_pnl"] = round(unreal, 4)
            margin = float(p.get("margin_used") or p.get("stake_usd") or 0)
            if margin > 0:
                p["pnl_pct"] = round(unreal / margin * 100.0, 4)
            disp["unRealizedProfit"] = f"{unreal:.8f}"
        p["exchange_display"] = disp
        p["mark_ws_overlay"] = True
        p["mark_ws_overlay_ms"] = now_ms
    return open_ui


def _prices_for_coins(
    coins: list[str], *, deadline: float | None = None, max_age_ms: float = 900
) -> dict[str, float]:
    """Yalnızca istenen coinler — bookTicker önce (sub-s), mark/REST yedek."""
    if not coins:
        return {}
    age_ms = int(max(60, max_age_ms))
    out: dict[str, float] = {}
    if _async_hub_enabled():
        try:
            from binance_futures_trader.async_hub import get_orchestrator

            orch = get_orchestrator()
            if orch:
                live = orch.get_all_prices_bulk(max_recv_age_sec=max(1.0, age_ms / 1000.0))
                for coin in coins:
                    if deadline is not None and time.perf_counter() >= deadline:
                        break
                    key = str(coin).upper()
                    px = live.get(key) or live.get(coin)
                    if px and float(px) > 0:
                        out[coin] = float(px)
                if len(out) >= len(coins):
                    return out
        except Exception:
            pass
    from binance_futures_trader.fast_price_ws import get_all_fast_prices, get_fast_price
    try:
        bulk_fast = get_all_fast_prices(max_age_ms=age_ms)
        for coin in coins:
            if deadline is not None and time.perf_counter() >= deadline:
                break
            d = bulk_fast.get(str(coin).upper())
            if d and float(d.get("mid") or 0) > 0:
                out[coin] = float(d["mid"])
    except Exception:
        pass
    if deadline is None or time.perf_counter() < deadline:
        try:
            from binance_futures_trader.mark_ws import get_mark_prices_bulk

            bulk_mark = get_mark_prices_bulk(max_recv_age_sec=45)
            for coin in coins:
                if coin in out:
                    continue
                if deadline is not None and time.perf_counter() >= deadline:
                    break
                key = str(coin).upper()
                px = bulk_mark.get(key) or bulk_mark.get(coin)
                if px and float(px) > 0:
                    out[coin] = float(px)
        except Exception:
            pass
    for coin in coins:
        if coin in out:
            continue
        if deadline is not None and time.perf_counter() >= deadline:
            break
        d = get_fast_price(coin, max_age_ms=age_ms)
        if d and float(d.get("mid") or 0) > 0:
            out[coin] = float(d["mid"])
    missing = [c for c in coins if c not in out]
    if missing:
        for coin, px in _prices_from_local_ticks(missing).items():
            if coin not in out and px > 0:
                out[coin] = float(px)
    missing = [c for c in coins if c not in out]
    try:
        from elite_trader.network_guard import is_degraded, skip_rest
    except Exception:
        is_degraded = lambda: False  # type: ignore
        skip_rest = lambda: False  # type: ignore
    if missing and (deadline is None or time.perf_counter() < deadline) and not skip_rest():
        try:
            from binance_futures_trader.mark_ws import get_mark_prices

            relaxed = get_mark_prices(max_age_sec=600)
            for coin in missing:
                px = relaxed.get(str(coin).upper()) or relaxed.get(coin)
                if px and float(px) > 0:
                    out[coin] = float(px)
        except Exception:
            try:
                from elite_trader.network_guard import note_failure

                note_failure(kind="mark_rest")
            except Exception:
                pass
    if deadline is None or time.perf_counter() < deadline:
        try:
            from elite_trader.network_guard import is_degraded
        except Exception:
            is_degraded = lambda: False  # type: ignore
        cache_ttl = 60.0 if is_degraded() else 12.0
        cache_fresh = (time.time() - _price_cache_ts) < cache_ttl
        tick_px = _prices_from_local_ticks(coins, max_age_sec=3.0)
        for coin, px in tick_px.items():
            if coin not in out and px > 0:
                out[coin] = float(px)
        with _price_cache_lock:
            for coin in coins:
                if coin in out:
                    continue
                if deadline is not None and time.perf_counter() >= deadline:
                    break
                if not cache_fresh and not is_degraded():
                    continue
                px = _price_cache.get(coin) or _price_cache.get(str(coin).upper())
                if px and float(px) > 0:
                    out[coin] = float(px)
    return out


def _position_time_label() -> str:
    """Grafik zaman damgası — isoformat yerine hafif etiket."""
    global _position_ts_cache
    now = time.time()
    if now - _position_ts_cache[0] < 0.04:
        return _position_ts_cache[1]
    label = datetime.utcfromtimestamp(now).strftime("%H:%M:%S.") + f"{int(now * 1000) % 1000:03d}"
    _position_ts_cache = (now, label)
    return label


def _patch_exchange_cache_marks(bulk: dict[str, float]) -> None:
    """Devre dışı — mark/uPnL yalnızca REST positionRisk (WS ile ezme flash sapması)."""
    del bulk  # tick çıkış kararları bulk kullanır; borsa önbelleğine yazılmaz
    return


def _apply_position_price_tick(pos: dict[str, Any], bulk: dict[str, float]) -> None:
    on_ex = bool(pos.get("on_exchange")) and LIVE_ORDERS and not client.paper
    if on_ex:
        from elite_trader.exchange_position_sync import light_sync_exchange_fields

        sym = str(pos.get("symbol") or "")
        side = str(pos.get("side") or "LONG").upper()
        sym_u = sym.upper()
        ep_match: dict[str, Any] | None = None
        for ep in _positions_cache:
            rs = str(ep.get("symbol") or f"{ep.get('coin')}USDT").upper()
            if rs == sym_u and str(ep.get("side") or "LONG").upper() == side:
                ep_match = ep
                break
        if ep_match:
            if _position_tick_seq % 12 == 0:
                from elite_trader.exchange_position_sync import apply_exchange_snapshot

                apply_exchange_snapshot(pos, ep_match)
            else:
                light_sync_exchange_fields(pos, ep_match)
            mark = float(pos.get("current_price") or 0)
            if mark > 0:
                hist = pos.setdefault("price_history", [])
                times = pos.setdefault("time_history", [])
                if not hist or abs(hist[-1] - mark) > 1e-12:
                    hist.append(mark)
                    times.append(_position_time_label())
                    if len(hist) > 60:
                        hist.pop(0)
                        times.pop(0)
        return

    sym = pos["symbol"]
    coin_key = sym.replace("USDT", "")
    bulk_price = bulk.get(coin_key) or bulk.get(sym) or bulk.get(coin_key.upper())
    if not bulk_price or float(bulk_price) <= 0:
        return
    px = float(bulk_price)
    pos["price_history"].append(px)
    pos["time_history"].append(_position_time_label())
    if len(pos["price_history"]) > 60:
        pos["price_history"].pop(0)
        pos["time_history"].pop(0)
    pos["current_price"] = px

    # Paper positions: calculate from mark price
    if not on_ex:
        ep = float(pos.get("entry_price") or px)
        size = float(pos.get("size") or 0)
        side = str(pos.get("side") or pos.get("type") or "LONG")
        if size > 0 and ep > 0:
            if side == "LONG":
                pos["unrealized_pnl"] = (px - ep) * size
            else:
                pos["unrealized_pnl"] = (ep - px) * size
            stake = max(float(pos.get("stake_usd") or 1), 0.01)
            pos["pnl_pct"] = float(pos["unrealized_pnl"]) / stake * 100


def _try_proactive_hedges() -> None:
    """Zararda ana pozisyon açık — ters bacak ayrı TP hedefiyle (reverse yok)."""
    if not LIVE_ORDERS or client.paper or not positions:
        return
    from elite_trader.position_hedge import (
        has_hedge_for,
        hedge_cooldown_ok,
        hedge_exchange_supported,
        hedge_live_enabled,
        hedge_stake_frac,
        is_hedge_leg,
        mark_hedge_attempt,
        needs_live_hedge,
        opposite_side,
    )

    if not hedge_live_enabled() or not hedge_exchange_supported(client=client):
        return
    for pos in list(positions):
        if is_hedge_leg(pos):
            continue
        if not needs_live_hedge(pos):
            continue
        if has_hedge_for(pos, positions):
            pos["hedge_pending"] = False
            continue
        if not hedge_cooldown_ok(pos):
            continue
        mark_hedge_attempt(pos)
        sym = pos["symbol"]
        opp = opposite_side(str(pos["side"]))
        unreal = float(pos.get("unrealized_pnl") or 0)
        stake_main = float(pos.get("stake_usd") or 120)
        hedge_stake = max(stake_main * hedge_stake_frac(), 50.0)
        age_min = position_age_seconds(pos) / 60.0
        print(
            f"  🛡 HEDGE-TP {sym} {pos['side']}→{opp} "
            f"stake≈${hedge_stake:.0f} uPnL=${unreal:.2f} age={age_min:.1f}dk"
        )
        if not _assert_live_open_slot(sym, hedge=True):
            pos["hedge_pending"] = False
            continue
        child = _open_hedge_leg(pos, opp_side=opp, stake_usd=hedge_stake)
        if child:
            pos["hedge_pending"] = False
        else:
            pos["hedge_pending"] = False


def _try_position_rescues() -> None:
    """Eski kurtarma — ELITE_RESCUE_ENABLED=0 iken kapalı."""
    if not LIVE_ORDERS or client.paper or not positions:
        return
    from elite_trader.position_rescue import (
        mark_rescue_attempt,
        needs_rescue,
        opposite_side,
        pick_rescue_action,
        rescue_cooldown_ok,
        rescue_enabled,
        rescue_stake_frac,
    )

    if not rescue_enabled():
        return
    for pos in list(positions):
        if not needs_rescue(pos):
            continue
        if not rescue_cooldown_ok(pos):
            continue
        action = pick_rescue_action(pos, positions)
        if not action:
            continue
        mark_rescue_attempt(pos)
        sym = pos["symbol"]
        unreal = float(pos.get("unrealized_pnl") or 0)
        age_min = position_age_seconds(pos) / 60.0
        if action == "reverse":
            print(
                f"  🔄 RESCUE-REVERSE {sym} {pos['side']} "
                f"uPnL=${unreal:.2f} age={age_min:.1f}dk"
            )
            pid = pos["id"]
            if close_position(pid, "RESCUE-REVERSE"):
                opp = opposite_side(str(pos["side"]))
                child = open_position(
                    sym,
                    opp,
                    0.0,
                    leverage=int(pos.get("leverage") or 5),
                    signal_source="RescueReverse",
                    rescue_bypass=True,
                )
                if child:
                    child["rescue_leg"] = True
                    child["rescue_of_id"] = pid
                    child["rescue_action"] = "reverse"
                    pos["rescue_pending"] = False
            else:
                pos["rescue_pending"] = False
            continue
        opp = opposite_side(str(pos["side"]))
        stake_main = float(pos.get("stake_usd") or 120)
        hedge_stake = max(stake_main * rescue_stake_frac(), 50.0)
        print(
            f"  🛡 RESCUE-HEDGE {sym} {pos['side']}→{opp} "
            f"stake≈${hedge_stake:.0f} uPnL=${unreal:.2f} age={age_min:.1f}dk"
        )
        if not _assert_live_open_slot(sym, rescue=True):
            pos["rescue_pending"] = False
            continue
        child = _open_hedge_leg(pos, opp_side=opp, stake_usd=hedge_stake, rescue=True)
        if child:
            child["rescue_leg"] = True
            child["rescue_of_id"] = pos.get("id")
            child["rescue_action"] = "hedge"
            pos["rescue_pending"] = False
        else:
            pos["rescue_pending"] = False


def _open_hedge_leg(
    parent: dict[str, Any],
    *,
    opp_side: str,
    stake_usd: float,
    rescue: bool = False,
) -> dict[str, Any] | None:
    """Ters yön hedge — ana pozisyon açık kalır; bacak normal TP/SL ile kapanır."""
    from elite_trader.position_hedge import hedge_exchange_supported

    if not hedge_exchange_supported(client=client):
        return None
    symbol = str(parent.get("symbol") or "")
    if not symbol:
        return None
    lev = max(int(parent.get("leverage") or 5), 1)
    entry_price, _ = fetch_price(symbol)
    if entry_price <= 0:
        return None
    coin = symbol.replace("USDT", "")
    size = stake_usd * lev / entry_price
    with _live_open_lock:
        _refresh_positions_cache_only(force=True)
        slot_ok = _assert_live_open_slot(
            symbol, rescue=rescue, hedge=not rescue
        )
        if not slot_ok:
            return None
    try:
        client.ensure_margin_type(coin)
        client.ensure_leverage(coin, lev)
        qty = client.round_qty(coin, size)
        if qty <= 0:
            return None
        order = client.market_order(coin, opp_side, qty, reduce_only=False)
    except Exception as exc:
        tag = "RESCUE-HEDGE" if rescue else "HEDGE-TP"
        print(f"  ⛔ {tag} emir {symbol}: {exc}")
        return None
    global position_id_counter
    position_id_counter += 1
    from elite_trader.fee_economics import apply_net_targets_to_position, tp_sl_gross_triggers

    ex_mode = active_execution_mode()
    tp_usd, sl_usd, net_tp, rt_fee = tp_sl_gross_triggers(stake_usd, lev, ex_mode)
    child: dict[str, Any] = {
        "id": position_id_counter,
        "symbol": symbol,
        "side": opp_side,
        "entry_price": entry_price,
        "current_price": entry_price,
        "size": qty,
        "leverage": lev,
        "stake_usd": stake_usd,
        "unrealized_pnl": 0.0,
        "opened_at_iso": datetime.now(timezone.utc).isoformat(),
        "entry_time": time.time(),
        "tp_target_usd": tp_usd,
        "sl_target_usd": sl_usd,
        "tp_net_target_usd": net_tp,
        "round_trip_fee_est_usd": rt_fee,
        "signal_source": "HedgeTP",
        "on_exchange": True,
        "exchange_order_id": str(order.get("orderId") or ""),
        "panel_mode": ex_mode,
        "min_unreal_seen": 0.0,
        "max_unreal_seen": 0.0,
        "hedge_leg": True,
        "hedge_of_id": parent.get("id"),
        "leg_type": "hedge",
    }
    apply_net_targets_to_position(child, ex_mode)
    positions.append(child)
    time.sleep(0.12)
    _refresh_positions_cache_only(force=True)
    return child


def _open_rescue_hedge(
    parent: dict[str, Any],
    *,
    opp_side: str,
    stake_usd: float,
) -> dict[str, Any] | None:
    """Geriye uyumluluk — yeni hedge bacakları _open_hedge_leg kullanır."""
    return _open_hedge_leg(parent, opp_side=opp_side, stake_usd=stake_usd, rescue=True)


def _check_live_position_exits(bulk: dict[str, float]) -> None:
    """Ana Hat — fiyat tick sonrası anında TP/SL."""
    if not positions:
        return
    exec_mode = active_execution_mode()
    from elite_trader.exchange_position_sync import process_position_exit

    exch_list = list(_positions_cache) if LIVE_ORDERS and not client.paper else []
    
    # UPDATE: Exchange positions için de max/min unreal tracking
    for ep in _positions_cache:
        unreal = float(ep.get("unrealized_pnl") or 0)
        ep["max_unreal_seen"] = max(float(ep.get("max_unreal_seen", unreal)), unreal)
        ep["min_unreal_seen"] = min(float(ep.get("min_unreal_seen", unreal)), unreal)
    
    for pos in list(positions):
        unreal = float(pos.get("unrealized_pnl") or 0)
        pos["max_unreal_seen"] = max(float(pos.get("max_unreal_seen", unreal)), unreal)
        pos["min_unreal_seen"] = min(float(pos.get("min_unreal_seen", unreal)), unreal)
        
        # TP Timer DISABLED - WS price unreliable, causing false positives
        # Only use SPIKE exits with REST verify
        from elite_trader.panel_strategy import position_age_seconds
        age = position_age_seconds(pos)
        
        # TP Timer disabled - use only SPIKE with REST verify
        
        exit_reason = process_position_exit(
            pos,
            exchange_positions=exch_list,
            bulk_prices=bulk,
            exec_mode=exec_mode,
            live_orders=LIVE_ORDERS,
            client_paper=client.paper,
        )
        if exit_reason:
            if pos.get("on_exchange") and exit_reason in (
                "TP",
                "TP-RECOVER",
                "SL",
                "SPIKE-QUICK",
                "SPIKE-PEAK",
                "SPIKE-FLASH",
                "STALE-RELEASE",
                "STALE-RECOVER",
                "TP-TIMER",
            ):
                print(
                    f"  🎯 {exit_reason} {pos['symbol']} uPnL=${unreal:.4f} "
                    f"(borsa) tp=${pos.get('tp_target_usd')} sl=${pos.get('sl_target_usd')}"
                )
            close_position(pos["id"], exit_reason)

    _try_proactive_hedges()
    _try_position_rescues()


def update_open_positions_fast() -> float:
    """Açık pozisyonlar — hızlı fiyat patch + bütçeli TP/SL (paper + live)."""
    global last_position_price_ms, last_avg_latency_ms, _last_position_price_at
    global _last_position_missing_n, _position_tick_seq
    t0 = time.perf_counter()
    budget_ms = _position_price_budget_ms()
    deadline = t0 + budget_ms / 1000.0
    max_age = _position_price_max_age_ms()
    _position_tick_seq += 1

    paper_coins = _refresh_paper_open_coins_cache(
        fast=True, force=(_position_tick_seq % 8 == 0)
    )
    try:
        from elite_trader.mega_live import mega_motor_active, mega_open_coins

        mega_coins = (
            mega_open_coins(sync_if_missing=False) if mega_motor_active() else []
        )
    except Exception:
        mega_coins = []
    mega_primary = False
    try:
        mega_primary = _is_mega_primary_process() and bool(mega_coins)
    except Exception:
        mega_primary = False
    live_coins = [p["symbol"].replace("USDT", "") for p in positions]
    live_exchange_only = (
        LIVE_ORDERS
        and not client.paper
        and positions
        and all(bool(p.get("on_exchange")) for p in positions)
    )
    coins = sorted(set(live_coins) | set(paper_coins) | set(mega_coins))
    if not coins and not positions:
        last_position_price_ms = 0.0
        _last_position_price_at = time.time()
        return 0.0

    bulk: dict[str, float] = {}
    if mega_primary:
        sim_only = False
        try:
            from elite_trader.mega_live import mega_live_enabled, mega_sim_enabled

            sim_only = mega_sim_enabled() and not mega_live_enabled()
        except Exception:
            pass
        mega_deadline = t0 + (
            min(0.15, budget_ms / 1000.0) if sim_only else min(0.028, budget_ms / 1000.0)
        )
        bulk = _prices_for_coins(mega_coins, deadline=mega_deadline, max_age_ms=max_age)
        if not bulk:
            bulk = _prices_from_local_ticks(mega_coins)
        if not bulk:
            with _price_cache_lock:
                bulk = {
                    c: float(_price_cache[c])
                    for c in mega_coins
                    if _price_cache.get(c) and float(_price_cache[c]) > 0
                }
        try:
            from elite_trader.mega_live import (
                _mega_sim_price_bulk,
                check_mega_exits,
                refresh_mega_sim_marks,
            )

            refresh_mega_sim_marks(bulk)
            prices = bulk if bulk else _mega_sim_price_bulk()
            if prices:
                check_mega_exits(prices)
        except Exception as exc:
            _note_position_stall("mega_exit", str(exc)[:80])
        _last_position_price_at = time.time()
        last_position_price_ms = (time.perf_counter() - t0) * 1000.0
        return last_position_price_ms

    if not live_exchange_only and coins:
        bulk = _prices_for_coins(coins, deadline=deadline, max_age_ms=max_age)
        if not bulk and coins:
            bulk = _prices_from_local_ticks(coins)
        if not bulk and coins:
            try:
                from elite_trader.network_guard import is_degraded
            except Exception:
                is_degraded = lambda: False  # type: ignore
            if is_degraded():
                with _price_cache_lock:
                    bulk = {
                        c: float(_price_cache[c])
                        for c in coins
                        if _price_cache.get(c) and float(_price_cache[c]) > 0
                    }
        if not bulk and coins:
            with _price_cache_lock:
                bulk = {
                    c: float(_price_cache[c])
                    for c in coins
                    if _price_cache.get(c) and float(_price_cache[c]) > 0
                }

        missing = [c for c in coins if c not in bulk]
        _last_position_missing_n = len(missing)
        if missing and len(missing) >= len(coins):
            _note_position_stall(
                "fiyat_eksik",
                f"{len(missing)}/{len(coins)} coin fiyat yok ({', '.join(missing[:4])})",
            )
    else:
        _last_position_missing_n = 0

    if paper_coins and bulk:
        try:
            parallel_engine.patch_open_prices(bulk)
        except Exception as exc:
            _note_position_stall("paper_patch", str(exc)[:80])

    _last_position_price_at = time.time()
    price_ms = (time.perf_counter() - t0) * 1000.0
    last_position_price_ms = price_ms

    if positions:
        for pos in positions:
            _apply_position_price_tick(pos, bulk)
        if LIVE_ORDERS and not client.paper:
            if _position_tick_seq % 4 == 0:
                try:
                    from elite_trader.exchange_trade_truth import enrich_open_entry_fee_api
                    from elite_trader.fee_economics import entry_fee_api_ready

                    for pos in positions:
                        if pos.get("on_exchange") and not entry_fee_api_ready(pos):
                            enrich_open_entry_fee_api(pos, client, allow_fetch=True)
                except Exception:
                    pass
            _check_live_position_exits(bulk)

    if (
        paper_coins
        and bulk
        and not mega_primary
        and (_position_tick_seq % _position_exit_every_n() == 0)
    ):
        exit_deadline = time.time() + _position_exit_budget_ms() / 1000.0
        try:
            parallel_engine.check_paper_exits(bulk, deadline=exit_deadline)
        except Exception as exc:
            _note_position_stall("paper_exit", str(exc)[:80])

    if mega_coins and bulk and not mega_primary:
        try:
            from elite_trader.mega_live import check_mega_exits

            check_mega_exits(bulk)
        except Exception as exc:
            _note_position_stall("mega_exit", str(exc)[:80])
    elif mega_coins and not mega_primary:
        try:
            from elite_trader.mega_live import check_mega_exits

            check_mega_exits({})
        except Exception as exc:
            _note_position_stall("mega_exit", str(exc)[:80])

    loop_ms = (time.perf_counter() - t0) * 1000.0
    if loop_ms > budget_ms * 1.5 and paper_coins:
        _note_position_stall(
            "yavas_tur",
            f"tur {loop_ms:.0f}ms (fiyat {price_ms:.0f}ms, bütçe {budget_ms:.0f}ms)",
        )
    return last_position_price_ms


def update_open_position_prices_fast() -> float:
    """Geriye uyumluluk."""
    return update_open_positions_fast()


def _closed_ram_max() -> int:
    return max(100, _env_int("ELITE_CLOSED_RAM_MAX", 500))


def _trim_closed_positions_ram() -> None:
    """RAM'de kapalı pozisyon listesini sınırla."""
    global closed_positions
    cap = _closed_ram_max()
    if len(closed_positions) > cap:
        del closed_positions[: len(closed_positions) - cap]


def _position_price_worker() -> None:
    """Açık pozisyon — sürekli fiyat patch + bütçeli TP/SL."""
    global _last_position_price_at, _last_paper_coin_count
    gen = _position_thread_generation
    tick = 0
    while not _position_price_stop.is_set() and _position_thread_generation == gen:
        loop_t0 = time.perf_counter()
        tick += 1
        iv = _position_check_interval(has_open=_any_open_positions_for_worker())
        try:
            _position_price_worker_tick(tick, gen, loop_t0)
        except Exception as exc:
            _note_position_stall("worker_fatal", str(exc)[:120])
            if _position_price_wake.wait(timeout=min(2.0, max(0.05, iv))):
                _position_price_wake.clear()
            continue
        wait = max(0.001, iv - (time.perf_counter() - loop_t0))
        if _position_price_wake.wait(timeout=wait):
            _position_price_wake.clear()


def _position_price_worker_tick(tick: int, gen: int, loop_t0: float) -> None:
    """position-price döngüsü — tek tur (hata üst thread'i öldürmez)."""
    global _last_position_price_at, _last_paper_coin_count

    paper_coins = _refresh_paper_open_coins_cache(fast=True, force=(tick <= 2))
    has_live = bool(positions)
    has_paper = bool(paper_coins)
    has_mega = False
    try:
        from elite_trader.mega_live import mega_has_open

        has_mega = mega_has_open()
    except Exception:
        has_mega = False
    has_open = has_live or has_paper or has_mega
    iv = _position_check_interval(has_open=has_open)

    if has_open and has_paper and (
        len(paper_coins) != _last_paper_coin_count or tick <= 2
    ):
        if len(paper_coins) != _last_paper_coin_count:
            _last_paper_coin_count = len(paper_coins)
        try:
            _sync_position_fast_feed()
        except Exception:
            pass

    if has_open:
        try:
            update_open_positions_fast()
        except Exception as exc:
            _note_position_stall("fiyat_patch", str(exc)[:80])
    else:
        _last_position_price_at = time.time()
        _last_paper_coin_count = 0

    loop_ms = (time.perf_counter() - loop_t0) * 1000.0
    stall_mult = _position_stall_loop_mult()
    if has_open and loop_ms > iv * 1000 * stall_mult:
        if time.time() < _position_worker_grace_until:
            pass
        else:
            _note_position_stall(
                "döngü_gecikme",
                f"worker {loop_ms:.0f}ms (hedef {iv * 1000:.0f}ms)",
            )


def _start_position_price_worker() -> None:
    global _position_price_thread
    if _position_price_thread and _position_price_thread.is_alive():
        return
    _position_price_stop.clear()
    _position_price_thread = threading.Thread(
        target=_position_price_worker, name="position-price", daemon=True
    )
    _position_price_thread.start()


def _stop_position_price_worker() -> None:
    _position_price_stop.set()
    if _position_price_thread and _position_price_thread.is_alive():
        _position_price_thread.join(timeout=1.5)


def _exchange_positions_worker() -> None:
    """Pozisyon motoru — sürekli REST positionRisk (tüm açık pozisyonlar)."""
    while not _exchange_poll_stop.is_set():
        loop_t0 = time.perf_counter()
        if LIVE_ORDERS and not client.paper:
            has_open = bool(_positions_cache) or bool(positions)
            iv = (
                _effective_position_poll_interval_sec()
                if has_open
                else _exchange_cache_ttl_sec()
            )
            ok = _refresh_positions_cache_only(
                force=has_open,
                min_interval_sec=iv,
            )
            if ok and has_open:
                _schedule_exchange_reconcile()
            wait = iv
        else:
            wait = _exchange_cache_ttl_sec()
        sleep_s = max(0.02, wait - (time.perf_counter() - loop_t0))
        _exchange_poll_stop.wait(sleep_s)


def _start_exchange_poll_worker() -> None:
    global _exchange_poll_thread
    if _exchange_poll_thread and _exchange_poll_thread.is_alive():
        return
    _exchange_poll_stop.clear()
    _exchange_poll_thread = threading.Thread(
        target=_exchange_positions_worker, name="exchange-poll", daemon=True
    )
    _exchange_poll_thread.start()


def _stop_exchange_poll_worker() -> None:
    _exchange_poll_stop.set()
    if _exchange_poll_thread and _exchange_poll_thread.is_alive():
        _exchange_poll_thread.join(timeout=2.0)


def _fast_tick_worker() -> None:
    """527 evren fiyat tick — yalnızca price_history (motor eval ayrı)."""
    gen = _fast_tick_generation
    while not _fast_tick_stop.is_set() and _fast_tick_generation == gen:
        loop_t0 = time.perf_counter()
        try:
            scan_price_ticks_fast()
        except Exception:
            pass
        wait = max(0.05, _ui_tick_interval_sec() - (time.perf_counter() - loop_t0))
        _fast_tick_stop.wait(wait)


def _motor_scan_worker() -> None:
    """Motor eval — tek daemon thread; bütçe scan_motor_eval içinde (thread sızıntısı yok)."""
    gen = _motor_thread_generation
    hard = _motor_cycle_hard_timeout_sec()
    while not _motor_stop.is_set() and _motor_thread_generation == gen:
        if _berserk2_scan_active():
            # BERSERK2: tarama fast-tick içinde — klasik motoru çalıştırma (GIL/SSL blokajı yok)
            _motor_stop.wait(max(0.18, _env_float("BERSERK2_SCAN_INTERVAL_SEC", 0.28)))
            continue
        loop_t0 = time.perf_counter()
        try:
            scan_motor_eval()
        except Exception:
            pass
        elapsed = time.perf_counter() - loop_t0
        if elapsed > hard:
            print(
                f"  ⚠ Motor tur aşımı {elapsed:.2f}s > {hard:.2f}s "
                f"(executor korunuyor — segfault önleme)"
            )
        iv = _effective_motor_scan_interval_sec()
        _motor_stop.wait(max(0.05, iv - elapsed))


def _start_motor_scan_worker() -> None:
    global _motor_scan_thread
    if _motor_scan_thread and _motor_scan_thread.is_alive():
        return
    _motor_stop.clear()
    _motor_scan_thread = threading.Thread(
        target=_motor_scan_worker, name="motor-scan", daemon=True
    )
    _motor_scan_thread.start()


def _stop_motor_scan_worker() -> None:
    _motor_stop.set()
    if _motor_scan_thread and _motor_scan_thread.is_alive():
        _motor_scan_thread.join(timeout=2.0)


def _ensure_worker_threads() -> None:
    """Ölü daemon thread'leri yeniden başlat."""
    if not (_fast_tick_thread and _fast_tick_thread.is_alive()):
        _start_fast_tick_worker()
    if not _berserk2_scan_active():
        if not (_motor_scan_thread and _motor_scan_thread.is_alive()):
            _start_motor_scan_worker()
    if not (_position_price_thread and _position_price_thread.is_alive()):
        _start_position_price_worker()
    if not (_snapshot_refresh_thread and _snapshot_refresh_thread.is_alive()):
        _start_snapshot_refresh()
    if not (_exchange_poll_thread and _exchange_poll_thread.is_alive()):
        _start_exchange_poll_worker()


_HEARTBEAT_PATH = _ROOT / ".pids" / "elite_9005_heartbeat.json"


def _exit_gate_snapshot() -> dict[str, Any]:
    try:
        from elite_trader.fee_economics import exit_gate_stats, exit_tp_only

        s = exit_gate_stats()
        s["tp_only"] = exit_tp_only(active_execution_mode())
        return s
    except Exception:
        return {}


def _heartbeat_payload() -> dict[str, Any]:
    """Canlı süreç durumu — bellek/heartbeat (disk parallel_universes değil)."""
    ff: dict[str, Any] = {}
    try:
        from binance_futures_trader.fast_price_ws import fast_feed_status

        ff = fast_feed_status()
    except Exception:
        pass
    mw: dict[str, Any] = {}
    try:
        from binance_futures_trader.mark_ws import feed_status

        mw = feed_status()
    except Exception:
        pass
    try:
        paper_open = sum(parallel_engine.open_counts_by_mode().values())
    except Exception:
        paper_open = 0
    pos_iv = _position_check_interval(has_open=_any_open_positions_for_worker())
    mega_h: dict[str, Any] = {}
    try:
        from elite_trader.mega_live import mega_health, mega_motor_active

        if mega_motor_active():
            mega_h = mega_health()
    except Exception:
        pass
    return {
        "pid": os.getpid(),
        "ts": time.time(),
        "iso": datetime.utcnow().isoformat() + "Z",
        "tick_ago": round(time.time() - _last_tick_at, 3) if _last_tick_at else None,
        "motor_ago": round(time.time() - _last_motor_at, 3) if _last_motor_at else None,
        "position_ago": round(time.time() - _last_position_price_at, 3)
        if _last_position_price_at
        else None,
        "position_tick_ms": round(last_position_price_ms, 1),
        "position_interval_ms": round(pos_iv * 1000, 0),
        "fast_tick_ms": round(last_tick_ms, 1),
        "motor_eval_ms": round(last_scan_ms, 1),
        "motor_interval_ms": round(_effective_motor_scan_interval_sec() * 1000, 0),
        "position_missing": _last_position_missing_n,
        "position_stalls": _position_stalls_total,
        "position_restarts": _position_stuck_restarts,
        "recoveries": _motor_recoveries,
        "paper_open": paper_open,
        "live_open": len(positions),
        "live_max_open": execution_max_open(),
        "exit_gate": _exit_gate_snapshot(),
        "threads": {
            "fast_tick": bool(_fast_tick_thread and _fast_tick_thread.is_alive()),
            "motor_scan": bool(_motor_scan_thread and _motor_scan_thread.is_alive()),
            "position_price": bool(
                _position_price_thread and _position_price_thread.is_alive()
            ),
            "exchange_poll": bool(
                _exchange_poll_thread and _exchange_poll_thread.is_alive()
            ),
            "watchdog": bool(_watchdog_thread and _watchdog_thread.is_alive()),
            "connection_keeper": bool(
                _connection_keeper_thread and _connection_keeper_thread.is_alive()
            ),
        },
        "exchange_poll_ms": round(_exchange_position_poll_ms, 1),
        "exchange_poll_timeouts": _exchange_position_poll_timeouts,
        "exchange_api_min_ms": round(_exchange_api_ms_min, 1) or None,
        "exchange_api_ema_ms": round(_exchange_api_ms_ema, 1) or None,
        "exchange_poll_iv_ms": round(_effective_position_poll_interval_sec() * 1000, 0),
        "exchange_cache_age_ms": (
            int((time.time() - _exchange_cache_ts) * 1000)
            if _exchange_cache_ts
            else None
        ),
        "price_feed": {
            "mark_ws": {
                "connected": bool(mw.get("connected")),
                "lag_ms": mw.get("lag_ms"),
                "coins": mw.get("coins"),
                "health": mw.get("health"),
            },
            "fast_feed": {
                "connected": bool(ff.get("connected")),
                "lag_ms": ff.get("lag_ms"),
                "coins": ff.get("coins"),
                "source": ff.get("source"),
                "book_coins": ff.get("book_coins"),
            },
        },
        "mega": mega_h,
    }


def _write_process_heartbeat() -> None:
    """Dış supervisor — süreç canlılık dosyası."""
    try:
        _HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = _heartbeat_payload()
        _HEARTBEAT_PATH.write_text(
            json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except Exception:
        pass


def _connection_keepalive_interval_sec() -> float:
    return max(3.0, min(30.0, _env_float("ELITE_CONNECTION_KEEPALIVE_SEC", 6.0)))


def _demo_reconnect_interval_sec() -> float:
    return max(5.0, min(120.0, _env_float("ELITE_DEMO_API_RECONNECT_SEC", 10.0)))


def _ws_feed_needs_reconnect() -> tuple[bool, bool]:
    """Mark / bookTicker gecikme veya kopukluk."""
    max_lag = _env_int("ELITE_WS_MAX_LAG_MS", 3500)
    mark_stale = False
    fast_stale = False
    try:
        from binance_futures_trader.mark_ws import feed_status

        ms = feed_status()
        if not ms.get("connected"):
            mark_stale = True
        else:
            lag = int(ms.get("lag_ms") or 0)
            if lag > max_lag:
                mark_stale = True
    except Exception:
        mark_stale = True
    try:
        from binance_futures_trader.fast_price_ws import fast_feed_status

        ff = fast_feed_status()
        if ff.get("enabled"):
            if not ff.get("connected"):
                fast_stale = True
            else:
                lag = int(ff.get("lag_ms") or 0)
                if lag > max_lag:
                    fast_stale = True
    except Exception:
        pass
    return mark_stale, fast_stale


def _connection_keeper_tick() -> None:
    """Demo API + WS — kopuklukta hızlı yeniden bağlan."""
    global _last_demo_reconnect_try, _last_api_warm_at
    now = time.time()

    mark_stale, fast_stale = _ws_feed_needs_reconnect()
    if mark_stale or fast_stale:
        _ensure_ws_price_feeds(force_reconnect=True)

    if LIVE_ORDERS:
        if client.paper:
            if now - _last_demo_reconnect_try >= _demo_reconnect_interval_sec():
                _last_demo_reconnect_try = now
                _try_reconnect_demo_api()
        elif now - _last_api_warm_at >= _connection_keepalive_interval_sec():
            try:
                from elite_trader.network_guard import binance_rest_enabled

                if not binance_rest_enabled():
                    pass
                else:
                    _last_api_warm_at = now
                    if client.api_ping():
                        from elite_trader.network_guard import note_success

                        note_success()
                    else:
                        from elite_trader.network_guard import note_failure

                        note_failure(kind="api_ping")
            except Exception:
                pass


def _connection_keeper_worker() -> None:
    iv = _connection_keepalive_interval_sec()
    while not _connection_keeper_stop.is_set():
        try:
            _connection_keeper_tick()
        except Exception:
            pass
        _connection_keeper_stop.wait(iv)


def _start_connection_keeper() -> None:
    global _connection_keeper_thread
    if _connection_keeper_thread and _connection_keeper_thread.is_alive():
        return
    _connection_keeper_stop.clear()
    _connection_keeper_thread = threading.Thread(
        target=_connection_keeper_worker, name="connection-keeper", daemon=True
    )
    _connection_keeper_thread.start()


def _stop_connection_keeper() -> None:
    _connection_keeper_stop.set()
    if _connection_keeper_thread and _connection_keeper_thread.is_alive():
        _connection_keeper_thread.join(timeout=2.0)


def _pipeline_watchdog_worker() -> None:
    """527 tick / motor / sinyal / pozisyon fiyat — sürekli canlılık denetimi."""
    global _last_motor_at
    tick = 0
    while not _watchdog_stop.is_set():
        tick += 1
        now = time.time()
        motor_iv = _effective_motor_scan_interval_sec()
        tick_iv = _ui_tick_interval_sec()
        pos_iv = _position_check_interval(has_open=True)
        stuck_thr = _motor_stuck_threshold_sec()

        motor_stale_thr = max(stuck_thr, motor_iv * 4.0)
        if _berserk2_scan_active():
            motor_stale_thr = max(6.0, _env_float("BERSERK2_MOTOR_STALE_SEC", 12.0))
        if _last_motor_at > 0 and now - _last_motor_at > motor_stale_thr:
            if _berserk2_scan_active():
                _last_motor_at = now
            else:
                stuck = bool(_motor_scan_thread and _motor_scan_thread.is_alive())
                _recover_motor_pipeline(
                    reason=f"stale {now - _last_motor_at:.0f}s (iv={motor_iv:.1f}s"
                    + (", thread takılı" if stuck else ", thread ölü")
                    + ")",
                    force_restart=stuck,
                )

        if _last_tick_at > 0 and now - _last_tick_at > max(3.0, tick_iv * 6.0):
            tick_alive = bool(_fast_tick_thread and _fast_tick_thread.is_alive())
            if tick_alive:
                _force_restart_fast_tick_worker(
                    reason=f"stale {now - _last_tick_at:.0f}s (iv={tick_iv:.2f}s)"
                )
            else:
                _start_fast_tick_worker()

        try:
            ps = parallel_engine.paper_signal_stats()
            if ps.get("pending", 0) > 96:
                print(
                    f"  ⚠ Paper kuyruk birikti: pending={ps.get('pending')} "
                    f"(işlenen={ps.get('processed')})"
                )
        except Exception:
            pass

        pos_thr = _position_stuck_threshold_sec()
        if os.environ.get("BINANCE_ELITE_PORT") in MEGA_PRIMARY_PORTS:
            pos_thr = max(pos_thr, _env_float("MEGA_POSITION_STUCK_SEC", 8.0))
        if _last_position_price_at > 0 and now - _last_position_price_at > pos_thr:
            pos_alive = bool(_position_price_thread and _position_price_thread.is_alive())
            if pos_alive:
                _force_restart_position_worker(
                    reason=f"stale {now - _last_position_price_at:.0f}s"
                )
            else:
                _start_position_price_worker()

        _ensure_worker_threads()
        _write_process_heartbeat()

        if tick % 5 == 0:
            mark_stale, fast_stale = _ws_feed_needs_reconnect()
            if mark_stale or fast_stale:
                _ensure_ws_price_feeds(force_reconnect=True)

        if tick % 300 == 0:
            try:
                _maybe_rollup_data_lake_metrics()
            except Exception:
                pass

        if tick % 30 == 0:
            ss = _scanner_status_dict()
            try:
                paper_open = sum(parallel_engine.open_counts_by_mode().values())
            except Exception:
                paper_open = 0
            if len(watchlist) < 50 and tick % 60 == 0:
                try:
                    refresh_tradeable_universe(force=True)
                except Exception:
                    pass
            print(
                f"  📡 Pipeline: evren={ss.get('symbols_with_ticks', '?')}/{len(watchlist) or len(tradable_symbols) or '?'} "
                f"aday={_last_motor_candidates_n} eval={_last_motor_eval_n} "
                f"sinyal={len(signals)} paper_açık={paper_open}"
            )

        _watchdog_stop.wait(2.0)


def _start_pipeline_watchdog() -> None:
    global _watchdog_thread
    if _watchdog_thread and _watchdog_thread.is_alive():
        return
    _watchdog_stop.clear()
    _watchdog_thread = threading.Thread(
        target=_pipeline_watchdog_worker, name="pipeline-watchdog", daemon=True
    )
    _watchdog_thread.start()


def _stop_pipeline_watchdog() -> None:
    _watchdog_stop.set()
    if _watchdog_thread and _watchdog_thread.is_alive():
        _watchdog_thread.join(timeout=2.0)


def _start_fast_tick_worker() -> None:
    global _fast_tick_thread
    if _fast_tick_thread and _fast_tick_thread.is_alive():
        return
    _fast_tick_stop.clear()
    _fast_tick_thread = threading.Thread(
        target=_fast_tick_worker, name="fast-tick", daemon=True
    )
    _fast_tick_thread.start()


def _stop_fast_tick_worker() -> None:
    _fast_tick_stop.set()
    if _fast_tick_thread and _fast_tick_thread.is_alive():
        _fast_tick_thread.join(timeout=1.5)


def _heavy_snap_cache_fresh() -> bool:
    return (
        bool(_heavy_snap_cache)
        and (time.time() - _heavy_snap_cache_ts) < _HEAVY_SNAP_TTL_SEC
    )


def _store_heavy_snap_cache(snap: dict[str, Any]) -> None:
    global _heavy_snap_cache, _heavy_snap_cache_ts
    elite = snap.get("elite") or {}
    _heavy_snap_cache = {
        "evrim_adaptive": elite.get("evrim_adaptive"),
        "deleted_archives": elite.get("deleted_archives"),
        "mode_archives": elite.get("mode_archives"),
        "market_intelligence": snap.get("market_intelligence"),
        "view_mode_detail": snap.get("view_mode_detail"),
        "execution_mode_detail": snap.get("execution_mode_detail"),
        "data_lake_summary": snap.get("data_lake_summary"),
        "modes_metrics": snap.get("modes_metrics"),
        "evrim_meta_learning": snap.get("evrim_meta_learning"),
        "modes_data_flow": snap.get("modes_data_flow"),
        "sentinel_dashboard": snap.get("sentinel_dashboard"),
    }
    _heavy_snap_cache_ts = time.time()


def _apply_heavy_snap_cache(snap: dict[str, Any]) -> None:
    if not _heavy_snap_cache:
        return
    c = _heavy_snap_cache
    elite = snap.setdefault("elite", {})
    for key in (
        "evrim_adaptive",
        "deleted_archives",
        "mode_archives",
    ):
        if key in c:
            elite[key] = c[key]
    for key in (
        "market_intelligence",
        "view_mode_detail",
        "execution_mode_detail",
        "data_lake_summary",
        "modes_metrics",
        "evrim_meta_learning",
        "modes_data_flow",
        "sentinel_dashboard",
    ):
        if key in c:
            snap[key] = c[key]


def _build_live_status_strip() -> dict[str, Any]:
    """Panel üst şeridi — canlı pozisyon, fiyat beslemesi, mod dağılımı."""
    exec_mid = active_execution_mode()
    prof = mode_catalog().get(exec_mid) or {}
    live_orders = LIVE_ORDERS and not client.paper
    exch_n = len(_positions_cache) if live_orders and _positions_cache else len(positions)
    modes_open: dict[str, int] = {}
    try:
        modes_open = parallel_engine.open_counts_by_mode()
    except Exception:
        pass
    if live_orders and is_live_binance_motor(exec_mid):
        modes_open[exec_mid] = exch_n

    ff_ok = False
    ff_lag: int | None = None
    ff_coins = 0
    try:
        from binance_futures_trader.fast_price_ws import fast_feed_status

        ffs = fast_feed_status()
        ff_ok = bool(ffs.get("connected"))
        ff_lag = ffs.get("lag_ms")
        ff_coins = int(ffs.get("coins") or 0)
    except Exception:
        pass

    ws_health = "disconnected"
    ws_source = "none"
    ws_lag: int | None = None
    ws_coins = 0
    try:
        from binance_futures_trader.mark_ws import feed_status as mfs

        ms = mfs()
        ws_health = str(ms.get("health") or "disconnected")
        ws_source = str(ms.get("source") or "none")
        ws_lag = ms.get("lag_ms")
        ws_coins = int(ms.get("coins") or 0)
    except Exception:
        pass

    mp = {}
    try:
        from elite_trader.evrim_motor_diag import build_motor_diag

        mp = build_motor_diag(
            execution_mode=exec_mid,
            reject_stats=_motor_reject_stats,
            queue_len=len(motor_signals),
            open_count=exch_n if live_orders else len(positions),
            max_open=execution_max_open(),
            last_order_ago_sec=round(time.time() - _last_demo_order_ts, 1)
            if _last_demo_order_ts > 0
            else None,
            queue_added=_motor_queue_added,
            orders_opened=_motor_orders_opened,
        )
    except Exception:
        pass

    unreal = sum(float(p.get("unrealized_pnl") or 0) for p in positions)
    if live_orders and _positions_cache:
        unreal = sum(float(p.get("unrealized_pnl") or 0) for p in _positions_cache)

    parallel_routing: dict[str, Any] = {}
    try:
        from elite_trader.order_gate import get_routing_status

        parallel_routing = get_routing_status(exec_mid)
    except Exception:
        pass

    return {
        "execution_mode": exec_mid,
        "execution_label": prof.get("short_label") or prof.get("label") or exec_mid,
        "live_orders": live_orders,
        "live_open": exch_n if live_orders else len(positions),
        "live_max_open": execution_max_open(),
        "motor_queue": len(motor_signals),
        "live_unrealized_usd": round(unreal, 2),
        "open_positions_source": "binance" if live_orders and _positions_cache else "local",
        "modes_open": modes_open,
        "parallel_routing": parallel_routing,
        "price_feed": {
            "mark_health": ws_health,
            "mark_source": ws_source,
            "mark_lag_ms": ws_lag,
            "mark_coins": ws_coins,
            "bookticker_ok": ff_ok,
            "bookticker_lag_ms": ff_lag,
            "bookticker_coins": ff_coins,
            "position_tick_ms": round(last_position_price_ms, 1),
            "position_tick_iv_ms": round(_position_check_interval() * 1000, 0),
        },
        "scan": {
            "watchlist_total": len(watchlist),
            "tradable_core": len(tradable_symbols),
            "symbols_with_ticks": len(price_history),
            "tick_ms": round(last_tick_ms, 1),
            "motor_ms": round(last_scan_ms, 1),
            "tick_iv_ms": round(_ui_tick_interval_sec() * 1000, 0),
            "motor_iv_ms": round(_effective_motor_scan_interval_sec() * 1000, 0),
            "confirmed_signals": len(motor_signals),
        },
        "motor_pipeline": mp,
        "api_ok": _api_healthy(),
        "api_paper": client.paper,
    }


def _clone_snapshot_for_live_refresh(base: dict[str, Any]) -> dict[str, Any]:
    """Canlı poll — önbelleği bozmadan pozisyon satırlarını kopyala."""
    snap = {**base}
    pos = base.get("positions") or {}
    opens: list[dict[str, Any]] = []
    for raw in pos.get("open") or []:
        row = dict(raw)
        if row.get("exchange_display"):
            row["exchange_display"] = dict(row["exchange_display"])
        opens.append(row)
    snap["positions"] = {
        "open": opens,
        "closed": list(pos.get("closed") or []),
    }
    snap["summary"] = dict(base.get("summary") or {})
    return snap


def _refresh_binance_snapshot_positions(
    snap: dict[str, Any],
    *,
    light: bool = False,
) -> None:
    """Panel/WS — açık pozisyon alanları yalnızca REST positionRisk önbelleği."""
    if not (LIVE_ORDERS and not client.paper):
        return
    exch_positions = list(_positions_cache or [])
    exec_mid = active_execution_mode()
    from elite_trader.exchange_open_display import build_open_positions_for_ui

    open_ui = build_open_positions_for_ui(
        positions, exch_positions, client, allow_chart_fetch=False, enrich_fill=False
    )
    if not _panel_api_only_mode():
        open_ui = _overlay_ws_marks_on_binance_open_ui(open_ui)
    snap["exchange_positions"] = exch_positions
    snap["open_positions_source"] = "binance"
    snap["display_source"] = "binance"
    snap["live_only"] = live_only_execution()
    pos_block = dict(snap.get("positions") or {})
    pos_block["open"] = open_ui
    if not light:
        pos_block["closed"] = _closed_positions_for_ui()[-200:]
    elif "closed" not in pos_block:
        pos_block["closed"] = list((snap.get("positions") or {}).get("closed") or [])
    snap["positions"] = pos_block
    snap["ts"] = datetime.utcnow().isoformat() + "Z"
    summary = dict(snap.get("summary") or {})
    tu = sum(float(p.get("unrealized_pnl") or 0) for p in open_ui)
    summary["unrealized_pnl"] = tu
    summary["open_trades"] = len(open_ui)
    closed_ui = pos_block.get("closed") or []
    if not light:
        closed_ui = _closed_positions_for_ui()[-200:]
        pos_block["closed"] = closed_ui
        summary.update(_session_pnl_summary_fields(closed_ui))
    elif closed_ui:
        summary.update(_session_pnl_summary_fields(closed_ui))
    if _wallet_cache:
        summary["current_capital"] = float(
            _wallet_cache.get("total_margin_balance") or summary.get("current_capital") or 0
        )
        summary["available_capital"] = float(
            _wallet_cache.get("available_balance") or summary.get("available_capital") or 0
        )
        summary["exchange_unrealized_pnl"] = float(
            _wallet_cache.get("total_unrealized_pnl") or tu
        )
    snap["summary"] = summary
    if _wallet_cache:
        snap["exchange_wallet"] = _wallet_cache
        snap["exchange_balance"] = _wallet_cache.get("available_balance")
    if light:
        snap["strip_open_positions"] = open_ui
        return
    try:
        _pu_books = parallel_engine.all_universe_books()
    except Exception:
        _pu_books = {}
    try:
        snap["strip_open_positions"] = _build_strip_open_positions(
            _pu_books,
            exec_mid=exec_mid,
            exchange_open_ui=open_ui,
        )
    except Exception:
        snap["strip_open_positions"] = list(open_ui)


def _build_ws_snapshot_light() -> dict[str, Any]:
    """WS yayını — önceki snapshot + REST pozisyon yenileme (get_snapshot atlanır)."""
    base: dict[str, Any] = dict(_last_ws_snapshot) if _last_ws_snapshot else {}
    if not base:
        return _build_ws_snapshot()
    _refresh_binance_snapshot_positions(base, light=True)
    try:
        base["watchlist_prices"] = _watchlist_prices_subset()
    except Exception:
        pass
    iv_ms = round(_position_check_interval() * 1000, 0)
    base["api_latency_ms"] = round(last_position_price_ms or last_avg_latency_ms, 1)
    base["position_price_scan_ms"] = round(last_position_price_ms, 1)
    base["watchlist_scan_ms"] = round(last_tick_ms or last_scan_ms, 1)
    base["position_check_sec"] = _position_check_interval()
    base["perf_live"] = {
        "tick_ms": round(last_tick_ms, 1),
        "scan_ms": round(last_scan_ms, 1),
        "motor_eval_ms": round(last_scan_ms, 1),
        "position_price_ms": round(last_position_price_ms, 1),
        "position_price_interval_ms": iv_ms,
        "ui_tick_interval_ms": round(_ui_tick_interval_sec() * 1000, 0),
        "motor_scan_interval_ms": round(_effective_motor_scan_interval_sec() * 1000, 0),
        "panel_broadcast_ms": round(_panel_refresh_sec() * 1000, 0),
    }
    _apply_heavy_snap_cache(base)
    return base


def _build_ws_snapshot() -> dict[str, Any]:
    """Panel WS snapshot — hafif get_snapshot (ağır bloklar önbellekten)."""
    snap = get_snapshot(light=True)
    iv_ms = round(_position_check_interval() * 1000, 0)
    snap["api_latency_ms"] = round(last_position_price_ms or last_avg_latency_ms, 1)
    snap["position_price_scan_ms"] = round(last_position_price_ms, 1)
    snap["watchlist_scan_ms"] = round(last_tick_ms or last_scan_ms, 1)
    snap["position_check_sec"] = _position_check_interval()
    snap["perf_live"] = {
        "tick_ms": round(last_tick_ms, 1),
        "scan_ms": round(last_scan_ms, 1),
        "motor_eval_ms": round(last_scan_ms, 1),
        "position_price_ms": round(last_position_price_ms, 1),
        "position_price_interval_ms": iv_ms,
        "ui_tick_interval_ms": round(_ui_tick_interval_sec() * 1000, 0),
        "motor_scan_interval_ms": round(_effective_motor_scan_interval_sec() * 1000, 0),
        "panel_broadcast_ms": round(_panel_refresh_sec() * 1000, 0),
    }
    _store_heavy_snap_cache(snap)
    return snap


def _build_api_only_panel_snapshot(*, force_positions: bool = False) -> dict[str, Any]:
    """Panel — yalnızca Binance REST; ek gecikme/overlay/get_snapshot yok."""
    mega_panel = _panel_snap_from_mega_live(light=not force_positions)
    if mega_panel is not None:
        return mega_panel

    exec_mid = active_execution_mode()
    view = active_view_mode()
    poll_iv = _effective_position_poll_interval_sec()
    cache_age = (time.time() - _exchange_cache_ts) if _exchange_cache_ts else 9999.0
    if force_positions:
        _refresh_positions_cache_only(
            force=True,
            timeout_sec=_effective_position_timeout_sec(critical=True),
            min_interval_sec=0.0,
        )
    wallet_age = (time.time() - _wallet_cache_ts) if _wallet_cache_ts else 9999.0
    if wallet_age > _exchange_wallet_refresh_sec() * 0.9:
        refresh_exchange_cache(force=False, min_interval_sec=_exchange_wallet_refresh_sec())

    from elite_trader.exchange_open_display import build_open_positions_for_ui

    open_ui = build_open_positions_for_ui(
        positions,
        list(_positions_cache or []),
        client,
        allow_chart_fetch=False,
        enrich_fill=False,
    )
    tu = sum(float(p.get("unrealized_pnl") or 0) for p in open_ui)
    closed_ui = _closed_positions_for_ui()[-200:]
    session_fields = _session_pnl_summary_fields(closed_ui)
    ew = _wallet_cache if LIVE_ORDERS and not client.paper and _wallet_cache else None
    margin = float(ew.get("total_margin_balance") or 0) if ew else get_current_capital()
    avail = float(ew.get("available_balance") or 0) if ew else margin
    start_cap = float(session_fields.get("starting_capital") or _motor_session_start())
    if ew and start_cap > 0:
        session_fields["session_pnl"] = round(margin - start_cap, 2)
        session_fields["session_pnl_pct"] = round((margin - start_cap) / start_cap * 100.0, 2)
        session_fields["total_pnl"] = session_fields["session_pnl"]
        session_fields["total_pnl_pct"] = session_fields["session_pnl_pct"]
    elif start_cap > 0:
        session_fields.setdefault("session_pnl", round(margin - start_cap, 2))
    cache_ms = int((time.time() - _exchange_cache_ts) * 1000) if _exchange_cache_ts else None
    mp = _build_motor_pipeline_diag(exec_mid, open_count=len(open_ui))
    return {
        "ts": datetime.utcnow().isoformat() + "Z",
        "panel_api_only": True,
        "live_only": live_only_execution(),
        "display_source": "binance",
        "open_positions_source": "binance",
        "view_mode": view,
        "execution_mode": exec_mid,
        "execution_label": (mode_catalog().get(exec_mid) or {}).get("label", exec_mid),
        "view_label": "Binance API",
        "mode": "DEMO_LIVE" if LIVE_ORDERS and not client.paper else "PAPER",
        "live_orders": LIVE_ORDERS and not client.paper,
        "api_connected": LIVE_ORDERS and not client.paper and not client._auth_error,
        "exchange_wallet": ew,
        "exchange_balance": ew.get("available_balance") if ew else None,
        "summary": {
            "open_trades": len(open_ui),
            "unrealized_pnl": round(tu, 4),
            "current_capital": round(margin, 2),
            "available_capital": round(avail, 2),
            "exchange_margin_balance": round(margin, 2),
            "exchange_available_balance": round(avail, 2),
            "exchange_unrealized_pnl": round(tu, 4),
            **session_fields,
        },
        "positions": {"open": open_ui, "closed": closed_ui},
        "strip_open_positions": open_ui,
        "strip_recent_closed": closed_ui[:12],
        "signals": [],
        "approaching_signals": [],
        "approaching_reversal_signals": [],
        "scanner_status": {
            "exchange_poll_ms": round(_exchange_position_poll_ms, 1),
            "exchange_cache_age_ms": cache_ms,
            "open_position_count": len(open_ui),
        },
        "perf_live": {
            "panel_api_only": True,
            "position_price_interval_ms": round(poll_iv * 1000, 0),
            "exchange_poll_ms": round(_exchange_position_poll_ms, 1),
        },
        "display_note": "API-only panel · Binance positionRisk",
        "elite": {"motor_pipeline": mp},
    }


def _snapshot_refresh_loop() -> None:
    """Arka planda snapshot üret — panel WS asla bloklanmaz."""
    global _last_ws_snapshot, _last_snapshot_build_ms, _last_snapshot_at, _ticker_prices_cache
    cycle = 0
    full_every = max(12, int(30.0 / max(0.12, _panel_refresh_sec())))
    while not _snapshot_refresh_stop.is_set():
        t0 = time.perf_counter()
        try:
            if _panel_uses_exchange_snapshot():
                # positionRisk yalnızca exchange-poll worker — snapshot REST ile yarışmasın
                _last_ws_snapshot = _build_api_only_panel_snapshot(force_positions=False)
            elif _last_ws_snapshot:
                _last_ws_snapshot = _build_ws_snapshot_light()
            elif not _heavy_snap_cache_fresh() or cycle % full_every == 0:
                _last_ws_snapshot = _build_ws_snapshot()
            else:
                _last_ws_snapshot = _build_ws_snapshot_light()
            if not _panel_api_only_mode():
                _ticker_prices_cache = _watchlist_prices_subset()
        except Exception:
            pass
        cycle += 1
        _last_snapshot_build_ms = (time.perf_counter() - t0) * 1000.0
        _last_snapshot_at = time.time()
        elapsed = time.perf_counter() - t0
        _snapshot_refresh_stop.wait(max(0.04, _panel_refresh_sec() - elapsed))


def _start_snapshot_refresh() -> None:
    global _snapshot_refresh_thread
    if _snapshot_refresh_thread and _snapshot_refresh_thread.is_alive():
        return
    _snapshot_refresh_stop.clear()
    _snapshot_refresh_thread = threading.Thread(
        target=_snapshot_refresh_loop, name="snapshot-refresh", daemon=True
    )
    _snapshot_refresh_thread.start()


def _stop_snapshot_refresh() -> None:
    _snapshot_refresh_stop.set()
    if _snapshot_refresh_thread and _snapshot_refresh_thread.is_alive():
        _snapshot_refresh_thread.join(timeout=2.0)


async def _panel_ws_broadcast_loop() -> None:
    """Panel WebSocket — sürekli yayın (~300ms)."""
    while True:
        try:
            snap = _last_ws_snapshot
            if snap and ws_manager.clients:
                await ws_manager.broadcast(snap)
        except Exception:
            pass
        await asyncio.sleep(_panel_refresh_sec())


def update_positions_exits() -> None:
    """Borsa senkron yedek — positionRisk poll worker + position-price thread."""
    coins = _all_open_position_coins(refresh_paper=True)
    bulk = _prices_for_coins(
        coins, max_age_ms=_position_price_max_age_ms()
    ) if coins else {}

    if bulk and not live_only_execution():
        try:
            parallel_engine.tick_prices(bulk, check_exits=True)
        except Exception:
            pass

    if not positions:
        return

    if bulk:
        _check_live_position_exits(bulk)


def update_positions() -> float:
    """Geriye uyumluluk — hızlı fiyat + çıkış kontrolü."""
    ms = update_open_position_prices_fast()
    update_positions_exits()
    return ms


def _enrich_paper_positions_for_ui(
    open_list: list[dict[str, Any]], mode_id: str
) -> list[dict[str, Any]]:
    """Paper kitap satırlarını panel tabloları/kartlar için tam alan setine çevir."""
    out: list[dict[str, Any]] = []
    for raw in open_list:
        p = dict(raw)
        p["data_source"] = "binance" if p.get("on_exchange") else "parallel"
        p["panel_mode"] = p.get("panel_mode") or p.get("universe_id") or mode_id
        ep = float(p.get("entry_price") or 0)
        cp = float(p.get("current_price") or ep)
        stake = max(float(p.get("stake_usd") or 0), 0.01)
        size = float(p.get("size") or 0)
        side = str(p.get("side") or "LONG")
        p["entry_price"] = ep
        p["current_price"] = cp
        if not p.get("tp_target") or not p.get("sl_target"):
            tp_usd, sl_usd = stake_targets(stake, mode_id)
            if size > 0 and ep > 0:
                if side == "LONG":
                    p["tp_target"] = ep + tp_usd / size
                    p["sl_target"] = ep - sl_usd / size
                else:
                    p["tp_target"] = ep - tp_usd / size
                    p["sl_target"] = ep + sl_usd / size
            else:
                p["tp_target"] = ep
                p["sl_target"] = ep
            p.setdefault("tp_target_usd", tp_usd)
            p.setdefault("sl_target_usd", sl_usd)
        unreal = float(p.get("unrealized_pnl") or 0)
        p["unrealized_pnl"] = round(unreal, 4)
        p["pnl_pct"] = round(unreal / stake * 100, 4) if stake > 0 else 0.0
        p.setdefault("leverage", 5)
        p.setdefault("entry_fee", 0.0)
        p.setdefault("position_value", size * cp if size and cp else stake)
        p.setdefault("signal_strength", p.get("signal_strength") or "Medium")
        p.setdefault("signal_source", p.get("signal_source") or ("MEGA-LIVE" if mode_id == "mega" and p.get("on_exchange") else f"Paper-{mode_id}"))
        p.setdefault("price_history", p.get("price_history") or [ep, cp])
        p.setdefault("time_history", p.get("time_history") or [p.get("opened_at_iso") or ""])
        out.append(p)
    return out


def _action_bucket(action: str | None) -> str:
    return action if action else "BEKLE"


def _build_strip_open_positions(
    parallel_books: dict[str, dict[str, Any]],
    *,
    exec_mid: str,
    exchange_open_ui: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Ticker altı şerit: canlı Binance → yalnızca borsa; aksi halde mod kitapları."""
    live_binance = exchange_open_ui is not None
    if live_binance:
        modes = mode_catalog()
        m = modes.get(exec_mid) or {}
        label = str(m.get("short_label") or exec_mid)
        out: list[dict[str, Any]] = []
        for raw in list(exchange_open_ui or []):
            p = dict(raw)
            p["data_source"] = "binance"
            p["strip_mode_labels"] = label + " ★"
            p["strip_is_live"] = True
            p["strip_primary_mode"] = exec_mid
            unreal = float(p.get("unrealized_pnl") or 0)
            stake = max(float(p.get("stake_usd") or 1), 0.01)
            age = position_age_seconds(p)
            lev = int(p.get("leverage") or 5)
            p["strip_action"] = _action_bucket(
                shadow_action(
                    unrealized_usd=unreal,
                    stake_usd=stake,
                    mode_id=exec_mid,
                    age_sec=age,
                    leverage=lev,
                )
            )
            out.append(p)
        return sorted(out, key=lambda x: str(x.get("symbol") or ""))

    modes = mode_catalog()
    merged: dict[str, dict[str, Any]] = {}
    mode_tags: dict[str, list[tuple[str, bool, str]]] = {}
    live_binance = exchange_open_ui is not None

    for mid in mode_order():
        if mid not in modes:
            continue
        m = modes[mid]
        is_exec = mid == exec_mid and live_binance
        book = parallel_books.get(mid) or {}
        if is_exec:
            mode_open = list(exchange_open_ui or [])
        else:
            mode_open = list(book.get("open") or [])

        label = str(m.get("short_label") or mid)
        for raw in mode_open:
            sym = str(raw.get("symbol") or "").upper()
            if not sym:
                continue
            side = str(raw.get("side") or "LONG").upper()
            key = f"{sym}:{side}"
            tags = mode_tags.setdefault(key, [])
            if not any(t[0] == label for t in tags):
                tags.append((label, bool(is_exec), mid))

            if is_exec:
                row = dict(raw)
                row["data_source"] = "binance"
            else:
                row = _enrich_paper_positions_for_ui([dict(raw)], mid)[0]

            cur = merged.get(key)
            if cur is None:
                merged[key] = row
            elif is_exec:
                merged[key] = row
            elif cur.get("data_source") != "binance":
                if float(row.get("stake_usd") or 0) >= float(cur.get("stake_usd") or 0):
                    merged[key] = row

    out: list[dict[str, Any]] = []
    for key, row in merged.items():
        p = dict(row)
        tags = mode_tags.get(key) or []
        labels: list[str] = []
        primary_mid = exec_mid if any(t[2] == exec_mid for t in tags) else (tags[0][2] if tags else exec_mid)
        has_live = False
        for lbl, is_live, _mid in tags:
            labels.append(lbl + (" ★" if is_live else ""))
            has_live = has_live or is_live
        p["strip_mode_labels"] = " · ".join(labels)
        p["strip_is_live"] = has_live
        p["strip_primary_mode"] = primary_mid
        unreal = float(p.get("unrealized_pnl") or 0)
        stake = max(float(p.get("stake_usd") or 1), 0.01)
        age = position_age_seconds(p)
        lev = int(p.get("leverage") or 5)
        p["strip_action"] = _action_bucket(
            shadow_action(
                unrealized_usd=unreal,
                stake_usd=stake,
                mode_id=primary_mid,
                age_sec=age,
                leverage=lev,
            )
        )
        out.append(p)

    out = _apply_live_mark_to_open_rows(out)
    return sorted(out, key=lambda x: str(x.get("symbol") or ""))


def _parse_event_ts(v: Any) -> float:
    """Unix epoch veya 'YYYY-MM-DD HH:MM:SS' / ISO zaman damgasını saniyeye çevir."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        fv = float(v)
        return fv if fv > 1e9 else 0.0
    s = str(v).strip()
    if not s:
        return 0.0
    try:
        fv = float(s)
        if fv > 1e9:
            return fv
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1)).timestamp()
    except Exception:
        pass
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _strip_recent_closed(
    parallel_books: dict[str, dict[str, Any]], *, max_n: int = 40
) -> list[dict[str, Any]]:
    """Şerit kapanış flash'ı için son kapanan işlemler."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()

    def _add(row: dict[str, Any]) -> None:
        key = (row.get("id"), row.get("symbol"), row.get("exit_time"))
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    if LIVE_ORDERS and not client.paper:
        exec_mid = active_execution_mode()
        for c in _closed_positions_for_ui()[:max_n]:
            row = dict(c)
            row["panel_mode"] = row.get("panel_mode") or row.get("execution_mode_at_close") or exec_mid
            _add(row)
    for mid, book in parallel_books.items():
        for c in list(book.get("closed") or [])[-max_n:]:
            row = dict(c)
            row["panel_mode"] = row.get("panel_mode") or row.get("universe_id") or mid
            _add(row)

    def _exit_ts(r: dict[str, Any]) -> float:
        for key in ("exit_time", "closed_at_iso", "exit_time_str"):
            ts = _parse_event_ts(r.get(key))
            if ts > 0:
                return ts
        return 0.0

    rows.sort(key=_exit_ts, reverse=True)
    return rows[:max_n]


def _motor_reject(reason: str) -> None:
    key = str(reason or "unknown")[:48]
    _motor_reject_stats[key] = _motor_reject_stats.get(key, 0) + 1


def _maybe_log_motor_pipeline() -> None:
    global _last_motor_diag_log_ts
    now = time.time()
    if now - _last_motor_diag_log_ts < 90.0:
        return
    _last_motor_diag_log_ts = now
    exec_mid = active_execution_mode()
    top = sorted(_motor_reject_stats.items(), key=lambda x: -x[1])[:8]
    top_s = ", ".join(f"{k}:{v}" for k, v in top) if top else "—"
    print(
        f"  📊 Motor [{exec_mid}] kuyruk={len(motor_signals)} "
        f"açık={len(positions)}/{execution_max_open()} red:{top_s}"
    )
    try:
        paper_sum = parallel_engine.paper_reject_summary()
        if paper_sum:
            parts = []
            for mid in ("berserk", "hunter", "chop_master", "sentinel", "evrim"):
                row = paper_sum.get(mid)
                if not row or not row.get("total"):
                    continue
                parts.append(f"{mid}:{row.get('top_txt') or row.get('total')}")
            if parts:
                print(
                    f"  📋 Paper red (oturum) core={len(tradable_symbols)} "
                    f"scan={len(watchlist)} · " + " · ".join(parts[:4])
                )
    except Exception:
        pass


def _append_motor_signal(candidate: dict[str, Any]) -> None:
    """Seçili motor profiline uyan adayları canlı emir kuyruğuna ekle."""
    global motor_signals, _motor_queue_added
    sym = candidate.get("symbol")
    direction = candidate.get("type")
    if any(
        s.get("symbol") == sym and s.get("type") == direction
        for s in motor_signals[-12:]
    ):
        return
    motor_signals.append(dict(candidate))
    _motor_queue_added += 1
    if len(motor_signals) > 120:
        motor_signals.pop(0)


def _signals_for_live_execution() -> list[dict]:
    """Seçili motor — live emir kuyruğu (berserk2: motor_signals + signals yedek)."""
    exec_mid = active_execution_mode()
    if exec_mid == "berserk2":
        if motor_signals:
            return motor_signals
        return list(signals[-40:])
    return motor_signals


def _on_execution_motor_changed(old: str, new: str) -> None:
    """Motor değişince borsa kapat, bakiye sıfırla, profilden devam (Ana Hat DB korunur)."""
    global motor_signals, positions, closed_positions, position_id_counter, signals
    from elite_trader.motor_session import restart_motor_session

    out = restart_motor_session(
        old,
        new,
        positions=positions,
        closed_positions=closed_positions,
        motor_signals=motor_signals,
        signals=signals,
        close_exchange_fn=(
            close_binance_exchange_positions
            if LIVE_ORDERS and not client.paper
            else None
        ),
        sync_exchange_fn=(
            (lambda: _sync_positions_from_exchange())
            if LIVE_ORDERS and not client.paper
            else None
        ),
    )
    all_ids = [
        int(p["id"])
        for p in closed_positions + positions
        if p.get("id") is not None
    ]
    if all_ids:
        position_id_counter = max(position_id_counter, max(all_ids) + 1)
    print(
        f"  ⚙ Motor: {old} → {new} | oturum ${out.get('session_start', 0):.0f} "
        f"({'Binance' if LIVE_ORDERS and not client.paper else 'paper'}) "
        f"{out.get('exchange', {}).get('message', '')}"
    )


def _record_price_tick(symbol: str, price: float) -> None:
    """Hızlı fiyat kaydı — mod değerlendirmesi yok."""
    global _price_cache_ts
    if price <= 0:
        return
    coin = str(symbol).upper().replace("USDT", "")
    now = time.time()
    _last_tick_price_at[coin] = now
    with _price_cache_lock:
        _price_cache[coin] = float(price)
        _price_cache_ts = now
    try:
        from binance_futures_trader.mark_ws import ingest_rest_prices

        ingest_rest_prices({coin: float(price)})
    except Exception:
        pass
    from elite_trader.market_intelligence_hub import get_hub

    get_hub().record_tick(symbol, price, price_history)


def _momentum_score(symbol: str, price: float) -> float:
    """Son 20 bar momentum büyüklüğü (%)."""
    hist = price_history.get(symbol) or []
    if len(hist) <= 20:
        return 0.0
    old = float(hist[-20]["price"])
    if old <= 0:
        return 0.0
    return abs((float(price) - old) / old * 100.0)


def _short_momentum_score(symbol: str, price: float) -> float:
    """UI approaching ile aynı kısa pencere momentum (%)."""
    lookback = max(2, min(10, _env_int("UI_APPROACHING_LOOKBACK", 3)))
    min_pct = _env_float("ENTRY_SHORT_MOMENTUM_PCT", 0.025)
    hist = price_history.get(symbol) or []
    if len(hist) <= lookback:
        return 0.0
    old = float(hist[-lookback]["price"])
    if old <= 0:
        return 0.0
    ch = abs((float(price) - old) / old * 100.0)
    return ch if ch >= min_pct else 0.0


def _berserk2_scan_active() -> bool:
    """BERSERK2 top10 hızlı tarama — berserk2 veya MEGA-only (9006) process."""
    try:
        if active_execution_mode() == "berserk2":
            return True
        if active_view_mode() == "berserk2":
            return True
        from elite_trader.mega_live import mega_motor_active
        from elite_trader.mode_registry import enabled_mode_ids

        if mega_motor_active() and "mega" in enabled_mode_ids():
            if active_execution_mode() == "mega" or active_view_mode() == "mega":
                return True
    except Exception:
        pass
    return False


_last_berserk2_scan_at: float = 0.0


def _berserk2_momentum_threshold_for_rank(rank: int) -> float:
    """Top-N sırası — en hareketlilerde daha düşük giriş eşiği (TP scalp)."""
    if rank < 5:
        return _env_float("BERSERK2_MOMENTUM_TIER1_PCT", 0.003)
    if rank < 12:
        return _env_float("BERSERK2_MOMENTUM_TIER2_PCT", 0.005)
    return _env_float("BERSERK2_MOMENTUM_TIER3_PCT", 0.008)


def _evaluate_berserk2_candidate_fast(
    symbol: str, price: float, *, rank: int = 9
) -> None:
    """BERSERK2 — hafif aday; paper kitap veya demo canlı emir kuyruğu."""
    from elite_trader.berserk2_flash_reversal import build_flash_reversal_candidate
    from elite_trader.mode_profiles import get_profile
    from elite_trader.panel_strategy import is_live_binance_motor
    from elite_trader.signal_paths import append_live_signal, build_berserk2_momentum_candidate

    prof = get_profile("berserk2") or {}
    rev = build_flash_reversal_candidate(
        symbol, price, price_history, prof, rank=rank
    )
    if rev and os.getenv("BERSERK2_FLASH_REVERSAL_ENABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        _emit_berserk2_candidate(rev)
        return

    min_ch = _berserk2_momentum_threshold_for_rank(rank)
    cand = build_berserk2_momentum_candidate(
        symbol, price, price_history, min_abs_change_pct=min_ch
    )
    if not cand:
        return
    cand["berserk2_mover_rank"] = rank
    cand["target_mode"] = "berserk2"
    _emit_berserk2_candidate(cand)


def _mega_vol_scan_pass(
    prices: dict[str, float],
    *,
    deadline: float,
) -> int:
    """MEGA — hot/warm volatil coinlerde düşük eşikli ikinci tarama turu."""
    try:
        from elite_trader.mega_live import mega_motor_active, process_scan_candidate
        from elite_trader.mega_volatility import (
            build_vol_scan_candidate,
            enabled as mega_vol_enabled,
            snapshot as vol_snapshot,
        )
        from elite_trader.panel_strategy import is_live_binance_motor

        if not mega_motor_active() or not mega_vol_enabled():
            return 0
        vol = vol_snapshot()
        tier_ok = {"hot", "warm"}
        if _env_int("MEGA_VOL_COLD_N", 0) > 0:
            tier_ok.add("cold")
        symbols = [
            str(c.get("symbol") or "")
            for c in (vol.get("coins") or [])
            if c.get("tier") in tier_ok
        ]
        if os.getenv("MEGA_SCAN_UNIVERSE_WATCHLIST", "0").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            from elite_trader.mega_volatility import scan_symbol_list

            symbols = scan_symbol_list(prices=prices)
        if not symbols:
            return 0
        min_pct = _env_float("MEGA_VOL_SCAN_MIN_MOMENTUM_PCT", 0.002)
        n = 0
        for sym in symbols:
            if time.perf_counter() >= deadline:
                break
            fp = float(prices.get(sym) or prices.get(sym.replace("USDT", "")) or 0)
            if fp <= 0:
                continue
            cand = build_vol_scan_candidate(
                sym, fp, price_history, min_abs_change_pct=min_pct
            )
            if not cand:
                continue
            try:
                process_scan_candidate(cand, fp)
                n += 1
            except Exception:
                pass
        return n
    except Exception:
        return 0


def _emit_berserk2_candidate(cand: dict[str, Any]) -> None:
    from elite_trader.mega_live import mega_motor_active
    from elite_trader.panel_strategy import is_live_binance_motor
    from elite_trader.signal_paths import append_live_signal

    sym = cand.get("symbol")
    direction = cand.get("type")
    if not any(
        s.get("symbol") == sym and s.get("type") == direction for s in signals[-12:]
    ):
        append_live_signal(cand, signals)
    px = float(cand.get("price") or 0)
    if is_live_binance_motor("berserk2"):
        _append_motor_signal(cand)
        if (
            not mega_motor_active()
            and not live_only_execution()
            and px > 0
        ):
            try:
                parallel_engine.enqueue_market_signal(cand, px)
            except Exception:
                pass
    if mega_motor_active() and px > 0:
        try:
            from elite_trader.mega_live import process_scan_candidate

            process_scan_candidate(cand, px)
        except Exception:
            pass
    if is_live_binance_motor("berserk2") or mega_motor_active():
        return
    try:
        parallel_engine.on_market_signal_for_mode("berserk2", cand, px)
    except Exception:
        pass


def scan_berserk2_top10_signals() -> None:
    """Top10 — bütçeli hızlı tur (motor thread'den ayrı)."""
    global _last_berserk2_scan_at, last_scan_ms, _last_motor_at
    global _last_motor_eval_n, _last_motor_candidates_n
    if not _berserk2_scan_active():
        return
    min_iv = max(0.18, _env_float("BERSERK2_SCAN_INTERVAL_SEC", 0.28))
    now = time.time()
    if now - _last_berserk2_scan_at < min_iv:
        return
    _last_berserk2_scan_at = now
    t0 = time.perf_counter()
    budget_sec = max(0.08, min(0.50, _env_float("BERSERK2_SCAN_BUDGET_MS", 320) / 1000.0))
    deadline = time.perf_counter() + budget_sec
    try:
        from elite_trader.berserk2_btc_context import schedule_btc_refresh
        from elite_trader.berserk2_movers import iter_tracked_symbols
        from elite_trader.mode_profiles import get_profile

        prof = get_profile("berserk2") or {}
        if not prof.get("berserk2_fast_scan_enabled", True):
            return
        schedule_btc_refresh(client)
        prices = _bulk_prices_cached_fast()
        if not prices:
            return
        from elite_trader.mega_live import mega_motor_active

        if mega_motor_active() and os.getenv("MEGA_SCAN_UNIVERSE", "").strip().lower() in (
            "watchlist",
            "full",
        ):
            from elite_trader.mega_volatility import scan_symbol_list

            symbols = scan_symbol_list(prices=prices)
        else:
            symbols = list(iter_tracked_symbols())
        _last_motor_candidates_n = len(symbols)
        eval_n = 0
        mega_watchlist = mega_motor_active() and os.getenv(
            "MEGA_SCAN_UNIVERSE", ""
        ).strip().lower() in ("watchlist", "full")
        for rank, sym in enumerate(symbols):
            if time.perf_counter() >= deadline:
                break
            fp = float(prices.get(sym) or prices.get(sym.replace("USDT", "")) or 0)
            if fp <= 0:
                continue
            if mega_watchlist:
                try:
                    from elite_trader.mega_volatility import (
                        is_micro_price,
                        micro_price_scan_eligible,
                        row_for,
                    )

                    if is_micro_price(fp):
                        vol_row = row_for(sym) or {}
                        ch = _short_momentum_pct(sym, fp, min_pct=0.0)
                        if not micro_price_scan_eligible(
                            fp,
                            change_pct=ch,
                            vol_score=float(vol_row.get("vol_score") or 0),
                            vol_tier=str(vol_row.get("tier") or ""),
                        ):
                            continue
                except Exception:
                    pass
            _record_price_tick(sym, fp)
            try:
                _evaluate_berserk2_candidate_fast(sym, fp, rank=rank)
                eval_n += 1
            except Exception:
                pass
        vol_n = _mega_vol_scan_pass(prices, deadline=deadline)
        _last_motor_at = time.time()
        last_scan_ms = (time.perf_counter() - t0) * 1000.0
        _last_motor_eval_n = eval_n + vol_n
    except Exception:
        pass


def _short_momentum_pct(
    symbol: str, price: float, *, min_pct: float | None = None
) -> float:
    lookback = max(2, min(6, _env_int("BERSERK2_MOMENTUM_LOOKBACK", 2)))
    floor = (
        float(min_pct)
        if min_pct is not None
        else _env_float("BERSERK2_MIN_MOMENTUM_PCT", 0.004)
    )
    hist = price_history.get(symbol) or price_history.get(symbol.replace("USDT", "")) or []
    if len(hist) < 2:
        return 0.0
    idx = min(lookback, len(hist) - 1)
    old = float(hist[-1 - idx].get("price") or 0)
    if old <= 0:
        return 0.0
    ch = abs((float(price) - old) / old * 100.0)
    return ch if ch >= floor else 0.0


def _collect_entry_eval_symbols(
    prices: dict[str, float],
    *,
    top_n: int | None = None,
) -> list[tuple[str, float]]:
    """Motor adayları — flex momentum ile hub.build_candidate hizalı."""
    if _berserk2_scan_active():
        try:
            from elite_trader.berserk2_movers import iter_tracked_symbols

            out: list[tuple[str, float]] = []
            for sym in iter_tracked_symbols():
                fp = float(prices.get(sym) or prices.get(sym.replace("USDT", "")) or 0)
                if fp > 0:
                    out.append((sym, fp))
            if out:
                return out
        except Exception:
            pass
    exec_mid = active_execution_mode()
    if exec_mid == "berserk2":
        try:
            from elite_trader.berserk2_movers import get_top10

            top = get_top10()
            if top:
                out: list[tuple[str, float]] = []
                for sym in top:
                    fp = float(prices.get(sym) or prices.get(sym.replace("USDT", "")) or 0)
                    if fp <= 0:
                        coin = sym.replace("USDT", "")
                        fp = float(prices.get(coin) or 0)
                    if fp > 0:
                        out.append((sym, fp))
                if out:
                    return out
        except Exception:
            pass
    universe = set(watchlist) | tradable_symbols
    limit = top_n if top_n is not None else _scan_eval_top_n()
    by_sym: dict[str, tuple[float, float]] = {}

    for key, price in prices.items():
        sym = _normalize_universe_symbol(str(key), universe)
        if not sym:
            continue
        fp = float(price)
        if fp <= 0:
            continue
        sc = _momentum_flex_score(sym, fp)
        if sc <= 0:
            continue
        prev = by_sym.get(sym)
        if not prev or sc > prev[0]:
            by_sym[sym] = (sc, fp)

    ranked = sorted(by_sym.items(), key=lambda x: -x[1][0])
    return [(sym, fp) for sym, (_, fp) in ranked[:limit]]


def _evaluate_signal_candidate(symbol: str, price: float, *, deadline: float | None = None) -> None:
    """Top-N aday — paper önce, ağır live gate tur başına sınırlı."""
    global signals, price_history, motor_signals, _motor_live_gate_left
    from elite_trader.market_intelligence_hub import get_hub

    hub = get_hub()
    candidate = hub.build_candidate(symbol, price, price_history)
    if not candidate:
        return

    sym = candidate.get("symbol")
    direction = candidate.get("type")
    if not any(
        s.get("symbol") == sym and s.get("type") == direction for s in signals[-12:]
    ):
        from elite_trader.signal_paths import append_live_signal

        append_live_signal(candidate, signals)

    px = float(price)
    if not live_only_execution():
        try:
            parallel_engine.enqueue_market_signal(candidate, px)
        except Exception:
            pass

    if deadline is not None and time.time() >= deadline:
        return

    exec_mid = active_execution_mode()
    if (
        LIVE_ORDERS
        and not client.paper
        and exec_mid
        and _motor_live_gate_left > 0
        and abs(float(candidate.get("change") or 0)) >= 0.06
    ):
        _motor_live_gate_left -= 1
        ok_motor, motor_reason = _entry_gate_timed(exec_mid, candidate)
        if ok_motor:
            row = dict(candidate)
            row["target_mode"] = exec_mid
            _append_motor_signal(row)
        elif motor_reason:
            _motor_reject(motor_reason)


def _process_price_tick(symbol: str, price: float) -> None:
    """Tek sembol — kayıt + değerlendirme (parça tarama için)."""
    _record_price_tick(symbol, price)
    _evaluate_signal_candidate(symbol, price)


def _maybe_rollup_data_lake_metrics() -> None:
    global _last_metrics_rollup_ts
    if time.time() - _last_metrics_rollup_ts < 600.0:
        return
    _last_metrics_rollup_ts = time.time()
    try:
        from elite_trader.data_lake.ingest import persist_all_mode_metrics

        persist_all_mode_metrics()
    except Exception:
        pass


def scan_price_ticks_fast() -> None:
    """Tüm evren (527) — Approaching Signals için price_history; motor tarama hızında."""
    global last_tick_ms, _last_tick_at
    from elite_trader.signal_paths import update_price_history

    t0 = time.time()
    prices = _bulk_prices_cached_fast()
    if _berserk2_scan_active():
        try:
            from elite_trader.berserk2_movers import iter_tracked_symbols

            universe = set(iter_tracked_symbols()) | set(watchlist)
        except Exception:
            universe = set(watchlist) | tradable_symbols
    else:
        universe = set(watchlist) | tradable_symbols
    if not prices:
        last_tick_ms = (time.time() - t0) * 1000.0
        _last_tick_at = time.time()
        return

    by_sym: dict[str, float] = {}
    if _berserk2_scan_active():
        for sym in universe:
            coin = sym.replace("USDT", "")
            fp = float(
                prices.get(sym) or prices.get(coin) or prices.get(f"{coin}USDT") or 0
            )
            if fp > 0:
                by_sym[sym] = fp
    else:
        for key, price in prices.items():
            sym = _normalize_universe_symbol(str(key), universe)
            if not sym:
                continue
            fp = float(price)
            if fp <= 0:
                continue
            by_sym[sym] = fp

    for sym in universe:
        fp = by_sym.get(sym)
        if fp is None:
            coin = sym.replace("USDT", "")
            fp = by_sym.get(coin)
        if fp and fp > 0:
            update_price_history(sym, fp, price_history)

    last_tick_ms = (time.time() - t0) * 1000.0
    _last_tick_at = time.time()
    
    # Spread map (bookTicker varsa)
    spread_map: dict[str, float] = {}
    volume_map: dict[str, float] = {}
    try:
        if fast_feed:
            for coin, tick in fast_feed.tickers.items():
                sym = f"{coin}USDT" if not coin.endswith("USDT") else coin
                bid = float(tick.get("b") or 0)
                ask = float(tick.get("a") or 0)
                if bid > 0 and ask > bid:
                    spread_map[sym] = (ask - bid) / bid
        # Volume surge from price history
        for sym, hist in price_history.items():
            if len(hist) >= 5:
                recent_vol = sum(float(h.get("volume", 0)) for h in hist[-2:])
                avg_vol = sum(float(h.get("volume", 0)) for h in hist[-5:-2]) / 3 if len(hist) >= 5 else recent_vol
                if avg_vol > 0:
                    volume_map[sym] = recent_vol / avg_vol
    except Exception:
        pass
    
    try:
        from elite_trader.berserk2_movers import refresh_top_movers

        refresh_top_movers(
            list(universe),
            by_sym,
            price_history,
            min_volume_usdt=_env_float("BERSERK2_MIN_VOLUME_USDT", 3_000_000),
            top_n=_env_int("BERSERK2_TOP_N", 20),
            spread_map=spread_map,
            volume_map=volume_map,
        )
        try:
            from elite_trader.mega_live import mega_motor_active
            from elite_trader.mega_volatility import enabled as mega_vol_enabled
            from elite_trader.mega_volatility import refresh_from_price_universe
            from elite_trader.berserk2_movers import get_top10

            if mega_motor_active() and mega_vol_enabled():
                refresh_from_price_universe(
                    list(universe),
                    by_sym,
                    price_history,
                    spread_map=spread_map,
                    volume_map=volume_map,
                    top_movers=tuple(get_top10() or ()),
                )
        except Exception:
            pass
    except Exception:
        pass
    scan_berserk2_top10_signals()
    _trim_global_price_caches()


def _trim_berserk2_price_caches(allowed: set[str]) -> None:
    """Geriye uyumluluk — global trim."""
    if allowed:
        _trim_global_price_caches()


def scan_motor_eval() -> None:
    """Top-N motor — bütçeli, round-robin, sembol/tur sınırı."""
    global last_scan_ms, _last_motor_at, _motor_eval_cursor, _last_motor_eval_n
    global _last_motor_candidates_n, _motor_live_gate_left

    if _berserk2_scan_active():
        _last_motor_at = time.time()
        last_scan_ms = 0.5
        return

    from elite_trader.market_intelligence_hub import get_hub

    gen = _motor_thread_generation
    _last_motor_at = time.time()
    _motor_live_gate_left = max(1, _env_int("MOTOR_LIVE_GATE_PER_CYCLE", 1))
    t0 = time.time()
    hard_deadline = t0 + _motor_cycle_hard_timeout_sec()
    budget = _motor_scan_budget_sec()
    max_sym = _motor_symbols_per_cycle()
    eval_n = 0
    deadline = t0 + budget
    try:
        if time.time() >= hard_deadline:
            return
        prices = _bulk_prices_cached_fast()
        if gen != _motor_thread_generation:
            return
        get_hub().ingest_bulk_prices(prices)

        if not prices:
            return

        candidates = _collect_entry_eval_symbols_cached(prices)
        _last_motor_candidates_n = len(candidates)
        if not candidates:
            return

        n = len(candidates)
        start = _motor_eval_cursor % n
        ordered = candidates[start:] + candidates[:start]

        for i, (sym, fp) in enumerate(ordered):
            if gen != _motor_thread_generation:
                break
            if i >= max_sym or time.time() >= deadline or time.time() >= hard_deadline:
                break
            _last_motor_at = time.time()
            try:
                _evaluate_signal_candidate(sym, fp, deadline=min(deadline, hard_deadline))
                eval_n += 1
            except Exception:
                pass
            _motor_eval_cursor += 1
    finally:
        last_scan_ms = (time.time() - t0) * 1000.0
        _last_motor_at = time.time()
        _last_motor_eval_n = eval_n


def scan_entry_eval_light() -> None:
    """Hızlı tick sonrası hafif giriş turu — yalnızca top kısa momentum."""
    prices = _bulk_prices_cached()
    if not prices:
        return
    top_n = max(8, min(32, _env_int("ENTRY_LIGHT_TOP_N", 24)))
    for sym, fp in _collect_entry_eval_symbols(prices, top_n=top_n):
        _evaluate_signal_candidate(sym, fp)


def scan_signals_bulk() -> None:
    """Tam tur — tick + motor (geriye uyumluluk)."""
    scan_price_ticks_fast()
    scan_motor_eval()


def scan_signals_for_symbols(symbols: list[str]) -> None:
    """Verilen sembol listesi için fiyat + momentum (parça parça tarama için)."""
    global signals, price_history

    def _fetch_one(sym: str) -> tuple[str, float, float]:
        try:
            px, lat = fetch_price(sym)
            return sym, float(px), float(lat)
        except Exception:
            return sym, 0.0, 0.0

    futures = [_scan_executor.submit(_fetch_one, s) for s in symbols]
    scan_timeout = max(30.0, min(120.0, 6.0 + len(symbols) * 0.08))
    for fut in as_completed(futures, timeout=scan_timeout):
        try:
            symbol, price, _ = fut.result()
            if price > 0:
                _process_price_tick(symbol, price)
        except Exception:
            continue


def scan_signals() -> None:
    scan_signals_bulk()


async def scan_signals_async_full() -> None:
    await asyncio.to_thread(scan_motor_eval)


async def scan_ticks_async() -> None:
    await asyncio.to_thread(scan_price_ticks_fast)


def update_capital_history():
    current = get_current_capital()
    capital_history.append({
        'time': datetime.utcnow().isoformat(),
        'capital': current
    })
    
    if len(capital_history) > 100:
        capital_history.pop(0)

def _watchlist_prices_rest_api() -> dict[str, Any]:
    """Canlı panel ticker — yalnızca REST positionRisk mark (açık pozisyonlar)."""
    out: dict[str, Any] = {}
    if not (LIVE_ORDERS and not client.paper):
        return out
    for ep in _positions_cache or []:
        sym = str(ep.get("symbol") or f"{ep.get('coin')}USDT")
        raw = ep.get("exchange_raw") or {}
        mark_s = raw.get("markPrice")
        if mark_s is None or str(mark_s) == "":
            mark_s = str(ep.get("mark_price") or "")
        if not mark_s:
            continue
        try:
            mark = float(mark_s)
        except (TypeError, ValueError):
            continue
        entry = float(ep.get("entry_price") or 0)
        side = str(ep.get("side") or "LONG")
        chg = 0.0
        if entry > 0:
            chg = (mark - entry) / entry * 100.0
            if side == "SHORT":
                chg = -chg
        out[sym] = {
            "price": mark,
            "price_str": str(mark_s),
            "change": round(chg, 4),
            "source": "binance_rest",
        }
    return out


def _watchlist_prices_subset(max_keys: int = 527) -> dict[str, Any]:
    """Ticker şeridi — canlıda REST mark; paper'da yerel tarama."""
    if LIVE_ORDERS and not client.paper:
        return _watchlist_prices_rest_api()
    out: dict[str, Any] = {}
    open_syms = {p["symbol"] for p in positions}

    # price_history tabanlı: son ve ilk fiyat farkından % değişim
    ph_entries: list[tuple[str, float, float]] = []  # (sym, price, chg%)
    for sym, hist in price_history.items():
        if len(hist) < 2:
            continue
        cur = hist[-1]["price"]
        # Son 30 tik ile kıyasla (daha uzun pencere = daha iyi değişim tespiti)
        lookback_idx = max(0, len(hist) - 30)
        old = hist[lookback_idx]["price"]
        chg = (cur - old) / old * 100.0 if old else 0.0
        ph_entries.append((sym, cur, chg))

    # En volatil önce; açık pozisyonlar her zaman ilk sıraya
    ph_entries.sort(key=lambda x: (x[0] not in open_syms, -abs(x[2])))
    for sym, cur, chg in ph_entries[:max_keys]:
        out[sym] = {"price": cur, "change": round(chg, 4)}

    # REST önbelleğinden eksik watchlist coinleri tamamla (başlangıç için)
    if len(out) < max_keys:
        with _price_cache_lock:
            cache_snap = dict(_price_cache)
        for coin, price in cache_snap.items():
            if len(out) >= max_keys:
                break
            sym = f"{coin}USDT"
            if sym not in out and price:
                out[sym] = {"price": float(price), "change": 0.0}

    return out


def _execution_realism_bundle() -> dict[str, Any]:
    """
    Paper sonuçlarının canlıya taşınabilirliği — kabaca slipaj tavanı, ücret,
    gecikme ve dolum olasılığı (order book derinliği tam modellenmez).
    """
    slip_cap = _env_float("ENTRY_CLOB_MAX_SLIPPAGE", 0.03)
    taker_rt = 0.0004 * 2.0
    n = len(positions)
    # Çok eşzamanlı pozisyon → düşük likidite altında dolum riski artar
    fill_p = max(0.45, min(0.96, 0.94 - n * 0.025))
    spread_proxy_bps = 3.0 + min(22.0, n * 1.2) + last_avg_latency_ms * 0.01
    return {
        "max_slippage_budget": round(slip_cap, 4),
        "round_trip_taker_fee_rate": taker_rt,
        "avg_price_api_latency_ms": round(last_avg_latency_ms, 2),
        "estimated_fill_probability": round(fill_p, 3),
        "spread_stress_proxy_bps": round(spread_proxy_bps, 2),
        "open_positions_load_factor": n,
        "disclaimer": (
            "Testnet / paper ile ana ağ likiditesi ve gerçek derinlik farklıdır; "
            "sonuçlar ortalamaya dayalı heuristiktir."
        ),
    }


def _adaptive_setup_summary() -> dict[str, Any]:
    """Kapalı işlemlerden güç/strateji tipi — adaptif ağırlıklandırma için özet."""
    acc: dict[str, dict[str, float]] = defaultdict(
        lambda: {"n": 0, "wins": 0, "pnl": 0.0}
    )
    for p in closed_positions:
        k = str(p.get("signal_strength") or "Unknown")
        acc[k]["n"] += 1
        fp = float(p.get("final_pnl", p.get("net_pnl", 0)) or 0)
        acc[k]["pnl"] += fp
        if fp > 0:
            acc[k]["wins"] += 1
    out: dict[str, Any] = {}
    for k, v in acc.items():
        n = int(v["n"])
        wr = (v["wins"] / n) if n else 0.0
        out[k] = {
            "trades": n,
            "win_rate": round(wr, 4),
            "total_final_pnl": round(v["pnl"], 2),
        }
    return {"by_signal_strength": out, "total_closed": len(closed_positions)}


def _hedge_advisory_list() -> list[dict[str, Any]]:
    """Ters yöne hareket: hedge / ters maruziyet danışmanı (otomatik ikinci pozisyon açmaz)."""
    from elite_trader.fee_economics import hedge_loss_ratio

    advisories: list[dict[str, Any]] = []
    for pos in positions:
        ratio, net_unreal, sl_budget = hedge_loss_ratio(pos)
        if sl_budget <= 1e-9:
            continue
        if -0.88 <= ratio <= -0.15:
            opp = "SHORT" if pos["side"] == "LONG" else "LONG"
            frac = _env_float("ELITE_HEDGE_STAKE_FRAC", 0.38)
            advisories.append(
                {
                    "symbol": pos["symbol"],
                    "current_side": pos["side"],
                    "unrealized_vs_sl": round(ratio, 3),
                    "net_unrealized_usd": round(net_unreal, 4),
                    "sl_budget_usd": round(sl_budget, 4),
                    "suggested_hedge_or_flip_side": opp,
                    "suggested_hedge_stake_frac_of_main": frac,
                    "rationale": (
                        "Net unrealized (ücret sonrası) / SL bütçesi — "
                        "hedge stake ≈ ana pozisyonun "
                        f"{frac:.0%}'i (ELITE_HEDGE_STAKE_FRAC)."
                    ),
                }
            )
    return advisories


def _approaching_signals_for_ui(limit: int = 28) -> list[dict[str, Any]]:
    """
    Şablonda boş ekran olmasın: motor kuyruğu + izleme adayları.
    Motor kuyruğundaki sinyaller önce gösterilir, sonra price_history'den izleme.
    """
    in_signals = {s["symbol"] for s in signals}
    min_pct = _env_float("UI_APPROACHING_MIN_PCT", 0.005)
    lookback = max(2, min(10, _env_int("UI_APPROACHING_LOOKBACK", 3)))
    # Motor kuyruğundaki sinyalleri önce ekle
    motor_syms: set[str] = set()
    rows: list[tuple[float, dict[str, Any]]] = []
    for ms in motor_signals[-30:]:
        sym = ms.get("symbol", "")
        if not sym:
            continue
        motor_syms.add(sym)
        abs_c = abs(float(ms.get("change") or 0))
        rows.append((abs_c + 10.0, {  # motor sinyalleri her zaman üstte
            "symbol": sym,
            "type": ms.get("type", "LONG"),
            "price": float(ms.get("price") or 0),
            "change": float(ms.get("change") or 0),
            "time": ms.get("time", datetime.utcnow().strftime("%H:%M:%S")),
            "strength": ms.get("strength", "Strong"),
            "ui_tier": "motor",
            "ui_label": "Motor",
        }))
    in_signals = in_signals | motor_syms
    for symbol, hist in price_history.items():
        if symbol in in_signals:
            continue
        if len(hist) < lookback:
            continue
        price = float(hist[-1]["price"])
        old = float(hist[-lookback]["price"])
        if old <= 0 or price <= 0:
            continue
        change = ((price - old) / old) * 100.0
        if abs(change) < min_pct:
            continue
        boost = 0.0
        if len(hist) > 4:
            op4 = float(hist[-4]["price"])
            if op4 > 0:
                micro = ((price - op4) / op4) * 100.0
                if abs(micro) > abs(change) * 0.35:
                    boost = 0.02 * (1 if change * micro > 0 else -1)
        adj_change = change + boost
        abs_c = abs(adj_change)
        strength = (
            "Strong"
            if abs_c > 0.5
            else "Medium"
            if abs_c > 0.25
            else "Weak"
        )
        rows.append(
            (
                abs_c,
                {
                    "symbol": symbol,
                    "type": "LONG" if adj_change > 0 else "SHORT",
                    "price": price,
                    "change": float(adj_change),
                    "time": datetime.utcnow().strftime("%H:%M:%S"),
                    "strength": strength,
                    "ui_tier": "approaching",
                    "ui_label": "İzleme",
                },
            )
        )
    rows.sort(key=lambda x: -x[0])
    return [r[1] for r in rows[:limit]]


def _flash_reversal_watch_for_ui(limit: int = 16) -> list[dict[str, Any]]:
    """Flash düşüş → dönüş adayları — panel 'Yaklaşan Dönüş' satırı."""
    global _reversal_watch_cache, _reversal_watch_cache_ts
    now = time.time()
    if (
        _reversal_watch_cache
        and (now - _reversal_watch_cache_ts) < _REVERSAL_WATCH_TTL_SEC
    ):
        return list(_reversal_watch_cache[:limit])

    from elite_trader.berserk2_flash_reversal import flash_reversal_enabled, scan_flash_reversal_watch
    from elite_trader.mode_profiles import get_profile

    prof = get_profile("berserk2") or {}
    if not flash_reversal_enabled(prof):
        _reversal_watch_cache = []
        _reversal_watch_cache_ts = now
        return []

    in_signals = {s.get("symbol") for s in signals if s.get("symbol")}
    rows: list[tuple[float, dict[str, Any]]] = []
    try:
        from elite_trader.berserk2_movers import iter_tracked_symbols

        symbols = list(iter_tracked_symbols())
    except Exception:
        symbols = list(price_history.keys())

    prices = _bulk_prices_cached_fast() or {}
    for sym in symbols:
        if sym in in_signals:
            continue
        hist = price_history.get(sym) or price_history.get(sym.replace("USDT", "")) or []
        if len(hist) < 4:
            continue
        fp = float(
            prices.get(sym)
            or prices.get(sym.replace("USDT", ""))
            or hist[-1].get("price")
            or 0
        )
        if fp <= 0:
            continue
        row = scan_flash_reversal_watch(sym, fp, price_history, prof)
        if not row:
            continue
        rows.append((float(row.get("watch_score") or 0), row))

    rows.sort(key=lambda x: -x[0])
    _reversal_watch_cache = [r[1] for r in rows[: max(limit, 16)]]
    _reversal_watch_cache_ts = now
    return list(_reversal_watch_cache[:limit])


def _scanner_status_dict() -> dict[str, Any]:
    from elite_trader.market_intelligence_hub import get_hub

    ready10 = sum(1 for h in price_history.values() if len(h) >= 10)
    ui_lb = max(2, min(10, _env_int("UI_APPROACHING_LOOKBACK", 3)))
    ready_ui = sum(1 for h in price_history.values() if len(h) >= ui_lb)
    pool = get_hub().snapshot()
    scan_meta: dict[str, Any] = {}
    paper_gate: dict[str, Any] = {}
    try:
        from elite_trader.hunter_metrics import hunter_scan_meta

        scan_meta = hunter_scan_meta()
    except Exception:
        pass
    try:
        paper_gate = {
            "summary": parallel_engine.paper_reject_summary(),
            "scan_universe_size": len(watchlist),
            "tradable_core_size": len(tradable_symbols),
        }
    except Exception:
        pass
    return {
        "last_tick_ms": round(last_tick_ms, 1),
        "last_full_scan_ms": round(last_scan_ms, 1),
        "last_motor_eval_ms": round(last_scan_ms, 1),
        "ui_tick_interval_sec": _ui_tick_interval_sec(),
        "motor_scan_interval_sec": _effective_motor_scan_interval_sec(),
        "last_position_price_ms": round(last_position_price_ms, 1),
        "position_price_interval_ms": round(_position_check_interval() * 1000, 0),
        "open_position_count": len(positions),
        "watchlist_total": len(watchlist),
        "symbols_with_ticks": len(price_history),
        "symbols_ready_for_momentum": ready10,
        "symbols_ready_for_ui_watch": ready_ui,
        "ui_lookback_bars": ui_lb,
        "confirmed_signal_count": len(motor_signals),
        "intelligence_pool": pool,
        "hunter_scan": scan_meta,
        "scan_eval_top_n": _scan_eval_top_n(),
        "paper_gate": paper_gate,
    }


def _loop_status(last_at: float, interval_sec: float, *, stale_mult: float = 3.0) -> str:
    if last_at <= 0:
        return "bekliyor"
    age = time.time() - last_at
    if age <= interval_sec * stale_mult:
        return "ok"
    if age <= interval_sec * stale_mult * 3:
        return "yavaş"
    return "durdu"


def _build_system_health_panel() -> dict[str, Any]:
    """Sağ üst panel — döngü aralıkları, son süre, gecikme."""
    now = time.time()
    ss = _scanner_status_dict()
    tick_iv = _ui_tick_interval_sec()
    motor_iv = _effective_motor_scan_interval_sec()
    pos_iv = _position_check_interval(has_open=True)
    snap_iv = 0.35

    fast_alive = bool(_fast_tick_thread and _fast_tick_thread.is_alive())
    motor_alive = bool(_motor_scan_thread and _motor_scan_thread.is_alive())
    wd_alive = bool(_watchdog_thread and _watchdog_thread.is_alive())
    snap_alive = bool(_snapshot_refresh_thread and _snapshot_refresh_thread.is_alive())
    pos_alive = bool(_position_price_thread and _position_price_thread.is_alive())
    exch_alive = bool(_exchange_poll_thread and _exchange_poll_thread.is_alive())

    try:
        paper_open = sum(parallel_engine.open_counts_by_mode().values())
    except Exception:
        paper_open = 0
    live_open = len(positions)
    pos_idle = paper_open == 0 and live_open == 0

    try:
        paper_stats = parallel_engine.paper_signal_stats()
    except Exception:
        paper_stats = {}

    loops = [
        {
            "id": "universe_tick",
            "label": "Evren fiyat tick",
            "detail": f"{ss.get('symbols_with_ticks', 0)}/{ss.get('watchlist_total', '?')} sembol",
            "interval_sec": round(tick_iv, 2),
            "duration_ms": round(last_tick_ms, 1),
            "ago_sec": round(now - _last_tick_at, 1) if _last_tick_at else None,
            "status": _loop_status(_last_tick_at, tick_iv),
            "thread": "fast-tick" if fast_alive else "kapalı",
        },
        {
            "id": "motor_scan",
            "label": "BERSERK2 top10" if _berserk2_scan_active() else "Motor tarama",
            "detail": (
                (
                    f"top10 aday={_last_motor_candidates_n} eval={_last_motor_eval_n} "
                    f"· bütçe {int(_env_float('BERSERK2_SCAN_BUDGET_MS', 180))}ms (fast-tick)"
                )
                if _berserk2_scan_active()
                else (
                    f"tur×{_motor_symbols_per_cycle()} aday={_last_motor_candidates_n} eval={_last_motor_eval_n} "
                    f"· bütçe {int(_motor_scan_budget_sec()*1000)}ms"
                    + (f" · kurtarma×{_motor_recoveries}" if _motor_recoveries else "")
                )
            ),
            "interval_sec": round(
                _env_float("BERSERK2_SCAN_INTERVAL_SEC", 0.28)
                if _berserk2_scan_active()
                else motor_iv,
                2,
            ),
            "duration_ms": round(last_scan_ms, 1),
            "ago_sec": round(now - _last_motor_at, 1) if _last_motor_at else None,
            "status": (
                "yavaş"
                if last_scan_ms
                > (
                    _env_float("BERSERK2_SCAN_BUDGET_MS", 180) * 2.5
                    if _berserk2_scan_active()
                    else motor_iv * 1000 * 2.5
                )
                else _loop_status(_last_motor_at, motor_iv)
            ),
            "thread": "fast-tick/b2" if _berserk2_scan_active() else ("motor-scan" if motor_alive else "kapalı"),
        },
        {
            "id": "paper_signal",
            "label": "Paper sinyal kuyruk",
            "detail": (
                f"pending={paper_stats.get('pending', 0)} "
                f"· işlenen={paper_stats.get('processed', 0)}"
                + (f" · restart×{_motor_stuck_restarts}" if _motor_stuck_restarts else "")
            ),
            "interval_sec": round(_paper_signal_budget_sec(), 2),
            "duration_ms": None,
            "ago_sec": None,
            "status": "ok" if paper_stats.get("worker_alive") else "kapalı",
            "thread": "paper-signal" if paper_stats.get("worker_alive") else "kapalı",
        },
        {
            "id": "panel_ws",
            "label": "Panel WS snapshot",
            "detail": "approaching + scanner",
            "interval_sec": snap_iv,
            "duration_ms": round(_last_snapshot_build_ms, 1),
            "ago_sec": round(now - _last_snapshot_at, 1) if _last_snapshot_at else None,
            "status": _loop_status(_last_snapshot_at, snap_iv),
            "thread": "snapshot-refresh" if snap_alive else "kapalı",
        },
        {
            "id": "position_price",
            "label": "Pozisyon fiyat",
            "detail": (
                f"TP/SL · max_age {int(_position_price_max_age_ms())}ms"
                + (f" · eksik {_last_position_missing_n}" if _last_position_missing_n else "")
                + (f" · uyarı×{_position_stalls_total}" if _position_stalls_total else "")
            ),
            "interval_sec": round(pos_iv, 2),
            "duration_ms": round(last_position_price_ms, 1),
            "ago_sec": round(now - _last_position_price_at, 1) if _last_position_price_at else None,
            "status": (
                "ok"
                if pos_idle
                else (
                    _loop_status(_last_position_price_at, pos_iv)
                    if _last_position_price_at
                    else ("ok" if pos_alive else "kapalı")
                )
            ),
            "thread": "position-price" if pos_alive else "kapalı",
        },
        {
            "id": "exchange_poll",
            "label": "Pozisyon motoru",
            "detail": (
                f"REST positionRisk · {int(_effective_position_poll_interval_sec() * 1000)}ms"
                + (
                    f" · son {round(_exchange_position_poll_ms, 0)}ms"
                    if _exchange_position_poll_ms
                    else ""
                )
                + (
                    f" · timeout×{_exchange_position_poll_timeouts}"
                    if _exchange_position_poll_timeouts
                    else ""
                )
            ),
            "interval_sec": round(_effective_position_poll_interval_sec(), 2),
            "duration_ms": round(_exchange_position_poll_ms, 1) or None,
            "ago_sec": (
                round(now - _exchange_cache_ts, 2) if _exchange_cache_ts else None
            ),
            "status": (
                "ok"
                if exch_alive
                else ("yavaş" if _exchange_position_poll_timeouts else "kapalı")
            ),
            "thread": "exchange-poll" if exch_alive else "kapalı",
        },
    ]

    all_ok = all(
        lp.get("status") in ("ok", "bekliyor")
        for lp in loops
        if lp["id"] in ("universe_tick", "motor_scan", "panel_ws", "position_price")
    )

    pipeline = {
        "universe_tracked": ss.get("symbols_with_ticks", 0),
        "approaching_ready": ss.get("symbols_ready_for_ui_watch", 0),
        "signals_count": len(signals),
        "motor_eval_last": _last_motor_eval_n,
        "motor_candidates_last": _last_motor_candidates_n,
        "paper_open": paper_open,
        "live_open": live_open,
        "recoveries": _motor_recoveries,
        "motor_restarts": _motor_stuck_restarts,
        "position_restarts": _position_stuck_restarts,
        "paper_queue_pending": paper_stats.get("pending", 0),
        "paper_queue_processed": paper_stats.get("processed", 0),
        "watchdog": "ok" if wd_alive else "kapalı",
        "position_stalls": _position_stalls_total,
        "position_missing_prices": _last_position_missing_n,
        "position_tick_ms": round(last_position_price_ms, 1),
    }

    pos_alerts = list(_position_stall_events[:4])
    if not pos_idle and _last_position_price_at > 0:
        pos_age = now - _last_position_price_at
        if pos_age > pos_iv * 2.5:
            pos_alerts.insert(
                0,
                {
                    "ts": now,
                    "kind": "stale_tick",
                    "detail": f"son pozisyon fiyat {pos_age:.1f}s önce",
                },
            )

    return {
        "ok": all_ok and not pos_alerts,
        "updated_at_iso": datetime.utcnow().isoformat() + "Z",
        "summary": (
            "Pipeline aktif — evren/sinyal/pozisyon akıyor"
            if all_ok
            else "Bazı döngüler yavaş veya durmuş — watchdog kurtarıyor"
        ),
        "loops": loops,
        "pipeline": pipeline,
        "position_alerts": pos_alerts,
        "approaching_ready": ss.get("symbols_ready_for_ui_watch"),
        "approaching_min_pct": _env_float("UI_APPROACHING_MIN_PCT", 0.005),
        "tick_match_scan": bool(_env_int("ELITE_UI_TICK_MATCH_SCAN", 1)),
    }


def _view_mode_detail(view_id: str) -> dict[str, Any]:
    """Görünüm modu detayı — profil ayarları değiştirilmez."""
    cat = mode_catalog()
    prof = cat.get(view_id) or {}
    book = parallel_engine.get_universe_book(view_id)
    summ = parallel_engine.build_summary(view_id)
    return {
        "mode_id": view_id,
        "label": prof.get("label") or view_id,
        "short_label": prof.get("short_label") or view_id,
        "description": prof.get("description") or "",
        "is_live": bool(prof.get("is_live")),
        "shadow_only": prof.get("shadow_only", True),
        "starting_balance": prof.get("starting_balance"),
        "tp_stake_pct": prof.get("tp_stake_pct"),
        "sl_stake_pct": prof.get("sl_stake_pct"),
        "min_edge": prof.get("min_edge"),
        "open_count": len(book.get("open") or []),
        "closed_count": len(book.get("closed") or []),
        "dashboard": summ,
    }


def _closed_row_quality(row: dict[str, Any]) -> tuple[Any, ...]:
    """Aynı id — en doğru satır (API settlement öncelikli)."""
    return (
        1 if row.get("exchange_settled") else 0,
        1 if str(row.get("fee_source") or "") == "binance_api" else 0,
        1 if str(row.get("pnl_source") or "") == "binance_api" else 0,
        1 if row.get("wallet_pnl") is not None else 0,
        1 if row.get("exchange_close_order_id") else 0,
        str(row.get("exit_time") or row.get("closed_at") or ""),
    )


def _closed_dedupe_key(row: dict[str, Any]) -> tuple[Any, ...]:
    rid = row.get("id")
    if rid is not None:
        return ("id", int(rid))
    sym = str(row.get("symbol") or "").upper()
    side = str(row.get("side") or "").upper()
    return (
        "row",
        sym,
        side,
        str(row.get("exit_time") or row.get("closed_at") or ""),
    )


def _dedupe_closed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aynı id (+ sembol) — tek satır; DB/API kaydı tercih."""
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = _closed_dedupe_key(row)
        prev = best.get(key)
        if prev is None or _closed_row_quality(row) > _closed_row_quality(prev):
            best[key] = dict(row)
    out = list(best.values())
    out.sort(
        key=lambda c: str(c.get("exit_time") or c.get("closed_at") or ""),
        reverse=True,
    )
    return out


def _closed_net_pnl_row(row: dict[str, Any]) -> float:
    """Kapalı satır net PnL — brüt realized (pnl_usd) asla net sayılmaz."""
    for key in ("wallet_pnl", "final_pnl", "net_pnl"):
        val = row.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


def _sum_closed_net_pnl(rows: list[dict[str, Any]]) -> float:
    return round(sum(_closed_net_pnl_row(r) for r in rows), 2)


def _closed_win_count(rows: list[dict[str, Any]]) -> int:
    return len([r for r in rows if _closed_net_pnl_row(r) > 0])


def _session_pnl_summary_fields(
    closed_ui: list[dict[str, Any]], *, session_start: float | None = None
) -> dict[str, float | int]:
    realized = _sum_closed_net_pnl(closed_ui)
    wins = _closed_win_count(closed_ui)
    start = float(session_start if session_start is not None else _motor_session_start())
    out: dict[str, float | int] = {
        "realized_pnl": realized,
        "total_pnl": realized,
        "closed_trades": len(closed_ui),
        "win_count": wins,
        "closed_losses": max(0, len(closed_ui) - wins),
    }
    if start > 0:
        out["starting_capital"] = round(start, 2)
        out["total_pnl_pct"] = round(realized / start * 100, 2)
        out["win_rate"] = round(wins / len(closed_ui) * 100, 1) if closed_ui else 0.0
    return out


def _closed_positions_for_ui() -> list[dict[str, Any]]:
    """Kapalı tablo — RAM + DB + paralel kitap birleşimi."""
    out = list(closed_positions)
    if _elite_state_enabled():
        try:
            from elite_pro_state import load_closed

            seen = {
                (c.get("id"), c.get("symbol"), c.get("exit_time")) for c in out
            }
            for c in load_closed() or []:
                key = (c.get("id"), c.get("symbol"), c.get("exit_time"))
                if key not in seen:
                    out.append(c)
                    seen.add(key)
        except Exception:
            pass
    exec_mid = active_execution_mode()
    try:
        book = parallel_engine.get_universe_book(exec_mid)
        seen = {(c.get("id"), c.get("symbol"), c.get("exit_time")) for c in out}
        for c in book.get("closed") or []:
            key = (c.get("id"), c.get("symbol"), c.get("exit_time"))
            if key not in seen:
                out.append(c)
                seen.add(key)
    except Exception:
        pass
    out = _dedupe_closed_rows(out)
    if LIVE_ORDERS and not client.paper:
        try:
            from elite_trader.exchange_trade_truth import enrich_closed_list_api

            out = enrich_closed_list_api(out, client)
        except Exception:
            pass
    return out


def _closed_row_matches(
    row: dict[str, Any],
    trade_id: int,
    *,
    symbol: str | None = None,
    exit_time: str | None = None,
) -> bool:
    if int(row.get("id") or -1) != int(trade_id):
        return False
    if symbol and str(row.get("symbol") or "").upper() != str(symbol).upper():
        return False
    if exit_time:
        et = str(row.get("exit_time") or row.get("closed_at") or "")
        if et != str(exit_time):
            return False
    return True


def _closed_stats_from_ram() -> dict[str, Any]:
    wins = len(
        [p for p in closed_positions if float(p.get("final_pnl") or 0) > 0]
    )
    total = len(closed_positions)
    return {
        "closed_trades": total,
        "win_count": wins,
        "closed_losses": max(0, total - wins),
        "win_rate": round((wins / total * 100), 2) if total else 0.0,
        "realized_pnl": round(
            sum(
                float(p.get("final_pnl") or p.get("pnl_usd") or 0)
                for p in closed_positions
            ),
            4,
        ),
        "total_fees": round(
            sum(float(p.get("total_fees") or 0) for p in closed_positions), 4
        ),
        "total_taxes": round(
            sum(float(p.get("tax") or 0) for p in closed_positions), 4
        ),
    }


def _invalidate_snap_caches_after_closed_delete() -> None:
    global _heavy_snap_cache, _heavy_snap_cache_ts, _last_ws_snapshot
    _heavy_snap_cache = {}
    _heavy_snap_cache_ts = 0.0
    if isinstance(_last_ws_snapshot, dict):
        summary = dict(_last_ws_snapshot.get("summary") or {})
        summary.update(_closed_stats_from_ram())
        pos = dict(_last_ws_snapshot.get("positions") or {})
        pos["closed"] = _closed_positions_for_ui()[-200:]
        _last_ws_snapshot["summary"] = summary
        _last_ws_snapshot["positions"] = pos


def delete_closed_trade(
    trade_id: int,
    *,
    symbol: str | None = None,
    exit_time: str | None = None,
    reason: str = "panel_row_delete",
) -> dict[str, Any]:
    """Panel — tek kapanmış işlem satırını arşivle, tüm kaynaklardan sil, KPI güncelle."""
    global closed_positions
    tid = int(trade_id)
    if tid <= 0:
        return {"ok": False, "error": "invalid trade id"}

    removed_rows = [c for c in closed_positions if _closed_row_matches(c, tid, symbol=symbol, exit_time=exit_time)]
    closed_positions[:] = [
        c for c in closed_positions if not _closed_row_matches(c, tid, symbol=symbol, exit_time=exit_time)
    ]

    db_row: dict[str, Any] | None = None
    if _elite_state_enabled():
        try:
            from elite_pro_state import delete_closed_by_id

            db_row = delete_closed_by_id(tid)
        except Exception as exc:
            return {"ok": False, "error": f"db delete failed: {exc}"}

    if not removed_rows:
        for c in _closed_positions_for_ui():
            if _closed_row_matches(c, tid, symbol=symbol, exit_time=exit_time):
                removed_rows.append(c)
                break
    if db_row and not removed_rows:
        removed_rows.append(db_row)

    mode_id = str(
        (removed_rows[0] if removed_rows else db_row or {}).get("panel_mode")
        or active_execution_mode()
    )
    try:
        parallel_engine.remove_closed_trade(
            tid, mode_id=mode_id, symbol=symbol, exit_time=exit_time
        )
    except Exception:
        pass

    archived = False
    archive_id = None
    if removed_rows:
        try:
            from elite_trader.data_archive import archive_single_closed_trade

            meta = archive_single_closed_trade(
                removed_rows[0], reason=reason, trigger="panel"
            )
            archived = True
            archive_id = meta.get("archive_id")
        except Exception:
            pass

    if not removed_rows and not db_row:
        return {"ok": False, "error": "trade not found", "trade_id": tid}

    _invalidate_snap_caches_after_closed_delete()
    stats = _closed_stats_from_ram()
    print(
        f"  🗑 Panel closed delete #{tid} {symbol or ''} "
        f"(archived={archived}, remaining={stats['closed_trades']})"
    )
    return {
        "ok": True,
        "trade_id": tid,
        "removed": bool(removed_rows or db_row),
        "archived": archived,
        "archive_id": archive_id,
        "summary": stats,
    }


def get_snapshot(*, light: bool = False) -> dict[str, Any]:
    # Hot path: önbellek kullan — WS/API burada Binance REST çağırmaz
    use_heavy_cache = light or _heavy_snap_cache_fresh()
    current_capital = get_current_capital()
    closed_ui = _closed_positions_for_ui()
    total_unrealized = sum(p['unrealized_pnl'] for p in positions)
    total_realized = _sum_closed_net_pnl(closed_ui)
    total_pnl = total_realized + total_unrealized
    
    win_count = _closed_win_count(closed_ui)
    total_count = len(closed_ui)
    win_rate = (win_count / total_count * 100) if total_count > 0 else 0
    
    total_fees = sum(p.get('total_fees', 0) for p in closed_positions)
    total_taxes = sum(p.get('tax', 0) for p in closed_positions)
    
    # Calculate total active stake
    total_active_stake = sum(p['stake_usd'] for p in positions)
    total_position_value = sum(p.get('position_value', p['size'] * p['current_price']) for p in positions)

    wr_session = _session_wr()
    elite_alloc = capital_snapshot(
        current_capital,
        [float(p["stake_usd"]) for p in positions],
        win_rate=wr_session,
    )
    exch_wallet = _wallet_cache if LIVE_ORDERS and not client.paper and _wallet_cache else None
    exch_positions = (
        _positions_cache if LIVE_ORDERS and not client.paper else []
    )
    avail = float(exch_wallet.get("available_balance", current_capital)) if exch_wallet else (
        current_capital - total_active_stake
    )
    session_start = _motor_session_start()
    session_total = session_start + total_realized + total_unrealized
    session_avail_est = max(0.0, session_total - total_active_stake)
    exchange_margin = (
        float(
            exch_wallet.get("total_margin_balance")
            or exch_wallet.get("total_wallet_balance")
            or 0
        )
        if exch_wallet
        else 0.0
    )
    exchange_wallet_bal = (
        float(exch_wallet.get("total_wallet_balance") or 0) if exch_wallet else 0.0
    )
    exchange_avail = float(exch_wallet.get("available_balance") or 0) if exch_wallet else 0.0

    ps = panel_strategy_snapshot()
    view = active_view_mode()
    snap: dict[str, Any] = {
        'ts': datetime.utcnow().isoformat() + 'Z',
        'live_only': live_only_execution(),
        'display_source': 'live',
        'view_mode': view,
        'view_label': ps.get('view_label') or 'Ana Hat',
        'mode': (
            'DEMO_LIVE'
            if LIVE_ORDERS and not client.paper
            else ('TESTNET' if not client.paper else 'PAPER')
        ),
        'live_orders': LIVE_ORDERS and not client.paper,
        'api_connected': LIVE_ORDERS and not client.paper and not client._auth_error,
        'auth_error': client._auth_error or (
            "demo-fapi.binance.com SSL timeout — ağ/VPN kontrol; otomatik yeniden denenecek"
            if LIVE_ORDERS and client.paper
            else None
        ),
        'api_reconnecting': LIVE_ORDERS and client.paper,
        'exchange_balance': (
            exch_wallet.get("available_balance") if exch_wallet else None
        ),
        'exchange_wallet': exch_wallet,
        'exchange_positions': exch_positions,
        'wallet': {
            'usdt': current_capital,
            'available_usdt': avail,
            'max_position_usd': _env_float(
                "MAX_POSITION_USD", STARTING_CAPITAL * 0.1
            ),
        },
        'summary': {
            'starting_capital': session_start,
            'current_capital': current_capital,
            'session_total_balance': round(session_total, 2),
            'session_available_est': round(session_avail_est, 2),
            'exchange_margin_balance': round(exchange_margin, 2),
            'exchange_wallet_balance': round(exchange_wallet_bal, 2),
            'exchange_available_balance': round(exchange_avail, 2),
            'realized_pnl': total_realized,
            'total_pnl': total_realized,
            'total_pnl_pct': (total_realized / session_start * 100) if session_start else 0,
            'unrealized_pnl': total_unrealized,
            'open_trades': len(positions),
            'closed_trades': total_count,
            'win_rate': win_rate,
            'win_count': win_count,
            'total_fees': total_fees,
            'total_taxes': total_taxes,
            'total_active_stake': total_active_stake,
            'total_position_value': total_position_value,
            'available_capital': avail,
            'exchange_unrealized_pnl': (
                float(exch_wallet.get("total_unrealized_pnl", 0)) if exch_wallet else 0
            ),
        },
        'elite': {
            'capital_allocator': elite_alloc,
            'session_win_rate': wr_session,
            'aggressive_high_growth': os.environ.get('AGGRESSIVE_HIGH_GROWTH', '0'),
            'emergency_equity_block': _emergency_equity_block(),
            'scan_loop_last_ms': last_scan_ms,
            'last_position_update_latency_ms': last_position_price_ms or last_avg_latency_ms,
            'last_position_price_ms': round(last_position_price_ms, 1),
            'scenario_file': SCENARIO_FILE,
            'dashboard_port_config': os.environ.get('DASHBOARD_PORT', ''),
            'watchlist_size': len(watchlist),
            'tradable_core_size': len(tradable_symbols),
            'sl_emergency_guard': sl_emergency_snapshot(),
            'loss_learner': loss_learner_snapshot(),
            'panel_strategy': panel_strategy_snapshot(),
            'evrim_adaptive': None,
            'motor_pipeline': (
                __import__(
                    "elite_trader.evrim_motor_diag",
                    fromlist=["build_motor_diag"],
                ).build_motor_diag(
                    execution_mode=active_execution_mode(),
                    reject_stats=_motor_reject_stats,
                    queue_len=len(motor_signals),
                    open_count=len(positions),
                    max_open=execution_max_open(),
                    last_order_ago_sec=round(time.time() - _last_demo_order_ts, 1)
                    if _last_demo_order_ts > 0
                    else None,
                    queue_added=_motor_queue_added,
                    orders_opened=_motor_orders_opened,
                )
            ),
            'parallel_universes': None,
            'deleted_archives': [] if light else (
                snapshot_archives_for_ui(limit=25)
                if _elite_state_enabled()
                else []
            ),
            'mode_archives': [] if light else (
                list_mode_archives(view, limit=25)
                if _elite_state_enabled()
                else []
            ),
        },
        'execution_realism': _execution_realism_bundle(),
        'adaptive_learning': _adaptive_setup_summary(),
        'hedge_advisory': _hedge_advisory_list(),
        'positions': {
            'open': positions,
            'closed': [],  # aşağıda live path ile doldurulur
        },
        'signals': signals[-20:],
        'approaching_signals': _approaching_signals_for_ui(),
        'approaching_reversal_signals': _flash_reversal_watch_for_ui(),
        'scanner_status': _scanner_status_dict(),
        'system_health': _build_system_health_panel(),
        'equity': [p['capital'] for p in capital_history],
        'timestamps': [p['time'] for p in capital_history],
        'watchlist_prices': _watchlist_prices_subset(),
        'price_deltas': (
            {}
            if live_only_execution()
            else get_price_deltas()
        ),
    }

    closed_ui = _closed_positions_for_ui()[-200:]
    snap["positions"]["closed"] = closed_ui

    exec_mid = active_execution_mode()
    snap['execution_mode'] = exec_mid
    snap['execution_label'] = (mode_catalog().get(exec_mid) or {}).get("label", exec_mid)
    snap['view_mode'] = view
    snap['view_label'] = ps.get('view_label') or snap.get('view_label')
    if not use_heavy_cache:
        try:
            from elite_trader.market_intelligence_hub import get_hub

            snap['market_intelligence'] = get_hub().snapshot()
        except Exception:
            snap['market_intelligence'] = None
        snap['view_mode_detail'] = _view_mode_detail(view)
        snap['execution_mode_detail'] = _view_mode_detail(exec_mid)
    else:
        snap.setdefault('market_intelligence', None)
        snap.setdefault('view_mode_detail', None)
        snap.setdefault('execution_mode_detail', None)

    live_motor = LIVE_ORDERS and is_live_binance_motor(exec_mid)
    binance_connected = live_motor and not client.paper
    binance_cached = live_motor and client.paper and bool(exch_positions)

    open_ui: list[dict[str, Any]] | None = None
    if binance_connected or binance_cached:
        from elite_trader.exchange_open_display import build_open_positions_for_ui

        open_ui = build_open_positions_for_ui(
            positions,
            list(exch_positions or []),
            client,
            allow_chart_fetch=False,
            enrich_fill=False,
        )
        if not _panel_api_only_mode():
            open_ui = _overlay_ws_marks_on_binance_open_ui(open_ui)
        live_closed = closed_ui
        u_summary = parallel_engine.build_summary(view)
        snap['positions'] = {"open": open_ui, "closed": live_closed}
        snap['open_positions_source'] = 'binance' if binance_connected else 'binance_cache'
        snap['display_source'] = 'binance'
        tu = sum(float(p.get("unrealized_pnl") or 0) for p in open_ui)
        snap['summary'] = {**snap['summary'], **u_summary}
        snap['summary']['unrealized_pnl'] = tu
        snap['summary']['open_trades'] = len(open_ui)
        snap['summary']['closed_trades'] = len(closed_positions)
        snap['summary']['win_count'] = win_count
        snap['summary']['closed_losses'] = max(0, total_count - win_count)
        snap['summary']['win_rate'] = win_rate
        snap['summary']['realized_pnl'] = round(total_realized, 2)
        if live_closed:
            snap['summary']['closed_trades'] = max(
                int(snap['summary'].get('closed_trades') or 0), len(live_closed)
            )
        if exch_wallet:
            snap['summary']['current_capital'] = float(
                exch_wallet.get("total_margin_balance") or u_summary['current_capital']
            )
            snap['summary']['available_capital'] = float(
                exch_wallet.get("available_balance") or avail
            )
        if binance_cached:
            snap['display_note'] = (
                f"Binance önbellek ({len(open_ui)} açık) — API yeniden bağlanıyor"
            )
        elif view != exec_mid:
            snap['display_note'] = (
                f"Açık pozisyonlar Binance canlı · görünüm "
                f"«{(mode_catalog().get(view) or {}).get('short_label', view)}» · "
                f"motor «{(mode_catalog().get(exec_mid) or {}).get('short_label', exec_mid)}»"
            )
    elif live_motor:
        live_closed = closed_ui
        snap['positions'] = {"open": [], "closed": live_closed}
        snap['open_positions_source'] = 'binance_offline'
        snap['display_source'] = 'binance'
        snap['display_note'] = (
            'Binance bağlantısı yok — yerel kitap gizlendi (panel = borsa truth)'
        )
        snap['summary']['open_trades'] = 0
        snap['summary']['unrealized_pnl'] = 0.0
    else:
        view_book = parallel_engine.get_universe_book(view)
        u_summary = parallel_engine.build_summary(view)
        view_open = list(view_book.get("open") or [])
        view_closed = list(view_book.get("closed") or [])[-200:]
        open_ui = _apply_live_mark_to_open_rows(
            _enrich_paper_positions_for_ui(view_open, view)
        )
        snap['display_source'] = 'mode_book'
        snap['positions'] = {"open": open_ui, "closed": view_closed}
        snap['open_positions_source'] = 'mode_book'
        snap['summary'] = {**snap['summary'], **u_summary}
        snap['view_session'] = {
            'mode_id': view,
            'mode_label': (mode_catalog().get(view) or {}).get('short_label') or view,
            **u_summary,
        }
        snap['display_note'] = (
            f"«{(mode_catalog().get(view) or {}).get('short_label', view)}» kitabı — "
            f"{len(open_ui)} açık · motor «{(mode_catalog().get(exec_mid) or {}).get('short_label', exec_mid)}»"
        )
    snap['wallet'] = {
        'usdt': snap['summary']['current_capital'],
        'available_usdt': snap['summary']['available_capital'],
        'max_position_usd': snap['wallet']['max_position_usd'],
    }

    ex_open_ui = open_ui
    if ex_open_ui is None and LIVE_ORDERS and is_live_binance_motor(exec_mid) and (
        not client.paper or bool(exch_positions)
    ):
        from elite_trader.exchange_open_display import build_open_positions_for_ui

        ex_open_ui = build_open_positions_for_ui(
            positions,
            list(exch_positions or []),
            client,
            allow_chart_fetch=False,
            enrich_fill=False,
        )
        if not _panel_api_only_mode():
            ex_open_ui = _overlay_ws_marks_on_binance_open_ui(ex_open_ui)
    pu_summary = dict(snap['summary'])
    if LIVE_ORDERS and not client.paper and exch_wallet:
        pu_summary['current_capital'] = round(
            float(exch_wallet.get("total_margin_balance") or current_capital), 2
        )
        pu_summary['available_capital'] = round(
            float(exch_wallet.get("available_balance") or avail), 2
        )
    try:
        snap['elite']['parallel_universes'] = parallel_universe_report(
            positions,
            closed_positions,
            starting_capital=_env_float("STARTING_BALANCE", 5000.0),
            live_summary=pu_summary,
            exchange_open_ui=ex_open_ui,
        )
    except Exception as exc:
        print(f"  ⚠ parallel_universe_report: {exc}")
        snap['elite']['parallel_universes'] = None
    try:
        _pu_books = parallel_engine.all_universe_books()
    except Exception as exc:
        print(f"  ⚠ strip_open_positions (books): {exc}")
        _pu_books = {}
    try:
        snap["strip_open_positions"] = _build_strip_open_positions(
            _pu_books,
            exec_mid=exec_mid,
            exchange_open_ui=ex_open_ui,
        )
    except Exception as exc:
        print(f"  ⚠ strip_open_positions: {exc}")
        snap["strip_open_positions"] = []
    try:
        snap["strip_recent_closed"] = _strip_recent_closed(_pu_books)
    except Exception as exc:
        print(f"  ⚠ strip_recent_closed: {exc}")
        snap["strip_recent_closed"] = []
    if light:
        try:
            snap["view_mode_detail"] = _view_mode_detail(view)
        except Exception:
            snap.setdefault("view_mode_detail", None)
    if not use_heavy_cache:
        try:
            from elite_trader.data_lake.ingest import summary_for_ui
            from elite_trader.evrim_meta_learning import latest_meta_summary

            snap["data_lake_summary"] = summary_for_ui()
            snap["modes_metrics"] = snap["data_lake_summary"]
            snap["evrim_meta_learning"] = latest_meta_summary()
        except Exception:
            snap["data_lake_summary"] = {}
            snap["modes_metrics"] = {}
            snap["evrim_meta_learning"] = {}
        try:
            snap['elite']['evrim_adaptive'] = (
                __import__(
                    "elite_trader.evrim_adaptive", fromlist=["snapshot_for_ui"]
                ).snapshot_for_ui()
            )
        except Exception:
            snap['elite']['evrim_adaptive'] = None
        if not light:
            _store_heavy_snap_cache(snap)
    else:
        _apply_heavy_snap_cache(snap)
    try:
        from elite_trader.order_gate import get_routing_status

        snap["motor_gate"] = get_routing_status(active_futures_mode())
    except Exception:
        snap["motor_gate"] = {}
    try:
        from elite_trader.system_checkpoint_md import list_recent_checkpoints

        snap["recent_checkpoints"] = list_recent_checkpoints(3)
    except Exception:
        snap["recent_checkpoints"] = []
    try:
        from elite_trader.evrim_live_decisions import get_panel

        snap["evrim_live_panel"] = get_panel()
    except Exception:
        snap["evrim_live_panel"] = {}
    if light and _heavy_snap_cache_fresh():
        snap.setdefault("modes_data_flow", _heavy_snap_cache.get("modes_data_flow") or {})
        snap.setdefault("sentinel_dashboard", _heavy_snap_cache.get("sentinel_dashboard") or {})
    else:
        try:
            from elite_trader.mode_minimum_data import all_status
            from elite_trader.mode_reject_buffer import all_summaries
            from elite_trader.parallel_universe_engine import all_universe_books

            books = all_universe_books()
            snap["modes_data_flow"] = {
                "minimum_data": all_status(books),
                "reject_buffers": all_summaries(),
            }
        except Exception:
            snap["modes_data_flow"] = {}
        try:
            from elite_trader.sentinel_benchmark import get_dashboard

            snap["sentinel_dashboard"] = get_dashboard(
                active_futures_mode=active_execution_mode(),
                live_orders=LIVE_ORDERS and not client.paper,
                book=parallel_engine.get_universe_book("sentinel"),
                global_scan_sec=_effective_motor_scan_interval_sec(),
            )
        except Exception:
            snap.setdefault("sentinel_dashboard", {})
    if light:
        try:
            snap["live_status_strip"] = _build_live_status_strip()
        except Exception:
            snap.setdefault("live_status_strip", {})
    return snap

class WSManager:
    def __init__(self):
        self.clients: list[WebSocket] = []
    
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.append(ws)
    
    def disconnect(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)
    
    async def broadcast(self, data: dict):
        if not self.clients:
            return
        txt = json.dumps(data)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(txt)
            except:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

ws_manager = WSManager()

async def update_loop():
    global last_avg_latency_ms
    await asyncio.sleep(2)

    update_count = 0
    last_tick_ts = 0.0
    last_exit_ts = 0.0
    _tick_task: asyncio.Task | None = None
    tick_iv = _ui_tick_interval_sec()
    exit_iv = max(0.25, _env_float("ELITE_POSITION_EXIT_SEC", 0.4))
    loop_sleep = 0.05

    while True:
        try:
            now = time.time()
            tick_iv = _ui_tick_interval_sec()
            if active_execution_mode() == "evrim":
                prof = execution_profile()
                exit_iv = max(1.0, float(prof.get("position_exit_sec") or exit_iv))
                if update_count % 90 == 0:
                    try:
                        from elite_trader.evrim_risk_policy import (
                            maybe_trade_flow_recovery,
                        )

                        rec = maybe_trade_flow_recovery(prof)
                        if rec.get("active"):
                            print(
                                f"  🔄 Evrim akış kurtarma: {rec.get('idle_sec', 0):.0f}s "
                                f"işlem yok — eşik gevşetildi"
                            )
                    except Exception:
                        pass
            has_open = bool(positions)
            if not has_open and update_count % 5 == 0:
                try:
                    has_open = bool(parallel_engine.open_position_coins())
                except Exception:
                    has_open = False

            if now - _watchlist_last_refresh >= _env_int(
                "BINANCE_UNIVERSE_REFRESH_SEC", 3600
            ):
                await asyncio.to_thread(refresh_tradeable_universe)

            # Borsa yedek senkron — ana TP/SL position-price thread'de
            if has_open and now - last_exit_ts >= exit_iv:
                await asyncio.to_thread(update_positions_exits)
                last_exit_ts = now

            # Fiyat tick — fast-tick thread birincil; ölüyse yedek
            _ft_alive = bool(_fast_tick_thread and _fast_tick_thread.is_alive())
            if not _ft_alive and now - last_tick_ts >= tick_iv:
                if _tick_task is None or _tick_task.done():
                    async def _safe_tick() -> None:
                        try:
                            await scan_ticks_async()
                        except Exception as _te:
                            print(f"⚠ tick task: {_te}")
                    _tick_task = asyncio.create_task(_safe_tick())
                    last_tick_ts = time.time()

            # Pipeline watchdog thread'leri denetler; motor asyncio döngüsünde

            if update_count % 5 == 0:
                update_capital_history()

            if update_count % 120 == 0:
                await asyncio.to_thread(refresh_exchange_cache)

            if update_count % 150 == 0 and client.paper and LIVE_ORDERS:
                asyncio.create_task(asyncio.to_thread(_try_reconnect_demo_api))

            if LIVE_ORDERS and not client.paper and not _emergency_equity_block():
                exec_q = _signals_for_live_execution()
                ranked = sorted(
                    list(exec_q[-40:]),
                    key=lambda s: abs(float(s.get("change") or 0)),
                    reverse=True,
                )
                for signal in ranked[:6]:
                    traded = await asyncio.to_thread(_try_execute_signal, signal)
                    if traded:
                        print(
                            f"🤖 Demo emir [{active_execution_mode()}]: "
                            f"{signal['symbol']} {signal['type']} "
                            f"Δ{float(signal['change']):+.2f}%"
                        )
                        break
                if update_count % 45 == 0:
                    await asyncio.to_thread(_maybe_log_motor_pipeline)

            await asyncio.to_thread(maybe_periodic_scan, closed_positions)
            if update_count % 60 == 0:
                await asyncio.to_thread(maybe_auto_apply_pending)
            if _evrim_runtime_enabled() and update_count % 40 == 0:
                try:
                    from elite_trader.evrim_adaptive import maybe_tune

                    await asyncio.to_thread(maybe_tune)
                except Exception:
                    pass
            if _evrim_runtime_enabled() and update_count % 1500 == 0:
                try:
                    from elite_trader.evrim_cross_mode_learner import bootstrap_evrim_from_history

                    await asyncio.to_thread(bootstrap_evrim_from_history)
                except Exception:
                    pass
            if (
                _evrim_runtime_enabled()
                or os.getenv("ELITE_MARKET_INTEL", "0").strip().lower()
                in ("1", "true", "yes")
            ) and update_count % 24 == 0:
                try:
                    from elite_trader.market_intelligence_hub import get_hub

                    await asyncio.to_thread(
                        get_hub().refresh_intelligence, force=False
                    )
                except Exception:
                    pass
            # Panel WS yayını ayrı döngüde (_panel_ws_broadcast_loop)

            update_count += 1
        except Exception as e:
            import traceback as _tb
            print(f"❌ {e}\n{''.join(_tb.format_tb(e.__traceback__))}")

        await asyncio.sleep(loop_sleep)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global STARTING_CAPITAL, client
    if LIVE_ORDERS and client.paper:
        print("  ⚠ Demo API geçici yok (SSL/ağ) — panel PAPER; 30sn'de yeniden denenecek")
        try:
            await asyncio.wait_for(
                asyncio.to_thread(_try_reconnect_demo_api), timeout=25.0
            )
        except asyncio.TimeoutError:
            pass
    elif LIVE_ORDERS and not client.paper:
        await asyncio.to_thread(_sync_positions_from_exchange)
        if _wallet_cache:
            print(
                f"  ✓ Demo cüzdan: ${_wallet_cache['total_margin_balance']:,.2f} USDT "
                f"(kullanılabilir ${_wallet_cache['available_balance']:,.2f}) | canlı emir AÇIK"
            )
        ex_mid = active_execution_mode()
        ex_lbl = (mode_catalog().get(ex_mid) or {}).get("label", ex_mid)
        prof = execution_profile()
        edge_h = prof.get("min_edge")
        edge_txt = f"edge≥{edge_h}" if edge_h is not None else "edge profil"
        print(
            f"  📡 Canlı emir motoru: {ex_lbl} ({edge_txt}) — "
            f"5 mod tarama; seçilmeyenler paper"
        )
    try:
        if not _async_hub_enabled():
            _ensure_ws_price_feeds()
    except Exception:
        pass
    if _async_hub_enabled():
        try:
            from binance_futures_trader.async_hub import start_hub
            from binance_futures_trader import config as _bcfg

            _core_syms = (
                list(tradable_symbols)[:50]
                if tradable_symbols
                else list(_bcfg.WATCHLIST)[:50]
            )
            if not _core_syms:
                _core_syms = list(_def_watch)[:50]
            await asyncio.wait_for(
                start_hub(
                    api_key=os.getenv("BINANCE_API_KEY", "").strip(),
                    on_wallet=_on_uds_wallet,
                    on_positions=None,
                    reconcile_fn=_hub_reconcile_exchange,
                    core_symbols=_core_syms,
                ),
                timeout=12.0,
            )
            print(
                f"  📡 Async Binance hub: !bookTicker + mark + UDS "
                f"(core WS {len(_core_syms)} sembol)"
            )
        except asyncio.TimeoutError:
            print("  ⚠ Async hub zaman aşımı (12s) — REST/cache fiyat yolu")
        except Exception as exc:
            print(f"  ⚠ Async hub başlatılamadı — legacy thread yolu: {exc}")
    if _evrim_runtime_enabled() or os.getenv("ELITE_MARKET_INTEL", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        try:
            from elite_trader.market_intelligence_hub import get_hub

            await asyncio.to_thread(get_hub().refresh_intelligence, force=True)
            print("  📡 Piyasa zekâ havuzu: haber + harici kaynak yüklendi")
        except Exception as exc:
            print(f"  ⚠ Piyasa havuzu: {exc}")
    else:
        print("  📡 Piyasa zekâ havuzu: kapalı (berserk2-only / ELITE_MARKET_INTEL=0)")
    if len(_price_cache) < 5:
        _load_price_cache()
    await asyncio.to_thread(_restore_closed_from_db)
    loss_learner_start()
    print("  🧬 Evrim 2×: birleşik motor (demo) + 10 modül + RSS haber")

    def _startup_heavy_background() -> None:
        from elite_trader.mode_registry import enabled_mode_ids

        enabled = set(enabled_mode_ids())
        if "evrim" in enabled:
            try:
                from elite_trader.evrim_adaptive import ensure_evrim_session, maybe_tune
                from elite_trader.evrim_opportunity import persist_learning_guide

                persist_learning_guide()
                ensure_evrim_session()
                maybe_tune(force=True)
            except Exception as exc:
                print(f"  ⚠ Evrim başlatma: {exc}")
            try:
                from elite_trader.evrim_cross_mode_learner import bootstrap_evrim_from_history

                boot = bootstrap_evrim_from_history()
                by_mode = boot.get("by_mode", {})
                total = boot.get("ingested", 0)
                if total:
                    detail = " ".join(f"{m}={n}" for m, n in by_mode.items())
                    print(f"  🧬 EVRIM çapraz-mod bootstrap: {total} işlem ({detail})")
            except Exception as _be:
                print(f"  ⚠ EVRIM bootstrap: {_be}")
        else:
            print("  ⏭ Evrim başlatma atlandı (ELITE_ENABLED_MODES — evrim kapalı)")
        if os.getenv("LAB_AUTO_BOOTSTRAP", "0").strip().lower() in ("1", "true", "yes"):
            try:
                from elite_trader.training_lab.lab_knowledge import bootstrap_system_knowledge

                boot = bootstrap_system_knowledge()
                if boot.get("written"):
                    print(f"  📚 Lab bilgi bootstrap: {len(boot['written'])} doküman")
                elif boot.get("skipped"):
                    print("  📚 Lab bilgi: zaten yüklü")
            except Exception as exc:
                print(f"  ⚠ Lab bootstrap: {exc}")

    threading.Thread(
        target=_startup_heavy_background, name="startup-bg", daemon=True
    ).start()
    try:
        from elite_trader.system_checkpoint_md import on_restart_boot

        cp = on_restart_boot()
        print(f"  📋 Checkpoint MD: {cp.get('file')}")
    except Exception as exc:
        print(f"  ⚠ Checkpoint MD: {exc}")
    try:
        ensure_spike_quick_proposal()
        n_auto = maybe_auto_apply_pending()
        if n_auto:
            print(f"  🧠 LossLearner: {n_auto} öneri otomatik onaylandı ve senaryoya yazıldı")
    except Exception as exc:
        print(f"  ⚠ LossLearner bootstrap: {exc}")
    # REST fiyat yenileme thread'i — WS çalışmasa bile fiyatlar güncel kalır
    _start_rest_price_refresher()
    _refresh_paper_open_coins_cache()
    _sync_position_fast_feed()
    _start_position_price_worker()
    global _position_worker_grace_until
    _position_worker_grace_until = time.time() + max(
        12.0, _env_float("ELITE_POSITION_BOOT_GRACE_SEC", 18.0)
    )
    _start_exchange_poll_worker()
    try:
        from elite_trader.mega_live import mega_motor_active, start_mega_rest_worker

        if mega_motor_active():
            start_mega_rest_worker()
    except Exception:
        pass
    _start_fast_tick_worker()
    _start_motor_scan_worker()
    _start_pipeline_watchdog()
    _start_connection_keeper()
    _start_snapshot_refresh()
    # bookTicker !all — SSL tek bağlantı, tüm coinler
    if not _async_hub_enabled():
        try:
            from binance_futures_trader.fast_price_ws import ensure_fast_feed_started as _eff

            _eff([])
        except Exception:
            pass
    try:
        _px0 = await asyncio.wait_for(asyncio.to_thread(client.all_prices), timeout=8.0)
        if len(_px0) >= 5:
            _now0 = time.time()
            with _price_cache_lock:
                _price_cache_prev.update(_price_cache)
                _price_cache.update(_px0)
                _price_cache_ts = _now0
            print(f"  ✅ Fiyat önbelleki dolduruldu: {len(_px0)} sembol")
    except asyncio.TimeoutError:
        print("  ⚠ Başlangıç fiyat önbelleki zaman aşımı — REST thread devralacak")
    except Exception as _e0:
        print(f"  ⚠ Başlangıç fiyat önbelleki doldurulamadı: {_e0}")
    if len(_price_cache) < 5:
        try:
            if _demo_only_data_enabled():
                _px_pub = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_demo_fapi_prices, client), timeout=8.0
                )
                if len(_px_pub) >= 5:
                    _now0 = time.time()
                    with _price_cache_lock:
                        _price_cache_prev.update(_price_cache)
                        _price_cache.update(_px_pub)
                        _price_cache_ts = _now0
                    try:
                        from binance_futures_trader.mark_ws import ingest_rest_prices

                        ingest_rest_prices(_px_pub)
                    except Exception:
                        pass
                    _save_price_cache()
                    print(f"  ↻ Fiyat yedek (demo-fapi): {len(_px_pub)} sembol")
            else:
                _px_pub = await asyncio.wait_for(
                    asyncio.to_thread(_fetch_public_mainnet_prices), timeout=6.0
                )
                if len(_px_pub) >= 5:
                    _now0 = time.time()
                    with _price_cache_lock:
                        _price_cache_prev.update(_price_cache)
                        _price_cache.update(_px_pub)
                        _price_cache_ts = _now0
                    try:
                        from binance_futures_trader.mark_ws import ingest_rest_prices

                        ingest_rest_prices(_px_pub)
                    except Exception:
                        pass
                    _save_price_cache()
                    print(f"  ↻ Fiyat yedek (mainnet public): {len(_px_pub)} sembol")
        except Exception:
            pass
    # Fast feed (bookTicker) — tam watchlist ile başlat
    if not _async_hub_enabled():
        try:
            from binance_futures_trader.fast_price_ws import ensure_fast_feed_started as _eff

            _seed = _fast_feed_coin_list()
            if _seed:
                _eff(_seed)
        except Exception:
            pass
    try:
        global _last_ws_snapshot
        _last_ws_snapshot = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "loading": True,
            "summary": {"current_capital": STARTING_CAPITAL, "open_trades": 0},
        }
    except Exception:
        pass
    asyncio.create_task(_panel_ws_broadcast_loop())
    asyncio.create_task(update_loop())
    yield
    if _async_hub_enabled():
        try:
            from binance_futures_trader.async_hub import stop_hub

            await stop_hub()
        except Exception:
            pass
    _stop_snapshot_refresh()
    _stop_pipeline_watchdog()
    _stop_connection_keeper()
    _stop_motor_scan_worker()
    _reset_motor_eval_executor()
    _stop_fast_tick_worker()
    _stop_position_price_worker()
    _stop_exchange_poll_worker()
    try:
        from elite_trader.mega_live import stop_mega_rest_worker

        stop_mega_rest_worker()
    except Exception:
        pass
    try:
        parallel_engine.stop_paper_signal_worker()
    except Exception:
        pass
    _reset_exchange_fetch_executor()
    _reset_api_heavy_executor()
    # Kapanırken parallel universe state'i diske yaz
    try:
        parallel_engine.flush_state()
    except Exception:
        pass

app = FastAPI(title=f"Binance Futures Elite Pro (:{ELITE_PORT})", lifespan=lifespan)

if _panel_v2_dir.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/panel-assets",
        StaticFiles(directory=str(_panel_v2_dir)),
        name="panel_assets",
    )


@app.exception_handler(RuntimeError)
async def _thread_exhaustion_handler(request, exc: RuntimeError):
    if "can't start new thread" in str(exc).lower():
        from starlette.responses import JSONResponse

        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "server_busy", "retry_ms": 500},
        )
    raise exc


@app.get("/legacy", response_class=HTMLResponse)
async def index_legacy():
    """Eski monolit panel."""
    try:
        if _elite_template_path.exists():
            return _elite_template_path.read_text(encoding="utf-8")
    except Exception:
        pass
    return _html_template_cache


@app.get("/", response_class=HTMLResponse)
async def index():
    if os.environ.get("BINANCE_ELITE_PORT") in MEGA_PRIMARY_PORTS:
        return RedirectResponse(url="/paper", status_code=302)
    try:
        if _panel_v2_enabled() and _panel_v2_index.exists():
            return _panel_v2_index.read_text(encoding="utf-8")
        if _elite_template_path.exists():
            return _elite_template_path.read_text(encoding="utf-8")
    except Exception:
        pass
    return _html_template_cache


@app.get("/paper", response_class=HTMLResponse)
async def index_paper():
    """MEGA paper lab — canlı berserk2'den ayrı görünüm."""
    try:
        port = os.environ.get("BINANCE_ELITE_PORT", "")
        if port == "9007" and _panel_v2_paper_9007.exists():
            return _panel_v2_paper_9007.read_text(encoding="utf-8")
        if _panel_v2_enabled() and _panel_v2_paper_index.exists():
            return _panel_v2_paper_index.read_text(encoding="utf-8")
    except Exception:
        pass
    return "<h1>MEGA Paper</h1><p>paper.html bulunamadı.</p>"


@app.get("/admin", response_class=HTMLResponse)
async def index_admin():
    p = _panel_v2_dir / "admin.html"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return "<h1>Admin</h1><p>admin.html bulunamadı.</p>"


@app.get("/lab", response_class=HTMLResponse)
async def index_lab():
    p = _panel_v2_dir / "lab.html"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return "<h1>Lab</h1><p>lab.html bulunamadı.</p>"


@app.get("/develop", response_class=HTMLResponse)
async def index_develop():
    p = _panel_v2_dir / "develop.html"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return "<h1>Develop</h1><p>develop.html bulunamadı.</p>"


@app.get("/ops", response_class=HTMLResponse)
async def index_ops():
    p = _panel_v2_dir / "ops.html"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return "<h1>Ops</h1><p>ops.html bulunamadı.</p>"


def _build_motor_pipeline_diag(
    exec_mid: str,
    *,
    open_count: int,
    reject_stats: dict[str, int] | None = None,
    queue_len: int | None = None,
) -> dict[str, Any]:
    from elite_trader.evrim_motor_diag import build_motor_diag

    return build_motor_diag(
        execution_mode=exec_mid,
        reject_stats=reject_stats if reject_stats is not None else dict(_motor_reject_stats),
        queue_len=int(queue_len if queue_len is not None else len(motor_signals)),
        open_count=open_count,
        max_open=execution_max_open(),
        last_order_ago_sec=round(time.time() - _last_demo_order_ts, 1)
        if _last_demo_order_ts > 0
        else None,
        queue_added=_motor_queue_added,
        orders_opened=_motor_orders_opened,
    )


def _panel_snap_from_mega_live(*, light: bool = True) -> dict[str, Any] | None:
    """9006 — /api/live ve monitor için MEGA Binance API özeti."""
    if not _is_mega_primary_process():
        return None
    try:
        from elite_trader.mega_live import mega_motor_active, snapshot as mega_snap
    except Exception:
        return None
    if not mega_motor_active():
        return None
    try:
        ms = mega_snap(light=light)
    except Exception:
        return None
    summ = ms.get("summary") or {}
    wallet = dict(ms.get("wallet") or {})
    scan = dict(ms.get("scan") or {})
    scan.update(_mega_scan_context())
    open_rows = list(ms.get("open") or [])
    closed_rows = list(ms.get("closed") or [])

    anchor = float(summ.get("session_anchor") or summ.get("starting_capital") or 0)
    equity = float(
        summ.get("equity") or summ.get("current_capital") or wallet.get("total_wallet_balance") or 0
    )
    margin = float(wallet.get("total_margin_balance") or equity)
    avail = float(
        summ.get("available_balance")
        or wallet.get("available_balance")
        or wallet.get("usdt_available")
        or 0
    )
    unreal = float(
        summ.get("unrealized_pnl") or wallet.get("total_unrealized_pnl") or 0
    )
    session_pnl = float(
        summ.get("session_pnl")
        if summ.get("session_pnl") is not None
        else (equity - anchor if anchor > 0 and equity > 0 else 0)
    )
    session_pct = float(
        summ.get("total_pnl_pct")
        if summ.get("total_pnl_pct") is not None
        else (session_pnl / anchor * 100.0 if anchor > 0 else 0.0)
    )

    reject_stats: dict[str, int] = {}
    for item in scan.get("reject_top") or []:
        reject_stats[str(item.get("reason") or "other")] = int(item.get("count") or 0)
    if not reject_stats:
        rb = scan.get("reject_buffer") or {}
        for item in rb.get("top") or []:
            reject_stats[str(item.get("reason") or "other")] = int(item.get("count") or 0)

    mp = _build_motor_pipeline_diag(
        "mega",
        open_count=len(open_rows),
        reject_stats=reject_stats,
        queue_len=int(scan.get("motor_queue") or len(motor_signals)),
    )

    summary: dict[str, Any] = {
        "starting_capital": round(anchor, 2) if anchor > 0 else None,
        "session_anchor": round(anchor, 2) if anchor > 0 else None,
        "current_capital": round(equity, 2),
        "exchange_margin_balance": round(margin, 2),
        "exchange_wallet_balance": round(float(wallet.get("total_wallet_balance") or equity), 2),
        "exchange_available_balance": round(avail, 2),
        "available_capital": round(avail, 2),
        "session_pnl": round(session_pnl, 2),
        "total_pnl": round(session_pnl, 2),
        "total_pnl_pct": round(session_pct, 2),
        "realized_pnl": round(session_pnl - unreal, 2),
        "unrealized_pnl": round(unreal, 2),
        "exchange_unrealized_pnl": round(unreal, 2),
        "open_trades": len(open_rows),
        "closed_trades": int(summ.get("closed_trades") or len(closed_rows)),
        "win_rate": summ.get("win_rate"),
        "win_count": None,
    }
    wins = sum(
        1
        for r in closed_rows
        if float(r.get("final_pnl") or r.get("net_pnl") or 0) > 0
    )
    if closed_rows:
        summary["win_count"] = wins
        if summary.get("win_rate") is None:
            summary["win_rate"] = round(wins / len(closed_rows) * 100.0, 1)

    api_base = str(wallet.get("api_base") or "demo-fapi.binance.com")
    return {
        "ts": datetime.utcnow().isoformat() + "Z",
        "panel_api_only": True,
        "live_only": live_only_execution(),
        "display_source": "mega_binance",
        "open_positions_source": "mega_binance",
        "view_mode": active_view_mode(),
        "execution_mode": "mega",
        "execution_label": "MEGA",
        "view_label": "MEGA Canlı API",
        "mode": "MEGA_LIVE",
        "live_orders": True,
        "api_connected": True,
        "exchange_wallet": wallet,
        "exchange_balance": avail,
        "summary": summary,
        "positions": {"open": open_rows, "closed": closed_rows[-100:]},
        "strip_open_positions": open_rows,
        "strip_recent_closed": closed_rows[-12:],
        "signals": [],
        "approaching_signals": [],
        "approaching_reversal_signals": [],
        "mega_scan": scan,
        "scanner_status": {
            "exchange_cache_age_ms": int(
                max(0, (time.time() - float(wallet.get("_ts") or 0)) * 1000)
            )
            if wallet.get("_ts")
            else None,
            "open_position_count": len(open_rows),
            "scanned_recent": scan.get("scanned_recent"),
            "candidates_recent": scan.get("candidates_recent"),
        },
        "elite": {"motor_pipeline": mp},
        "display_note": f"MEGA canlı · {api_base} · anchor ${anchor:,.0f}" if anchor else "MEGA canlı · Binance API",
    }


def _mega_scan_context() -> dict[str, Any]:
    """MEGA panel — berserk2 tarama meta + motor kuyruğu."""
    age = None
    if _last_berserk2_scan_at > 0:
        age = round(time.time() - _last_berserk2_scan_at, 1)
    watching: list[dict[str, Any]] = []
    for ms in motor_signals[-14:]:
        sym = str(ms.get("symbol") or "")
        if not sym:
            continue
        watching.append(
            {
                "symbol": sym,
                "type": str(ms.get("type") or "LONG"),
                "change": round(float(ms.get("change") or 0), 4),
                "strength": str(ms.get("strength") or "Medium"),
                "price": float(ms.get("price") or 0),
                "time": ms.get("time") or "",
                "ui_label": "Motor kuyruk",
            }
        )
    vol_block: dict[str, Any] = {}
    try:
        from elite_trader.mega_volatility import snapshot as vol_snapshot

        vol_block = vol_snapshot()
    except Exception:
        pass
    return {
        "last_scan_age_sec": age,
        "last_scan_ms": round(last_scan_ms, 1),
        "eval_last_n": _last_motor_eval_n,
        "candidates_last_n": _last_motor_candidates_n,
        "motor_queue": len(motor_signals),
        "watchlist_size": len(watchlist),
        "watching": watching,
        "volatility": vol_block,
    }


@app.get("/api/paper/{mode_id}/snapshot")
def api_paper_mode_snapshot(mode_id: str, light: int = 0):
    """Paper mod kitabı — açık/kapalı + özet (canlı motor değil)."""
    from elite_trader.mode_registry import enabled_mode_ids, resolve_mode_id

    mid = resolve_mode_id(mode_id)
    if mid not in enabled_mode_ids():
        return {"ok": False, "error": "mode not enabled"}
    light_snap = bool(int(light or 0))
    try:
        if mid == "mega":
            from elite_trader.mega_live import mega_motor_active, snapshot as mega_snap

            if mega_motor_active():
                from elite_trader.mega_live import (
                    mega_live_enabled,
                    mega_sim_enabled,
                    snapshot as mega_snap,
                )

                snap = mega_snap(light=light_snap)
                book = parallel_engine.get_universe_book(mid)
                open_ui = list(snap.get("open") or [])
                if not open_ui:
                    open_ui = _enrich_paper_positions_for_ui(
                        list(book.get("open") or []), mid
                    )
                closed_ui = list(snap.get("closed") or [])
                book_closed = list(book.get("closed") or [])
                if mega_sim_enabled() and not mega_live_enabled():
                    if book_closed:
                        closed_ui = book_closed[-100:]
                    if not open_ui:
                        open_ui = _enrich_paper_positions_for_ui(
                            list(book.get("open") or []), mid
                        )
                    summ = dict(snap.get("summary") or {})
                    ps = parallel_engine.build_summary(mid)
                    summ.update(
                        {
                            k: ps[k]
                            for k in (
                                "starting_capital",
                                "current_capital",
                                "available_capital",
                                "session_available_est",
                                "realized_pnl",
                                "unrealized_pnl",
                                "total_pnl",
                                "total_pnl_pct",
                                "open_trades",
                                "closed_trades",
                                "win_rate",
                                "win_count",
                            )
                            if k in ps
                        }
                    )
                    summ["source"] = "paper_book"
                    snap["summary"] = summ
                scan = dict(snap.get("scan") or {})
                scan.update(_mega_scan_context())
                scan["max_open"] = execution_max_open()
                scan.setdefault("motor_queue", len(motor_signals))
                is_live = mega_live_enabled()
                return {
                    "ok": True,
                    "ts": datetime.utcnow().isoformat() + "Z",
                    "mode_id": mid,
                    "live": is_live,
                    "paper_sim": mega_sim_enabled() and not is_live,
                    "light": light_snap,
                    "summary": snap.get("summary") or {},
                    "wallet": snap.get("wallet") or {},
                    "scan": scan,
                    "open": open_ui,
                    "closed": closed_ui[-100:],
                }
        book = parallel_engine.get_universe_book(mid)
        summ = parallel_engine.build_summary(mid)
        open_ui = _enrich_paper_positions_for_ui(list(book.get("open") or []), mid)
        closed = list(book.get("closed") or [])[-100:]
        return {
            "ok": True,
            "ts": datetime.utcnow().isoformat() + "Z",
            "mode_id": mid,
            "summary": summ,
            "open": open_ui,
            "closed": closed,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/live")
async def api_live(light: Optional[str] = None):
    """Panel poll — API-only modda doğrudan positionRisk; aksi halde snapshot önbellek."""
    force_full = str(light or "").strip().lower() in ("0", "false", "full")
    loop = asyncio.get_running_loop()
    timeout = (
        max(2.5, _effective_position_timeout_sec() + 0.35)
        if _panel_uses_exchange_snapshot() and not force_full
        else 4.0
    )
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                _api_heavy_executor_get(),
                lambda: _api_live_payload(force_full=force_full),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        if _panel_uses_exchange_snapshot() and _last_ws_snapshot:
            return dict(_last_ws_snapshot)
        if _last_ws_snapshot:
            stale = dict(_last_ws_snapshot)
            note = str(stale.get("display_note") or "")
            if "snapshot gecikmesi" not in note:
                stale["display_note"] = (note + " · snapshot gecikmesi (önbellek)").strip(" ·")
            return stale
        return _minimal_live_snapshot("Snapshot gecikmesi — iskelet veri")


def _minimal_live_snapshot(note: str = "Panel yükleniyor") -> dict[str, Any]:
    """/api/live timeout yedek — boş ekran yerine iskelet snapshot."""
    mega_panel = _panel_snap_from_mega_live(light=True)
    if mega_panel is not None:
        snap = dict(mega_panel)
        snap["display_note"] = note
        return snap
    exec_mid = active_execution_mode()
    view = active_view_mode()
    start = _motor_session_start()
    cap = get_current_capital()
    unreal = sum(float(p.get("unrealized_pnl") or 0) for p in positions)
    return {
        "ts": datetime.utcnow().isoformat() + "Z",
        "live_only": live_only_execution(),
        "display_source": "binance" if LIVE_ORDERS and is_live_binance_motor(exec_mid) else "live",
        "open_positions_source": (
            "binance" if LIVE_ORDERS and not client.paper else "live_reference"
        ),
        "view_mode": view,
        "execution_mode": exec_mid,
        "summary": {
            "open_trades": len(positions),
            "closed_trades": len(closed_positions),
            "starting_capital": start,
            "current_capital": cap,
            "session_pnl": round(cap - start, 2) if start > 0 else 0,
            "total_pnl": round(cap - start, 2) if start > 0 else 0,
            "unrealized_pnl": unreal,
        },
        "positions": {"open": list(positions), "closed": list(closed_positions)[-50:]},
        "signals": signals[-20:],
        "approaching_signals": [],
        "approaching_reversal_signals": list(_reversal_watch_cache[:16]),
        "scanner_status": _scanner_status_dict(),
        "display_note": note,
    }


def _attach_closed_to_panel_snap(
    snap: dict[str, Any], closed_ui: list[dict[str, Any]]
) -> dict[str, Any]:
    """Kapalı işlem tablosu — API-only poll her tur DB/RAM birleşimini taşır."""
    sm = dict(snap.get("summary") or {})
    keep_keys = (
        "session_pnl",
        "session_pnl_pct",
        "session_anchor",
        "total_pnl",
        "total_pnl_pct",
        "current_capital",
        "exchange_margin_balance",
        "exchange_wallet_balance",
        "exchange_available_balance",
        "available_capital",
        "unrealized_pnl",
        "exchange_unrealized_pnl",
        "open_trades",
    )
    preserved = {k: sm[k] for k in keep_keys if k in sm}
    closed_fields = _session_pnl_summary_fields(closed_ui)
    for k, v in closed_fields.items():
        if k in preserved:
            continue
        sm[k] = v
    sm.update(preserved)
    if preserved.get("session_pnl") is not None:
        sm["realized_pnl"] = closed_fields.get("realized_pnl", sm.get("realized_pnl"))
    snap["summary"] = sm
    pos = snap.get("positions") or {}
    snap["positions"] = {"open": list(pos.get("open") or []), "closed": closed_ui}
    snap["strip_recent_closed"] = closed_ui[:12]
    return snap


def _snapshot_for_live_poll(*, force_full: bool = False) -> dict[str, Any]:
    """Panel /api/live — API-only veya hafif snapshot yolu."""
    if _panel_uses_exchange_snapshot() and not force_full:
        poll_iv = _effective_position_poll_interval_sec()
        cache_age = (time.time() - _exchange_cache_ts) if _exchange_cache_ts else 9999.0
        closed_ui = _closed_positions_for_ui()[-200:]
        if _last_ws_snapshot and cache_age < poll_iv * 1.5:
            snap = _clone_snapshot_for_live_refresh(_last_ws_snapshot)
            snap["ts"] = datetime.utcnow().isoformat() + "Z"
            ss = dict(snap.get("scanner_status") or {})
            ss["exchange_cache_age_ms"] = int(cache_age * 1000)
            snap["scanner_status"] = ss
            return _attach_closed_to_panel_snap(snap, closed_ui)
        snap = _build_api_only_panel_snapshot(force_positions=False)
        return _attach_closed_to_panel_snap(snap, closed_ui)
    if force_full:
        return get_snapshot(light=False)
    if _last_ws_snapshot:
        snap = _clone_snapshot_for_live_refresh(_last_ws_snapshot)
        if LIVE_ORDERS and not client.paper:
            _refresh_binance_snapshot_positions(snap, light=True)
        snap["ts"] = datetime.utcnow().isoformat() + "Z"
        return snap
    return get_snapshot(light=True)


def _api_live_payload(*, force_full: bool = False) -> dict[str, Any]:
    try:
        return _snapshot_for_live_poll(force_full=force_full)
    except Exception:
        if _last_ws_snapshot:
            snap = _clone_snapshot_for_live_refresh(_last_ws_snapshot)
            if LIVE_ORDERS and not client.paper:
                try:
                    _refresh_binance_snapshot_positions(snap, light=True)
                except Exception:
                    pass
            return snap
        return _minimal_live_snapshot("Snapshot hatası — iskelet veri")


@app.get("/api/closed")
async def api_closed():
    """Kapalı pozisyonlar — DB + RAM (basitleştirilmiş)."""
    def _get_closed():
        try:
            # Önce RAM'den al
            closed = list(closed_positions)
            
            # DB'den de ekle (duplikasyon kontrolü ile)
            if _elite_state_enabled():
                try:
                    from elite_pro_state import load_closed
                    db_closed = list(load_closed())
                    seen_ids = {c.get("id") for c in closed}
                    for c in db_closed:
                        if c.get("id") not in seen_ids:
                            closed.append(c)
                            seen_ids.add(c.get("id"))
                except Exception:
                    pass
            
            # Sort by exit time
            closed_sorted = sorted(
                closed,
                key=lambda c: c.get("exit_time") or c.get("closed_at_iso") or c.get("exit_time_str") or "",
                reverse=True
            )
            return {"ok": True, "closed_trades": closed_sorted, "count": len(closed_sorted)}
        except Exception as e:
            return {"ok": False, "error": str(e), "closed_trades": []}
    
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_api_heavy_executor_get(), _get_closed)


@app.post("/api/closed/delete")
def api_closed_delete(body: dict = Body(default_factory=dict)):
    """Panel — tek kapanmış işlem satırını sil (arşiv + KPI yenileme)."""
    try:
        trade_id = int(body.get("id") or body.get("trade_id") or 0)
    except (TypeError, ValueError):
        trade_id = 0
    symbol = str(body.get("symbol") or "").strip() or None
    exit_time = str(body.get("exit_time") or "").strip() or None
    reason = str(body.get("reason") or "panel_row_delete").strip()
    result = delete_closed_trade(
        trade_id, symbol=symbol, exit_time=exit_time, reason=reason
    )
    if not result.get("ok"):
        return result
    snap = get_snapshot()
    return {
        **result,
        "snapshot": snap,
        "closed_count": len(_closed_positions_for_ui()),
    }


@app.get("/api/debug/signals")
def api_debug_signals():
    """Sinyal üretim tanılama — geçici debug endpoint."""
    from elite_trader.signal_paths import build_raw_momentum_candidate
    sample = {}
    for sym in ["AIUSDT", "BROCCOLIF3BUSDT", "BTCUSDT", "ETHUSDT"]:
        hist = price_history.get(sym) or []
        candidate = None
        reject = None
        if len(hist) > 20:
            price = float(hist[-1]["price"])
            candidate = build_raw_momentum_candidate(sym, price, price_history)
            if candidate:
                from elite_trader.parallel_universe_engine import entry_gate_for_mode
                ok, reason = entry_gate_for_mode("evrim", candidate)
                reject = reason if not ok else None
        sample[sym] = {
            "hist_len": len(hist),
            "latest_price": float(hist[-1]["price"]) if hist else None,
            "price_20ago": float(hist[-20]["price"]) if len(hist) > 20 else None,
            "candidate": candidate,
            "motor_accepted": candidate is not None and reject is None,
            "motor_reject": reject,
        }
    return {
        "price_history_total": len(price_history),
        "motor_signals_len": len(motor_signals),
        "motor_reject_stats": dict(_motor_reject_stats),
        "sample": sample,
    }


@app.post("/api/close-all")
def close_all_positions(save: bool = True):
    """Tüm açık pozisyonları kapat. save=false → borsa kapanır, DB'ye yazılmaz."""
    result = close_all_exchange_positions(save=bool(save))
    return {
        "closed": result.get("exchange_closed", 0),
        "local_cleared": result.get("local_cleared", 0),
        "local_saved": result.get("local_saved"),
        "saved": bool(save),
        "errors": result.get("errors") or [],
        "message": (
            f"Closed {result.get('exchange_closed', 0)} exchange positions "
            f"({'saved' if save else 'no save'})"
        ),
    }


@app.post("/api/settings/restart")
def settings_restart():
    """Bot yeniden başlat (port-aware: 9005 / 9006 / 9007)."""
    try:
        info = restart_live_bot()
        if not info.get("restarted"):
            return {
                "ok": False,
                "error": info.get("stderr_tail") or "restart failed",
                "restart": info,
            }
        return {"ok": True, "restart": info, "message": info.get("message") or f"PID {info.get('pid')}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/health/strip")
def api_health_strip():
    from elite_trader.health_strip import health_strip_payload

    return health_strip_payload()


@app.get("/api/panel/mode")
def panel_mode_get():
    return {"ok": True, "panel_strategy": panel_strategy_snapshot()}


@app.get("/api/modes")
def api_modes_list():
    from elite_trader.mode_registry import MODE_META, MODE_IDS

    ps = panel_strategy_snapshot()
    active = active_futures_mode()
    modes = []
    for mid in MODE_IDS:
        meta = dict(MODE_META.get(mid) or {})
        prof = mode_catalog().get(mid) or {}
        modes.append(
            {
                "id": mid,
                "display_name": meta.get("display_name", mid),
                "role": meta.get("role"),
                "paper": mid != active or not (LIVE_ORDERS and not client.paper),
                "is_active_futures": mid == active,
                "can_trade_live": meta.get("can_trade_live"),
                "learning_access": meta.get("learning_access"),
                "profile_summary": {
                    "max_open": prof.get("max_open"),
                    "scan_interval_sec": prof.get("scan_interval_sec"),
                    "min_edge": prof.get("min_edge"),
                },
            }
        )
    return {
        "ok": True,
        "modes": modes,
        "active_futures_mode": active,
        "panel_strategy": ps,
    }


@app.get("/api/motor-gate/status")
def api_motor_gate_status():
    from elite_trader.order_gate import get_routing_status

    status = get_routing_status(active_futures_mode())
    try:
        from elite_trader.data_lake.ingest import summary_for_ui

        status["modes_metrics"] = summary_for_ui()
    except Exception:
        status["modes_metrics"] = {}
    return {"ok": True, **status}


@app.get("/api/ticker-prices")
async def api_ticker_prices():
    """Ticker şeridi — canlıda REST mark; paper'da önbellek."""
    if LIVE_ORDERS and not client.paper:
        return {"ok": True, "prices": _watchlist_prices_rest_api(), "source": "binance_rest"}
    if _ticker_prices_cache:
        return {"ok": True, "prices": _ticker_prices_cache}
    return {"ok": True, "prices": _watchlist_prices_subset()}


def _connection_live_payload() -> dict[str, Any]:
    """Sync bağlantı özeti — sınırlı thread pool üzerinden çağrılır."""
    now_ms = int(time.time() * 1000)
    api_ok = _api_healthy()
    api_paper = client.paper
    auth_error = client._auth_error
    active_client = client
    mega_mc = _mega_api_client()
    if mega_mc and _is_mega_primary_process():
        active_client = mega_mc
        api_paper = mega_mc.paper
        auth_error = mega_mc._auth_error
    try:
        from elite_trader.connection_alerts import _endpoint_label

        api_label = _endpoint_label(active_client)
    except Exception:
        api_label = "fapi.binance.com"

    open_count = len(positions)
    if _is_mega_primary_process():
        try:
            from elite_trader.mega_live import mega_open_coins

            open_count = len(mega_open_coins())
        except Exception:
            pass

    ff_lag = None
    ff_coins = 0
    ff_ok = False
    try:
        from binance_futures_trader.fast_price_ws import fast_feed_status

        ffs = fast_feed_status()
        ff_ok = ffs.get("connected", False)
        ff_lag = ffs.get("lag_ms")
        ff_coins = ffs.get("coins", 0)
    except Exception:
        pass

    ws_lag = None
    ws_source = "none"
    ws_coins = 0
    ws_health = "disconnected"
    rest_coins = 0
    try:
        from binance_futures_trader.mark_ws import feed_status as mfs

        ms = mfs()
        ws_lag = ms.get("lag_ms")
        ws_source = ms.get("source", "none")
        ws_coins = ms.get("coins", 0)
        ws_health = ms.get("health", "disconnected")
    except Exception:
        pass
    with _price_cache_lock:
        rest_coins = len(_price_cache)

    rest_age_ms = int((time.time() - _price_cache_ts) * 1000) if _price_cache_ts else None

    async_hub: dict[str, Any] = {"enabled": _async_hub_enabled()}
    coingecko: dict[str, Any] = {"ok": False}
    coinmarketcap: dict[str, Any] = {"ok": False}
    if _async_hub_enabled():
        try:
            from binance_futures_trader.async_hub import get_orchestrator

            orch = get_orchestrator()
            if orch:
                async_hub = orch.status()
                ext = async_hub.get("external_intel") or {}
                coingecko = ext.get("coingecko") or coingecko
                coinmarketcap = ext.get("coinmarketcap") or coinmarketcap
        except Exception:
            pass

    return {
        "ok": True,
        "ts_ms": now_ms,
        "api_ok": api_ok,
        "api_paper": api_paper,
        "api_label": api_label,
        "auth_error": auth_error,
        "async_hub": async_hub,
        "coingecko": coingecko,
        "coinmarketcap": coinmarketcap,
        "bookticker": {"ok": ff_ok, "lag_ms": ff_lag, "coins": ff_coins},
        "mark_ws": {
            "health": ws_health,
            "source": ws_source,
            "lag_ms": ws_lag,
            "coins": ws_coins,
        },
        "rest": {"coins": rest_coins, "age_ms": rest_age_ms},
        "open_positions": open_count,
    }


@app.get("/api/connection/live")
async def api_connection_live():
    """Anlık bağlantı — bounded executor (thread patlamasını önler)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _api_heavy_executor_get(), _connection_live_payload
    )


@app.get("/api/connection/alerts")
async def api_connection_alerts():
    """Bağlantı uyarıları — panel banner (5s poll)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _api_heavy_executor_get(), _connection_alerts_payload
    )


def _connection_alerts_payload() -> dict[str, Any]:
    live = _connection_live_payload()
    active = client
    if _is_mega_primary_process():
        mc = _mega_api_client()
        if mc:
            active = mc
    try:
        from elite_trader.connection_alerts import build_alerts

        return build_alerts(
            api_ok=bool(live.get("api_ok")),
            api_paper=bool(live.get("api_paper")),
            auth_error=live.get("auth_error"),
            client=active,
            open_positions=int(live.get("open_positions") or 0),
        )
    except Exception as exc:
        return {"ok": False, "severity": "critical", "alerts": [], "error": str(exc)}


@app.get("/api/heartbeat")
def api_heartbeat():
    """Canlı süreç heartbeat — pozisyon döngüsü + fiyat beslemesi."""
    return {"ok": True, **_heartbeat_payload()}


def _monitor_snapshot_payload() -> dict[str, Any]:
    """Hafif terminal izleyici — ağır get_snapshot/thread pool yok."""
    mega_panel = _panel_snap_from_mega_live(light=True)
    if mega_panel is not None:
        summ = dict(mega_panel.get("summary") or {})
        mp = (mega_panel.get("elite") or {}).get("motor_pipeline") or {}
        scan = mega_panel.get("mega_scan") or {}
        hb = _heartbeat_payload()
        return {
            "ok": True,
            "ts": mega_panel.get("ts") or datetime.utcnow().isoformat() + "Z",
            "api_connected": True,
            "live_only": live_only_execution(),
            "exchange_balance": summ.get("exchange_available_balance"),
            "summary": {
                "open_positions": summ.get("open_trades", 0),
                "max_open": execution_max_open(),
                "closed_trades": summ.get("closed_trades", 0),
                "starting_capital": summ.get("starting_capital"),
                "session_anchor": summ.get("session_anchor"),
                "current_capital": summ.get("current_capital"),
                "session_pnl": summ.get("session_pnl"),
                "unrealized_pnl": summ.get("unrealized_pnl"),
            },
            "positions": mega_panel.get("positions") or {"open": [], "closed": []},
            "events": list(_monitor_events)[:24],
            "read_speed": {"mega_panel": True},
            "elite": mega_panel.get("elite") or {},
            "heartbeat": hb,
            "motor": {
                "queue": mp.get("queue_len") or scan.get("motor_queue") or 0,
                "orders_opened": mp.get("orders_opened") or _motor_orders_opened,
                "queue_added": mp.get("queue_added") or _motor_queue_added,
                "reject_stats": mp.get("reject_stats") or {},
                "execution_mode": "mega",
                "max_open": mp.get("max_open") or execution_max_open(),
                "reject_top_txt": mp.get("reject_top_txt") or "",
            },
            "mega_scan": scan,
        }

    t_build = time.perf_counter()
    exec_mid = active_execution_mode()
    live_orders = LIVE_ORDERS and not client.paper
    exch_positions = list(_positions_cache or [])
    exch_wallet = _wallet_cache if live_orders and _wallet_cache else None

    open_ui: list[dict[str, Any]] = []
    if live_orders and exch_positions:
        from elite_trader.exchange_open_display import build_open_positions_for_ui

        open_ui = build_open_positions_for_ui(
            positions, exch_positions, client, allow_chart_fetch=False, enrich_fill=False
        )
    elif positions:
        open_ui = list(positions)

    now_ts = time.time()
    for p in open_ui:
        et = float(p.get("entry_time") or 0)
        if et > 0 and not p.get("duration_sec"):
            p["duration_sec"] = max(0.0, now_ts - et)
        upd_ms = p.get("exchange_update_ms")
        if upd_ms:
            try:
                p["exchange_data_age_ms"] = max(
                    0, int(now_ts * 1000) - int(upd_ms)
                )
            except (TypeError, ValueError):
                pass

    closed_recent = _closed_positions_for_ui()[:12]
    hb = _heartbeat_payload()
    ex_bal = None
    if exch_wallet:
        ex_bal = float(
            exch_wallet.get("available_balance")
            or exch_wallet.get("total_wallet_balance")
            or 0
        )

    motor_rejects: dict[str, int] = {}
    try:
        motor_rejects = dict(_motor_reject_stats)
    except Exception:
        pass

    pf = hb.get("price_feed") or {}
    mw = pf.get("mark_ws") or {}
    ff = pf.get("fast_feed") or {}
    has_open = len(open_ui) > 0
    pos_ago = hb.get("position_ago")
    cache_age_ms = (
        int((now_ts - _exchange_cache_ts) * 1000) if _exchange_cache_ts else None
    )
    read_speed = {
        "snapshot_build_ms": round((time.perf_counter() - t_build) * 1000.0, 2),
        "bot_position_tick_ms": hb.get("position_tick_ms"),
        "bot_position_interval_ms": hb.get("position_interval_ms"),
        "bot_position_ago_ms": int(float(pos_ago) * 1000) if pos_ago is not None else None,
        "exchange_cache_age_ms": cache_age_ms,
        "exchange_position_poll_ms": hb.get("exchange_poll_ms"),
        "exchange_poll_timeouts": hb.get("exchange_poll_timeouts"),
        "exchange_refresh_ms": round(
            (_effective_position_poll_interval_sec() if has_open else _exchange_cache_ttl_sec())
            * 1000.0,
            0,
        ),
        "mark_ws_lag_ms": mw.get("lag_ms"),
        "book_lag_ms": ff.get("lag_ms"),
        "price_max_age_ms": round(_position_price_max_age_ms(), 0),
        "positions_open": len(open_ui),
        "position_missing_prices": hb.get("position_missing"),
    }

    return {
        "ok": True,
        "ts": datetime.utcnow().isoformat() + "Z",
        "api_connected": live_orders and not client._auth_error,
        "live_only": live_only_execution(),
        "exchange_balance": ex_bal,
        "summary": {
            "open_positions": len(open_ui),
            "max_open": execution_max_open(),
            "closed_trades": len(closed_positions),
            "starting_capital": _motor_session_start(),
            "current_capital": get_current_capital(),
        },
        "positions": {"open": open_ui, "closed": closed_recent},
        "events": list(_monitor_events)[:24],
        "read_speed": read_speed,
        "elite": {
            "last_position_update_latency_ms": last_position_price_ms
            or last_avg_latency_ms,
        },
        "heartbeat": hb,
        "motor": {
            "queue": len(motor_signals),
            "orders_opened": _motor_orders_opened,
            "queue_added": _motor_queue_added,
            "reject_stats": motor_rejects,
            "execution_mode": exec_mid,
            "max_open": execution_max_open(),
            "reject_top_txt": _build_motor_pipeline_diag(
                exec_mid, open_count=len(open_ui), reject_stats=motor_rejects
            ).get("reject_top_txt", ""),
        },
    }


@app.get("/api/monitor/snapshot")
def api_monitor_snapshot():
    """position_monitor.py — hızlı snapshot (<500ms hedef)."""
    return _monitor_snapshot_payload()


@app.get("/api/position-monitor")
def api_position_monitor():
    """Scalp pozisyon izleme — bellek içi fiyat yaşı + heartbeat."""
    hb = _heartbeat_payload()
    positions_live: list[dict[str, Any]] = []
    try:
        positions_live = parallel_engine.open_positions_monitor()
    except Exception:
        pass
    ages = [p["price_age_ms"] for p in positions_live if p.get("price_age_ms") is not None]
    summary = {
        "open_count": len(positions_live),
        "price_age_ms_min": min(ages) if ages else None,
        "price_age_ms_max": max(ages) if ages else None,
        "price_age_ms_avg": round(sum(ages) / len(ages), 1) if ages else None,
        "missing_prices": hb.get("position_missing", 0),
    }
    return {
        "ok": True,
        "source": "memory",
        "note": "Fiyat yaşları bellek içi; parallel_universes.json diski her tick yazılmaz.",
        "heartbeat": hb,
        "summary": summary,
        "positions": positions_live,
        "config": {
            "position_check_ms": hb.get("position_interval_ms"),
            "position_price_max_age_ms": _position_price_max_age_ms(),
            "position_exit_every_n": _position_exit_every_n(),
        },
    }


@app.get("/api/price-feed/status")
def api_price_feed_status():
    """Mark WS + REST fiyat beslemesi sağlık durumu."""
    try:
        from binance_futures_trader.mark_ws import feed_status, get_mark_prices
        ws = feed_status()
        prices = get_mark_prices()
        sample = {k: v for k, v in list(prices.items())[:5]}
    except Exception as e:
        ws = {"error": str(e)}
        sample = {}
    # Fast feed (bookTicker) durumu
    fast_status: dict = {}
    try:
        from binance_futures_trader.fast_price_ws import fast_feed_status, get_all_fast_prices
        fast_status = fast_feed_status()
        fast_prices = {k: round(v["mid"], 6) for k, v in list(get_all_fast_prices().items())[:5]}
    except Exception as ex:
        fast_status = {"error": str(ex)}
        fast_prices = {}

    rest_prices: dict = {}
    try:
        rest_prices = {k: v for k, v in list(client._last_prices.items())[:5]}
    except Exception:
        pass
    return {
        "ok": True,
        "mark_ws": ws,
        "ws_price_count": ws.get("coins", 0),
        "ws_health": ws.get("health", "unknown"),
        "ws_reconnects": ws.get("reconnects", 0),
        "ws_lag_ms": ws.get("lag_ms"),
        "ws_url": ws.get("url", ""),
        "fast_feed": fast_status,
        "fast_feed_connected": fast_status.get("connected", False),
        "fast_feed_lag_ms": fast_status.get("lag_ms"),
        "fast_feed_coins": fast_status.get("coins", 0),
        "fast_feed_sample": fast_prices,
        "sample_prices": sample,
        "rest_cache_count": len(client._last_prices),
        "rest_cache_sample": rest_prices,
    }


@app.post("/api/price-feed/reconnect")
def api_price_feed_reconnect():
    """Mark WS + bookTicker bağlantısını zorla yeniden başlat."""
    try:
        from binance_futures_trader.mark_ws import force_reconnect, ensure_mark_feed_started
        from binance_futures_trader.fast_price_ws import (
            force_reconnect as fast_force_reconnect,
            ensure_fast_feed_started,
        )

        force_reconnect()
        ensure_mark_feed_started()
        fast_force_reconnect()
        ensure_fast_feed_started(_fast_feed_coin_list())
        return {"ok": True, "message": "Mark WS + bookTicker yeniden bağlanma tetiklendi"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/status")
def api_system_status():
    from elite_trader.futures_order_router import is_safe_mode_active

    prof = execution_profile()
    # WS sağlık durumu
    ws_health = "unknown"
    ws_reconnects = 0
    try:
        from binance_futures_trader.mark_ws import feed_status
        fs = feed_status()
        ws_health = fs.get("health", "unknown")
        ws_reconnects = fs.get("reconnects", 0)
    except Exception:
        pass
    return {
        "ok": True,
        "active_futures_mode": active_futures_mode(),
        "execution_mode": active_execution_mode(),
        "view_mode": active_view_mode(),
        "safe_mode": is_safe_mode_active(),
        "live_orders": LIVE_ORDERS and not client.paper,
        "api_healthy": _api_healthy(),
        "api_connected": LIVE_ORDERS and not client.paper and not client._auth_error,
        "scan_interval_sec": prof.get("scan_interval_sec"),
        "auth_error": client._auth_error,
        "ws_health": ws_health,
        "ws_reconnects": ws_reconnects,
    }


@app.get("/api/modes/{mode_id}/settings")
def api_mode_settings(mode_id: str):
    from elite_trader.mode_registry import resolve_mode_id

    mid = resolve_mode_id(mode_id)
    prof = mode_catalog().get(mid)
    if not prof:
        return {"ok": False, "error": "unknown mode"}
    return {"ok": True, "mode_id": mid, "settings": prof}


@app.get("/api/modes/{mode_id}/decisions")
def api_mode_decisions(mode_id: str, limit: int = 100):
    from elite_trader.data_lake.ingest import query_decisions
    from elite_trader.mode_registry import resolve_mode_id

    mid = resolve_mode_id(mode_id)
    try:
        rows = query_decisions(mid, reader_id="evrim", limit=min(limit, 500))
    except PermissionError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "mode_id": mid, "decisions": rows}


@app.get("/api/modes/{mode_id}/metrics")
def api_mode_metrics(mode_id: str):
    from elite_trader.data_lake.ingest import query_metrics, summary_for_ui
    from elite_trader.mode_registry import resolve_mode_id

    mid = resolve_mode_id(mode_id)
    try:
        hist = query_metrics(mid, reader_id="evrim", limit=5)
        rollup = (summary_for_ui() or {}).get(mid) or {}
    except PermissionError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "mode_id": mid, "rollup": rollup, "history": hist}


@app.get("/api/modes/{mode_id}/decision-log")
def api_mode_decision_log(mode_id: str, limit: int = 100, only_rejects: bool = False):
    """MD 32 zorunlu log alanı: decision_log tablosu."""
    from elite_trader.data_lake.ingest import query_decision_log
    from elite_trader.mode_registry import resolve_mode_id

    mid = resolve_mode_id(mode_id)
    try:
        rows = query_decision_log(
            mid, reader_id="evrim", limit=min(limit, 1000), only_rejects=only_rejects
        )
    except PermissionError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "mode_id": mid, "rows": rows}


@app.get("/api/modes/{mode_id}/rejects")
def api_mode_rejects(mode_id: str):
    from elite_trader.mode_registry import resolve_mode_id
    from elite_trader.mode_reject_buffer import summary as reject_buffer_summary

    mid = resolve_mode_id(mode_id)
    try:
        buf = reject_buffer_summary(mid)
        from elite_trader.data_lake.ingest import reject_summary

        lake = reject_summary(mid, reader_id="evrim")
    except PermissionError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "mode_id": mid,
        "rejects": buf.get("top_reject_reasons") or lake,
        "reject_buffer": buf,
    }


@app.get("/api/evrim/live-decisions")
def api_evrim_live_decisions():
    try:
        from elite_trader.evrim_live_decisions import get_panel

        return {"ok": True, **get_panel()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/modes/{mode_id}/route-distribution")
def api_mode_route_distribution(mode_id: str):
    from elite_trader.data_lake.ingest import route_distribution
    from elite_trader.mode_registry import resolve_mode_id

    mid = resolve_mode_id(mode_id)
    try:
        dist = route_distribution(mid, reader_id="evrim")
    except PermissionError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "mode_id": mid, "distribution": dist}


@app.get("/api/modes/{mode_id}/learning-count")
def api_mode_learning_count(mode_id: str):
    from elite_trader.data_lake.ingest import learning_record_count
    from elite_trader.mode_registry import resolve_mode_id

    mid = resolve_mode_id(mode_id)
    try:
        n = learning_record_count(mid, reader_id="evrim")
    except PermissionError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "mode_id": mid, "learning_records": n}


@app.get("/api/modes/overview")
def api_modes_overview():
    """Aşama 1 MD dashboard: her mod için trade sayısı, paper/live PnL, fee/gross, red sebepleri, route dağılımı."""
    global _modes_overview_cache, _modes_overview_cache_ts
    now = time.time()
    if (
        _modes_overview_cache is not None
        and (now - _modes_overview_cache_ts) < _MODES_OVERVIEW_TTL_SEC
    ):
        return _modes_overview_cache

    from elite_trader.data_lake.ingest import (
        learning_record_count,
        reject_summary,
        route_distribution,
        summary_for_ui,
    )
    from elite_trader.data_lake.db import get_conn
    from elite_trader.mode_registry import MODE_META, enabled_mode_ids
    from elite_trader.order_gate import get_routing_status
    from elite_trader.panel_strategy import is_live_binance_motor

    routing = get_routing_status(active_futures_mode())
    try:
        rollup = summary_for_ui() or {}
    except Exception:
        rollup = {}
    conn = get_conn()
    out: dict[str, Any] = {}
    for mid in enabled_mode_ids():
        meta = MODE_META.get(mid) or {}
        try:
            paper_row = conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(pnl_usd),0) pnl FROM paper_trades "
                "WHERE mode_id = ? AND ts_close IS NOT NULL",
                (mid,),
            ).fetchone()
            live_row = conn.execute(
                "SELECT COUNT(*) n, COALESCE(SUM(pnl_usd),0) pnl FROM live_trades "
                "WHERE mode_id = ? AND ts_close IS NOT NULL",
                (mid,),
            ).fetchone()
        except Exception:
            paper_row = {"n": 0, "pnl": 0.0}
            live_row = {"n": 0, "pnl": 0.0}
        try:
            rejects = reject_summary(mid, reader_id="evrim")
        except Exception:
            rejects = []
        try:
            dist = route_distribution(mid, reader_id="evrim")
        except Exception:
            dist = {}
        learn_n = 0
        r = rollup.get(mid) or {}
        out[mid] = {
            "mode_id": mid,
            "mode_name": str(meta.get("display_name") or mid.upper()),
            "is_live": bool(is_live_binance_motor(mid)),
            "is_execution_mode": mid == routing.get("active_futures_mode"),
            "paper_trades": int(paper_row["n"] or 0),
            "paper_pnl_usd": float(paper_row["pnl"] or 0.0),
            "live_trades": int(live_row["n"] or 0),
            "live_pnl_usd": float(live_row["pnl"] or 0.0),
            "fee_gross_ratio": r.get("fee_gross_ratio"),
            "profit_factor": r.get("profit_factor"),
            "win_rate": r.get("win_rate"),
            "decisions": r.get("decisions"),
            "top_rejects": rejects,
            "route_distribution": dist,
            "learning_records": learn_n,
        }
    payload = {
        "ok": True,
        "active_futures_mode": routing.get("active_futures_mode"),
        "live_mode_name": routing.get("live_mode_name"),
        "paper_mode_names": routing.get("paper_mode_names"),
        "recent_routes": routing.get("recent_routes") or [],
        "modes": out,
    }
    _modes_overview_cache = payload
    _modes_overview_cache_ts = time.time()
    return payload


def _elite_process_log_path() -> Path:
    custom = os.getenv("ELITE_PROCESS_LOG", "").strip()
    if custom:
        p = Path(custom)
        return p if p.is_absolute() else (_ROOT / p)
    port = str(os.getenv("BINANCE_ELITE_PORT", "")).strip()
    if port == "9006":
        return _ROOT / "logs" / "binance_elite_mega_9006.log"
    if port == "9007":
        return _ROOT / "logs" / "binance_elite_mega_9007.log"
    if port == "9005":
        return _ROOT / "logs" / "binance_elite_8300_9005.log"
    return _ROOT / "logs" / "binance_elite.log"


def _tail_process_log_lines(
    path: Path, n: int, max_read: int = 512_000
) -> tuple[list[str], int]:
    size = path.stat().st_size
    if size <= 0:
        return [], 0
    read_from = max(0, size - max_read)
    with open(path, "rb") as f:
        f.seek(read_from)
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if read_from > 0 and lines:
        lines = lines[1:]
    return lines[-max(1, min(n, 500)) :], size


def _read_process_log_chunk(
    path: Path,
    *,
    offset: int = 0,
    tail: int = 0,
    max_bytes: int = 65536,
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "ok": False,
            "error": "log not found",
            "path": path.name,
            "offset": 0,
            "size": 0,
            "lines": [],
        }
    size = path.stat().st_size
    if tail > 0 and offset <= 0:
        lines, size = _tail_process_log_lines(path, min(tail, 500))
        return {
            "ok": True,
            "path": path.name,
            "offset": size,
            "size": size,
            "lines": lines,
            "truncated": False,
            "mode": "tail",
        }
    if offset < 0:
        offset = 0
    if offset > size:
        lines, size = _tail_process_log_lines(path, 120)
        return {
            "ok": True,
            "path": path.name,
            "offset": size,
            "size": size,
            "lines": lines,
            "truncated": False,
            "reset": True,
            "mode": "reset",
        }
    cap = max(4096, min(max_bytes, 262144))
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(cap)
    new_offset = offset + len(chunk)
    lines: list[str] = []
    if chunk:
        if not chunk.endswith(b"\n") and new_offset < size:
            last_nl = chunk.rfind(b"\n")
            if last_nl >= 0:
                chunk = chunk[: last_nl + 1]
                new_offset = offset + len(chunk)
            else:
                new_offset = offset
                chunk = b""
        if chunk:
            lines = chunk.decode("utf-8", errors="replace").splitlines()
    return {
        "ok": True,
        "path": path.name,
        "offset": new_offset,
        "size": size,
        "lines": lines,
        "truncated": new_offset < size,
        "mode": "chunk",
    }


@app.get("/api/logs/process")
def api_logs_process(
    offset: int = 0,
    tail: int = 0,
    max_bytes: int = 65536,
):
    """Canlı süreç stdout logu — byte offset ile artımlı tail."""
    path = _elite_process_log_path()
    try:
        use_tail = tail if offset <= 0 else 0
        return _read_process_log_chunk(
            path,
            offset=offset,
            tail=use_tail,
            max_bytes=max_bytes,
        )
    except OSError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "path": path.name,
            "offset": offset,
            "size": 0,
            "lines": [],
        }


_ADMIN_COOKIE = "elite_admin_session"


def _require_admin(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)) -> None:
    from elite_trader.admin_auth import session_valid

    if not session_valid(admin_session):
        raise HTTPException(status_code=401, detail="admin auth required")


@app.get("/api/mega/control/status")
def api_mega_control_status():
    if not _is_mega_primary_process():
        raise HTTPException(status_code=404, detail="not mega primary")
    from elite_trader.mega_control import get_status

    return get_status()


@app.post("/api/mega/control/pause")
def api_mega_control_pause():
    if not _is_mega_primary_process():
        raise HTTPException(status_code=404, detail="not mega primary")
    from elite_trader.mega_control import request_pause

    return request_pause()


@app.post("/api/mega/control/start")
def api_mega_control_start():
    if not _is_mega_primary_process():
        raise HTTPException(status_code=404, detail="not mega primary")
    from elite_trader.mega_control import request_start

    return request_start()


@app.post("/api/mega/control/restart")
def api_mega_control_restart():
    if not _is_mega_primary_process():
        raise HTTPException(status_code=404, detail="not mega primary")
    from elite_trader.mega_control import request_restart

    return request_restart()


@app.post("/api/mega/positions/sync")
def api_mega_positions_sync(force: bool = True):
    """Borsa positionRisk → yerel MEGA kitap (manuel tetik)."""
    if not _is_mega_primary_process():
        raise HTTPException(status_code=404, detail="not mega primary")
    from elite_trader.mega_live import mega_open_coins, run_mega_position_sync_tick, snapshot
    from elite_trader.mega_position_sync import wake_mega_position_sync

    run_mega_position_sync_tick(force=force)
    wake_mega_position_sync(force=force)
    snap = snapshot(light=True)
    return {
        "ok": True,
        "open_count": len(mega_open_coins()),
        "open": snap.get("open") or [],
        "summary": snap.get("summary") or {},
    }


@app.post("/api/mega/closed/sync")
def api_mega_closed_sync(force: bool = True):
    """Kapalı işlemler — demo/mainnet userTrades ile hizala (hayalet sil, PnL düzelt)."""
    if not _is_mega_primary_process():
        raise HTTPException(status_code=404, detail="not mega primary")
    from elite_trader.mega_close_sync import sync_missing_closes_from_exchange, wake_mega_close_sync
    from elite_trader.mega_live import reconcile_mega_closed_with_exchange, snapshot

    added = sync_missing_closes_from_exchange(force=force)
    rep = reconcile_mega_closed_with_exchange(force=force)
    wake_mega_close_sync(force=force)
    snap = snapshot(light=True)
    closed = snap.get("closed") or []
    return {
        "ok": True,
        "reconcile": rep,
        "added_from_exchange": added,
        "closed_count": len(closed),
        "closed_tail": closed[-8:],
    }


@app.post("/api/mega/positions/{position_id}/close")
def api_mega_position_close(position_id: int):
    if not _is_mega_primary_process():
        raise HTTPException(status_code=404, detail="not mega primary")
    from elite_trader.mega_control import audit_log
    from elite_trader.mega_live import close_mega_position

    ok = close_mega_position(position_id, "Manual")
    if ok:
        audit_log("manual_close", position_id=position_id)
    return {"ok": ok, "position_id": position_id}


@app.post("/api/admin/login")
def api_admin_login(body: dict = Body(...)):
    from elite_trader.admin_auth import create_session, verify_password

    password = str(body.get("password") or "")
    if not verify_password(password):
        raise HTTPException(status_code=403, detail="invalid password")
    token = create_session()
    resp = Response(content='{"ok":true}', media_type="application/json")
    resp.set_cookie(
        _ADMIN_COOKIE,
        token,
        httponly=True,
        max_age=86400,
        samesite="lax",
    )
    return resp


@app.post("/api/admin/logout")
def api_admin_logout(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    from elite_trader.admin_auth import revoke_session

    revoke_session(admin_session)
    resp = Response(content='{"ok":true}', media_type="application/json")
    resp.delete_cookie(_ADMIN_COOKIE)
    return resp


@app.get("/api/admin/auth/status")
def api_admin_auth_status(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    from elite_trader.admin_auth import auth_status

    return auth_status(admin_session)


@app.get("/api/admin/settings/schema")
def api_admin_settings_schema(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    _require_admin(admin_session)
    from elite_trader.admin_settings import get_schema

    return get_schema()


@app.get("/api/admin/settings/values")
def api_admin_settings_values(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    _require_admin(admin_session)
    from elite_trader.admin_settings import get_values

    return get_values()


@app.get("/api/admin/settings/impact")
def api_admin_settings_impact(
    key: str | None = None,
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.admin_settings import get_impact

    return get_impact(key)


@app.patch("/api/admin/settings")
def api_admin_settings_patch(
    body: dict = Body(...),
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.admin_settings import patch_settings

    return patch_settings(body.get("patch") or body)


@app.post("/api/admin/settings/preview")
def api_admin_settings_preview(
    body: dict = Body(...),
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.admin_settings import preview_settings

    return preview_settings(body.get("patch") or body)


@app.get("/api/admin/profiles")
def api_admin_profiles(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    _require_admin(admin_session)
    from elite_trader.admin_settings import list_profiles

    return list_profiles()


@app.get("/api/admin/profiles/{mode_id}")
def api_admin_profile_get(mode_id: str, admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    _require_admin(admin_session)
    from elite_trader.admin_settings import get_profile_values

    return get_profile_values(mode_id)


@app.patch("/api/admin/profiles/{mode_id}")
def api_admin_profile_patch(
    mode_id: str,
    body: dict = Body(...),
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.admin_settings import patch_profile

    return patch_profile(mode_id, body.get("patch") or body)


@app.post("/api/admin/profiles/preview")
def api_admin_profile_preview(
    body: dict = Body(...),
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.admin_settings import preview_profile

    return preview_profile(str(body.get("mode_id") or "mega"), body.get("patch") or body)


@app.post("/api/lab/knowledge/bootstrap")
def api_lab_knowledge_bootstrap(
    body: dict = Body(default={}),
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.training_lab.lab_api import bootstrap_knowledge

    force = str(body.get("force") or "").lower() in ("1", "true", "yes")
    return bootstrap_knowledge(force=force)


@app.get("/api/lab/knowledge/status")
def api_lab_knowledge_status(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab import lab_store
    from pathlib import Path

    docs = lab_store.lab_data_dir() / "documents"
    marker = docs / ".knowledge_bootstrap_ts"
    sys_docs = sorted(docs.glob("sys_*.txt")) if docs.is_dir() else []
    return {
        "ok": True,
        "bootstrapped": marker.is_file(),
        "bootstrap_ts": marker.read_text(encoding="utf-8").strip() if marker.is_file() else None,
        "sys_documents": [p.name for p in sys_docs],
        "lessons_count": len(lab_store.read_lessons(limit=500)),
    }


@app.get("/api/lab/sessions")
def api_lab_sessions(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab import lab_store

    return {"sessions": lab_store.list_sessions()}


@app.post("/api/lab/chat")
def api_lab_chat(body: dict = Body(...), admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab.lab_api import lab_chat

    return lab_chat(
        str(body.get("session_id") or ""),
        str(body.get("message") or ""),
        context=body.get("context"),
    )


@app.post("/api/lab/motor/run")
def api_lab_motor_run(body: dict = Body(...), admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab.lab_api import run_motor_sandbox

    return run_motor_sandbox(str(body.get("motor") or "scan_summary"), body.get("payload"))


@app.post("/api/lab/documents/ingest")
def api_lab_doc_ingest(body: dict = Body(...), admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab.lab_api import ingest_image, ingest_pdf, ingest_text

    kind = str(body.get("kind") or "text")
    if kind == "pdf":
        import base64

        raw = base64.b64decode(body.get("data_b64") or "")
        return ingest_pdf(raw, name=str(body.get("name") or "doc.pdf"))
    if kind.startswith("image/"):
        import base64

        raw = base64.b64decode(body.get("data_b64") or "")
        return ingest_image(
            raw,
            name=str(body.get("name") or "chart.png"),
            kind=kind,
            prompt=str(body.get("prompt") or ""),
        )
    return ingest_text(str(body.get("text") or ""), name=str(body.get("name") or "paste.txt"))


@app.get("/api/lab/lessons")
def api_lab_lessons(limit: int = 50, admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab import lab_store

    return {"ok": True, "lessons": lab_store.list_lessons(limit=max(1, min(limit, 200)))}


@app.post("/api/lab/lessons")
def api_lab_lessons_post(body: dict = Body(...), admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab.lab_api import add_lesson

    return add_lesson(
        str(body.get("text") or ""),
        session_id=str(body.get("session_id") or ""),
        tags=body.get("tags"),
    )


@app.get("/api/lab/documents")
def api_lab_documents(limit: int = 20, admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab import lab_store

    return {"ok": True, "documents": lab_store.list_documents(limit=max(1, min(limit, 50)))}


@app.post("/api/lab/checkpoint/link")
def api_lab_checkpoint_link(body: dict = Body(...), admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab.lab_api import link_checkpoint

    return link_checkpoint(str(body.get("session_id") or ""), str(body.get("checkpoint_id") or ""))


@app.get("/api/lab/sim/counterfactual")
def api_lab_sim_counterfactual(symbol: str | None = None):
    from elite_trader.lab_simulator import simulate_from_scan_cache

    return simulate_from_scan_cache(symbol)


@app.get("/api/lab/export")
def api_lab_export(
    session_id: str = "",
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    lab_ok = os.getenv("LAB_ACCESS", "1").strip().lower() in ("1", "true", "yes")
    if not lab_ok:
        _require_admin(admin_session)
    from elite_trader.training_lab.lab_api import export_bundle

    return export_bundle(session_id=session_id)


@app.get("/api/develop/status")
def api_develop_status(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    _require_admin(admin_session)
    from elite_trader.training_lab import develop_api

    return develop_api.develop_status()


@app.get("/api/develop/scenario")
def api_develop_scenario(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    _require_admin(admin_session)
    from elite_trader.training_lab import develop_api

    return develop_api.scenario_summary()


@app.get("/api/develop/proposals")
def api_develop_proposals(
    status: str | None = None,
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.training_lab import develop_api

    return develop_api.list_proposals_ui(status=status or None)


@app.post("/api/develop/knowledge/bootstrap")
def api_develop_bootstrap(
    body: dict = Body(default={}),
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.training_lab.lab_api import bootstrap_knowledge

    force = str(body.get("force") or "").lower() in ("1", "true", "yes")
    return bootstrap_knowledge(force=force)


@app.post("/api/develop/restart")
def api_develop_restart(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    _require_admin(admin_session)
    from elite_trader.training_lab import develop_api

    return develop_api.restart_bot()


@app.post("/api/develop/systemd-restart")
def api_develop_systemd_restart(
    body: dict = Body(default={}),
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.training_lab import develop_api

    svc = str(body.get("service") or "binance-elite-9007-mainnet")
    return develop_api.try_systemd_restart(service=svc)


@app.get("/api/develop/checks")
def api_develop_checks(admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE)):
    _require_admin(admin_session)
    from elite_trader.training_lab import develop_api

    return develop_api.run_self_checks()


@app.get("/api/ops/dashboard")
def api_ops_dashboard(
    fresh: int = 0,
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    from elite_trader.training_lab import ops_monitor

    return ops_monitor.ops_dashboard(fresh_llm=fresh > 0)


@app.get("/api/logs/decisions")
def api_logs_decisions(limit: int = 500, format: str = "json"):
    from elite_trader.data_lake.ingest import export_decisions_jsonl

    rows = export_decisions_jsonl(min(limit, 2000))
    if format.lower() == "csv":
        import csv
        import io

        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(buf.getvalue(), media_type="text/csv")
    return {"ok": True, "count": len(rows), "decisions": rows}


@app.post("/api/checkpoints/create")
def api_checkpoint_create(
    body: dict = Body(default={}),
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    try:
        from elite_trader.system_checkpoint_md import write_checkpoint

        label = str(body.get("label") or "Manuel checkpoint")
        return write_checkpoint("manual", label=label, name_parts=["manual", "admin"])
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/checkpoints/recent")
def api_checkpoints_recent(limit: int = 3):
    try:
        from elite_trader.system_checkpoint_md import list_recent_checkpoints

        rows = list_recent_checkpoints(max(1, min(limit, 20)))
        return {"ok": True, "checkpoints": rows}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "checkpoints": []}


@app.get("/api/checkpoints/{filename}/preview")
def api_checkpoint_rollback_preview(filename: str, scopes: str = ""):
    try:
        from elite_trader.system_checkpoint_md import rollback_preview

        scope_list = [s.strip() for s in scopes.split(",") if s.strip()] or None
        return rollback_preview(filename, scope_list)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/checkpoints/{filename}/rollback")
def api_checkpoint_rollback(
    filename: str,
    body: dict = Body(...),
    admin_session: str | None = Cookie(default=None, alias=_ADMIN_COOKIE),
):
    _require_admin(admin_session)
    try:
        from elite_trader.system_checkpoint_md import rollback_checkpoint

        scopes = body.get("scopes") or ["panel_strategy_state", "mode_profiles"]
        return rollback_checkpoint(
            filename,
            scopes=scopes,
            reason=str(body.get("reason") or ""),
            confirm=bool(body.get("confirm")),
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/checkpoints/{filename}")
def api_checkpoint_content(filename: str):
    try:
        from elite_trader.system_checkpoint_md import read_checkpoint_content

        content = read_checkpoint_content(filename)
        if content is None:
            return {"ok": False, "error": "not found"}
        return {"ok": True, "file": filename, "content": content}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/checkpoints/{filename}/download")
def api_checkpoint_download(filename: str):
    try:
        from elite_trader.system_checkpoint_md import checkpoint_download_path

        path = checkpoint_download_path(filename)
        if path is None:
            return {"ok": False, "error": "not found"}
        return FileResponse(
            path=str(path),
            media_type="text/markdown",
            filename=filename,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/config/export")
def api_config_export():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent
    out: dict[str, Any] = {"ok": True, "profiles": {}, "panel": {}}
    mp = root / "data" / "mode_profiles.json"
    ps = root / "data" / "panel_strategy_state.json"
    if mp.is_file():
        out["profiles"] = json.loads(mp.read_text(encoding="utf-8"))
    if ps.is_file():
        out["panel"] = json.loads(ps.read_text(encoding="utf-8"))
    return out


@app.post("/api/panel/view")
def panel_view_set(body: dict = Body(default_factory=dict)):
    """Panel görünümü — veri silinmez, pozisyon kapatılmaz."""
    mode_id = str(body.get("mode") or "").strip()
    if not mode_id:
        return {"ok": False, "error": "mode required"}
    try:
        old = active_view_mode()
        set_view_mode(mode_id)
        applied = active_view_mode()
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    print(f"  👁 Panel görünüm: {old} → {applied}")
    return {
        "ok": True,
        "view_mode": applied,
        "panel_strategy": panel_strategy_snapshot(),
        "snapshot": get_snapshot(light=True),
    }


@app.get("/api/evrim/training")
def evrim_training_get():
    try:
        from elite_trader.evrim_training import training_snapshot

        return {"ok": True, **training_snapshot()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/evrim/training/prompt")
def evrim_training_prompt(body: dict = Body(default_factory=dict)):
    text = str(body.get("prompt") or body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "prompt required"}
    try:
        from elite_trader.evrim_training import apply_training_prompt

        out = apply_training_prompt(text, source=str(body.get("source") or "user"))
        return {**out, "snapshot": get_snapshot()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/evrim/training/toggle")
def evrim_training_toggle(body: dict = Body(default_factory=dict)):
    enabled = body.get("enabled")
    if enabled is None:
        return {"ok": False, "error": "enabled required"}
    try:
        from elite_trader.evrim_training import set_training_enabled

        out = set_training_enabled(bool(enabled))
        return {"ok": True, "training": out, "snapshot": get_snapshot()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/evrim/unified/status")
def evrim_unified_status():
    try:
        from elite_trader.evrim_unified_engine import unified_status

        return {"ok": True, **unified_status()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/evrim/unified/risk-report")
def evrim_unified_risk_report():
    try:
        from elite_trader.evrim_unified_engine import build_pre_live_risk_report

        return {"ok": True, "report": build_pre_live_risk_report()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/market-intelligence/status")
def market_intelligence_status():
    try:
        from elite_trader.market_intelligence_hub import get_hub

        return {"ok": True, "pool": get_hub().snapshot()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/market-intelligence/refresh")
def market_intelligence_refresh():
    try:
        from elite_trader.market_intelligence_hub import get_hub

        get_hub().refresh_intelligence(force=True)
        return {"ok": True, "pool": get_hub().snapshot(), "snapshot": get_snapshot()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/evrim/unified/news/refresh")
def evrim_unified_news_refresh():
    try:
        from elite_trader.market_intelligence_hub import get_hub

        get_hub().refresh_intelligence(force=True)
        from elite_trader.evrim_unified_engine import maybe_refresh_news

        return {"ok": True, **maybe_refresh_news(force=True), "pool": get_hub().snapshot()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/evrim/unified/live-enable")
def evrim_unified_live_enable(body: dict = Body(default_factory=dict)):
    confirm = body.get("confirm") in (True, "true", 1, "1")
    try:
        from elite_trader.evrim_unified_engine import enable_live_trading

        return enable_live_trading(confirm=confirm)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/evrim/config/suggestions")
def evrim_config_suggestions():
    try:
        from elite_trader.evrim_config_pipeline import list_pending_suggestions

        return {"ok": True, "pending": list_pending_suggestions()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/evrim/config/suggestions/{suggestion_id}/approve")
def evrim_config_approve(suggestion_id: str):
    try:
        from elite_trader.evrim_config_pipeline import apply_approved_config
        from elite_trader.system_checkpoint_md import on_evrim_config_change

        result = apply_approved_config(suggestion_id)
        try:
            on_evrim_config_change(suggestion_id, result if isinstance(result, dict) else {})
        except Exception:
            pass
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/evrim/config/suggestions/{suggestion_id}/reject")
def evrim_config_reject(suggestion_id: str):
    try:
        from elite_trader.evrim_config_pipeline import reject_suggestion

        return reject_suggestion(suggestion_id)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/evrim/training/backtest")
def evrim_training_backtest(body: dict = Body(default_factory=dict)):
    background = body.get("background", True)
    if isinstance(background, str):
        background = background.lower() not in ("0", "false", "no")
    try:
        from elite_trader.evrim_training import trigger_mtf_backtest

        out = trigger_mtf_backtest(background=bool(background))
        return {**out, "snapshot": get_snapshot()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/panel/execution")
def panel_execution_set(body: dict = Body(default_factory=dict)):
    """Binance çıkış motoru — .env dokunulmaz; borsa pozisyonları kapanır, oturum sıfırlanır."""
    mode_id = str(body.get("mode") or "").strip()
    if not mode_id:
        return {"ok": False, "error": "mode required"}
    try:
        old, applied = set_execution_mode(mode_id, note=body.get("note") or "")
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    _on_execution_motor_changed(old, applied)
    return {
        "ok": True,
        "previous_execution": old,
        "execution_mode": applied,
        "panel_strategy": panel_strategy_snapshot(),
        "snapshot": get_snapshot(),
    }


@app.post("/api/panel/mode")
def panel_mode_set(body: dict = Body(default_factory=dict)):
    """Geriye uyumluluk — yalnızca görünüm (kapatma yok). execution için /api/panel/execution."""
    mode_id = str(body.get("mode") or "").strip()
    if not mode_id:
        return {"ok": False, "error": "mode required"}
    try:
        old = active_view_mode()
        set_view_mode(mode_id)
        applied = active_view_mode()
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "previous_mode": old,
        "current_mode": applied,
        "view_mode": applied,
        "closed_count": 0,
        "panel_strategy": panel_strategy_snapshot(),
        "snapshot": get_snapshot(),
    }


@app.get("/api/export/trades")
def api_export_trades(
    format: str = "csv",
    scope: str = "all",
    mode_id: Optional[str] = None,
):
    """İşlem dışa aktarım — scope: all|live|history|open|parallel; mode_id ile tek mod."""
    fmt = (format or "csv").strip().lower()
    sc = (scope or "all").strip().lower()
    mid = (mode_id or "").strip() or None
    try:
        if fmt == "zip":
            data, filename = build_zip_export(
                live_closed=list(closed_positions),
                live_open=list(positions),
                scope=sc,
                mode_id=mid,
            )
            media = "application/zip"
        else:
            data, filename = build_csv_export(
                live_closed=list(closed_positions),
                live_open=list(positions),
                scope=sc,
                mode_id=mid,
            )
            media = "text/csv; charset=utf-8"
        return Response(
            content=data,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        return Response(
            content=f"Hata: {exc}".encode("utf-8"),
            status_code=500,
            media_type="text/plain",
        )


@app.post("/api/learner/proposals/{proposal_id}/approve")
def learner_approve_proposal(proposal_id: str):
    p = get_proposal(proposal_id)
    if not p:
        return {"ok": False, "error": "proposal not found"}
    applied = apply_proposal_to_scenario(p)
    already = proposal_satisfied(p)
    ok = set_proposal_status(proposal_id, "approved")
    if not ok:
        return {"ok": False, "error": "proposal not found"}
    if applied:
        msg = "Onaylandı ve senaryo dosyasına yazıldı (çalışan süreçte env güncellendi)."
    elif already:
        msg = "Onaylandı — ayarlar zaten senaryoda mevcut."
    else:
        msg = "Onaylandı — öneride uygulanabilir env anahtarı yok veya dosya yazılamadı."
    return {
        "ok": True,
        "applied": applied,
        "message": msg,
        "snapshot": loss_learner_snapshot(),
    }


@app.post("/api/learner/proposals/{proposal_id}/reject")
def learner_reject_proposal(proposal_id: str):
    ok = set_proposal_status(proposal_id, "rejected")
    if not ok:
        return {"ok": False, "error": "proposal not found"}
    return {"ok": True, "snapshot": loss_learner_snapshot()}


@app.get("/api/archives")
def api_archives_list():
    from elite_trader.data_archive import snapshot_archives_for_ui

    return {"ok": True, "archives": snapshot_archives_for_ui(limit=30)}


@app.get("/api/archives/{archive_id}")
def api_archives_detail(archive_id: str):
    from elite_trader.data_archive import archive_detail

    detail = archive_detail(archive_id)
    if not detail:
        return {"ok": False, "error": "archive not found"}
    return {"ok": True, **detail}


@app.post("/api/mode/archive")
def api_mode_archive(body: dict = Body(default_factory=dict)):
    """Aktif modun işlemlerini arşivle (mod başına klasör)."""
    mode_id = str(body.get("mode_id") or active_view_mode()).strip()
    reason = str(body.get("reason") or "").strip()
    if not reason:
        return {"ok": False, "error": "reason required"}
    try:
        if is_live_binance_motor(mode_id):
            meta = archive_mode(
                mode_id,
                reason=reason,
                trigger="panel",
                live_trades=collect_live_trades(
                    open_positions=list(positions),
                    closed_positions=list(closed_positions),
                ),
            )
        else:
            meta = archive_mode(mode_id, reason=reason, trigger="panel")
        return {
            "ok": True,
            "archive": meta,
            "mode_id": mode_id,
            "message": f"{meta.get('mode_label', mode_id)} işlemleri arşivlendi.",
            "snapshot": get_snapshot(),
        }
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/mode/reset")
def api_mode_reset(body: dict = Body(default_factory=dict)):
    """Mod bakiyesi/geçmiş sıfır — Ana Hat: borsa pozisyonları kapatılır."""
    global positions, closed_positions, position_id_counter
    if not _elite_state_enabled():
        return {"ok": False, "error": "only port 9005"}
    mode_id = str(body.get("mode_id") or active_view_mode()).strip()
    reason = str(body.get("reason") or "").strip()
    if not reason:
        return {"ok": False, "error": "reason required"}
    archive_first = body.get("archive_first", True)
    close_exchange = body.get("close_exchange", True)

    try:
        archive_meta = None
        if archive_first:
            if is_live_binance_motor(mode_id):
                archive_meta = archive_mode(
                    mode_id,
                    reason=f"[sıfırlama öncesi] {reason}",
                    trigger="panel_reset",
                    live_trades=collect_live_trades(
                        open_positions=list(positions),
                        closed_positions=list(closed_positions),
                    ),
                )
            else:
                archive_meta = archive_mode(
                    mode_id,
                    reason=f"[sıfırlama öncesi] {reason}",
                    trigger="panel_reset",
                )

        exchange_out = None
        if is_live_binance_motor(mode_id):
            exec_mid = active_execution_mode()
            if close_exchange and is_live_binance_motor(exec_mid) and LIVE_ORDERS:
                exchange_out = close_binance_exchange_positions()
            for pos in list(positions):
                close_position(pos["id"], "MODE-RESET")
            mem = reset_live_memory(
                positions=positions,
                closed_positions=closed_positions,
                position_id_counter=position_id_counter,
                wipe_db=True,
            )
            position_id_counter = 1
            result = {
                "scope": "live",
                "mode_id": mode_id,
                "memory": mem,
                "exchange": exchange_out,
            }
        elif mode_id in parallel_mode_ids():
            result = {
                "scope": "parallel",
                "mode_id": mode_id,
                "universe": reset_parallel_universe(mode_id),
            }
        else:
            return {"ok": False, "error": f"unknown mode: {mode_id}"}

        print(f"  🔄 Mod sıfırlandı: {mode_id} — {reason}")
        return {
            "ok": True,
            "archive": archive_meta,
            "result": result,
            "message": (
                f"{result.get('mode_id', mode_id)} geçmişi sıfırlandı. "
                + (
                    exchange_out.get("message", "")
                    if exchange_out
                    else "Paper kitap temizlendi."
                )
            ),
            "snapshot": get_snapshot(),
        }
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/mode/archives")
def api_mode_archives_list(mode_id: str = ""):
    mid = (mode_id or active_view_mode()).strip()
    return {
        "ok": True,
        "mode_id": mid,
        "archives": list_mode_archives(mid, limit=40),
    }


@app.get("/api/mode/archives/{archive_id}")
def api_mode_archives_detail(archive_id: str):
    detail = archive_detail_mode(archive_id)
    if not detail:
        return {"ok": False, "error": "archive not found"}
    return {"ok": True, **detail}


@app.post("/api/archives/wipe")
def api_archives_wipe(body: dict = Body(default_factory=dict)):
    """Panelden silme — önce arşiv, sonra dosya silme (ayar dosyasına dokunmaz)."""
    global closed_positions, position_id_counter
    if not _elite_state_enabled():
        return {"ok": False, "error": "only port 9005"}
    reason = str(body.get("reason") or "").strip()
    if not reason:
        return {"ok": False, "error": "reason required"}
    from elite_trader.data_archive import wipe_9005_with_archive

    meta = wipe_9005_with_archive(reason=reason, trigger="panel")
    closed_positions.clear()
    position_id_counter = 1
    return {
        "ok": True,
        "archive": meta,
        "message": "Arşivlendi ve yerel veri silindi. Bot yeni işlemleri sıfırdan kaydeder.",
        "snapshot": get_snapshot(),
    }


@app.websocket("/ws")
async def ws_live(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        if _last_ws_snapshot:
            await ws.send_text(json.dumps(_last_ws_snapshot))
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=60.0)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "ping", "ts": time.time()}))
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception as exc:
        print(f"  ⚠ WS hata: {exc}")
        ws_manager.disconnect(ws)

if __name__ == "__main__":
    import sys
    import uvicorn

    faulthandler.enable()
    try:
        faulthandler.register(signal.SIGUSR1, all_threads=True)  # type: ignore[name-defined]
    except Exception:
        pass

    def _fatal_excepthook(exc_type, exc, tb) -> None:
        import traceback as _tb

        print(f"❌ FATAL {exc_type.__name__}: {exc}", file=sys.stderr)
        _tb.print_exception(exc_type, exc, tb, file=sys.stderr)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _fatal_excepthook

    def _acquire_single_instance_lock() -> None:
        """Port 9005 — çift süreç / port çakışmasını önle."""
        if ELITE_PORT != 9005:
            return
        import fcntl

        lock_dir = Path(__file__).resolve().parent / ".pids"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / f"elite_instance_{ELITE_PORT}.lock"
        lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"❌ Başka Elite {ELITE_PORT} süreci çalışıyor ({lock_path})")
            print("   ./stop_binance_elite_8300_9005.sh  veya  ./scripts/elite_9005_process_ctl.sh restart")
            raise SystemExit(1)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        # Süreç bitene kadar kilidi tut
        import atexit

        def _release() -> None:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                lock_fd.close()
            except Exception:
                pass

        atexit.register(_release)

    _acquire_single_instance_lock()
    print("━" * 80)
    print(f"🚀 BINANCE FUTURES ELITE PRO — senaryo: {SCENARIO_FILE}")
    print("━" * 80)
    print(f"📡 Access: http://localhost:{ELITE_PORT}")
    print(f"💰 STARTING_BALANCE: ${STARTING_CAPITAL:,.0f} | MAX_AÇIK: {execution_max_open()}")
    try:
        from elite_trader.fee_economics import exit_tp_only

        if exit_tp_only(active_execution_mode()):
            print("🎯 Çıkış modu: yalnızca TP / SPIKE (SL·STALE engelli)")
    except Exception:
        pass
    print(
        f"📐 TP: ELITE_TP_STAKE_PCT={TP_PCT} × ELITE_TP_TRIGGER_FRAC={TP_TRIGGER} | "
        f"SL: ELITE_SL_STAKE_PCT={SL_PCT}"
    )
    if LIVE_ORDERS and not client.paper:
        mode_lbl = (
            "MAINNET canlı emir (fapi.binance.com)"
            if _is_9005_mainnet()
            else "DEMO canlı emir (demo-fapi)"
        )
    else:
        mode_lbl = "TESTNET" if not client.paper else "PAPER"
    core = len(tradable_symbols) if tradable_symbols else len(watchlist)
    print(
        f"🔧 Mode: {mode_lbl} | tarama: {len(watchlist)} | emir çekirdeği: {core} sembol"
    )
    if client.paper and LIVE_ORDERS:
        print("  ⚠ BINANCE_LIVE_ORDERS=1 ama API paper — anahtarları kontrol edin")
    print("━" * 80)
    uvicorn.run(app, host=ELITE_BIND_HOST, port=ELITE_PORT)
