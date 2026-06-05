"""
Evrim — harici haber beslemesi (RSS + opsiyonel JSON/Telegram dosyası).

Yalnızca evrim radar_news_feed state'ini günceller.
"""
from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RSS = (
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://bitcoinmagazine.com/feed",
    "https://www.theblock.co/rss.xml",
)
_CACHE: dict[str, Any] = {"ts": 0.0, "items": []}
_MIN_REFRESH_SEC = max(120.0, float(os.getenv("EVRIM_NEWS_MIN_REFRESH_SEC", "180") or 180))

_BULL = re.compile(
    r"\b(etf\s+approval|approved|surge|rally|breakout|bullish|record\s+high|"
    r"inflow|adoption|partnership|listing)\b",
    re.I,
)
_BEAR = re.compile(
    r"\b(hack|exploit|ban|lawsuit|sec\s+sue|crash|collapse|delist|"
    r"outflow|bearish|liquidation|bankrupt|shutdown)\b",
    re.I,
)
_UNCERTAIN = re.compile(
    r"\b(investigation|rumor|may|could|uncertain|delay|halt|warning)\b",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_headline(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "neutral"
    if _BEAR.search(t):
        return "bearish"
    if _BULL.search(t):
        return "bullish"
    if _UNCERTAIN.search(t):
        return "uncertain"
    return "neutral"


def _fetch_url(url: str, timeout: float = 12.0) -> str:
    req = Request(
        url,
        headers={"User-Agent": "EvrimNewsBot/1.0 (+binance-futures-scanner)"},
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_rss_xml(raw: str, source: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return items
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for item in root.findall(".//item") + root.findall(".//{*}entry"):
        title_el = item.find("title") or item.find("{*}title")
        if title_el is None or not (title_el.text or "").strip():
            continue
        title = re.sub(r"\s+", " ", (title_el.text or "").strip())[:240]
        sent = _classify_headline(title)
        items.append(
            {
                "title": title,
                "source": source,
                "sentiment": sent,
                "fetched_at": _now_iso(),
            }
        )
    return items[:25]


def _rss_urls() -> tuple[str, ...]:
    import os

    raw = os.getenv("EVRIM_RSS_FEEDS", "").strip()
    if raw:
        return tuple(u.strip() for u in raw.split(",") if u.strip())
    return _DEFAULT_RSS


def _load_external_json() -> list[dict[str, Any]]:
    import os

    path = os.getenv("EVRIM_NEWS_JSON", "").strip()
    if not path:
        p = _ROOT / "data" / "evrim_external_news.json"
        if p.is_file():
            path = str(p)
        else:
            return []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
    except Exception:
        pass
    return []


def fetch_news_items(*, force: bool = False) -> list[dict[str, Any]]:
    """RSS + harici JSON birleşik haber listesi."""
    now = time.time()
    if not force and now - float(_CACHE.get("ts") or 0) < _MIN_REFRESH_SEC:
        return list(_CACHE.get("items") or [])

    all_items: list[dict[str, Any]] = []
    for url in _rss_urls():
        try:
            raw = _fetch_url(url)
            all_items.extend(_parse_rss_xml(raw, source=url.split("/")[2][:40]))
        except Exception:
            continue

    for row in _load_external_json():
        title = str(row.get("title") or row.get("headline") or "")[:240]
        if not title:
            continue
        sent = str(row.get("sentiment") or _classify_headline(title))
        all_items.append(
            {
                "title": title,
                "source": str(row.get("source") or "external_json"),
                "sentiment": sent,
                "fetched_at": row.get("fetched_at") or _now_iso(),
            }
        )

    _CACHE["ts"] = now
    _CACHE["items"] = all_items[:40]
    return list(_CACHE["items"])


def build_radar_news_feed(items: list[dict[str, Any]]) -> dict[str, Any]:
    """En güncel başlıkları radar bucket'larına dağıt."""
    if not items:
        return {
            "crypto_news": {"status": "placeholder"},
            "etf_regulation": {"status": "placeholder"},
            "macro_calendar": {"status": "placeholder"},
            "exchange_announcements": {"status": "placeholder"},
            "listing_delisting": {"status": "placeholder"},
            "updated_at": _now_iso(),
        }

    def pick(keywords: tuple[str, ...], bucket: str) -> dict[str, Any]:
        for it in items:
            t = (it.get("title") or "").lower()
            if any(k in t for k in keywords):
                return {
                    "status": "ok",
                    "headline": it["title"],
                    "sentiment": it.get("sentiment") or "neutral",
                    "source": it.get("source") or bucket,
                    "fetched_at": it.get("fetched_at"),
                }
        return {"status": "placeholder"}

    top = items[0]
    crypto = {
        "status": "ok",
        "headline": top.get("title"),
        "sentiment": top.get("sentiment") or "neutral",
        "source": top.get("source") or "rss",
        "fetched_at": top.get("fetched_at"),
    }
    return {
        "crypto_news": crypto,
        "etf_regulation": pick(("etf", "sec", "regulation", "approval"), "etf"),
        "macro_calendar": pick(("fed", "cpi", "rate", "inflation", "jobs"), "macro"),
        "exchange_announcements": pick(
            ("binance", "exchange", "maintenance", "outage"), "exchange"
        ),
        "listing_delisting": pick(("list", "delist", "launchpool"), "listing"),
        "updated_at": _now_iso(),
        "items_n": len(items),
    }


def persist_radar_news_feed(*, force: bool = False) -> dict[str, Any]:
    """State'e yaz — evrim_market_radar okur."""
    items = fetch_news_items(force=force)
    feed = build_radar_news_feed(items)
    try:
        from elite_trader.evrim_training import load_training_state, _save_training_state

        st = load_training_state()
        st["radar_news_feed"] = feed
        st["radar_news_last_fetch"] = _now_iso()
        _save_training_state(st)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:80], "feed": feed}
    return {"ok": True, "feed": feed, "items_n": len(items)}
