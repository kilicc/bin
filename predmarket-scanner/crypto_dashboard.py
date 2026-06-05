"""
Crypto-focused PredMarket Dashboard — Dark terminal theme, port 8001.

Usage:
    uvicorn crypto_dashboard:app --port 8001 --reload
    # ya da:
    python crypto_dashboard.py
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import pickle
import sqlite3
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

try:
    from config import DATA_DIR, settings
    DB_PATH: Path = settings.paper_db
    STARTING_BALANCE: float = settings.paper_starting_balance
    EDGE_THRESHOLD: float = settings.edge_threshold
except Exception:
    DATA_DIR = Path("data")
    DB_PATH = DATA_DIR / "paper.db"
    STARTING_BALANCE = 20.0
    EDGE_THRESHOLD = 0.06

CAL_PATH   = DATA_DIR / "calibration_data.pkl"
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

_GAMMA = "https://gamma-api.polymarket.com"
_CLOB  = "https://clob.polymarket.com"
_COINGECKO = "https://api.coingecko.com/api/v3"

# ── Kripto anahtar kelimeleri ──────────────────────────────────────────────
CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "ripple",
    "dogecoin", "doge", "binance", "bnb", "cardano", "ada", "avalanche", "avax",
    "polygon", "matic", "chainlink", "link", "polkadot", "dot", "uniswap", "uni",
    "litecoin", "ltc", "stellar", "xlm", "crypto", "defi", "nft", "coinbase",
    "halving", "etf", "altcoin", "memecoin", "blockchain", "tron", "trx",
    "near", "aptos", "apt", "sui", "pepe", "shib", "floki", "ton",
]

CRYPTO_COINS = {
    "bitcoin":     "BTC",
    "ethereum":    "ETH",
    "solana":      "SOL",
    "ripple":      "XRP",
    "dogecoin":    "DOGE",
    "binancecoin": "BNB",
    "cardano":     "ADA",
    "avalanche-2": "AVAX",
    "polkadot":    "DOT",
    "chainlink":   "LINK",
}


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _dumps(obj: Any) -> str:
    return json.dumps(_sanitize(obj))


def _is_crypto_market(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in CRYPTO_KEYWORDS)


# ═══════════════════════════════════════════════════════════════════════════
#  Caches
# ═══════════════════════════════════════════════════════════════════════════
_crypto_price_cache: dict[str, Any] = {"data": {}, "ts": 0.0}
_crypto_scan_cache:  dict[str, Any] = {"data": {}, "ts": 0.0}
_price_history_cache: dict[str, dict] = {}
_PRICE_HIST_TTL = 60
_CRYPTO_PRICE_TTL = 30
_CRYPTO_SCAN_TTL  = 60

try:
    import httpx as _httpx
    _HTTPX_OK = True
except ImportError:
    _HTTPX_OK = False


# ═══════════════════════════════════════════════════════════════════════════
#  CoinGecko — gerçek zamanlı kripto fiyatları
# ═══════════════════════════════════════════════════════════════════════════

async def _fetch_crypto_prices() -> dict[str, Any]:
    import time as _t
    now = _t.time()
    if now - _crypto_price_cache["ts"] < _CRYPTO_PRICE_TTL:
        return _crypto_price_cache["data"]

    result: dict[str, Any] = {}
    if not _HTTPX_OK:
        return result

    try:
        ids = ",".join(CRYPTO_COINS.keys())
        async with _httpx.AsyncClient(timeout=8.0, headers={"Accept": "application/json"}) as cl:
            r = await cl.get(
                f"{_COINGECKO}/simple/price",
                params={
                    "ids": ids,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_24hr_vol": "true",
                    "include_market_cap": "true",
                },
            )
            if r.status_code == 200:
                raw = r.json()
                for coin_id, sym in CRYPTO_COINS.items():
                    if coin_id in raw:
                        d = raw[coin_id]
                        result[sym] = {
                            "price":   d.get("usd", 0),
                            "change":  round(d.get("usd_24h_change", 0) or 0, 2),
                            "vol":     d.get("usd_24h_vol", 0),
                            "mcap":    d.get("usd_market_cap", 0),
                        }
    except Exception as exc:
        print(f"[crypto_prices] {exc}")

    _crypto_price_cache.update({"data": result, "ts": now})
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Polymarket — kripto market tarayıcısı
# ═══════════════════════════════════════════════════════════════════════════

async def _fetch_crypto_scan() -> dict[str, Any]:
    """
    Polymarket kripto market tarayıcısı.
    /events?tag_slug=crypto ile yalnızca kripto event'leri çeker;
    keyword filtresi yerine API'nin resmi etiket sistemi kullanılır.
    """
    import json as _j
    import time as _t2

    now = _t2.time()
    if now - _crypto_scan_cache["ts"] < _CRYPTO_SCAN_TTL:
        return _crypto_scan_cache["data"]

    result: dict[str, Any] = {
        "opportunities": [],
        "scanned": 0,
        "found": 0,
        "ts": datetime.utcnow().isoformat() + "Z",
    }

    # Kalibrasyon tablosu
    cal_lookup: dict[int, float] = {}
    if CAL_PATH.exists():
        try:
            with open(CAL_PATH, "rb") as f:
                cal_data: list = pickle.load(f)
            bins: dict[int, dict] = defaultdict(lambda: {"hits": 0, "n": 0})
            for item in cal_data:
                try:
                    p = float(item[0])
                    outcome = bool(item[-1])
                    bi = min(9, int(p * 10))
                    bins[bi]["hits"] += 1 if outcome else 0
                    bins[bi]["n"] += 1
                except Exception:
                    pass
            for bi, b in bins.items():
                if b["n"] >= 5:
                    cal_lookup[bi] = b["hits"] / b["n"]
        except Exception:
            pass

    if not _HTTPX_OK:
        _crypto_scan_cache.update({"data": result, "ts": now})
        return result

    open_mids: set[str] = set()
    try:
        if DB_PATH.exists():
            _c = sqlite3.connect(str(DB_PATH))
            open_mids = {str(r[0]) for r in _c.execute(
                "SELECT market_id FROM positions WHERE closed_at IS NULL"
            ).fetchall()}
            _c.close()
    except Exception:
        pass

    try:
        async with _httpx.AsyncClient(
            timeout=12.0,
            headers={"User-Agent": "predmarket-crypto/0.1", "Accept": "application/json"},
            follow_redirects=True,
        ) as cl:
            # /events?tag_slug=crypto → yalnızca kripto event'leri (resmi etiket)
            crypto_markets: list[dict] = []
            seen_ids: set[str] = set()
            offset = 0

            while len(crypto_markets) < 300:
                r = await cl.get(
                    f"{_GAMMA}/events",
                    params={
                        "active": "true", "closed": "false",
                        "limit": 100, "offset": offset,
                        "tag_slug": "crypto",
                        "order": "volume24hr", "ascending": "false",
                    },
                )
                if r.status_code != 200:
                    break
                events_batch = r.json()
                if not events_batch:
                    break

                for ev in events_batch:
                    for m in (ev.get("markets") or []):
                        if not m.get("active") or m.get("closed"):
                            continue
                        mid = str(m.get("id") or "")
                        if not mid or mid in seen_ids:
                            continue
                        seen_ids.add(mid)
                        crypto_markets.append(m)

                offset += len(events_batch)
                if len(events_batch) < 100:
                    break

            result["scanned"] = len(crypto_markets)
            opps = []

            for mkt in crypto_markets:
                try:
                    end_date = mkt.get("endDate") or mkt.get("closedTime")
                    if not end_date:
                        continue
                    end_dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
                    hours_left = (end_dt.timestamp() - _t2.time()) / 3600
                    if hours_left < 0.5 or hours_left > 720:
                        continue

                    raw_op = mkt.get("outcomePrices", "[]")
                    op = _j.loads(raw_op) if isinstance(raw_op, str) else (raw_op or [])
                    if not op:
                        continue
                    yes_price = float(op[0])
                    if yes_price <= 0.01 or yes_price >= 0.99:
                        continue

                    bi = min(9, int(yes_price * 10))
                    true_yes = cal_lookup.get(bi)
                    if true_yes is None:
                        true_yes = 0.5

                    edge_yes = true_yes - yes_price
                    edge_no  = (1.0 - true_yes) - (1.0 - yes_price)
                    best_edge = max(edge_yes, edge_no)
                    side = "YES" if edge_yes >= edge_no else "NO"

                    vol = float(mkt.get("volume24hr") or mkt.get("volume") or 0)
                    liq = float(mkt.get("liquidity") or mkt.get("liquidityNum") or 0)
                    mid = str(mkt.get("id", ""))

                    opps.append({
                        "market_id":    mid,
                        "question":     (mkt.get("question") or "")[:90],
                        "side":         side,
                        "yes_price":    round(yes_price, 4),
                        "cur_price":    round(yes_price if side == "YES" else 1 - yes_price, 4),
                        "true_prob":    round(true_yes if side == "YES" else 1 - true_yes, 4),
                        "edge":         round(best_edge, 4),
                        "hours_left":   round(hours_left, 1),
                        "volume_24h":   round(vol, 0),
                        "liquidity":    round(liq, 0),
                        "has_position": mid in open_mids,
                    })
                except Exception:
                    pass

            opps.sort(key=lambda x: x["edge"], reverse=True)
            result["opportunities"] = opps[:40]
            result["found"] = len(opps)

    except Exception as exc:
        print(f"[crypto_scan] {exc}")

    _crypto_scan_cache.update({"data": result, "ts": now})
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Fiyat geçmişi — tek market
# ═══════════════════════════════════════════════════════════════════════════

async def _fetch_price_hist(market_id: str, force: bool = False) -> dict[str, Any]:
    import json as _j
    import time as _t3
    now = _t3.time()
    cached = _price_history_cache.get(market_id)
    if cached and not force and (now - cached["ts"]) < _PRICE_HIST_TTL:
        return cached["data"]

    result: dict[str, Any] = {
        "market_id": market_id, "question": "",
        "history": [], "current_price": None, "error": None,
    }
    if not _HTTPX_OK:
        result["error"] = "httpx not installed"
        return result

    try:
        async with _httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "predmarket-crypto/0.1"},
            follow_redirects=True,
        ) as cl:
            param_key = "conditionId" if str(market_id).startswith("0x") else "id"
            r = await cl.get(f"{_GAMMA}/markets", params={param_key: market_id})
            if r.status_code != 200:
                result["error"] = f"Gamma {r.status_code}"
                return result
            markets = r.json()
            if not markets:
                result["error"] = "Not found"
                return result
            mkt = markets[0]
            result["question"] = (mkt.get("question") or "")[:80]

            raw_tok = mkt.get("clobTokenIds", "[]")
            tokens = _j.loads(raw_tok) if isinstance(raw_tok, str) else (raw_tok or [])
            if not tokens:
                result["error"] = "No token IDs"
                return result

            raw_op = mkt.get("outcomePrices", "[]")
            op = _j.loads(raw_op) if isinstance(raw_op, str) else (raw_op or [])
            if op:
                try:
                    result["current_price"] = round(float(op[0]), 4)
                except Exception:
                    pass

            pts: list = []
            for interval in ("1d", "max"):
                r2 = await cl.get(
                    f"{_CLOB}/prices-history",
                    params={"market": tokens[0], "interval": interval},
                )
                if r2.status_code == 200:
                    pts = r2.json().get("history", [])
                    if pts:
                        break

            if pts:
                result["history"] = [
                    {"t": int(h["t"]), "p": round(float(h["p"]), 4)} for h in pts
                ]
                result["current_price"] = round(float(pts[-1]["p"]), 4)
                result.pop("error", None)

    except Exception as exc:
        result["error"] = str(exc)[:120]

    _price_history_cache[market_id] = {"data": result, "ts": now}
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Portfolio — kripto filtrelenmiş
# ═══════════════════════════════════════════════════════════════════════════

def _read_crypto_portfolio() -> dict[str, Any]:
    empty = {
        "open_positions": [], "closed_positions": [],
        "stats": {
            "starting_balance": STARTING_BALANCE, "current_equity": STARTING_BALANCE,
            "realized_pnl": 0.0, "closed_trades": 0, "wins": 0,
            "win_rate": None, "open_trades": 0, "avg_edge": None,
        },
        "daily_pnl": [],
        "equity": [], "timestamps": [], "labels": [],
    }
    if not DB_PATH.exists():
        return empty

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    all_closed = conn.execute(
        "SELECT * FROM positions WHERE closed_at IS NOT NULL ORDER BY closed_at ASC"
    ).fetchall()
    all_open = conn.execute(
        "SELECT * FROM positions WHERE closed_at IS NULL"
    ).fetchall()

    closed = [r for r in all_closed if _is_crypto_market(r["question"] or "")]
    opens  = [r for r in all_open   if _is_crypto_market(r["question"] or "")]
    _pnl_eps = 1e-4
    closed = [r for r in closed if abs(float(r["pnl_usd"] or 0)) > _pnl_eps]

    agg = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END),0) wins, "
        "COALESCE(SUM(pnl_usd),0) total FROM positions WHERE closed_at IS NOT NULL "
        "AND ABS(COALESCE(pnl_usd, 0)) > 0.0001"
    ).fetchone()
    conn.close()

    equity = STARTING_BALANCE
    ts_list, eq_list, labels = [], [], []
    for row in closed:
        pnl = row["pnl_usd"] or 0.0
        equity += pnl
        ts_list.append(row["closed_at"])
        eq_list.append(round(equity, 4))
        q = (row["question"] or "")[:50]
        labels.append(f"{q} [{row['side']}] {pnl:+.2f}")

    n_closed = len(closed)
    wins = sum(1 for r in closed if (r["pnl_usd"] or 0) > 0.0001)
    total_pnl = sum((r["pnl_usd"] or 0) for r in closed)

    daily: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "n": 0, "wins": 0})
    for r in closed:
        d = (r["closed_at"] or "")[:10]
        pnl = r["pnl_usd"] or 0.0
        daily[d]["pnl"] += pnl
        if abs(pnl) <= 0.0001:
            continue
        daily[d]["n"] += 1
        if pnl > 0:
            daily[d]["wins"] += 1
    daily_list = [
        {"date": d, "pnl": round(v["pnl"], 4), "n": v["n"], "wins": v["wins"]}
        for d, v in sorted(daily.items(), reverse=True)
    ][:7]

    open_positions = [
        {
            "id": r["id"],
            "market_id": r["market_id"],
            "question": (r["question"] or "")[:80],
            "side": r["side"],
            "entry_price": round(r["entry_price"] or 0, 4),
            "true_prob": round(r["true_prob"] or 0, 4),
            "edge": round(r["edge"] or 0, 4),
            "stake_usd": round(r["stake_usd"] or 0, 2),
            "contracts": round(r["contracts"] or 0, 4),
            "opened_at": r["opened_at"],
            "rationale": (r["rationale"] or "")[:120],
        }
        for r in opens
    ]

    closed_positions = [
        {
            "question": (r["question"] or "")[:80],
            "side": r["side"],
            "entry_price": round(r["entry_price"] or 0, 4),
            "close_price": round(r["close_price"] or 0, 4),
            "true_prob": round(r["true_prob"] or 0, 4),
            "edge": round(r["edge"] or 0, 4),
            "stake_usd": round(r["stake_usd"] or 0, 2),
            "contracts": round(r["contracts"] or 0, 4),
            "pnl_usd": round(r["pnl_usd"] or 0, 4),
            "pnl_pct": round((r["pnl_usd"] or 0) / max(r["stake_usd"] or 1, 0.01) * 100, 2),
            "opened_at": r["opened_at"],
            "closed_at": r["closed_at"],
        }
        for r in reversed(closed)
    ]

    avg_edge = None
    if closed:
        edges = [r["edge"] or 0 for r in closed]
        avg_edge = round(sum(edges) / len(edges), 4)

    return {
        "open_positions": open_positions,
        "closed_positions": closed_positions,
        "equity": eq_list,
        "timestamps": ts_list,
        "labels": labels,
        "daily_pnl": daily_list,
        "stats": {
            "starting_balance": STARTING_BALANCE,
            "current_equity": round(equity, 4),
            "realized_pnl": round(total_pnl, 4),
            "closed_trades": n_closed,
            "wins": wins,
            "win_rate": round(wins / n_closed, 4) if n_closed > 0 else None,
            "open_trades": len(opens),
            "avg_edge": avg_edge,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Snapshot
# ═══════════════════════════════════════════════════════════════════════════

def _snapshot() -> dict[str, Any]:
    portfolio = _read_crypto_portfolio()
    return {
        "ts": datetime.utcnow().isoformat() + "Z",
        "portfolio": portfolio,
        "crypto_prices": _crypto_price_cache.get("data", {}),
        "crypto_scan":   _crypto_scan_cache.get("data", {}),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Live price enrichment
# ═══════════════════════════════════════════════════════════════════════════

async def _enrich(snap: dict[str, Any]) -> dict[str, Any]:
    positions = snap.get("portfolio", {}).get("open_positions", [])
    if not positions:
        return snap
    results = await asyncio.gather(
        *[_fetch_price_hist(p["market_id"]) for p in positions],
        return_exceptions=True,
    )
    for pos, res in zip(positions, results):
        if isinstance(res, Exception) or not isinstance(res, dict) or res.get("error"):
            pos["live_price"] = None
            pos["unrealized_pnl"] = None
        else:
            cp = res.get("current_price")
            if cp is not None:
                pos["live_price"] = cp
                sp = cp if pos["side"] == "YES" else (1.0 - cp)
                pos["unrealized_pnl"] = round(
                    pos.get("contracts", 0) * sp - pos.get("stake_usd", 0), 4
                )
            else:
                pos["live_price"] = None
                pos["unrealized_pnl"] = None
    return snap


# ═══════════════════════════════════════════════════════════════════════════
#  Background loops
# ═══════════════════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._clients:
            self._clients.remove(ws)

    async def broadcast(self, payload: dict) -> None:
        dead = []
        txt = _dumps(payload)
        for ws in list(self._clients):
            try:
                await ws.send_text(txt)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._clients)


manager = ConnectionManager()


async def _push_loop(interval: int = 10) -> None:
    while True:
        await asyncio.sleep(interval)
        if manager.count > 0:
            try:
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(None, _snapshot)
                data = await _enrich(data)
                await manager.broadcast(data)
            except Exception as exc:
                print(f"[crypto_dash] push: {exc}")


async def _crypto_price_loop() -> None:
    while True:
        try:
            await _fetch_crypto_prices()
        except Exception as exc:
            print(f"[crypto_price_loop] {exc}")
        await asyncio.sleep(30)


async def _crypto_scan_loop() -> None:
    while True:
        try:
            await _fetch_crypto_scan()
        except Exception as exc:
            print(f"[crypto_scan_loop] {exc}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_push_loop())
    asyncio.create_task(_crypto_price_loop())
    asyncio.create_task(_crypto_scan_loop())
    yield


# ═══════════════════════════════════════════════════════════════════════════
#  FastAPI
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(title="Crypto PredMarket Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/data")
async def api_data():
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _snapshot)
    return await _enrich(data)


@app.get("/api/crypto-prices")
async def api_crypto_prices():
    return await _fetch_crypto_prices()


@app.get("/api/crypto-scan")
async def api_crypto_scan():
    return await _fetch_crypto_scan()


@app.get("/api/price-history/{market_id}")
async def api_price_history(market_id: str):
    return await _fetch_price_hist(market_id, force=True)


@app.get("/api/futures-data")
async def api_futures_data():
    """Hyperliquid futures pozisyonları + market tarayıcı verisi."""
    import time as _t
    result: dict = {
        "open_positions": [],
        "closed_positions": [],
        "funding_scan": [],
        "stats": {},
        "ts": datetime.utcnow().isoformat() + "Z",
    }

    FUTURES_STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "20.0"))

    # ── DB'den pozisyonları oku ───────────────────────────────────────────────
    if DB_PATH.exists():
        try:
            _c = sqlite3.connect(str(DB_PATH))
            _c.row_factory = sqlite3.Row
            opens = _c.execute(
                "SELECT * FROM futures_positions WHERE closed_at IS NULL ORDER BY opened_at DESC"
            ).fetchall()
            closed = _c.execute(
                "SELECT * FROM futures_positions WHERE closed_at IS NOT NULL ORDER BY closed_at DESC LIMIT 50"
            ).fetchall()
            stats_row = _c.execute(
                "SELECT COUNT(*) n, "
                "COALESCE(SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END),0) wins, "
                "COALESCE(SUM(pnl_usd),0) total "
                "FROM futures_positions WHERE closed_at IS NOT NULL"
            ).fetchone()
            open_stake_row = _c.execute(
                "SELECT COALESCE(SUM(stake_usd),0) s FROM futures_positions WHERE closed_at IS NULL"
            ).fetchone()
            # Strateji istatistikleri
            try:
                strat_rows = _c.execute(
                    "SELECT strategy, wins, losses, total_pnl FROM strategy_stats"
                ).fetchall()
                result["strategy_stats"] = [
                    {
                        "strategy": r["strategy"],
                        "wins": r["wins"],
                        "losses": r["losses"],
                        "win_rate": round(r["wins"] / max(r["wins"]+r["losses"], 1), 4),
                        "total_pnl": round(r["total_pnl"], 4),
                    }
                    for r in strat_rows
                ]
            except Exception:
                result["strategy_stats"] = []
            _c.close()

            # Unrealized P&L hesapla (sonraki adımda all_mids ile doldurulacak)
            open_list = [dict(r) for r in opens]
            closed_list = [dict(r) for r in closed]
            n = stats_row["n"]
            realized_pnl = float(stats_row["total"])
            open_stake   = float(open_stake_row["s"])

            result["open_positions"]  = open_list
            result["closed_positions"] = closed_list
            result["stats"] = {
                "starting_balance": FUTURES_STARTING_BALANCE,
                "closed_trades": n,
                "wins": stats_row["wins"],
                "win_rate": round(stats_row["wins"] / n, 4) if n > 0 else None,
                "realized_pnl": round(realized_pnl, 4),
                "open_trades": len(opens),
                "open_stake": round(open_stake, 4),
            }
        except Exception as exc:
            print(f"[futures_data] DB: {exc}")

    # ── Hyperliquid'den anlık funding + fiyat + unrealized P&L ──────────────
    if _HTTPX_OK:
        try:
            async with _httpx.AsyncClient(
                timeout=10.0,
                headers={"User-Agent": "predmarket-hl/0.1", "Accept": "application/json"},
            ) as cl:
                r = await cl.post(
                    "https://api.hyperliquid.xyz/info",
                    json={"type": "metaAndAssetCtxs"},
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code == 200:
                    data = r.json()
                    universe = data[0].get("universe", []) if data else []
                    ctxs     = data[1] if len(data) > 1 else []

                    all_mids: dict[str, float] = {}
                    scan_rows = []

                    for u, ctx in zip(universe, ctxs):
                        if u.get("isDelisted"):
                            continue
                        try:
                            coin      = u["name"]
                            mark_px   = float(ctx.get("markPx") or 0)
                            funding   = float(ctx.get("funding") or 0)
                            oi        = float(ctx.get("openInterest") or 0)
                            oi_usd    = oi * mark_px
                            if mark_px <= 0:
                                continue
                            all_mids[coin] = mark_px
                            if oi_usd < 1_000_000:
                                continue
                            scan_rows.append({
                                "coin":    coin,
                                "mark_px": round(mark_px, 6),
                                "funding": round(funding * 100, 6),
                                "oi_usd":  round(oi_usd, 0),
                                "extreme": abs(funding) > 0.0003,
                            })
                        except Exception:
                            continue

                    scan_rows.sort(key=lambda x: abs(x["funding"]), reverse=True)
                    result["funding_scan"] = scan_rows[:50]

                    # Açık pozisyonların unrealized P&L ve canlı fiyatını hesapla
                    unrealized_total = 0.0
                    for pos in result["open_positions"]:
                        coin = pos.get("coin", "")
                        cur  = all_mids.get(coin)
                        if cur is None:
                            cur = pos.get("last_price")
                        if cur is None:
                            cur = pos.get("entry_price")
                        if cur:
                            contracts = float(pos.get("contracts") or 0)
                            entry     = float(pos.get("entry_price") or 0)
                            fund_paid = float(pos.get("funding_paid") or 0)
                            if pos.get("side") == "LONG":
                                price_pnl = contracts * (cur - entry)
                            else:
                                price_pnl = contracts * (entry - cur)
                            upnl = price_pnl + fund_paid
                            pos["live_price"]      = round(cur, 6)
                            pos["unrealized_pnl"]  = round(upnl, 4)
                            pos["unrealized_pct"]  = round(upnl / max(float(pos.get("stake_usd") or 1), 0.01) * 100, 2)
                            unrealized_total += upnl

                    # Bakiye hesapla
                    s = result["stats"]
                    realized = s.get("realized_pnl", 0.0)
                    equity   = FUTURES_STARTING_BALANCE + realized + unrealized_total
                    open_stk = s.get("open_stake", 0.0)
                    s["unrealized_pnl"]  = round(unrealized_total, 4)
                    s["equity"]          = round(equity, 4)
                    s["available"]       = round(max(0.0, equity - open_stk), 4)
                    s["equity_pct"]      = round((equity - FUTURES_STARTING_BALANCE) / FUTURES_STARTING_BALANCE * 100, 2)

        except Exception as exc:
            print(f"[futures_data] HL: {exc}")

    result["runtime"] = _read_json_file(FUTURES_SCANNER_HEARTBEAT_JSON)
    result["module_hint"] = (
        "paper.db → futures_positions | süreç: crypto_futures_scanner.py"
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Crypto Engine API  (tamamen bağımsız modül — crypto_engine.py)
# ═══════════════════════════════════════════════════════════════════════════════

ENGINE_DB_PATH = Path(__file__).parent / "data" / "crypto_engine.db"
ENGINE_START_BALANCE = float(os.getenv("ENGINE_START_BALANCE", "20.0"))
ENGINE_HEARTBEAT_JSON = Path(__file__).parent / "data" / "crypto_engine.heartbeat.json"
FUTURES_SCANNER_HEARTBEAT_JSON = Path(__file__).parent / "data" / "crypto_futures_scanner.heartbeat.json"


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _engine_pos_row(r: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row → JSON-güvenli dict (motor açık/kapalı pozisyon)."""
    d = dict(r)
    out: dict[str, Any] = {}
    for k, v in d.items():
        if v is None:
            out[k] = None
        elif isinstance(v, (int, float, str, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    # Sayısal alanlar
    for fk in (
        "entry_price", "close_price", "stake_usd", "contracts", "score",
        "hl_funding", "bn_funding", "pnl_usd", "funding_paid", "last_price",
    ):
        if fk in out and out[fk] is not None:
            try:
                out[fk] = round(float(out[fk]), 8)
            except (TypeError, ValueError):
                pass
    if "leverage" in out and out["leverage"] is not None:
        try:
            out["leverage"] = int(out["leverage"])
        except (TypeError, ValueError):
            out["leverage"] = 1
    if "fear_greed" in out and out["fear_greed"] is not None:
        try:
            out["fear_greed"] = int(out["fear_greed"])
        except (TypeError, ValueError):
            pass
    if "whale_count" in out and out["whale_count"] is not None:
        try:
            out["whale_count"] = int(out["whale_count"])
        except (TypeError, ValueError):
            out["whale_count"] = 0
    return out


@app.get("/api/engine-data")
async def api_engine_data():
    """Crypto Engine (çok kaynaklı) veri endpoint'i."""
    result: dict = {
        "open_positions":  [],
        "closed_positions": [],
        "funding_scan":    [],
        "strategy_stats":  [],
        "data_log":        [],
        "stats":           {},
        "ts": datetime.utcnow().isoformat() + "Z",
    }

    # ── DB ──────────────────────────────────────────────────────────────────
    if ENGINE_DB_PATH.exists():
        try:
            _c = sqlite3.connect(str(ENGINE_DB_PATH))
            _c.row_factory = sqlite3.Row

            opens = _c.execute(
                "SELECT * FROM positions WHERE closed_at IS NULL ORDER BY opened_at DESC"
            ).fetchall()
            closed = _c.execute(
                "SELECT * FROM positions WHERE closed_at IS NOT NULL "
                "ORDER BY closed_at DESC LIMIT 120"
            ).fetchall()
            stats_row = _c.execute(
                "SELECT COUNT(*) n, "
                "COALESCE(SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END),0) wins, "
                "COALESCE(SUM(pnl_usd),0) total "
                "FROM positions WHERE closed_at IS NOT NULL "
                "AND ABS(COALESCE(pnl_usd, 0)) > 0.0001"
            ).fetchone()
            stake_row = _c.execute(
                "SELECT COALESCE(SUM(stake_usd),0) s FROM positions WHERE closed_at IS NULL"
            ).fetchone()
            strat_rows = []
            try:
                strat_rows = _c.execute(
                    "SELECT strategy,wins,losses,total_pnl FROM strategy_stats"
                ).fetchall()
            except Exception:
                pass
            log_rows = []
            try:
                log_rows = _c.execute(
                    "SELECT ts,fear_greed,top_coins,hl_extremes FROM data_log "
                    "ORDER BY id DESC LIMIT 10"
                ).fetchall()
            except Exception:
                pass
            _c.close()

            n = stats_row["n"]
            result["open_positions"]   = [_engine_pos_row(r) for r in opens]
            result["closed_positions"] = [_engine_pos_row(r) for r in closed]
            result["strategy_stats"]   = [
                {
                    "strategy": r["strategy"],
                    "wins":     r["wins"],
                    "losses":   r["losses"],
                    "win_rate": round(r["wins"] / max(r["wins"]+r["losses"], 1), 4),
                    "total_pnl": round(r["total_pnl"], 4),
                }
                for r in strat_rows
            ]
            result["data_log"] = [dict(r) for r in log_rows]
            result["stats"] = {
                "starting_balance": ENGINE_START_BALANCE,
                "closed_trades":    n,
                "closed_rows":      len(closed),
                "wins":             stats_row["wins"],
                "win_rate":         round(stats_row["wins"] / n, 4) if n > 0 else None,
                "realized_pnl":     round(float(stats_row["total"]), 4),
                "open_trades":      len(opens),
                "open_stake":       round(float(stake_row["s"]), 4),
            }
        except Exception as exc:
            print(f"[engine_data] DB: {exc}")

    # ── Hyperliquid anlık fiyat + unrealized ────────────────────────────────
    if _HTTPX_OK:
        try:
            async with _httpx.AsyncClient(timeout=10.0) as cl:
                r = await cl.post(
                    "https://api.hyperliquid.xyz/info",
                    json={"type": "metaAndAssetCtxs"},
                    headers={"Content-Type": "application/json"},
                )
                if r.status_code == 200:
                    data     = r.json()
                    universe = data[0].get("universe", []) if data else []
                    ctxs     = data[1] if len(data) > 1 else []
                    all_mids: dict[str, float] = {}
                    scan_rows = []
                    for u, ctx in zip(universe, ctxs):
                        if u.get("isDelisted"):
                            continue
                        try:
                            coin    = u["name"]
                            px      = float(ctx.get("markPx") or 0)
                            funding = float(ctx.get("funding") or 0)
                            oi      = float(ctx.get("openInterest") or 0) * px
                            if px <= 0:
                                continue
                            all_mids[coin] = px
                            if oi < 1_000_000:
                                continue
                            scan_rows.append({
                                "coin":    coin,
                                "mark_px": round(px, 6),
                                "funding": round(funding * 100, 6),
                                "oi_usd":  round(oi, 0),
                                "extreme": abs(funding) > 0.0002,
                            })
                        except Exception:
                            continue
                    scan_rows.sort(key=lambda x: abs(x["funding"]), reverse=True)
                    result["funding_scan"] = scan_rows[:60]

                    unrealized_total = 0.0
                    for pos in result["open_positions"]:
                        coin = pos.get("coin", "")
                        cur  = all_mids.get(coin) or pos.get("last_price") or pos.get("entry_price")
                        if cur:
                            c = float(pos.get("contracts") or 0)
                            e = float(pos.get("entry_price") or 0)
                            f = float(pos.get("funding_paid") or 0)
                            ppnl = c * (float(cur) - e) if pos.get("side") == "LONG" else c * (e - float(cur))
                            upnl = ppnl + f
                            pos["live_price"]     = round(float(cur), 6)
                            pos["unrealized_pnl"] = round(upnl, 4)
                            pos["unrealized_pct"] = round(upnl / max(float(pos.get("stake_usd") or 1), 0.01) * 100, 2)
                            unrealized_total += upnl

                    s = result["stats"]
                    realized = s.get("realized_pnl", 0.0)
                    equity   = ENGINE_START_BALANCE + realized + unrealized_total
                    stk      = s.get("open_stake", 0.0)
                    s["unrealized_pnl"] = round(unrealized_total, 4)
                    s["equity"]         = round(equity, 4)
                    s["available"]      = round(max(0.0, equity - stk), 4)
                    s["equity_pct"]     = round((equity - ENGINE_START_BALANCE) / ENGINE_START_BALANCE * 100, 2)

        except Exception as exc:
            print(f"[engine_data] HL: {exc}")

    # ── Fear & Greed ─────────────────────────────────────────────────────────
    try:
        async with _httpx.AsyncClient(timeout=6.0) as cl:
            fg_r = await cl.get("https://api.alternative.me/fng/?limit=1")
            if fg_r.status_code == 200:
                fg_data = fg_r.json()
                result["fear_greed"] = {
                    "value":       int(fg_data["data"][0]["value"]),
                    "label":       fg_data["data"][0]["value_classification"],
                    "updated_at":  fg_data["data"][0].get("timestamp", ""),
                }
    except Exception:
        result["fear_greed"] = {"value": 50, "label": "Neutral"}

    result["runtime"] = _read_json_file(ENGINE_HEARTBEAT_JSON)
    result["module_hint"] = (
        "crypto_engine.db → positions | süreç: crypto_engine.py (9 kaynak)"
    )
    return result


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        loop = asyncio.get_running_loop()
        try:
            initial = await loop.run_in_executor(None, _snapshot)
            initial = await _enrich(initial)
            await ws.send_text(_dumps(initial))
        except Exception as exc:
            print(f"[crypto_ws] initial: {exc}")
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


@app.get("/", response_class=HTMLResponse)
async def index():
    f = STATIC_DIR / "crypto.html"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return "<h1>static/crypto.html bulunamadı</h1>"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("crypto_dashboard:app", host="0.0.0.0", port=8001, reload=True)
