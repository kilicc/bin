"""
Crypto Futures Scanner — Hyperliquid Perpetuals, Multi-Strategy Paper Mode
===========================================================================

7 STRATEJI  ×  AĞIRLIKLI PUANLAMA  ×  OTOMATIK BACKTEST

──────────────────────────────────────────────────────────────────────────
 STRATEJİ         AĞIRLIK  AÇIKLAMA
──────────────────────────────────────────────────────────────────────────
 FUNDING_EXT        2.5    Funding rate aşırı → zıt yön pozisyon
 RSI_EXTREME        2.0    RSI <38 oversold LONG / >62 overbought SHORT
 EMA_CROSS          1.5    EMA9 × EMA21 crossover yönü
 BB_EXTREME         1.5    Bollinger Band dışına çıkış → geri dönüş
 VOL_BREAKOUT       1.0    Hacim spike + fiyat yönü
 WHALE_COPY         1.0    Hyperliquid leaderboard top cüzdan yönü
 FEAR_GREED         1.5    Alt.me Fear&Greed Index — zıt yön ticareti
──────────────────────────────────────────────────────────────────────────
 Maks puan  = 11.0   │  Min giriş puanı = MIN_SCORE (varsayılan 2.0)

Puan Mantığı:
  Her strateji: +ağırlık (LONG) / -ağırlık (SHORT) / 0 (nötr)
  Toplam puan pozitif → LONG,  negatif → SHORT
  |puan| ≥ MIN_SCORE → pozisyon aç

Otomatik Backtest (başlangıçta):
  Son 7 günün 1h mum verisi üzerinde her coin için strateji puanları
  geriye dönük test edilir. Coin başına win-rate hesaplanır, MIN_SCORE
  eşiği coin bazında otomatik ayarlanır.

Paper Demo ($20 bakiye):
  - Başlangıç: $20.00
  - Pozisyon başına max: $5.00
  - Kelly fraction: 0.25
  - TP / SL: fiyat %3.5 (varsayılan; TAKE_PROFIT_STAKE_PCT / STOP_LOSS_STAKE_PCT)
  - Bakiye gerçek zamanlı takip (equity = başlangıç + realize + unrealize)
"""
from __future__ import annotations

import math
import os
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

FUTURES_LOCK      = ROOT / "data" / "crypto_futures_scanner.lock"
FUTURES_HEARTBEAT = ROOT / "data" / "crypto_futures_scanner.heartbeat.json"

try:
    from config import DATA_DIR, settings
    DB_PATH          = settings.paper_db
    STARTING_BALANCE = settings.paper_starting_balance
    TAKE_PROFIT_PCT  = settings.take_profit_stake_pct
    STOP_LOSS_PCT    = settings.stop_loss_stake_pct
except Exception:
    DATA_DIR         = ROOT / "data"
    DB_PATH          = DATA_DIR / "paper.db"
    STARTING_BALANCE = 20.0
    TAKE_PROFIT_PCT  = 0.035
    STOP_LOSS_PCT    = 0.035

# Tahmin (config) ile aynı isimli env’i paylaşmamak için: HL perp’te fiyat % TP/SL
if os.getenv("FUT_TP_PCT"):
    TAKE_PROFIT_PCT = float(os.environ["FUT_TP_PCT"])
if os.getenv("FUT_SL_PCT"):
    STOP_LOSS_PCT = float(os.environ["FUT_SL_PCT"])

# ── Operasyonel parametreler ──────────────────────────────────────────────────
SCAN_INTERVAL   = int(os.getenv("FUT_SCAN_INTERVAL_SEC",    "60"))
POS_CHECK       = int(os.getenv("FUT_POSITION_CHECK_SEC",   "15"))
MAX_POS_USD     = float(os.getenv("FUT_MAX_POSITION_USD",   "5.0"))
KELLY_FRACTION  = float(os.getenv("FUT_KELLY_FRACTION",     "0.25"))
MAX_OPEN_POS    = int(os.getenv("FUT_MAX_OPEN_POSITIONS",   "10"))
MAX_HOLD_HOURS  = float(os.getenv("FUT_MAX_HOLD_HOURS",     "24.0"))
SL_COOLDOWN_MIN = int(os.getenv("FUT_SL_COOLDOWN_MINUTES",  "60"))
MIN_OI_USD      = float(os.getenv("FUT_MIN_OI_USD",         "5000000"))

# ── Strateji eşikleri ─────────────────────────────────────────────────────────
MIN_SCORE          = float(os.getenv("FUT_MIN_SCORE",          "2.0"))
LEVERAGE_MIN       = int(os.getenv("FUT_LEVERAGE_MIN",         "2"))
LEVERAGE_MAX       = int(os.getenv("FUT_LEVERAGE_MAX",         "20"))
FUNDING_EXTREME    = float(os.getenv("FUT_FUNDING_EXTREME",    "0.00008"))
RSI_OVERSOLD       = float(os.getenv("FUT_RSI_OVERSOLD",       "38.0"))
RSI_OVERBOUGHT     = float(os.getenv("FUT_RSI_OVERBOUGHT",     "62.0"))
RSI_PERIOD         = int(os.getenv("FUT_RSI_PERIOD",           "14"))
BB_PERIOD          = int(os.getenv("FUT_BB_PERIOD",            "20"))
BB_STD             = float(os.getenv("FUT_BB_STD",             "1.8"))
EMA_FAST           = int(os.getenv("FUT_EMA_FAST",             "9"))
EMA_SLOW           = int(os.getenv("FUT_EMA_SLOW",             "21"))
VOL_LOOKBACK       = int(os.getenv("FUT_VOL_LOOKBACK",         "20"))
VOL_SPIKE_MULT     = float(os.getenv("FUT_VOL_SPIKE_MULT",     "1.8"))
CANDLE_INTERVAL    = os.getenv("FUT_CANDLE_INTERVAL",          "1h")
LOOKBACK_CANDLES   = int(os.getenv("FUT_LOOKBACK_CANDLES",     "60"))
WHALE_TOP_N        = int(os.getenv("FUT_WHALE_TOP_N",          "20"))
BACKTEST_DAYS      = int(os.getenv("FUT_BACKTEST_DAYS",        "7"))
# Fear & Greed eşikleri (engine ile aynı)
FG_EXTREME_FEAR    = int(os.getenv("ENGINE_FG_FEAR",           "35"))
FG_EXTREME_GREED   = int(os.getenv("ENGINE_FG_GREED",          "70"))

# ATR tabanlı TP/SL + break-even (crypto_engine ile aynı ENGINE_* anahtarları)
USE_ATR_EXITS      = os.getenv("ENGINE_USE_ATR_EXITS", "1").lower() in ("1", "true", "yes")
ATR_PERIOD         = int(os.getenv("ENGINE_ATR_PERIOD", "14"))
ATR_TP_MULT         = float(os.getenv("ENGINE_ATR_TP_MULT", "1.06"))
ATR_SL_MULT         = float(os.getenv("ENGINE_ATR_SL_MULT", "0.94"))
ATR_TP_MIN_FRAC     = float(os.getenv("ENGINE_ATR_TP_MIN_FRAC", "0.010"))
ATR_TP_MAX_FRAC     = float(os.getenv("ENGINE_ATR_TP_MAX_FRAC", "0.050"))
ATR_SL_MIN_FRAC     = float(os.getenv("ENGINE_ATR_SL_MIN_FRAC", "0.009"))
ATR_SL_MAX_FRAC     = float(os.getenv("ENGINE_ATR_SL_MAX_FRAC", "0.045"))
USE_BREAK_EVEN      = os.getenv("ENGINE_USE_BREAK_EVEN", "1").lower() in ("1", "true", "yes")
BE_ARM_FRAC         = float(os.getenv("ENGINE_BE_ARM_FRAC", "0.46"))
BE_GIVEBACK_FRAC    = float(os.getenv("ENGINE_BE_GIVEBACK", "0.00042"))

ENGINE_DYNAMIC_WATCHLIST = os.getenv("ENGINE_DYNAMIC_WATCHLIST", "1").lower() in ("1", "true", "yes")
ENGINE_WATCHLIST_MAX     = int(os.getenv("ENGINE_WATCHLIST_MAX", "44"))
ENGINE_ANCHOR_COINS      = os.getenv("ENGINE_ANCHOR_COINS", "BTC,ETH,SOL")
ENGINE_BT_MIN_WR         = float(os.getenv("ENGINE_BT_MIN_WR", "0.37"))

COPY_LOOKBACK_MS       = int(os.getenv("ENGINE_COPY_LOOKBACK_MS", "720000"))
COPY_BURST_WINDOW_MS   = int(os.getenv("ENGINE_COPY_BURST_WINDOW_MS", "2700000"))
COPY_BURST_FILLS       = int(os.getenv("ENGINE_COPY_BURST_FILLS", "52"))
COPY_MIN_MONTH_ROI     = float(os.getenv("ENGINE_COPY_MIN_MONTH_ROI", "0.026"))
COPY_MIN_WEEK_ROI      = float(os.getenv("ENGINE_COPY_MIN_WEEK_ROI", "0.0"))

_bot_whale = os.getenv("COPY_BOT_ADDRESSES", "")
COPY_BOT_ADDRS: set[str] = {
    a.strip().lower() for a in _bot_whale.split(",") if a.strip().startswith("0x")
}

# Strateji ağırlıkları
W_FUNDING  = 2.5
W_RSI      = 2.0
W_EMA      = 1.5
W_BB       = 1.5
W_VOL      = 1.0
W_WHALE    = 1.0
W_FEAR     = 1.5   # Fear & Greed — engine ile aynı
MAX_SCORE  = W_FUNDING + W_RSI + W_EMA + W_BB + W_VOL + W_WHALE + W_FEAR  # 11.0

# ── API ───────────────────────────────────────────────────────────────────────
HL_INFO  = "https://api.hyperliquid.xyz/info"
HL_STATS = "https://stats-data.hyperliquid.xyz/Mainnet"

# ── İzlenen coin listesi (en likit Hyperliquid perp'ler) ─────────────────────
WATCHLIST = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK",
    "DOT", "NEAR", "APT", "SUI", "INJ", "TIA", "WIF", "PEPE", "ARB",
    "OP", "MATIC", "ATOM", "LTC", "BCH", "FIL", "AAVE", "UNI", "TRUMP",
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Veri yapıları
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SignalResult:
    """Tek bir strateji sinyali."""
    strategy: str
    score: float          # pozitif=LONG, negatif=SHORT, 0=nötr
    value: float          # ham indikatör değeri
    detail: str = ""


@dataclass
class CoinSignal:
    """Bir coin için tüm strateji sinyallerinin özeti."""
    coin: str
    mark_px: float
    funding: float
    oi_usd: float
    signals: list[SignalResult] = field(default_factory=list)
    total_score: float = 0.0
    side: str = ""          # "LONG" | "SHORT" | ""
    confidence: float = 0.0

    def compute(self) -> None:
        self.total_score = sum(s.score for s in self.signals)
        abs_score = abs(self.total_score)
        if abs_score >= MIN_SCORE:
            self.side = "LONG" if self.total_score > 0 else "SHORT"
            self.confidence = min(1.0, abs_score / MAX_SCORE)
        else:
            self.side = ""
            self.confidence = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
#  DB
# ═══════════════════════════════════════════════════════════════════════════════

def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS futures_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            stake_usd REAL NOT NULL,
            contracts REAL NOT NULL,
            score REAL NOT NULL DEFAULT 0,
            strategies TEXT NOT NULL DEFAULT '',
            funding_rate REAL NOT NULL DEFAULT 0,
            rsi REAL,
            whale_confirms INTEGER NOT NULL DEFAULT 0,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            close_price REAL,
            pnl_usd REAL,
            close_reason TEXT,
            funding_paid REAL NOT NULL DEFAULT 0.0,
            last_price REAL,
            last_update TEXT
        )
    """)
    # Strateji performans tablosu
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_stats (
            strategy TEXT PRIMARY KEY,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            total_pnl REAL NOT NULL DEFAULT 0.0,
            updated_at TEXT
        )
    """)
    # Migration
    for col, typedef in [
        ("score",         "REAL NOT NULL DEFAULT 0"),
        ("strategies",    "TEXT NOT NULL DEFAULT ''"),
        ("funding_paid",  "REAL NOT NULL DEFAULT 0.0"),
        ("last_price",    "REAL"),
        ("last_update",   "TEXT"),
        ("leverage",      "INTEGER NOT NULL DEFAULT 1"),
        ("tp_frac",       "REAL"),
        ("sl_frac",       "REAL"),
        ("be_armed",      "INTEGER NOT NULL DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE futures_positions ADD COLUMN {col} {typedef}")
        except Exception:
            pass
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fut_open
        ON futures_positions(coin, closed_at)
    """)
    conn.commit()
    return conn


def _ensure_unique_futures_open_coin(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_fut_one_open_coin "
            "ON futures_positions(coin) WHERE closed_at IS NULL"
        )
        conn.commit()
    except sqlite3.OperationalError:
        conn.rollback()


def dedupe_futures_open_same_coin(conn: sqlite3.Connection) -> int:
    n = 0
    dups = conn.execute(
        "SELECT coin FROM futures_positions WHERE closed_at IS NULL "
        "GROUP BY coin HAVING COUNT(*) > 1"
    ).fetchall()
    for d in dups:
        coin = d["coin"]
        rows = conn.execute(
            "SELECT id FROM futures_positions WHERE coin=? AND closed_at IS NULL "
            "ORDER BY id ASC",
            (coin,),
        ).fetchall()
        for extra in rows[1:]:
            pid = int(extra["id"])
            r = conn.execute(
                "SELECT last_price, entry_price FROM futures_positions WHERE id=?",
                (pid,),
            ).fetchone()
            if not r:
                continue
            px = float(r["last_price"] or r["entry_price"] or 0.0)
            if px <= 0:
                px = float(r["entry_price"] or 1.0)
            close_position(conn, pid, px, "DEDUP")
            n += 1
    return n


# ═══════════════════════════════════════════════════════════════════════════════
#  Hyperliquid API yardımcıları
# ═══════════════════════════════════════════════════════════════════════════════

def _hl_post(client: httpx.Client, payload: dict,
             retries: int = 2, timeout: float = 12.0) -> dict | list | None:
    for attempt in range(retries + 1):
        try:
            r = client.post(HL_INFO, json=payload,
                            headers={"Content-Type": "application/json"},
                            timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            if attempt < retries:
                time.sleep(1.0)
    return None


def _hl_get(client: httpx.Client, path: str,
            retries: int = 2, timeout: float = 15.0) -> dict | list | None:
    url = f"{HL_STATS}/{path}"
    for attempt in range(retries + 1):
        try:
            r = client.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            if attempt < retries:
                time.sleep(1.0)
    return None


def fetch_candles(client: httpx.Client, coin: str,
                  n: int = LOOKBACK_CANDLES,
                  interval: str = CANDLE_INTERVAL) -> list[dict]:
    ms = {"1m": 60_000, "5m": 300_000, "15m": 900_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
    iv = ms.get(interval, 3_600_000)
    now_ms = int(time.time() * 1000)
    data = _hl_post(client, {
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval,
                "startTime": now_ms - n * iv * 2, "endTime": now_ms},
    }, timeout=15.0)
    return (data or [])[-n:]


def fetch_fear_greed() -> int:
    """Alternative.me Fear & Greed Index (0-100). 50 döner hata durumunda."""
    try:
        r = httpx.get("https://api.alternative.me/fng/?limit=1", timeout=8)
        return int(r.json()["data"][0]["value"])
    except Exception:
        return 50  # nötr varsay


def fetch_all_mids(client: httpx.Client) -> dict[str, float]:
    raw = _hl_post(client, {"type": "allMids"})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            pass
    return out


def fetch_meta_ctxs(client: httpx.Client) -> tuple[list, list]:
    data = _hl_post(client, {"type": "metaAndAssetCtxs"})
    if not data or len(data) < 2:
        return [], []
    return data[0].get("universe", []), data[1]


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
    k = 2.0 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def compute_bollinger(closes: list[float],
                      period: int = BB_PERIOD,
                      n_std: float = BB_STD) -> tuple[float, float, float] | None:
    """(upper, mid, lower) ya da None."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    std = math.sqrt(sum((x - mid) ** 2 for x in window) / period)
    return mid + n_std * std, mid, mid - n_std * std


def compute_volume_spike(volumes: list[float],
                         lookback: int = VOL_LOOKBACK) -> float:
    """Son hacim / son N ortalama hacim oranı."""
    if len(volumes) < lookback + 1:
        return 1.0
    avg = sum(volumes[-lookback - 1:-1]) / lookback
    if avg <= 0:
        return 1.0
    return volumes[-1] / avg


def compute_wilder_atr(candles: list[dict], period: int = 14) -> float | None:
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
    if not USE_ATR_EXITS or mark_px <= 0:
        return TAKE_PROFIT_PCT, STOP_LOSS_PCT
    raw = fetch_candles(client, coin, n=max(ATR_PERIOD + 22, 40))
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
#  Strateji sinyalleri
# ═══════════════════════════════════════════════════════════════════════════════

def signal_funding(funding: float) -> SignalResult:
    """S1: Funding Rate Extreme → zıt yön."""
    if funding > FUNDING_EXTREME:
        score = -W_FUNDING * min(1.0, funding / (FUNDING_EXTREME * 3))
        return SignalResult("FUNDING", score, funding,
                            f"fund={funding*100:+.4f}% → SHORT")
    if funding < -FUNDING_EXTREME:
        score = W_FUNDING * min(1.0, abs(funding) / (FUNDING_EXTREME * 3))
        return SignalResult("FUNDING", score, funding,
                            f"fund={funding*100:+.4f}% → LONG")
    return SignalResult("FUNDING", 0.0, funding, "nötr")


def signal_rsi(closes: list[float]) -> SignalResult:
    """S2: RSI Extreme."""
    rsi = compute_rsi(closes)
    if rsi is None:
        return SignalResult("RSI", 0.0, 0.0, "veri yetersiz")
    if rsi < RSI_OVERSOLD:
        score = W_RSI * (1.0 - rsi / RSI_OVERSOLD)
        return SignalResult("RSI", score, rsi, f"RSI={rsi:.1f} oversold → LONG")
    if rsi > RSI_OVERBOUGHT:
        score = -W_RSI * ((rsi - RSI_OVERBOUGHT) / (100 - RSI_OVERBOUGHT))
        return SignalResult("RSI", score, rsi, f"RSI={rsi:.1f} overbought → SHORT")
    return SignalResult("RSI", 0.0, rsi, f"RSI={rsi:.1f} nötr")


def signal_ema_cross(closes: list[float]) -> SignalResult:
    """S3: EMA9 × EMA21 Crossover."""
    if len(closes) < EMA_SLOW + 2:
        return SignalResult("EMA", 0.0, 0.0, "veri yetersiz")
    fast = compute_ema(closes, EMA_FAST)
    slow = compute_ema(closes, EMA_SLOW)
    if not fast or not slow:
        return SignalResult("EMA", 0.0, 0.0, "hesap hatası")

    # Son iki noktadaki crossover
    f_prev, f_last = fast[-2], fast[-1]
    s_prev, s_last = slow[-2], slow[-1]
    gap_pct = abs(f_last - s_last) / max(s_last, 1e-9) * 100

    if f_prev <= s_prev and f_last > s_last:
        return SignalResult("EMA", W_EMA, gap_pct,
                            f"EMA{EMA_FAST}×{EMA_SLOW} golden cross → LONG")
    if f_prev >= s_prev and f_last < s_last:
        return SignalResult("EMA", -W_EMA, gap_pct,
                            f"EMA{EMA_FAST}×{EMA_SLOW} death cross → SHORT")
    # Trend yönü (cross olmasa da trend puanı)
    if f_last > s_last:
        return SignalResult("EMA", W_EMA * 0.5, gap_pct,
                            f"EMA trend UP (+{gap_pct:.2f}%)")
    return SignalResult("EMA", -W_EMA * 0.5, gap_pct,
                        f"EMA trend DOWN (-{gap_pct:.2f}%)")


def signal_bollinger(closes: list[float], mark_px: float) -> SignalResult:
    """S4: Bollinger Band Extreme → geri dönüş."""
    bb = compute_bollinger(closes)
    if bb is None:
        return SignalResult("BB", 0.0, 0.0, "veri yetersiz")
    upper, mid, lower = bb
    band_width = upper - lower
    if band_width <= 0:
        return SignalResult("BB", 0.0, 0.0, "sıkışma")

    if mark_px > upper:
        pct_out = (mark_px - upper) / band_width
        return SignalResult("BB", -W_BB * min(1.0, pct_out * 3),
                            mark_px / upper,
                            f"fiyat BB üstünde ({pct_out*100:.1f}%) → SHORT")
    if mark_px < lower:
        pct_out = (lower - mark_px) / band_width
        return SignalResult("BB", W_BB * min(1.0, pct_out * 3),
                            mark_px / lower,
                            f"fiyat BB altında ({pct_out*100:.1f}%) → LONG")
    # BB içi → orta bant yönü
    pos = (mark_px - mid) / (band_width / 2)  # -1..+1
    return SignalResult("BB", 0.0, pos, f"BB içi pos={pos:+.2f}")


def signal_volume(closes: list[float], volumes: list[float]) -> SignalResult:
    """S5: Volume Spike + Fiyat Yönü."""
    ratio = compute_volume_spike(volumes)
    if ratio < VOL_SPIKE_MULT:
        return SignalResult("VOL", 0.0, ratio, f"vol ratio={ratio:.2f} normal")
    # Spike var: fiyat yönüne bak
    if len(closes) < 3:
        return SignalResult("VOL", 0.0, ratio, "veri yetersiz")
    delta = closes[-1] - closes[-2]
    direction = 1 if delta > 0 else -1
    intensity = min(1.0, (ratio - VOL_SPIKE_MULT) / VOL_SPIKE_MULT)
    score = direction * W_VOL * intensity
    side_str = "LONG" if direction > 0 else "SHORT"
    return SignalResult("VOL", score, ratio,
                        f"vol spike ×{ratio:.1f} fiyat {'▲' if direction>0 else '▼'} → {side_str}")


# ── Whale / kopya cache ────────────────────────────────────────────────────────
_whale_cache: dict = {"wallets": [], "ts": 0.0}
_WHALE_TTL = 3600
_burst_cache: dict[str, tuple[bool, float]] = {}
_BURST_CACHE_TTL = 7200.0


def _fill_burst_is_bot(client: httpx.Client, addr_lower: str) -> bool:
    """Kısa pencerede aşırı fill → HFT/bot. TTL cache."""
    t = time.time()
    hit = _burst_cache.get(addr_lower)
    if hit and t - hit[1] < _BURST_CACHE_TTL:
        return hit[0]
    st = int(time.time() * 1000) - COPY_BURST_WINDOW_MS
    fills = _hl_post(client, {
        "type": "userFillsByTime", "user": addr_lower, "startTime": st,
    }, timeout=6.0)
    is_bot = isinstance(fills, list) and len(fills) > COPY_BURST_FILLS
    _burst_cache[addr_lower] = (is_bot, t)
    return is_bot


def _parse_window_perf(row: dict) -> dict[str, dict]:
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


def _is_bot_heuristic(perf: dict[str, dict], _acct_val: float) -> bool:
    at  = perf.get("allTime", {})
    pnl = at.get("pnl", 0)
    vlm = at.get("vlm", 0)
    roi = at.get("roi", 0)
    if pnl > 0 and vlm > 0 and (vlm / pnl) > 8000:
        return True
    if vlm > 1e11 and roi < 0.05:
        return True
    return False


def get_top_wallets(client: httpx.Client) -> list[tuple[str, float]]:
    """(adres, ağırlık). Onaylı insanlar + burst/ROI filtreli leaderboard."""
    now = time.time()
    if now - _whale_cache["ts"] < _WHALE_TTL and _whale_cache["wallets"]:
        return _whale_cache["wallets"]

    result: list[tuple[str, float]] = []
    for addr in COPY_BOT_ADDRS:
        result.append((addr, 2.5))

    data = _hl_get(client, "leaderboard", timeout=20.0)
    rows: list[dict] = []
    if isinstance(data, dict):
        rows = data.get("leaderboardRows") or []
    elif isinstance(data, list):
        rows = data

    existing = {a for a, _ in result}
    bot_filtered: list[tuple[str, float, float, float]] = []

    for r in rows[:180]:
        addr = r.get("ethAddress") or ""
        if not addr.startswith("0x") or addr.lower() in existing:
            continue
        perf   = _parse_window_perf(r)
        acct   = float(r.get("accountValue", 0))
        at     = perf.get("allTime", {})
        mo     = perf.get("month", {})
        wk     = perf.get("week", {})
        pnl    = at.get("pnl", 0)
        roi    = at.get("roi", 0)
        mo_roi = mo.get("roi", 0)
        wk_roi = wk.get("roi", 0.0)

        if pnl < 50_000 or roi < 0.10 or acct < 1_000:
            continue
        if mo_roi < COPY_MIN_MONTH_ROI:
            continue
        if COPY_MIN_WEEK_ROI > 0 and wk_roi < COPY_MIN_WEEK_ROI:
            continue
        if _is_bot_heuristic(perf, acct):
            continue

        bot_filtered.append((addr.lower(), pnl, mo_roi, wk_roi))

    bot_filtered.sort(key=lambda x: x[2] * 0.65 + x[3] * 0.35, reverse=True)

    vetted: list[tuple[str, float, float, float]] = []
    for tup in bot_filtered[:55]:
        addr = tup[0]
        if _fill_burst_is_bot(client, addr):
            continue
        vetted.append(tup)
        if len(vetted) >= WHALE_TOP_N + 8:
            break

    for addr, _pnl, mo_roi, wk_roi in vetted[:WHALE_TOP_N]:
        if addr in existing:
            continue
        score_roi = mo_roi * 0.7 + wk_roi * 0.3
        weight = 1.0 + min(score_roi * 2.2, 1.35)
        result.append((addr, round(weight, 3)))

    _whale_cache.update({"wallets": result, "ts": now})
    print(f"  [whale] {len(COPY_BOT_ADDRS)} onaylı + {len(vetted)} burst-filtreli "
          f"(LB {len(rows)} satır)")
    return result


def signal_whale(client: httpx.Client, coin: str) -> SignalResult:
    """S6: Ağırlıklı top trader yönü (COPY_LOOKBACK_MS taze fill)."""
    wallets = get_top_wallets(client)
    if not wallets:
        return SignalResult("WHALE", 0.0, 0, "leaderboard boş")

    cutoff = int(time.time() * 1000) - COPY_LOOKBACK_MS
    long_w = short_w = 0.0
    long_n = short_n = 0
    checked = 0

    for addr, weight in wallets[:22]:
        try:
            fills = _hl_post(client, {
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
        except Exception:
            continue
        time.sleep(0.04)

    total = long_w + short_w
    if total < 0.5:
        return SignalResult("WHALE", 0.0, 0, f"({checked} cüzdan) taze işlem yok")

    bias = (long_w - short_w) / total
    agree_n = long_n if bias > 0 else short_n
    intensity = min(1.0, abs(bias) * (1.0 + 0.14 * min(agree_n, 4)))
    score = bias * W_WHALE * intensity
    return SignalResult(
        "WHALE", round(score, 4), float(long_n + short_n),
        f"{len(wallets)} czd L:{long_w:.1f}({long_n})/S:{short_w:.1f}({short_n}) "
        f"bias={bias:+.2f} t≤{COPY_LOOKBACK_MS // 60000}dk",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Strateji motoru
# ═══════════════════════════════════════════════════════════════════════════════

def signal_fear_greed(fg_value: int) -> SignalResult:
    """S7: Fear & Greed Index (Alternative.me) — zıt yön ticareti."""
    if fg_value <= 20:
        return SignalResult("FEAR_GREED", W_FEAR, fg_value, f"FG={fg_value} ekstrem korku→LONG")
    if fg_value <= FG_EXTREME_FEAR:
        intensity = 0.5 + 0.5 * (FG_EXTREME_FEAR - fg_value) / max(FG_EXTREME_FEAR - 20, 1)
        return SignalResult("FEAR_GREED", round(W_FEAR * intensity, 3), fg_value,
                            f"FG={fg_value} korku→LONG ({intensity:.2f}×)")
    if fg_value <= 45:
        intensity = 0.25 * (45 - fg_value) / 10
        return SignalResult("FEAR_GREED", round(W_FEAR * intensity, 3), fg_value,
                            f"FG={fg_value} hafif korku")
    if fg_value >= 80:
        return SignalResult("FEAR_GREED", -W_FEAR, fg_value, f"FG={fg_value} ekstrem açgözlülük→SHORT")
    if fg_value >= FG_EXTREME_GREED:
        intensity = 0.5 + 0.5 * (fg_value - FG_EXTREME_GREED) / max(80 - FG_EXTREME_GREED, 1)
        return SignalResult("FEAR_GREED", round(-W_FEAR * intensity, 3), fg_value,
                            f"FG={fg_value} açgözlülük→SHORT ({intensity:.2f}×)")
    if fg_value >= 55:
        intensity = 0.25 * (fg_value - 55) / 15
        return SignalResult("FEAR_GREED", round(-W_FEAR * intensity, 3), fg_value,
                            f"FG={fg_value} hafif açgözlülük")
    return SignalResult("FEAR_GREED", 0.0, fg_value, f"FG={fg_value} nötr")


def analyze_coin(client: httpx.Client,
                 coin: str, mark_px: float,
                 funding: float, oi_usd: float,
                 run_whale: bool = True,
                 fear_greed: int = 50) -> CoinSignal:
    """Bir coin için tüm 7 stratejiyi çalıştırır (F&G dahil)."""
    cs = CoinSignal(coin=coin, mark_px=mark_px,
                    funding=funding, oi_usd=oi_usd)

    # Hızlı ön filtre
    if oi_usd < MIN_OI_USD:
        return cs

    # Mum verisini bir kez çek
    candles = fetch_candles(client, coin, n=max(LOOKBACK_CANDLES, BB_PERIOD + 5))
    if len(candles) < RSI_PERIOD + 2:
        return cs

    closes  = [float(c["c"]) for c in candles if "c" in c]
    volumes = [float(c["v"]) for c in candles if "v" in c]
    if len(closes) < RSI_PERIOD + 2:
        return cs

    # S1 Funding
    cs.signals.append(signal_funding(funding))
    # S2 RSI
    cs.signals.append(signal_rsi(closes))
    # S3 EMA Cross
    cs.signals.append(signal_ema_cross(closes))
    # S4 Bollinger
    cs.signals.append(signal_bollinger(closes, mark_px))
    # S5 Volume
    cs.signals.append(signal_volume(closes, volumes))
    # S6 Whale (isteğe bağlı — yavaş)
    if run_whale:
        cs.signals.append(signal_whale(client, coin))
    # S7 Fear & Greed
    cs.signals.append(signal_fear_greed(fear_greed))

    cs.compute()
    return cs


# ═══════════════════════════════════════════════════════════════════════════════
#  Hızlı Backtest
# ═══════════════════════════════════════════════════════════════════════════════

def quick_backtest(client: httpx.Client,
                   coin: str,
                   days: int = BACKTEST_DAYS,
                   tp_pct: float = 0.05,
                   sl_pct: float = 0.05) -> dict:
    """
    Son N günün 1h mumları üzerinde sinyal-bazlı backtest.
    TP/SL: giriş fiyatının %tp_pct / %sl_pct'i.
    Döner: {wins, losses, win_rate, avg_pnl, trades}
    """
    n = days * 24 + LOOKBACK_CANDLES + 5
    candles = fetch_candles(client, coin, n=n, interval="1h")
    if len(candles) < LOOKBACK_CANDLES + 10:
        return {"wins": 0, "losses": 0, "win_rate": 0.5, "avg_pnl": 0.0, "trades": 0}

    wins = losses = 0
    pnls: list[float] = []

    for i in range(LOOKBACK_CANDLES, len(candles) - 1):
        window = candles[i - LOOKBACK_CANDLES: i]
        closes  = [float(c["c"]) for c in window if "c" in c]
        volumes = [float(c["v"]) for c in window if "v" in c]
        if len(closes) < RSI_PERIOD + 2:
            continue

        funding = 0.0  # backtest'te funding verisi yok, sıfır kullan
        mark    = float(candles[i]["o"])  # sonraki mumun açılışına giriş

        sigs = [
            signal_funding(funding),
            signal_rsi(closes),
            signal_ema_cross(closes),
            signal_bollinger(closes, float(window[-1]["c"])),
            signal_volume(closes, volumes),
        ]
        total = sum(s.score for s in sigs)
        bt_min = MIN_SCORE * 0.65   # backtest'te funding=0 olduğu için düşürülmüş
        if abs(total) < bt_min:
            continue

        side = "LONG" if total > 0 else "SHORT"
        tp = mark * (1 + tp_pct) if side == "LONG" else mark * (1 - tp_pct)
        sl = mark * (1 - sl_pct) if side == "LONG" else mark * (1 + sl_pct)

        # Kalan mumları tarif
        for j in range(i + 1, min(i + 25, len(candles))):
            hi = float(candles[j]["h"])
            lo = float(candles[j]["l"])
            if side == "LONG":
                if lo <= sl:
                    losses += 1; pnls.append(-sl_pct); break
                if hi >= tp:
                    wins += 1; pnls.append(tp_pct); break
            else:
                if hi >= sl:
                    losses += 1; pnls.append(-sl_pct); break
                if lo <= tp:
                    wins += 1; pnls.append(tp_pct); break
        else:
            # Süre doldu → mark-to-market
            last = float(candles[min(i + 24, len(candles) - 1)]["c"])
            pnl = (last - mark) / mark if side == "LONG" else (mark - last) / mark
            if pnl > 0:
                wins += 1
            else:
                losses += 1
            pnls.append(pnl)

    total_trades = wins + losses
    return {
        "wins":     wins,
        "losses":   losses,
        "win_rate": wins / total_trades if total_trades else 0.5,
        "avg_pnl":  sum(pnls) / len(pnls) if pnls else 0.0,
        "trades":   total_trades,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Bakiye takibi
# ═══════════════════════════════════════════════════════════════════════════════

def get_realized_pnl(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd),0) t FROM futures_positions WHERE closed_at IS NOT NULL"
    ).fetchone()
    return float(row["t"])


def get_open_stake(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(stake_usd),0) t FROM futures_positions WHERE closed_at IS NULL"
    ).fetchone()
    return float(row["t"])


def get_unrealized_pnl(conn: sqlite3.Connection,
                        all_mids: dict[str, float]) -> float:
    rows = conn.execute(
        "SELECT coin, side, entry_price, contracts, funding_paid, last_price "
        "FROM futures_positions WHERE closed_at IS NULL"
    ).fetchall()
    total = 0.0
    for r in rows:
        cur = all_mids.get(r["coin"]) or r["last_price"] or r["entry_price"]
        if not cur:
            continue
        price_pnl = (r["contracts"] * (float(cur) - r["entry_price"])
                     if r["side"] == "LONG"
                     else r["contracts"] * (r["entry_price"] - float(cur)))
        total += price_pnl + (r["funding_paid"] or 0.0)
    return total


def get_equity(conn: sqlite3.Connection,
               all_mids: Optional[dict[str, float]] = None) -> float:
    return STARTING_BALANCE + get_realized_pnl(conn) + get_unrealized_pnl(conn, all_mids or {})


def get_available_balance(conn: sqlite3.Connection,
                           all_mids: Optional[dict[str, float]] = None) -> float:
    return max(0.0, get_equity(conn, all_mids) - get_open_stake(conn))


def kelly_stake(confidence: float,
                available: Optional[float] = None) -> float:
    """Kelly × güven × bakiye — dinamik pozisyon büyüklüğü (margin)."""
    base  = available if available is not None else STARTING_BALANCE
    stake = base * KELLY_FRACTION * confidence
    return round(min(stake, MAX_POS_USD), 4)


def calc_leverage(confidence: float) -> int:
    """
    Sinyal gücüne göre kaldıraç belirle.
    confidence=0 → LEVERAGE_MIN (2x)
    confidence=1 → LEVERAGE_MAX (20x)

    Kademeli tablo:
      < 0.15  → 2x   (sadece eşiği geçti)
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

def open_position(conn: sqlite3.Connection, client: httpx.Client, cs: CoinSignal,
                  available: float) -> int:
    stake    = kelly_stake(cs.confidence, available=available)
    stake    = round(min(stake, available, MAX_POS_USD), 4)
    if stake < 0.5:
        return -1

    leverage    = calc_leverage(cs.confidence)
    notional    = stake * leverage                    # gerçek piyasa değeri
    contracts   = notional / cs.mark_px              # kontrat sayısı
    tp_frac, sl_frac = dynamic_tp_sl_fracs(client, cs.coin, cs.mark_px)
    strat_names = ",".join(
        s.strategy for s in cs.signals if abs(s.score) > 0.1)
    rsi_val     = next(
        (s.value for s in cs.signals if s.strategy == "RSI"), None)
    whale_val   = next(
        (int(s.value) for s in cs.signals if s.strategy == "WHALE"), 0)
    now         = datetime.now(timezone.utc).isoformat()

    try:
        cur = conn.execute("""
        INSERT INTO futures_positions
          (coin, side, entry_price, stake_usd, contracts,
           score, strategies, funding_rate, rsi, whale_confirms,
           opened_at, funding_paid, last_price, last_update, leverage,
           tp_frac, sl_frac, be_armed)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,0.0,?,?,?,?,?,0)
    """, (cs.coin, cs.side, cs.mark_px, stake, round(contracts, 8),
          round(cs.total_score, 4), strat_names,
          round(cs.funding, 8),
          round(rsi_val, 2) if rsi_val else None,
          whale_val, now,
          round(cs.mark_px, 6), now, leverage,
          tp_frac, sl_frac))
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        return -2


def close_position(conn: sqlite3.Connection, pos_id: int,
                   close_price: float, reason: str) -> float:
    row = conn.execute(
        "SELECT side, entry_price, stake_usd, contracts, funding_paid, strategies "
        "FROM futures_positions WHERE id=?", (pos_id,)
    ).fetchone()
    if not row:
        return 0.0

    price_pnl = (row["contracts"] * (close_price - row["entry_price"])
                 if row["side"] == "LONG"
                 else row["contracts"] * (row["entry_price"] - close_price))
    pnl = price_pnl + (row["funding_paid"] or 0.0)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        UPDATE futures_positions
        SET closed_at=?, close_price=?, pnl_usd=?, close_reason=?, last_price=?
        WHERE id=?
    """, (now, round(close_price, 6), round(pnl, 4), reason,
          round(close_price, 6), pos_id))
    conn.commit()

    if reason not in ("DEDUP", "ADMIN"):
        won = pnl > 0
        for strat in (row["strategies"] or "").split(","):
            strat = strat.strip()
            if not strat:
                continue
            conn.execute("""
                INSERT INTO strategy_stats(strategy, wins, losses, total_pnl, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(strategy) DO UPDATE SET
                  wins      = wins + excluded.wins,
                  losses    = losses + excluded.losses,
                  total_pnl = total_pnl + excluded.total_pnl,
                  updated_at= excluded.updated_at
            """, (strat, 1 if won else 0, 0 if won else 1, round(pnl, 4), now))
        conn.commit()
    return pnl


def apply_funding_costs(conn: sqlite3.Connection,
                         funding_map: dict[str, float],
                         all_mids: dict[str, float]) -> None:
    rows = conn.execute(
        "SELECT id, coin, side, contracts, opened_at, last_update "
        "FROM futures_positions WHERE closed_at IS NULL"
    ).fetchall()
    now_ts  = time.time()
    now_iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
    for r in rows:
        coin = r["coin"]
        if coin not in funding_map:
            continue
        last = r["last_update"] or r["opened_at"]
        try:
            last_dt   = datetime.fromisoformat(
                str(last).replace("Z", "+00:00"))
            elapsed_h = (now_ts - last_dt.timestamp()) / 3600.0
        except Exception:
            elapsed_h = 0.0
        if elapsed_h < 0.05:
            continue
        mark     = all_mids.get(coin, 0.0)
        notional = r["contracts"] * mark
        accrued  = notional * funding_map[coin] * (elapsed_h / 8.0)
        if r["side"] == "SHORT":
            accrued = -accrued
        conn.execute("""
            UPDATE futures_positions
            SET funding_paid = COALESCE(funding_paid,0) - ?,
                last_price   = ?,
                last_update  = ?
            WHERE id=?
        """, (round(accrued, 6),
              round(mark, 6) if mark else None,
              now_iso, r["id"]))
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Pozisyon kontrol döngüsü
# ═══════════════════════════════════════════════════════════════════════════════

def open_position_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) n FROM futures_positions WHERE closed_at IS NULL"
    ).fetchone()["n"]


def already_positioned(conn: sqlite3.Connection, coin: str) -> bool:
    return bool(conn.execute(
        "SELECT id FROM futures_positions WHERE coin=? AND closed_at IS NULL",
        (coin,)
    ).fetchone())


def is_on_cooldown(conn: sqlite3.Connection, coin: str, side: str) -> bool:
    cutoff = datetime.fromtimestamp(
        time.time() - SL_COOLDOWN_MIN * 60, tz=timezone.utc).isoformat()
    return bool(conn.execute("""
        SELECT id FROM futures_positions
        WHERE coin=? AND side=? AND closed_at > ? AND pnl_usd < 0
        ORDER BY closed_at DESC LIMIT 1
    """, (coin, side, cutoff)).fetchone())


def check_and_close(conn: sqlite3.Connection,
                    client: httpx.Client) -> tuple[int, dict[str, float], str]:
    hl_err = ""
    try:
        all_mids = fetch_all_mids(client)
    except Exception as exc:
        all_mids = {}
        hl_err = f"allMids istisna: {exc}"
    if not all_mids and not hl_err:
        hl_err = "allMids boş"

    # Funding maliyetleri uygula
    if all_mids:
        meta, ctxs = fetch_meta_ctxs(client)
        funding_map: dict[str, float] = {}
        for u, ctx in zip(meta, ctxs):
            coin = u.get("name", "")
            try:
                funding_map[coin] = float(ctx.get("funding") or 0)
            except Exception:
                pass
        apply_funding_costs(conn, funding_map, all_mids)

    rows = conn.execute(
        "SELECT id, coin, side, entry_price, stake_usd, contracts, "
        "opened_at, funding_paid, last_price, leverage, tp_frac, sl_frac, be_armed "
        "FROM futures_positions WHERE closed_at IS NULL"
    ).fetchall()
    closed_n = 0

    for pos in rows:
        coin     = pos["coin"]
        side     = pos["side"]
        entry    = pos["entry_price"]
        stake    = pos["stake_usd"]
        contr    = pos["contracts"]
        pid      = pos["id"]
        fund     = pos["funding_paid"] or 0.0
        leverage = pos["leverage"] or 1
        tpf = float(pos["tp_frac"] or TAKE_PROFIT_PCT)
        slf = float(pos["sl_frac"] or STOP_LOSS_PCT)
        be_armed = int(pos["be_armed"] or 0)

        cur = float(all_mids.get(coin) or pos["last_price"] or entry or 0.0)
        if not cur:
            continue

        used_stale = coin not in all_mids
        stale_tag = "[son fiyat] " if used_stale else ""

        price_pnl  = (contr * (cur - entry) if side == "LONG"
                      else contr * (entry - cur))
        unrealized = price_pnl + fund
        pct_move   = (cur - entry) / entry if side == "LONG" else (entry - cur) / entry
        pct_stake  = pct_move * leverage   # kaldıraçlı stake yüzdesi

        if pct_move >= tpf:
            pnl = close_position(conn, pid, cur, "TP")
            print(f"  💰 TP  [{pid}] {coin:<6} {side} {leverage}x  {stale_tag}"
                  f"fiyat:+{pct_move*100:.2f}%  stake:{pct_stake*100:+.1f}%  PnL=${pnl:+.4f}")
            closed_n += 1
            continue

        if pct_move <= -slf:
            pnl = close_position(conn, pid, cur, "SL")
            print(f"  ⛔ SL  [{pid}] {coin:<6} {side} {leverage}x  {stale_tag}"
                  f"fiyat:{pct_move*100:.2f}%  stake:{pct_stake*100:+.1f}%  PnL=${pnl:+.4f}")
            closed_n += 1
            continue

        if USE_BREAK_EVEN and be_armed:
            if side == "LONG" and cur <= entry * (1.0 - BE_GIVEBACK_FRAC):
                pnl = close_position(conn, pid, cur, "BE")
                print(f"  ⚖ BE  [{pid}] {coin:<6} LONG  {stale_tag}giveback  PnL=${pnl:+.4f}")
                closed_n += 1
                continue
            if side == "SHORT" and cur >= entry * (1.0 + BE_GIVEBACK_FRAC):
                pnl = close_position(conn, pid, cur, "BE")
                print(f"  ⚖ BE  [{pid}] {coin:<6} SHORT {stale_tag}giveback  PnL=${pnl:+.4f}")
                closed_n += 1
                continue

        if USE_BREAK_EVEN and not be_armed and pct_move >= tpf * BE_ARM_FRAC:
            conn.execute("UPDATE futures_positions SET be_armed=1 WHERE id=?", (pid,))
            conn.commit()
            print(f"  🔒 BE-arm [{pid}] {coin:<6} {side}  kâr %{pct_move*100:.2f}")

        try:
            odt   = datetime.fromisoformat(
                str(pos["opened_at"]).replace("Z", "+00:00"))
            age_h = (time.time() - odt.timestamp()) / 3600.0
        except Exception:
            age_h = 0.0

        if age_h >= MAX_HOLD_HOURS:
            pnl = close_position(conn, pid, cur, "TIMEOUT")
            print(f"  ⏱ EXP [{pid}] {coin:<6} {side}  {stale_tag}"
                  f"{age_h:.1f}h  PnL=${pnl:+.4f}")
            closed_n += 1
            continue

        ind      = "▲" if unrealized > 0 else "▼"
        mv       = (cur - entry) / entry * 100
        lev_pnl  = mv * leverage     # kaldıraçlı getiri %
        print(f"  {ind} [{pid:>2}] {coin:<6} {side:<5} {leverage}x  {stale_tag}"
              f"giriş={entry:.4f}→{cur:.4f} ({mv:+.2f}%)  "
              f"stake:{lev_pnl:+.1f}% (${unrealized:+.4f})  "
              f"kalan={MAX_HOLD_HOURS-age_h:.1f}h")

    return closed_n, all_mids, hl_err


# ═══════════════════════════════════════════════════════════════════════════════
#  Market tarama
# ═══════════════════════════════════════════════════════════════════════════════

def scan_markets(conn: sqlite3.Connection, client: httpx.Client,
                 all_mids: dict[str, float],
                 backtest_scores: dict[str, float]) -> int:
    if open_position_count(conn) >= MAX_OPEN_POS:
        print(f"  [scan] Pozisyon limiti dolu ({MAX_OPEN_POS})")
        return 0

    available = get_available_balance(conn, all_mids)
    if available < 0.5:
        print(f"  [scan] Yetersiz bakiye: ${available:.2f}")
        return 0

    # Tüm asset context
    meta, ctxs = fetch_meta_ctxs(client)
    ctx_map: dict[str, dict] = {}
    for u, ctx in zip(meta, ctxs):
        if not u.get("isDelisted"):
            ctx_map[u["name"]] = ctx

    candidates = [
        (c, px, oi, f) for c, px, oi, f in scan_candidate_rows(meta, ctxs, ctx_map, all_mids)
        if not already_positioned(conn, c)
    ]
    wl_tag = "DYN" if ENGINE_DYNAMIC_WATCHLIST else "FIX"

    fg_now = fetch_fear_greed()
    print(f"  [scan] evren={wl_tag} Fear&Greed={fg_now}  {len(candidates)} aday…")

    opened = 0
    for coin, px, oi_usd, funding in candidates:
        if open_position_count(conn) >= MAX_OPEN_POS:
            break

        available = get_available_balance(conn, all_mids)
        if available < 0.5:
            break

        # Ön filtre: F&G aktifse (korku/açgözlülük bölgesi) hepsi geçer
        if not (fg_now <= 45 or fg_now >= 55):
            rsi_q = compute_rsi(
                [float(c["c"]) for c in fetch_candles(client, coin, 20)] or [50.0])
            if (abs(funding) < FUNDING_EXTREME * 0.3 and
                    rsi_q is not None and
                    RSI_OVERSOLD + 10 < rsi_q < RSI_OVERBOUGHT - 10):
                continue

        # Tam analiz (F&G dahil)
        run_whale = len(candidates) <= 8
        cs = analyze_coin(client, coin, px, funding, oi_usd,
                          run_whale=run_whale, fear_greed=fg_now)
        time.sleep(0.08)

        # Debug: skor görünümü
        if abs(cs.total_score) > 0.3:
            sig_str = " ".join(
                f"{s.strategy}:{s.score:+.2f}" for s in cs.signals if abs(s.score) > 0.05)
            print(f"  · {coin:<6} skor={cs.total_score:+.3f} "
                  f"(min={MIN_SCORE}) side={cs.side or '—'}  {sig_str}")

        if not cs.side:
            continue
        if is_on_cooldown(conn, coin, cs.side):
            continue

        # Backtest win-rate tabanı (ENGINE_BT_MIN_WR)
        bt_wr = backtest_scores.get(coin, 0.5)
        if bt_wr < ENGINE_BT_MIN_WR:
            print(f"  ⚠ [{coin}] backtest WR={bt_wr:.1%} < {ENGINE_BT_MIN_WR:.0%}, atlandı")
            continue

        pid = open_position(conn, client, cs, available)
        if pid == -2:
            print(f"  ⊗ [{coin}] aynı coinde zaten açık (UNIQUE / yarış)")
            continue
        if pid > 0:
            active = [s for s in cs.signals if abs(s.score) > 0.1]
            strats = " | ".join(f"{s.strategy}:{s.score:+.1f}" for s in active)
            new_av = get_available_balance(conn, all_mids)
            row = conn.execute(
                "SELECT stake_usd, leverage FROM futures_positions WHERE id=?", (pid,)
            ).fetchone()
            stake_used = row["stake_usd"]
            lev        = row["leverage"] or 1
            notional   = stake_used * lev
            print(f"  ➕ [{pid}] {cs.side:<5} {coin:<6} @{px:.4f}  "
                  f"score={cs.total_score:+.2f}  {lev}x  "
                  f"margin=${stake_used:.2f}  notional=${notional:.2f}  "
                  f"bt_wr={bt_wr:.0%}  bakiye=${new_av:.2f}")
            print(f"       └─ {strats}")
            opened += 1

    return opened


# ═══════════════════════════════════════════════════════════════════════════════
#  Başlangıç backtest
# ═══════════════════════════════════════════════════════════════════════════════

def run_startup_backtest(client: httpx.Client) -> dict[str, float]:
    """
    Watchlist'teki tüm coinler için hızlı 7 günlük backtest.
    Döner: {coin: win_rate}
    """
    print(f"\n  [backtest] {BACKTEST_DAYS} günlük geçmiş test ediliyor…")
    scores: dict[str, float] = {}
    priority = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "AVAX", "LINK"]
    coins = priority + [c for c in WATCHLIST if c not in priority]

    for coin in coins[:15]:  # ilk 15 coin
        try:
            bt = quick_backtest(client, coin, days=BACKTEST_DAYS)
            scores[coin] = bt["win_rate"]
            star = "★" if bt["win_rate"] >= 0.55 else (" " if bt["win_rate"] >= 0.45 else "✗")
            print(f"    {star} {coin:<6} "
                  f"trades={bt['trades']:>3}  "
                  f"win={bt['wins']:>2}/{bt['losses']:>2}  "
                  f"WR={bt['win_rate']:.0%}  "
                  f"avgPnL={bt['avg_pnl']*100:+.2f}%")
        except Exception as e:
            scores[coin] = 0.5
            print(f"    ? {coin:<6} hata: {e}")
        time.sleep(0.1)

    passing = sum(1 for v in scores.values() if v >= 0.5)
    print(f"  [backtest] Tamamlandı. "
          f"{passing}/{len(scores)} coin ≥%50 win rate\n")
    return scores


# ═══════════════════════════════════════════════════════════════════════════════
#  Ana döngü
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    try:
        from scanner_runtime import singleton_process_lock, write_heartbeat_atomic
    except ImportError:
        import contextlib

        def singleton_process_lock(_path: Path):  # type: ignore[misc]
            return contextlib.nullcontext()

        def write_heartbeat_atomic(_path: Path, _data: dict) -> None:  # type: ignore[misc]
            pass

    try:
        with singleton_process_lock(FUTURES_LOCK):
            _run_futures_scanner_main(write_heartbeat_atomic)
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)


def _run_futures_scanner_main(write_heartbeat_atomic) -> None:
    conn = init_db(DB_PATH)
    merged = dedupe_futures_open_same_coin(conn)
    if merged:
        print(f"  [startup] {merged} çift açık kayıt DEDUP ile kapatıldı.")
    _ensure_unique_futures_open_coin(conn)

    client = httpx.Client(
        timeout=20.0,
        headers={"User-Agent": "hl-futures-v2/0.1", "Accept": "application/json"},
    )

    stopped = False
    def _stop(*_):
        nonlocal stopped
        stopped = True
        print("\n[Ctrl+C] Scanner durduruluyor…")
    signal.signal(signal.SIGINT, _stop)

    print("=" * 72)
    print(" Hyperliquid Multi-Strategy Futures Scanner — Paper Demo $20")
    print(f" DB         : {DB_PATH}")
    print(f" Kilit      : {FUTURES_LOCK}")
    print(f" Heartbeat  : {FUTURES_HEARTBEAT}")
    print(f" Bakiye     : ${STARTING_BALANCE}  Kelly: {KELLY_FRACTION}  Max: ${MAX_POS_USD}/pos")
    print(f" TP / SL    : taban %{TAKE_PROFIT_PCT*100:.1f}/%{STOP_LOSS_PCT*100:.1f}  "
          f"ATR={'açık' if USE_ATR_EXITS else 'kapalı'}  BE={'açık' if USE_BREAK_EVEN else 'kapalı'}  "
          f"| Max süre: {MAX_HOLD_HOURS}h")
    print(f" Kaldıraç   : {LEVERAGE_MIN}x–{LEVERAGE_MAX}x  (sinyal gücüne göre otomatik)")
    print(f" Min Puan   : {MIN_SCORE}/{MAX_SCORE:.1f}  |  Tarama: {SCAN_INTERVAL}s  Kontrol: {POS_CHECK}s")
    print(f" Stratejiler: FUNDING({W_FUNDING}) RSI({W_RSI}) EMA({W_EMA}) "
          f"BB({W_BB}) VOL({W_VOL}) WHALE({W_WHALE}) FEAR_GREED({W_FEAR})")
    print(f" Watchlist  : {', '.join(WATCHLIST[:12])}…")
    print("=" * 72)

    # Başlangıç bakiyeleri
    equity = get_equity(conn)
    print(f" Mevcut equity: ${equity:.4f}  "
          f"Realize P&L: ${get_realized_pnl(conn):+.4f}  "
          f"Açık pos: {open_position_count(conn)}")

    # Backtest
    backtest_scores: dict[str, float] = {}
    try:
        backtest_scores = run_startup_backtest(client)
    except Exception as e:
        print(f"  [backtest] atlandı: {e}")
        backtest_scores = {c: 0.5 for c in WATCHLIST}

    pos_cycle = 0
    last_scan = 0.0

    while not stopped:
        loop_start = time.time()
        pos_cycle += 1
        now_str = datetime.now().strftime("%H:%M:%S")

        # ── A. Açık pozisyonları kontrol et ──────────────────────────────────
        print(f"\n[{now_str}] Kontrol #{pos_cycle}")
        closed_n, all_mids, hl_err = check_and_close(conn, client)
        if closed_n:
            print(f"  {closed_n} pozisyon kapatıldı.")
        if hl_err and pos_cycle % 4 == 1:
            print(f"  ⚠ HL: {hl_err}")

        # ── B. Market taraması ────────────────────────────────────────────────
        if loop_start - last_scan >= SCAN_INTERVAL:
            avail = get_available_balance(conn, all_mids)
            print(f"  [tarama] Coin analizi başlıyor… "
                  f"Kullanılabilir: ${avail:.2f}")
            opened = scan_markets(conn, client, all_mids, backtest_scores)
            last_scan = time.time()
        else:
            opened = 0

        # ── C. Özet ──────────────────────────────────────────────────────────
        realized   = get_realized_pnl(conn)
        unrealized = get_unrealized_pnl(conn, all_mids)
        equity     = STARTING_BALANCE + realized + unrealized
        open_stake = get_open_stake(conn)
        available  = max(0.0, equity - open_stake)
        open_n     = open_position_count(conn)
        closed_tot = conn.execute(
            "SELECT COUNT(*) n FROM futures_positions WHERE closed_at IS NOT NULL"
        ).fetchone()["n"]
        eq_pct = (equity - STARTING_BALANCE) / STARTING_BALANCE * 100

        scan_info = f"  Yeni: {opened}" if opened else ""
        print(f"  💼 Equity=${equity:.4f} ({eq_pct:+.2f}%)  "
              f"Kullanılabilir=${available:.2f}  Stake=${open_stake:.2f}  "
              f"↑${realized:+.4f} realize  ~${unrealized:+.4f} unrealize  "
              f"Açık:{open_n}  Kapalı:{closed_tot}{scan_info}")

        write_heartbeat_atomic(FUTURES_HEARTBEAT, {
            "engine": "crypto_futures_scanner",
            "db": str(DB_PATH),
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "loop": pos_cycle,
            "equity": round(equity, 4),
            "open_positions": open_n,
            "mids_count": len(all_mids),
            "mids_ok": bool(all_mids),
            "hl_last_error": hl_err,
            "seconds_since_full_scan": round(loop_start - last_scan, 1) if last_scan else -1.0,
        })

        # Strateji istatistikleri (her 10 döngüde bir)
        if pos_cycle % 10 == 0:
            stats = conn.execute(
                "SELECT strategy, wins, losses, total_pnl FROM strategy_stats"
            ).fetchall()
            if stats:
                print("  📊 Strateji performansı:")
                for s in stats:
                    n = s["wins"] + s["losses"]
                    wr = s["wins"] / n if n else 0
                    print(f"      {s['strategy']:<10} "
                          f"W/L={s['wins']}/{s['losses']}  "
                          f"WR={wr:.0%}  PnL=${s['total_pnl']:+.4f}")

        if stopped:
            break

        sleep_end = loop_start + POS_CHECK
        while not stopped and time.time() < sleep_end:
            time.sleep(0.1)

    conn.close()
    client.close()
    print("Scanner kapandı.")


if __name__ == "__main__":
    main()
