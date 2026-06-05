"""BTC likidasyon / OI / long-short — arka plan önbellek (panel snapshot dokunmaz).

Aşama 1: Binance demo-fapi (positionRisk, OI, forceOrders, L/S oranı) — borsa gerçeği.
Aşama 2: Fiyat etrafında cluster modeli (force order halkası + mark).
Aşama 3: CryptoQuant (opsiyonel, cache; API plan yoksa sessiz atlanır).
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.request import Request, urlopen

_lock = threading.Lock()
_ctx: dict[str, Any] = {"updated_at": 0.0, "fast_updated_at": 0.0, "rest_updated_at": 0.0}
_force_ring: deque[dict[str, Any]] = deque(maxlen=400)
_oi_ring: deque[tuple[float, float]] = deque(maxlen=48)  # (ts, oi_btc)
_refresh_inflight = False
_watcher_stop = threading.Event()
_watcher_thread: threading.Thread | None = None
_watcher_client: Any | None = None


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return _env_bool("MEGA_BTC_LIQ_ENABLED", True)


def fast_tick_sec() -> float:
    """Mark + cluster — REST yok (berserk2 fiyat veya son mark)."""
    return max(1.0, _env_float("MEGA_BTC_LIQ_FAST_SEC", 3.0))


def rest_refresh_sec() -> float:
    """Binance OI / L-S / forceOrders — arka plan thread."""
    v = os.getenv("MEGA_BTC_LIQ_REST_SEC") or os.getenv("MEGA_BTC_LIQ_REFRESH_SEC")
    try:
        sec = float(v) if v else 10.0
    except ValueError:
        sec = 10.0
    return max(5.0, sec)


def refresh_min_sec() -> float:
    """Geriye uyumluluk — REST aralığı."""
    return rest_refresh_sec()


def cq_refresh_min_sec() -> float:
    return max(120.0, _env_float("MEGA_BTC_LIQ_CQ_SEC", 300.0))


def _cq_key() -> str:
    return (os.getenv("CRYPTOQUANT_API_KEY") or "").strip()


def _record_force_events(rows: list[dict[str, Any]]) -> None:
    now = time.time()
    for row in rows or []:
        try:
            px = float(row.get("price") or row.get("ap") or 0)
            qty = float(row.get("origQty") or row.get("qty") or row.get("executedQty") or 0)
        except (TypeError, ValueError):
            continue
        if px <= 0 or qty <= 0:
            continue
        side = str(row.get("side") or "").upper()
        ts_ms = float(row.get("time") or row.get("T") or 0)
        ts = ts_ms / 1000.0 if ts_ms > 1e12 else now
        _force_ring.append(
            {
                "ts": ts,
                "price": px,
                "qty": qty,
                "usd": px * qty,
                "side": side,
            }
        )


def _hub_btc_mark() -> float:
    try:
        from elite_trader.berserk2_btc_context import get_btc_context

        px = float((get_btc_context() or {}).get("btc_price") or 0)
        return px if px > 0 else 0.0
    except Exception:
        return 0.0


def _fetch_binance_liq(client: Any) -> dict[str, Any]:
    """Demo-fapi — BTCUSDT (4 uç paralel, motor döngüsünü bloklamaz)."""
    out: dict[str, Any] = {
        "source": "binance_demo_fapi",
        "binance_updated_at": time.time(),
    }
    if client is None or getattr(client, "paper", False):
        out["binance_ok"] = False
        return out
    sym = "BTCUSDT"
    mark = 0.0
    parts: dict[str, Any] = {}

    def _prem() -> dict[str, Any]:
        return client._get("/fapi/v1/premiumIndex", {"symbol": sym})

    def _oi() -> dict[str, Any]:
        return client._get("/fapi/v1/openInterest", {"symbol": sym})

    def _ls() -> list:
        return client._get(
            "/futures/data/globalLongShortAccountRatio",
            {"symbol": sym, "period": "5m", "limit": 1},
        )

    def _fo() -> list:
        since = int((time.time() - 900) * 1000)
        return client._get(
            "/fapi/v1/allForceOrders",
            {"symbol": sym, "limit": 50, "startTime": since},
        )

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="btc-liq") as pool:
        futs = {
            pool.submit(_prem): "prem",
            pool.submit(_oi): "oi",
            pool.submit(_ls): "ls",
            pool.submit(_fo): "fo",
        }
        for fut in as_completed(futs):
            tag = futs[fut]
            try:
                parts[tag] = fut.result()
            except Exception as exc:
                parts[f"{tag}_error"] = str(exc)[:80]

    try:
        prem = parts.get("prem") or {}
        mark = float(prem.get("markPrice") or 0)
        out["mark_price"] = mark
    except Exception as exc:
        out["mark_error"] = str(exc)[:80]

    try:
        oi = parts.get("oi") or {}
        oi_btc = float(oi.get("openInterest") or 0)
        out["open_interest_btc"] = oi_btc
        if mark > 0 and oi_btc > 0:
            out["open_interest_usd"] = round(oi_btc * mark, 0)
        now = time.time()
        _oi_ring.append((now, oi_btc))
        if len(_oi_ring) >= 2:
            t0, o0 = _oi_ring[-2]
            if o0 > 0 and now > t0:
                out["oi_change_pct"] = round((oi_btc - o0) / o0 * 100.0, 3)
    except Exception as exc:
        out["oi_error"] = str(exc)[:80]
    if parts.get("oi_error"):
        out["oi_error"] = parts["oi_error"]

    try:
        ls = parts.get("ls")
        if isinstance(ls, list) and ls:
            row = ls[-1]
            out["ls_account_ratio"] = float(row.get("longShortRatio") or 0)
            out["ls_long_pct"] = round(float(row.get("longAccount") or 0) * 100.0, 1)
            out["ls_short_pct"] = round(float(row.get("shortAccount") or 0) * 100.0, 1)
    except Exception as exc:
        out["ls_error"] = str(exc)[:80]
    if parts.get("ls_error"):
        out["ls_error"] = parts["ls_error"]

    try:
        fo = parts.get("fo")
        if isinstance(fo, list):
            _record_force_events(fo)
            out["force_orders_n"] = len(fo)
    except Exception as exc:
        out["force_error"] = str(exc)[:80]
    if parts.get("fo_error"):
        out["force_error"] = parts["fo_error"]

    out.update(_build_clusters(mark, time.time()))
    out["binance_ok"] = mark > 0
    return out


def refresh_btc_liq_fast(*, force: bool = False) -> dict[str, Any]:
    """CPU-only — mark (hub/önbellek) + cluster; panel/motor <1ms okur."""
    if not enabled():
        return {}
    now = time.time()
    with _lock:
        cur = dict(_ctx)
    if not force and (now - float(cur.get("fast_updated_at") or 0)) < fast_tick_sec():
        return cur
    mark = float(cur.get("mark_price") or 0)
    if mark <= 0:
        mark = _hub_btc_mark()
    if mark <= 0:
        return cur
    patch = {
        "fast_updated_at": now,
        "updated_at": now,
        "mark_price": mark,
    }
    patch.update(_build_clusters(mark, now))
    with _lock:
        _ctx.update(patch)
        return dict(_ctx)


def _build_clusters(mark: float, now: float) -> dict[str, Any]:
    """Aşama 2 — mark etrafında likidasyon kümeleri (son 15 dk force orders)."""
    window = max(60.0, _env_float("MEGA_BTC_LIQ_CLUSTER_WINDOW_SEC", 900.0))
    bands = max(3, int(_env_float("MEGA_BTC_LIQ_CLUSTER_BANDS", 7)))
    if mark <= 0:
        return {
            "cluster_bias": "unknown",
            "cluster_summary": "mark yok",
            "clusters": [],
        }

    span = max(0.005, _env_float("MEGA_BTC_LIQ_CLUSTER_SPAN_PCT", 0.03))
    step = (2.0 * span) / max(1, bands - 1)
    grid: list[dict[str, Any]] = []
    for i in range(bands):
        pct = -span + step * i
        level = mark * (1.0 + pct)
        grid.append(
            {
                "pct_from_mark": round(pct * 100.0, 2),
                "price": round(level, 2),
                "long_liq_usd": 0.0,
                "short_liq_usd": 0.0,
            }
        )

    long_below = 0.0
    short_above = 0.0
    for ev in list(_force_ring):
        if now - float(ev.get("ts") or 0) > window:
            continue
        px = float(ev.get("price") or 0)
        usd = float(ev.get("usd") or 0)
        side = str(ev.get("side") or "").upper()
        if px <= 0 or usd <= 0:
            continue
        rel = (px - mark) / mark
        idx = int(round((rel + span) / step))
        idx = max(0, min(bands - 1, idx))
        if side == "SELL":
            grid[idx]["long_liq_usd"] += usd
            if px < mark:
                long_below += usd
        elif side == "BUY":
            grid[idx]["short_liq_usd"] += usd
            if px > mark:
                short_above += usd

    for g in grid:
        g["long_liq_usd"] = round(g["long_liq_usd"], 0)
        g["short_liq_usd"] = round(g["short_liq_usd"], 0)

    top_long = max(grid, key=lambda x: x["long_liq_usd"])
    top_short = max(grid, key=lambda x: x["short_liq_usd"])
    bias = "neutral"
    if long_below > short_above * 1.35 and long_below >= 50_000:
        bias = "long_liq_below"
    elif short_above > long_below * 1.35 and short_above >= 50_000:
        bias = "short_liq_above"

    parts = []
    if long_below > 0:
        parts.append(f"↓long liq ${long_below/1e6:.2f}M")
    if short_above > 0:
        parts.append(f"↑short liq ${short_above/1e6:.2f}M")
    if top_long["long_liq_usd"] > 10_000:
        parts.append(
            f"küme {top_long['pct_from_mark']:+.1f}% (${top_long['long_liq_usd']/1e3:.0f}k long)"
        )

    return {
        "cluster_bias": bias,
        "cluster_summary": " · ".join(parts) if parts else "düşük liq akışı",
        "long_liq_below_usd": round(long_below, 0),
        "short_liq_above_usd": round(short_above, 0),
        "nearest_long_cluster_pct": top_long.get("pct_from_mark"),
        "nearest_short_cluster_pct": top_short.get("pct_from_mark"),
        "clusters": grid,
    }


def _fetch_cryptoquant(cur: dict[str, Any]) -> dict[str, Any]:
    key = _cq_key()
    if not key or not _env_bool("MEGA_BTC_LIQ_CQ_ENABLED", True):
        return {}
    now = time.time()
    if (now - float(cur.get("cq_updated_at") or 0)) < cq_refresh_min_sec():
        return {}
    out: dict[str, Any] = {"cq_updated_at": now}
    base = "https://api.cryptoquant.com/v1/btc/market-data"
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "MegaBtcLiq/1.0"}
    for path, label in (
        ("/liquidations?exchange=binance&window=hour&limit=2", "liq"),
        ("/open-interest?exchange=binance&window=hour&limit=2", "oi"),
    ):
        try:
            req = Request(f"{base}{path}", headers=headers)
            with urlopen(req, timeout=18.0) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            rows = ((data or {}).get("result") or {}).get("data") or []
            if not rows:
                continue
            row = rows[-1] if isinstance(rows, list) else {}
            if label == "liq":
                out["cq_long_liq_usd"] = float(row.get("long_liquidations_usd") or 0)
                out["cq_short_liq_usd"] = float(row.get("short_liquidations_usd") or 0)
            else:
                out["cq_open_interest"] = float(row.get("open_interest") or 0)
            out["cq_ok"] = True
        except Exception as exc:
            msg = str(exc)[:100]
            if "403" in msg or "401" in msg:
                out["cq_status"] = "auth_or_plan"
                out["cq_note"] = "CryptoQuant API plan/izin — Binance cluster aktif"
            else:
                out["cq_error"] = msg
    return out


def refresh_btc_liq_rest(
    binance_client: Any | None = None, *, force: bool = False
) -> dict[str, Any]:
    """Tam Binance REST paketi — arka plan thread."""
    if not enabled():
        return {}
    now = time.time()
    with _lock:
        cur = dict(_ctx)
    if not force and (now - float(cur.get("rest_updated_at") or 0)) < rest_refresh_sec():
        return cur

    patch: dict[str, Any] = {
        "updated_at": now,
        "rest_updated_at": now,
        "fast_updated_at": now,
    }
    patch.update(_fetch_binance_liq(binance_client))
    cq = _fetch_cryptoquant({**cur, **patch})
    if cq:
        patch.update(cq)

    with _lock:
        _ctx.update(patch)
        return dict(_ctx)


def refresh_btc_liq(binance_client: Any | None = None, *, force: bool = False) -> dict[str, Any]:
    """REST due → tam paket; değilse hızlı cluster tick."""
    if not enabled():
        return {}
    now = time.time()
    with _lock:
        rest_age = now - float(_ctx.get("rest_updated_at") or 0)
    if force or rest_age >= rest_refresh_sec():
        return refresh_btc_liq_rest(binance_client, force=force)
    return refresh_btc_liq_fast(force=force)


def get_btc_liq() -> dict[str, Any]:
    with _lock:
        return dict(_ctx)


def liq_snapshot() -> dict[str, Any]:
    """Panel — salt okunur önbellek (<1ms)."""
    m = get_btc_liq()
    now = time.time()
    age = None
    if m.get("updated_at"):
        age = round(max(0.0, now - float(m["updated_at"])), 1)
    fast_age = None
    if m.get("fast_updated_at"):
        fast_age = round(max(0.0, now - float(m["fast_updated_at"])), 1)
    rest_age = None
    if m.get("rest_updated_at"):
        rest_age = round(max(0.0, now - float(m["rest_updated_at"])), 1)
    bias = str(m.get("cluster_bias") or "neutral")
    labels = {
        "long_liq_below": "Altında long liq",
        "short_liq_above": "Üstünde short liq",
        "neutral": "Nötr",
        "unknown": "—",
    }
    return {
        "summary": m.get("cluster_summary") or "—",
        "bias": bias,
        "bias_label": labels.get(bias, bias),
        "mark_price": m.get("mark_price"),
        "open_interest_usd": m.get("open_interest_usd"),
        "oi_change_pct": m.get("oi_change_pct"),
        "ls_account_ratio": m.get("ls_account_ratio"),
        "ls_long_pct": m.get("ls_long_pct"),
        "ls_short_pct": m.get("ls_short_pct"),
        "long_liq_below_usd": m.get("long_liq_below_usd"),
        "short_liq_above_usd": m.get("short_liq_above_usd"),
        "nearest_long_cluster_pct": m.get("nearest_long_cluster_pct"),
        "nearest_short_cluster_pct": m.get("nearest_short_cluster_pct"),
        "force_orders_n": m.get("force_orders_n"),
        "source": m.get("source"),
        "cq_ok": m.get("cq_ok"),
        "cq_long_liq_usd": m.get("cq_long_liq_usd"),
        "cq_short_liq_usd": m.get("cq_short_liq_usd"),
        "cq_note": m.get("cq_note"),
        "age_sec": age,
        "fast_age_sec": fast_age,
        "rest_age_sec": rest_age,
    }


def liquidation_proxy() -> float:
    """0–1 skor — hunter / mega scoring için."""
    m = get_btc_liq()
    below = float(m.get("long_liq_below_usd") or 0)
    above = float(m.get("short_liq_above_usd") or 0)
    oi = abs(float(m.get("oi_change_pct") or 0))
    total = below + above
    if total <= 0:
        return min(0.35, oi / 15.0)
    vol = min(1.0, total / 2_000_000.0)
    return min(1.0, vol * 0.75 + min(0.25, oi / 20.0))


def liq_entry_allowed(side: str) -> tuple[bool, str]:
    """Aşama 3 — hafif giriş filtresi (varsayılan yumuşak)."""
    if not _env_bool("MEGA_BTC_LIQ_ENTRY_GATE", False):
        return True, ""
    m = get_btc_liq()
    s = str(side or "LONG").upper()
    bias = str(m.get("cluster_bias") or "neutral")
    if s == "SHORT" and bias == "long_liq_below":
        below = float(m.get("long_liq_below_usd") or 0)
        if below >= _env_float("MEGA_BTC_LIQ_SHORT_MIN_USD", 200_000):
            return True, ""
    if s == "LONG" and bias == "short_liq_above":
        above = float(m.get("short_liq_above_usd") or 0)
        if above >= _env_float("MEGA_BTC_LIQ_LONG_MIN_USD", 200_000):
            return True, ""
    if s == "LONG" and bias == "long_liq_below":
        return False, "liq_long_into_cluster_below"
    if s == "SHORT" and bias == "short_liq_above":
        return False, "liq_short_into_cluster_above"
    return True, ""


def schedule_btc_liq_refresh(binance_client: Any | None = None) -> None:
    global _refresh_inflight
    with _lock:
        if _refresh_inflight:
            return
        now = time.time()
        cur = dict(_ctx)
        rest_due = (now - float(cur.get("rest_updated_at") or 0)) >= rest_refresh_sec()
        fast_due = (now - float(cur.get("fast_updated_at") or 0)) >= fast_tick_sec()
        if not rest_due and not fast_due:
            return
        _refresh_inflight = True

    def _run() -> None:
        global _refresh_inflight
        try:
            refresh_btc_liq(binance_client, force=False)
        finally:
            with _lock:
                _refresh_inflight = False

    threading.Thread(target=_run, name="mega-btc-liq", daemon=True).start()


def _watcher_sleep_sec() -> float:
    now = time.time()
    with _lock:
        cur = dict(_ctx)
    rest_left = rest_refresh_sec() - (now - float(cur.get("rest_updated_at") or 0))
    fast_left = fast_tick_sec() - (now - float(cur.get("fast_updated_at") or 0))
    return max(0.35, min(rest_left, fast_left))


def _watcher_loop() -> None:
    while not _watcher_stop.is_set():
        try:
            client = _watcher_client
            if client is None:
                try:
                    from elite_trader.mega_live import get_mega_client

                    client = get_mega_client()
                except Exception:
                    client = None
            if client is not None and not getattr(client, "paper", False):
                now = time.time()
                with _lock:
                    cur = dict(_ctx)
                if (now - float(cur.get("rest_updated_at") or 0)) >= rest_refresh_sec():
                    refresh_btc_liq_rest(client, force=False)
                elif (now - float(cur.get("fast_updated_at") or 0)) >= fast_tick_sec():
                    refresh_btc_liq_fast(force=False)
        except Exception:
            pass
        _watcher_stop.wait(timeout=_watcher_sleep_sec())


def start_btc_liq_watcher(binance_client: Any | None = None) -> None:
    global _watcher_thread, _watcher_client
    if not enabled():
        return
    _watcher_client = binance_client
    if _watcher_thread and _watcher_thread.is_alive():
        return
    _watcher_stop.clear()
    _watcher_thread = threading.Thread(
        target=_watcher_loop, name="mega-btc-liq-watch", daemon=True
    )
    _watcher_thread.start()
    schedule_btc_liq_refresh(binance_client)


def stop_btc_liq_watcher() -> None:
    _watcher_stop.set()
