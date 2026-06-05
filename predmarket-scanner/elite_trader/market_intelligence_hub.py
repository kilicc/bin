"""
Tek piyasa zekâ havuzu — Binance + harici kaynaklar + haber.

- Mod profillerine / işlem ayarlarına dokunmaz.
- Ham veriyi toplar; dezenformasyon / doğrulanmamış içerik filtrelenir.
- Her mod mevcut filtresiyle havuzdan okur (candidate üzerinde pool_* meta).
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent

# Güvenilir kaynak alan adları (RSS + büyük medya)
_TRUSTED_SOURCE_RE = re.compile(
    r"(coindesk|cointelegraph|reuters|bloomberg|theblock|decrypt|"
    r"binance\.com|coinbase|forbes|wsj|cnbc|sec\.gov|federalreserve)",
    re.I,
)

# Doğrulanmamış / dezenformasyon kalıpları
_DISINFO_RE = re.compile(
    r"(free\s+btc|airdrop\s+claim|send\s+\d+\s*eth|guaranteed\s+\d+x|"
    r"elon\s+musk\s+gift|whatsapp\s+group|telegram\s+signal\s+vip|"
    r"double\s+your\s+crypto|1000%\s+profit|not\s+a\s+scam|"
    r"click\s+here\s+to\s+claim|wallet\s+drain|seed\s+phrase)",
    re.I,
)

_UNVERIFIED_ONLY_RE = re.compile(
    r"^(breaking|rumor|unconfirmed|sources\s+say|might|could\s+soon)\b",
    re.I,
)

_BLOCKED_SOURCES = frozenset(
    {
        "unknown",
        "telegram_rumor",
        "twitter_unverified",
        "anon",
        "crypto_influencer",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credibility_score(item: dict[str, Any]) -> tuple[bool, str]:
    """True = havuza alınır."""
    title = str(item.get("title") or item.get("headline") or "").strip()
    source = str(item.get("source") or "").strip().lower()
    if not title or len(title) < 12:
        return False, "empty_title"
    if _DISINFO_RE.search(title):
        return False, "disinfo_pattern"
    if source in _BLOCKED_SOURCES:
        return False, "blocked_source"
    verified = item.get("verified") is True or item.get("trust") == "high"
    trusted = bool(_TRUSTED_SOURCE_RE.search(source)) or verified
    if _UNVERIFIED_ONLY_RE.match(title) and not trusted:
        return False, "unverified_rumor"
    if item.get("verified") is False or item.get("trust") == "low":
        return False, "low_trust"
    if not trusted and re.search(
        r"\b(rumor|unconfirmed|allegedly|might\s+be|could\s+be)\b", title, re.I
    ):
        return False, "rumor_untrusted"
    return True, "ok"


class MarketIntelligenceHub:
    """Ortak veri kanalı — fiyat taraması + haber + harici akış meta."""

    def __init__(self) -> None:
        self._news_verified: list[dict[str, Any]] = []
        self._news_rejected = 0
        self._news_accepted = 0
        self._external_quotes: dict[str, float] = {}
        self._flows: list[dict[str, Any]] = []
        self._last_news_ts = 0.0
        self._last_external_ts = 0.0
        self._last_bulk_n = 0
        self._ticks_recorded = 0
        self._btc_24h_change: float | None = None
        self._cmc_global: dict[str, Any] = {}

    def filter_news_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for it in items:
            ok, reason = _credibility_score(it)
            if ok:
                row = dict(it)
                row["pool_credibility"] = "verified"
                out.append(row)
                self._news_accepted += 1
            else:
                self._news_rejected += 1
                row = dict(it)
                row["pool_reject_reason"] = reason
        self._news_verified = out[:48]
        return out

    def refresh_news(self, *, force: bool = False) -> list[dict[str, Any]]:
        from elite_trader.evrim_news_feed import fetch_news_items

        raw = fetch_news_items(force=force)
        filtered = self.filter_news_items(raw)
        self._last_news_ts = time.time()
        return filtered

    def load_external_bundle(self) -> None:
        path = os.getenv("MARKET_INTEL_EXTERNAL_JSON", "").strip()
        if not path:
            p = _ROOT / "data" / "market_intel_external.json"
            if p.is_file():
                path = str(p)
            else:
                return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return
        self._last_external_ts = time.time()
        quotes = data.get("quotes") if isinstance(data, dict) else None
        if isinstance(quotes, list):
            for q in quotes:
                sym = str(q.get("symbol") or "").upper()
                px = float(q.get("price") or 0)
                if sym and px > 0:
                    self._external_quotes[sym] = px
        flows = data.get("flows") if isinstance(data, dict) else None
        if isinstance(flows, list):
            self._flows = [f for f in flows if isinstance(f, dict)][:80]
        news = data.get("news") if isinstance(data, dict) else None
        if isinstance(news, list):
            self.filter_news_items(
                [
                    {
                        "title": n.get("title") or n.get("headline"),
                        "source": n.get("source") or "external_json",
                        "sentiment": n.get("sentiment"),
                        "verified": n.get("verified"),
                        "fetched_at": n.get("fetched_at") or _now_iso(),
                    }
                    for n in news
                    if n.get("title") or n.get("headline")
                ]
            )

    def refresh_intelligence(self, *, force: bool = False) -> None:
        self.refresh_news(force=force)
        self.load_external_bundle()
        self._persist_evrim_radar_feed()

    def refresh_coingecko(self, client: Any) -> None:
        """Cold-path CoinGecko quotes — bias/meta only, never execution price."""
        prices = getattr(client, "_majors_cache", {}).get("prices") or {}
        if not prices:
            return
        self._last_external_ts = time.time()
        for sym, px in prices.items():
            if px and float(px) > 0:
                self._external_quotes[str(sym).upper()] = float(px)
        self._btc_24h_change = getattr(client, "btc_24h_change", lambda: None)()

    def refresh_coinmarketcap(self, client: Any) -> None:
        """Cold-path CMC rank/quotes — meta only."""
        quotes = getattr(client, "_quotes", {}) or {}
        if not quotes:
            return
        self._last_external_ts = time.time()
        for sym, row in quotes.items():
            px = float((row or {}).get("price") or 0)
            if px > 0:
                self._external_quotes[str(sym).upper()] = px
        self._cmc_global = getattr(client, "_global", {}) or {}

    def btc_macro_bias(self) -> float | None:
        """BTC 24h % — stake/regime bias hint only."""
        ch = getattr(self, "_btc_24h_change", None)
        return float(ch) if ch is not None else None

    def _persist_evrim_radar_feed(self) -> None:
        """Evrim radar state — profil ayarı değil, okuma amaçlı."""
        if not self._news_verified:
            return
        try:
            from elite_trader.evrim_news_feed import build_radar_news_feed
            from elite_trader.evrim_training import (
                _save_training_state,
                load_training_state,
            )

            feed = build_radar_news_feed(self._news_verified)
            st = load_training_state()
            st["radar_news_feed"] = feed
            st["radar_news_last_fetch"] = _now_iso()
            st["market_intel_pool"] = {
                "news_verified_n": len(self._news_verified),
                "news_rejected_n": self._news_rejected,
                "updated_at": _now_iso(),
            }
            _save_training_state(st)
        except Exception:
            pass

    def record_tick(
        self,
        symbol: str,
        price: float,
        price_history: dict[str, list],
    ) -> None:
        from elite_trader.signal_paths import update_price_history

        if price > 0:
            update_price_history(symbol, price, price_history)
            self._ticks_recorded += 1

    def ingest_bulk_prices(self, prices: dict[str, float]) -> None:
        self._last_bulk_n = len(prices)

    def build_candidate(
        self,
        symbol: str,
        price: float,
        price_history: dict[str, list],
    ) -> dict[str, Any] | None:
        from elite_trader.signal_paths import build_raw_momentum_candidate_flex

        cand = build_raw_momentum_candidate_flex(symbol, price, price_history)
        if not cand:
            return None
        return self.enrich_candidate(cand)

    def enrich_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        sym = str(candidate.get("symbol") or "")
        ctx = self._symbol_context(sym)
        out = dict(candidate)
        out["pool_channel"] = "market_intelligence"
        out["pool_news_sentiment"] = ctx.get("news_sentiment")
        out["pool_flow_bias"] = ctx.get("flow_bias")
        out["pool_headline"] = ctx.get("headline")
        ext = self._external_quotes.get(sym)
        if ext and float(candidate.get("price") or 0) > 0:
            ref = float(candidate["price"])
            out["pool_cross_px_delta_pct"] = round((ext - ref) / ref * 100, 4)
        return out

    def _symbol_context(self, symbol: str) -> dict[str, Any]:
        base = symbol.replace("USDT", "").upper()
        sent_scores: list[float] = []
        headline = None
        for it in self._news_verified[:24]:
            t = (it.get("title") or "").upper()
            if base and base not in t and base not in (it.get("symbols") or []):
                continue
            s = str(it.get("sentiment") or "neutral")
            if s == "bullish":
                sent_scores.append(1.0)
            elif s == "bearish":
                sent_scores.append(-1.0)
            elif s == "uncertain":
                sent_scores.append(0.0)
            if headline is None:
                headline = (it.get("title") or "")[:120]
        flow_bias = 0.0
        for fl in self._flows:
            fs = str(fl.get("symbol") or "").upper()
            if fs and fs not in (symbol, base):
                continue
            net = float(fl.get("net_usd") or 0)
            if net > 0:
                flow_bias += 1.0
            elif net < 0:
                flow_bias -= 1.0
        news_sent = None
        if sent_scores:
            avg = sum(sent_scores) / len(sent_scores)
            news_sent = "bullish" if avg > 0.25 else "bearish" if avg < -0.25 else "neutral"
        elif self._news_verified:
            top = self._news_verified[0]
            news_sent = str(top.get("sentiment") or "neutral")
            headline = headline or (top.get("title") or "")[:120]
        return {
            "news_sentiment": news_sent,
            "flow_bias": flow_bias if flow_bias else None,
            "headline": headline,
        }

    def snapshot(self) -> dict[str, Any]:
        top_news = [
            {
                "title": (n.get("title") or "")[:100],
                "source": n.get("source"),
                "sentiment": n.get("sentiment"),
            }
            for n in self._news_verified[:6]
        ]
        return {
            "channel": "market_intelligence",
            "updated_at": _now_iso(),
            "ticks_recorded": self._ticks_recorded,
            "last_bulk_symbols": self._last_bulk_n,
            "news_verified_n": len(self._news_verified),
            "news_rejected_n": self._news_rejected,
            "news_accepted_n": self._news_accepted,
            "external_quotes_n": len(self._external_quotes),
            "flows_n": len(self._flows),
            "btc_24h_change": getattr(self, "_btc_24h_change", None),
            "cmc_global": getattr(self, "_cmc_global", {}),
            "last_news_refresh_ts": self._last_news_ts,
            "top_headlines": top_news,
            "note": (
                "Ortak havuz — mod ayarları değişmez; her mod kendi filtresiyle okur."
            ),
        }


_HUB: MarketIntelligenceHub | None = None


def get_hub() -> MarketIntelligenceHub:
    global _HUB
    if _HUB is None:
        _HUB = MarketIntelligenceHub()
    return _HUB
