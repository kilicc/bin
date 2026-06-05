"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          CRYPTO FUTURES ENGINE  —  Tamamen Bağımsız Modül                  ║
║                                                                              ║
║  Polymarket / tahmin piyasası bağlantısı YOK. Sadece gerçek kripto vadeli. ║
╚══════════════════════════════════════════════════════════════════════════════╝

VERİ KAYNAKLARI (6+):
  1. Hyperliquid    — funding, OI, OHLCV, mark fiyat, leaderboard fills
  2. Binance Futures — funding, OHLCV (çapraz doğrulama + arbitraj sinyali)
  3. Bybit / OKX / Gate — USDT vadeli işlem fiyatları (toplu API, HL ile spread)
  4. Alternative.me  — Kripto Fear & Greed Index
  5. CoinGecko       — piyasa büyüklüğü, 24h değişim, trending coinler
  6. CoinGlass       — çok borsa tasfiye (liquidation) toplaması

STRATEJİLER (9)  ×  AĞIRLIKLI PUANLAMA:
  ─────────────────────────────────────────────────────────────────────────
   #   Strateji          Ağırlık  Açıklama
  ─────────────────────────────────────────────────────────────────────────
   1   FUNDING_MULTI      3.0    HL + Binance funding birlikte aşırı ise
   2   RSI_EXTREME        2.0    RSI < 32 oversold / > 68 overbought
   3   COPY_TRADE         2.0    Top cüzdan + bilinen bot adresleri takibi
   4   FEAR_GREED         1.5    Ekstrem korku → LONG, ekstrem açgözlülük → SHORT
   5   EMA_CROSS          1.5    EMA9 × EMA21 golden/death cross
   6   BB_EXTREME         1.5    Bollinger Band dışı fiyat → geri dönüş
   7   LIQUIDATION        1.5    Büyük tasfiye dalgası sonrası geri dönüş
   8   VOL_BREAKOUT       1.0    Hacim spike + fiyat yönü
   9   CEX_ARB            2.0    HL vs Binance/Bybit/OKX/Gate medyan fiyat spread
  ─────────────────────────────────────────────────────────────────────────
   MAX PUAN = 16.0   |   MIN GİRİŞ = .env (ENGINE_MIN_SCORE)

COPY TRADING MODÜLÜ:
  • Hyperliquid leaderboard top-25 adres otomatik çekilir
  • COPY_BOT_ADDRESSES env'den kullanıcı tanımlı bot adresleri eklenir
  • Son 30dk içindeki fill'ler analiz edilir
  • ≥ 3 whale aynı yönde = güçlü sinyal (tam ağırlık)
  • Bot adresi = 1.5× ağırlık

PAPER DEMO ($20 — AYRI BAKİYE):
  • DB : data/crypto_engine.db   (paper.db ile HİÇBİR İLİŞKİSİ YOK)
  • Başlangıç : $20.00
  • Max pozisyon : $5.00
  • TP / SL : fiyat %3.5 (varsayılan, .env ENGINE_TP_PCT / ENGINE_SL_PCT)
  • Kelly : 0.25

Çalıştırmak için:
  python crypto_engine.py
"""
from __future__ import annotations

import json
import math
import os
import statistics
import signal
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

# ═══════════════════════════════════════════════════════════════════════════════
#  Konfigürasyon
# ═══════════════════════════════════════════════════════════════════════════════

ENGINE_DB         = ROOT / "data" / "crypto_engine.db"
ENGINE_LOCK       = ROOT / "data" / "crypto_engine.lock"
ENGINE_HEARTBEAT  = ROOT / "data" / "crypto_engine.heartbeat.json"
STARTING_BALANCE  = float(os.getenv("ENGINE_START_BALANCE",    "20.0"))
MAX_POS_USD       = float(os.getenv("ENGINE_MAX_POS_USD",       "5.0"))
KELLY_FRACTION    = float(os.getenv("ENGINE_KELLY",             "0.25"))
MAX_OPEN_POS      = int(os.getenv("ENGINE_MAX_OPEN",            "10"))
MAX_HOLD_HOURS    = float(os.getenv("ENGINE_MAX_HOLD_HOURS",    "24.0"))
SCAN_INTERVAL     = int(os.getenv("ENGINE_SCAN_INTERVAL",       "90"))
POS_CHECK         = int(os.getenv("ENGINE_POS_CHECK",           "15"))
SL_COOLDOWN_MIN   = int(os.getenv("ENGINE_SL_COOLDOWN",         "60"))
TAKE_PROFIT_PCT   = float(os.getenv("ENGINE_TP_PCT",            "0.035"))
STOP_LOSS_PCT     = float(os.getenv("ENGINE_SL_PCT",            "0.035"))

# ATR tabanlı dinamik TP/SL (pozisyon açılışında hesaplanır, DB'de saklanır)
USE_ATR_EXITS     = os.getenv("ENGINE_USE_ATR_EXITS", "1").lower() in ("1", "true", "yes")
ATR_PERIOD        = int(os.getenv("ENGINE_ATR_PERIOD", "14"))
ATR_TP_MULT        = float(os.getenv("ENGINE_ATR_TP_MULT", "1.06"))
ATR_SL_MULT        = float(os.getenv("ENGINE_ATR_SL_MULT", "0.94"))
ATR_TP_MIN_FRAC    = float(os.getenv("ENGINE_ATR_TP_MIN_FRAC", "0.010"))
ATR_TP_MAX_FRAC    = float(os.getenv("ENGINE_ATR_TP_MAX_FRAC", "0.050"))
ATR_SL_MIN_FRAC    = float(os.getenv("ENGINE_ATR_SL_MIN_FRAC", "0.009"))
ATR_SL_MAX_FRAC    = float(os.getenv("ENGINE_ATR_SL_MAX_FRAC", "0.045"))

USE_BREAK_EVEN    = os.getenv("ENGINE_USE_BREAK_EVEN", "1").lower() in ("1", "true", "yes")
BE_ARM_FRAC        = float(os.getenv("ENGINE_BE_ARM_FRAC", "0.46"))   # tp_frac × bu kadar kârda BE silahı
BE_GIVEBACK_FRAC   = float(os.getenv("ENGINE_BE_GIVEBACK", "0.00042"))  # giriş altı/üstü tampon

# Dinamik evren: anchor coinler + HL 24h hacim sıralı (likidite tabanı MIN_OI_USD)
ENGINE_DYNAMIC_WATCHLIST = os.getenv("ENGINE_DYNAMIC_WATCHLIST", "1").lower() in ("1", "true", "yes")
ENGINE_WATCHLIST_MAX     = int(os.getenv("ENGINE_WATCHLIST_MAX", "44"))
ENGINE_ANCHOR_COINS      = os.getenv("ENGINE_ANCHOR_COINS", "BTC,ETH,SOL")

# Backtest WR alt sınırı (daha seçici → daha yüksek kaliteli giriş)
ENGINE_BT_MIN_WR       = float(os.getenv("ENGINE_BT_MIN_WR", "0.37"))

# Kopya: taze fill penceresi + burst bot filtresi
COPY_LOOKBACK_MS       = int(os.getenv("ENGINE_COPY_LOOKBACK_MS", "720000"))       # 12 dk
COPY_BURST_WINDOW_MS   = int(os.getenv("ENGINE_COPY_BURST_WINDOW_MS", "2700000"))  # 45 dk
COPY_BURST_FILLS       = int(os.getenv("ENGINE_COPY_BURST_FILLS", "52"))
COPY_MIN_MONTH_ROI     = float(os.getenv("ENGINE_COPY_MIN_MONTH_ROI", "0.026"))
COPY_MIN_WEEK_ROI      = float(os.getenv("ENGINE_COPY_MIN_WEEK_ROI", "0.0"))        # 0=kapalı

# Strateji eşikleri
MIN_SCORE        = float(os.getenv("ENGINE_MIN_SCORE",          "2.0"))
LEVERAGE_MIN     = int(os.getenv("ENGINE_LEVERAGE_MIN",         "2"))
LEVERAGE_MAX     = int(os.getenv("ENGINE_LEVERAGE_MAX",         "20"))
FUNDING_EXTREME  = float(os.getenv("ENGINE_FUNDING_EXTREME",    "0.0002"))
RSI_OVERSOLD     = float(os.getenv("ENGINE_RSI_OVERSOLD",       "32.0"))
RSI_OVERBOUGHT   = float(os.getenv("ENGINE_RSI_OVERBOUGHT",     "68.0"))
RSI_PERIOD       = int(os.getenv("ENGINE_RSI_PERIOD",           "14"))
BB_PERIOD        = int(os.getenv("ENGINE_BB_PERIOD",            "20"))
BB_STD           = float(os.getenv("ENGINE_BB_STD",             "2.0"))
EMA_FAST         = int(os.getenv("ENGINE_EMA_FAST",             "9"))
EMA_SLOW         = int(os.getenv("ENGINE_EMA_SLOW",             "21"))
VOL_LOOKBACK     = int(os.getenv("ENGINE_VOL_LOOKBACK",         "20"))
VOL_SPIKE_MULT   = float(os.getenv("ENGINE_VOL_SPIKE",          "2.0"))
FG_EXTREME_FEAR  = int(os.getenv("ENGINE_FG_FEAR",              "25"))
FG_EXTREME_GREED = int(os.getenv("ENGINE_FG_GREED",             "75"))
WHALE_TOP_N      = int(os.getenv("ENGINE_WHALE_TOP_N",          "25"))
WHALE_MIN_N      = int(os.getenv("ENGINE_WHALE_MIN_N",          "3"))
LIQ_THRESHOLD    = float(os.getenv("ENGINE_LIQ_THRESHOLD",      "50000000"))
CANDLE_INTERVAL  = os.getenv("ENGINE_CANDLE_INTERVAL",          "1h")
LOOKBACK_CANDLES = int(os.getenv("ENGINE_LOOKBACK_CANDLES",     "60"))
MIN_OI_USD       = float(os.getenv("ENGINE_MIN_OI_USD",         "5000000"))
BACKTEST_DAYS    = int(os.getenv("ENGINE_BACKTEST_DAYS",         "7"))
# Çoklu borsa fiyat spread (HL referans)
W_ARB            = float(os.getenv("ENGINE_W_ARB",               "2.0"))
ARB_SPREAD_MIN   = float(os.getenv("ENGINE_ARB_SPREAD_MIN",      "0.0004"))  # min |fark| tetik
ARB_SPREAD_CAP   = float(os.getenv("ENGINE_ARB_SPREAD_CAP",      "0.004"))   # bu kadar spread → tam skor

# Kullanıcı tanımlı bot adresleri (virgülle ayrılmış HL adresleri)
_bot_str = os.getenv("COPY_BOT_ADDRESSES", "")
COPY_BOT_ADDRS: set[str] = {
    a.strip().lower() for a in _bot_str.split(",") if a.strip().startswith("0x")
}

# Strateji ağırlıkları
W_FUNDING  = 3.0
W_RSI      = 2.0
W_COPY     = 2.0
W_FEAR     = 1.5
W_EMA      = 1.5
W_BB       = 1.5
W_LIQ      = 1.5
W_VOL      = 1.0
MAX_SCORE  = (
    W_FUNDING + W_RSI + W_COPY + W_FEAR + W_EMA + W_BB + W_LIQ + W_VOL + W_ARB
)

# Takip listesi (Hyperliquid'de likit olan ana çiftler)
WATCHLIST = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK",
    "DOT", "NEAR", "APT", "SUI", "INJ", "TIA", "WIF", "PEPE", "ARB",
    "OP", "MATIC", "ATOM", "LTC", "BCH", "AAVE", "UNI", "TRUMP", "HYPE",
]

# Binance sembol eşleştirme
_BN_MAP = {c: f"{c}USDT" for c in WATCHLIST}

# API endpoints
HL_INFO        = "https://api.hyperliquid.xyz/info"
HL_STATS       = "https://stats-data.hyperliquid.xyz/Mainnet"
BN_FUTURES     = "https://fapi.binance.com/fapi/v1"
BYBIT_V5      = "https://api.bybit.com/v5/market/tickers"
OKX_V5        = "https://www.okx.com/api/v5/market/tickers"
GATE_V4       = "https://api.gateio.ws/api/v4/futures/usdt/tickers"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
COINGECKO_URL  = "https://api.coingecko.com/api/v3"
COINGLASS_URL  = "https://open-api.coinglass.com/public/v2"


# ═══════════════════════════════════════════════════════════════════════════════
#  Veri yapıları
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    strategy: str
    score: float      # +pozitif=LONG  -negatif=SHORT  0=nötr
    value: float
    detail: str = ""


@dataclass
class CoinSignal:
    coin: str
    mark_px: float
    hl_funding: float
    bn_funding: float
    oi_usd: float
    signals: list[Signal] = field(default_factory=list)
    total_score: float = 0.0
    side: str = ""
    confidence: float = 0.0

    def compute(self) -> None:
        self.total_score = sum(s.score for s in self.signals)
        abs_sc = abs(self.total_score)
        if abs_sc >= MIN_SCORE:
            self.side       = "LONG" if self.total_score > 0 else "SHORT"
            self.confidence = min(1.0, abs_sc / MAX_SCORE)
        else:
            self.side, self.confidence = "", 0.0


# ═══════════════════════════════════════════════════════════════════════════════
#  Veritabanı
# ═══════════════════════════════════════════════════════════════════════════════

def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            coin         TEXT    NOT NULL,
            side         TEXT    NOT NULL,
            entry_price  REAL    NOT NULL,
            stake_usd    REAL    NOT NULL,
            contracts    REAL    NOT NULL,
            score        REAL    NOT NULL DEFAULT 0,
            strategies   TEXT    NOT NULL DEFAULT '',
            hl_funding   REAL    NOT NULL DEFAULT 0,
            bn_funding   REAL    NOT NULL DEFAULT 0,
            fear_greed   INTEGER,
            whale_count  INTEGER NOT NULL DEFAULT 0,
            opened_at    TEXT    NOT NULL,
            closed_at    TEXT,
            close_price  REAL,
            pnl_usd      REAL,
            close_reason TEXT,
            funding_paid REAL    NOT NULL DEFAULT 0.0,
            last_price   REAL,
            last_update  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_stats (
            strategy   TEXT PRIMARY KEY,
            wins       INTEGER NOT NULL DEFAULT 0,
            losses     INTEGER NOT NULL DEFAULT 0,
            total_pnl  REAL    NOT NULL DEFAULT 0.0,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         TEXT NOT NULL,
            fear_greed INTEGER,
            top_coins  TEXT,
            hl_extremes INTEGER
        )
    """)
    for col, td in [
        ("bn_funding",  "REAL NOT NULL DEFAULT 0"),
        ("fear_greed",  "INTEGER"),
        ("whale_count", "INTEGER NOT NULL DEFAULT 0"),
        ("funding_paid","REAL NOT NULL DEFAULT 0.0"),
        ("last_price",  "REAL"),
        ("last_update", "TEXT"),
        ("leverage",    "INTEGER NOT NULL DEFAULT 1"),
        ("tp_frac",     "REAL"),
        ("sl_frac",     "REAL"),
        ("be_armed",    "INTEGER NOT NULL DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {col} {td}")
        except Exception:
            pass
    conn.execute("CREATE INDEX IF NOT EXISTS idx_open ON positions(coin,closed_at)")
    conn.commit()
    return conn


def _ensure_unique_open_coin_index(conn: sqlite3.Connection) -> None:
    """Aynı coin için en fazla bir açık satır (SQLite partial UNIQUE index)."""
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_one_open_coin "
            "ON positions(coin) WHERE closed_at IS NULL"
        )
        conn.commit()
    except sqlite3.OperationalError:
        conn.rollback()


def dedupe_open_positions_same_coin(conn: sqlite3.Connection) -> int:
    """
    Aynı coinde birden fazla açık satır varsa (yarış / çift süreç),
    en düşük id dışındakileri DEDUP ile kapatır (strateji istatistiğine yazılmaz).
    """
    n = 0
    dups = conn.execute(
        "SELECT coin FROM positions WHERE closed_at IS NULL "
        "GROUP BY coin HAVING COUNT(*) > 1"
    ).fetchall()
    for d in dups:
        coin = d["coin"]
        rows = conn.execute(
            "SELECT id FROM positions WHERE coin=? AND closed_at IS NULL "
            "ORDER BY id ASC",
            (coin,),
        ).fetchall()
        for extra in rows[1:]:
            pid = int(extra["id"])
            r = conn.execute(
                "SELECT last_price, entry_price FROM positions WHERE id=?",
                (pid,),
            ).fetchone()
            if not r:
                continue
            px = float(r["last_price"] or r["entry_price"] or 0.0)
            if px <= 0:
                px = float(r["entry_price"] or 1.0)
            close_pos(conn, pid, px, "DEDUP")
            n += 1
    return n


# ═══════════════════════════════════════════════════════════════════════════════
#  HTTP yardımcıları
# ═══════════════════════════════════════════════════════════════════════════════

def _post(client: httpx.Client, url: str, payload: dict,
          timeout: float = 12.0, retries: int = 2) -> dict | list | None:
    for i in range(retries + 1):
        try:
            r = client.post(url, json=payload,
                            headers={"Content-Type": "application/json"},
                            timeout=timeout)
            return r.json() if r.status_code == 200 else None
        except Exception:
            if i < retries:
                time.sleep(0.8)
    return None


def _get(client: httpx.Client, url: str,
         params: dict | None = None,
         timeout: float = 12.0, retries: int = 2) -> dict | list | None:
    for i in range(retries + 1):
        try:
            r = client.get(url, params=params, timeout=timeout)
            return r.json() if r.status_code == 200 else None
        except Exception:
            if i < retries:
                time.sleep(0.8)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Veri toplayıcılar
# ═══════════════════════════════════════════════════════════════════════════════

# ── 1. Hyperliquid ─────────────────────────────────────────────────────────────

def hl_meta_ctxs(client: httpx.Client) -> tuple[list, list]:
    d = _post(client, HL_INFO, {"type": "metaAndAssetCtxs"})
    if not d or len(d) < 2:
        return [], []
    return d[0].get("universe", []), d[1]


def hl_all_mids(client: httpx.Client) -> dict[str, float]:
    raw = _post(client, HL_INFO, {"type": "allMids"})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[k] = float(v)
        except Exception:
            pass
    return out


def hl_candles(client: httpx.Client, coin: str, n: int,
               interval: str = CANDLE_INTERVAL) -> list[dict]:
    ms_map = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
              "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
    iv  = ms_map.get(interval, 3_600_000)
    now = int(time.time() * 1000)
    d   = _post(client, HL_INFO, {
        "type": "candleSnapshot",
        "req":  {"coin": coin, "interval": interval,
                 "startTime": now - n * iv * 2, "endTime": now},
    }, timeout=15.0)
    return (d or [])[-n:]


# ── 2. Binance Futures ─────────────────────────────────────────────────────────

_bn_fund_cache: dict[str, tuple[float, float]] = {}   # symbol → (rate, ts)
_BN_FUND_TTL = 600


def bn_funding(client: httpx.Client, coin: str) -> float | None:
    """Binance'tan coin/USDT funding rate (8h). Cache: 10dk."""
    sym = _BN_MAP.get(coin)
    if not sym:
        return None
    now = time.time()
    if sym in _bn_fund_cache:
        rate, ts = _bn_fund_cache[sym]
        if now - ts < _BN_FUND_TTL:
            return rate
    data = _get(client, f"{BN_FUTURES}/fundingRate",
                params={"symbol": sym, "limit": 1}, timeout=8.0)
    if not data or not isinstance(data, list):
        return None
    try:
        rate = float(data[0]["fundingRate"])
        _bn_fund_cache[sym] = (rate, now)
        return rate
    except Exception:
        return None


def bn_candles(client: httpx.Client, coin: str,
               n: int = 60, interval: str = "1h") -> list[dict]:
    sym  = _BN_MAP.get(coin)
    if not sym:
        return []
    raw = _get(client, f"{BN_FUTURES}/klines",
               params={"symbol": sym, "interval": interval, "limit": n},
               timeout=12.0)
    if not isinstance(raw, list):
        return []
    # Binance format: [ts, open, high, low, close, volume, ...]
    out = []
    for c in raw:
        try:
            out.append({"o": float(c[1]), "h": float(c[2]),
                        "l": float(c[3]), "c": float(c[4]),
                        "v": float(c[5])})
        except Exception:
            pass
    return out


# ── 2b. Çoklu borsa mark / last fiyatları (spread sinyali) ─────────────────────

# coin → (binance_sym, bybit_sym, okx_inst, gate_contract)
_CEX_SYMBOL_OVERRIDES: dict[str, tuple[str, str, str, str]] = {
    "PEPE": ("1000PEPEUSDT", "1000PEPEUSDT", "1000PEPE-USDT-SWAP", "1000PEPE_USDT"),
    "MATIC": ("MATICUSDT", "MATICUSDT", "MATIC-USDT-SWAP", "MATIC_USDT"),
}


def _cex_keys(coin: str) -> tuple[str, str, str, str]:
    if coin in _CEX_SYMBOL_OVERRIDES:
        return _CEX_SYMBOL_OVERRIDES[coin]
    u = f"{coin}USDT"
    return (u, u, f"{coin}-USDT-SWAP", f"{coin}_USDT")


def _bn_all_futures_last(client: httpx.Client) -> dict[str, float]:
    """Binance USDT-M tüm sembol last price."""
    raw = _get(client, f"{BN_FUTURES}/ticker/price", timeout=18.0)
    out: dict[str, float] = {}
    if not isinstance(raw, list):
        return out
    for row in raw:
        try:
            if isinstance(row, dict) and row.get("symbol"):
                out[str(row["symbol"])] = float(row["price"])
        except Exception:
            pass
    return out


def _bybit_all_linear_last(client: httpx.Client) -> dict[str, float]:
    out: dict[str, float] = {}
    cursor = ""
    for _ in range(8):
        params: dict[str, str] = {"category": "linear", "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        data = _get(client, BYBIT_V5, params=params, timeout=18.0)
        lst = (data or {}).get("result", {}).get("list") or []
        if not lst:
            break
        for it in lst:
            try:
                sym = str(it.get("symbol", ""))
                px  = float(it.get("lastPrice") or it.get("markPrice") or 0)
                if sym and px > 0:
                    out[sym] = px
            except Exception:
                pass
        cursor = str((data or {}).get("result", {}).get("nextPageCursor") or "")
        if not cursor:
            break
    return out


def _okx_all_swap_last(client: httpx.Client) -> dict[str, float]:
    data = _get(client, OKX_V5, params={"instType": "SWAP"}, timeout=18.0)
    out: dict[str, float] = {}
    for it in (data or {}).get("data", []) or []:
        try:
            iid = str(it.get("instId", ""))
            px  = float(it.get("last") or it.get("idxPx") or 0)
            if iid and px > 0:
                out[iid] = px
        except Exception:
            pass
    return out


def _gate_usdt_futures_last(client: httpx.Client) -> dict[str, float]:
    raw = _get(client, GATE_V4, timeout=18.0)
    out: dict[str, float] = {}
    if not isinstance(raw, list):
        return out
    for it in raw:
        try:
            c = str(it.get("contract", ""))
            p = float(it.get("last") or it.get("mark_price") or 0)
            if c and p > 0:
                out[c] = p
        except Exception:
            pass
    return out


def build_cex_price_book(client: httpx.Client) -> dict[str, dict[str, float]]:
    """
    Her coin için {binance, bybit, okx, gate} last fiyatları (HL hariç).
    API hatalarında kısmi sonuç döner.
    """
    bn: dict[str, float] = {}
    bb: dict[str, float] = {}
    ok: dict[str, float] = {}
    gt: dict[str, float] = {}
    try:
        bn = _bn_all_futures_last(client)
    except Exception:
        pass
    try:
        bb = _bybit_all_linear_last(client)
    except Exception:
        pass
    try:
        ok = _okx_all_swap_last(client)
    except Exception:
        pass
    try:
        gt = _gate_usdt_futures_last(client)
    except Exception:
        pass

    book: dict[str, dict[str, float]] = {}
    for coin in WATCHLIST:
        bns, bbs, oks, gts = _cex_keys(coin)
        row: dict[str, float] = {}
        p = bn.get(bns)
        if p and p > 0:
            row["binance"] = p
        p = bb.get(bbs)
        if p and p > 0:
            row["bybit"] = p
        p = ok.get(oks)
        if p and p > 0:
            row["okx"] = p
        p = gt.get(gts)
        if p and p > 0:
            row["gate"] = p
        if row:
            book[coin] = row
    return book


def sig_cross_exchange(hl_px: float, venues: dict[str, float]) -> Signal:
    """
    HL fiyatı, diğer borsaların medyanına göre sapmışsa mean-reversion yönünde sinyal.
    HL > medyan → kısa (SHORT), HL < medyan → LONG.
    """
    prices = [v for v in venues.values() if v and v > 0]
    if len(prices) < 2:
        return Signal("CEX_ARB", 0.0, 0.0,
                      f"CEX<{len(prices)} borsa fiyatı")
    med = float(statistics.median(prices))
    if med <= 0 or hl_px <= 0:
        return Signal("CEX_ARB", 0.0, 0.0, "geçersiz fiyat")
    diff = (hl_px - med) / hl_px
    span = max(ARB_SPREAD_CAP - ARB_SPREAD_MIN, 1e-9)
    if abs(diff) < ARB_SPREAD_MIN:
        return Signal("CEX_ARB", 0.0, diff,
                      f"HL vs medyan {diff*100:+.3f}% (eşik altı)")
    excess   = abs(diff) - ARB_SPREAD_MIN
    intensity = min(1.0, excess / span)
    score_mag = W_ARB * intensity
    if diff > 0:
        score = -score_mag
        side = "SHORT"
    else:
        score = score_mag
        side = "LONG"
    labs = ",".join(f"{k}:{v:.6g}" for k, v in sorted(venues.items()))
    return Signal(
        "CEX_ARB", round(score, 4), diff,
        f"{side} HL/med={diff*100:+.3f}%  [{labs}] med={med:.6g}",
    )


# ── 3. Fear & Greed Index ─────────────────────────────────────────────────────

_fg_cache: tuple[int, float] = (50, 0.0)   # (value, ts)
_FG_TTL = 3600


def fear_greed_index(client: httpx.Client) -> int:
    global _fg_cache
    val, ts = _fg_cache
    if time.time() - ts < _FG_TTL:
        return val
    data = _get(client, FEAR_GREED_URL, timeout=8.0)
    try:
        v    = int(data["data"][0]["value"])
        _fg_cache = (v, time.time())
        return v
    except Exception:
        return 50


# ── 4. CoinGecko ─────────────────────────────────────────────────────────────

_cg_map = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "BNB": "binancecoin", "XRP": "ripple", "DOGE": "dogecoin",
    "ADA": "cardano", "AVAX": "avalanche-2", "LINK": "chainlink",
    "DOT": "polkadot", "NEAR": "near", "APT": "aptos",
    "SUI": "sui", "INJ": "injective-protocol", "ARB": "arbitrum",
    "OP": "optimism", "MATIC": "matic-network", "ATOM": "cosmos",
    "LTC": "litecoin", "AAVE": "aave", "UNI": "uniswap",
    "WIF": "dogwifcoin", "PEPE": "pepe", "TIA": "celestia",
}
_cg_cache: dict[str, dict] = {}
_CG_TTL = 300


def cg_market_data(client: httpx.Client,
                   coins: list[str]) -> dict[str, dict]:
    """24h değişim, market cap rank, trending için CoinGecko."""
    global _cg_cache
    now = time.time()
    if _cg_cache.get("_ts", 0) + _CG_TTL > now:
        return _cg_cache

    ids = ",".join(
        _cg_map[c] for c in coins[:20] if c in _cg_map
    )
    if not ids:
        return {}
    data = _get(client,
                f"{COINGECKO_URL}/simple/price",
                params={
                    "ids": ids,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                }, timeout=10.0)
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    reverse = {v: k for k, v in _cg_map.items()}
    for cg_id, vals in data.items():
        coin = reverse.get(cg_id)
        if coin:
            out[coin] = {
                "usd":      vals.get("usd", 0),
                "24h_pct":  vals.get("usd_24h_change", 0),
                "mcap":     vals.get("usd_market_cap", 0),
            }
    out["_ts"] = now  # type: ignore[assignment]
    _cg_cache = out
    return out


# ── 5. CoinGlass (tasfiye verileri) ───────────────────────────────────────────

_liq_cache: dict[str, float] = {}   # coin → toplam tasfiye $
_LIQ_TTL = 300
_liq_ts  = 0.0


def coinglass_liquidations(client: httpx.Client) -> dict[str, float]:
    """Son 24 saatlik tasfiye $ (coin bazlı). Cache: 5dk."""
    global _liq_cache, _liq_ts
    now = time.time()
    if now - _liq_ts < _LIQ_TTL and _liq_cache:
        return _liq_cache

    # CoinGlass free public endpoint
    data = _get(client,
                "https://open-api.coinglass.com/public/v2/liquidation_history",
                params={"symbol": "all", "time_type": "h24"},
                timeout=10.0)
    out: dict[str, float] = {}
    if isinstance(data, dict):
        items = data.get("data") or []
        for row in items:
            try:
                sym = (row.get("symbol") or "").upper().replace("USDT", "")
                total_usd = float(row.get("liquidationUsd") or 0)
                if sym:
                    out[sym] = total_usd
            except Exception:
                pass

    # Fallback: HL clearing data üzerinden tahmin
    if not out:
        meta, ctxs = hl_meta_ctxs(client)
        for u, ctx in zip(meta, ctxs):
            coin = u.get("name", "")
            try:
                px  = float(ctx.get("markPx") or 0)
                oi  = float(ctx.get("openInterest") or 0) * px
                fund = abs(float(ctx.get("funding") or 0))
                # Yüksek funding → daha fazla potansiyel tasfiye
                if fund > FUNDING_EXTREME * 2:
                    out[coin] = oi * 0.02  # OI'nin %2'si tahmin
            except Exception:
                pass

    _liq_cache = out
    _liq_ts    = now
    return out


# ═══════════════════════════════════════════════════════════════════════════════
#  Teknik göstergeler
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0.0) for d in deltas[-period:]]
    losses = [-min(d, 0.0) for d in deltas[-period:]]
    ag, al = sum(gains) / period, sum(losses) / period
    if al == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + ag / al))


def compute_ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k   = 2.0 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def compute_bollinger(closes: list[float],
                      period: int = BB_PERIOD,
                      n_std: float = BB_STD) -> tuple[float, float, float] | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid    = sum(window) / period
    std    = math.sqrt(sum((x - mid) ** 2 for x in window) / period)
    return mid + n_std * std, mid, mid - n_std * std


def compute_vol_spike(vols: list[float], lb: int = VOL_LOOKBACK) -> float:
    if len(vols) < lb + 1:
        return 1.0
    avg = sum(vols[-lb - 1:-1]) / lb
    return (vols[-1] / avg) if avg > 0 else 1.0


def compute_wilder_atr(candles: list[dict], period: int = 14) -> float | None:
    """Wilder ATR — mum dict'leri h,l,c anahtarlı (HL)."""
    if len(candles) < period + 2:
        return None
    trs: list[float] = []
    for i in range(1, len(candles)):
        try:
            h  = float(candles[i]["h"])
            l  = float(candles[i]["l"])
            pc = float(candles[i - 1]["c"])
        except (KeyError, TypeError, ValueError):
            continue
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period + 1:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def dynamic_tp_sl_fracs(client: httpx.Client, coin: str, mark_px: float) -> tuple[float, float]:
    """ATR/price ile TP/SL oranları; sabit env tabanı ile clamp."""
    if not USE_ATR_EXITS or mark_px <= 0:
        return TAKE_PROFIT_PCT, STOP_LOSS_PCT
    raw = hl_candles(client, coin, n=max(ATR_PERIOD + 22, 40))
    atr = compute_wilder_atr(raw, ATR_PERIOD)
    if atr is None or atr <= 0:
        return TAKE_PROFIT_PCT, STOP_LOSS_PCT
    af = atr / mark_px
    tp = max(ATR_TP_MIN_FRAC, min(ATR_TP_MAX_FRAC, ATR_TP_MULT * af))
    sl = max(ATR_SL_MIN_FRAC, min(ATR_SL_MAX_FRAC, ATR_SL_MULT * af))
    tp = max(tp, TAKE_PROFIT_PCT * 0.72)
    sl = max(sl, STOP_LOSS_PCT * 0.78)
    return round(tp, 6), round(sl, 6)


def scan_candidate_rows(
    meta: list, ctxs: list, ctx_map: dict[str, dict], mids: dict[str, float],
) -> list[tuple[str, float, float, float]]:
    """Tarama satırları: (coin, px, oi_usd, hl_funding)."""
    rows: list[tuple[str, float, float, float]] = []
    if not ENGINE_DYNAMIC_WATCHLIST:
        for coin in WATCHLIST:
            ctx = ctx_map.get(coin)
            if not ctx:
                continue
            try:
                px     = float(ctx.get("markPx") or mids.get(coin) or 0)
                oi_usd = float(ctx.get("openInterest") or 0) * px
                fund   = float(ctx.get("funding") or 0)
            except Exception:
                continue
            if px > 0 and oi_usd >= MIN_OI_USD:
                rows.append((coin, px, oi_usd, fund))
        return rows

    anchors = [c.strip().upper() for c in ENGINE_ANCHOR_COINS.split(",") if c.strip()]
    ranked: list[tuple[str, float, float, float, float]] = []
    for u, ctx in zip(meta, ctxs):
        if u.get("isDelisted"):
            continue
        coin = u.get("name") or ""
        if not coin:
            continue
        try:
            px     = float(ctx.get("markPx") or mids.get(coin) or 0)
            oi_usd = float(ctx.get("openInterest") or 0) * px
            fund   = float(ctx.get("funding") or 0)
            dvol   = float(ctx.get("dayNtlVlm") or 0)
        except Exception:
            continue
        if px <= 0 or oi_usd < MIN_OI_USD:
            continue
        ranked.append((coin, px, oi_usd, fund, dvol))
    ranked.sort(key=lambda x: -x[4])

    seen: set[str] = set()
    for coin in anchors:
        ctx = ctx_map.get(coin)
        if not ctx or coin in seen:
            continue
        try:
            px     = float(ctx.get("markPx") or mids.get(coin) or 0)
            oi_usd = float(ctx.get("openInterest") or 0) * px
            fund   = float(ctx.get("funding") or 0)
        except Exception:
            continue
        if px > 0 and oi_usd >= MIN_OI_USD:
            rows.append((coin, px, oi_usd, fund))
            seen.add(coin)

    for coin, px, oi_usd, fund, _ in ranked:
        if len(rows) >= ENGINE_WATCHLIST_MAX:
            break
        if coin in seen:
            continue
        rows.append((coin, px, oi_usd, fund))
        seen.add(coin)
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
#  Strateji sinyal üreticiler
# ═══════════════════════════════════════════════════════════════════════════════

def sig_funding_multi(hl_fund: float, bn_fund: Optional[float]) -> Signal:
    """S1: HL + Binance funding birlikteliği → güçlü mean-reversion sinyali."""
    hl_score = 0.0
    if hl_fund > FUNDING_EXTREME:
        hl_score = -min(1.0, hl_fund / (FUNDING_EXTREME * 4))
    elif hl_fund < -FUNDING_EXTREME:
        hl_score = min(1.0, abs(hl_fund) / (FUNDING_EXTREME * 4))

    bn_score = 0.0
    if bn_fund is not None:
        if bn_fund > FUNDING_EXTREME:
            bn_score = -min(1.0, bn_fund / (FUNDING_EXTREME * 4))
        elif bn_fund < -FUNDING_EXTREME:
            bn_score = min(1.0, abs(bn_fund) / (FUNDING_EXTREME * 4))

    # Her iki borsa da aynı yönde aşırıysa tam puan
    if hl_score != 0 and bn_score != 0 and (hl_score * bn_score > 0):
        combined = (abs(hl_score) + abs(bn_score)) / 2
        score    = math.copysign(combined * W_FUNDING, hl_score)
        src      = "HL+BN"
    elif hl_score != 0:
        score    = hl_score * W_FUNDING * 0.7
        src      = "HL"
    elif bn_score != 0:
        score    = bn_score * W_FUNDING * 0.5
        src      = "BN"
    else:
        return Signal("FUNDING", 0.0, hl_fund, "nötr")

    side = "LONG" if score > 0 else "SHORT"
    return Signal("FUNDING", round(score, 4),
                  hl_fund, f"{src} fund→{side} HL:{hl_fund*100:+.4f}%"
                           + (f" BN:{bn_fund*100:+.4f}%" if bn_fund else ""))


def sig_rsi(closes: list[float]) -> Signal:
    """S2: RSI Extreme."""
    rsi = compute_rsi(closes)
    if rsi is None:
        return Signal("RSI", 0.0, 0.0, "yetersiz veri")
    if rsi < RSI_OVERSOLD:
        score = W_RSI * (1.0 - rsi / RSI_OVERSOLD)
        return Signal("RSI", round(score, 4), rsi, f"RSI={rsi:.1f} oversold→LONG")
    if rsi > RSI_OVERBOUGHT:
        score = -W_RSI * ((rsi - RSI_OVERBOUGHT) / (100 - RSI_OVERBOUGHT))
        return Signal("RSI", round(score, 4), rsi, f"RSI={rsi:.1f} overbought→SHORT")
    return Signal("RSI", 0.0, rsi, f"RSI={rsi:.1f} nötr")


def sig_ema_cross(closes: list[float]) -> Signal:
    """S3: EMA9/EMA21 crossover."""
    if len(closes) < EMA_SLOW + 2:
        return Signal("EMA", 0.0, 0.0, "yetersiz veri")
    fast = compute_ema(closes, EMA_FAST)
    slow = compute_ema(closes, EMA_SLOW)
    if not fast or not slow:
        return Signal("EMA", 0.0, 0.0, "hesap hatası")
    f_prev, f_now = fast[-2], fast[-1]
    s_prev, s_now = slow[-2], slow[-1]
    gap = abs(f_now - s_now) / max(s_now, 1e-9) * 100
    if f_prev <= s_prev and f_now > s_now:
        return Signal("EMA", W_EMA, gap, f"EMA{EMA_FAST}×{EMA_SLOW} golden cross→LONG")
    if f_prev >= s_prev and f_now < s_now:
        return Signal("EMA", -W_EMA, gap, f"EMA{EMA_FAST}×{EMA_SLOW} death cross→SHORT")
    trend = W_EMA * 0.5 * (1 if f_now > s_now else -1)
    return Signal("EMA", round(trend, 4), gap,
                  f"EMA trend {'UP' if trend > 0 else 'DOWN'} gap={gap:.2f}%")


def sig_bollinger(closes: list[float], mark_px: float) -> Signal:
    """S4: Bollinger Band dışı → geri dönüş."""
    bb = compute_bollinger(closes)
    if bb is None:
        return Signal("BB", 0.0, 0.0, "yetersiz veri")
    upper, mid, lower = bb
    bw = upper - lower
    if bw <= 0:
        return Signal("BB", 0.0, 0.0, "sıkışma")
    if mark_px > upper:
        pct = (mark_px - upper) / bw
        return Signal("BB", round(-W_BB * min(1.0, pct * 2.5), 4),
                      mark_px / upper,
                      f"fiyat BB üstünde +{pct*100:.1f}%→SHORT")
    if mark_px < lower:
        pct = (lower - mark_px) / bw
        return Signal("BB", round(W_BB * min(1.0, pct * 2.5), 4),
                      mark_px / lower,
                      f"fiyat BB altında -{pct*100:.1f}%→LONG")
    return Signal("BB", 0.0, (mark_px - mid) / (bw / 2), "BB içi")


def sig_volume(closes: list[float], vols: list[float]) -> Signal:
    """S5: Volume spike + yön."""
    ratio = compute_vol_spike(vols)
    if ratio < VOL_SPIKE_MULT or len(closes) < 3:
        return Signal("VOL", 0.0, ratio, f"vol normal ×{ratio:.2f}")
    direction = 1 if (closes[-1] > closes[-2]) else -1
    intensity = min(1.0, (ratio - VOL_SPIKE_MULT) / VOL_SPIKE_MULT)
    score = direction * W_VOL * intensity
    return Signal("VOL", round(score, 4), ratio,
                  f"vol spike ×{ratio:.1f} {'▲LONG' if direction>0 else '▼SHORT'}")


def sig_fear_greed(fg_value: int) -> Signal:
    """
    S6: Fear & Greed Index — zıt yön ticareti.
    Tam sinyal: <20 veya >80  |  Kısmi sinyal: 20-40 veya 60-80
    """
    if fg_value <= 20:
        return Signal("FEAR", W_FEAR, fg_value, f"FG={fg_value} ekstrem korku→LONG")
    if fg_value <= FG_EXTREME_FEAR:          # 20-35 arası
        intensity = 0.5 + 0.5 * (FG_EXTREME_FEAR - fg_value) / max(FG_EXTREME_FEAR - 20, 1)
        return Signal("FEAR", round(W_FEAR * intensity, 4), fg_value,
                      f"FG={fg_value} korku→LONG ({intensity:.2f}×)")
    if fg_value <= 45:                        # 35-45: hafif korku
        intensity = 0.25 * (45 - fg_value) / 10
        return Signal("FEAR", round(W_FEAR * intensity, 4), fg_value,
                      f"FG={fg_value} hafif korku (+{W_FEAR*intensity:.2f})")
    if fg_value >= 80:
        return Signal("FEAR", -W_FEAR, fg_value, f"FG={fg_value} ekstrem açgözlülük→SHORT")
    if fg_value >= FG_EXTREME_GREED:         # 70-80 arası
        intensity = 0.5 + 0.5 * (fg_value - FG_EXTREME_GREED) / max(80 - FG_EXTREME_GREED, 1)
        return Signal("FEAR", round(-W_FEAR * intensity, 4), fg_value,
                      f"FG={fg_value} açgözlülük→SHORT ({intensity:.2f}×)")
    if fg_value >= 55:                        # 55-70: hafif açgözlülük
        intensity = 0.25 * (fg_value - 55) / 15
        return Signal("FEAR", round(-W_FEAR * intensity, 4), fg_value,
                      f"FG={fg_value} hafif açgözlülük")
    return Signal("FEAR", 0.0, fg_value, f"FG={fg_value} nötr (45-55)")


def sig_liquidation(coin: str, liq_map: dict[str, float],
                    mark_px: float, closes: list[float]) -> Signal:
    """S7: Büyük tasfiye dalgası → geri dönüş potansiyeli."""
    liq_usd = liq_map.get(coin, 0.0)
    if liq_usd < LIQ_THRESHOLD:
        return Signal("LIQ", 0.0, liq_usd,
                      f"liq=${liq_usd/1e6:.1f}M eşiğin altı")
    # Tasfiye yönünü fiyat hareketinden tahmin et
    if len(closes) < 3:
        return Signal("LIQ", 0.0, liq_usd, "veri yetersiz")
    price_chg = (closes[-1] - closes[-3]) / closes[-3]  # 3 mumda değişim
    intensity  = min(1.0, liq_usd / (LIQ_THRESHOLD * 5))
    if price_chg < -0.01:   # Fiyat düştü → LONG liq olmuş → geri dönüş LONG
        score = W_LIQ * intensity
        return Signal("LIQ", round(score, 4), liq_usd,
                      f"liq=${liq_usd/1e6:.0f}M fiyat{price_chg*100:.1f}%→LONG rebound")
    if price_chg > 0.01:    # Fiyat yükseldi → SHORT liq → geri dönüş SHORT
        score = -W_LIQ * intensity
        return Signal("LIQ", round(score, 4), liq_usd,
                      f"liq=${liq_usd/1e6:.0f}M fiyat+{price_chg*100:.1f}%→SHORT")
    return Signal("LIQ", 0.0, liq_usd, f"liq=${liq_usd/1e6:.1f}M yön belirsiz")


# ── Copy Trade modülü ─────────────────────────────────────────────────────────

_whale_cache: dict = {"wallets": [], "ts": 0.0}
_WHALE_TTL = 3600
_burst_cache: dict[str, tuple[bool, float]] = {}
_BURST_CACHE_TTL = 7200.0


def _fill_burst_is_bot(client: httpx.Client, addr_lower: str) -> bool:
    """45 dk içinde aşırı fill → HFT/bot. Sonuç kısa TTL cache."""
    t = time.time()
    hit = _burst_cache.get(addr_lower)
    if hit and t - hit[1] < _BURST_CACHE_TTL:
        return hit[0]
    st = int(time.time() * 1000) - COPY_BURST_WINDOW_MS
    fills = _post(client, HL_INFO, {
        "type": "userFillsByTime", "user": addr_lower, "startTime": st,
    }, timeout=6.0)
    is_bot = isinstance(fills, list) and len(fills) > COPY_BURST_FILLS
    _burst_cache[addr_lower] = (is_bot, t)
    return is_bot


def _parse_window_perf(row: dict) -> dict[str, dict]:
    """windowPerformances listesini dict'e çevirir."""
    out: dict[str, dict] = {}
    for item in row.get("windowPerformances", []):
        if isinstance(item, list) and len(item) == 2:
            period, vals = item
            out[period] = {
                "pnl": float(vals.get("pnl", 0)),
                "roi": float(vals.get("roi", 0)),
                "vlm": float(vals.get("vlm", 0)),
            }
    return out


def _is_bot_heuristic(perf: dict[str, dict], acct_val: float) -> bool:
    """
    Yüksek frekanslı bot tespiti (fill kontrolsüz, sadece leaderboard verisi).
    Kriter: vlm/PnL > 8000× VEYA (hacim>$100B ve ROI<%5) → büyük ihtimalle bot.
    """
    at  = perf.get("allTime", {})
    pnl = at.get("pnl", 0)
    vlm = at.get("vlm", 0)
    roi = at.get("roi", 0)
    if pnl > 0 and vlm > 0:
        ratio = vlm / pnl
        if ratio > 8000:
            return True
    if vlm > 1e11 and roi < 0.05:
        return True
    return False


def _get_top_wallets(client: httpx.Client) -> list[tuple[str, float]]:
    """
    (adres, ağırlık) listesi döndürür.  Cache: 1 saat.
    Önce .env'deki onaylı insan adresleri, sonra leaderboard'dan bot-filtreli top traderlar.
    """
    now = time.time()
    if now - _whale_cache["ts"] < _WHALE_TTL and _whale_cache["wallets"]:
        return _whale_cache["wallets"]

    result: list[tuple[str, float]] = []

    # 1. Öncelik: .env'deki onaylanmış insan trader adresleri (yüksek ağırlık)
    for addr in COPY_BOT_ADDRS:
        result.append((addr.lower(), 2.5))

    # 2. Leaderboard'dan bot olmayan traderlar
    data = _get(client, f"{HL_STATS}/leaderboard", timeout=20.0)
    rows: list[dict] = []
    if isinstance(data, dict):
        rows = data.get("leaderboardRows") or []
    elif isinstance(data, list):
        rows = data

    existing = {a for a, _ in result}
    bot_filtered: list[tuple[str, float, float, float]] = []
    # (addr, pnl, mo_roi, week_roi)

    for r in rows[:180]:
        addr = r.get("ethAddress") or ""
        if not addr.startswith("0x") or addr.lower() in existing:
            continue
        perf  = _parse_window_perf(r)
        acct  = float(r.get("accountValue", 0))
        at    = perf.get("allTime", {})
        mo    = perf.get("month", {})
        wk    = perf.get("week", {})
        pnl   = at.get("pnl", 0)
        roi   = at.get("roi", 0)
        mo_roi = mo.get("roi", 0)
        wk_roi = wk.get("roi", 0.0)

        if pnl < 50_000:
            continue
        if roi < 0.10:
            continue
        if acct < 1_000:
            continue
        if mo_roi < COPY_MIN_MONTH_ROI:
            continue
        if COPY_MIN_WEEK_ROI > 0 and wk_roi < COPY_MIN_WEEK_ROI:
            continue
        if _is_bot_heuristic(perf, acct):
            continue

        bot_filtered.append((addr.lower(), pnl, mo_roi, wk_roi))

    # Aylık + haftalık ROI birleşik skor
    bot_filtered.sort(key=lambda x: x[2] * 0.65 + x[3] * 0.35, reverse=True)

    vetted: list[tuple[str, float, float, float]] = []
    for tup in bot_filtered[:55]:
        addr = tup[0]
        if _fill_burst_is_bot(client, addr):
            continue
        vetted.append(tup)
        if len(vetted) >= WHALE_TOP_N + 8:
            break

    for addr, pnl, mo_roi, wk_roi in vetted[:WHALE_TOP_N]:
        if addr in existing:
            continue
        score_roi = mo_roi * 0.7 + wk_roi * 0.3
        weight = 1.0 + min(score_roi * 2.2, 1.35)
        result.append((addr, round(weight, 3)))

    _whale_cache.update({"wallets": result, "ts": now})
    print(f"  [whale] {len(COPY_BOT_ADDRS)} onaylı insan + "
          f"{len(vetted)} burst-filtreli trader (LB {len(rows)} satır)")
    return result


def sig_copy_trade(client: httpx.Client, coin: str) -> Signal:
    """S8: Top trader + bot/burst filtresi → taze fill (COPY_LOOKBACK_MS) ile sinyal."""
    wallets = _get_top_wallets(client)
    if not wallets:
        return Signal("COPY", 0.0, 0, "cüzdan listesi boş")

    cutoff = int(time.time() * 1000) - COPY_LOOKBACK_MS
    long_w = short_w = 0.0
    long_n = short_n = 0
    checked = 0

    for addr, weight in wallets[:22]:
        fills = _post(client, HL_INFO, {
            "type": "userFillsByTime",
            "user": addr, "startTime": cutoff,
        }, timeout=6.0)
        if not isinstance(fills, list):
            continue
        checked += 1
        for f in fills:
            if f.get("coin") != coin:
                continue
            d = f.get("dir", "")
            if "Open Long" in d:
                long_w += weight
                long_n += 1
                break
            if "Open Short" in d:
                short_w += weight
                short_n += 1
                break
        time.sleep(0.04)

    total = long_w + short_w
    if total < 0.5:
        return Signal("COPY", 0.0, 0, f"({checked} cüzdan) taze işlem yok")

    bias = (long_w - short_w) / total
    agree_n = long_n if bias > 0 else short_n
    intensity = min(1.0, abs(bias) * (1.0 + 0.14 * min(agree_n, 4)))
    score = bias * W_COPY * intensity
    return Signal("COPY", round(score, 4), float(long_n + short_n),
                  f"{len(wallets)} czd L:{long_w:.1f}({long_n})/S:{short_w:.1f}({short_n}) "
                  f"bias={bias:+.2f} t≤{COPY_LOOKBACK_MS//60000}dk")


# ═══════════════════════════════════════════════════════════════════════════════
#  Analiz motoru
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_coin(client: httpx.Client, coin: str,
                 mark_px: float, hl_fund: float, oi_usd: float,
                 fg_value: int, liq_map: dict[str, float],
                 run_copy: bool = True,
                 cex_venues: Optional[dict[str, float]] = None) -> CoinSignal:
    cs = CoinSignal(coin=coin, mark_px=mark_px, hl_funding=hl_fund,
                    bn_funding=0.0, oi_usd=oi_usd)
    if oi_usd < MIN_OI_USD:
        return cs

    # Mum verisini HL'den çek (birincil)
    candles = hl_candles(client, coin, max(LOOKBACK_CANDLES, BB_PERIOD + 5))
    closes  = [float(c["c"]) for c in candles if "c" in c]
    vols    = [float(c["v"]) for c in candles if "v" in c]

    # Binance OHLCV ile takviye (çapraz doğrulama)
    bn_candles_data = bn_candles(client, coin, n=30)
    if bn_candles_data and len(closes) < RSI_PERIOD + 2:
        closes = [float(c["c"]) for c in bn_candles_data]
        vols   = [float(c["v"]) for c in bn_candles_data]

    if len(closes) < RSI_PERIOD + 2:
        return cs

    # Binance funding
    bn_fund = bn_funding(client, coin)
    cs.bn_funding = bn_fund or 0.0

    # Sinyaller
    cs.signals.append(sig_funding_multi(hl_fund, bn_fund))
    cs.signals.append(sig_rsi(closes))
    cs.signals.append(sig_ema_cross(closes))
    cs.signals.append(sig_bollinger(closes, mark_px))
    cs.signals.append(sig_volume(closes, vols))
    cs.signals.append(sig_fear_greed(fg_value))
    cs.signals.append(sig_liquidation(coin, liq_map, mark_px, closes))
    cs.signals.append(sig_cross_exchange(mark_px, cex_venues or {}))
    if run_copy:
        cs.signals.append(sig_copy_trade(client, coin))

    cs.compute()
    return cs


# ═══════════════════════════════════════════════════════════════════════════════
#  Bakiye takibi
# ═══════════════════════════════════════════════════════════════════════════════

def get_realized_pnl(conn: sqlite3.Connection) -> float:
    r = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd),0) t FROM positions WHERE closed_at IS NOT NULL"
    ).fetchone()
    return float(r["t"])


def get_open_stake(conn: sqlite3.Connection) -> float:
    r = conn.execute(
        "SELECT COALESCE(SUM(stake_usd),0) t FROM positions WHERE closed_at IS NULL"
    ).fetchone()
    return float(r["t"])


def get_unrealized_pnl(conn: sqlite3.Connection,
                        mids: dict[str, float]) -> float:
    rows = conn.execute(
        "SELECT coin, side, entry_price, contracts, funding_paid, last_price "
        "FROM positions WHERE closed_at IS NULL"
    ).fetchall()
    total = 0.0
    for r in rows:
        cur  = mids.get(r["coin"]) or r["last_price"] or r["entry_price"]
        if not cur:
            continue
        ppnl = (r["contracts"] * (float(cur) - r["entry_price"])
                if r["side"] == "LONG"
                else r["contracts"] * (r["entry_price"] - float(cur)))
        total += ppnl + (r["funding_paid"] or 0.0)
    return total


def get_equity(conn: sqlite3.Connection,
               mids: Optional[dict[str, float]] = None) -> float:
    return STARTING_BALANCE + get_realized_pnl(conn) + get_unrealized_pnl(conn, mids or {})


def get_available(conn: sqlite3.Connection,
                  mids: Optional[dict[str, float]] = None) -> float:
    return max(0.0, get_equity(conn, mids) - get_open_stake(conn))


def kelly_stake(conf: float, available: Optional[float] = None) -> float:
    """Kelly × güven × bakiye — dinamik margin büyüklüğü."""
    base  = available if available is not None else STARTING_BALANCE
    stake = base * KELLY_FRACTION * conf
    return round(min(stake, MAX_POS_USD), 4)


def calc_leverage(confidence: float) -> int:
    """
    Sinyal gücüne göre kaldıraç belirle.
    confidence=0 → 2x  |  confidence=1 → 20x

      < 0.15  → 2x
      0.15-0.30 → 3x
      0.30-0.45 → 5x
      0.45-0.60 → 8x
      0.60-0.75 → 12x
      0.75-0.90 → 16x
      > 0.90    → 20x
    """
    if confidence < 0.15: lev = 2
    elif confidence < 0.30: lev = 3
    elif confidence < 0.45: lev = 5
    elif confidence < 0.60: lev = 8
    elif confidence < 0.75: lev = 12
    elif confidence < 0.90: lev = 16
    else: lev = 20
    return max(LEVERAGE_MIN, min(lev, LEVERAGE_MAX))


# ═══════════════════════════════════════════════════════════════════════════════
#  Pozisyon yönetimi
# ═══════════════════════════════════════════════════════════════════════════════

def open_pos(conn: sqlite3.Connection, client: httpx.Client, cs: CoinSignal,
             available: float, fg: int) -> int:
    stake    = min(kelly_stake(cs.confidence, available), available, MAX_POS_USD)
    if stake < 0.5:
        return -1
    leverage   = calc_leverage(cs.confidence)
    notional   = stake * leverage               # gerçek piyasa değeri
    contracts  = notional / cs.mark_px
    tp_frac, sl_frac = dynamic_tp_sl_fracs(client, cs.coin, cs.mark_px)
    strat_str  = ",".join(s.strategy for s in cs.signals if abs(s.score) > 0.05)
    whale_val  = next((int(s.value) for s in cs.signals if s.strategy == "COPY"), 0)
    now        = datetime.now(timezone.utc).isoformat()
    try:
        cur = conn.execute("""
        INSERT INTO positions
          (coin, side, entry_price, stake_usd, contracts,
           score, strategies, hl_funding, bn_funding, fear_greed,
           whale_count, opened_at, funding_paid, last_price, last_update, leverage,
           tp_frac, sl_frac, be_armed)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0.0,?,?,?,?,?,0)
    """, (cs.coin, cs.side, cs.mark_px, round(stake, 4),
          round(contracts, 8), round(cs.total_score, 4),
          strat_str, round(cs.hl_funding, 8),
          round(cs.bn_funding, 8), fg, whale_val,
          now, round(cs.mark_px, 6), now, leverage,
          tp_frac, sl_frac))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        return -2


def close_pos(conn: sqlite3.Connection, pid: int,
              close_price: float, reason: str) -> float:
    row = conn.execute(
        "SELECT side, entry_price, stake_usd, contracts, funding_paid, strategies "
        "FROM positions WHERE id=?", (pid,)
    ).fetchone()
    if not row:
        return 0.0
    ppnl = (row["contracts"] * (close_price - row["entry_price"])
            if row["side"] == "LONG"
            else row["contracts"] * (row["entry_price"] - close_price))
    pnl = ppnl + (row["funding_paid"] or 0.0)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        UPDATE positions SET closed_at=?, close_price=?, pnl_usd=?,
                             close_reason=?, last_price=? WHERE id=?
    """, (now, round(close_price, 6), round(pnl, 4),
          reason, round(close_price, 6), pid))
    conn.commit()
    won = pnl > 0
    if reason not in ("DEDUP", "ADMIN"):
        for strat in (row["strategies"] or "").split(","):
            strat = strat.strip()
            if not strat:
                continue
            conn.execute("""
                INSERT INTO strategy_stats(strategy,wins,losses,total_pnl,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(strategy) DO UPDATE SET
                  wins=wins+excluded.wins, losses=losses+excluded.losses,
                  total_pnl=total_pnl+excluded.total_pnl, updated_at=excluded.updated_at
            """, (strat, 1 if won else 0, 0 if won else 1, round(pnl, 4), now))
        conn.commit()
    return pnl


def apply_funding(conn: sqlite3.Connection, fund_map: dict[str, float],
                  mids: dict[str, float]) -> None:
    rows = conn.execute(
        "SELECT id,coin,side,contracts,opened_at,last_update FROM positions WHERE closed_at IS NULL"
    ).fetchall()
    now_ts  = time.time()
    now_iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
    for r in rows:
        if r["coin"] not in fund_map:
            continue
        last = r["last_update"] or r["opened_at"]
        try:
            elapsed_h = (now_ts - datetime.fromisoformat(
                str(last).replace("Z", "+00:00")).timestamp()) / 3600.0
        except Exception:
            elapsed_h = 0.0
        if elapsed_h < 0.05:
            continue
        mark     = mids.get(r["coin"], 0.0)
        notional = r["contracts"] * mark
        accrued  = notional * fund_map[r["coin"]] * (elapsed_h / 8.0)
        if r["side"] == "SHORT":
            accrued = -accrued
        conn.execute("""
            UPDATE positions SET funding_paid=COALESCE(funding_paid,0)-?,
                                 last_price=?, last_update=? WHERE id=?
        """, (round(accrued, 6), round(mark, 6) if mark else None, now_iso, r["id"]))
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Kontrol döngüsü
# ═══════════════════════════════════════════════════════════════════════════════

def open_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) n FROM positions WHERE closed_at IS NULL"
    ).fetchone()["n"]


def already_open(conn: sqlite3.Connection, coin: str) -> bool:
    return bool(conn.execute(
        "SELECT id FROM positions WHERE coin=? AND closed_at IS NULL", (coin,)
    ).fetchone())


def on_cooldown(conn: sqlite3.Connection, coin: str, side: str) -> bool:
    cutoff = datetime.fromtimestamp(
        time.time() - SL_COOLDOWN_MIN * 60, tz=timezone.utc).isoformat()
    return bool(conn.execute("""
        SELECT id FROM positions WHERE coin=? AND side=? AND
        closed_at>? AND pnl_usd<0 ORDER BY closed_at DESC LIMIT 1
    """, (coin, side, cutoff)).fetchone())


def check_and_close(conn: sqlite3.Connection,
                    client: httpx.Client) -> tuple[int, dict[str, float], str]:
    hl_err = ""
    try:
        mids = hl_all_mids(client)
    except Exception as exc:
        mids = {}
        hl_err = f"allMids istisna: {exc}"
    if not mids and not hl_err:
        hl_err = "allMids boş (HL yanıt yok veya parse hatası)"

    meta, ctxs = hl_meta_ctxs(client)
    fund_map: dict[str, float] = {}
    for u, ctx in zip(meta, ctxs):
        try:
            fund_map[u["name"]] = float(ctx.get("funding") or 0)
        except Exception:
            pass
    if mids:
        apply_funding(conn, fund_map, mids)

    rows = conn.execute(
        "SELECT id,coin,side,entry_price,stake_usd,contracts,opened_at,"
        "funding_paid,leverage,last_price,tp_frac,sl_frac,be_armed "
        "FROM positions WHERE closed_at IS NULL"
    ).fetchall()
    closed_n = 0

    for pos in rows:
        coin     = pos["coin"]
        lp       = pos["last_price"]
        entry    = pos["entry_price"]
        cur      = float(mids.get(coin) or lp or entry or 0.0)
        if not cur:
            continue
        contr    = pos["contracts"]
        stake    = pos["stake_usd"]
        fund     = pos["funding_paid"] or 0.0
        pid      = pos["id"]
        leverage = pos["leverage"] or 1
        tpf = float(pos["tp_frac"] or TAKE_PROFIT_PCT)
        slf = float(pos["sl_frac"] or STOP_LOSS_PCT)
        be_armed = int(pos["be_armed"] or 0)

        ppnl     = (contr * (cur - entry) if pos["side"] == "LONG"
                    else contr * (entry - cur))
        upnl     = ppnl + fund
        pct_move = ((cur - entry) / entry if pos["side"] == "LONG"
                    else (entry - cur) / entry)
        pct_stake = pct_move * leverage   # kaldıraçlı stake getirisi

        used_stale = not mids.get(coin)
        stale_tag = " [son fiyat]" if used_stale else ""

        # TP/SL: satır bazlı ATR oranları; break-even kâr kilidi
        if pct_move >= tpf:
            pnl = close_pos(conn, pid, cur, "TP")
            print(f"  💰 TP  [{pid}] {coin:<6} {pos['side']} {leverage}x{stale_tag}  "
                  f"fiyat:+{pct_move*100:.2f}%  stake:{pct_stake*100:+.1f}%  PnL=${pnl:+.4f}")
            closed_n += 1
            continue
        if pct_move <= -slf:
            pnl = close_pos(conn, pid, cur, "SL")
            print(f"  ⛔ SL  [{pid}] {coin:<6} {pos['side']} {leverage}x{stale_tag}  "
                  f"fiyat:{pct_move*100:.2f}%  stake:{pct_stake*100:+.1f}%  PnL=${pnl:+.4f}")
            closed_n += 1
            continue

        if USE_BREAK_EVEN and be_armed:
            if pos["side"] == "LONG" and cur <= entry * (1.0 - BE_GIVEBACK_FRAC):
                pnl = close_pos(conn, pid, cur, "BE")
                print(f"  ⚖ BE  [{pid}] {coin:<6} LONG{stale_tag}  "
                      f"giveback→giriş  PnL=${pnl:+.4f}")
                closed_n += 1
                continue
            if pos["side"] == "SHORT" and cur >= entry * (1.0 + BE_GIVEBACK_FRAC):
                pnl = close_pos(conn, pid, cur, "BE")
                print(f"  ⚖ BE  [{pid}] {coin:<6} SHORT{stale_tag}  "
                      f"giveback→giriş  PnL=${pnl:+.4f}")
                closed_n += 1
                continue

        if USE_BREAK_EVEN and not be_armed and pct_move >= tpf * BE_ARM_FRAC:
            conn.execute(
                "UPDATE positions SET be_armed=1 WHERE id=?", (pid,))
            conn.commit()
            print(f"  🔒 BE-arm [{pid}] {coin:<6} {pos['side']}  "
                  f"kâr %{pct_move*100:.2f} ≥ {BE_ARM_FRAC:.0%}×TP")

        try:
            odt   = datetime.fromisoformat(
                str(pos["opened_at"]).replace("Z", "+00:00"))
            age_h = (time.time() - odt.timestamp()) / 3600.0
        except Exception:
            age_h = 0.0
        if age_h >= MAX_HOLD_HOURS:
            pnl = close_pos(conn, pid, cur, "TIMEOUT")
            print(f"  ⏱ EXP [{pid}] {coin:<6} {pos['side']}{stale_tag} "
                  f"{age_h:.1f}h  PnL=${pnl:+.4f}")
            closed_n += 1
            continue

        mv  = (cur - entry) / entry * 100
        ind = "▲" if upnl > 0 else "▼"
        print(f"  {ind} [{pid:>2}] {coin:<6} {pos['side']:<5} {leverage}x{stale_tag}  "
              f"@{entry:.4f}→{cur:.4f} ({mv:+.2f}%)  "
              f"stake:{pct_stake*100:+.1f}% (${upnl:+.4f})  "
              f"kalan={MAX_HOLD_HOURS-age_h:.1f}h")
    return closed_n, mids, hl_err


# ═══════════════════════════════════════════════════════════════════════════════
#  Hızlı Backtest
# ═══════════════════════════════════════════════════════════════════════════════

def quick_backtest(client: httpx.Client, coin: str,
                   days: int = BACKTEST_DAYS) -> dict:
    n = days * 24 + LOOKBACK_CANDLES + 5
    raw = hl_candles(client, coin, n=n, interval="1h")
    # Binance ile takviye
    if len(raw) < LOOKBACK_CANDLES + 10:
        raw = bn_candles(client, coin, n=n, interval="1h")
    if len(raw) < LOOKBACK_CANDLES + 10:
        return {"wins": 0, "losses": 0, "win_rate": 0.5, "avg_pnl": 0.0, "trades": 0}

    wins = losses = 0
    pnls: list[float] = []
    bt_min = MIN_SCORE * 0.60  # backtest'te funding+copy yok, eşiği düşür

    for i in range(LOOKBACK_CANDLES, len(raw) - 1):
        window  = raw[i - LOOKBACK_CANDLES: i]
        closes  = [float(c["c"]) for c in window]
        vols    = [float(c["v"]) for c in window if "v" in c]
        if len(closes) < RSI_PERIOD + 2:
            continue
        mark = float(raw[i]["o"])
        sigs = [
            sig_funding_multi(0.0, None),
            sig_rsi(closes),
            sig_ema_cross(closes),
            sig_bollinger(closes, float(window[-1]["c"])),
            sig_volume(closes, vols),
            sig_fear_greed(50),    # backtest'te sabit nötr
        ]
        total = sum(s.score for s in sigs)
        if abs(total) < bt_min:
            continue
        side = "LONG" if total > 0 else "SHORT"
        tp   = mark * (1 + TAKE_PROFIT_PCT) if side == "LONG" else mark * (1 - TAKE_PROFIT_PCT)
        sl   = mark * (1 - STOP_LOSS_PCT)   if side == "LONG" else mark * (1 + STOP_LOSS_PCT)
        for j in range(i + 1, min(i + 25, len(raw))):
            hi, lo = float(raw[j]["h"]), float(raw[j]["l"])
            if side == "LONG":
                if lo <= sl:  losses += 1; pnls.append(-STOP_LOSS_PCT); break
                if hi >= tp:  wins   += 1; pnls.append(TAKE_PROFIT_PCT); break
            else:
                if hi >= sl:  losses += 1; pnls.append(-STOP_LOSS_PCT); break
                if lo <= tp:  wins   += 1; pnls.append(TAKE_PROFIT_PCT); break
        else:
            last = float(raw[min(i + 24, len(raw) - 1)]["c"])
            pnl  = (last - mark) / mark if side == "LONG" else (mark - last) / mark
            (wins if pnl > 0 else losses).__class__  # dummy
            if pnl > 0: wins += 1
            else: losses += 1
            pnls.append(pnl)

    n_tr = wins + losses
    return {
        "wins": wins, "losses": losses,
        "win_rate": wins / n_tr if n_tr else 0.5,
        "avg_pnl":  sum(pnls) / len(pnls) if pnls else 0.0,
        "trades":   n_tr,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Market tarama
# ═══════════════════════════════════════════════════════════════════════════════

def scan(conn: sqlite3.Connection, client: httpx.Client,
         mids: dict[str, float], backtest_wrs: dict[str, float]) -> int:

    if open_count(conn) >= MAX_OPEN_POS:
        print(f"  [scan] Limit dolu ({MAX_OPEN_POS})")
        return 0

    available = get_available(conn, mids)
    if available < 0.5:
        print(f"  [scan] Yetersiz bakiye ${available:.2f}")
        return 0

    fg = fear_greed_index(client)
    print(f"  [scan] Fear&Greed={fg}  Kullanılabilir=${available:.2f}")

    liq_map = coinglass_liquidations(client)

    meta, ctxs = hl_meta_ctxs(client)
    ctx_map: dict[str, dict] = {
        u["name"]: ctx for u, ctx in zip(meta, ctxs)
        if not u.get("isDelisted")
    }

    cex_book = build_cex_price_book(client)
    try:
        spreads: list[tuple[str, float]] = []
        for cc, row in cex_book.items():
            if len(row) < 2:
                continue
            ctx = ctx_map.get(cc)
            if not ctx:
                continue
            hlp = float(ctx.get("markPx") or mids.get(cc) or 0)
            if hlp <= 0:
                continue
            med = float(statistics.median(row.values()))
            spreads.append((cc, abs(hlp - med) / hlp))
        spreads.sort(key=lambda x: -x[1])
        if spreads:
            print("  [cex] HL vs CEX medyan (en yüksek sapma): "
                  + ", ".join(f"{a}:{b*100:.3f}%" for a, b in spreads[:5]))
    except Exception:
        pass

    candidates = [
        (c, px, oi, f) for c, px, oi, f in scan_candidate_rows(meta, ctxs, ctx_map, mids)
        if not already_open(conn, c)
    ]
    wl_tag = "DYN" if ENGINE_DYNAMIC_WATCHLIST else "FIX"
    print(f"  [scan] evren={wl_tag} {len(candidates)} aday taranıyor…")
    opened = 0

    for coin, px, oi_usd, hl_fund in candidates:
        if open_count(conn) >= MAX_OPEN_POS:
            break
        available = get_available(conn, mids)
        if available < 0.5:
            break

        # Ön filtre: F&G korku/açgözlülük bölgesindeyse TÜM coinler geçer
        if fg <= 45 or fg >= 55:
            pass   # F&G aktif → hepsini analiz et
        else:
            # Nötr F&G: düşük funding + RSI "ölü bant" ise bu coini atla
            q_closes = [float(c["c"]) for c in hl_candles(client, coin, 20)]
            rsi_q = compute_rsi(q_closes) if q_closes else None
            if (abs(hl_fund) < FUNDING_EXTREME * 0.3 and
                    rsi_q is not None and
                    RSI_OVERSOLD + 10 < rsi_q < RSI_OVERBOUGHT - 10):
                continue

        run_copy = len(candidates) <= 6
        cex_row = cex_book.get(coin, {})
        cs = analyze_coin(client, coin, px, hl_fund, oi_usd, fg, liq_map,
                          run_copy=run_copy, cex_venues=cex_row)
        time.sleep(0.1)

        # Skor debug logu
        if abs(cs.total_score) > 0.3:
            sigs_str = " ".join(
                f"{s.strategy}:{s.score:+.2f}" for s in cs.signals if abs(s.score) > 0.05)
            print(f"  · {coin:<6} skor={cs.total_score:+.3f} "
                  f"(min={MIN_SCORE}) side={cs.side or '—'}  {sigs_str}")

        if not cs.side or on_cooldown(conn, coin, cs.side):
            continue

        bt_wr = backtest_wrs.get(coin, 0.5)
        if bt_wr < ENGINE_BT_MIN_WR:
            print(f"  ⚠ [{coin}] backtest WR={bt_wr:.1%} < {ENGINE_BT_MIN_WR:.0%}, atlandı")
            continue

        pid = open_pos(conn, client, cs, available, fg)
        if pid == -2:
            print(f"  ⊗ [{coin}] aynı coinde zaten açık pozisyon (UNIQUE / yarış engeli)")
            continue
        if pid > 0:
            active  = [s for s in cs.signals if abs(s.score) > 0.05]
            strats  = " | ".join(f"{s.strategy}:{s.score:+.1f}" for s in active)
            row     = conn.execute(
                "SELECT stake_usd, leverage FROM positions WHERE id=?", (pid,)
            ).fetchone()
            stake   = row["stake_usd"]
            lev     = row["leverage"] or 1
            notional = stake * lev
            new_av  = get_available(conn, mids)
            print(f"  ➕ [{pid}] {cs.side:<5} {coin:<6} @{px:.4f}  "
                  f"score={cs.total_score:+.2f}  {lev}x  "
                  f"margin=${stake:.2f}  notional=${notional:.2f}  "
                  f"bt={bt_wr:.0%}  bakiye=${new_av:.2f}")
            print(f"       └─ {strats}")
            opened += 1

    return opened


# ═══════════════════════════════════════════════════════════════════════════════
#  Başlangıç backtest
# ═══════════════════════════════════════════════════════════════════════════════

def startup_backtest(client: httpx.Client) -> dict[str, float]:
    print(f"\n  [backtest] {BACKTEST_DAYS} günlük veri testi başlıyor…")
    scores: dict[str, float] = {}
    priority = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "AVAX", "LINK"]
    coins = priority + [c for c in WATCHLIST if c not in priority]
    for coin in coins[:12]:
        try:
            bt   = quick_backtest(client, coin, days=BACKTEST_DAYS)
            wr   = bt["win_rate"]
            scores[coin] = wr
            star = "★" if wr >= 0.55 else (" " if wr >= 0.45 else "✗")
            print(f"    {star} {coin:<6} "
                  f"t={bt['trades']:>3}  "
                  f"W{bt['wins']}/L{bt['losses']}  "
                  f"WR={wr:.0%}  avgPnL={bt['avg_pnl']*100:+.2f}%")
        except Exception as e:
            scores[coin] = 0.5
            print(f"    ? {coin:<6} hata: {e}")
        time.sleep(0.1)
    ok = sum(1 for v in scores.values() if v >= 0.5)
    print(f"  [backtest] {ok}/{len(scores)} coin ≥50% WR\n")
    return scores


# ═══════════════════════════════════════════════════════════════════════════════
#  Ana döngü
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)   # type: ignore[attr-defined]
    try:
        from scanner_runtime import singleton_process_lock, write_heartbeat_atomic
    except ImportError:
        import contextlib

        def singleton_process_lock(_path: Path):  # type: ignore[misc]
            return contextlib.nullcontext()

        def write_heartbeat_atomic(_path: Path, _data: dict) -> None:  # type: ignore[misc]
            pass

    try:
        with singleton_process_lock(ENGINE_LOCK):
            _run_engine_main(write_heartbeat_atomic)
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)


def _run_engine_main(write_heartbeat_atomic) -> None:
    conn = init_db(ENGINE_DB)
    merged = dedupe_open_positions_same_coin(conn)
    if merged:
        print(f"  [startup] {merged} çift açık kayıt DEDUP ile kapatıldı.")
    _ensure_unique_open_coin_index(conn)

    client = httpx.Client(
        timeout=20.0,
        headers={"User-Agent": "crypto-engine/2.0", "Accept": "application/json"},
        follow_redirects=True,
    )

    stopped = False
    def _stop(*_):
        nonlocal stopped
        stopped = True
        print("\n[Ctrl+C] Motor durduruluyor…")
    signal.signal(signal.SIGINT, _stop)

    print("=" * 76)
    print(" CRYPTO FUTURES ENGINE  —  Çok Kaynaklı, Çok Stratejili, Paper $20")
    print(f" DB        : {ENGINE_DB}")
    print(f" Kilit     : {ENGINE_LOCK}")
    print(f" Heartbeat : {ENGINE_HEARTBEAT}")
    print(f" Bakiye    : ${STARTING_BALANCE}  Kelly:{KELLY_FRACTION}  Max:${MAX_POS_USD}/pos")
    print(f" TP/SL     : taban %{TAKE_PROFIT_PCT*100:.1f}/%{STOP_LOSS_PCT*100:.1f}  "
          f"ATR={'açık' if USE_ATR_EXITS else 'kapalı'}  BE={'açık' if USE_BREAK_EVEN else 'kapalı'}  "
          f"MaxSüre:{MAX_HOLD_HOURS}h")
    print(f" Kaldıraç  : {LEVERAGE_MIN}x–{LEVERAGE_MAX}x  (sinyal gücüne göre otomatik)")
    print(f" Min Puan  : {MIN_SCORE}/{MAX_SCORE:.1f}")
    print(f" Bot Adres : {len(COPY_BOT_ADDRS)} kayıtlı")
    print(" Kaynaklar : HL + Binance/Bybit/OKX/Gate fiyat + F&G + CoinGecko + CoinGlass")
    print(" Stratejiler: FUNDING RSI COPY FEAR EMA BB LIQ VOL CEX_ARB")
    print("=" * 76)

    eq = get_equity(conn)
    print(f" Equity: ${eq:.4f}  "
          f"Realize P&L: ${get_realized_pnl(conn):+.4f}  "
          f"Açık: {open_count(conn)}")

    # Başlangıç backtest
    backtest_wrs: dict[str, float] = {}
    try:
        backtest_wrs = startup_backtest(client)
    except Exception as e:
        print(f"  [backtest] atlandı: {e}")
        backtest_wrs = {c: 0.5 for c in WATCHLIST}

    pos_cycle = 0
    last_scan = 0.0
    last_data_log = 0.0

    while not stopped:
        loop_start = time.time()
        pos_cycle += 1
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{now_str}] Kontrol #{pos_cycle}")

        closed_n, mids, hl_err = check_and_close(conn, client)
        if closed_n:
            print(f"  {closed_n} pozisyon kapatıldı.")
        if hl_err and pos_cycle % 4 == 1:
            print(f"  ⚠ HL: {hl_err}")

        if loop_start - last_scan >= SCAN_INTERVAL:
            opened    = scan(conn, client, mids, backtest_wrs)
            last_scan = time.time()
        else:
            opened = 0

        # Veri logu (30dk'da bir)
        if loop_start - last_data_log >= 1800:
            try:
                fg = fear_greed_index(client)
                cg = cg_market_data(client, WATCHLIST[:10])
                meta, ctxs = hl_meta_ctxs(client)
                extremes = sum(
                    1 for ctx in ctxs
                    if abs(float(ctx.get("funding") or 0)) > FUNDING_EXTREME
                )
                top3 = sorted(
                    [(c, cg.get(c, {}).get("24h_pct", 0)) for c in WATCHLIST[:10]],
                    key=lambda x: abs(x[1]), reverse=True
                )[:3]
                top_str = ",".join(f"{c}:{v:+.1f}%" for c, v in top3)
                conn.execute(
                    "INSERT INTO data_log(ts,fear_greed,top_coins,hl_extremes) VALUES(?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), fg, top_str, extremes)
                )
                conn.commit()
                print(f"  📊 Fear&Greed={fg}  HL extreme={extremes}  Top3:{top_str}")
            except Exception:
                pass
            last_data_log = loop_start

        # Özet
        realized   = get_realized_pnl(conn)
        unrealized = get_unrealized_pnl(conn, mids)
        equity     = STARTING_BALANCE + realized + unrealized
        stake      = get_open_stake(conn)
        avail      = max(0.0, equity - stake)
        open_n     = open_count(conn)
        closed_tot = conn.execute(
            "SELECT COUNT(*) n FROM positions WHERE closed_at IS NOT NULL"
        ).fetchone()["n"]
        eq_pct     = (equity - STARTING_BALANCE) / STARTING_BALANCE * 100
        scan_info  = f"  Yeni:{opened}" if opened else ""
        print(f"  💼 ${equity:.4f}({eq_pct:+.2f}%)  "
              f"Kullanılabilir=${avail:.2f}  "
              f"Stake=${stake:.2f}  ↑${realized:+.4f}  ~${unrealized:+.4f}  "
              f"Açık:{open_n} Kapalı:{closed_tot}{scan_info}")

        write_heartbeat_atomic(ENGINE_HEARTBEAT, {
            "engine": "crypto_engine",
            "db": str(ENGINE_DB),
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "loop": pos_cycle,
            "equity": round(equity, 4),
            "open_positions": open_n,
            "mids_count": len(mids),
            "mids_ok": bool(mids),
            "hl_last_error": hl_err,
            "seconds_since_full_scan": round(loop_start - last_scan, 1) if last_scan else -1.0,
        })

        # Strateji istatistikleri (15 döngüde bir)
        if pos_cycle % 15 == 0:
            stats = conn.execute(
                "SELECT strategy,wins,losses,total_pnl FROM strategy_stats"
            ).fetchall()
            if stats:
                print("  📊 Strateji performansı:")
                for s in sorted(stats, key=lambda x: x["wins"]+x["losses"], reverse=True):
                    n  = s["wins"] + s["losses"]
                    wr = s["wins"] / n if n else 0
                    print(f"      {s['strategy']:<10} "
                          f"W/L={s['wins']}/{s['losses']}  "
                          f"WR={wr:.0%}  PnL=${s['total_pnl']:+.4f}")

        if stopped:
            break
        end = loop_start + POS_CHECK
        while not stopped and time.time() < end:
            time.sleep(0.1)

    conn.close()
    client.close()
    print("Motor kapandı.")


if __name__ == "__main__":
    main()
