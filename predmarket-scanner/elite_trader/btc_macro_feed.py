"""BTC makro — türev (Binance), kitap, CMC dominance, F&G, haber başlıkları."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any
from urllib.request import Request, urlopen

_lock = threading.Lock()
_macro: dict[str, Any] = {
    "updated_at": 0.0,
    "derivatives_updated_at": 0.0,
    "news_updated_at": 0.0,
    "cmc_updated_at": 0.0,
    "fng_updated_at": 0.0,
}
_BTC_NEWS = re.compile(
    r"\b(btc|bitcoin|etf|fed|sec|crypto\s+market|halving|binance)\b",
    re.I,
)


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _fetch_json(url: str, timeout: float = 12.0, headers: dict[str, str] | None = None) -> Any:
    hdr = {"User-Agent": "MegaBtcMacro/1.0"}
    if headers:
        hdr.update(headers)
    req = Request(url, headers=hdr)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _fetch_fear_greed() -> dict[str, Any]:
    try:
        data = _fetch_json("https://api.alternative.me/fng/?limit=1&format=json")
        row = ((data or {}).get("data") or [{}])[0]
        val = int(row.get("value") or 0)
        label = str(row.get("value_classification") or "")
        return {
            "fng_score": val,
            "fng_label": label,
            "fng_updated_at": time.time(),
        }
    except Exception as exc:
        return {"fng_error": str(exc)[:80]}


def _fetch_cmc_global() -> dict[str, Any]:
    key = (os.getenv("COINMARKETCAP_API_KEY") or "").strip()
    if not key:
        return {"cmc_enabled": False}
    try:
        data = _fetch_json(
            "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest?convert=USD",
            headers={"X-CMC_PRO_API_KEY": key, "Accept": "application/json"},
        )
        g = (data or {}).get("data") or {}
        usd = (g.get("quote") or {}).get("USD") or {}
        return {
            "cmc_enabled": True,
            "btc_dominance": float(g.get("btc_dominance") or 0),
            "eth_dominance": float(g.get("eth_dominance") or 0),
            "total_market_cap_usd": float(usd.get("total_market_cap") or 0),
            "total_volume_24h_usd": float(usd.get("total_volume_24h") or 0),
            "cmc_updated_at": time.time(),
        }
    except Exception as exc:
        return {"cmc_enabled": True, "cmc_error": str(exc)[:80]}


def _fetch_binance_derivatives(client: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"derivatives_updated_at": time.time()}
    if client is None or getattr(client, "paper", False):
        return out
    sym = "BTCUSDT"
    try:
        fr = client.funding_rate("BTC")
        if fr is not None:
            out["funding_rate"] = float(fr)
            out["funding_rate_pct"] = round(float(fr) * 100.0, 4)
    except Exception:
        pass
    try:
        prem = client._get("/fapi/v1/premiumIndex", {"symbol": sym})
        out["mark_price"] = float(prem.get("markPrice") or 0)
        out["index_price"] = float(prem.get("indexPrice") or 0)
    except Exception:
        pass
    try:
        t24 = client._get("/fapi/v1/ticker/24hr", {"symbol": sym})
        out["change_24h_pct"] = float(t24.get("priceChangePercent") or 0)
        out["quote_volume_24h"] = float(t24.get("quoteVolume") or 0)
        out["high_24h"] = float(t24.get("highPrice") or 0)
        out["low_24h"] = float(t24.get("lowPrice") or 0)
    except Exception:
        pass
    try:
        oi = client._get("/fapi/v1/openInterest", {"symbol": sym})
        oi_btc = float(oi.get("openInterest") or 0)
        out["open_interest_btc"] = oi_btc
        px = float(out.get("mark_price") or 0)
        if px > 0 and oi_btc > 0:
            out["open_interest_usd"] = round(oi_btc * px, 0)
    except Exception:
        pass
    return out


def _fetch_book() -> dict[str, Any]:
    try:
        from elite_trader.berserk2_btc_context import _btc_book_imbalance

        imb = _btc_book_imbalance()
        if imb is not None:
            return {"book_imbalance_bps": imb, "book_updated_at": time.time()}
    except Exception:
        pass
    return {}


def _btc_headlines_from_hub() -> dict[str, Any]:
    try:
        from elite_trader.market_intelligence_hub import get_hub

        hub = get_hub()
        items = list(getattr(hub, "_news_verified", []) or [])
        btc_items: list[dict[str, Any]] = []
        for it in items:
            title = str(it.get("title") or "")
            if not title:
                continue
            if _BTC_NEWS.search(title) or not btc_items:
                btc_items.append(
                    {
                        "title": title[:140],
                        "sentiment": str(it.get("sentiment") or "neutral"),
                        "source": str(it.get("source") or "")[:40],
                    }
                )
            if len(btc_items) >= 6:
                break
        top = btc_items[0] if btc_items else {}
        bull = sum(1 for x in btc_items if x.get("sentiment") == "bullish")
        bear = sum(1 for x in btc_items if x.get("sentiment") == "bearish")
        agg = "neutral"
        if bear > bull and bear >= 2:
            agg = "bearish"
        elif bull > bear and bull >= 2:
            agg = "bullish"
        elif top:
            agg = str(top.get("sentiment") or "neutral")
        return {
            "news_agg_sentiment": agg,
            "news_headline": (top.get("title") or "")[:120],
            "news_headlines": btc_items[:5],
            "news_updated_at": time.time(),
        }
    except Exception as exc:
        return {"news_error": str(exc)[:80]}


def _fetch_fmp_macro() -> dict[str, Any]:
    key = (os.getenv("FMP_API_KEY") or "").strip()
    if not key or not _env_bool("MEGA_BTC_FMP_CALENDAR", True):
        return {}
    try:
        from datetime import date, timedelta

        d0 = date.today().isoformat()
        d1 = (date.today() + timedelta(days=7)).isoformat()
        url = (
            "https://financialmodelingprep.com/stable/economic-calendar"
            f"?from={d0}&to={d1}&apikey={key}"
        )
        req = Request(url, headers={"User-Agent": "MegaBtcMacro/1.0"})
        with urlopen(req, timeout=15.0) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        if raw.strip().lower().startswith("restricted") or "subscription" in raw.lower():
            return {
                "fmp_status": "plan_required",
                "fmp_note": "FMP plan — economic-calendar endpoint gerekli",
                "fmp_updated_at": time.time(),
            }
        rows = json.loads(raw)
        if isinstance(rows, dict):
            rows = rows.get("data") or rows.get("economicCalendar") or []
        if not isinstance(rows, list):
            return {"fmp_status": "empty", "fmp_updated_at": time.time()}
        high: list[dict[str, str]] = []
        for ev in rows[:80]:
            if not isinstance(ev, dict):
                continue
            impact = str(ev.get("impact") or ev.get("importance") or "").lower()
            if impact and impact not in ("high", "medium", "3", "2"):
                continue
            if impact in ("low", "1"):
                continue
            ev_name = str(ev.get("event") or ev.get("name") or "")[:80]
            if not ev_name:
                continue
            country = str(ev.get("country") or "")
            if country and country.upper() not in ("US", "EU", "CN", "JP", "UK", "DE", ""):
                if str(impact).lower() != "high" and impact != "3":
                    continue
            high.append(
                {
                    "date": str(ev.get("date") or ev.get("releaseDate") or "")[:16],
                    "event": ev_name,
                    "country": country,
                    "impact": impact,
                }
            )
            if len(high) >= 5:
                break
        nxt = high[0] if high else {}
        return {
            "fmp_status": "ok" if high else "empty",
            "macro_next_event": nxt.get("event"),
            "macro_next_date": nxt.get("date"),
            "macro_events": high,
            "fmp_updated_at": time.time(),
        }
    except Exception as exc:
        msg = str(exc)[:120]
        if "402" in msg or "403" in msg or "Restricted" in msg:
            return {
                "fmp_status": "plan_required",
                "fmp_note": "FMP plan yükseltme gerekli (economic-calendar)",
                "fmp_updated_at": time.time(),
            }
        return {"fmp_error": msg, "fmp_updated_at": time.time()}


def refresh_btc_macro(
    binance_client: Any | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Tam makro yenileme — BTC izleyici thread."""
    global _macro
    now = time.time()
    with _lock:
        cur = dict(_macro)

    patch: dict[str, Any] = {"updated_at": now}
    patch.update(_fetch_book())

    d_iv = max(15.0, _env_float("MEGA_BTC_MACRO_DERIVATIVES_SEC", 30.0))
    if force or (now - float(cur.get("derivatives_updated_at") or 0)) >= d_iv:
        patch.update(_fetch_binance_derivatives(binance_client))

    fng_iv = max(300.0, _env_float("MEGA_BTC_MACRO_FNG_SEC", 3600.0))
    if force or (now - float(cur.get("fng_updated_at") or 0)) >= fng_iv:
        patch.update(_fetch_fear_greed())

    cmc_iv = max(60.0, _env_float("MEGA_BTC_MACRO_CMC_SEC", 120.0))
    if force or (now - float(cur.get("cmc_updated_at") or 0)) >= cmc_iv:
        patch.update(_fetch_cmc_global())
        try:
            from elite_trader.market_intelligence_hub import get_hub

            g = {
                k: patch[k]
                for k in (
                    "btc_dominance",
                    "eth_dominance",
                    "total_market_cap_usd",
                    "total_volume_24h_usd",
                )
                if k in patch
            }
            if g:
                get_hub()._cmc_global = g
        except Exception:
            pass

    news_iv = max(120.0, _env_float("MEGA_BTC_MACRO_NEWS_SEC", 300.0))
    if force or (now - float(cur.get("news_updated_at") or 0)) >= news_iv:
        patch.update(_btc_headlines_from_hub())

    if _env_bool("MEGA_BTC_FMP_CALENDAR", True) and (
        force or (now - float(cur.get("fmp_updated_at") or 0)) >= 3600.0
    ):
        patch.update(_fetch_fmp_macro())

    with _lock:
        _macro.update(patch)
        return dict(_macro)


def patch_btc_macro_fast() -> dict[str, Any]:
    """Kitap + cache — her 0.3 sn."""
    patch = _fetch_book()
    with _lock:
        _macro.update(patch)
        return dict(_macro)


def get_btc_macro() -> dict[str, Any]:
    with _lock:
        return dict(_macro)


def macro_snapshot() -> dict[str, Any]:
    """Panel + btc_context."""
    m = get_btc_macro()
    fng = int(m.get("fng_score") or 0)
    dom = m.get("btc_dominance")
    fr = m.get("funding_rate_pct")
    parts = []
    if dom is not None:
        parts.append(f"Dom {float(dom):.1f}%")
    if fng:
        parts.append(f"F&G {fng}")
    if fr is not None:
        parts.append(f"Fund {fr}%")
    if m.get("book_imbalance_bps") is not None:
        parts.append(f"Kitap {m['book_imbalance_bps']}")
    bias = _macro_bias_label(m)
    return {
        "summary": " · ".join(parts) if parts else "—",
        "bias": bias,
        "bias_label": _BIAS_LABELS.get(bias, bias),
        "btc_dominance": dom,
        "eth_dominance": m.get("eth_dominance"),
        "fng_score": fng or None,
        "fng_label": m.get("fng_label"),
        "funding_rate_pct": fr,
        "open_interest_usd": m.get("open_interest_usd"),
        "change_24h_pct": m.get("change_24h_pct"),
        "book_imbalance_bps": m.get("book_imbalance_bps"),
        "news_agg_sentiment": m.get("news_agg_sentiment"),
        "news_headline": m.get("news_headline"),
        "news_headlines": m.get("news_headlines") or [],
        "macro_next_event": m.get("macro_next_event"),
        "macro_next_date": m.get("macro_next_date"),
        "macro_events": m.get("macro_events") or [],
        "fmp_status": m.get("fmp_status"),
        "fmp_note": m.get("fmp_note"),
        "updated_at": m.get("updated_at"),
        "age_sec": round(max(0.0, time.time() - float(m.get("updated_at") or 0)), 1)
        if m.get("updated_at")
        else None,
    }


_BIAS_LABELS = {
    "risk_on_long": "LONG lehine",
    "risk_off_short": "SHORT lehine",
    "neutral": "Nötr",
    "caution": "Temkinli",
}


def _macro_bias_label(m: dict[str, Any]) -> str:
    fng = int(m.get("fng_score") or 50)
    ch = float(m.get("change_24h_pct") or 0)
    news = str(m.get("news_agg_sentiment") or "neutral")
    fr = float(m.get("funding_rate_pct") or 0)
    if fng <= 25 and news != "bearish":
        return "risk_on_long"
    if fng >= 75 or (news == "bearish" and ch < -1.0):
        return "risk_off_short"
    if fr > _env_float("MEGA_BTC_MACRO_FUNDING_LONG_BLOCK_PCT", 0.025) and ch > 0:
        return "caution"
    if fr < -_env_float("MEGA_BTC_MACRO_FUNDING_SHORT_BLOCK_PCT", 0.03):
        return "risk_on_long"
    if ch <= -2.0 or news == "bearish":
        return "risk_off_short"
    if ch >= 2.0 and news == "bullish":
        return "risk_on_long"
    return "neutral"


def macro_entry_allowed(
    side: str,
    signal: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """MEGA giriş — makro veto (cascade/flash muaf)."""
    if not _env_bool("MEGA_MACRO_ENTRY_GUARD", True):
        return True, ""
    sig = signal or {}
    if sig.get("mega_btc_cascade") or sig.get("mega_btc_cascade_direct"):
        return True, ""
    if sig.get("mega_flash_reversal") or sig.get("mega_flash_pump"):
        return True, ""

    m = get_btc_macro()
    s = str(side or "LONG").upper()
    fng = int(m.get("fng_score") or 50)
    news = str(m.get("news_agg_sentiment") or "neutral")
    fr = float(m.get("funding_rate_pct") or 0)

    if s == "LONG":
        bounce_long = False
        if _env_bool("MEGA_MACRO_BOUNCE_RELAX_FUNDING", True):
            try:
                from elite_trader.btc_flash_cascade import bounce_favors_long
                from elite_trader.mega_direction_guard import _price_history

                bounce_long, _ = bounce_favors_long(_price_history())
            except Exception:
                bounce_long = False
        if fng >= int(_env_float("MEGA_BTC_MACRO_FNG_BLOCK_LONG", 78)):
            return False, "macro_fng_extreme_greed"
        if (
            not bounce_long
            and fr >= _env_float("MEGA_BTC_MACRO_FUNDING_LONG_BLOCK_PCT", 0.025)
        ):
            return False, "macro_funding_crowded_long"
        if news == "bearish" and _env_bool("MEGA_MACRO_NEWS_VETO", True):
            return False, "macro_news_bearish"
    else:
        if fng <= int(_env_float("MEGA_BTC_MACRO_FNG_BLOCK_SHORT", 22)):
            return False, "macro_fng_extreme_fear"
        if fr <= -_env_float("MEGA_BTC_MACRO_FUNDING_SHORT_BLOCK_PCT", 0.03):
            return False, "macro_funding_crowded_short"
        if news == "bullish" and _env_bool("MEGA_MACRO_NEWS_VETO", True):
            return False, "macro_news_bullish"

    return True, ""
