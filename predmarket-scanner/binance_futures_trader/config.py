"""Ortam değişkenleri — BN_FUT_* prefix."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _f(key: str, default: str) -> float:
    try:
        return float(os.getenv(key, default))
    except ValueError:
        return float(default)


def _i(key: str, default: str) -> int:
    try:
        return int(os.getenv(key, default))
    except ValueError:
        return int(default)


def _b(key: str, default: str = "0") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes")


DB_PATH = Path(os.getenv("BN_FUT_DB_PATH", str(ROOT / "data" / "binance_futures_demo.db")))
DASHBOARD_PORT = _i("BN_FUT_DASHBOARD_PORT", "8210")
STARTING_BALANCE = _f("BN_FUT_START_BALANCE", "1000")
MODE = os.getenv("BN_FUT_MODE", "paper").strip().lower()  # paper | testnet

STRATEGY_PROFILE = os.getenv("BN_FUT_STRATEGY_PROFILE", "standard").strip().lower()

TP_PCT = _f("BN_FUT_TP_PCT", "0.03")
SL_PCT = _f("BN_FUT_SL_PCT", "0.05")
# Açılış sonrası SL bekleme + slippage tamponu (erken SL önlemi)
SL_MIN_HOLD_SEC = _i("BN_FUT_SL_MIN_HOLD_SEC", "120")
SL_BUFFER_PCT = _f("BN_FUT_SL_BUFFER_PCT", "0.0015")
SL_ATR_MULT = _f("BN_FUT_SL_ATR_MULT", "1.35")
# Scalp profili (BN_FUT_STRATEGY_PROFILE=scalp iken env ile override edilir)
SCALP_MOM_THRESH = _f("BN_FUT_SCALP_MOM_THRESH", "0.0035")
SCALP_LOOKBACK = _i("BN_FUT_SCALP_LOOKBACK", "72")
SCALP_LEV_MULT = _f("BN_FUT_SCALP_LEV_MULT", "1.22")
SCALP_MIN_CONF_LEV = _f("BN_FUT_SCALP_MIN_CONF_LEV", "3.8")
SCALP_STAKE_MULT = _f("BN_FUT_SCALP_STAKE_MULT", "1.18")
SCALP_BT_HOLD_BARS = _i("BN_FUT_SCALP_BT_HOLD_BARS", "8")

# Margin: isolated = pozisyon başına risk (çoklu scalp için önerilir)
MARGIN_TYPE = os.getenv("BN_FUT_MARGIN_TYPE", "isolated").strip().lower()

# Uzun süre açık pozisyon — fiyat %2 veya stake ROI %2
STALE_MIN_AGE_SEC = _i("BN_FUT_STALE_MIN_AGE_SEC", "2700")
STALE_TP_MOVE_PCT = _f("BN_FUT_STALE_TP_MOVE_PCT", "0.02")
STALE_TP_ROI_PCT = _f("BN_FUT_STALE_TP_ROI_PCT", "0.02")

# Runner — kademeli kâr (stake üzerinden ROI)
RUNNER_MIN_CONF = _f("BN_FUT_RUNNER_MIN_CONF", "4.0")
RUNNER_MIN_SCORE = _f("BN_FUT_RUNNER_MIN_SCORE", "3.5")
RUNNER_MIN_MOM_TAGS = _i("BN_FUT_RUNNER_MIN_MOM_TAGS", "2")
RUNNER_MAX_MOVE_PCT = _f("BN_FUT_RUNNER_MAX_MOVE_PCT", "0.08")


def _parse_float_list(raw: str, default: str) -> list[float]:
    text = os.getenv(raw, default)
    out: list[float] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
            if v > 1:
                v /= 100.0
            out.append(v)
        except ValueError:
            continue
    return out


TIER_ROI_PCTS = _parse_float_list("BN_FUT_TIER_ROI_PCTS", "0.10,0.20,0.30")
TIER_CLOSE_FRACS = _parse_float_list("BN_FUT_TIER_CLOSE_FRACS", "0.33,0.33,0.34")

# Sinyal kalitesi + öğrenme
MIN_SIGNAL_PARTS = _i("BN_FUT_MIN_SIGNAL_PARTS", "2")
MIN_SIGNAL_PART_SCORE = _f("BN_FUT_MIN_SIGNAL_PART_SCORE", "0.25")
LEARN_MIN_TRADES = _i("BN_FUT_LEARN_MIN_TRADES", "3")
LEARN_WEIGHT_FLOOR = _f("BN_FUT_LEARN_WEIGHT_FLOOR", "0.30")
LEARN_WEIGHT_CAP = _f("BN_FUT_LEARN_WEIGHT_CAP", "1.55")
BT_VETO_WR = _f("BN_FUT_BT_VETO_WR", "0.38")
COIN_LOSS_VETO_COUNT = _i("BN_FUT_COIN_LOSS_VETO_COUNT", "5")


def is_scalp() -> bool:
    return STRATEGY_PROFILE in ("scalp", "fast", "turbo")
SCAN_INTERVAL = _i("BN_FUT_SCAN_INTERVAL_SEC", "20")
POS_CHECK = _i("BN_FUT_POSITION_CHECK_SEC", "5")
MAX_OPEN = _i("BN_FUT_MAX_OPEN", "12")
MAX_POS_USD = _f("BN_FUT_MAX_POSITION_USD", "150")
MIN_POS_USD = _f("BN_FUT_MIN_POSITION_USD", "25")
KELLY = _f("BN_FUT_KELLY", "0.30")
MIN_SCORE = _f("BN_FUT_MIN_SCORE", "2.0")
ACTIVE_CAPITAL_PCT = _f("BN_FUT_ACTIVE_CAPITAL_PCT", "0.50")
TARGET_DAILY_PCT = _f("BN_FUT_TARGET_DAILY_PCT", "0.50")

HEDGE_ENABLED = _b("BN_FUT_HEDGE_ENABLED", "1")
HEDGE_TRIGGER_PCT = _f("BN_FUT_HEDGE_TRIGGER_PCT", "0.012")
HEDGE_STAKE_FRAC = _f("BN_FUT_HEDGE_STAKE_FRAC", "0.35")
HEDGE_PROACTIVE = _b("BN_FUT_HEDGE_PROACTIVE", "1")

LEVERAGE = _i("BN_FUT_LEVERAGE", "5")
LEVERAGE_DEFAULT = _i("BN_FUT_LEVERAGE", "5")
LEVERAGE_MIN = _i("BN_FUT_LEVERAGE_MIN", "2")
LEVERAGE_MAX = _i("BN_FUT_LEVERAGE_MAX", "12")
# Binance USDT-M varsayılan taker ~0.04% (borsa VIP seviyesine göre değişir)
TAKER_FEE_RATE = _f("BN_FUT_TAKER_FEE_RATE", "0.0004")
MAKER_FEE_RATE = _f("BN_FUT_MAKER_FEE_RATE", "0.0002")
CANDLE_INTERVAL = os.getenv("BN_FUT_CANDLE_INTERVAL", "15m")
MARK_WS_ENABLED = _b("BN_FUT_MARK_WS", "1")
MARK_WS_MAX_AGE_SEC = _f("BN_FUT_MARK_WS_MAX_AGE_SEC", "3")
PANEL_POLL_MS = _i("BN_FUT_PANEL_POLL_MS", "500")
PANEL_FULL_POLL_MS = _i("BN_FUT_PANEL_FULL_POLL_MS", "12000")
SYNC_INTERVAL_SEC = _f("BN_FUT_SYNC_INTERVAL_SEC", "20")
SIGNAL_REFRESH_SEC = _f("BN_FUT_SIGNAL_REFRESH_SEC", "22")
LIVE_POSITION_POLL_SEC = _f("BN_FUT_LIVE_POSITION_POLL_SEC", "2.5")
LIVE_BALANCE_POLL_SEC = _f("BN_FUT_LIVE_BALANCE_POLL_SEC", "10")
LIVE_REST_TIMEOUT_SEC = _f("BN_FUT_LIVE_REST_TIMEOUT_SEC", "4")
WATCHLIST = [
    c.strip().upper()
    for c in os.getenv(
        "BN_FUT_WATCHLIST",
        "BTC,ETH,SOL,BNB,XRP,DOGE,AVAX,LINK,MATIC,APT",
    ).split(",")
    if c.strip()
]

API_KEY = os.getenv("BINANCE_FUTURES_API_KEY", "").strip()
API_SECRET = os.getenv("BINANCE_FUTURES_API_SECRET", "").strip()
TESTNET = _b("BINANCE_FUTURES_TESTNET", "1")
# demo-fapi.binance.com (yeni Futures Demo; eski testnet.binancefuture.com değil)
FUTURES_DEMO = _b("BINANCE_FUTURES_DEMO", "1" if TESTNET else "0")
API_REST_BASE = os.getenv("BINANCE_FUTURES_REST_BASE", "").strip()

CEX_ARB_ENABLED = _b("BN_FUT_CEX_ARB", "1")
GAP_ANALYSIS_ENABLED = _b("BN_FUT_GAP_ANALYSIS", "1")
FLOW_ANALYSIS_ENABLED = _b("BN_FUT_FLOW_ANALYSIS", "1")
NEWS_ENABLED = _b("BN_FUT_NEWS", "1")
LEARNING_ENABLED = _b("BN_FUT_LEARNING", "1")
EDU_MEMORY_ENABLED = _b("BN_FUT_EDU_MEMORY", "1")
EDU_STRATEGY_ID = os.getenv("BN_FUT_EDU_STRATEGY_ID", "").strip()
PORTFOLIO_ENGINE = _b("BN_FUT_PORTFOLIO_ENGINE", "0")
BACKTEST_ON_START = _b("BN_FUT_BACKTEST_START", "1")
BACKTEST_DAYS = _i("BN_FUT_BACKTEST_DAYS", "5")
FRESH_START = _b("BN_FUT_FRESH_START", "0")


def reload_from_env() -> None:
    """Ortam değişkenlerini yeniden oku (elite pro başlatmadan önce çağırın)."""
    global DB_PATH, DASHBOARD_PORT, STARTING_BALANCE, MODE, STRATEGY_PROFILE
    global API_KEY, API_SECRET, TESTNET, FUTURES_DEMO, API_REST_BASE
    global TP_PCT, SL_PCT, MAX_OPEN, SCAN_INTERVAL, POS_CHECK
    DB_PATH = Path(os.getenv("BN_FUT_DB_PATH", str(ROOT / "data" / "binance_futures_demo.db")))
    DASHBOARD_PORT = _i("BN_FUT_DASHBOARD_PORT", "8210")
    STARTING_BALANCE = _f("BN_FUT_START_BALANCE", "1000")
    MODE = os.getenv("BN_FUT_MODE", "paper").strip().lower()
    STRATEGY_PROFILE = os.getenv("BN_FUT_STRATEGY_PROFILE", "standard").strip().lower()
    API_KEY = os.getenv("BINANCE_FUTURES_API_KEY", "").strip()
    API_SECRET = os.getenv("BINANCE_FUTURES_API_SECRET", "").strip()
    TESTNET = _b("BINANCE_FUTURES_TESTNET", "1")
    FUTURES_DEMO = _b("BINANCE_FUTURES_DEMO", "1" if TESTNET else "0")
    API_REST_BASE = os.getenv("BINANCE_FUTURES_REST_BASE", "").strip()
    TP_PCT = _f("BN_FUT_TP_PCT", "0.03")
    SL_PCT = _f("BN_FUT_SL_PCT", "0.05")
    MAX_OPEN = _i("BN_FUT_MAX_OPEN", "12")
    SCAN_INTERVAL = _i("BN_FUT_SCAN_INTERVAL_SEC", "20")
    POS_CHECK = _i("BN_FUT_POSITION_CHECK_SEC", "5")
