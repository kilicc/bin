#!/usr/bin/env python3
"""
Elite 9005 — terminal izleyici
- Hızlı bot snapshot (~15–50ms); fiyat sütunları yapışkan (varsayılan 2s)
- Binance cüzdan ping seyrek (varsayılan 15s)
- Book fill net (komisyon + Est. Funding) yalnızca fiyat yenileme döngüsünde
- Min kapanış hedefi: ELITE_EXIT_MIN_NET_USD (varsayılan $0.40)
- Son kapanan işlemlerde sinyal fill + order/settle süreleri

Çalıştır (predmarket-scanner klasöründen):
  python3 scripts/position_monitor.py
"""
from __future__ import annotations

import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / "scenarios" / "binance_elite_8300_9005.env", override=True)
load_dotenv(_ROOT / ".env", override=True)
load_dotenv(_ROOT / "scenarios" / "binance_elite_8300_9005.env", override=True)

BOT_PORT = os.getenv("BINANCE_ELITE_PORT", os.getenv("DASHBOARD_PORT", "9005"))
BOT_BASE = os.getenv("ELITE_MONITOR_BOT_BASE", f"http://127.0.0.1:{BOT_PORT}")
MONITOR_API = os.getenv(
    "ELITE_MONITOR_SNAPSHOT_URL", f"{BOT_BASE}/api/monitor/snapshot"
)
BOT_API = os.getenv("ELITE_MONITOR_BOT_URL", f"{BOT_BASE}/api/live")
CONN_API = os.getenv("ELITE_MONITOR_CONN_URL", f"{BOT_BASE}/api/connection/live")
HB_API = os.getenv("ELITE_MONITOR_HB_URL", f"{BOT_BASE}/api/heartbeat")
UPDATE_SEC = float(os.getenv("ELITE_MONITOR_INTERVAL_SEC", "0.2"))
API_TIMEOUT = float(os.getenv("ELITE_MONITOR_API_TIMEOUT_SEC", "6.0"))
MIN_NET = float(os.getenv("ELITE_EXIT_MIN_NET_USD", "0.40"))
EXCHANGE_REFRESH_MS = float(os.getenv("ELITE_EXCHANGE_POSITION_REFRESH_SEC", "0.5")) * 1000.0
ENV_POS_CHECK_MS = float(os.getenv("ELITE_POSITION_CHECK_SEC", "0.02")) * 1000.0
# Ağır REST/fill — ekranda fiyat her tick değil, bu aralıkta yenilenir
PRICE_DISPLAY_REFRESH_SEC = float(os.getenv("ELITE_MONITOR_PRICE_REFRESH_SEC", "0.5"))
BALANCE_PING_SEC = float(os.getenv("ELITE_MONITOR_BALANCE_PING_SEC", "15.0"))
HB_REFRESH_SEC = float(os.getenv("ELITE_MONITOR_HB_REFRESH_SEC", "8.0"))


MAX_OPEN_ROWS = 10
MAX_CLOSED_ROWS = 5
MAX_EVENT_ROWS = 8
STICKY_LIVE_SEC = float(os.getenv("ELITE_MONITOR_STICKY_SEC", "10"))
FILL_REFRESH_SEC = float(os.getenv("ELITE_MONITOR_FILL_REFRESH_SEC", "2.0"))

MAX_SPEED_LINES = 5
SPEED_LOG_EVERY_SEC = float(os.getenv("ELITE_MONITOR_SPEED_LOG_SEC", "4.0"))
RISK_MEASURE_EVERY_SEC = float(os.getenv("ELITE_MONITOR_RISK_MEASURE_SEC", "0"))

_last_frame_lines = 0
_fill_cache: dict[str, tuple[float, dict]] = {}
_last_live: dict | None = None
_last_live_ts = 0.0
_seen_open_keys: set[str] = set()
_last_open_by_key: dict[str, dict] = {}
_events_bootstrapped = False
_local_events: deque[dict] = deque(maxlen=40)
_last_speed_log_ts = 0.0
_last_risk_measure_ts = 0.0
_last_risk_ms = 0.0
_last_risk_count = 0
_speed_hist: dict[str, deque] = {
    "snapshot": deque(maxlen=90),
    "fill": deque(maxlen=90),
    "risk": deque(maxlen=45),
}
# Ekranda gösterilen fiyat/net — bot snapshot hızlı; fiyat sütunları yapışkan
_display_est: dict[str, dict] = {}
_display_est_ts = 0.0
_display_est_keys: set[str] = set()
_last_bn_ping: tuple[bool, float, str, float | None] = (False, 0.0, "", None)
_last_bn_ping_ts = 0.0
_last_hb: dict | None = None
_last_hb_ts = 0.0


class _Screen:
    """Alternatif tampon — clear/scroll yok, sabit çerçeve."""

    active = False

    @classmethod
    def enter(cls) -> None:
        if cls.active:
            return
        sys.stdout.write("\033[?1049h\033[2J\033[H")
        sys.stdout.flush()
        cls.active = True

    @classmethod
    def leave(cls) -> None:
        if not cls.active:
            return
        sys.stdout.write("\033[?1049l")
        sys.stdout.flush()
        cls.active = False

    @classmethod
    def render(cls, lines: list[str]) -> None:
        global _last_frame_lines
        cls.enter()
        sys.stdout.write("\033[H")
        width = 98
        for line in lines:
            txt = line.rstrip("\n")
            if len(txt) > width:
                txt = txt[: width - 1] + "…"
            sys.stdout.write(txt + "\033[K\n")
        extra = _last_frame_lines - len(lines)
        for _ in range(max(0, extra)):
            sys.stdout.write("\033[K\n")
        _last_frame_lines = len(lines)
        sys.stdout.flush()


def _clear() -> None:
    _Screen.leave()


def _fmt_age(sec: float) -> str:
    if sec < 60:
        return f"{sec:.0f}s"
    if sec < 3600:
        return f"{sec / 60:.1f}m"
    return f"{sec / 3600:.1f}h"


def _pos_age_sec(p: dict) -> float:
    ds = p.get("duration_sec")
    if ds is not None:
        try:
            return max(0.0, float(ds))
        except (TypeError, ValueError):
            pass
    et = p.get("entry_time")
    if et is not None:
        try:
            return max(0.0, time.time() - float(et))
        except (TypeError, ValueError):
            pass
    return 0.0


def _ping_binance() -> tuple[bool, float, str, float | None]:
    """Tek client — warm REST gecikmesi."""
    global _BN_CLIENT
    try:
        if _BN_CLIENT is None:
            from binance_futures_trader.client import BinanceFuturesClient

            _BN_CLIENT = BinanceFuturesClient()
        t0 = time.perf_counter()
        _BN_CLIENT._get("/fapi/v2/balance", signed=True)
        ms = (time.perf_counter() - t0) * 1000.0
        w = _BN_CLIENT.exchange_wallet() or {}
        bal = float(w.get("total_wallet_balance") or w.get("usdt_balance") or 0)
        return True, ms, "", bal
    except Exception as exc:
        return False, 0.0, str(exc)[:80], None


_BN_CLIENT = None


def _ping_binance_cached() -> tuple[bool, float, str, float | None]:
    """Cüzdan ping — her döngü değil; UI hızlı kalır."""
    global _last_bn_ping, _last_bn_ping_ts
    now = time.time()
    if now - _last_bn_ping_ts < BALANCE_PING_SEC and _last_bn_ping_ts > 0:
        return _last_bn_ping
    ok, ms, err, bal = _ping_binance()
    _last_bn_ping = (ok, ms, err, bal)
    _last_bn_ping_ts = now
    return _last_bn_ping


def _heartbeat_cached(live: dict | None) -> dict | None:
    """Snapshot içindeki heartbeat yeterli; ayrı HB isteği seyrek."""
    global _last_hb, _last_hb_ts
    if live and live.get("heartbeat"):
        _last_hb = live.get("heartbeat")
        _last_hb_ts = time.time()
        return _last_hb
    now = time.time()
    if _last_hb and now - _last_hb_ts < HB_REFRESH_SEC:
        return _last_hb
    hb_raw, _, _ = _get_json(HB_API, timeout=1.5, retries=1)
    if hb_raw and hb_raw.get("ok"):
        _last_hb = {k: v for k, v in hb_raw.items() if k != "ok"}
        _last_hb_ts = now
    return _last_hb


def _maybe_refresh_price_display(
    positions: list[dict],
    *,
    live: dict | None,
    force: bool = False,
) -> float:
    """Fill/net sütunları — PRICE_DISPLAY_REFRESH_SEC'te bir güncellenir."""
    global _display_est, _display_est_ts, _display_est_keys
    keys = {_pos_key(p) for p in positions if p.get("symbol")}
    now = time.time()
    due = force or not _display_est or keys != _display_est_keys
    if not due and now - _display_est_ts < PRICE_DISPLAY_REFRESH_SEC:
        return 0.0
    t0 = time.perf_counter()
    if positions and live is not None:
        _enrich_positions_fill(positions)
    new_est: dict[str, dict] = {}
    for p in positions:
        if not p.get("symbol"):
            continue
        new_est[_pos_key(p)] = _est_net(p)
    _display_est = new_est
    _display_est_keys = keys
    _display_est_ts = now
    return (time.perf_counter() - t0) * 1000.0


def _display_est_for(p: dict) -> dict:
    """Mark her tick; fill/net yapışkan önbellekten."""
    mark_gross = float(p.get("unrealized_pnl") or p.get("exchange_upnl") or 0)
    cached = _display_est.get(_pos_key(p))
    if cached:
        out = dict(cached)
        out["mark_gross"] = mark_gross
        return out
    return _est_net(p)


def _get_json(
    url: str, *, timeout: float | None = None, retries: int = 2
) -> tuple[dict | None, float, str]:
    """JSON GET — timeout/retry; hata metni döner."""
    to = timeout if timeout is not None else API_TIMEOUT
    last_err = ""
    for attempt in range(max(1, retries)):
        try:
            t0 = time.perf_counter()
            r = requests.get(url, timeout=to)
            ms = (time.perf_counter() - t0) * 1000.0
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                continue
            return r.json(), ms, ""
        except requests.exceptions.Timeout:
            last_err = f"timeout ({to:.1f}s)"
        except requests.exceptions.ConnectionError:
            last_err = "bağlantı yok — bot kapalı mı?"
        except Exception as exc:
            last_err = str(exc)[:80]
        if attempt + 1 < retries:
            time.sleep(0.15)
    return None, 0.0, last_err


def _exchange_positions_fallback() -> list[dict]:
    """Bot API yoksa — doğrudan Binance positionRisk."""
    global _BN_CLIENT
    try:
        if _BN_CLIENT is None:
            from binance_futures_trader.client import BinanceFuturesClient

            _BN_CLIENT = BinanceFuturesClient()
        if _BN_CLIENT.paper:
            return []
        out: list[dict] = []
        for ep in _BN_CLIENT.exchange_positions() or []:
            sym = str(ep.get("symbol") or f"{ep.get('coin')}USDT")
            out.append(
                {
                    "symbol": sym,
                    "side": str(ep.get("side") or "LONG"),
                    "entry_price": float(ep.get("entry_price") or 0),
                    "current_price": float(ep.get("mark_price") or 0),
                    "size": float(ep.get("contracts") or 0),
                    "leverage": int(ep.get("leverage") or 5),
                    "unrealized_pnl": float(ep.get("unrealized_pnl") or 0),
                    "data_source": "binance_fallback",
                }
            )
        return out
    except Exception:
        return []


def _fetch_bot_snapshot() -> tuple[dict | None, float, str, str]:
    """Önce hafif /api/monitor/snapshot, gerekirse /api/live."""
    snap, ms, err = _get_json(MONITOR_API, timeout=min(API_TIMEOUT, 4.0))
    if snap and snap.get("ok"):
        return snap, ms, "", "monitor"
    snap2, ms2, err2 = _get_json(BOT_API, timeout=API_TIMEOUT)
    if snap2:
        return snap2, ms2, "", "live"
    detail = err or err2 or "bilinmeyen hata"
    return None, ms or ms2, detail, ""


def _pos_key(p: dict) -> str:
    return f"{p.get('symbol')}|{p.get('side')}"


def _enrich_positions_fill(positions: list[dict]) -> None:
    """Fill net — sembol başına kısa önbellek (REST titremesini azaltır)."""
    if not positions:
        return
    now = time.time()
    try:
        from elite_trader.exchange_fill_truth import enrich_open_position_fill_fields

        client = _BN_CLIENT
        if client is None:
            from binance_futures_trader.client import BinanceFuturesClient

            client = BinanceFuturesClient()
        if getattr(client, "paper", True):
            return
        for p in positions:
            key = _pos_key(p)
            cached = _fill_cache.get(key)
            if cached and now - cached[0] < FILL_REFRESH_SEC:
                p.update(cached[1])
                continue
            try:
                enrich_open_position_fill_fields(p, client=client)
                _fill_cache[key] = (
                    now,
                    {
                        k: p.get(k)
                        for k in (
                            "fill_price_est",
                            "fill_gross_unreal",
                            "fill_net_est",
                            "fill_net_ready",
                            "exit_min_net_usd",
                            "fill_net_fees_est",
                            "fill_net_funding_est",
                            "est_funding_fee_usd",
                            "funding_rate",
                            "mark_unrealized_pnl",
                            "book_bid",
                            "book_ask",
                            "book_src",
                        )
                    },
                )
            except Exception:
                pass
    except Exception:
        pass


def _sticky_live(live: dict | None, bot_err: str) -> tuple[dict | None, str, bool]:
    """Kısa API kesintisinde son iyi snapshot'ı tut."""
    global _last_live, _last_live_ts
    if live is not None:
        _last_live = live
        _last_live_ts = time.time()
        return live, bot_err, False
    if _last_live and time.time() - _last_live_ts <= STICKY_LIVE_SEC:
        age = int(time.time() - _last_live_ts)
        note = f"önbellek {age}s"
        err = f"{note}" + (f" · {bot_err}" if bot_err else "")
        return _last_live, err, True
    return None, bot_err, False


def _est_net(pos: dict) -> dict:
    """Fill tabanlı net (panel alanları varsa); yoksa mark tahmini."""
    fill_net = pos.get("fill_net_est")
    fill_gross = pos.get("fill_gross_unreal")
    mark_gross = float(pos.get("unrealized_pnl") or pos.get("exchange_upnl") or 0)
    if fill_net is not None:
        final = float(fill_net)
        gross = float(fill_gross if fill_gross is not None else mark_gross)
        from elite_trader.fee_economics import estimate_close_from_position

        est = estimate_close_from_position({**pos, "unrealized_pnl": gross})
        return {
            "gross": gross,
            "mark_gross": mark_gross,
            "fees": float(est.get("total_fees") or 0),
            "funding": float(
                est.get("est_funding_fee")
                or pos.get("fill_net_funding_est")
                or pos.get("est_funding_fee_usd")
                or 0
            ),
            "final": final,
            "ready": bool(pos.get("fill_net_ready", final > MIN_NET)),
            "fill_px": pos.get("fill_price_est"),
            "source": "book_fill",
        }
    from elite_trader.fee_economics import estimate_close_from_position

    est = estimate_close_from_position(pos)
    final = float(est.get("final_pnl") or 0)
    return {
        "gross": mark_gross,
        "mark_gross": mark_gross,
        "fees": float(est.get("total_fees") or 0),
        "funding": float(est.get("est_funding_fee") or 0),
        "final": final,
        "ready": final > MIN_NET,
        "fill_px": None,
        "source": "mark",
    }


def _latency_bar(ms: float) -> str:
    if ms <= 0:
        return "—"
    if ms < 450:
        return "🟢 iyi"
    if ms < 900:
        return "🟡 normal (TR→demo)"
    if ms < 2000:
        return "🟠 yavaş"
    return "🔴 çok yavaş"


def _fmt_ms(v) -> str:
    if v is None or v == "":
        return "—"
    try:
        return f"{float(v):.0f}ms"
    except (TypeError, ValueError):
        return "—"


def _fmt_event_line(ev: dict) -> str:
    kind = str(ev.get("kind") or "").upper()
    ts = str(ev.get("ts") or datetime.now().strftime("%H:%M:%S"))[:8]
    sym = str(ev.get("symbol") or "?")[:10]
    side = str(ev.get("side") or "")[:5]
    if kind == "OPEN":
        entry = ev.get("entry_price")
        entry_s = f"@${float(entry):.4f}" if entry else "@—"
        stake = ev.get("stake_usd")
        stake_s = f" stake=${float(stake):.0f}" if stake else ""
        oid = ev.get("order_id")
        oid_s = f" #{oid}" if oid else ""
        sig = ev.get("signal") or ev.get("source") or ""
        sig_s = f" {sig}" if sig else ""
        return (
            f"{ts}  🟢 AÇ  {side:<5}{sym:<10}{entry_s}"
            f" qty={ev.get('size', '—')}{stake_s}{oid_s}{sig_s}"
        )[:98]
    if kind == "CLOSE":
        net = ev.get("final_pnl")
        net_s = f" net=${float(net):+.2f}" if net is not None else ""
        reason = ev.get("exit_reason") or ""
        ack = _fmt_ms(ev.get("order_ack_ms"))
        return (
            f"{ts}  🔴 KAP {side:<5}{sym:<10}{net_s}  {reason}  ack={ack}"
        )[:98]
    if kind == "SYNC":
        return (
            f"{ts}  ↻ SYNC {side:<5}{sym:<10}"
            f"borsadan alındı qty={ev.get('size', '—')}"
        )[:98]
    if kind == "INFO":
        return f"{ts}  ℹ  {ev.get('msg', '')}"[:98]
    if kind == "SPEED":
        return f"{ts}  ⚡ {ev.get('msg', '')}"[:98]
    return f"{ts}  {kind} {sym} {side}"[:98]


def _track_local_events(positions: list[dict]) -> None:
    """Bot yeniden başlamadan önce — borsa diff ile açılış/kapanış."""
    global _seen_open_keys, _last_open_by_key, _events_bootstrapped
    current = {_pos_key(p): p for p in positions if p.get("symbol")}
    if not _events_bootstrapped:
        _seen_open_keys = set(current.keys())
        _last_open_by_key = {k: dict(v) for k, v in current.items()}
        _events_bootstrapped = True
        if current:
            _local_events.appendleft(
                {
                    "kind": "INFO",
                    "ts": datetime.now().strftime("%H:%M:%S"),
                    "msg": f"{len(current)} pozisyon zaten açık — yeni açılışlar burada görünür",
                }
            )
        return
    for key, p in current.items():
        if key not in _seen_open_keys:
            _local_events.appendleft(
                {
                    "kind": "OPEN",
                    "ts": datetime.now().strftime("%H:%M:%S"),
                    "symbol": p.get("symbol"),
                    "side": p.get("side"),
                    "entry_price": p.get("entry_price"),
                    "size": p.get("size"),
                    "stake_usd": p.get("stake_usd"),
                    "order_id": p.get("exchange_order_id"),
                    "signal": p.get("signal_source") or p.get("data_source"),
                    "source": "diff",
                }
            )
            _seen_open_keys.add(key)
    for key in list(_seen_open_keys):
        if key not in current:
            prev = _last_open_by_key.get(key) or {}
            _local_events.appendleft(
                {
                    "kind": "CLOSE",
                    "ts": datetime.now().strftime("%H:%M:%S"),
                    "symbol": prev.get("symbol"),
                    "side": prev.get("side"),
                    "exit_reason": "—",
                    "source": "diff",
                }
            )
            _seen_open_keys.discard(key)
    _last_open_by_key = {k: dict(v) for k, v in current.items()}


def _avg_p95(hist: deque) -> tuple[float, float]:
    if not hist:
        return 0.0, 0.0
    s = sorted(hist)
    avg = sum(s) / len(s)
    p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
    return avg, p95


def _speed_grade(ms: float | None, *, good: float, warn: float) -> str:
    if ms is None or ms <= 0:
        return "—"
    if ms <= good:
        return "🟢"
    if ms <= warn:
        return "🟡"
    return "🔴"


def _measure_position_risk_rest(hb: dict | None = None) -> tuple[float, int]:
    """Bot motoru positionRisk süresi — ayrı REST çağrısı yok."""
    ms = float((hb or {}).get("exchange_poll_ms") or 0)
    n = int((hb or {}).get("live_open") or 0)
    if ms <= 0:
        return 0.0, n
    return ms, n


def _build_speed_metrics(
    *,
    live: dict | None,
    live_ms: float,
    fill_ms: float,
    hb: dict | None,
) -> dict:
    rs = dict((live or {}).get("read_speed") or {})
    rs["monitor_snapshot_ms"] = round(live_ms, 1) if live_ms > 0 else None
    rs["monitor_fill_ms"] = round(fill_ms, 1) if fill_ms > 0 else None
    rs["monitor_risk_ms"] = round(_last_risk_ms, 1) if _last_risk_ms > 0 else None
    rs["monitor_risk_count"] = _last_risk_count
    if hb and not rs.get("bot_position_tick_ms"):
        rs["bot_position_tick_ms"] = hb.get("position_tick_ms")
        rs["bot_position_interval_ms"] = hb.get("position_interval_ms")
        rs.setdefault("exchange_position_poll_ms", hb.get("exchange_poll_ms"))
        rs.setdefault("exchange_poll_timeouts", hb.get("exchange_poll_timeouts"))
        rs.setdefault("exchange_cache_age_ms", hb.get("exchange_cache_age_ms"))
        rs.setdefault("exchange_api_min_ms", hb.get("exchange_api_min_ms"))
        rs.setdefault("exchange_poll_iv_ms", hb.get("exchange_poll_iv_ms"))
        if hb.get("exchange_poll_ms"):
            rs["monitor_risk_ms"] = hb.get("exchange_poll_ms")
            rs["monitor_risk_count"] = hb.get("live_open")
        pa = hb.get("position_ago")
        if pa is not None:
            rs["bot_position_ago_ms"] = int(float(pa) * 1000)
        pf = hb.get("price_feed") or {}
        rs.setdefault("mark_ws_lag_ms", (pf.get("mark_ws") or {}).get("lag_ms"))
        rs.setdefault("book_lag_ms", (pf.get("fast_feed") or {}).get("lag_ms"))
    snap_avg, snap_p95 = _avg_p95(_speed_hist["snapshot"])
    fill_avg, fill_p95 = _avg_p95(_speed_hist["fill"])
    risk_avg, risk_p95 = _avg_p95(_speed_hist["risk"])
    rs["avg_snapshot_ms"] = round(snap_avg, 1)
    rs["p95_snapshot_ms"] = round(snap_p95, 1)
    rs["avg_fill_ms"] = round(fill_avg, 1)
    rs["p95_fill_ms"] = round(fill_p95, 1)
    rs["avg_risk_ms"] = round(risk_avg, 1)
    rs["p95_risk_ms"] = round(risk_p95, 1)
    tick = rs.get("bot_position_tick_ms")
    rs["grade_tick"] = _speed_grade(
        float(tick) if tick is not None else None, good=35, warn=120
    )
    rs["grade_mark"] = _speed_grade(
        rs.get("mark_ws_lag_ms"), good=80, warn=250
    )
    rs["grade_book"] = _speed_grade(
        rs.get("book_lag_ms"), good=80, warn=250
    )
    rs["grade_cache"] = _speed_grade(
        rs.get("exchange_cache_age_ms"), good=400, warn=900
    )
    return rs


def _speed_log_message(rs: dict) -> str:
    tick = rs.get("bot_position_tick_ms")
    iv = rs.get("bot_position_interval_ms")
    ago = rs.get("bot_position_ago_ms")
    return (
        f"bot tick={tick}ms iv={iv}ms ago={ago}ms"
        f" | markLag={rs.get('mark_ws_lag_ms')}ms bookLag={rs.get('book_lag_ms')}ms"
        f" | cache={rs.get('exchange_cache_age_ms')}ms"
        f" | snap={rs.get('monitor_snapshot_ms')}ms fill={rs.get('monitor_fill_ms')}ms"
        f" | riskREST={rs.get('monitor_risk_ms')}ms×{rs.get('monitor_risk_count', 0)}"
    )


def _maybe_log_speed_event(rs: dict) -> None:
    global _last_speed_log_ts
    now = time.time()
    if now - _last_speed_log_ts < SPEED_LOG_EVERY_SEC:
        return
    _last_speed_log_ts = now
    _local_events.appendleft(
        {
            "kind": "SPEED",
            "ts": datetime.now().strftime("%H:%M:%S"),
            "msg": _speed_log_message(rs),
        }
    )


def _merge_events(live: dict | None) -> list[dict]:
    api_ev = list((live or {}).get("events") or [])
    merged: list[dict] = []
    seen: set[str] = set()
    for ev in list(_local_events) + api_ev:
        key = "|".join(
            [
                str(ev.get("kind") or ""),
                str(ev.get("ts") or ""),
                str(ev.get("msg") or ev.get("symbol") or ""),
                str(ev.get("order_id") or ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(ev)
        if len(merged) >= MAX_EVENT_ROWS:
            break
    return merged


def display(
    *,
    bn_ok: bool,
    bn_ms: float,
    bn_err: str,
    bn_bal: float | None,
    lat_hist: deque,
    live: dict | None,
    live_ms: float,
    bot_err: str,
    bot_src: str,
    fallback_positions: list[dict],
    hb: dict | None,
    cached: bool = False,
    speed: dict | None = None,
    positions_override: list[dict] | None = None,
) -> None:
    lines: list[str] = []
    lines.append("╔" + "═" * 96 + "╗")
    lines.append("║" + " ELITE 9005 — FILL NET + KAPANIŞ SÜRESİ İZLEYİCİ ".center(96) + "║")
    lines.append("╚" + "═" * 96 + "╝")
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    avg_ms = sum(lat_hist) / len(lat_hist) if lat_hist else 0.0
    p95 = sorted(lat_hist)[int(len(lat_hist) * 0.95)] if len(lat_hist) >= 5 else avg_ms

    if hb is None and live:
        hb = live.get("heartbeat") or {}
    pos_iv = hb.get("position_interval_ms") if hb else None
    pos_ago = hb.get("position_ago") if hb else None
    pos_tick = hb.get("position_tick_ms") if hb else None
    pos_iv_s = f"{pos_iv:.0f}ms" if pos_iv is not None else f"~{ENV_POS_CHECK_MS:.0f}ms (env)"
    pos_ago_s = f"{float(pos_ago)*1000:.0f}ms önce" if pos_ago is not None else "—"
    cache_tag = " · önbellek" if cached else ""
    price_age = (
        int(time.time() - _display_est_ts)
        if _display_est_ts > 0
        else None
    )
    price_tag = (
        f" · fiyat {price_age}s"
        if price_age is not None and price_age >= 1
        else ""
    )

    lines.append(
        f"⏰ {ts}  |  poll {UPDATE_SEC:.2f}s  |  fiyat yenile {PRICE_DISPLAY_REFRESH_SEC:.0f}s"
        f"  |  min net > ${MIN_NET:.2f}{cache_tag}{price_tag}"
    )
    lines.append(f"  API: {MONITOR_API}")
    lines.append("")
    lines.append("── Hız özeti ──")
    lines.append(
        f"  🌐 Binance REST: son {bn_ms:.0f}ms  ort {avg_ms:.0f}ms  p95 {p95:.0f}ms  {_latency_bar(bn_ms)}"
    )
    bot_ms_s = f"{live_ms:.0f}ms" if live_ms > 0 else "—"
    src_tag = f" [{bot_src}]" if bot_src else ""
    tick_s = f"  (işlem {pos_tick:.1f}ms)" if pos_tick is not None else ""
    lines.append(
        f"  🤖 Bot snapshot: {bot_ms_s}{src_tag}  |  döngü: {pos_iv_s}  |  tick: {pos_ago_s}{tick_s}"
    )
    lines.append(
        f"  🔄 Borsa REST yenileme: {EXCHANGE_REFRESH_MS:.0f}ms"
        f"  |  ELITE_POSITION_CHECK_SEC={ENV_POS_CHECK_MS:.0f}ms"
    )
    pf = (hb or {}).get("price_feed") or {}
    mw = pf.get("mark_ws") or {}
    ff = pf.get("fast_feed") or {}
    mw_lag = mw.get("lag_ms")
    ff_lag = ff.get("lag_ms")
    lines.append(
        f"  📡 WS mark lag: {mw_lag if mw_lag is not None else '—'}ms"
        f"  |  bookTicker lag: {ff_lag if ff_lag is not None else '—'}ms"
    )

    rs = speed or {}
    lines.append("")
    lines.append("── Fiyat / uPnL okuma hızı ──")
    tick = rs.get("bot_position_tick_ms")
    iv = rs.get("bot_position_interval_ms")
    ago = rs.get("bot_position_ago_ms")
    lines.append(
        f"  Bot: döngü {iv if iv is not None else '—'}ms"
        f"  |  son tick {tick if tick is not None else '—'}ms"
        f"  {rs.get('grade_tick','')}  |  son güncelleme {ago if ago is not None else '—'}ms önce"
    )
    lines.append(
        f"  REST positionRisk: son {rs.get('exchange_position_poll_ms', rs.get('monitor_risk_ms', '—'))}ms"
        f"  min {rs.get('exchange_api_min_ms', '—')}ms"
        f"  |  önbellek {rs.get('exchange_cache_age_ms', '—')}ms {rs.get('grade_cache','')}"
        f"  (iv {rs.get('exchange_poll_iv_ms', rs.get('exchange_refresh_ms', '—'))}ms)"
    )
    lines.append(
        f"  REST bookTicker fill: {rs.get('monitor_fill_ms', '—')}ms"
        f" (ort {rs.get('avg_fill_ms', '—')})"
        f"  |  bot tick {rs.get('bot_position_interval_ms', '—')}ms"
        f"  timeout×{rs.get('exchange_poll_timeouts', 0)}"
    )
    lines.append(
        f"  Hedef: positionRisk ~340ms · cache yaşı <500ms · tek REST motor · 🟢=iyi 🟡=normal 🔴=yavaş"
    )

    lines.append("")
    lines.append("── Binance demo-fapi ──")
    bn_icon = "🟢" if bn_ok else "🔴"
    bal_s = f"${bn_bal:,.2f}" if bn_bal is not None else "—"
    err_s = f"  ⚠  {bn_err}" if not bn_ok and bn_err else "  ·"
    lines.append(f"  {bn_icon} Auth: {'OK' if bn_ok else 'FAIL'}  |  💰 Cüzdan: {bal_s}")
    lines.append(err_s)

    bot_up = live is not None
    api_connected = bool((live or {}).get("api_connected"))
    lines.append("")
    lines.append("── Bot (9005) ──")
    if not bot_up:
        lines.append("  🔴 Bot API yanıt yok")
        lines.append(f"  ⚠  {bot_err or '—'}")
        lines.append("  💡 ./scripts/elite_9005_process_ctl.sh start")
        fb = (
            f"  ↻ Binance doğrudan: {len(fallback_positions)} pozisyon"
            if fallback_positions
            else "  ·"
        )
        lines.append(fb)
        lines.append("  ·")
    else:
        ex_bal = float(live.get("exchange_balance") or live.get("balance") or 0)
        summary = live.get("summary") or {}
        elite = live.get("elite") or {}
        motor = live.get("motor") or {}
        lat = elite.get("last_position_update_latency_ms")
        lat_s = f"{float(lat):.1f}ms" if lat is not None else "—"
        rejects = motor.get("reject_stats") or {}
        top_rej = sorted(rejects.items(), key=lambda x: -int(x[1] or 0))[:3]
        rej_s = ", ".join(f"{k}:{v}" for k, v in top_rej) if top_rej else "—"
        lines.append(
            f"  {'🟢' if api_connected else '🟡'} API: {api_connected}"
            f"  |  bakiye: ${ex_bal:,.2f}"
            f"  |  açık: {summary.get('open_positions', '?')}/{summary.get('max_open', '?')}"
            f"  |  kapanan: {summary.get('closed_trades', 0)}"
        )
        lines.append(
            f"  ⚙  pozisyon gecikmesi: {lat_s}"
            f"  |  🎯 kuyruk: {motor.get('queue', '—')}"
            f"  |  açılan: {motor.get('orders_opened', '—')}"
        )
        lines.append(f"  📋 red: {rej_s}")
        th = (hb or {}).get("threads") or {}
        alive = sum(1 for v in th.values() if v)
        lines.append(
            f"  🧵 thread: {alive}/{len(th) or 0} canlı"
            f"  |  stall: {(hb or {}).get('position_stalls', 0)}"
            f"  |  restart: {(hb or {}).get('position_restarts', 0)}"
        )
        lines.append("  ·")

    positions = positions_override
    if positions is None:
        positions = ((live or {}).get("positions") or {}).get("open") or []
        if not positions and fallback_positions:
            positions = fallback_positions
    _track_local_events(positions)
    events = _merge_events(live)

    lines.append("")
    lines.append("── Demo Binance — pozisyon olay günlüğü ──")
    if events:
        for ev in events[:MAX_EVENT_ROWS]:
            lines.append("  " + _fmt_event_line(ev))
    else:
        lines.append("  (henüz olay yok — yeni açılış/kapanış burada)")
    for _ in range(max(0, MAX_EVENT_ROWS - len(events[:MAX_EVENT_ROWS]))):
        lines.append(" " * 72)

    lines.append("")
    lines.append("── Açık pozisyonlar (fill − fee − funding net) ──")
    hdr = (
        f"{'SYMBOL':<12}{'SD':<6}{'MARK':>8}{'FILL':>8}{'NET':>9}"
        f"{'TP?':>6}{'FILL$':>10}{'AGE':>7}"
    )
    lines.append(hdr)
    lines.append("─" * 72)
    total_mark = 0.0
    total_net = 0.0
    shown = positions[:MAX_OPEN_ROWS]
    for p in shown:
        sym = str(p.get("symbol") or "")[:12]
        side = str(p.get("side") or "")[:5]
        e = _display_est_for(p)
        total_mark += e["mark_gross"]
        total_net += e["final"]
        tp = "✅" if e["ready"] else "—"
        age = _fmt_age(_pos_age_sec(p))
        fill_px = f"${float(e['fill_px']):.4f}" if e.get("fill_px") else "—"
        src = "B" if e.get("source") == "book_fill" else "M"
        lines.append(
            f"{sym:<12}{side:<6}"
            f"${e['mark_gross']:>+7.2f}"
            f"${e['gross']:>+7.2f}"
            f"${e['final']:>+7.2f}"
            f"{tp:>6}"
            f"{fill_px:>10}"
            f"{age:>7} {src}"
        )
    for _ in range(MAX_OPEN_ROWS - len(shown)):
        lines.append(" " * 72)
    if shown:
        lines.append("─" * 72)
        lines.append(
            f"{'TOPLAM':<18}mark ${total_mark:>+7.2f}  net ${total_net:>+7.2f}"
            f"  (hedef > ${MIN_NET:.2f})  B=book M=mark"
        )
    else:
        lines.append("  (açık pozisyon yok)")
        lines.append(" " * 72)

    closed = ((live or {}).get("positions") or {}).get("closed") or []
    recent = closed[:MAX_CLOSED_ROWS]
    lines.append("")
    lines.append("── Son kapanan işlemler ──")
    hdr2 = f"{'SYMBOL':<10}{'SD':<6}{'NET':>8}{'S-FILL':>10}{'S-NET':>8}{'ACK':>7}{'SET':>7}{'TOT':>7}"
    lines.append(hdr2)
    lines.append("─" * 68)
    if recent:
        for c in recent:
            ex = c.get("close_execution") or {}
            sym = str(c.get("symbol") or "")[:10]
            side = str(c.get("side") or "")[:5]
            final = float(c.get("final_pnl") or c.get("wallet_pnl") or 0)
            s_fill = ex.get("signal_fill_px") or c.get("signal_fill_px")
            s_net = ex.get("signal_est_net") or c.get("signal_est_net")
            ack = ex.get("order_ack_ms") or c.get("order_ack_ms")
            settle = ex.get("settle_ms") or c.get("settle_ms")
            tot = ex.get("total_close_ms") or c.get("total_close_ms")
            fill_s = f"${float(s_fill):.4f}" if s_fill else "—"
            net_s = f"${float(s_net):+.2f}" if s_net is not None else "—"
            lines.append(
                f"{sym:<10}{side:<6}"
                f"${final:>+6.2f}"
                f"{fill_s:>10}"
                f"{net_s:>8}"
                f"{_fmt_ms(ack):>7}"
                f"{_fmt_ms(settle):>7}"
                f"{_fmt_ms(tot):>7}"
            )
    else:
        lines.append("  (henüz kapanış yok)")
    for _ in range(max(0, MAX_CLOSED_ROWS - len(recent))):
        lines.append(" " * 68)

    lines.append("")
    lines.append("Ctrl+C ile çık")
    _Screen.render(lines)


def main() -> None:
    lat_hist: deque[float] = deque(maxlen=120)
    prev_pos_keys: set[str] = set()
    _Screen.enter()
    try:
        while True:
            bn_ok, bn_ms, bn_err, bn_bal = _ping_binance_cached()
            if bn_ms > 0 and time.time() - _last_bn_ping_ts < 1.0:
                lat_hist.append(bn_ms)
            live, live_ms, bot_err, bot_src = _fetch_bot_snapshot()
            live, bot_err, cached = _sticky_live(live, bot_err)
            hb = _heartbeat_cached(live)
            fallback: list[dict] = []
            if live is None:
                fallback = _exchange_positions_fallback()
                if fallback and not bot_err:
                    bot_err = bot_err or "bot snapshot yok — borsa fallback"

            positions = ((live or {}).get("positions") or {}).get("open") or []
            if not positions and fallback:
                positions = list(fallback)
            pos_keys = {_pos_key(p) for p in positions if p.get("symbol")}
            force_prices = bool(pos_keys - prev_pos_keys or prev_pos_keys - pos_keys)
            prev_pos_keys = pos_keys
            fill_ms = _maybe_refresh_price_display(
                positions, live=live, force=force_prices
            )
            if fill_ms > 0:
                _speed_hist["fill"].append(fill_ms)

            now = time.time()
            global _last_risk_measure_ts, _last_risk_ms, _last_risk_count
            if RISK_MEASURE_EVERY_SEC > 0 and now - _last_risk_measure_ts >= RISK_MEASURE_EVERY_SEC:
                _last_risk_ms, _last_risk_count = _measure_position_risk_rest(hb)
                _last_risk_measure_ts = now
                if _last_risk_ms > 0:
                    _speed_hist["risk"].append(_last_risk_ms)

            if live_ms > 0:
                _speed_hist["snapshot"].append(live_ms)

            speed = _build_speed_metrics(
                live=live, live_ms=live_ms, fill_ms=fill_ms, hb=hb
            )
            _maybe_log_speed_event(speed)

            display(
                bn_ok=bn_ok,
                bn_ms=bn_ms,
                bn_err=bn_err,
                bn_bal=bn_bal,
                lat_hist=lat_hist,
                live=live,
                live_ms=live_ms,
                bot_err=bot_err,
                bot_src=bot_src,
                fallback_positions=fallback,
                hb=hb if isinstance(hb, dict) else None,
                cached=cached,
                speed=speed,
                positions_override=positions,
            )
            time.sleep(UPDATE_SEC)
    except KeyboardInterrupt:
        _Screen.leave()
        print("\n✅ İzleyici durduruldu\n")


if __name__ == "__main__":
    main()
