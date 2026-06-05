"""
PredMarket Dashboard — FastAPI + WebSocket live panel.

Usage:
    uvicorn dashboard:app --port 8000 --reload
    # ya da doğrudan:
    python dashboard.py
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles


def _sanitize(obj: Any) -> Any:
    """Recursively replace NaN / Inf with None so json.dumps never throws."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _dumps(obj: Any) -> str:
    return json.dumps(_sanitize(obj))

# ── Config import (project-relative) ──────────────────────────────────────
try:
    from config import DATA_DIR, settings

    DB_PATH: Path = settings.paper_db
    STARTING_BALANCE: float = settings.paper_starting_balance
    MODE: str = settings.mode
    EDGE_THRESHOLD: float = settings.edge_threshold
except Exception:
    DATA_DIR = Path("data")
    DB_PATH = DATA_DIR / "paper.db"
    STARTING_BALANCE = 22_000.0
    MODE = "paper"
    EDGE_THRESHOLD = 0.06

# Senaryo paneli: PAPER_DB_PATH + STARTING_BALANCE (ör. paper_110.db / $110)
_paper_db_override = (os.getenv("PAPER_DB_PATH") or "").strip()
if _paper_db_override:
    DB_PATH = Path(_paper_db_override)
    if not DB_PATH.is_absolute():
        DB_PATH = Path(__file__).parent / DB_PATH
    try:
        STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", str(STARTING_BALANCE)))
    except ValueError:
        pass

SCENARIO_LABEL = (os.getenv("SCENARIO_NAME") or os.getenv("SCENARIO_LABEL") or "").strip()
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8000"))


def _live_trading_enabled() -> bool:
    return os.getenv("DISABLE_LIVE_TRADING", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )

CAL_PATH = DATA_DIR / "calibration_data.pkl"
CANDIDATES_PATH = DATA_DIR / "candidates.pkl"
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

# Panel: paper.db ana veri; canlı CLOB ayrı blok (live_portfolio.py)
def _live_trading_snapshot() -> dict[str, Any] | None:
    """Canlı blok: live.db her zaman; CLOB cüzdanı ayrı (hata olsa da pozisyonlar görünsün)."""
    if not _live_trading_enabled():
        return None
    import live_portfolio as lp

    portfolio: dict[str, Any]
    try:
        portfolio = lp.read_live_portfolio()
    except Exception as exc:
        print(f"[dashboard] live_portfolio: {exc}")
        return None

    wallet: dict[str, Any] = {}
    try:
        import live_wallet as lw

        wallet = lw.fetch_wallet_snapshot()
    except Exception as exc:
        print(f"[dashboard] live_wallet: {exc}")
        wallet = {"configured": False, "usdc": None, "error": str(exc)[:120]}

    st = portfolio.get("stats") or {}
    runtime: dict[str, Any] = {}
    try:
        runtime = lp.read_live_runtime()
    except Exception as exc:
        runtime = {"error": str(exc)[:120]}

    return {
        "wallet": wallet,
        "portfolio": portfolio,
        "runtime": runtime,
        "summary": {
            "usdc_balance": wallet.get("usdc"),
            "realized_pnl": st.get("realized_pnl", 0.0),
            "open_trades": st.get("open_trades", 0),
            "closed_trades": st.get("closed_trades", 0),
            "win_rate": st.get("win_rate"),
            "wr_tp_sl": st.get("wr_tp_sl"),
            "tp_count": st.get("tp_count", 0),
            "sl_count": st.get("sl_count", 0),
            "losses": st.get("losses", 0),
            "max_position_usd": wallet.get("max_position_usd"),
            "exit_rule": portfolio.get("exit_rule", {}),
        },
    }


def _polymarket_extras() -> dict[str, Any]:
    try:
        import live_portfolio as lp
        import live_wallet as lw

        lt = _live_trading_snapshot()
        if lt:
            p = lt["portfolio"]
            st = p.get("stats") or {}
            return {
                "polymarket_wallet": lt.get("wallet"),
                "live_portfolio": {
                    "db_path": p.get("db_path"),
                    "open_trades": st.get("open_trades", 0),
                    "closed_trades": st.get("closed_trades", 0),
                    "realized_pnl": st.get("realized_pnl", 0.0),
                },
                "live_trading": lt,
                "live_runtime": lt.get("runtime")
                or p.get("runtime")
                or lp.read_live_runtime(),
            }

        return {
            "polymarket_wallet": lw.fetch_wallet_snapshot(),
            "live_portfolio": lw.read_live_db_summary(),
            "live_trading": None,
            "live_runtime": lp.read_live_runtime(),
        }
    except Exception:
        return {
            "polymarket_wallet": None,
            "live_portfolio": None,
            "live_trading": None,
            "live_runtime": None,
        }


# ═══════════════════════════════════════════════════════════════════════════
#  Data readers
# ═══════════════════════════════════════════════════════════════════════════

def _read_portfolio() -> dict[str, Any]:
    """paper.db → equity curve + open/closed positions."""
    if not DB_PATH.exists():
        return {
            "timestamps": [],
            "equity": [],
            "labels": [],
            "pnl_bars": [],
            "candles": [],
            "stats": {
                "starting_balance": STARTING_BALANCE,
                "current_equity": STARTING_BALANCE,
                "realized_pnl": 0.0,
                "closed_trades": 0,
                "wins": 0,
                "win_rate": None,
                "open_trades": 0,
            },
            "open_positions": [],
            "closed_positions": [],
        }

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        from elite_trader.db import ensure_dashboard_schema

        ensure_dashboard_schema(conn)
    except Exception:
        pass

    closed = conn.execute(
        """SELECT id, question, side, entry_price, true_prob, edge,
                  stake_usd, contracts, opened_at, closed_at,
                  close_price, resolved_yes, pnl_usd, exit_reason
           FROM positions
           WHERE closed_at IS NOT NULL
           ORDER BY closed_at ASC"""
    ).fetchall()
    # P&L ≈ 0 kapanışları geçmişten çıkar (STALE-TP +$0.00 gibi satırlar)
    _pnl_eps = 1e-4
    closed = [r for r in closed if abs(float(r["pnl_usd"] or 0)) > _pnl_eps]

    open_rows = conn.execute(
        """SELECT id, market_id, question, side, entry_price, true_prob, edge,
                  stake_usd, contracts, opened_at, rationale, formula_score
           FROM positions WHERE closed_at IS NULL"""
    ).fetchall()

    agg = conn.execute(
        """SELECT COUNT(*) n,
                  COALESCE(SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END),0) wins,
                  COALESCE(SUM(pnl_usd),0) total_pnl
           FROM positions WHERE closed_at IS NOT NULL
             AND ABS(COALESCE(pnl_usd, 0)) > 0.0001"""
    ).fetchone()

    n_closed, wins, total_pnl = agg["n"], agg["wins"], agg["total_pnl"]

    # Equity curve
    equity = STARTING_BALANCE
    timestamps, equity_series, labels = [], [], []
    pnl_bars: list[dict] = []
    candles: list[dict] = []

    for i, row in enumerate(closed):
        pnl = row["pnl_usd"] or 0.0
        equity += pnl
        q = (row["question"] or "")[:50]
        timestamps.append(row["closed_at"])
        equity_series.append(round(equity, 4))
        labels.append(f"{q} [{row['side']}] PnL: ${pnl:+.2f}")

        pnl_bars.append({"x": i + 1, "y": round(pnl, 4), "label": q, "win": pnl > 0})

        entry = row["entry_price"] or 0.0
        close = row["close_price"] or 0.0
        true_p = row["true_prob"] or entry
        hi = max(entry, close, true_p)
        lo = min(entry, close, true_p)
        candles.append({
            "x": row["closed_at"],
            "open": round(entry, 4),
            "close": round(close, 4),
            "high": round(min(1.0, hi + 0.01), 4),
            "low": round(max(0.0, lo - 0.01), 4),
            "win": pnl > 0,
            "label": q,
            "pnl": round(pnl, 4),
            "edge": round(row["edge"] or 0.0, 4),
        })

    open_positions = [
        {
            "id": r["id"],
            "market_id": r["market_id"],
            "question": (r["question"] or "")[:70],
            "side": r["side"],
            "entry_price": round(r["entry_price"] or 0, 4),
            "true_prob": round(r["true_prob"] or 0, 4),
            "edge": round(r["edge"] or 0, 4),
            "stake_usd": round(r["stake_usd"] or 0, 2),
            "contracts": round(r["contracts"] or 0, 4),
            "opened_at": r["opened_at"],
            "rationale": (r["rationale"] or "")[:120],
            "formula_score": round(float(r["formula_score"] or 0), 3)
            if r["formula_score"] is not None
            else None,
        }
        for r in open_rows
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
            "pnl_pct": round((r["pnl_usd"] or 0) / (r["stake_usd"] or 1) * 100, 2),
            "resolved_yes": r["resolved_yes"],
            "exit_reason": r["exit_reason"] or "",
            "opened_at": r["opened_at"],
            "closed_at": r["closed_at"],
        }
        for r in reversed(closed)
    ]

    win_rate = (wins / n_closed) if n_closed > 0 else None

    avg_edge_row = conn.execute(
        "SELECT AVG(edge) FROM positions WHERE closed_at IS NOT NULL "
        "AND ABS(COALESCE(pnl_usd, 0)) > 0.0001"
    ).fetchone()
    avg_edge = round(float(avg_edge_row[0]), 4) if avg_edge_row and avg_edge_row[0] else None

    daily_rows = conn.execute(
        """SELECT DATE(closed_at) d, ROUND(SUM(pnl_usd),4) pnl,
                  COUNT(*) n, SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END) wins
           FROM positions WHERE closed_at IS NOT NULL
             AND ABS(COALESCE(pnl_usd, 0)) > 0.0001
           GROUP BY DATE(closed_at) ORDER BY d DESC LIMIT 7"""
    ).fetchall()
    daily_pnl = [{"date": r["d"], "pnl": r["pnl"], "n": r["n"], "wins": r["wins"]} for r in daily_rows]

    conn.close()

    return {
        "timestamps": timestamps,
        "equity": equity_series,
        "labels": labels,
        "pnl_bars": pnl_bars,
        "candles": candles,
        "stats": {
            "starting_balance": STARTING_BALANCE,
            "current_equity": round(equity, 4),
            "realized_pnl": round(float(total_pnl), 4),
            "closed_trades": n_closed,
            "wins": wins,
            "win_rate": round(win_rate, 4) if win_rate is not None else None,
            "open_trades": len(open_rows),
            "avg_edge": avg_edge,
        },
        "daily_pnl": daily_pnl,
        "open_positions": open_positions,
        "closed_positions": closed_positions,
    }


def _read_calibration() -> dict[str, Any]:
    """calibration_data.pkl → bucket curve + brier."""
    if not CAL_PATH.exists():
        return {"buckets": [], "total_points": 0, "brier": None}

    try:
        with open(CAL_PATH, "rb") as f:
            data: list = pickle.load(f)
    except Exception:
        return {"buckets": [], "total_points": 0, "brier": None}

    if not data:
        return {"buckets": [], "total_points": 0, "brier": None}

    n_bins = 10
    bins: dict[int, dict] = defaultdict(lambda: {"sum_p": 0.0, "hits": 0, "n": 0})

    for item in data:
        try:
            if isinstance(item, (list, tuple)):
                p = float(item[0])
                outcome = bool(item[-1])
            else:
                continue
        except (TypeError, IndexError):
            continue
        bi = min(n_bins - 1, int(p * n_bins))
        bins[bi]["sum_p"] += p
        bins[bi]["hits"] += 1 if outcome else 0
        bins[bi]["n"] += 1

    buckets = []
    for bi in range(n_bins):
        b = bins[bi]
        if b["n"] == 0:
            continue
        mean_p = b["sum_p"] / b["n"]
        actual = b["hits"] / b["n"]
        bias = actual - mean_p
        z = 1.96
        n, hits = b["n"], b["hits"]
        if 0 < actual < 1:
            denom = 1 + z * z / n
            centre = actual + z * z / (2 * n)
            margin = z * math.sqrt(actual * (1 - actual) / n + z * z / (4 * n * n))
            ci_lo = max(0.0, (centre - margin) / denom)
            ci_hi = min(1.0, (centre + margin) / denom)
        else:
            ci_lo = ci_hi = actual
        buckets.append(
            {
                "label": f"{bi/10:.1f}–{(bi+1)/10:.1f}",
                "mean_pred": round(mean_p, 4),
                "actual": round(actual, 4),
                "bias": round(bias, 4),
                "count": n,
                "ci_lo": round(ci_lo, 4),
                "ci_hi": round(ci_hi, 4),
            }
        )

    brier_total: float | None = None
    try:
        brier_total = round(
            sum((float(d[0]) - (1.0 if d[-1] else 0.0)) ** 2 for d in data) / len(data),
            4,
        )
    except Exception:
        pass

    return {"buckets": buckets, "total_points": len(data), "brier": brier_total}


def _read_candidates() -> list[dict]:
    """candidates.pkl → top market opportunities (best-effort parse)."""
    if not CANDIDATES_PATH.exists():
        return []
    try:
        with open(CANDIDATES_PATH, "rb") as f:
            raw = pickle.load(f)
        if not isinstance(raw, list):
            raw = list(raw)[:30]
        out = []
        for item in raw[:25]:
            if hasattr(item, "model_dump"):
                d = item.model_dump(exclude={"raw"})
            elif hasattr(item, "__dict__"):
                d = {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
            elif isinstance(item, dict):
                d = item
            else:
                continue
            row: dict[str, Any] = {
                "question": str(d.get("question", ""))[:70],
                "category": str(d.get("category", "—")),
                "yes_price": None,
                "volume_24h": float(d.get("volume_24h", 0)),
                "liquidity": float(d.get("liquidity", 0)),
            }
            # yes_price via outcomes list or direct attribute
            outcomes = d.get("outcomes", [])
            if outcomes:
                for o in outcomes:
                    name = str(getattr(o, "name", "") or o.get("name", "") if isinstance(o, dict) else "").lower()
                    price = float(getattr(o, "price", 0) if not isinstance(o, dict) else o.get("price", 0))
                    if name in {"yes", "evet"} or (len(outcomes) == 2 and name == ""):
                        row["yes_price"] = round(price, 4)
                        break
                if row["yes_price"] is None and outcomes:
                    try:
                        o = outcomes[0]
                        row["yes_price"] = round(float(getattr(o, "price", 0) if not isinstance(o, dict) else o.get("price", 0)), 4)
                    except Exception:
                        pass
            out.append(row)
        return out
    except Exception:
        return []


def _whale_stats_from_trades(trades: list, watchlist: set[str], top_n: int = 15) -> list[dict]:
    """history_trades.pkl yoksa recent_trades üzerinden whale sıralaması."""
    wallet_agg: dict[str, dict] = defaultdict(lambda: {"vol": 0.0, "n": 0, "yes": 0})
    for t in trades:
        w = getattr(t, "wallet", None) or (t.get("wallet") if isinstance(t, dict) else None)
        if not w:
            continue
        side = getattr(t, "side", None) or (t.get("side") if isinstance(t, dict) else "")
        size = float(getattr(t, "size_usd", 0) or (t.get("size_usd") if isinstance(t, dict) else 0))
        row = wallet_agg[w]
        row["vol"] += size
        row["n"] += 1
        if side == "YES":
            row["yes"] += 1
    top = sorted(wallet_agg.items(), key=lambda x: x[1]["vol"], reverse=True)[:top_n]
    return [
        {
            "addr": addr,
            "short": addr[:6] + "…" + addr[-4:],
            "vol": round(w["vol"]),
            "n": w["n"],
            "yes_pct": round(w["yes"] / w["n"], 3) if w["n"] else 0.0,
            "watched": addr in watchlist,
        }
        for addr, w in top
    ]


def _refresh_market_feed_sync() -> int:
    """
    Polymarket Data API → data/recent_trades.pkl (panel feed + halka grafikler).
    momentum_scanner bunu doldurmaz; reset sonrası boş kalır.
    """
    try:
        from markets.polymarket_data_api import PolymarketDataAPI
    except ImportError as exc:
        print(f"[market_feed] import: {exc}")
        return 0

    pages = int(os.getenv("MARKET_FEED_PAGES", "4"))
    days = float(os.getenv("MARKET_FEED_DAYS", "2"))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with PolymarketDataAPI(sleep_between_pages=0.2) as api:
            trades = list(api.iter_recent_trades(since=since, max_pages=max(1, pages)))
    except Exception as exc:
        print(f"[market_feed] API: {exc}")
        return 0

    if not trades:
        print("[market_feed] 0 trade — API yanıt vermedi")
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "recent_trades.pkl"
    with open(path, "wb") as f:
        pickle.dump(trades, f)
    print(f"[market_feed] {len(trades)} trade → {path.name}")
    return len(trades)


def _read_market_data() -> dict[str, Any]:
    """Whale leaderboard + recent-trade distributions + live trade feed."""
    result: dict[str, Any] = {
        "whale_stats": [],
        "recent_trades": [],
        "price_dist": [],
        "side_dist": {"YES": 0, "NO": 0},
        "dir_dist": {"open": 0, "close": 0},
        "total_history_trades": 0,
        "watchlist_size": 0,
    }

    # ── Watchlist ──────────────────────────────────────────────────────────
    watchlist: set[str] = set()
    for wl_file in ("whale_watchlist_curated.pkl", "whale_watchlist.pkl"):
        p = DATA_DIR / wl_file
        if p.exists():
            try:
                wl = pickle.load(open(p, "rb"))
                watchlist = wl if isinstance(wl, set) else set(wl)
                result["watchlist_size"] = len(watchlist)
                break
            except Exception:
                pass

    # ── History trades → whale leaderboard ────────────────────────────────
    hist_path = DATA_DIR / "history_trades.pkl"
    if hist_path.exists():
        try:
            hist: list = pickle.load(open(hist_path, "rb"))
            result["total_history_trades"] = len(hist)

            wallet_agg: dict[str, dict] = defaultdict(
                lambda: {"vol": 0.0, "n": 0, "yes": 0}
            )
            for t in hist:
                w = wallet_agg[t.wallet]
                w["vol"] += t.size_usd
                w["n"] += 1
                if t.side == "YES":
                    w["yes"] += 1

            top = sorted(wallet_agg.items(), key=lambda x: x[1]["vol"], reverse=True)[:15]
            result["whale_stats"] = [
                {
                    "addr": addr,
                    "short": addr[:6] + "…" + addr[-4:],
                    "vol": round(w["vol"]),
                    "n": w["n"],
                    "yes_pct": round(w["yes"] / w["n"], 3) if w["n"] else 0.0,
                    "watched": addr in watchlist,
                }
                for addr, w in top
            ]
        except Exception as exc:
            print(f"[dashboard] whale stats: {exc}")

    # ── Recent trades → live feed + distributions ──────────────────────────
    rec_path = DATA_DIR / "recent_trades.pkl"
    if rec_path.exists():
        try:
            recent: list = pickle.load(open(rec_path, "rb"))

            # Price distribution (10 buckets)
            pbuckets: dict[int, int] = defaultdict(int)
            for t in recent:
                bi = min(9, int(float(t.price) * 10))
                pbuckets[bi] += 1
            result["price_dist"] = [
                {
                    "label": f"{i/10:.1f}–{(i+1)/10:.1f}",
                    "count": pbuckets.get(i, 0),
                }
                for i in range(10)
            ]

            # Side + direction counts
            for t in recent:
                s = t.side
                if s in result["side_dist"]:
                    result["side_dist"][s] += 1
                d = t.direction
                if d in result["dir_dist"]:
                    result["dir_dist"][d] += 1

            # Sorted recent feed (newest first, cap at 80)
            sorted_rec = sorted(
                recent,
                key=lambda t: t.timestamp if hasattr(t, "timestamp") else 0,
                reverse=True,
            )[:80]
            result["recent_trades"] = [
                {
                    "wallet": t.wallet[:6] + "…" + t.wallet[-4:],
                    "wallet_full": t.wallet,
                    "side": t.side,
                    "price": round(float(t.price), 3),
                    "size_usd": round(float(t.size_usd), 2),
                    "direction": t.direction,
                    "watched": t.wallet in watchlist,
                    "ts": (
                        t.timestamp.isoformat()
                        if hasattr(t.timestamp, "isoformat")
                        else str(t.timestamp)
                    ),
                }
                for t in sorted_rec
            ]
        except Exception as exc:
            print(f"[dashboard] recent trades: {exc}")

    if not result["whale_stats"] and rec_path.exists():
        try:
            recent_fb: list = pickle.load(open(rec_path, "rb"))
            result["whale_stats"] = _whale_stats_from_trades(recent_fb, watchlist)
            if not result["total_history_trades"]:
                result["total_history_trades"] = len(recent_fb)
        except Exception as exc:
            print(f"[dashboard] whale fallback: {exc}")

    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Live price history — Polymarket CLOB + Gamma
# ═══════════════════════════════════════════════════════════════════════════

try:
    import httpx as _httpx
    _HTTPX_OK = True
except ImportError:
    _HTTPX_OK = False

_GAMMA = "https://gamma-api.polymarket.com"
_CLOB  = "https://clob.polymarket.com"

_price_cache: dict[str, dict[str, Any]] = {}
_PRICE_TTL = 45  # seconds
_price_warn_at: dict[str, float] = {}
_PRICE_WARN_COOLDOWN = 300  # seconds — aynı market için log spam önleme

_live_scan_cache: dict[str, Any] = {"data": {}, "ts": 0.0}
_LIVE_SCAN_TTL = 60  # seconds


async def _fetch_price_history(market_id: str, force: bool = False) -> dict[str, Any]:
    """Fetch YES-token price history for a market_id (Gamma integer id or conditionId)."""
    import json as _json

    now = datetime.utcnow().timestamp()
    cached = _price_cache.get(market_id)
    if cached and not force and (now - cached["ts"]) < _PRICE_TTL:
        return cached["data"]

    result: dict[str, Any] = {
        "market_id": market_id,
        "question": "",
        "token_id": None,
        "history": [],      # [{t: unix, p: float}]
        "current_price": None,
        "error": None,
    }

    if not _HTTPX_OK:
        result["error"] = "httpx not installed"
        return result

    _mid_short = market_id[:16] + "…"
    try:
        async with _httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": "predmarket-scanner/0.1", "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            from gamma_markets import resolve_gamma_market

            mkt = await resolve_gamma_market(client, market_id)
            if mkt is None:
                result["error"] = "Market not found in Gamma"
                import time as _t

                if _t.time() - _price_warn_at.get(market_id, 0) >= _PRICE_WARN_COOLDOWN:
                    _price_warn_at[market_id] = _t.time()
                    print(f"[price] ❌ Market not found in Gamma: {_mid_short}")
                return result
            result["question"] = (mkt.get("question") or "")[:80]

            # Parse clobTokenIds
            raw_tok = mkt.get("clobTokenIds", "[]")
            tokens: list[str] = (
                _json.loads(raw_tok) if isinstance(raw_tok, str) else (raw_tok or [])
            )
            if not tokens:
                result["error"] = "No clobTokenIds in Gamma response"
                print(f"[price] ❌ No clobTokenIds: {_mid_short}")
                return result

            yes_token = tokens[0]
            result["token_id"] = yes_token

            # Current price from outcomePrices
            raw_op = mkt.get("outcomePrices", "[]")
            op: list = _json.loads(raw_op) if isinstance(raw_op, str) else (raw_op or [])
            if op:
                try:
                    result["current_price"] = round(float(op[0]), 4)
                except (ValueError, TypeError):
                    pass

            # Step 2: Price history from CLOB
            pts: list = []
            for interval in ("1d", "max"):
                r2 = await client.get(
                    f"{_CLOB}/prices-history",
                    params={"market": yes_token, "interval": interval},
                )
                if r2.status_code == 200:
                    pts = r2.json().get("history", [])
                    if pts:
                        break
                    print(f"[price] ⚠️  CLOB {interval} returned empty history: {_mid_short}")
                else:
                    result["error"] = f"CLOB HTTP {r2.status_code} ({interval})"
                    print(f"[price] ❌ CLOB {r2.status_code} ({interval}): {_mid_short}")

            if pts:
                result["history"] = [
                    {"t": int(h["t"]), "p": round(float(h["p"]), 4)} for h in pts
                ]
                result["current_price"] = round(float(pts[-1]["p"]), 4)
                result.pop("error", None)
            elif result.get("current_price") is None:
                result["error"] = "No CLOB history and no outcomePrices"
                print(f"[price] ❌ No price data at all: {_mid_short}")

    except Exception as exc:
        result["error"] = str(exc)[:140]
        print(f"[price] ❌ EXCEPTION {_mid_short} | {exc}")

    _price_cache[market_id] = {"data": result, "ts": now}
    return result


async def _fetch_live_scan() -> dict[str, Any]:
    """Real-time scan: top Polymarket opportunities scored via calibration."""
    import json as _json
    import time as _time

    now = _time.time()
    if now - _live_scan_cache["ts"] < _LIVE_SCAN_TTL:
        return _live_scan_cache["data"]

    result: dict[str, Any] = {
        "opportunities": [],
        "scanned": 0,
        "found": 0,
        "ts": datetime.utcnow().isoformat() + "Z",
    }

    # Build calibration lookup  bucket_idx -> true_frequency
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
        _live_scan_cache.update({"data": result, "ts": now})
        return result

    # Currently open position market_ids (to mark in table)
    open_market_ids: set[str] = set()
    try:
        if DB_PATH.exists():
            _conn = sqlite3.connect(str(DB_PATH))
            _rows = _conn.execute(
                "SELECT market_id FROM positions WHERE closed_at IS NULL"
            ).fetchall()
            _conn.close()
            open_market_ids = {str(r[0]) for r in _rows}
    except Exception:
        pass

    try:
        from datetime import timezone as _tz
        import time as _time2

        async with _httpx.AsyncClient(
            timeout=12.0,
            headers={"User-Agent": "predmarket-scanner/0.1", "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            r = await client.get(
                f"{_GAMMA}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 100,
                    "order": "volume24hr",
                    "ascending": "false",
                },
            )
            if r.status_code != 200:
                _live_scan_cache.update({"data": result, "ts": now})
                return result

            markets = r.json()
            result["scanned"] = len(markets)
            opportunities = []

            for mkt in markets:
                try:
                    if not mkt.get("active") or mkt.get("closed"):
                        continue
                    end_date = mkt.get("endDate")
                    if not end_date:
                        continue
                    end_dt = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
                    hours_left = (end_dt.timestamp() - _time2.time()) / 3600
                    if hours_left < 1.0 or hours_left > 72.0:
                        continue

                    raw_op = mkt.get("outcomePrices", "[]")
                    op = _json.loads(raw_op) if isinstance(raw_op, str) else (raw_op or [])
                    if not op:
                        continue
                    yes_price = float(op[0])
                    if yes_price <= 0.02 or yes_price >= 0.98:
                        continue

                    bi = min(9, int(yes_price * 10))
                    true_yes = cal_lookup.get(bi)
                    if true_yes is None:
                        continue

                    edge_yes = true_yes - yes_price
                    edge_no = (1.0 - true_yes) - (1.0 - yes_price)
                    best_edge = max(edge_yes, edge_no)
                    side = "YES" if edge_yes >= edge_no else "NO"

                    vol = float(mkt.get("volume24hr") or mkt.get("volume_24h") or 0)
                    liq = float(mkt.get("liquidity") or 0)
                    market_id = str(mkt.get("id", ""))

                    opportunities.append({
                        "market_id": market_id,
                        "question": (mkt.get("question") or "")[:80],
                        "category": str(mkt.get("category") or "—")[:20],
                        "side": side,
                        "yes_price": round(yes_price, 4),
                        "cur_price": round(yes_price if side == "YES" else 1.0 - yes_price, 4),
                        "true_prob": round(true_yes if side == "YES" else 1.0 - true_yes, 4),
                        "edge": round(best_edge, 4),
                        "hours_left": round(hours_left, 1),
                        "volume_24h": round(vol, 0),
                        "liquidity": round(liq, 0),
                        "has_position": market_id in open_market_ids,
                    })
                except Exception:
                    pass

            opportunities.sort(key=lambda x: x["edge"], reverse=True)
            result["opportunities"] = opportunities[:30]
            result["found"] = len(opportunities)

    except Exception as exc:
        print(f"[live_scan] {exc}")

    _live_scan_cache.update({"data": result, "ts": now})
    return result


async def _live_scan_loop() -> None:
    """Background task: refresh live_scan cache every 60 s."""
    import asyncio as _aio
    while True:
        try:
            await _fetch_live_scan()
        except Exception as exc:
            print(f"[live_scan_loop] {exc}")
        await _aio.sleep(60)


async def _market_feed_loop() -> None:
    """recent_trades.pkl — panel Market Activity / feed / stream."""
    import asyncio as _aio

    interval = max(120, int(os.getenv("MARKET_FEED_INTERVAL_SEC", "300")))
    while True:
        try:
            loop = _aio.get_running_loop()
            n = await loop.run_in_executor(None, _refresh_market_feed_sync)
            if n > 0 and manager.count > 0:
                data = await loop.run_in_executor(None, _snapshot)
                data = await _enrich_snapshot(data)
                await manager.broadcast(data)
        except Exception as exc:
            print(f"[market_feed_loop] {exc}")
        await _aio.sleep(interval)


def _read_attribution() -> dict[str, Any] | None:
    try:
        from elite_trader.attribution import load_latest

        return load_latest()
    except Exception as exc:
        print(f"[dashboard] attribution: {exc}")
        return None


def _elite_pacing_snapshot(portfolio: dict[str, Any]) -> dict[str, Any] | None:
    elite_labels = (
        "elite_formula_800h",
        "elite_formula_cal_primary",
        "elite_formula_velocity",
        "elite_global_2x",
    )
    if "elite" not in str(DB_PATH).lower() and SCENARIO_LABEL not in elite_labels:
        return None
    try:
        from elite_trader.hourly_pacing import HourlyPacing

        p = HourlyPacing.from_env()
        p.realized_pnl = float((portfolio.get("stats") or {}).get("realized_pnl") or 0)
        return p.snapshot()
    except Exception:
        return None


def _elite_decision_snapshot(portfolio: dict[str, Any]) -> dict[str, Any] | None:
    elite_labels = (
        "elite_formula_800h",
        "elite_formula_cal_primary",
        "elite_formula_velocity",
        "elite_global_2x",
    )
    if SCENARIO_LABEL not in elite_labels and "elite" not in str(DB_PATH).lower():
        return None
    try:
        from elite_trader.decision_mode import alignment_status, decision_mode, mode_label_tr

        min_edge = float(os.getenv("ELITE_MIN_EDGE", "0.055"))
        min_score = float(os.getenv("ELITE_MIN_FORMULA_SCORE", "0.58"))
        open_pos = portfolio.get("open_positions") or []
        counts: dict[str, int] = {
            "aligned": 0,
            "cal_only": 0,
            "whale_only": 0,
            "conflict": 0,
        }
        for p in open_pos:
            edge = float(p.get("edge") or 0)
            sc = p.get("formula_score")
            if sc is None:
                continue
            st = alignment_status(edge, float(sc), min_edge=min_edge, min_score=min_score)
            counts[st] = counts.get(st, 0) + 1
        return {
            "mode": decision_mode(),
            "mode_label_tr": mode_label_tr(),
            "min_edge": min_edge,
            "min_score": min_score,
            "open_alignment": counts,
        }
    except Exception as exc:
        print(f"[dashboard] elite_decision: {exc}")
        return None



def _velocity_snapshot() -> dict[str, Any] | None:
    if SCENARIO_LABEL != "elite_formula_velocity" and "velocity" not in str(DB_PATH).lower():
        return None
    try:
        from elite_trader import scan_stats
        from elite_trader.attribution import velocity_metrics

        m24 = velocity_metrics(DB_PATH, hours=24.0)
        m6 = velocity_metrics(DB_PATH, hours=6.0)
        return {
            "opens_per_hour_24h": m24.get("opens_per_hour"),
            "closes_per_hour_24h": m24.get("closes_per_hour"),
            "opens_per_hour_6h": m6.get("opens_per_hour"),
            "closes_per_hour_6h": m6.get("closes_per_hour"),
            "avg_hold_minutes_24h": m24.get("avg_hold_minutes"),
            "scan_rejects": scan_stats.snapshot(),
        }
    except Exception as exc:
        print(f"[dashboard] velocity: {exc}")
        return None


def _is_elite_dashboard() -> bool:
    db = str(DB_PATH).lower()
    label = (SCENARIO_LABEL or "").lower()
    return (
        "elite" in db
        or "apex_2x" in db
        or label.startswith("elite_")
    )


def _elite_runtime_snapshot(portfolio: dict[str, Any]) -> dict[str, Any] | None:
    """Scanner tarama / fiyat / pozisyon canlı özeti (paper elite portları)."""
    if not _is_elite_dashboard():
        return None
    try:
        import sqlite3
        from pathlib import Path

        from elite_trader import scan_stats
        from elite_trader.runtime_status import age_seconds, heartbeat_path, read_heartbeat

        hb = read_heartbeat(DB_PATH)
        hb_path = heartbeat_path(DB_PATH)
        hb_mtime: float | None = None
        if hb_path.is_file():
            hb_mtime = hb_path.stat().st_mtime

        pos_chk = float(hb.get("position_check_sec") or 2) if hb else 2.0
        scan_int = float(hb.get("scan_interval_sec") or 10) if hb else 10.0
        hb_age = age_seconds(hb.get("ts") if hb else None)
        scan_age = age_seconds(hb.get("last_full_scan_at") if hb else None)
        chk_age = age_seconds(hb.get("last_position_check_at") if hb else None)

        scan_in_progress = bool(hb.get("scan_in_progress")) if hb else False
        try:
            last_scan_dur = float(hb.get("last_scan_duration_sec") or 0) if hb else 0.0
        except (TypeError, ValueError):
            last_scan_dur = 0.0
        alive_limit = max(pos_chk * 6, 20.0, last_scan_dur * 1.25)
        scan_fresh_limit = max(scan_int * 4.0, last_scan_dur * 2.0, 90.0)
        scanner_alive = scan_in_progress or (
            hb_age is not None and hb_age <= alive_limit
        )
        scan_recent = scan_in_progress or (
            scan_age is not None and scan_age <= scan_fresh_limit
        )

        open_n = int((portfolio.get("stats") or {}).get("open_trades") or 0)
        last_open = last_close = None
        recent: list[dict[str, Any]] = []
        if DB_PATH.exists():
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT MAX(opened_at) lo, MAX(closed_at) lc
                FROM positions
                """
            ).fetchone()
            if row:
                last_open = row["lo"]
                last_close = row["lc"]
            for r in conn.execute(
                """
                SELECT id, side, substr(question,1,48) q, stake_usd, pnl_usd,
                       exit_reason, opened_at, closed_at
                FROM positions
                ORDER BY COALESCE(closed_at, opened_at) DESC
                LIMIT 6
                """
            ):
                recent.append(
                    {
                        "id": r["id"],
                        "side": r["side"],
                        "question": r["q"],
                        "stake_usd": round(float(r["stake_usd"] or 0), 2),
                        "pnl_usd": round(float(r["pnl_usd"] or 0), 2)
                        if r["pnl_usd"] is not None
                        else None,
                        "exit_reason": r["exit_reason"],
                        "opened_at": r["opened_at"],
                        "closed_at": r["closed_at"],
                        "event": "close" if r["closed_at"] else "open",
                    }
                )
            conn.close()

        stats_path = Path(__file__).parent / "data" / f"scan_stats_{DB_PATH.stem}.json"
        stats_age: float | None = None
        if stats_path.is_file():
            stats_age = datetime.utcnow().timestamp() - stats_path.stat().st_mtime

        return {
            "port": int(os.getenv("DASHBOARD_PORT", "0") or 0),
            "scenario": SCENARIO_LABEL,
            "db_path": str(DB_PATH),
            "scanner_alive": scanner_alive,
            "scanner_status": (
                "scanning"
                if scan_in_progress
                else (
                    "running"
                    if scanner_alive
                    else ("stale" if hb else "offline")
                )
            ),
            "scan_in_progress": scan_in_progress,
            "last_scan_duration_sec": last_scan_dur if last_scan_dur > 0 else None,
            "markets_scanned": hb.get("markets_scanned") if hb else None,
            "markets_total": hb.get("markets_total") if hb else None,
            "heartbeat_age_sec": round(hb_age, 1) if hb_age is not None else None,
            "heartbeat_pid": hb.get("pid") if hb else None,
            "cycle": hb.get("cycle") if hb else None,
            "closed_last": hb.get("closed_last") if hb else None,
            "opened_last": hb.get("opened_last") if hb else None,
            "position_check_sec": pos_chk,
            "scan_interval_sec": scan_int,
            "last_full_scan_age_sec": round(scan_age, 1)
            if scan_age is not None
            else None,
            "last_check_age_sec": round(chk_age, 1) if chk_age is not None else None,
            "full_scan_recent": scan_recent,
            "last_open_at": last_open,
            "last_close_at": last_close,
            "open_positions": open_n,
            "scan_rejects": scan_stats.snapshot(),
            "stats_file_age_sec": round(stats_age, 1)
            if stats_age is not None
            else None,
            "recent_activity": recent,
            "paper_only": not _live_trading_enabled(),
        }
    except Exception as exc:
        print(f"[dashboard] elite_runtime: {exc}")
        return None


def _global_2x_snapshot(portfolio: dict[str, Any]) -> dict[str, Any] | None:
    if (
        SCENARIO_LABEL not in ("elite_global_2x", "elite_apex_2x_24h")
        and "global_2x" not in str(DB_PATH).lower()
        and "apex_2x" not in str(DB_PATH).lower()
    ):
        return None
    try:
        import pickle
        from pathlib import Path

        from elite_trader import scan_stats
        from elite_trader.attribution import velocity_metrics
        from elite_trader.capital_allocator import snapshot as cap_snap
        from elite_trader.decision_mode import mode_label_tr
        from elite_trader.hourly_pacing import HourlyPacing
        from elite_trader.success_formula import SuccessFormula

        p = HourlyPacing.from_env()
        p.realized_pnl = float((portfolio.get("stats") or {}).get("realized_pnl") or 0)
        pacing = p.snapshot()
        open_pos = portfolio.get("open_positions") or []
        open_stakes = [float(x.get("stake_usd") or 0) for x in open_pos]
        equity = float(os.getenv("STARTING_BALANCE", "22000")) + p.realized_pnl
        cap = cap_snap(equity, open_stakes)
        vel = velocity_metrics(DB_PATH, hours=24.0)
        formula = SuccessFormula.load()
        rules = list(formula.rules_tr[:5]) if formula else []
        n_elite = 0
        gw = Path(__file__).parent / "data" / "elite_global_wallets.pkl"
        if gw.is_file():
            n_elite = len(pickle.load(open(gw, "rb")))
        hedge_n = 0
        if DB_PATH.exists():
            import sqlite3

            c = sqlite3.connect(str(DB_PATH))
            row = c.execute(
                "SELECT COUNT(*) FROM positions WHERE closed_at IS NULL AND leg_type='hedge'"
            ).fetchone()
            hedge_n = int(row[0]) if row else 0
            c.close()
        return {
            "mode_label": mode_label_tr(),
            "pacing": pacing,
            "capital": cap,
            "velocity": vel,
            "rules_tr": rules,
            "global_elite_wallets": n_elite,
            "open_hedges": hedge_n,
            "scan_rejects": scan_stats.snapshot(),
        }
    except Exception as exc:
        print(f"[dashboard] global_2x: {exc}")
        return None


def _snapshot() -> dict[str, Any]:
    portfolio = _read_portfolio()
    calibration = _read_calibration()
    candidates = _read_candidates()
    market_data = _read_market_data()
    extras = _polymarket_extras()
    return {
        "ts": datetime.utcnow().isoformat() + "Z",
        "mode": f"PAPER:{SCENARIO_LABEL}" if SCENARIO_LABEL else "PAPER",
        "edge_threshold": EDGE_THRESHOLD,
        "portfolio": portfolio,
        "calibration": calibration,
        "candidates": candidates,
        "market_data": market_data,
        "live_scan": _live_scan_cache.get("data", {}),
        "attribution": _read_attribution(),
        "elite_pacing": _elite_pacing_snapshot(portfolio),
        "elite_decision": _elite_decision_snapshot(portfolio),
        "velocity": _velocity_snapshot(),
        "global_2x": _global_2x_snapshot(portfolio),
        "elite_runtime": _elite_runtime_snapshot(portfolio),
        **extras,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  WebSocket connection manager
# ═══════════════════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.remove(ws)

    async def broadcast(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        txt = _dumps(payload)
        for ws in list(self._clients):
            try:
                await ws.send_text(txt)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._clients:
                self._clients.remove(ws)

    @property
    def count(self) -> int:
        return len(self._clients)


manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════════════════
#  Live-price enrichment — adds current_price + unrealized_pnl to open positions
# ═══════════════════════════════════════════════════════════════════════════

# ── Circuit breaker: tüm bağlantılar başarısız olunca backoff uygular ────────
_cb_fail_streak   = 0      # ardışık tam-başarısız döngü sayısı
_cb_next_allowed  = 0.0    # bu zaman damgasından önce fetch yapma
_CB_BACKOFFS      = [10, 30, 60, 120, 300]  # sn cinsinden backoff adımları


async def _enrich_open_positions(positions: list[dict]) -> None:
    """CLOB fiyat + unrealized PnL (paper veya canlı liste)."""
    if not positions:
        return
    results = await asyncio.gather(
        *[_fetch_price_history(p["market_id"]) for p in positions],
        return_exceptions=True,
    )
    for pos, res in zip(positions, results):
        if isinstance(res, Exception):
            pos["live_price"] = None
            pos["unrealized_pnl"] = None
            pos["price_error"] = str(res)
            continue
        if not isinstance(res, dict) or res.get("error"):
            pos["live_price"] = None
            pos["unrealized_pnl"] = None
            pos["price_error"] = str(res.get("error") if isinstance(res, dict) else "bad response")
            continue
        cur_yes = res.get("current_price")
        if cur_yes is None:
            pos["live_price"] = None
            pos["unrealized_pnl"] = None
            pos["price_error"] = "current_price missing"
        else:
            cur_yes = round(float(cur_yes), 4)
            pos["live_price"] = cur_yes
            pos["price_error"] = None
            side_price = cur_yes if pos["side"] == "YES" else (1.0 - cur_yes)
            pos["unrealized_pnl"] = round(
                pos.get("contracts", 0) * side_price - pos.get("stake_usd", 0), 4
            )


async def _enrich_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    """Fetch CLOB live prices for paper + canlı açık pozisyonlar."""
    global _cb_fail_streak, _cb_next_allowed

    paper_pos: list[dict] = snap.get("portfolio", {}).get("open_positions", [])
    live_pos: list[dict] = []
    lt = snap.get("live_trading")
    if isinstance(lt, dict):
        live_pos = (lt.get("portfolio") or {}).get("open_positions", [])
    positions = paper_pos + live_pos
    if not positions:
        return snap

    # Circuit breaker: backoff süresi dolmadıysa fetch yapma
    import time as _time
    now = _time.time()
    if now < _cb_next_allowed:
        remaining = int(_cb_next_allowed - now)
        ts = datetime.utcnow().strftime("%H:%M:%S")
        print(f"[{ts}] ⏸  circuit breaker aktif — {remaining}s sonra tekrar denenecek")
        return snap

    ts = datetime.utcnow().strftime("%H:%M:%S")

    await _enrich_open_positions(positions)
    ok_count = sum(1 for p in positions if p.get("live_price") is not None and not p.get("price_error"))
    fail_count = len(positions) - ok_count
    errors: list[str] = []
    for p in positions:
        if p.get("price_error"):
            short = str(p["price_error"])[:60]
            if short not in errors:
                errors.append(short)

    cb_remaining = max(0, int(_cb_next_allowed - now)) if now < _cb_next_allowed else 0

    if fail_count == len(positions) and fail_count > 0:
        # Tüm bağlantılar başarısız → circuit breaker devreye gir
        _cb_fail_streak += 1
        backoff = _CB_BACKOFFS[min(_cb_fail_streak - 1, len(_CB_BACKOFFS) - 1)]
        _cb_next_allowed = _time.time() + backoff
        cb_remaining = backoff
        unique_errs = list(dict.fromkeys(errors))[:2]
        print(f"[{ts}] ❌ ağ hatası ({fail_count}/{len(positions)}) — "
              f"{backoff}s backoff (streak={_cb_fail_streak}) | {' | '.join(unique_errs)}")
    elif ok_count > 0:
        # En az bir başarılı → circuit breaker sıfırla
        _cb_fail_streak = 0
        _cb_next_allowed = 0.0
        cb_remaining = 0
        if fail_count:
            print(f"[{ts}] ✅ {ok_count}/{len(positions)} fiyat güncellendi "
                  f"({fail_count} başarısız)")
        else:
            print(f"[{ts}] ✅ {ok_count}/{len(positions)} fiyat güncellendi")

    rt = snap.get("elite_runtime")
    if isinstance(rt, dict):
        rt["price_feed"] = {
            "ok": ok_count,
            "fail": fail_count,
            "total": len(positions),
            "ts": datetime.utcnow().isoformat() + "Z",
            "circuit_breaker_sec": cb_remaining,
            "live": ok_count > 0 and cb_remaining == 0,
        }

    return snap


# ═══════════════════════════════════════════════════════════════════════════
#  Background push loop
# ═══════════════════════════════════════════════════════════════════════════

async def _push_loop(interval: int = 10) -> None:
    while True:
        await asyncio.sleep(interval)
        if manager.count > 0:
            try:
                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(None, _snapshot)
                data = await _enrich_snapshot(data)
                await manager.broadcast(data)
            except Exception as exc:
                print(f"[dashboard] push error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_push_loop())
    asyncio.create_task(_live_scan_loop())
    if not (DATA_DIR / "recent_trades.pkl").exists():
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _refresh_market_feed_sync)
        except Exception as exc:
            print(f"[dashboard] market_feed bootstrap: {exc}")
    asyncio.create_task(_market_feed_loop())
    yield


# ═══════════════════════════════════════════════════════════════════════════
#  FastAPI app
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(title="PredMarket Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/data")
async def api_data():
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _snapshot)
    return await _enrich_snapshot(data)


@app.get("/api/scanner-health")
async def api_scanner_health():
    """Elite scanner canlı durum — hızlı poll (WS beklemeden)."""
    loop = asyncio.get_running_loop()
    portfolio = await loop.run_in_executor(None, _read_portfolio)
    data: dict[str, Any] = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "elite_runtime": _elite_runtime_snapshot(portfolio),
    }
    rt = data.get("elite_runtime")
    if isinstance(rt, dict):
        paper_pos = portfolio.get("open_positions") or []
        if paper_pos:
            await _enrich_open_positions(paper_pos)
            ok = sum(1 for p in paper_pos if p.get("live_price") is not None)
            rt["price_feed"] = {
                "ok": ok,
                "fail": len(paper_pos) - ok,
                "total": len(paper_pos),
                "ts": datetime.utcnow().isoformat() + "Z",
                "circuit_breaker_sec": 0,
                "live": ok > 0,
            }
    return data


@app.get("/api/live")
async def api_live():
    """Canlı band — yalnızca live.db + CLOB; paper WS döngüsünden bağımsız yenileme."""
    if not _live_trading_enabled():
        return {
            "ts": datetime.utcnow().isoformat() + "Z",
            "live_trading": None,
            "live_runtime": None,
            "disabled": True,
        }
    loop = asyncio.get_running_loop()
    lt = await loop.run_in_executor(None, _live_trading_snapshot)
    snap: dict[str, Any] = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "live_trading": lt,
        "live_runtime": (lt or {}).get("runtime"),
    }
    if lt and isinstance(lt.get("portfolio"), dict):
        live_pos = lt["portfolio"].get("open_positions") or []
        if live_pos:
            await _enrich_open_positions(live_pos)
    return snap


@app.get("/api/price-history/{market_id}")
async def api_price_history(market_id: str):
    return await _fetch_price_history(market_id, force=True)


@app.get("/api/live-scan")
async def api_live_scan():
    return await _fetch_live_scan()


@app.get("/api/attribution")
async def api_attribution():
    """Son attribution raporu — piyasa vs formül vs hedef."""
    loop = asyncio.get_running_loop()

    def _run():
        from elite_trader.attribution import load_latest, write_report

        data = load_latest()
        if data is None:
            write_report()
            data = load_latest()
        pacing = None
        try:
            from elite_trader.hourly_pacing import HourlyPacing

            port = _read_portfolio()
            p = HourlyPacing.from_env()
            p.realized_pnl = float((port.get("stats") or {}).get("realized_pnl") or 0)
            pacing = p.snapshot()
        except Exception:
            pass
        return {"attribution": data, "elite_pacing": pacing}

    return await loop.run_in_executor(None, _run)


@app.post("/api/refresh-market-feed")
async def api_refresh_market_feed():
    """Manuel: Polymarket son işlemleri → recent_trades.pkl."""
    loop = asyncio.get_running_loop()
    n = await loop.run_in_executor(None, _refresh_market_feed_sync)
    return {"ok": n > 0, "trades": n}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        loop = asyncio.get_running_loop()
        try:
            initial = await loop.run_in_executor(None, _snapshot)
            initial = await _enrich_snapshot(initial)
            await ws.send_text(_dumps(initial))
        except Exception as exc:
            print(f"[dashboard] ws initial send error: {exc}")
            # Send a minimal valid payload so client doesn't show "disconnected"
            await ws.send_text(_dumps({
                "ts": datetime.utcnow().isoformat() + "Z",
                "mode": MODE.upper(),
                "edge_threshold": EDGE_THRESHOLD,
                "error": str(exc)[:200],
                "portfolio": {"timestamps":[],"equity":[],"labels":[],"pnl_bars":[],
                              "candles":[],"open_positions":[],"closed_positions":[],
                              "daily_pnl":[],
                              "stats":{"starting_balance":STARTING_BALANCE,
                                       "current_equity":STARTING_BALANCE,
                                       "realized_pnl":0.0,"closed_trades":0,
                                       "wins":0,"win_rate":None,"open_trades":0,
                                       "avg_edge":None}},
                "calibration": {"buckets":[],"total_points":0,"brier":None},
                "market_data": {"whale_stats":[],"recent_trades":[],"price_dist":[],
                                "side_dist":{"YES":0,"NO":0},"dir_dist":{"open":0,"close":0},
                                "total_history_trades":0,"watchlist_size":0},
                "candidates": [],
            }))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        try:
            manager.disconnect(ws)
        except ValueError:
            pass


@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = STATIC_DIR / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Dashboard — static/index.html bulunamadı</h1>"


# ── Direct run ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    title = SCENARIO_LABEL or "PredMarket Dashboard"
    print(f"Dashboard [{title}]: http://127.0.0.1:{DASHBOARD_PORT}  ({DB_PATH.name})")
    uvicorn.run("dashboard:app", host="0.0.0.0", port=DASHBOARD_PORT, reload=False)
