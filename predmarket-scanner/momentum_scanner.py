"""Calibration-based momentum paper scanner.

Strateji (2.3M data point'ten çıkarılan edge):
  Bucket   YES fiyatı  Gerçek YES oranı  Bias     Sinyal
  ─────────────────────────────────────────────────────
  0.4–0.5  piyasa %45  gerçekte %18      −0.27    BUY NO  ★★★
  0.5–0.6  piyasa %53  gerçekte %85      +0.32    BUY YES ★★★
  0.6–0.7  piyasa %65  gerçekte %91      +0.26    BUY YES ★★
  0.7–0.8  piyasa %75  gerçekte %96      +0.21    BUY YES ★★
  0.8–0.9  piyasa %85  gerçekte %96      +0.11    BUY YES ★
  0.9–1.0  piyasa %97  gerçekte %99.5    +0.026   küçük edge

Momentum filtresi: son 12h fiyat eğimini hesaplar.
  BUY NO  → yalnızca YES fiyatı düşüyor/sabit ise (piyasa zaten güveni kaybetmiş)
  BUY YES → yalnızca YES fiyatı yükseliyor/sabit ise (piyasa momentum kazanmış)

Self-improvement (self_improver.py):
  Her döngü sonunda kapalı pozisyonlardan öğrenir:
  - Bayesian kalibrasyon güncellemesi (2.3M data prior olarak kullanılır)
  - MOMENTUM_VETO ve EDGE_THRESHOLD win-rate'e göre otomatik ayarlanır
  - Her 10 kapanışta özet rapor basılır

Loop: her SCAN_INTERVAL_SEC saniyede bir çalışır.
  1. Çözülmüş pozisyonları kapat + P&L kaydet
  2. Self-improvement döngüsünü çalıştır
  3. Aktif market'leri çek (volume > min_vol)
  4. Edge zone'daki her market için: CLOB geçmişi → momentum → pozisyon aç
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

import self_improver
import backtest_trainer
import hybrid_tp

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
_LIVE_ENV = ROOT / "live.scanner.env"
if (
    os.getenv("POLYMARKET_LIVE_TRADING", "0").strip().lower() in ("1", "true", "yes")
    and os.getenv("POLYMARKET_LIVE_CONFIRM", "").strip() == "I_UNDERSTAND_REAL_MONEY_LOSS"
    and _LIVE_ENV.is_file()
):
    load_dotenv(_LIVE_ENV, override=True)

POLYMARKET_LIVE_ARMED = False
SCANNER_LOCK = ROOT / "data" / "polymarket_scanner.lock"
PAPER_SCANNER_LOCK = ROOT / "data" / "polymarket_scanner_paper.lock"

try:
    from config import DATA_DIR, settings

    POLYMARKET_LIVE_ARMED = settings.polymarket_live_armed
    DB_PATH = settings.live_db if POLYMARKET_LIVE_ARMED else settings.paper_db
    EDGE_THRESHOLD = settings.edge_threshold
    MAX_POS_USD = settings.max_position_usd
    KELLY_FRACTION = settings.kelly_fraction
    SCAN_INTERVAL   = settings.scan_interval_sec
    POSITION_CHECK  = int(os.getenv("POSITION_CHECK_SEC", "8"))
    STARTING_BALANCE = settings.paper_starting_balance
    MAX_HOURS_TO_CLOSE = settings.max_hours_to_close
    MIN_HOURS_TO_CLOSE = settings.min_hours_to_close
    STOP_LOSS_THRESHOLD    = settings.stop_loss_threshold
    TAKE_PROFIT_STAKE_PCT  = settings.take_profit_stake_pct
    STOP_LOSS_STAKE_PCT    = settings.stop_loss_stake_pct
    MAX_SPREAD             = settings.max_spread
    STALE_MINUTES          = int(os.getenv("STALE_MINUTES", "30"))
    STALE_MIN_PTS          = int(os.getenv("STALE_MIN_PTS", "2"))
    SL_COOLDOWN_MIN        = int(os.getenv("SL_COOLDOWN_MINUTES", "90"))
    MAX_HOLD_HOURS         = float(os.getenv("MAX_HOLD_HOURS", "36"))
    MAX_OPEN_POSITIONS     = int(os.getenv("MAX_OPEN_POSITIONS", "20"))
    SWAP_MIN_QUALITY_GAP   = float(os.getenv("SWAP_MIN_QUALITY_GAP", "0.24"))
    SWAP_COOLDOWN_SEC      = int(os.getenv("SWAP_COOLDOWN_SEC", "900"))
    FAST_TP_MAX_HOURS      = float(os.getenv("FAST_TP_MAX_HOURS", "24"))
    FAST_TP_STAKE_PCT      = float(os.getenv("FAST_TP_STAKE_PCT", "0.020"))
    ULTRA_FAST_TP_MAX_HOURS = float(os.getenv("ULTRA_FAST_TP_MAX_HOURS", "4"))
    ULTRA_FAST_TP_STAKE_PCT = float(os.getenv("ULTRA_FAST_TP_STAKE_PCT", "0.016"))
    QUICK_TP_EDGE_MIN      = float(os.getenv("QUICK_TP_EDGE_MIN", "0.24"))
    QUICK_TP_STAKE_PCT     = float(os.getenv("QUICK_TP_STAKE_PCT", "0.018"))
    # 1.0 = tam hedef; 0.985 gibi → biraz önce TP (yuvarlama / tick kaçırma)
    TP_TRIGGER_FRAC        = max(0.88, min(1.0, float(os.getenv("TP_TRIGGER_FRAC", "1.0"))))
    # Son N saat ekstra sıkı TP (0 = kapalı; sistemi bozmaz)
    NANO_TP_MAX_HOURS      = float(os.getenv("NANO_TP_MAX_HOURS", "0"))
    NANO_TP_STAKE_PCT      = float(os.getenv("NANO_TP_STAKE_PCT", "0.013"))
    ZERO_MOM_SKIP_MAX_HOURS = float(os.getenv("ZERO_MOM_SKIP_MAX_HOURS", "48"))
    # momentum=None yalnızca kapanışa bu kadar saatten az kala bloklansın (0 = hiç bloklama)
    ZERO_MOM_NONE_MAX_HOURS = float(os.getenv("ZERO_MOM_NONE_MAX_HOURS", "18"))
    VETO_VOLATILE_NARRATIVE = int(os.getenv("VETO_VOLATILE_NARRATIVE", "1"))
    # SL azaltma — varsayılan kapalı; .env ile 1 yapınca açılır (fırsat / risk dengesi)
    VETO_EUROVISION_RANKING = int(os.getenv("VETO_EUROVISION_RANKING", "0"))
    VETO_DAILY_UP_OR_DOWN = int(os.getenv("VETO_DAILY_UP_OR_DOWN", "0"))
    SPORTS_DRIFT_SL_PCT = float(os.getenv("SPORTS_DRIFT_SL_PCT", "0.015"))
    SPORTS_DRIFT_MIN_AGE_MIN = int(os.getenv("SPORTS_DRIFT_MIN_AGE_MIN", "60"))
    LONG_STALE_MIN_AGE_HOURS = float(os.getenv("LONG_STALE_MIN_AGE_HOURS", "2"))
    LONG_SPORTS_MAX_OPEN = int(os.getenv("LONG_SPORTS_MAX_OPEN", "2"))
    SPORTS_EARLY_TP_DISCOUNT = float(os.getenv("SPORTS_EARLY_TP_DISCOUNT", "0"))
    TP_SCRATCH_MIN_AGE_MIN = int(os.getenv("TP_SCRATCH_MIN_AGE_MIN", "45"))
    TP_SCRATCH_MIN_PNL_PCT = float(os.getenv("TP_SCRATCH_MIN_PNL_PCT", "0.0025"))
    STALE_LONG_TP_MIN_PNL_PCT = float(os.getenv("STALE_LONG_TP_MIN_PNL_PCT", "0.0015"))
    MARKET_MIN_REOPEN_SEC = int(os.getenv("MARKET_MIN_REOPEN_SEC", "0"))
    TP_DROUGHT_MINUTES = int(os.getenv("TP_DROUGHT_MINUTES", "0"))
    TP_DROUGHT_STAKE_PCT = float(os.getenv("TP_DROUGHT_STAKE_PCT", "0.004"))
except Exception:
    DATA_DIR = ROOT / "data"
    _pl = os.getenv("POLYMARKET_LIVE_TRADING", "0").strip().lower() in ("1", "true", "yes")
    _pc = os.getenv("POLYMARKET_LIVE_CONFIRM", "").strip() == "I_UNDERSTAND_REAL_MONEY_LOSS"
    POLYMARKET_LIVE_ARMED = _pl and _pc
    DB_PATH = (
        Path(os.getenv("LIVE_DB_PATH", str(ROOT / "data" / "live.db")))
        if POLYMARKET_LIVE_ARMED
        else ROOT / "data" / "paper.db"
    )
    EDGE_THRESHOLD = 0.06
    MAX_POS_USD = 5.0
    KELLY_FRACTION = 0.25
    SCAN_INTERVAL  = 60
    POSITION_CHECK = int(os.getenv("POSITION_CHECK_SEC", "8"))
    STARTING_BALANCE = 22_000.0
    MAX_HOURS_TO_CLOSE = 720.0
    MIN_HOURS_TO_CLOSE = 2.0
    STOP_LOSS_THRESHOLD    = 0.15
    TAKE_PROFIT_STAKE_PCT  = float(os.getenv("TAKE_PROFIT_STAKE_PCT", "0.035"))
    STOP_LOSS_STAKE_PCT    = float(os.getenv("STOP_LOSS_STAKE_PCT", "0.05"))
    MAX_SPREAD             = 0.04
    STALE_MINUTES   = 30
    STALE_MIN_PTS   = 2
    SL_COOLDOWN_MIN = 90
    MAX_HOLD_HOURS  = 36.0
    MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "20"))
    SWAP_MIN_QUALITY_GAP = float(os.getenv("SWAP_MIN_QUALITY_GAP", "0.24"))
    SWAP_COOLDOWN_SEC = int(os.getenv("SWAP_COOLDOWN_SEC", "900"))
    FAST_TP_MAX_HOURS = float(os.getenv("FAST_TP_MAX_HOURS", "24"))
    FAST_TP_STAKE_PCT = float(os.getenv("FAST_TP_STAKE_PCT", "0.020"))
    ULTRA_FAST_TP_MAX_HOURS = float(os.getenv("ULTRA_FAST_TP_MAX_HOURS", "4"))
    ULTRA_FAST_TP_STAKE_PCT = float(os.getenv("ULTRA_FAST_TP_STAKE_PCT", "0.016"))
    QUICK_TP_EDGE_MIN = float(os.getenv("QUICK_TP_EDGE_MIN", "0.24"))
    QUICK_TP_STAKE_PCT = float(os.getenv("QUICK_TP_STAKE_PCT", "0.018"))
    TP_TRIGGER_FRAC = max(0.88, min(1.0, float(os.getenv("TP_TRIGGER_FRAC", "1.0"))))
    NANO_TP_MAX_HOURS = float(os.getenv("NANO_TP_MAX_HOURS", "0"))
    NANO_TP_STAKE_PCT = float(os.getenv("NANO_TP_STAKE_PCT", "0.013"))
    ZERO_MOM_SKIP_MAX_HOURS = float(os.getenv("ZERO_MOM_SKIP_MAX_HOURS", "48"))
    ZERO_MOM_NONE_MAX_HOURS = float(os.getenv("ZERO_MOM_NONE_MAX_HOURS", "18"))
    VETO_VOLATILE_NARRATIVE = int(os.getenv("VETO_VOLATILE_NARRATIVE", "1"))
    VETO_EUROVISION_RANKING = int(os.getenv("VETO_EUROVISION_RANKING", "0"))
    VETO_DAILY_UP_OR_DOWN = int(os.getenv("VETO_DAILY_UP_OR_DOWN", "0"))
    SPORTS_DRIFT_SL_PCT = float(os.getenv("SPORTS_DRIFT_SL_PCT", "0.015"))
    SPORTS_DRIFT_MIN_AGE_MIN = int(os.getenv("SPORTS_DRIFT_MIN_AGE_MIN", "60"))
    LONG_STALE_MIN_AGE_HOURS = float(os.getenv("LONG_STALE_MIN_AGE_HOURS", "2"))
    LONG_SPORTS_MAX_OPEN = int(os.getenv("LONG_SPORTS_MAX_OPEN", "2"))
    SPORTS_EARLY_TP_DISCOUNT = float(os.getenv("SPORTS_EARLY_TP_DISCOUNT", "0"))
    TP_SCRATCH_MIN_AGE_MIN = int(os.getenv("TP_SCRATCH_MIN_AGE_MIN", "45"))
    TP_SCRATCH_MIN_PNL_PCT = float(os.getenv("TP_SCRATCH_MIN_PNL_PCT", "0.0025"))
    STALE_LONG_TP_MIN_PNL_PCT = float(os.getenv("STALE_LONG_TP_MIN_PNL_PCT", "0.0015"))
    MARKET_MIN_REOPEN_SEC = int(os.getenv("MARKET_MIN_REOPEN_SEC", "0"))
    TP_DROUGHT_MINUTES = int(os.getenv("TP_DROUGHT_MINUTES", "0"))
    TP_DROUGHT_STAKE_PCT = float(os.getenv("TP_DROUGHT_STAKE_PCT", "0.004"))

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

# Canlı tarayıcı: paper.db öğrenmesini okur, live.db'ye yazar; pkl güncellemez
LEARN_READONLY = os.getenv("POLYMARKET_LEARN_READONLY", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
# Canlıda yalnızca stake'in %X'i TP/SL (katmanlı TP / EXP / STALE yok)
LIVE_SIMPLE_EXIT = os.getenv("LIVE_SIMPLE_EXIT", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

MIN_VOLUME = 5_000.0       # Likidite filtresi
# Polymarket CLOB canlı emir istemcisi (main içinde atanır)
_CLOB_TRADING_CLIENT: Any | None = None
# İstatistik / günlük limit / self-improve: tam sıfır P&L kapanışları sayılmaz
PNL_NONZERO_SQL = "ABS(COALESCE(pnl_usd, 0)) > 0.0001"
PNL_NEAR_ZERO_USD = 0.0001  # swap: bu altındaki |tahmini P&L| = breakeven, kapatma

# Son başarılı swap’tan sonra tekrar swap yok (sürekli churn önler)
_swap_cooldown_until = 0.0
# Son TP kapanışı (kuraklık micro modu için)
_last_tp_closed_at: float = 0.0

MOMENTUM_LOOKBACK = 12     # Son kaç CLOB noktası kullanılır
MIN_RECENT_POINTS = 2      # Son 1 saatte en az bu kadar CLOB noktası → aktif market
MIN_VOLATILITY_1H = 0.02   # Son 1 saatte en az %2 fiyat aralığı → hızlı hareket potansiyeli

HIGH_MOM_GAP_VETO     = 0.05   # |momentum| > bu VE yes_price > 0.70 ise skip
LIVE_EVENT_MOM_VETO  = 0.15   # |momentum| > bu → maç muhtemelen canlı, her fiyatta skip

# ─── Kural 1: Canlı esports event marketleri — anlık gap riski ──────────────────
# SL hiçbir zaman çalışmaz: fiyat saniyeler içinde 30-50¢ atlayabiliyor.
# Kök neden: maç oynanırken oyun/seri bitişinde anlık çöküş (13 saniyede -50%).
import re as _re

# Tek oyunluk binary (Game N Winner, Map N Winner)
_SINGLE_GAME_PATTERNS = [
    _re.compile(r'\bGame\s+\d+\s+Winner\b', _re.IGNORECASE),
    _re.compile(r'\bMap\s+\d+\s+Winner\b',  _re.IGNORECASE),
    _re.compile(r'\s-\s+Game\s+\d+\b',      _re.IGNORECASE),
    _re.compile(r'\s-\s+Map\s+\d+\b',       _re.IGNORECASE),
    _re.compile(r'\bGame\s+\d+\s*$',        _re.IGNORECASE),
]

# Best-of-X seri maçları — canlı oynanırken fiyat saniyeler içinde 30¢ atlıyor
_BOX_SERIES_PATTERNS = [
    _re.compile(r'\(BO\d+\)',          _re.IGNORECASE),   # (BO3), (BO5) vb.
    _re.compile(r'\bBO\d+\b',         _re.IGNORECASE),   # BO3, BO5 (parantez olmadan)
    _re.compile(r'\bBest\s+of\s+\d+\b', _re.IGNORECASE), # Best of 3
    _re.compile(r'\bGame\s+Handicap\b', _re.IGNORECASE), # handicap serisi
    _re.compile(r'\bMap\s+Handicap\b',  _re.IGNORECASE),
    _re.compile(r'\bFirst\s+Map\b',    _re.IGNORECASE),
    _re.compile(r'\bFirst\s+Blood\b',  _re.IGNORECASE),
]


def _is_single_game_market(question: str) -> bool:
    """Tek oyunluk veya canlı BO seri marketi mi? (gap riski → yasaklı)"""
    if any(p.search(question) for p in _SINGLE_GAME_PATTERNS):
        return True
    if any(p.search(question) for p in _BOX_SERIES_PATTERNS):
        return True
    return False


# Canlı event tabanlı konuşma/eylem tahminleri — "Will X say/do Y?"
# Bunlar canlı bir olaya bağlı, fiyat saniyeler içinde 0 veya 1'e atlıyor.
# Trump "Iran" örneği: 3 farklı taraftan giriş, hepsi kayıp.
_LIVE_SPEECH_PATTERNS = [
    _re.compile(r'\bwill\s+\w+\s+say\b',      _re.IGNORECASE),  # Will X say Y?
    _re.compile(r'\bwill\s+\w+\s+mention\b',   _re.IGNORECASE),  # Will X mention Y?
    _re.compile(r'\bwill\s+\w+\s+announce\b',  _re.IGNORECASE),  # Will X announce Y?
    _re.compile(r'\bduring\s+(the\s+)?(meeting|summit|conference|debate|interview|speech|press|call)\b',
                _re.IGNORECASE),
    _re.compile(r'\b(meeting|summit|conference)\s+with\b', _re.IGNORECASE),
]


def _is_live_speech_market(question: str) -> bool:
    """Canlı konuşma/toplantı sırasında olan eylem tahmini mi? (unpredictable → yasaklı)"""
    return any(p.search(question) for p in _LIVE_SPEECH_PATTERNS)


# Haber / sayaç / diplomasi hype — kısa sürede fiyat kayması → SL (#107 Iran, #108 tweet sayacı)
_VOLATILE_NARRATIVE_PATTERNS = [
    _re.compile(r"\bdiplomatic\s+meeting\b", _re.IGNORECASE),
    _re.compile(r"\bUS\s*x\s*Iran\b", _re.IGNORECASE),
    _re.compile(r"\bpost\s+<\s*\d+", _re.IGNORECASE),  # "post <40 tweets ..."
    _re.compile(r"\btweets?\s+from\b.*\b20\d{2}\b", _re.IGNORECASE),  # tweets from ... tarih penceresi
    # SL: #201, #149 — "40-64 tweets" bandı (post <N ile yakalanmıyordu)
    _re.compile(r"\belon\s+musk\b.{0,80}\b\d+\s*-\s*\d+\s+tweets?\b", _re.IGNORECASE),
    _re.compile(r"\b\d+\s*-\s*\d+\s+tweets?\b.{0,80}\belon\s+musk\b", _re.IGNORECASE),
    # Beyaz Saray / kurum post sayacı aralığı — kısa vadede SL yoğun (paper veri)
    _re.compile(r"\bwhite\s+house\b.{0,160}\b\d+\s*-\s*\d+\b", _re.IGNORECASE),
    _re.compile(r"\b\d+\s*-\s*\d+\s+posts?\s+from\b", _re.IGNORECASE),
]


def _is_volatile_narrative_market(question: str) -> bool:
    """Tweet sayacı, diplomasi penceresi gibi yüksek gürültülü anlatı marketleri."""
    if not question:
        return False
    return any(p.search(question) for p in _VOLATILE_NARRATIVE_PATTERNS)


def _is_eurovision_ranking_market(question: str) -> bool:
    """
    Eurovision — sıralama, televote/jury ve doğrudan 'kazanır mı' ikilileri.
    Paper son 100 kapanış: SL'lerin çoğu Eurovision (top-N, outright win, jury).
    VETO_EUROVISION_RANKING=1 ile kapatılır (env adı tarihsel; kapsam genişletildi).
    """
    if not question or "eurovision" not in question.lower():
        return False
    if _re.search(
        r"\b(top\s+\d+|televote|grand\s+final|semi[-\s]?final|jury|winner)\b",
        question,
        _re.IGNORECASE,
    ):
        return True
    # "Will Finland win Eurovision 2026?" — ranking regex winner kelimesini tutmaz
    if _re.search(r"\bwin(s)?\b.{0,24}\beurovision\b", question, _re.IGNORECASE):
        return True
    if _re.search(r"\beurovision\b.{0,48}\bwin(s)?\b", question, _re.IGNORECASE):
        return True
    return False


def _is_daily_up_or_down_market(question: str) -> bool:
    """Gün içi 'Up or Down' — WTI/BTC vb. SL yoğun (whipsaw)."""
    if not question:
        return False
    if "up or down" not in question.lower():
        return False
    q = question.lower()
    return any(
        k in q
        for k in (
            "wti", "crude", "oil", "bitcoin", "ethereum",
            "solana", "xrp", "ripple", "doge", "s&p", "nasdaq",
        )
    )


_CRYPTO_STRIKE_RE = _re.compile(
    r"\b(above|below|over|under|at least|at most|greater than|less than)\b",
    _re.IGNORECASE,
)
_CRYPTO_ASSETS = ("bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "doge", "dogecoin")

_ESPORTS_OUTRIGHT_KW = (
    "pgl", "blast", "iem", "esl", "cs2", "counter-strike", "counter strike",
    "dota", "valorant", "league of legends", "lck", "lec", "vct", "major",
    "astana", "copenhagen", "stockholm",
)


def _is_crypto_strike_market(question: str) -> bool:
    """BTC/ETH 'above $80k on May 16' — kısa vadede whipsaw, ucuz TP zor."""
    if not question:
        return False
    q = question.lower()
    if not any(a in q for a in _CRYPTO_ASSETS):
        return False
    return bool(_CRYPTO_STRIKE_RE.search(q))


def _is_esports_outright_market(question: str) -> bool:
    """'Will Spirit win PGL…' — maç/turnuva gürültüsü, SL yoğun (canlı tek oyun ayrı)."""
    if not question or _is_single_game_market(question):
        return False
    q = question.lower()
    if not _re.search(r"\bwin(s)?\b", q):
        return False
    return any(k in q for k in _ESPORTS_OUTRIGHT_KW)


# ─── Korelasyon filtresi: aynı varlık + tarih kombinasyonu ──────────────────
# Örn: "Bitcoin ... May 14" etiketinde zaten pozisyon varsa yeni giriş engelle.
# BTC $78k-$80k + $80k-$82k + $80k üzeri = aynı olaya 3 pozisyon → hepsi kayıp.
_CORR_ASSETS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "ripple",
    "dogecoin", "doge", "bnb", "binance", "cardano", "ada", "avax",
    "trump", "biden", "harris", "fed", "interest rate", "inflation",
    "oil", "wti", "gold", "silver", "nasdaq", "s&p", "dow",
]
_CORR_DATE_RE = _re.compile(
    r'\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
    r'\s+\d{1,2}\b|\b\d{4}-\d{2}-\d{2}\b|\bq[1-4]\s+20\d\d\b',
    _re.IGNORECASE,
)


def _corr_key(question: str) -> frozenset:
    """Bir sorudan (varlık, tarih) çifti oluştur — korelasyon karşılaştırması için."""
    q = question.lower()
    tokens: set[str] = set()
    for asset in _CORR_ASSETS:
        if asset in q:
            tokens.add(asset)
            break  # İlk eşleşen varlık yeterli
    for m in _CORR_DATE_RE.findall(q):
        tokens.add(m.lower().strip())
    return frozenset(tokens)


def _live_event_key(question: str) -> str:
    """Aynı maç / event: 'Team A vs. Team B: O/U 210.5' → 'team a vs. team b'."""
    q = (question or "").strip()
    if ":" in q:
        q = q.split(":", 1)[0].strip()
    return q.lower()[:72]


def _one_per_event_enabled() -> bool:
    if POLYMARKET_LIVE_ARMED:
        return os.getenv("LIVE_ONE_PER_EVENT", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
    return os.getenv("PAPER_ONE_PER_EVENT", "0").strip().lower() in ("1", "true", "yes")


def _same_event_open(conn: sqlite3.Connection, question: str) -> bool:
    """Aynı maç başlığında ikinci pozisyon açma (spread + O/U yığını)."""
    if not _one_per_event_enabled():
        return False
    key = _live_event_key(question)
    if len(key) < 10:
        return False
    for row in conn.execute("SELECT question FROM positions WHERE closed_at IS NULL"):
        if _live_event_key(row["question"] or "") == key:
            return True
    return False


def _live_same_event_open(conn: sqlite3.Connection, question: str) -> bool:
    """Geriye uyumluluk — canlı/paper aynı mantık."""
    return _same_event_open(conn, question)


def _sports_theme(question: str) -> str:
    return self_improver._position_theme_bucket(question)


def _is_sports_question(question: str) -> bool:
    return _sports_theme(question) in ("sports_line", "sports_match", "esports")


def _is_sports_totals_market(question: str) -> bool:
    """Games Total / maç O-U (canlı gol sonrası bayat fiyat riski)."""
    q = (question or "").lower()
    if "games total" in q:
        return True
    if "o/u" in q or "over/under" in q or " over " in q and " under " in q:
        return " vs" in q or " vs." in q
    if "total:" in q and (" vs" in q or " vs." in q):
        return True
    return False


def _veto_sports_totals(hours_left: float, question: str) -> bool:
    if os.getenv("VETO_LIVE_SPORTS_TOTALS", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    if not _is_sports_totals_market(question):
        return False
    try:
        max_h = float(os.getenv("VETO_SPORTS_TOTALS_MAX_HOURS", "12"))
    except ValueError:
        max_h = 12.0
    return hours_left <= max_h


def _is_long_horizon_sports(hours_left: float | None, question: str) -> bool:
    return _is_sports_question(question) and hours_left is not None and hours_left > 4.0


def _hours_left_from_rationale(rationale: str | None) -> float | None:
    if not rationale:
        return None
    m = _re.search(r"hours_left=([\d.]+)h", str(rationale))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _long_sports_open_count(conn: sqlite3.Connection) -> int:
    n = 0
    for row in conn.execute(
        "SELECT question, rationale FROM positions WHERE closed_at IS NULL"
    ):
        hl = _hours_left_from_rationale(row["rationale"])
        if _is_long_horizon_sports(hl, row["question"] or ""):
            n += 1
    return n


def _market_reopen_blocked(conn: sqlite3.Connection, market_id: str) -> bool:
    sec = MARKET_MIN_REOPEN_SEC
    if sec <= 0:
        return False
    if conn.execute(
        "SELECT 1 FROM positions WHERE market_id=? AND closed_at IS NULL LIMIT 1",
        (market_id,),
    ).fetchone():
        return True
    row = conn.execute(
        """
        SELECT closed_at FROM positions
        WHERE market_id=? AND closed_at IS NOT NULL
        ORDER BY datetime(closed_at) DESC LIMIT 1
        """,
        (market_id,),
    ).fetchone()
    if not row or not row["closed_at"]:
        return False
    try:
        closed_dt = datetime.fromisoformat(str(row["closed_at"]).replace("Z", "+00:00"))
        if closed_dt.tzinfo is None:
            closed_dt = closed_dt.replace(tzinfo=timezone.utc)
        age = time.time() - closed_dt.timestamp()
        return age < float(sec)
    except Exception:
        return False


def _note_tp_closed() -> None:
    global _last_tp_closed_at
    _last_tp_closed_at = time.time()


def _tp_drought_active() -> bool:
    if TP_DROUGHT_MINUTES <= 0 or _last_tp_closed_at <= 0:
        return False
    return (time.time() - _last_tp_closed_at) >= float(TP_DROUGHT_MINUTES) * 60.0


def _reload_paper_env_globals() -> None:
    """Paper / senaryo: .env + insane_24h + senaryo dosyası → modül sabitleri."""
    global TAKE_PROFIT_STAKE_PCT, STOP_LOSS_STAKE_PCT, TP_TRIGGER_FRAC
    global MAX_OPEN_POSITIONS, MAX_POS_USD, POSITION_CHECK, EDGE_THRESHOLD
    global KELLY_FRACTION, SCAN_INTERVAL, FAST_TP_MAX_HOURS, FAST_TP_STAKE_PCT
    global ULTRA_FAST_TP_MAX_HOURS, ULTRA_FAST_TP_STAKE_PCT, QUICK_TP_EDGE_MIN
    global QUICK_TP_STAKE_PCT, NANO_TP_MAX_HOURS, NANO_TP_STAKE_PCT
    global SPORTS_DRIFT_SL_PCT, SPORTS_DRIFT_MIN_AGE_MIN, LONG_STALE_MIN_AGE_HOURS
    global LONG_SPORTS_MAX_OPEN, SPORTS_EARLY_TP_DISCOUNT, TP_SCRATCH_MIN_AGE_MIN
    global TP_SCRATCH_MIN_PNL_PCT, STALE_LONG_TP_MIN_PNL_PCT, MARKET_MIN_REOPEN_SEC
    global TP_DROUGHT_MINUTES, TP_DROUGHT_STAKE_PCT
    _db = str(DB_PATH).replace("\\", "/")
    if POLYMARKET_LIVE_ARMED and _db.endswith("/live.db"):
        return
    if os.getenv("INSANE_24H", "").strip().lower() in ("1", "true", "yes"):
        try:
            from dotenv import dotenv_values

            for _env_name in ("insane_24h.env", "apex_2x_24h.env"):
                _p = ROOT / "scenarios" / _env_name
                if _p.is_file():
                    for _k, _v in dotenv_values(_p).items():
                        if _v is not None:
                            os.environ[str(_k)] = str(_v)
        except Exception:
            pass
    TAKE_PROFIT_STAKE_PCT = float(
        os.getenv("TAKE_PROFIT_STAKE_PCT", str(TAKE_PROFIT_STAKE_PCT))
    )
    STOP_LOSS_STAKE_PCT = float(
        os.getenv("STOP_LOSS_STAKE_PCT", str(STOP_LOSS_STAKE_PCT))
    )
    TP_TRIGGER_FRAC = max(
        0.88, min(1.0, float(os.getenv("TP_TRIGGER_FRAC", str(TP_TRIGGER_FRAC))))
    )
    MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", str(MAX_OPEN_POSITIONS)))
    MAX_POS_USD = float(os.getenv("MAX_POSITION_USD", str(MAX_POS_USD)))
    POSITION_CHECK = int(os.getenv("POSITION_CHECK_SEC", str(POSITION_CHECK)))
    EDGE_THRESHOLD = float(os.getenv("EDGE_THRESHOLD", str(EDGE_THRESHOLD)))
    KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", str(KELLY_FRACTION)))
    SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SEC", str(SCAN_INTERVAL)))
    FAST_TP_MAX_HOURS = float(os.getenv("FAST_TP_MAX_HOURS", str(FAST_TP_MAX_HOURS)))
    FAST_TP_STAKE_PCT = float(os.getenv("FAST_TP_STAKE_PCT", str(FAST_TP_STAKE_PCT)))
    ULTRA_FAST_TP_MAX_HOURS = float(
        os.getenv("ULTRA_FAST_TP_MAX_HOURS", str(ULTRA_FAST_TP_MAX_HOURS))
    )
    ULTRA_FAST_TP_STAKE_PCT = float(
        os.getenv("ULTRA_FAST_TP_STAKE_PCT", str(ULTRA_FAST_TP_STAKE_PCT))
    )
    QUICK_TP_EDGE_MIN = float(os.getenv("QUICK_TP_EDGE_MIN", str(QUICK_TP_EDGE_MIN)))
    QUICK_TP_STAKE_PCT = float(os.getenv("QUICK_TP_STAKE_PCT", str(QUICK_TP_STAKE_PCT)))
    NANO_TP_MAX_HOURS = float(os.getenv("NANO_TP_MAX_HOURS", str(NANO_TP_MAX_HOURS)))
    NANO_TP_STAKE_PCT = float(os.getenv("NANO_TP_STAKE_PCT", str(NANO_TP_STAKE_PCT)))
    SPORTS_DRIFT_SL_PCT = float(os.getenv("SPORTS_DRIFT_SL_PCT", str(SPORTS_DRIFT_SL_PCT)))
    SPORTS_DRIFT_MIN_AGE_MIN = int(
        os.getenv("SPORTS_DRIFT_MIN_AGE_MIN", str(SPORTS_DRIFT_MIN_AGE_MIN))
    )
    LONG_STALE_MIN_AGE_HOURS = float(
        os.getenv("LONG_STALE_MIN_AGE_HOURS", str(LONG_STALE_MIN_AGE_HOURS))
    )
    LONG_SPORTS_MAX_OPEN = int(os.getenv("LONG_SPORTS_MAX_OPEN", str(LONG_SPORTS_MAX_OPEN)))
    SPORTS_EARLY_TP_DISCOUNT = float(
        os.getenv("SPORTS_EARLY_TP_DISCOUNT", str(SPORTS_EARLY_TP_DISCOUNT))
    )
    TP_SCRATCH_MIN_AGE_MIN = int(os.getenv("TP_SCRATCH_MIN_AGE_MIN", str(TP_SCRATCH_MIN_AGE_MIN)))
    TP_SCRATCH_MIN_PNL_PCT = float(
        os.getenv("TP_SCRATCH_MIN_PNL_PCT", str(TP_SCRATCH_MIN_PNL_PCT))
    )
    STALE_LONG_TP_MIN_PNL_PCT = float(
        os.getenv("STALE_LONG_TP_MIN_PNL_PCT", str(STALE_LONG_TP_MIN_PNL_PCT))
    )
    MARKET_MIN_REOPEN_SEC = int(os.getenv("MARKET_MIN_REOPEN_SEC", str(MARKET_MIN_REOPEN_SEC)))
    TP_DROUGHT_MINUTES = int(os.getenv("TP_DROUGHT_MINUTES", str(TP_DROUGHT_MINUTES)))
    TP_DROUGHT_STAKE_PCT = float(os.getenv("TP_DROUGHT_STAKE_PCT", str(TP_DROUGHT_STAKE_PCT)))


def _reload_live_env_globals() -> None:
    """live.scanner.env değerlerini modül sabitlerine uygula (config import sonrası)."""
    global TAKE_PROFIT_STAKE_PCT, STOP_LOSS_STAKE_PCT, TP_TRIGGER_FRAC
    global MAX_OPEN_POSITIONS, MAX_POS_USD, LIVE_SIMPLE_EXIT, POSITION_CHECK
    if not POLYMARKET_LIVE_ARMED:
        return
    TAKE_PROFIT_STAKE_PCT = float(os.getenv("TAKE_PROFIT_STAKE_PCT", str(TAKE_PROFIT_STAKE_PCT)))
    STOP_LOSS_STAKE_PCT = float(os.getenv("STOP_LOSS_STAKE_PCT", str(STOP_LOSS_STAKE_PCT)))
    TP_TRIGGER_FRAC = max(0.88, min(1.0, float(os.getenv("TP_TRIGGER_FRAC", str(TP_TRIGGER_FRAC)))))
    MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", str(MAX_OPEN_POSITIONS)))
    MAX_POS_USD = float(os.getenv("MAX_POSITION_USD", str(MAX_POS_USD)))
    POSITION_CHECK = int(os.getenv("POSITION_CHECK_SEC", str(POSITION_CHECK)))
    LIVE_SIMPLE_EXIT = os.getenv("LIVE_SIMPLE_EXIT", "1").strip().lower() in ("1", "true", "yes")


def _is_correlated_position(
    conn: sqlite3.Connection, question: str, *, exclude_market_id: str | None = None
) -> bool:
    """Aynı varlık + tarihte zaten açık pozisyon var mı?

    exclude_market_id: katmanlı girişte aynı market_id'deki mevcut pozisyonları sayma.
    """
    new_key = _corr_key(question)
    if len(new_key) < 2:  # Varlık + tarih ikisi de yoksa kontrol etme
        return False
    open_qs = conn.execute(
        "SELECT question, market_id FROM positions WHERE closed_at IS NULL"
    ).fetchall()
    for row in open_qs:
        if exclude_market_id and str(row["market_id"] or "") == exclude_market_id:
            continue
        existing_key = _corr_key(row["question"] or "")
        if len(new_key & existing_key) >= 2:  # 2+ ortak etiket → korelasyonlu
            return True
    return False

# ─── Kalibre edilmiş gerçek olasılık tablosu (2.3M data point'ten) ───────────
# bucket_idx → (YES için gerçek olasılık, bias)
# bucket_idx = int(yes_price * 10), min(9, ...)
# NOT: Bu tablo self_improver tarafından her döngüde Bayesian güncelleme alır.
CALIBRATION: dict[int, tuple[float, float]] = {
    0: (0.0098,  -0.0002),
    1: (0.1265,  -0.0141),
    2: (0.3466,  +0.0953),
    3: (0.3604,  +0.0176),
    4: (0.1828,  -0.2744),  # BUY NO ★★★  → true NO prob = 0.8172
    5: (0.8495,  +0.3193),  # BUY YES ★★★
    6: (0.9072,  +0.2603),  # BUY YES ★★
    7: (0.9603,  +0.2107),  # BUY YES ★★
    8: (0.9620,  +0.1074),  # BUY YES ★
    9: (0.9951,  +0.0258),  # BUY YES (küçük edge)
}

# Momentum skoru eşiği: bu değerden hızlı zıt yönde gidiyorsa sinyal atla
# self_improver tarafından win-rate analizine göre otomatik güncellenir
MOMENTUM_VETO = 0.015  # 24h'de >+1.5 puan yükseliş → BUY NO sinyalini veto et
THEME_EDGE_BOOST: dict[str, float] = {}  # self_improver TP/SL öğrenmesi


# ═══════════════════════════════════════════════════════════════════════════════
#  DB başlatma
# ═══════════════════════════════════════════════════════════════════════════════

def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venue TEXT NOT NULL,
            market_id TEXT NOT NULL,
            question TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            true_prob REAL NOT NULL,
            edge REAL NOT NULL,
            stake_usd REAL NOT NULL,
            contracts REAL NOT NULL,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            close_price REAL,
            resolved_yes INTEGER,
            pnl_usd REAL,
            rationale TEXT,
            exit_reason TEXT,
            outcome_token_id TEXT,
            neg_risk INTEGER,
            tick_size TEXT,
            live_order_id TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_positions_open
        ON positions(market_id, side, closed_at)
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_one_open_market
        ON positions(market_id) WHERE closed_at IS NULL
    """)
    _cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()}
    for col, typ in (
        ("exit_reason", "TEXT"),
        ("outcome_token_id", "TEXT"),
        ("neg_risk", "INTEGER"),
        ("tick_size", "TEXT"),
        ("live_order_id", "TEXT"),
        ("condition_id", "TEXT"),
    ):
        if col not in _cols:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {col} {typ}")
    conn.commit()
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
#  Yardımcı fonksiyonlar
# ═══════════════════════════════════════════════════════════════════════════════

def _get_with_retry(client: httpx.Client, url: str, params: dict | None = None,
                    retries: int = 2, timeout: float = 12.0) -> dict | None:
    """GET isteği — timeout/connection hatasında 1s bekleyip tekrar dener."""
    for attempt in range(retries + 1):
        try:
            r = client.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            return None
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError):
            if attempt < retries:
                time.sleep(1.0)
            continue
        except Exception:
            return None
    return None


def _parse_tokens(raw) -> list[str]:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return []
    return list(raw or [])


def _use_clob_midpoint_for_entry() -> bool:
    if os.getenv("CLOB_MIDPOINT_FOR_ENTRY", "1").strip().lower() in ("0", "false", "no"):
        return False
    if POLYMARKET_LIVE_ARMED:
        return True
    return os.getenv("PAPER_USE_CLOB_MIDPOINT", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _apply_clob_midpoint_yes_price(
    client: httpx.Client, yes_token: str, yes_price: float
) -> tuple[float, bool]:
    """Gamma outcomePrices yerine CLOB midpoint (giriş + edge daha gerçekçi)."""
    if not _use_clob_midpoint_for_entry():
        return yes_price, False
    import live_clob as lc

    mid = lc.fetch_midpoint_http(client, yes_token)
    if mid is None:
        return yes_price, False
    if abs(mid - yes_price) > 0.25:
        return yes_price, False
    return mid, True


def _normalize_condition_id(m: dict) -> str:
    cid = (m.get("conditionId") or m.get("condition_id") or "").strip()
    if cid:
        return cid.lower() if cid.startswith("0x") else cid
    return ""


def _parse_outcome_prices(raw) -> tuple[float, float] | None:
    """(yes_price, no_price) ya da None döner."""
    if isinstance(raw, str):
        try:
            arr = json.loads(raw)
        except Exception:
            return None
    else:
        arr = raw or []
    if len(arr) < 2:
        return None
    try:
        return float(arr[0]), float(arr[1])
    except (TypeError, ValueError):
        return None


def _linear_slope(points: list[float]) -> float:
    """Basit lineer regresyon eğimi (normalleştirilmiş x: 0..1)."""
    n = len(points)
    if n < 2:
        return 0.0
    xs = [i / (n - 1) for i in range(n)]
    mx = sum(xs) / n
    my = sum(points) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, points))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def _gap_stake_cap(yes_price: float) -> float:
    """Yüksek fiyatlı markette gap riskine karşı stake tavanı (genel tavanı aşmaz)."""
    cap_hi = float(os.getenv("GAP_STAKE_CAP_80", str(MAX_POS_USD * 0.5)))
    cap_mid = float(os.getenv("GAP_STAKE_CAP_70", str(MAX_POS_USD * 0.75)))
    if yes_price >= 0.80:
        return min(cap_hi, MAX_POS_USD)
    if yes_price >= 0.70:
        return min(cap_mid, MAX_POS_USD)
    return MAX_POS_USD


def kelly_stake(true_prob: float, entry_price: float, yes_price: float | None = None) -> float:
    """Kelly * fraction, fiyat bölgesine göre gap-aware üst sınırla."""
    if entry_price <= 0 or entry_price >= 1:
        return 0.0
    b = (1.0 / entry_price) - 1.0
    k = (true_prob * b - (1.0 - true_prob)) / b
    if k <= 0:
        return 0.0
    stake = STARTING_BALANCE * KELLY_FRACTION * k
    cap = _gap_stake_cap(yes_price) if yes_price is not None else MAX_POS_USD
    return min(stake, cap)


def signal_for_price(yes_price: float) -> tuple[str, float, float] | None:
    """
    YES fiyatı verilen bir market için sinyal hesaplar.
    Döndürür: (side, entry_price, edge) ya da None (edge yoksa).

    Uç fiyat kuralı: yes_price > 0.85 veya < 0.15 ise daha yüksek edge gerekir.
    Bu bölgelerdeki kalibrasyonun örneklem sayısı düşük ve kayıp riski yüksek.
    """
    bi = min(9, int(yes_price * 10))
    cal_yes, _ = CALIBRATION[bi]

    yes_edge = cal_yes - yes_price
    no_price  = 1.0 - yes_price
    cal_no    = 1.0 - cal_yes
    no_edge   = cal_no - no_price

    # Uç fiyat bölgesinde daha yüksek edge zorunlu
    # (>0.85 veya <0.15): bu aralıklar "neredeyse çözülmüş" → küçük hata büyük kayıp
    extreme_price = yes_price > 0.85 or yes_price < 0.15
    required_edge = (EDGE_THRESHOLD * 2.0) if extreme_price else EDGE_THRESHOLD

    if yes_edge >= no_edge and yes_edge >= required_edge:
        return ("YES", yes_price, yes_edge)
    if no_edge > yes_edge and no_edge >= required_edge:
        return ("NO", no_price, no_edge)
    return None


def entry_score(
    edge: float,
    momentum: float | None,
    spread: float,
    yes_price: float,
    hours_left: float,
) -> int:
    """
    0-5 arası giriş kalite skoru. Düşük skorda pozisyon açılmaz.

    Puan kaynakları:
      Edge büyüklüğü   : ≥0.10 → +1, ≥0.20 → +2, ≥0.30 → +3  (max 3)
      Momentum nötr    : |mom| < 0.008 → +1  (piyasa sakin, swing yok)
      Sıkı spread      : spread ≤ 0.02 → +1   (likit market)
    Ceza:
      Uç fiyat bölgesi : -1  (>0.85 veya <0.15)
    """
    score = 0

    # Edge puanı (max 3)
    if edge >= 0.30:
        score += 3
    elif edge >= 0.20:
        score += 2
    elif edge >= 0.10:
        score += 1

    # Momentum destekleyici: hafif hareket var ama aşırı değil
    # Sıfır momentum = fiyat geçmişi yok → bonus verilmez, sadece düşük hareket puanlanır
    if momentum is not None and 0.001 < abs(momentum) < 0.008:
        score += 1

    # Sıkı spread
    if spread > 0 and spread <= 0.02:
        score += 1

    # Uç fiyat cezası
    if yes_price > 0.85 or yes_price < 0.15:
        score -= 1

    return max(0, score)


# ═══════════════════════════════════════════════════════════════════════════════
#  CLOB momentum
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_entry_signals(
    client: httpx.Client, token_id: str
) -> tuple[float | None, bool, float, float | None]:
    """
    Tüm giriş sinyallerini tek seferde çeker.
    Döner: (slope, is_active, spread, last_trade_price)
      slope            : lineer momentum eğimi (None = veri yok)
      is_active        : son 1h aktivite + volatilite kontrolü
      spread           : bid-ask spread (0.0 = bilinmiyor)
      last_trade_price : son işlem fiyatı (None = bilinmiyor)
    """
    # ── 1. Fiyat geçmişi (momentum + aktivite) ──────────────────────────────
    data = _get_with_retry(client, f"{CLOB}/prices-history",
                           params={"market": token_id, "interval": "1d"},
                           timeout=15.0)
    if not data or not (data.get("history") or []):
        data = _get_with_retry(client, f"{CLOB}/prices-history",
                               params={"market": token_id, "interval": "max"},
                               timeout=15.0)

    slope: float | None = None
    is_active = False

    if data:
        history = data.get("history") or []
        if len(history) >= 2:
            cutoff_1h = time.time() - 3600
            recent_1h = [h for h in history if h.get("t", 0) >= cutoff_1h]
            points_1h = len(recent_1h)
            prices_1h = [float(h["p"]) for h in recent_1h if "p" in h]
            vol_1h    = max(prices_1h) - min(prices_1h) if len(prices_1h) >= 2 else 0.0
            is_active = points_1h >= MIN_RECENT_POINTS and vol_1h >= MIN_VOLATILITY_1H

            recent = history[-MOMENTUM_LOOKBACK:]
            prices = [float(h["p"]) for h in recent if "p" in h]
            slope  = _linear_slope(prices) if len(prices) >= 2 else None

    # ── 2. Spread (bid-ask) ──────────────────────────────────────────────────
    spread = 0.0
    spread_data = _get_with_retry(client, f"{CLOB}/spread",
                                  params={"token_id": token_id}, timeout=8.0)
    if spread_data:
        try:
            spread = float(spread_data.get("spread", 0))
        except (TypeError, ValueError):
            pass

    # ── 3. Son işlem fiyatı ──────────────────────────────────────────────────
    last_trade: float | None = None
    lt_data = _get_with_retry(client, f"{CLOB}/last-trade-price",
                               params={"token_id": token_id}, timeout=8.0)
    if lt_data:
        try:
            last_trade = float(lt_data.get("price", 0)) or None
        except (TypeError, ValueError):
            pass

    return slope, is_active, spread, last_trade


# Geriye dönük uyumluluk için alias
def fetch_momentum(client: httpx.Client, token_id: str) -> tuple[float | None, bool]:
    slope, is_active, _, _ = fetch_entry_signals(client, token_id)
    return slope, is_active


# ═══════════════════════════════════════════════════════════════════════════════
#  Pozisyon açma / kapama
# ═══════════════════════════════════════════════════════════════════════════════

def open_position(
    conn: sqlite3.Connection,
    market_id: str,
    question: str,
    side: str,
    entry_price: float,
    true_prob: float,
    edge: float,
    rationale: str,
    *,
    outcome_token_id: str | None = None,
    yes_price: float | None = None,
    stake_usd: float | None = None,
    condition_id: str | None = None,
) -> int:
    global _CLOB_TRADING_CLIENT
    if POLYMARKET_LIVE_ARMED and _CLOB_TRADING_CLIENT is not None:
        from markets.polymarket_geoblock import assert_can_trade_live

        geo_ok, geo_msg = assert_can_trade_live()
        if not geo_ok:
            print(f"  [LIVE] 🌍 geoblock: {geo_msg}")
            return -1

    if stake_usd is not None and stake_usd > 0:
        stake = float(stake_usd)
    else:
        kelly = kelly_stake(true_prob, entry_price, yes_price=yes_price)
        if POLYMARKET_LIVE_ARMED:
            stake = kelly
        else:
            stake = _finalize_paper_stake(kelly, yes_price)
    if stake <= 0:
        return -1

    conn.execute("BEGIN IMMEDIATE")
    try:
        dup = conn.execute(
            "SELECT id FROM positions WHERE market_id=? AND closed_at IS NULL LIMIT 1",
            (market_id,),
        ).fetchone()
        if dup:
            conn.execute("ROLLBACK")
            print(f"  🚫 DUP-DB market_id={market_id} zaten açık (#{dup['id']})")
            return -2
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise

    contracts = stake / entry_price
    live_oid: str | None = None
    nr_val: int | None = None
    tick_s: str | None = None

    if POLYMARKET_LIVE_ARMED and _CLOB_TRADING_CLIENT is not None and outcome_token_id:
        import live_clob as lc

        tick_s = _CLOB_TRADING_CLIENT.get_tick_size(outcome_token_id)
        nr_val = 1 if _CLOB_TRADING_CLIENT.get_neg_risk(outcome_token_id) else 0
        min_sh = lc.get_min_order_size(_CLOB_TRADING_CLIENT, outcome_token_id)
        planned = lc.plan_live_buy(entry_price, stake, MAX_POS_USD, min_sh)
        if planned is None:
            need = min_sh * entry_price
            print(
                f"  [LIVE] atla: min {min_sh:g} pay @ {entry_price:.3f} "
                f"≈ ${need:.2f} > max ${MAX_POS_USD:.2f}"
            )
            return -1
        contracts, stake = planned
        stack_ok, stack_msg = lc.validate_live_stack_buy(
            _CLOB_TRADING_CLIENT,
            conn,
            outcome_token_id,
            float(contracts),
            float(stake),
        )
        if not stack_ok:
            print(f"  [LIVE] katman/bakiye: {stack_msg}")
            return -1
        try:
            resp = lc.place_buy_limit(
                _CLOB_TRADING_CLIENT, outcome_token_id, entry_price, float(contracts)
            )
            if not lc.response_ok(resp):
                print(f"  [LIVE] BUY reddedildi: {resp}")
                return -1
            live_oid = str(resp.get("orderID") or resp.get("order_id") or "") or None
        except Exception as exc:
            print(f"  [LIVE] BUY hata: {exc}")
            return -1

    now = datetime.now(timezone.utc).isoformat()
    try:
        cur = conn.execute(
            """
        INSERT INTO positions
          (venue, market_id, question, side, entry_price, true_prob, edge,
           stake_usd, contracts, opened_at, rationale,
           outcome_token_id, neg_risk, tick_size, live_order_id, condition_id)
        VALUES ('polymarket',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            (
                market_id,
                question[:120],
                side,
                entry_price,
                true_prob,
                edge,
                round(stake, 4),
                round(contracts, 4),
                now,
                rationale,
                outcome_token_id,
                nr_val,
                tick_s,
                live_oid,
                (condition_id or None),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        print(f"  🚫 DUP-IDX market_id={market_id} (unique açık pozisyon)")
        return -2


def _commit_position_close(
    conn: sqlite3.Connection,
    pos_id: int,
    row: sqlite3.Row,
    close_price: float,
    resolved_yes: bool | None,
    exit_reason: str | None,
) -> float:
    side = row["side"]
    contracts = float(row["contracts"])
    stake = float(row["stake_usd"])
    entry_px = float(row["entry_price"])
    if resolved_yes is None:
        pnl = contracts * (close_price - entry_px)
        resolved_db = None
    else:
        won = (side == "YES" and resolved_yes) or (side == "NO" and not resolved_yes)
        pnl = contracts * (1.0 - entry_px) if won else -stake
        resolved_db = 1 if resolved_yes else 0
    reason_u = (exit_reason or "").upper()
    if resolved_yes is None and reason_u in ("SL", "STOP_LOSS"):
        sl_nominal = stake * STOP_LOSS_STAKE_PCT
        try:
            cat_pct = float(os.getenv("SL_CATASTROPHIC_PCT", "0.08"))
        except ValueError:
            cat_pct = 0.08
        sl_floor = -stake * cat_pct if cat_pct > 0 else pnl
        if pnl < -sl_nominal:
            pnl = -sl_nominal
        if pnl < sl_floor:
            pnl = sl_floor
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE positions
        SET closed_at=?, close_price=?, resolved_yes=?, pnl_usd=?, exit_reason=?
        WHERE id=? AND closed_at IS NULL
        """,
        (now, round(close_price, 4), resolved_db, round(pnl, 4), exit_reason, pos_id),
    )
    conn.commit()
    return pnl


def _scanner_heartbeat_path() -> Path:
    if POLYMARKET_LIVE_ARMED:
        return ROOT / "data" / "polymarket_scanner_live.heartbeat.json"
    return ROOT / "data" / "polymarket_scanner_paper.heartbeat.json"


def _write_scanner_heartbeat(conn: sqlite3.Connection, pos_cycle: int) -> None:
    try:
        from datetime import timezone as _tz

        from scanner_runtime import write_heartbeat_atomic

        open_n = open_position_count(conn)
        total_closed = conn.execute(
            "SELECT COUNT(*) n FROM positions WHERE closed_at IS NOT NULL"
        ).fetchone()["n"]
        total_pnl = conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) total FROM positions WHERE closed_at IS NOT NULL"
        ).fetchone()["total"]
        write_heartbeat_atomic(
            _scanner_heartbeat_path(),
            {
                "engine": "polymarket_scanner",
                "mode": "live" if POLYMARKET_LIVE_ARMED else "paper",
                "db": str(DB_PATH),
                "ts": datetime.now(_tz.utc).isoformat(),
                "pid": os.getpid(),
                "loop": pos_cycle,
                "live_armed": bool(POLYMARKET_LIVE_ARMED),
                "open_positions": int(open_n),
                "closed_trades": int(total_closed),
                "realized_pnl": round(float(total_pnl), 4),
            },
        )
    except Exception:
        pass


def close_position(
    conn: sqlite3.Connection,
    pos_id: int,
    close_price: float,
    resolved_yes: bool | None = None,
    exit_reason: str | None = None,
) -> float | None:
    """
    Pozisyonu kapat. Başarı → PnL; CLOB/DB hata → None (DB güncellenmez).

    POLYMARKET_LIVE_ARMED: erken çıkışta CLOB SELL; token bakiyesi 0 ise SYNC_SELL (zincirde yok).
    """
    global _CLOB_TRADING_CLIENT
    row = conn.execute(
        "SELECT side, entry_price, stake_usd, contracts, outcome_token_id "
        "FROM positions WHERE id=? AND closed_at IS NULL",
        (pos_id,),
    ).fetchone()
    if not row:
        return None

    contracts = float(row["contracts"])
    tok = row["outcome_token_id"]
    reason = exit_reason or "CLOSE"

    if (
        POLYMARKET_LIVE_ARMED
        and _CLOB_TRADING_CLIENT is not None
        and tok
        and resolved_yes is None
    ):
        import live_clob as lc

        bal = lc.get_conditional_balance(_CLOB_TRADING_CLIENT, str(tok))
        if bal is not None and bal < max(0.01, contracts * 0.02):
            pnl = _commit_position_close(
                conn, pos_id, row, close_price, None, "SYNC_SELL"
            )
            print(
                f"  [LIVE] SYNC_SELL #{pos_id} — CLOB bakiye={bal:.4f} "
                f"(zincirde yok), DB kapatıldı PnL=${pnl:+.2f}"
            )
            return pnl
        try:
            resp = lc.place_sell_exit(
                _CLOB_TRADING_CLIENT,
                str(tok),
                float(contracts),
                float(close_price),
            )
            if not lc.response_ok(resp):
                print(f"  [LIVE] SELL başarısız, DB güncellenmedi: {resp}")
                return None
        except Exception as exc:
            print(f"  [LIVE] SELL hata, DB güncellenmedi: {exc}")
            return None
    elif POLYMARKET_LIVE_ARMED and resolved_yes is not None:
        print(
            "  [LIVE] Çözülen market — PnL DB'ye yazıldı. "
            "Kazanan outcome token redeem için Polymarket arayüzünü kontrol edin."
        )

    return _commit_position_close(conn, pos_id, row, close_price, resolved_yes, reason)


def _effective_tp_stake_pct(hours_left: float | None, entry_edge: float) -> float:
    """
    Stake bazlı TP eşiği — uygulanan katmanların minimumu (en erken kilitleme).

    Canlı (LIVE_SIMPLE_EXIT): yalnızca TAKE_PROFIT_STAKE_PCT (ör. %2 stake).
    - Temel: TAKE_PROFIT_STAKE_PCT
    - Kapanışa ≤FAST_TP_MAX_HOURS: FAST_TP_STAKE_PCT ile sıkılaşır
    - ≤min(ULTRA_FAST_TP_MAX_HOURS, FAST_TP_MAX_HOURS): son saatlerde ULTRA_FAST_TP_STAKE_PCT
    - NANO_TP_MAX_HOURS > 0 ise: kapanışa o kadar saatten az kala NANO_TP_STAKE_PCT (ULTRA penceresi içinde)
    - |edge| ≥ QUICK_TP_EDGE_MIN (>0 ise): model yüksek güven → QUICK_TP_STAKE_PCT
      (QUICK_TP_EDGE_MIN ≤ 0 → bu katman kapalı)
    """
    if POLYMARKET_LIVE_ARMED and LIVE_SIMPLE_EXIT:
        return TAKE_PROFIT_STAKE_PCT
    tp = TAKE_PROFIT_STAKE_PCT
    e = abs(float(entry_edge or 0.0))
    if QUICK_TP_EDGE_MIN > 0.0 and e >= QUICK_TP_EDGE_MIN:
        tp = min(tp, QUICK_TP_STAKE_PCT)
    if hours_left is not None and 0 < hours_left <= FAST_TP_MAX_HOURS:
        tp = min(tp, FAST_TP_STAKE_PCT)
    ultra_cutoff = min(ULTRA_FAST_TP_MAX_HOURS, FAST_TP_MAX_HOURS)
    if hours_left is not None and 0 < hours_left <= ultra_cutoff:
        tp = min(tp, ULTRA_FAST_TP_STAKE_PCT)
    if NANO_TP_MAX_HOURS > 0.0:
        nano_cut = min(NANO_TP_MAX_HOURS, ultra_cutoff)
        if hours_left is not None and 0 < hours_left <= nano_cut:
            tp = min(tp, NANO_TP_STAKE_PCT)
    if _tp_drought_active():
        tp = min(tp, TP_DROUGHT_STAKE_PCT)
    return tp


# ═══════════════════════════════════════════════════════════════════════════════
#  Çözülen pozisyonları kapat
# ═══════════════════════════════════════════════════════════════════════════════

def check_and_close_positions(conn: sqlite3.Connection, client: httpx.Client) -> int:
    """
    Açık pozisyonları kontrol eder:
      1. Market tamamen çözüldüyse → binary P&L ile kapat
      2. TP: stake × _effective_tp_stake_pct × TP_TRIGGER_FRAC (1.0 = tam hedef; nano katmanı isteğe bağlı)
      3. SL: stake × STOP_LOSS_STAKE_PCT
      4. EXP / stale / max-hold kuralları
    CLOB midpoint ile fiyat — POSITION_CHECK aralığı kadar gecikmeli tetiklenir.
    """
    open_pos = conn.execute(
        "SELECT id, market_id, side, entry_price, contracts, stake_usd, question, "
        "opened_at, edge, true_prob FROM positions WHERE closed_at IS NULL"
    ).fetchall()
    closed_count = 0

    for pos in open_pos:
        try:
            m = _get_with_retry(client, f"{GAMMA}/markets/{pos['market_id']}")
            if not m or not isinstance(m, dict):
                continue

            prices = _parse_outcome_prices(m.get("outcomePrices"))
            if prices is None:
                continue
            yes_cur, _ = prices

            # CLOB midpoint kullan — Gamma outcomePrices 2-5¢ geride kalabilir
            # CLOB real-time → TP/SL tetiklemeleri daha doğru
            tokens = _parse_tokens(m.get("clobTokenIds"))
            if tokens:
                try:
                    clob_r = _get_with_retry(
                        client, f"{CLOB}/midpoint",
                        params={"token_id": tokens[0]}, timeout=5.0
                    )
                    if clob_r and "mid" in clob_r:
                        yes_cur = float(clob_r["mid"])
                except Exception:
                    pass  # Gamma fiyatıyla devam

            is_closed = m.get("closed", False) or m.get("resolved", False)

            # Kapanışa kalan süre (hızlı TP katmanı + EXP / stale için ortak)
            hours_left = None
            end_str = m.get("endDate") or m.get("closedTime")
            if end_str:
                try:
                    end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    hours_left = (end_dt.timestamp() - time.time()) / 3600.0
                except Exception:
                    pass

            # ── 1. Tam çözüm ────────────────────────────────────────────────
            if is_closed:
                if yes_cur > 0.95:
                    resolved_yes = True
                elif yes_cur < 0.05:
                    resolved_yes = False
                else:
                    continue  # Voided/draw — bekle
                close_price = yes_cur if pos["side"] == "YES" else (1.0 - yes_cur)
                pnl = close_position(conn, pos["id"], close_price, resolved_yes, exit_reason="RESOLVED")
                if pnl is None:
                    continue
                outcome_str = "YES ✓" if resolved_yes else "NO ✓"
                print(f"  ✓ [{pos['id']}] {outcome_str} PnL=${pnl:+.2f}  {pos['question'][:50]}")
                closed_count += 1
                continue

            # ── 2. Mark-to-market PnL hesapla ───────────────────────────────
            entry_price = pos["entry_price"]
            side        = pos["side"]
            contracts   = pos["contracts"]
            stake_usd   = pos["stake_usd"]
            cur_side_price = yes_cur if side == "YES" else (1.0 - yes_cur)
            price_delta    = cur_side_price - entry_price
            unrealized     = contracts * price_delta   # dolar P&L

            entry_edge = float(pos["edge"] or 0.0)
            if POLYMARKET_LIVE_ARMED and LIVE_SIMPLE_EXIT:
                tp_pct = TAKE_PROFIT_STAKE_PCT
                sl_pct = STOP_LOSS_STAKE_PCT
                trig = TP_TRIGGER_FRAC
            else:
                tp_pct = _effective_tp_stake_pct(hours_left, entry_edge)
                sl_pct = STOP_LOSS_STAKE_PCT
                trig = TP_TRIGGER_FRAC
            theme = _sports_theme(pos["question"] or "")
            if theme in ("sports_line", "sports_match", "esports") and SPORTS_EARLY_TP_DISCOUNT > 0:
                trig = max(0.88, trig - SPORTS_EARLY_TP_DISCOUNT)

            opened_at_str = pos["opened_at"]
            try:
                opened_dt = datetime.fromisoformat(str(opened_at_str).replace("Z", "+00:00"))
                if opened_dt.tzinfo is None:
                    opened_dt = opened_dt.replace(tzinfo=timezone.utc)
                pos_age_min = (time.time() - opened_dt.timestamp()) / 60.0
            except Exception:
                pos_age_min = 0.0
            pos_age_hours = pos_age_min / 60.0
            long_sports = _is_long_horizon_sports(hours_left, pos["question"] or "")

            hybrid_mode = "micro"
            hybrid_tag = ""
            if not (POLYMARKET_LIVE_ARMED and LIVE_SIMPLE_EXIT) and hybrid_tp.hybrid_enabled():
                true_p = float(pos["true_prob"] or entry_price)
                if side == "NO":
                    true_p = 1.0 - true_p
                vel = price_delta / max(pos_age_hours, 0.05)
                unreal_pct = unrealized / max(stake_usd, 1.0)
                spike = hybrid_tp.compute_spike_score(
                    entry_edge=entry_edge,
                    entry_price=entry_price,
                    side=side,
                    true_prob=true_p,
                    momentum=vel,
                    unrealized_pct=unreal_pct,
                    hours_left=hours_left,
                )
                plan = hybrid_tp.resolve_hybrid_tp(
                    tp_pct,
                    trig,
                    spike_score=spike,
                    drought=_tp_drought_active(),
                )
                tp_pct = plan.tp_stake_pct
                trig = plan.trigger_frac
                hybrid_mode = plan.mode
                hybrid_tag = f" [{plan.label}]"

            tp_target = stake_usd * tp_pct * trig
            sl_target = stake_usd * sl_pct

            if (
                not (POLYMARKET_LIVE_ARMED and LIVE_SIMPLE_EXIT)
                and hybrid_mode == "runner"
                and hybrid_tp.trail_should_exit(
                    mode=hybrid_mode,
                    tp_target_usd=tp_target,
                    unrealized=unrealized,
                    momentum=price_delta / max(pos_age_hours, 0.05),
                    side=side,
                )
            ):
                pnl = close_position(
                    conn, pos["id"], cur_side_price, None, exit_reason="TP_TRAIL"
                )
                if pnl is not None:
                    _note_tp_closed()
                    print(
                        f"  🏃 TP_TRAIL [{pos['id']}] {side}  "
                        f"PnL=${pnl:+.2f}{hybrid_tag}  {pos['question'][:40]}"
                    )
                    closed_count += 1
                    continue

            # ── 3a. Spor scratch TP (küçük yeşil, uzun bekleme) ─────────────
            if (
                not (POLYMARKET_LIVE_ARMED and LIVE_SIMPLE_EXIT)
                and _is_sports_question(pos["question"] or "")
                and pos_age_min >= TP_SCRATCH_MIN_AGE_MIN
                and unrealized >= stake_usd * TP_SCRATCH_MIN_PNL_PCT
            ):
                scratch_tgt = stake_usd * TP_SCRATCH_MIN_PNL_PCT * trig
                if unrealized >= scratch_tgt:
                    pnl = close_position(
                        conn, pos["id"], cur_side_price, None, exit_reason="TP_SCRATCH"
                    )
                    if pnl is not None:
                        _note_tp_closed()
                        print(
                            f"  💰 TP_SCRATCH [{pos['id']}] {side}  "
                            f"PnL=${pnl:+.2f}  {pos['question'][:40]}"
                        )
                        closed_count += 1
                        continue

            # ── 3. Take-Profit (stake yüzdesi — katmanlı sıkılaştırılmış) ──
            if unrealized >= tp_target:
                pnl = close_position(conn, pos["id"], cur_side_price, None, exit_reason="TP")
                if pnl is None:
                    print(
                        f"  ⚠ TP tetiklendi [{pos['id']}] ama kapanamadı — "
                        f"unreal=${unrealized:+.2f} hedef=${tp_target:.2f}  {pos['question'][:32]}"
                    )
                    continue
                _note_tp_closed()
                ret_pct = unrealized / stake_usd * 100
                eff_pct = tp_pct * trig
                print(
                    f"  💰 TP  [{pos['id']}] {side}  +{ret_pct:.1f}% stake "
                    f"(tp≈{eff_pct*100:.2f}% stake){hybrid_tag}  "
                    f"PnL=${pnl:+.2f}  {pos['question'][:40]}"
                )
                closed_count += 1
                continue

            # ── 3b. Uzun spor — durağan + küçük kâr → TP ────────────────────
            if (
                long_sports
                and pos_age_hours >= LONG_STALE_MIN_AGE_HOURS
                and abs(price_delta) < 0.01
                and unrealized >= stake_usd * STALE_LONG_TP_MIN_PNL_PCT
            ):
                pnl = close_position(
                    conn, pos["id"], cur_side_price, None, exit_reason="STALE_LONG_TP"
                )
                if pnl is not None:
                    _note_tp_closed()
                    print(
                        f"  💰 STALE_LONG_TP [{pos['id']}] {side}  "
                        f"PnL=${pnl:+.2f}  {pos['question'][:40]}"
                    )
                    closed_count += 1
                    continue

            # ── 3c. Uzun spor drift (erken kes, tam SL öncesi) ───────────────
            if (
                long_sports
                and pos_age_min >= SPORTS_DRIFT_MIN_AGE_MIN
                and unrealized <= -stake_usd * SPORTS_DRIFT_SL_PCT
            ):
                pnl = close_position(conn, pos["id"], cur_side_price, None, exit_reason="DRIFT")
                if pnl is not None:
                    print(
                        f"  📉 DRIFT [{pos['id']}] {side}  "
                        f"PnL=${pnl:+.2f}  {pos['question'][:40]}"
                    )
                    closed_count += 1
                    continue

            # ── 4. Stop-Loss (stake'in %5'i kadar kayıp) ─────────────────────
            if unrealized <= -sl_target:
                pnl = close_position(conn, pos["id"], cur_side_price, None, exit_reason="SL")
                if pnl is None:
                    print(
                        f"  ⚠ SL tetiklendi [{pos['id']}] ama kapanamadı — "
                        f"unreal=${unrealized:+.2f}  {pos['question'][:32]}"
                    )
                    continue
                ret_pct = unrealized / stake_usd * 100
                slip = abs(unrealized) - sl_target
                slip_note = f"  slip≈${slip:.3f}" if slip > 0.008 else ""
                print(
                    f"  ⛔ SL  [{pos['id']}] {side}  {ret_pct:.1f}% stake (hedef -{sl_pct*100:.1f}%)"
                    f"{slip_note}  entry={entry_price:.3f}→now={cur_side_price:.3f}  "
                    f"PnL=${pnl:+.2f}  {pos['question'][:40]}"
                )
                closed_count += 1
                continue

            # Canlı basit çıkış: yalnızca TP/SL + market çözümü
            if POLYMARKET_LIVE_ARMED and LIVE_SIMPLE_EXIT:
                pnl_sign = "+" if unrealized >= 0 else ""
                print(
                    f"  {'▲' if unrealized > 0 else '▼' if unrealized < 0 else '─'} "
                    f"[{pos['id']:>2}] {side}  stake=${stake_usd:.2f}  "
                    f"P&L={pnl_sign}{unrealized:.2f}$  "
                    f"TP +${tp_target:.2f} / SL -${sl_target:.2f}  {pos['question'][:32]}"
                )
                continue

            # ── 5. Zaman aşımı: 30 dk'dan az kaldı, fiyat hala belirsiz ─────
            if hours_left is not None and 0 < hours_left < 0.5 and 0.1 < yes_cur < 0.9:
                pnl = close_position(conn, pos["id"], cur_side_price, None, exit_reason="EXP")
                if pnl is None:
                    continue
                print(f"  ⏱ EXP [{pos['id']}] {side} {hours_left:.1f}h  "
                      f"PnL=${pnl:+.2f}  {pos['question'][:48]}")
                closed_count += 1
                continue

            # ── 6. Durağan market çıkışı ─────────────────────────────────────
            # Kısa vadeli market (≤6s kalan): STALE_MINUTES sonra aktivite yoksa kapat
            # Uzun vadeli spor: STALE_LONG (fiyat ±1¢, 2+ saat)
            if (
                long_sports
                and pos_age_hours >= LONG_STALE_MIN_AGE_HOURS
                and abs(price_delta) < 0.01
            ):
                pnl = close_position(
                    conn, pos["id"], cur_side_price, None, exit_reason="STALE_LONG"
                )
                if pnl is not None:
                    print(
                        f"  💤 STALE_LONG [{pos['id']}] {side}  "
                        f"{pos_age_hours:.1f}h açık  PnL=${pnl:+.2f}  {pos['question'][:40]}"
                    )
                    closed_count += 1
                    continue

            # Maksimum pozisyon tutma süresi: ne kadar beklenirse beklensin kapat
            if pos_age_hours >= MAX_HOLD_HOURS:
                pnl = close_position(conn, pos["id"], cur_side_price, None, exit_reason="MAX_HOLD")
                if pnl is None:
                    continue
                print(f"  ⏰ MAX-HOLD [{pos['id']}] {side}  "
                      f"{pos_age_hours:.1f}h açık (max={MAX_HOLD_HOURS:.0f}h)  "
                      f"PnL=${pnl:+.2f}  {pos['question'][:40]}")
                closed_count += 1
                continue

            stale_applicable = (hours_left is None or hours_left <= 6.0)
            if stale_applicable and pos_age_min >= STALE_MINUTES:
                tokens = _parse_tokens(m.get("clobTokenIds"))
                if tokens:
                    clob_data = _get_with_retry(
                        client, f"{CLOB}/prices-history",
                        params={"market": tokens[0], "interval": "1h"},
                        timeout=12.0,
                    )
                    cutoff = time.time() - 3600
                    pts_1h = len([
                        h for h in (clob_data or {}).get("history", [])
                        if h.get("t", 0) >= cutoff
                    ])
                    if pts_1h < STALE_MIN_PTS:
                        pnl = close_position(conn, pos["id"], cur_side_price, None, exit_reason="STALE")
                        if pnl is None:
                            continue
                        print(f"  💤 STALE [{pos['id']}] {side}  "
                              f"{pos_age_min:.0f}dk açık, son 1h={pts_1h} işlem  "
                              f"PnL=${pnl:+.2f}  {pos['question'][:40]}")
                        closed_count += 1
                        continue

            # ── 7. Durum logu (TP/SL tetiklenmediyse) ───────────────────────
            pnl_sign = "+" if unrealized >= 0 else ""
            delta = cur_side_price - entry_price
            if hours_left is not None:
                kalan = f"{hours_left:.1f}h" if hours_left < 24 else f"{hours_left/24:.1f}g"
            else:
                kalan = "?"
            indicator = "▲" if unrealized > 0.05 else ("▼" if unrealized < -0.05 else "─")
            print(f"  {indicator} [{pos['id']:>2}] {side:<3} "
                  f"giriş={entry_price:.3f}  şimdi={cur_side_price:.3f}  "
                  f"Δ={delta:+.3f}  P&L={pnl_sign}{unrealized:.2f}$  "
                  f"kalan={kalan}  {pos['question'][:40]}")

        except (httpx.TimeoutException, httpx.ConnectError):
            pass  # geçici ağ sorunu — sessizce atla, sonraki döngüde tekrar dene
        except Exception as exc:
            print(f"  [warn] close check {pos['market_id']}: {exc}")

    return closed_count


# ═══════════════════════════════════════════════════════════════════════════════
#  Market tarama
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_active_markets(client: httpx.Client, limit: int = 600) -> list[dict]:
    """
    Tüm kategorilerdeki aktif market'leri çeker.

    Strateji: her kategori için ilk 100 event'i volume24hr sırasıyla çek,
    içlerindeki TÜM marketleri topla (per-market limiti yok).
    Bu sayede düşük 24h hacimli ama yeni açılmış günlük marketler
    (örn. May 15 Bitcoin/ETH marketleri) gözden kaçmaz.
    MIN_VOLUME filtresi toplam hacim üzerinden uygulanır.
    """
    SCAN_TAGS = [
        "crypto", "politics", "sports", "financials", "science",
        "entertainment", "economics", "pop-culture", "technology", "world",
    ]

    out: list[dict] = []
    seen_ids: set[str] = set()

    for tag in SCAN_TAGS:
        try:
            events_batch = _get_with_retry(client, f"{GAMMA}/events", params={
                "active": "true", "closed": "false",
                "limit": 100, "tag_slug": tag,
                "order": "volume24hr", "ascending": "false",
            }, timeout=15.0)
        except httpx.HTTPError as exc:
            print(f"  [warn] fetch ({tag}): {exc}")
            continue

        if not events_batch:
            continue

        for ev in events_batch:
            for m in (ev.get("markets") or []):
                if not m.get("active") or m.get("closed"):
                    continue
                mid = str(m.get("id") or "")
                if not mid or mid in seen_ids:
                    continue
                seen_ids.add(mid)
                try:
                    v = float(m.get("volume") or 0)
                except (TypeError, ValueError):
                    v = 0.0
                if v < MIN_VOLUME:
                    continue
                out.append(m)

        time.sleep(0.05)

    if limit > 0:
        return out[:limit]
    return out


def already_positioned(conn: sqlite3.Connection, market_id: str, side: str) -> bool:
    row = conn.execute(
        "SELECT id FROM positions WHERE market_id=? AND side=? AND closed_at IS NULL",
        (market_id, side)
    ).fetchone()
    return row is not None


# ─── Katmanlı giriş (aynı market, küçük ek pozisyonlar) ─────────────────────
def _position_stack_enabled() -> bool:
    if POLYMARKET_LIVE_ARMED:
        return os.getenv("LIVE_ALLOW_STACK", "0").strip().lower() in ("1", "true", "yes")
    return os.getenv("PAPER_ALLOW_STACK", "0").strip().lower() in ("1", "true", "yes")


def _stack_max_per_market() -> int:
    return max(1, int(os.getenv("STACK_MAX_PER_MARKET", "3")))


def _stack_max_same_side() -> int:
    return max(1, int(os.getenv("STACK_MAX_SAME_SIDE", "2")))


def _stack_min_interval_sec() -> int:
    return max(0, int(os.getenv("STACK_MIN_INTERVAL_SEC", "180")))


def _stack_min_edge_gap() -> float:
    return float(os.getenv("STACK_MIN_EDGE_GAP", "0.012"))


def _stack_min_price_move() -> float:
    return float(os.getenv("STACK_MIN_PRICE_MOVE", "0.006"))


def _stack_stake_frac() -> float:
    return max(0.05, min(1.0, float(os.getenv("STACK_STAKE_FRAC", "0.40"))))


def _stack_layer_decay() -> float:
    return max(0.5, min(1.0, float(os.getenv("STACK_LAYER_DECAY", "0.85"))))


def _stack_max_stake_per_market_usd() -> float | None:
    raw = (os.getenv("STACK_MAX_STAKE_PER_MARKET_USD") or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except ValueError:
        return None


def _open_stack_count(
    conn: sqlite3.Connection, market_id: str, side: str | None = None
) -> int:
    if side:
        row = conn.execute(
            "SELECT COUNT(*) n FROM positions "
            "WHERE market_id=? AND side=? AND closed_at IS NULL",
            (market_id, side),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) n FROM positions "
            "WHERE market_id=? AND closed_at IS NULL",
            (market_id,),
        ).fetchone()
    return int(row["n"] if row else 0)


def _open_stake_on_market(conn: sqlite3.Connection, market_id: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(stake_usd), 0) t FROM positions "
        "WHERE market_id=? AND closed_at IS NULL",
        (market_id,),
    ).fetchone()
    return float(row["t"] or 0.0)


def _stack_stake_scale(conn: sqlite3.Connection, market_id: str, side: str) -> float:
    """İlk katman 1.0; sonrakiler STACK_STAKE_FRAC × decay^(katman-1)."""
    layer = _open_stack_count(conn, market_id, side)
    if layer <= 0:
        return 1.0
    return _stack_stake_frac() * (_stack_layer_decay() ** (layer - 1))


def _stack_allows_entry(
    conn: sqlite3.Connection,
    market_id: str,
    side: str,
    edge: float,
    entry_price: float,
) -> tuple[bool, str]:
    """Aynı market+side için ek katman açılabilir mi?"""
    if not _position_stack_enabled():
        return False, "stack_kapalı"
    total = _open_stack_count(conn, market_id)
    if total >= _stack_max_per_market():
        return False, "market_katman_dolu"
    same = _open_stack_count(conn, market_id, side)
    if same >= _stack_max_same_side():
        return False, "taraf_katman_dolu"
    if same == 0:
        return True, "ilk_katman"

    prev = conn.execute(
        """
        SELECT entry_price, edge, opened_at FROM positions
        WHERE market_id=? AND side=? AND closed_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (market_id, side),
    ).fetchone()
    if not prev:
        return True, "ilk_katman"

    min_iv = _stack_min_interval_sec()
    if min_iv > 0:
        try:
            opened_dt = datetime.fromisoformat(
                str(prev["opened_at"]).replace("Z", "+00:00")
            )
            if opened_dt.tzinfo is None:
                opened_dt = opened_dt.replace(tzinfo=timezone.utc)
            age_sec = time.time() - opened_dt.timestamp()
            if age_sec < min_iv:
                return False, f"bekle_{int(min_iv - age_sec)}sn"
        except Exception:
            pass

    prev_edge = float(prev["edge"] or 0.0)
    prev_px = float(prev["entry_price"] or 0.0)
    edge_ok = edge >= prev_edge + _stack_min_edge_gap()
    if side == "YES":
        price_ok = entry_price <= prev_px - _stack_min_price_move()
    else:
        price_ok = entry_price <= prev_px - _stack_min_price_move()
    if not (edge_ok or price_ok):
        return False, "edge/fiyat_iyileşmedi"
    return True, "katman_ok"


def is_on_cooldown(conn: sqlite3.Connection, market_id: str, side: str) -> tuple[bool, int]:
    """
    Market için SL/kayıp cooldown aktif mi? (her iki taraf birlikte kontrol edilir)
    Kök neden: NO → SL → YES girişi cooldown'u bypass ediyordu.
    Düzeltme: side parametresi artık yoksayılır, market_id bazlı kontrol yapılır.
    """
    cutoff_iso = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() - SL_COOLDOWN_MIN * 60,
        tz=timezone.utc
    ).isoformat()
    row = conn.execute("""
        SELECT id FROM positions
        WHERE market_id = ?
          AND closed_at > ?
          AND pnl_usd   < 0
        ORDER BY closed_at DESC
        LIMIT 1
    """, (market_id, cutoff_iso)).fetchone()
    if row:
        return True, row["id"]
    return False, -1


def _daily_entry_count(conn: sqlite3.Connection, market_id: str) -> int:
    """Bu market'e bugün kaç kez giriş yapıldı? (açık + kapalı)"""
    from datetime import date
    today = date.today().isoformat()
    row = conn.execute("""
        SELECT COUNT(*) n FROM positions
        WHERE market_id = ?
          AND DATE(opened_at) = ?
    """, (market_id, today)).fetchone()
    return row["n"] if row else 0


def _market_daily_limit(conn: sqlite3.Connection, market_id: str) -> int:
    """
    Market'in geçmiş performansına göre günlük max giriş sayısını belirler.

    - Geçmişte çoğunlukla kazanan (win ≥ 65%, n ≥ 3): 5 giriş/gün
    - Geçmişte karışık (win 40-65%, n ≥ 3): 3 giriş/gün
    - Yeni market (n < 3): 2 giriş/gün (henüz kanıtlamamış)
    - Kötü geçmiş (win < 40%, n ≥ 3): 1 giriş/gün (temkinli)
    """
    row = conn.execute("""
        SELECT COUNT(*) n,
               SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) wins
        FROM positions
        WHERE market_id = ? AND closed_at IS NOT NULL AND """ + PNL_NONZERO_SQL + """
    """, (market_id,)).fetchone()
    n = row["n"] if row else 0
    wins = row["wins"] if row and row["wins"] else 0

    if n < 3:
        return 2  # Yeterli geçmiş yok → muhafazakâr

    wr = wins / n
    if wr >= 0.65:
        base = 5  # Kanıtlanmış iyi market → daha fazla giriş izni
    elif wr >= 0.40:
        base = 3  # Orta performans → biraz daha izin
    else:
        base = 1  # Kötü geçmiş → çok temkinli

    if _position_stack_enabled():
        mult = max(1, int(os.getenv("STACK_DAILY_LIMIT_MULT", "2")))
        cap = max(_stack_max_per_market() * 3, 6)
        return min(cap, base * mult)
    return base


def open_position_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) n FROM positions WHERE closed_at IS NULL"
    ).fetchone()
    return row["n"]


def open_stake_total(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(stake_usd), 0) t FROM positions WHERE closed_at IS NULL"
    ).fetchone()
    return float(row["t"] or 0.0)


def _paper_max_open_stake_usd() -> float | None:
    """Açık pozisyonların toplam stake üst sınırı (ör. bakiyenin %35'i)."""
    raw = (os.getenv("PAPER_MAX_OPEN_STAKE_PCT") or "").strip()
    if not raw:
        return None
    try:
        pct = float(raw)
        if pct <= 0:
            return None
        return STARTING_BALANCE * pct
    except ValueError:
        return None


def can_add_open_stake(conn: sqlite3.Connection, additional_stake: float) -> bool:
    cap = _paper_max_open_stake_usd()
    if cap is None:
        return True
    return open_stake_total(conn) + float(additional_stake) <= cap + 0.02


def _swap_quality_open(edge: float) -> float:
    """Açık pozisyonu tutma önceliği — yüksek edge daha değerli (silinmez)."""
    return float(edge) * 4.0


def _swap_quality_candidate(
    edge: float, entry_score_val: int, momentum: float | None
) -> float:
    """Yeni giriş kalitesi — edge + skor + hafif momentum teyidi."""
    mom = abs(momentum) if momentum is not None else 0.0
    mom_term = min(mom, 0.04) * 2.5
    return float(edge) * 4.0 + 0.15 * float(entry_score_val) + mom_term


def _current_side_mid_price(
    client: httpx.Client, market_id: str, side: str
) -> float | None:
    """Kapama için taraf fiyatı (YES fiyatı veya NO tarafı 1-yes)."""
    m = _get_with_retry(client, f"{GAMMA}/markets/{market_id}", timeout=10.0)
    if not m or not isinstance(m, dict):
        return None
    prices = _parse_outcome_prices(m.get("outcomePrices"))
    if prices is None:
        return None
    yes_cur, _ = prices
    tokens = _parse_tokens(m.get("clobTokenIds"))
    if tokens:
        try:
            clob_r = _get_with_retry(
                client, f"{CLOB}/midpoint",
                params={"token_id": tokens[0]}, timeout=5.0
            )
            if clob_r and "mid" in clob_r:
                yes_cur = float(clob_r["mid"])
        except Exception:
            pass
    cur_side = yes_cur if side == "YES" else (1.0 - yes_cur)
    if not (0.0 < cur_side < 1.0):
        return None
    return cur_side


def _try_free_slot_via_swap(
    conn: sqlite3.Connection,
    client: httpx.Client,
    new_edge: float,
    new_score: int,
    new_momentum: float | None,
    new_market_id: str,
    new_question: str,
) -> bool:
    """
    Limit doluysa: yeni fırsat bir açık pozisyondan belirgin şekilde iyiyse
    o pozisyonu mark-to-mid kapatır ve bir slot açar.
    Breakeven (~$0) kapanış üretecek pozisyonlar swap için kapatılmaz.
    SWAP_COOLDOWN_SEC: ardışık swap’lar arası minimum süre (sık churn önlenir).
    """
    global _swap_cooldown_until
    if open_position_count(conn) < MAX_OPEN_POSITIONS:
        return True
    now_m = time.monotonic()
    if SWAP_COOLDOWN_SEC > 0 and now_m < _swap_cooldown_until:
        return False
    rows = conn.execute(
        """
        SELECT id, market_id, side, edge, entry_price, contracts
        FROM positions
        WHERE closed_at IS NULL
        ORDER BY edge ASC, opened_at ASC, id ASC
        LIMIT 25
        """
    ).fetchall()
    cand_q = _swap_quality_candidate(new_edge, new_score, new_momentum)
    for worst in rows:
        if str(worst["market_id"]) == str(new_market_id):
            continue
        open_q = _swap_quality_open(float(worst["edge"]))
        if cand_q <= open_q + SWAP_MIN_QUALITY_GAP:
            continue
        px = _current_side_mid_price(client, str(worst["market_id"]), str(worst["side"]))
        if px is None:
            continue
        try:
            contracts = float(worst["contracts"])
            entry = float(worst["entry_price"])
        except (TypeError, ValueError):
            continue
        est_pnl = contracts * (px - entry)
        if abs(est_pnl) <= PNL_NEAR_ZERO_USD:
            continue
        pnl = close_position(conn, int(worst["id"]), px, None, exit_reason="SWAP")
        if pnl is None:
            return False
        if SWAP_COOLDOWN_SEC > 0:
            _swap_cooldown_until = time.monotonic() + float(SWAP_COOLDOWN_SEC)
        print(
            f"  🔁 SWAP #{worst['id']} kapatıldı PnL=${pnl:+.2f} edge={float(worst['edge']):.3f}  "
            f"→ yer: edge={new_edge:.3f} skor={new_score}  {new_question[:40]}"
        )
        return True
    return False


@dataclass
class LiveScanFunnel:
    """Canlı tarama hunisi — kaç aday geçti / neden elendi."""

    total: int = 0
    signals: int = 0
    pre_veto: int = 0
    final_pool: int = 0
    opened: int = 0
    rejects: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def reject(self, reason: str) -> None:
        self.rejects[reason] += 1

    def print_summary(self) -> None:
        prof = _live_entry_profile() if POLYMARKET_LIVE_ARMED else "paper"
        print(f"  📊 CANLI HUNİ ({prof})")
        print(
            f"     Taranan: {self.total}  |  Kalibrasyon sinyali: {self.signals}"
            f"  |  Veto öncesi: {self.pre_veto}  |  Son havuz: {self.final_pool}"
            f"  |  Açılan: {self.opened}"
        )
        if not self.rejects:
            print("     Elendi: (sinyal yok — edge bandı / zaman penceresi)")
            return
        top = sorted(self.rejects.items(), key=lambda x: -x[1])[:12]
        print("     Elendi (üst nedenler):")
        for key, n in top:
            print(f"       · {key}: {n}")


def _live_funnel_enabled() -> bool:
    if not POLYMARKET_LIVE_ARMED:
        return False
    return os.getenv("LIVE_SCAN_FUNNEL", "1").strip().lower() in ("1", "true", "yes")


def _live_entry_profile() -> str:
    return os.getenv("LIVE_ENTRY_PROFILE", "strict").strip().lower()


def _live_mirror_paper() -> bool:
    """Paper ile aynı giriş mantığı; yalnızca CLOB min-pay + gerçek emir eklenir."""
    return POLYMARKET_LIVE_ARMED and _live_entry_profile() in (
        "mirror",
        "paper",
        "paper_like",
    )


def _live_max_entry_price(min_sh: float = 5.0) -> float:
    """5 pay × fiyat ≤ MAX_POS_USD. LIVE_MAX_ENTRY_PRICE=0 → yalnızca bu kural."""
    dyn = MAX_POS_USD / max(float(min_sh), 1.0)
    cap = float(os.getenv("LIVE_MAX_ENTRY_PRICE", "0"))
    if cap > 0:
        return min(cap, dyn)
    return dyn


def _live_min_stake_usd() -> float:
    if _live_mirror_paper():
        return float(os.getenv("LIVE_MIN_STAKE_USD", "0.85"))
    return 1.0


def _paper_min_stake_usd() -> float:
    try:
        return float(os.getenv("PAPER_MIN_POSITION_USD", "500"))
    except ValueError:
        return 500.0


def _paper_target_stake_usd() -> float:
    """>0 ise her paper girişi bu tutara yakın (max/cap ile sınırlı)."""
    try:
        return float(os.getenv("PAPER_TARGET_STAKE_USD", "0"))
    except ValueError:
        return 0.0


def _finalize_paper_stake(
    kelly: float, yes_price: float | None
) -> float:
    """
    Paper stake: küçük pozisyon yok.
    PAPER_TARGET_STAKE_USD=1000 → Kelly>0 ise ~$1000 (GAP/MAX ile sınırlı).
    Aksi halde Kelly, en az PAPER_MIN_POSITION_USD.
    """
    if kelly <= 0:
        return 0.0
    cap = _gap_stake_cap(yes_price) if yes_price is not None else MAX_POS_USD
    target = _paper_target_stake_usd()
    if target > 0:
        return min(target, cap, MAX_POS_USD)
    min_s = _paper_min_stake_usd()
    if kelly < min_s:
        return 0.0
    return min(kelly, cap, MAX_POS_USD)


def scan_markets(
    conn: sqlite3.Connection,
    client: httpx.Client,
    *,
    markets: list[dict] | None = None,
) -> int:
    """Aktif market'leri tarar, uygun olanlara pozisyon açar (limit doluysa SWAP ile yer açılabilir)."""
    if markets is None:
        markets = fetch_active_markets(client)
        print(f"  [scan] {len(markets)} aktif market tarandı (vol>${MIN_VOLUME:,.0f})")
    else:
        print(f"  [scan] {len(markets)} market (senkron çoklu paper)")

    funnel: LiveScanFunnel | None = LiveScanFunnel() if _live_funnel_enabled() else None
    opened = 0
    opened_this_scan: set[str] = set()
    for m in markets:
        if funnel is not None:
            funnel.total += 1
        # ── YES fiyatını belirle ─────────────────────────────────────────────
        op = _parse_outcome_prices(m.get("outcomePrices"))
        if op is None:
            continue
        yes_price, _ = op
        gamma_yes = yes_price

        # ── Token ID ─────────────────────────────────────────────────────────
        tokens = _parse_tokens(m.get("clobTokenIds"))
        if not tokens:
            continue
        yes_token = tokens[0]

        yes_price, used_mid = _apply_clob_midpoint_yes_price(client, yes_token, yes_price)
        if not (0.35 <= yes_price <= 0.92):
            if funnel is not None:
                funnel.reject("fiyat_bandı")
            continue  # Edge zone dışı — calibration edge küçük

        # ── End date filtresi ────────────────────────────────────────────────
        end_str = m.get("endDate") or m.get("closedTime")
        if not end_str:
            continue
        try:
            end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            hours_left = (end_dt.timestamp() - time.time()) / 3600.0
        except Exception:
            continue
        if hours_left < MIN_HOURS_TO_CLOSE or hours_left > MAX_HOURS_TO_CLOSE:
            if funnel is not None:
                funnel.reject("zaman_penceresi")
            continue

        # ── Market kimliği ve sorusu ─────────────────────────────────────────
        market_id = str(m.get("id") or m.get("conditionId") or "")
        if not market_id:
            continue
        condition_id = _normalize_condition_id(m)
        question = m.get("question") or m.get("description") or market_id

        if _veto_sports_totals(hours_left, question):
            if funnel is not None:
                funnel.reject("veto_sports_totals")
            print(f"  🚫 STOT canlı O/U totals ≤{os.getenv('VETO_SPORTS_TOTALS_MAX_HOURS', '12')}h: {question[:55]}")
            continue

        try:
            entry_slip_max = float(os.getenv("ENTRY_CLOB_MAX_SLIPPAGE", "0.03"))
        except ValueError:
            entry_slip_max = 0.03
        if used_mid and entry_slip_max > 0 and abs(yes_price - gamma_yes) > entry_slip_max:
            if funnel is not None:
                funnel.reject("clob_slip")
            print(
                f"  🚫 SLIP Gamma/CLOB {abs(yes_price - gamma_yes):.3f}>{entry_slip_max:.3f}  "
                f"{question[:55]}"
            )
            continue

        # ── Kalibrasyon sinyali ──────────────────────────────────────────────
        sig = signal_for_price(yes_price)
        if sig is None:
            if funnel is not None:
                funnel.reject("kalibrasyon_sinyal_yok")
            continue
        side, entry_price, edge = sig
        if funnel is not None:
            funnel.signals += 1
        _th_boost = THEME_EDGE_BOOST.get(self_improver._position_theme_bucket(question), 0.0)
        if _th_boost > 0 and edge < EDGE_THRESHOLD + _th_boost:
            if funnel is not None:
                funnel.reject("edge_eşik")
            continue

        # ── Duplicate + cooldown + günlük limit kontrolü ───────────────────
        stack_ok, stack_note = _stack_allows_entry(
            conn, market_id, side, edge, entry_price
        )
        if already_positioned(conn, market_id, side):
            if not stack_ok:
                if funnel is not None:
                    funnel.reject("zaten_pozisyon")
                continue
        on_cd, cd_pos = is_on_cooldown(conn, market_id, side)
        if on_cd:
            if funnel is not None:
                funnel.reject("sl_cooldown")
            print(f"  🚫 CD   #{cd_pos} SL'den {SL_COOLDOWN_MIN}dk cooldown  {question[:55]}")
            continue
        # Günlük giriş limiti: geçmiş performansa göre dinamik
        daily_entries = _daily_entry_count(conn, market_id)
        daily_limit = _market_daily_limit(conn, market_id)
        if daily_entries >= daily_limit:
            if funnel is not None:
                funnel.reject("gunluk_limit")
            print(f"  🚫 DAY  Bugün {daily_entries}/{daily_limit}x giriş (limit={daily_limit})  {question[:55]}")
            continue

        # ── Giriş sinyalleri: momentum + spread + last-trade ─────────────────
        momentum, is_active, spread, last_trade = fetch_entry_signals(client, yes_token)
        time.sleep(0.1)

        # Aktivite kontrolü: kısa vadeli marketlerde zorunlu, uzun vadelide esnek
        # < 6s kalan: son 1s aktivite şart (stale market olabilir)
        # > 6s kalan: long-duration market → son işlem fiyatı yeterliyse girilebilir
        if not is_active:
            if hours_left <= 6.0:
                if funnel is not None:
                    funnel.reject("stale_aktivite")
                continue  # Kısa vadeli stale market → geç
            elif last_trade is None:
                if funnel is not None:
                    funnel.reject("islem_yok")
                continue  # Uzun vadeli ama hiç işlem yok → geç

        # Spread filtresi: likit olmayan markete girme
        if spread > MAX_SPREAD:
            if funnel is not None:
                funnel.reject("spread_geniş")
            continue

        # Last-trade fiyat teyidi: kısa vadeli marketlerde (≤6s) zorunlu, uzun vadeli geçer
        # Uzun vadeli marketlerde son işlem günler önce olabilir → fark büyük ama geçerli
        if last_trade is not None and hours_left <= 6.0:
            expected_side_price = last_trade if side == "YES" else (1.0 - last_trade)
            if abs(expected_side_price - entry_price) > 0.05:
                if funnel is not None:
                    funnel.reject("son_islem_fiyat")
                continue

        # Sıfır mom: düz çizgi fiyat → kapanışa ZERO_MOM_SKIP_MAX_HOURS içindeyse atla
        mom_abs: float | None = None
        if momentum is not None:
            mom_abs = abs(float(momentum))
        if hours_left <= ZERO_MOM_SKIP_MAX_HOURS and mom_abs is not None and mom_abs < 0.002:
            allow_flat = _live_mirror_paper() and os.getenv(
                "LIVE_MIRROR_ALLOW_FLAT_MOM", "1"
            ).strip().lower() in ("1", "true", "yes")
            if not allow_flat:
                if funnel is not None:
                    funnel.reject("sıfır_momentum")
                continue
        # CLOB eğimi yok: yalnızca çok yakın vadede atla (None'ı 48s boyunca bloklamaz)
        if (
            ZERO_MOM_NONE_MAX_HOURS > 0
            and hours_left <= ZERO_MOM_NONE_MAX_HOURS
            and momentum is None
        ):
            if funnel is not None:
                funnel.reject("momentum_veri_yok")
            continue

        if momentum is not None:
            if side == "NO" and momentum > MOMENTUM_VETO:
                if funnel is not None:
                    funnel.reject("momentum_veto")
                continue
            if side == "YES" and momentum < -MOMENTUM_VETO:
                if funnel is not None:
                    funnel.reject("momentum_veto")
                continue
            if yes_price >= 0.70 and abs(momentum) > HIGH_MOM_GAP_VETO:
                if funnel is not None:
                    funnel.reject("yüksek_fiyat_mom")
                continue
            # Aşırı yüksek momentum = maç canlı oynanıyor → gap riski, her fiyatta veto
            if abs(momentum) > LIVE_EVENT_MOM_VETO:
                if funnel is not None:
                    funnel.reject("canlı_event_mom")
                continue

        # ── Çok sinyalli giriş skoru ─────────────────────────────────────────
        # Minimum 1 puan: yüksek edge tek başına yeterliyse gir,
        # düşük edge'de en az 1 destekleyici faktör gereksin.
        score = entry_score(edge, momentum, spread, yes_price, hours_left)
        min_score = max(0, int(os.getenv("PAPER_MIN_ENTRY_SCORE", "1")))
        if POLYMARKET_LIVE_ARMED and not _live_mirror_paper():
            min_score = max(1, int(os.getenv("LIVE_MIN_SCORE", "2")))
            min_edge = float(os.getenv("LIVE_MIN_EDGE", "0"))
            if min_edge > 0 and edge < min_edge:
                if funnel is not None:
                    funnel.reject("live_min_edge")
                continue
        if score < min_score:
            if funnel is not None:
                funnel.reject("skor_düşük")
            print(f"  🔵 SKOR  {score}puan (edge={edge:.2f} mom={momentum} sprd={spread:.3f}) skip  {question[:50]}")
            continue

        # ── Gerçek olasılık ve Kelly ─────────────────────────────────────────
        bi = min(9, int(yes_price * 10))
        cal_yes, _ = CALIBRATION[bi]
        true_prob = cal_yes if side == "YES" else (1.0 - cal_yes)

        kelly = kelly_stake(true_prob, entry_price, yes_price=yes_price)
        if POLYMARKET_LIVE_ARMED:
            stake = kelly
            min_stake = _live_min_stake_usd()
            if stake < min_stake:
                if _live_mirror_paper() and stake > 0:
                    stake = min(max(min_stake, stake), MAX_POS_USD)
                else:
                    if funnel is not None:
                        funnel.reject("stake_küçük")
                    continue
        else:
            stake = _finalize_paper_stake(kelly, yes_price)
            if _position_stack_enabled() and _open_stack_count(conn, market_id, side) > 0:
                stake *= _stack_stake_scale(conn, market_id, side)
            if stake <= 0:
                if funnel is not None:
                    funnel.reject("stake_küçük")
                continue
            mkt_cap = _stack_max_stake_per_market_usd()
            if mkt_cap is not None:
                room = mkt_cap - _open_stake_on_market(conn, market_id)
                if room < 1.0:
                    if funnel is not None:
                        funnel.reject("market_stake_tavanı")
                    continue
                stake = min(stake, room)
            if not can_add_open_stake(conn, stake):
                if funnel is not None:
                    funnel.reject("açık_stake_limiti")
                continue

        if POLYMARKET_LIVE_ARMED:
            min_sh = float(os.getenv("POLYMARKET_MIN_ORDER_SIZE", "5"))
            min_cost = min_sh * entry_price
            max_px = _live_max_entry_price(min_sh)
            if min_cost > MAX_POS_USD + 0.02:
                if funnel is not None:
                    funnel.reject("clob_min_pay")
                continue
            if entry_price > max_px + 1e-6:
                if funnel is not None:
                    funnel.reject("giriş_fiyatı_yüksek")
                continue
            if not _live_mirror_paper():
                quick_h = float(os.getenv("LIVE_QUICK_TP_MAX_HOURS", "0"))
                if quick_h > 0 and hours_left is not None and hours_left > quick_h:
                    if funnel is not None:
                        funnel.reject("kapanış_uzun")
                    continue
                if os.getenv("LIVE_REQUIRE_MOMENTUM", "1").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                ):
                    if momentum is None:
                        if funnel is not None:
                            funnel.reject("live_momentum_yok")
                        continue
                    mom_min = float(os.getenv("LIVE_MOMENTUM_MIN", "0.004"))
                    if side == "YES" and momentum < mom_min:
                        if funnel is not None:
                            funnel.reject("live_momentum_yön")
                        continue
                    if side == "NO" and momentum > -mom_min:
                        if funnel is not None:
                            funnel.reject("live_momentum_yön")
                        continue

        if funnel is not None:
            funnel.pre_veto += 1

        # ── Rationale ────────────────────────────────────────────────────────
        mom_str = f"{momentum:+.4f}" if momentum is not None else "n/a"
        lt_str  = f"{last_trade:.3f}" if last_trade is not None else "n/a"
        rationale = (
            f"Cal bucket {bi/10:.1f}-{(bi+1)/10:.1f}: "
            f"true_YES={cal_yes:.3f} bias={CALIBRATION[bi][1]:+.3f} | "
            f"momentum={mom_str} | spread={spread:.3f} | last_trade={lt_str} | "
            f"edge={edge:+.3f} | hours_left={hours_left:.1f}h"
        )

        # ── Shadow kayıt: sinyal üretilen her marketi eğitim için sakla ─────
        # Giriş yapılıp yapılmadığından bağımsız — sonuç belli olunca öğrenir.
        try:
            backtest_trainer.init_shadow_db(conn)
            backtest_trainer.record_observation(
                conn, market_id, question, yes_price,
                signal_side=side, signal_edge=edge,
                end_date=str(m.get("endDate") or m.get("endDateIso") or ""),
            )
        except Exception:
            pass

        # ── Single-game market yasağı ────────────────────────────────────────
        if _is_single_game_market(question):
            if funnel is not None:
                funnel.reject("veto_tek_oyun")
            continue

        # ── Canlı konuşma/toplantı tahmin yasağı ────────────────────────────
        # "Will X say Y during meeting?" → fiyat 0/1'e saniyeler içinde atlıyor
        if _is_live_speech_market(question):
            if funnel is not None:
                funnel.reject("veto_konuşma")
            print(f"  🚫 SPCH Canlı event konuşma tahmini, atla: {question[:55]}")
            continue

        if VETO_VOLATILE_NARRATIVE and _is_volatile_narrative_market(question):
            if funnel is not None:
                funnel.reject("veto_anlatı")
            print(f"  🚫 NRVT anlatı/haber (yüksek gürültü), atla: {question[:55]}")
            continue

        if VETO_EUROVISION_RANKING and _is_eurovision_ranking_market(question):
            if funnel is not None:
                funnel.reject("veto_eurovision")
            print(f"  🚫 EURO Eurovision sıralama/televote (SL yoğun), atla: {question[:55]}")
            continue

        if VETO_DAILY_UP_OR_DOWN and _is_daily_up_or_down_market(question):
            if funnel is not None:
                funnel.reject("veto_up_down")
            print(f"  🚫 UPDN günlük Up/Down (whipsaw), atla: {question[:55]}")
            continue

        if POLYMARKET_LIVE_ARMED:
            if os.getenv("VETO_LIVE_CRYPTO_STRIKE", "1").strip().lower() in (
                "1",
                "true",
                "yes",
            ) and _is_crypto_strike_market(question):
                if funnel is not None:
                    funnel.reject("veto_crypto")
                print(f"  🚫 LCRY canlı crypto strike (whipsaw), atla: {question[:55]}")
                continue
            if os.getenv("VETO_LIVE_ESPORTS_OUTRIGHT", "1").strip().lower() in (
                "1",
                "true",
                "yes",
            ) and _is_esports_outright_market(question):
                if funnel is not None:
                    funnel.reject("veto_esports")
                print(f"  🚫 LESP canlı esports outright, atla: {question[:55]}")
                continue

        if funnel is not None:
            funnel.final_pool += 1

        # ── Duplicate guard: aynı market_id (katman kapalıysa tek pozisyon) ───
        any_open = conn.execute(
            "SELECT id FROM positions WHERE market_id=? AND closed_at IS NULL LIMIT 1",
            (market_id,)
        ).fetchone()
        if any_open and not stack_ok:
            if funnel is not None:
                funnel.reject("market_zaten_açık")
            continue

        # ── Korelasyon engeli: aynı varlık + tarihte başka pozisyon varsa atla ──
        # Örn: BTC May 14 → $78k-$80k YESten sonra $80k-$82k NO açmasın
        corr_ex = market_id if _position_stack_enabled() and stack_ok else None
        if _is_correlated_position(conn, question, exclude_market_id=corr_ex):
            if funnel is not None:
                funnel.reject("korelasyon")
            continue
        if _same_event_open(conn, question):
            if funnel is not None:
                funnel.reject("aynı_event")
            print(f"  🚫 EVENT aynı maçta açık pozisyon var: {question[:55]}")
            continue

        if _market_reopen_blocked(conn, market_id):
            if funnel is not None:
                funnel.reject("market_yeniden_giriş")
            continue

        if market_id in opened_this_scan:
            if funnel is not None:
                funnel.reject("bu_taramada_rezerve")
            continue

        if (
            _is_long_horizon_sports(hours_left, question)
            and _long_sports_open_count(conn) >= LONG_SPORTS_MAX_OPEN
        ):
            if funnel is not None:
                funnel.reject("long_sports_limit")
            print(f"  🚫 LONG_SPORTS max {LONG_SPORTS_MAX_OPEN}: {question[:55]}")
            continue
        # Aynı sorudan (farklı market_id) — katmanlı girişte aynı market_id serbest
        if not (_position_stack_enabled() and stack_ok and _open_stack_count(conn, market_id) > 0):
            q_prefix = question[:50]
            dup_q = conn.execute(
                "SELECT id FROM positions WHERE question LIKE ? AND closed_at IS NULL LIMIT 1",
                (q_prefix + "%",)
            ).fetchone()
            if dup_q:
                if funnel is not None:
                    funnel.reject("benzer_soru")
                continue

        if POLYMARKET_LIVE_ARMED and os.getenv("LIVE_DISABLE_SWAP", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            if open_position_count(conn) >= MAX_OPEN_POSITIONS:
                if funnel is not None:
                    funnel.reject("slot_dolu")
                continue
        elif not _try_free_slot_via_swap(
            conn, client, edge, score, momentum, market_id, question
        ):
            continue

        out_tid = yes_token if side == "YES" else (tokens[1] if len(tokens) > 1 else yes_token)
        opened_this_scan.add(market_id)
        pos_id = open_position(
            conn, market_id, question, side, entry_price, true_prob, edge, rationale,
            outcome_token_id=out_tid,
            yes_price=yes_price,
            stake_usd=stake if not POLYMARKET_LIVE_ARMED else None,
            condition_id=condition_id or None,
        )
        if pos_id <= 0 and pos_id != -2:
            opened_this_scan.discard(market_id)
        if pos_id > 0:
            cap = _gap_stake_cap(yes_price)
            cap_tag = f" [gap cap ${cap:.0f}]" if stake >= cap - 0.01 else ""
            mid_tag = (
                f" mid={yes_price:.3f}"
                if used_mid and abs(yes_price - gamma_yes) > 0.002
                else ""
            )
            layer_n = _open_stack_count(conn, market_id, side)
            stack_tag = (
                f" [katman {layer_n}/{_stack_max_same_side()}]"
                if _position_stack_enabled() and layer_n > 1
                else ""
            )
            if stack_note not in ("ilk_katman", "stack_kapalı") and layer_n > 1:
                stack_tag = f"{stack_tag} ({stack_note})"
            print(f"  ➕ [{pos_id}] {side:3s} @{entry_price:.3f}  "
                  f"edge={edge:+.3f}  mom={mom_str}  "
                  f"stake=${stake:.1f}{cap_tag}{mid_tag}{stack_tag}  {question[:50]}")
            opened += 1
        elif funnel is not None:
            funnel.reject("clob_emir_hata")

    if funnel is not None:
        funnel.opened = opened
        funnel.print_summary()

    return opened


# ═══════════════════════════════════════════════════════════════════════════════
#  Ana döngü
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

    if POLYMARKET_LIVE_ARMED:
        _reload_live_env_globals()

    try:
        from scanner_runtime import singleton_process_lock
    except ImportError:

        def singleton_process_lock(_path: Path):  # type: ignore[misc]
            return contextlib.nullcontext()

    lock = singleton_process_lock(
        SCANNER_LOCK if POLYMARKET_LIVE_ARMED else PAPER_SCANNER_LOCK
    )
    try:
        with lock:
            _run_scanner_main()
    except RuntimeError as exc:
        print(exc)
        sys.exit(1)


def _run_scanner_main() -> None:
    global CALIBRATION, MOMENTUM_VETO, EDGE_THRESHOLD, THEME_EDGE_BOOST, _CLOB_TRADING_CLIENT
    global STARTING_BALANCE
    _reload_paper_env_globals()
    if not POLYMARKET_LIVE_ARMED:
        try:
            pid_path = ROOT / "data" / "paper_scanner.pid"
            pid_path.parent.mkdir(parents=True, exist_ok=True)
            pid_path.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass
    conn = init_db(DB_PATH)
    client = httpx.Client(
        timeout=20.0,
        headers={"User-Agent": "predmarket-momentum/0.1", "Accept": "application/json"},
    )

    if POLYMARKET_LIVE_ARMED:
        import live_clob as lc

        _CLOB_TRADING_CLIENT = lc.build_trading_client()
        if _CLOB_TRADING_CLIENT is None:
            print(
                "[LIVE] CLOB istemcisi oluşturulamadı. "
                "POLYMARKET_PRIVATE_KEY, POLYMARKET_DEPOSIT_WALLET ve py-clob-client-v2 gerekir."
            )
            return
        # Paper panel öğrenmesini kullan (live.db kapanışları pkl'yi bozmasın)
        _learn_ro = os.getenv("POLYMARKET_LEARN_READONLY", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if _learn_ro:
            snap = self_improver.load_learned_snapshot()
            if snap.get("calibration"):
                CALIBRATION = snap["calibration"]
            if snap.get("momentum_veto") is not None:
                MOMENTUM_VETO = float(snap["momentum_veto"])
            if snap.get("edge_threshold") is not None:
                EDGE_THRESHOLD = float(snap["edge_threshold"])
            if snap.get("theme_edge_boost"):
                THEME_EDGE_BOOST = dict(snap["theme_edge_boost"])
            print("  📚 Paper öğrenmesi yüklendi (salt-okunur — live.db pkl güncellemez)")
        if os.getenv("LIVE_USE_WALLET_BALANCE", "0").strip().lower() in ("1", "true", "yes"):
            usdc = lc.get_collateral_usdc(_CLOB_TRADING_CLIENT)
            if usdc and usdc > 0:
                STARTING_BALANCE = usdc
                print(f"  💰 Kelly bankroll = CLOB bakiye ≈${usdc:.2f}")
        open_n0 = open_position_count(conn)
        if open_n0 > MAX_OPEN_POSITIONS:
            print(
                f"  ⚠ [LIVE] {open_n0} açık pozisyon > limit {MAX_OPEN_POSITIONS} — "
                "yeni giriş kapalı; TP/SL ile kapanana kadar bekleyin"
            )
        print(
            f"  TP/SL canlı: +{TAKE_PROFIT_STAKE_PCT*100:.2f}% / -{STOP_LOSS_STAKE_PCT*100:.2f}% stake  "
            f"×{TP_TRIGGER_FRAC:.3f}"
        )

    stopped = False
    def _stop(*_):
        nonlocal stopped
        stopped = True
        print("\n[Ctrl+C] Scanner durduruluyor...")
    signal.signal(signal.SIGINT, _stop)

    print("=" * 65)
    _mode_line = (
        "LIVE CLOB (gerçek emir) + live.db"
        if POLYMARKET_LIVE_ARMED
        else "Paper Mode"
    )
    print(f" Calibration Momentum Scanner — {_mode_line}")
    print(f" DB: {DB_PATH}")
    if POLYMARKET_LIVE_ARMED:
        _msh = float(os.getenv("POLYMARKET_MIN_ORDER_SIZE", "5"))
        print(
            f" Live profil: {_live_entry_profile()}  |  max giriş ≤{_live_max_entry_price(_msh):.2f}"
            f" (min {_msh:g} pay × fiyat ≤ ${MAX_POS_USD})"
        )
    print(f" Edge threshold: {EDGE_THRESHOLD}  Kelly: {KELLY_FRACTION}  "
          f"Max pos: ${MAX_POS_USD}")
    print(f" Pozisyon kontrolü: {POSITION_CHECK}s  Market tarama: {SCAN_INTERVAL}s")
    _tp_demo = _effective_tp_stake_pct(FAST_TP_MAX_HOURS / 2, 0.0)
    _tp_ultra = _effective_tp_stake_pct(ULTRA_FAST_TP_MAX_HOURS / 2, 0.0)
    _tp_quick = _effective_tp_stake_pct(100.0, QUICK_TP_EDGE_MIN + 0.01)
    print(
        f" Zaman penceresi: {MIN_HOURS_TO_CLOSE:.0f}h – {MAX_HOURS_TO_CLOSE:.0f}h  "
        f"TP katmanları: taban +{TAKE_PROFIT_STAKE_PCT*100:.1f}% | "
        f"≤{FAST_TP_MAX_HOURS:.0f}h → min {FAST_TP_STAKE_PCT*100:.1f}% | "
        f"≤{min(ULTRA_FAST_TP_MAX_HOURS, FAST_TP_MAX_HOURS):.0f}h → min {ULTRA_FAST_TP_STAKE_PCT*100:.1f}% | "
        f"|edge|≥{QUICK_TP_EDGE_MIN:.2f} → min {QUICK_TP_STAKE_PCT*100:.1f}%  "
        f"(örnek: {_tp_demo*100:.1f}% / {_tp_ultra*100:.1f}% / {_tp_quick*100:.1f}%)"
    )
    _tp_extras: list[str] = []
    if TP_TRIGGER_FRAC < 0.9999:
        _tp_extras.append(f"TP tetik eşiği ×{TP_TRIGGER_FRAC:.3f} (hedefin kesri)")
    if NANO_TP_MAX_HOURS > 0:
        _nc = min(NANO_TP_MAX_HOURS, min(ULTRA_FAST_TP_MAX_HOURS, FAST_TP_MAX_HOURS))
        _tp_extras.append(f"nano ≤{_nc:.0f}h → {NANO_TP_STAKE_PCT*100:.1f}% stake")
    if SPORTS_EARLY_TP_DISCOUNT > 0:
        _tp_extras.append(f"spor erken TP −{SPORTS_EARLY_TP_DISCOUNT:.3f} trigger")
    if TP_DROUGHT_MINUTES > 0:
        _tp_extras.append(f"kuraklık {TP_DROUGHT_MINUTES}dk → {TP_DROUGHT_STAKE_PCT*100:.1f}% stake")
    if _one_per_event_enabled():
        _tp_extras.append("1 pozisyon/event")
    if MARKET_MIN_REOPEN_SEC > 0:
        _tp_extras.append(f"reopen ≥{MARKET_MIN_REOPEN_SEC}s")
    if LONG_SPORTS_MAX_OPEN > 0:
        _tp_extras.append(f"uzun spor max {LONG_SPORTS_MAX_OPEN}")
    if _tp_extras:
        print("  " + "  |  ".join(_tp_extras))
    if os.getenv("APEX_2X_24H", "").strip().lower() in ("1", "true", "yes"):
        _bal = float(os.getenv("STARTING_BALANCE", str(STARTING_BALANCE)))
        _mult = float(os.getenv("APEX_TARGET_MULTIPLIER", "2"))
        print(
            f" 🎯 APEX 2×24H: ${_bal:,.0f} → hedef ~${_bal * _mult:,.0f}  "
            f"| profil={os.getenv('PROFILE_NAME', 'apex')} "
            f"v{os.getenv('PROFILE_VERSION', '?')}"
        )
    if hybrid_tp.hybrid_enabled():
        _h_sp = float(os.getenv("HYBRID_TP_SPIKE_THRESHOLD", "0.52"))
        _h_r0 = float(os.getenv("HYBRID_TP_RUNNER_MIN_PCT", "0.17"))
        _h_r1 = float(os.getenv("HYBRID_TP_RUNNER_MAX_PCT", "0.25"))
        _h_tr = os.getenv("HYBRID_TP_TRAIL_ENABLED", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        print(
            f" Hibrit TP: spike≥{_h_sp:.2f} → runner {_h_r0*100:.0f}–{_h_r1*100:.0f}% stake  "
            f"| trail={'açık' if _h_tr else 'kapalı'}"
        )
    print(
        f" SL: -{STOP_LOSS_STAKE_PCT*100:.1f}% stake (katastrofik tavan "
        f"{float(os.getenv('SL_CATASTROPHIC_PCT', '0.08'))*100:.0f}%)  "
        f"MaxSpread: {MAX_SPREAD*100:.0f}%  Stale: {STALE_MINUTES}dk"
    )
    _none_m = (
        "kapalı"
        if ZERO_MOM_NONE_MAX_HOURS <= 0
        else f"≤{ZERO_MOM_NONE_MAX_HOURS:.0f}h"
    )
    print(
        f" Mom: düz çizgi ≤{ZERO_MOM_SKIP_MAX_HOURS:.0f}h  |  CLOB eğimi yok {_none_m}  |  "
        f"veto NRVT/EURO/UPDN: {VETO_VOLATILE_NARRATIVE}/"
        f"{VETO_EUROVISION_RANKING}/{VETO_DAILY_UP_OR_DOWN}"
    )
    print("=" * 65)

    _write_scanner_heartbeat(conn, 0)

    pos_cycle   = 0   # Her POSITION_CHECK saniyede bir artar
    scan_cycle  = 0   # Her SCAN_INTERVAL saniyede bir artar
    last_scan_t = 0.0 # Son market tarama zamanı

    while not stopped:
        loop_start = time.time()
        pos_cycle += 1
        now_str = datetime.now().strftime("%H:%M:%S")

        # ── A. Her döngü: açık pozisyonları kontrol et (TP/SL/stale) ────────
        print(f"\n[{now_str}] Kontrol #{pos_cycle}")
        closed = check_and_close_positions(conn, client)
        if closed:
            print(f"  {closed} pozisyon kapatıldı.")

        # ── B. Self-improvement — yalnızca paper.db (canlıda salt-okunur öğrenme) ─
        if not (POLYMARKET_LIVE_ARMED and LEARN_READONLY):
            try:
                learned = self_improver.run(conn)
                new_cal = learned.get("calibration")
                if new_cal:
                    CALIBRATION = new_cal
                new_mv = learned.get("momentum_veto")
                if new_mv and abs(new_mv - MOMENTUM_VETO) > 1e-6:
                    MOMENTUM_VETO = new_mv
                    print(f"  🔧 momentum_veto → {MOMENTUM_VETO:.4f}")
                new_et = learned.get("edge_threshold")
                if new_et and abs(new_et - EDGE_THRESHOLD) > 1e-6:
                    if os.getenv("APEX_2X_24H", "").strip().lower() in (
                        "1",
                        "true",
                        "yes",
                    ):
                        env_et = float(os.getenv("EDGE_THRESHOLD", str(EDGE_THRESHOLD)))
                        EDGE_THRESHOLD = min(float(new_et), env_et)
                        EDGE_THRESHOLD = max(0.035, EDGE_THRESHOLD)
                    else:
                        EDGE_THRESHOLD = float(new_et)
                    print(f"  🔧 edge_threshold → {EDGE_THRESHOLD:.4f}")
                new_tb = learned.get("theme_edge_boost")
                if isinstance(new_tb, dict) and new_tb != THEME_EDGE_BOOST:
                    THEME_EDGE_BOOST = dict(new_tb)
                    if THEME_EDGE_BOOST:
                        parts = "  ".join(
                            f"{k}+{v:.3f}" for k, v in sorted(THEME_EDGE_BOOST.items())
                        )
                        print(f"  🔧 theme_edge_boost → {parts}")
            except Exception as exc:
                print(f"  [self_improver] uyarı: {exc}")

        # ── B2. Periyodik işlem raporu (çıkış sebebi, tutma süresi, TP oranı) ──
        try:
            tr_int = int(os.getenv("TRADE_REPORT_INTERVAL_CYCLES", "40"))
            tr_n = int(os.getenv("TRADE_REPORT_LAST_N", "60"))
            tr_on_start = int(os.getenv("TRADE_REPORT_ON_START", "1"))
        except ValueError:
            tr_int, tr_n, tr_on_start = 40, 60, 1
        if tr_int > 0 and (
            (pos_cycle % tr_int == 0)
            or (tr_on_start != 0 and pos_cycle == 1)
        ):
            try:
                self_improver.print_closed_trade_report(conn, n=max(10, tr_n))
                try:
                    sl_n = int(os.getenv("SL_DIGEST_LAST_N", "15"))
                except ValueError:
                    sl_n = 15
                self_improver.print_sl_digest(conn, n=max(5, sl_n))
            except Exception as exc:
                print(f"  [işlem raporu] {exc}")

        # ── C. Yeni market taraması — yalnızca SCAN_INTERVAL dolduğunda ─────
        elapsed_since_scan = loop_start - last_scan_t
        opened = 0
        if elapsed_since_scan >= SCAN_INTERVAL:
            scan_cycle += 1
            print(f"  [tarama #{scan_cycle}] market aranıyor...")
            opened = scan_markets(conn, client)
            last_scan_t = time.time()

        # ── C2. Idle backtest: açık pozisyon yoksa eğit ──────────────────────
        # Her 5. kontrol döngüsünde ve açık pozisyon yokken backtest yap.
        # backtest_trainer kendi içinde 5dk cooldown'u yönetir → spam yok.
        open_n_now = open_position_count(conn)
        if (
            open_n_now == 0
            and pos_cycle % 5 == 0
            and not (POLYMARKET_LIVE_ARMED and LEARN_READONLY)
        ):
            try:
                bt_result = backtest_trainer.run_batch(
                    client, conn, CALIBRATION,
                    max_markets=20, verbose=True,
                )
                # Backtest en iyi edge threshold önerirse güncelle
                bt_edge = bt_result.get("best_edge_threshold")
                if bt_edge and bt_edge != EDGE_THRESHOLD and bt_result.get("simulated", 0) >= 10:
                    print(f"  📚 BACKTEST öneri: edge_threshold {EDGE_THRESHOLD:.3f} → {bt_edge:.3f}")
                    EDGE_THRESHOLD = bt_edge
            except Exception as bt_exc:
                pass  # Backtest hatası ana döngüyü etkilemez

        # ── D. Özet ──────────────────────────────────────────────────────────
        open_n = open_position_count(conn)
        total_closed = conn.execute(
            "SELECT COUNT(*) n FROM positions WHERE closed_at IS NOT NULL"
        ).fetchone()["n"]
        total_pnl = conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) total FROM positions WHERE closed_at IS NOT NULL"
        ).fetchone()["total"]
        scan_info = f"  Yeni: {opened}" if opened else ""
        print(f"  Açık: {open_n}  Kapalı: {total_closed}  "
              f"P&L: ${total_pnl:+.2f}{scan_info}")

        _write_scanner_heartbeat(conn, pos_cycle)

        if stopped:
            break

        # POSITION_CHECK saniye bekle (0.1s parçalar halinde — Ctrl+C'ye duyarlı)
        sleep_end = loop_start + POSITION_CHECK
        while not stopped and time.time() < sleep_end:
            time.sleep(0.1)

    conn.close()
    client.close()
    print("Scanner kapandı.")


if __name__ == "__main__":
    main()
