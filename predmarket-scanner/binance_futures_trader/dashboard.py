"""Binance Futures demo panel — port 8210."""
from __future__ import annotations

import json
import math
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, TypeVar

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "scenarios" / "binance_futures_demo.env")

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from binance_futures_trader import config as cfg
from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.db import (
    closed_trade_stats,
    closed_trade_stats_from_rows,
    equity,
    init_db,
    realized_pnl,
    set_meta,
)
from binance_futures_trader.portfolio import (
    effective_equity,
    enrich_closed,
    enrich_position,
    total_unrealized,
)
from binance_futures_trader.sync import sync_status, sync_with_exchange

STATIC = ROOT / "static"
HB = ROOT / "data" / "binance_futures.heartbeat.json"

_last_positions_fetch = 0.0
_last_balance_fetch = 0.0
_live_cache: dict[str, Any] = {
    "exchange_raw": [],
    "exchange_balance": None,
}
_bg_stop = threading.Event()
_bg_threads: list[threading.Thread] = []
_rest_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bn-dash-rest")

T = TypeVar("T")


def _call_timeout(fn: Callable[[], T], timeout: float, default: T) -> T:
    fut = _rest_pool.submit(fn)
    try:
        return fut.result(timeout=timeout)
    except (FuturesTimeout, Exception):
        return default


def _refresh_signals_bg() -> None:
    while not _bg_stop.is_set():
        try:
            client = _get_client()
            prices = _load_prices(client, live_only=True)
            if not prices:
                prices = _load_prices(client, live_only=False)
            _market_signals(client, prices)
        except Exception:
            pass
        _bg_stop.wait(cfg.SIGNAL_REFRESH_SEC)


def _sync_exchange_bg() -> None:
    while not _bg_stop.is_set():
        try:
            conn = init_db(cfg.DB_PATH)
            client = _get_client()
            if not client.paper:
                sync_with_exchange(conn, client)
            conn.close()
        except Exception:
            pass
        _bg_stop.wait(cfg.SYNC_INTERVAL_SEC)


def _start_background_workers() -> None:
    global _bg_threads
    if _bg_threads:
        return
    _bg_stop.clear()
    if cfg.MARK_WS_ENABLED:
        from binance_futures_trader.mark_ws import ensure_mark_feed_started

        ensure_mark_feed_started()
    _rest_pool.submit(_refresh_signals_bg_once)
    for target, name in (
        (_refresh_signals_bg, "bn-signals"),
        (_sync_exchange_bg, "bn-sync"),
    ):
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        _bg_threads.append(t)


def _refresh_signals_bg_once() -> None:
    try:
        client = _get_client()
        prices = _load_prices(client, live_only=True) or _load_prices(client)
        _market_signals(client, prices)
    except Exception:
        pass


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _start_background_workers()
    yield
    _bg_stop.set()
    if cfg.MARK_WS_ENABLED:
        from binance_futures_trader.mark_ws import stop_mark_feed

        stop_mark_feed()
    _rest_pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Binance Futures Demo", lifespan=_lifespan)
if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

_client: BinanceFuturesClient | None = None


def _get_client() -> BinanceFuturesClient:
    global _client
    if _client is None:
        _client = BinanceFuturesClient()
    return _client


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _load_prices(client: BinanceFuturesClient, *, live_only: bool = False) -> dict[str, float]:
    if cfg.MARK_WS_ENABLED:
        try:
            from binance_futures_trader.mark_ws import get_mark_prices

            ws = get_mark_prices()
            if ws:
                return ws
        except Exception:
            pass
    if live_only:
        return dict(client._last_prices)
    try:
        return client.all_prices()
    except Exception:
        return {}


def _price_feed_meta() -> dict[str, Any]:
    if not cfg.MARK_WS_ENABLED:
        return {"enabled": False, "source": "rest", "connected": False}
    try:
        from binance_futures_trader.mark_ws import feed_status

        return feed_status()
    except Exception:
        return {"enabled": True, "source": "websocket_mark_1s", "connected": False}


_signal_cache: tuple[float, list[dict[str, Any]], dict[str, list[float]]] = (
    0.0,
    [],
    {},
)


def _market_signals(
    client: BinanceFuturesClient,
    prices: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    """Watchlist sinyal taraması + mini grafik serileri."""
    global _signal_cache
    now = time.time()
    if now - _signal_cache[0] < 22 and _signal_cache[1]:
        return _signal_cache[1], _signal_cache[2]

    from binance_futures_trader.backtest import load_bt_cache
    from binance_futures_trader.cex_arb import build_cex_book
    from binance_futures_trader.learner import get_weights
    from binance_futures_trader.signals import analyze_coin

    bt_wrs = load_bt_cache()

    conn = init_db(cfg.DB_PATH)
    weights = get_weights(conn) if cfg.LEARNING_ENABLED else {}
    conn.close()
    cex_book = build_cex_book() if cfg.CEX_ARB_ENABLED else {}
    open_coins = set()
    try:
        conn2 = init_db(cfg.DB_PATH)
        open_coins = {
            str(r[0])
            for r in conn2.execute(
                "SELECT DISTINCT coin FROM positions WHERE closed_at IS NULL"
            ).fetchall()
        }
        conn2.close()
    except Exception:
        pass

    signals: list[dict[str, Any]] = []
    sparklines: dict[str, list[float]] = {}
    for coin in cfg.WATCHLIST:
        mark = prices.get(coin)
        if not mark or mark <= 0:
            continue
        candles: list = []
        try:
            candles = client.klines(coin, cfg.CANDLE_INTERVAL, 48)
            closes = [float(c["c"]) for c in candles if c.get("c")]
            if closes:
                sparklines[coin] = closes[-36:]
        except Exception:
            sparklines[coin] = []
        try:
            cs = analyze_coin(
                client,
                coin,
                mark,
                cex_book=cex_book,
                strategy_weights=weights,
            )
            from binance_futures_trader.leverage import compute_leverage

            lev, lev_reason = compute_leverage(
                coin,
                confidence=cs.confidence,
                total_score=cs.total_score,
                bt_wr=bt_wrs.get(coin, 0.55),
                candles=candles,
                funding=cs.funding,
                side=cs.side or "LONG",
            )
            signals.append(
                {
                    "coin": coin,
                    "mark": mark,
                    "side": cs.side or "",
                    "score": round(cs.total_score, 2),
                    "confidence": round(cs.confidence, 2),
                    "leverage": lev,
                    "leverage_reason": lev_reason,
                    "min_score": cfg.MIN_SCORE,
                    "has_signal": bool(cs.side),
                    "already_open": coin in open_coins,
                    "sparkline": sparklines.get(coin, []),
                    "parts": [
                        {"name": p.name, "score": p.score, "detail": p.detail}
                        for p in cs.parts[:8]
                    ],
                }
            )
        except Exception:
            signals.append(
                {
                    "coin": coin,
                    "mark": mark,
                    "side": "",
                    "score": 0,
                    "confidence": 0,
                    "min_score": cfg.MIN_SCORE,
                    "has_signal": False,
                    "already_open": coin in open_coins,
                    "parts": [],
                }
            )
    signals.sort(key=lambda x: abs(x.get("score") or 0), reverse=True)
    _signal_cache = (now, signals, sparklines)
    return signals, sparklines


def _portfolio(*, live_only: bool = False) -> dict[str, Any]:
    global _last_positions_fetch, _last_balance_fetch, _live_cache
    conn = init_db(cfg.DB_PATH)
    client = _get_client()
    now = time.time()
    open_rows = conn.execute(
        """
        SELECT id, coin, side, entry_price, stake_usd, contracts, leverage, score,
               strategies, opened_at, last_price, leg_type, tp_frac, sl_frac,
               hedge_of_id, COALESCE(on_exchange, 0) AS on_exchange,
               COALESCE(entry_fee_usd, 0) AS entry_fee_usd
        FROM positions WHERE closed_at IS NULL ORDER BY id DESC
        """
    ).fetchall()
    prices = _load_prices(client, live_only=live_only)
    exch_raw: list[dict[str, Any]] = []
    pos_interval = cfg.LIVE_POSITION_POLL_SEC if live_only else max(
        cfg.LIVE_POSITION_POLL_SEC, 4.0
    )
    if not client.paper and (now - _last_positions_fetch >= pos_interval):
        fresh = _call_timeout(
            client.exchange_positions,
            cfg.LIVE_REST_TIMEOUT_SEC,
            list(_live_cache.get("exchange_raw") or []),
        )
        if fresh:
            exch_raw = fresh
            _live_cache["exchange_raw"] = exch_raw
            _last_positions_fetch = now
        else:
            exch_raw = list(_live_cache.get("exchange_raw") or [])
    else:
        exch_raw = list(_live_cache.get("exchange_raw") or [])
    exchange_list = []
    for ep in exch_raw:
        mark = prices.get(ep["coin"]) or ep.get("mark_price")
        lev = int(ep.get("leverage") or cfg.LEVERAGE_DEFAULT)
        row = {
            "id": f"bn-{ep['coin']}-{ep['side']}",
            "coin": ep["coin"],
            "side": ep["side"],
            "entry_price": ep["entry_price"],
            "leverage": lev,
            "stake_usd": ep.get("notional_usd", 0) / max(lev, 1),
            "contracts": ep["contracts"],
            "opened_at": None,
            "leg_type": "exchange",
            "tp_frac": cfg.TP_PCT,
            "sl_frac": cfg.SL_PCT,
            "on_exchange": 1,
            "source": "binance_testnet",
        }
        enriched = enrich_position(row, mark)
        gross_bn = ep.get("unrealized_pnl")
        if gross_bn is not None:
            g = float(gross_bn)
            fees = float(enriched.get("fees_est_usd") or 0)
            enriched["unrealized_gross"] = round(g, 4)
            enriched["unrealized_net"] = round(g - fees, 4)
            enriched["unrealized_pnl"] = enriched["unrealized_net"]
        exchange_list.append(enriched)
    open_list = [
        enrich_position(dict(r), prices.get(str(r["coin"])))
        for r in open_rows
    ]
    local_on_exchange = [p for p in open_list if p.get("on_exchange")]
    local_simulated = [p for p in open_list if not p.get("on_exchange")]
    unrl_exch = sum(float(p.get("unrealized_pnl") or 0) for p in exchange_list)
    unrl = unrl_exch if exchange_list else total_unrealized(open_list)
    exch_bal = _live_cache.get("exchange_balance")
    fetch_bal = (not live_only) or (now - _last_balance_fetch >= cfg.LIVE_BALANCE_POLL_SEC)
    if fetch_bal and not client.paper:
        bal = _call_timeout(
            client.exchange_balance,
            cfg.LIVE_REST_TIMEOUT_SEC,
            _live_cache.get("exchange_balance"),
        )
        if bal is not None:
            exch_bal = bal
            _live_cache["exchange_balance"] = exch_bal
            _last_balance_fetch = now
            if exch_bal > 0:
                set_meta(conn, "exchange_balance", f"{exch_bal:.2f}")

    real = realized_pnl(conn)
    start = cfg.STARTING_BALANCE
    display_open = exchange_list if exchange_list else open_list
    deployed = sum(float(p.get("stake_usd") or 0) for p in display_open)
    notional_deployed = sum(
        float(p.get("notional_usd") or 0)
        or float(p.get("stake_usd") or 0) * max(1, int(p.get("leverage") or 1))
        for p in display_open
    )
    if exch_bal is not None and exch_bal > 0:
        wallet_usd = round(float(exch_bal), 2)
    else:
        wallet_usd = round(max(0.0, start + real - deployed), 2)
    # Toplam kasa = nakit + kilitli marjin + açık PnL (realize çift sayılmaz)
    total_equity = round(wallet_usd + deployed + unrl, 2)
    eq = total_equity
    pnl_total = round(total_equity - start, 2)
    performance_pct = round((total_equity - start) / start * 100, 3) if start > 0 else 0.0

    closed: list[sqlite3.Row] = []
    if not live_only:
        closed = conn.execute(
            """
            SELECT id, coin, side, entry_price, close_price, stake_usd, contracts,
                   leverage, tp_frac, sl_frac, score, strategies, opened_at, closed_at,
                   pnl_usd, pnl_gross_usd, entry_fee_usd, exit_fee_usd, funding_fee_usd, fees_usd,
                   exit_reason, leg_type,
                   COALESCE(on_exchange, 0) AS on_exchange, exchange_order_id
            FROM positions WHERE closed_at IS NOT NULL
            ORDER BY closed_at DESC LIMIT 120
            """
        ).fetchall()
    trade_stats = closed_trade_stats(conn)
    closed_enriched = [enrich_closed(dict(r)) for r in closed] if closed else []
    sync = sync_status(conn, client)
    strategy_weights = {}
    learning = {}
    if cfg.LEARNING_ENABLED:
        try:
            from binance_futures_trader.learner import get_weights, learning_summary

            strategy_weights = get_weights(conn)
            learning = learning_summary(conn)
        except Exception:
            pass
    phase2_block: dict[str, Any] = {}
    if cfg.PHASE2_ENABLED:
        try:
            from binance_futures_trader.risk_rules import daily_loss_status
            from binance_futures_trader.trade_journal import summarize as journal_summary

            phase2_block = {
                "enabled": True,
                "setup_name": cfg.SETUP_NAME,
                "risk_per_trade_pct": cfg.RISK_PER_TRADE_PCT,
                "daily_max_loss_pct": cfg.DAILY_MAX_LOSS_PCT,
                "rr_target": cfg.RR_TARGET,
                "daily": daily_loss_status(conn, start),
                "journal": journal_summary(max_recent=15),
            }
        except Exception as exc:
            phase2_block = {"enabled": True, "error": str(exc)[:200]}
    conn.close()

    hb = {}
    if HB.is_file():
        try:
            hb = json.loads(HB.read_text(encoding="utf-8"))
        except Exception:
            pass

    watch = {c: prices.get(c) for c in cfg.WATCHLIST if prices.get(c)}
    primary_n = len(exchange_list)

    key_hint = (cfg.API_KEY[:8] + "…") if cfg.API_KEY else None
    testnet_urls = [
        "https://testnet.binancefuture.com/en/futures/BTCUSDT",
        "https://demo.binancefuture.com/en/futures/BTCUSDT",
    ]

    payload: dict[str, Any] = {
        "starting_balance": start,
        "performance_pct": performance_pct,
        "equity": eq,
        "total_equity": total_equity,
        "learning": learning,
        "strategy_weights": strategy_weights,
        "wallet_usd": wallet_usd,
        "open_in_market_usd": round(deployed, 2),
        "pnl_total_usd": pnl_total,
        "exchange_balance": exch_bal,
        "trade_stats": trade_stats,
        "testnet_urls": testnet_urls,
        "api_key_hint": key_hint,
        "where_to_look": (
            "Pozisyonlar yalnızca Binance FUTURES TESTNET hesabında görünür — "
            "binance.com ana hesabında veya spot cüzdanda görünmez."
        ),
        "realized_pnl": real,
        "unrealized_pnl": round(unrl, 2),
        "target_daily_usd": cfg.STARTING_BALANCE * cfg.TARGET_DAILY_PCT,
        "active_capital_pct": cfg.ACTIVE_CAPITAL_PCT,
        "deployable_usd": round(eq * cfg.ACTIVE_CAPITAL_PCT, 2),
        "deployed_usd": round(deployed, 2),
        "exchange_deployed_usd": round(deployed, 2),
        "notional_deployed_usd": round(notional_deployed, 2),
        "mode": cfg.MODE,
        "strategy_profile": cfg.STRATEGY_PROFILE,
        "candle_interval": cfg.CANDLE_INTERVAL,
        "watchlist_count": len(cfg.WATCHLIST),
        "tp_pct": cfg.TP_PCT,
        "sl_pct": cfg.SL_PCT,
        "leverage": cfg.LEVERAGE_DEFAULT,
        "leverage_min": cfg.LEVERAGE_MIN,
        "leverage_max": cfg.LEVERAGE_MAX,
        "watchlist_prices": watch,
        "heartbeat": hb,
        "exchange_positions": exchange_list,
        "exchange_open_count": len(exchange_list),
        "open_positions": exchange_list,
        "local_positions": open_list,
        "local_simulated_count": len(local_simulated),
        "open_primary_count": primary_n,
        "open_total_count": len(exchange_list),
        "sync": sync,
        "sync_ok": sync.get("in_sync", False) and not client.paper,
        "paper_mode": client.paper,
        "api_connected": not client.paper and client._auth_error is None,
        "prices_updated_at": hb.get("ts"),
        "price_feed": _price_feed_meta(),
        "panel_poll_ms": cfg.PANEL_POLL_MS,
        "panel_full_poll_ms": cfg.PANEL_FULL_POLL_MS,
        "intelligence": {
            "cex_arb": cfg.CEX_ARB_ENABLED,
            "gaps": cfg.GAP_ANALYSIS_ENABLED,
            "flow": cfg.FLOW_ANALYSIS_ENABLED,
            "news": cfg.NEWS_ENABLED,
            "learning": cfg.LEARNING_ENABLED,
        },
    }
    if phase2_block:
        payload["phase2"] = phase2_block
    if strategy_weights:
        payload["strategy_weights"] = strategy_weights
    mkt_signals = list(_signal_cache[1] or [])
    sparklines = dict(_signal_cache[2] or {})
    payload["market_signals"] = mkt_signals
    payload["sparklines"] = sparklines
    for p in exchange_list:
        c = str(p.get("coin") or "")
        if c in sparklines:
            p["sparkline"] = sparklines[c]
    payload["live_light"] = live_only
    if not live_only:
        payload["closed_positions"] = closed_enriched
    return _sanitize(payload)


@app.get("/api/health")
def api_health():
    from binance_futures_trader.mark_ws import feed_status

    pf = feed_status() if cfg.MARK_WS_ENABLED else {}
    return {
        "ok": True,
        "ts": int(time.time() * 1000),
        "price_feed": pf,
        "signals_cached": bool(_signal_cache[1]),
        "positions_cached": bool(_live_cache.get("exchange_raw")),
    }


@app.get("/api/data")
def api_data():
    return _portfolio(live_only=False)


@app.get("/api/live")
def api_live():
    return _portfolio(live_only=True)


@app.get("/static/crypto.html")
@app.get("/crypto")
def redirect_legacy_panel():
    return RedirectResponse(url="/", status_code=302)


@app.get("/api/crypto-prices")
@app.get("/api/futures-data")
@app.get("/api/engine-data")
@app.get("/api/crypto-scan")
def legacy_crypto_api():
    """Eski crypto.html istekleri — doğru panel /api/data."""
    p = _portfolio(live_only=True)
    return {
        "redirect": "/",
        "message": "Binance Futures paneli: /api/data kullanın",
        "prices": p.get("watchlist_prices") or {},
        "open_positions": p.get("open_positions") or [],
        "equity": p.get("equity"),
        "exchange_balance": p.get("exchange_balance"),
    }


@app.get("/", response_class=HTMLResponse)
def index():
    p = ROOT / "static" / "binance_futures.html"
    if p.is_file():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<html><body><h1>Binance Futures Demo</h1>"
        "<p><a href='/api/data'>/api/data</a></p></body></html>"
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=cfg.DASHBOARD_PORT)
