"""Polymarket Data API trade fetcher — subgraph yerine bu.

The Graph hosted service kapandığı için Polymarket'in kendi data-api'sini
kullanıyoruz. Endpoint public, auth gerekmez, rate limit makul.

Şema (data-api.polymarket.com/trades):
  proxyWallet      → wallet adresi
  conditionId      → market id (binary'de bu hash, gamma'daki id ile uyumsuz olabilir)
  outcome          → "Yes" | "No"
  outcomeIndex     → 0=Yes, 1=No (binary için)
  side             → "BUY" | "SELL" (outcome token üzerinde)
  size             → outcome token miktarı (USDC.e değil)
  price            → [0,1] aralığında
  timestamp        → Unix int
  transactionHash  → 0x...
  title/slug/event → metadata

Polymarket'te BUY = pozisyon aç, SELL = pozisyon kapat.
YES/NO yönü `outcome` field'ından geliyor (BUY 'Yes' = YES pozisyonu aç).
size_usd = size * price (size kontrat sayısı, USDC.e karşılığı çarpım).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Iterator, Optional

import httpx

from .wallets import WalletTrade


DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"

# Polymarket data-api 3500'den büyük offset'i reddediyor (400 Bad Request).
# Bunun altında kalmamız için.
MAX_OFFSET = 3000


class PolymarketDataAPI:
    def __init__(self, base_url: str = DATA_API_BASE, timeout: float = 20.0,
                 page_size: int = 500, sleep_between_pages: float = 0.30):
        self.base_url = base_url.rstrip("/")
        self.page_size = min(page_size, 500)  # data-api default cap
        self.sleep_between_pages = sleep_between_pages
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": "predmarket-scanner/0.2",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- Core endpoint --------------------------------------------------------

    def _fetch_page(self, offset: int, user: Optional[str] = None,
                    market: Optional[str] = None) -> list[dict]:
        params: dict[str, str | int] = {"limit": self.page_size, "offset": offset}
        if user:
            params["user"] = user.lower()
        if market:
            params["market"] = market
        try:
            r = self._client.get(f"{self.base_url}/trades", params=params)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                # Rate-limit; biraz uzun bekleme
                time.sleep(5)
                return []
            print(f"[data-api] offset={offset} {e}")
            return []
        except httpx.HTTPError as e:
            print(f"[data-api] offset={offset} {e}")
            return []

    # --- Iterators ------------------------------------------------------------

    def iter_recent_trades(
        self,
        since: datetime,
        user: Optional[str] = None,
        market: Optional[str] = None,
        max_pages: int = 500,
    ) -> Iterator[WalletTrade]:
        """`since` zamanından bu yana tüm trade'leri ver.

        Data-api ~3500 kayıt sonra 400 Bad Request veriyor. MAX_OFFSET ile cap'liyoruz.
        Timestamp filter API'de yok → tüm sayfaları gez, client-side filtre uygula.
        """
        cutoff_ts = int(since.replace(tzinfo=timezone.utc).timestamp()) \
                    if since.tzinfo is None else int(since.timestamp())

        for page in range(max_pages):
            offset = page * self.page_size
            if offset > MAX_OFFSET:
                # API'nin 400 cap'ine ulaştık
                return
            batch = self._fetch_page(offset=offset, user=user, market=market)
            if not batch:
                return
            stopped_at_cutoff = False
            for raw in batch:
                ts = int(raw.get("timestamp") or 0)
                if ts < cutoff_ts:
                    # Bu trade cutoff'tan eski; daha eskiler de gelecek (DESC) → dur
                    stopped_at_cutoff = True
                    break
                t = self._parse(raw)
                if t is not None:
                    yield t
            if stopped_at_cutoff:
                return
            if len(batch) < self.page_size:
                return
            time.sleep(self.sleep_between_pages)

    def fetch_history(self, days: int = 90, user: Optional[str] = None,
                      max_pages: int = 500) -> list[WalletTrade]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        return list(self.iter_recent_trades(since=since, user=user, max_pages=max_pages))

    # --- Resolved outcomes (market resolution) -------------------------------

    @staticmethod
    def _parse_outcome(prices_raw) -> Optional[bool]:
        """outcomePrices field'ından kazanan tarafı çıkar.
        ["1","0"] → True (YES kazandı)
        ["0","1"] → False (NO kazandı)
        ["0","0"] → None (voided)
        ["0.5","0.5"] → None (refunded/draw)
        """
        import json as _json
        if isinstance(prices_raw, str):
            try:
                prices = _json.loads(prices_raw)
            except Exception:
                return None
        else:
            prices = prices_raw
        if not prices or len(prices) < 2:
            return None
        try:
            yes_p = float(prices[0])
            no_p = float(prices[1])
        except (ValueError, TypeError):
            return None
        if yes_p > 0.5 and no_p < 0.5:
            return True
        if yes_p < 0.5 and no_p > 0.5:
            return False
        return None  # voided veya draw

    def fetch_market_outcome(self, condition_id: str) -> Optional[bool]:
        """Tek market için lookup. Bulk için fetch_all_closed_markets kullan."""
        try:
            r = self._client.get(
                f"{GAMMA_BASE}/markets",
                params={"conditionIds": condition_id, "limit": 1},
            )
            r.raise_for_status()
            data = r.json()
            if not data:
                return None
            m = data[0]
            if not m.get("closed"):
                return None
            return self._parse_outcome(m.get("outcomePrices"))
        except Exception:
            return None

    def fetch_all_closed_markets(
        self,
        max_pages: int = 50,
        page_size: int = 500,
    ) -> dict[str, bool]:
        """Tüm kapanmış market'leri tek seferde çek. Bu fonksiyon dakikalar yerine
        saniyeler sürer çünkü gamma /markets?closed=true bulk endpoint.

        Returns:  {condition_id: True/False}  — voided market'ler dışında bırakılır.
        """
        outcomes: dict[str, bool] = {}
        for page in range(max_pages):
            offset = page * page_size
            try:
                r = self._client.get(
                    f"{GAMMA_BASE}/markets",
                    params={"closed": "true", "limit": page_size, "offset": offset},
                )
                r.raise_for_status()
                batch = r.json()
            except httpx.HTTPError as e:
                print(f"[gamma closed] page={page} {e}")
                break
            if not batch:
                break
            for m in batch:
                cid = (m.get("conditionId") or "").lower()
                if not cid:
                    continue
                outcome = self._parse_outcome(m.get("outcomePrices"))
                if outcome is not None:
                    outcomes[cid] = outcome
            if len(batch) < page_size:
                break
            time.sleep(0.15)
        return outcomes

    # --- Parser ---------------------------------------------------------------

    def _parse(self, raw: dict) -> Optional[WalletTrade]:
        try:
            wallet = raw.get("proxyWallet")
            condition_id = raw.get("conditionId")
            outcome = raw.get("outcome", "").lower()
            side_raw = raw.get("side", "").upper()
            size = float(raw.get("size") or 0)
            price = float(raw.get("price") or 0)
            ts = int(raw.get("timestamp") or 0)
            tx = raw.get("transactionHash")

            if not wallet or not condition_id or size <= 0 or price <= 0:
                return None
            if outcome not in ("yes", "no"):
                return None

            side_yes_no = "YES" if outcome == "yes" else "NO"
            direction = "open" if side_raw == "BUY" else "close"
            size_usd = size * price  # contracts * price = USDC.e karşılığı

            return WalletTrade(
                wallet=wallet.lower(),
                market_id=condition_id.lower(),
                side=side_yes_no,
                price=max(0.001, min(0.999, price)),
                size_usd=size_usd,
                direction=direction,
                timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                tx_hash=tx,
            )
        except Exception:
            return None


# --- Convenience for WhaleTracker ---------------------------------------------

def make_live_fetcher(base_url: str = DATA_API_BASE) \
        -> Callable[[Iterable[str], datetime], Iterable[WalletTrade]]:
    """Watch-list polling için fetcher (WhaleTracker'a verilebilir).

    data-api `user=` filter'ı tek wallet'a göre sorgular; watch-list için
    her wallet'ı ayrı ayrı çağırırız (rate-limit'e dikkat).
    """
    def _fetcher(watch_list: Iterable[str], since: datetime) -> Iterable[WalletTrade]:
        addresses = list(watch_list)
        with PolymarketDataAPI(base_url=base_url, sleep_between_pages=0.40) as api:
            for addr in addresses:
                yield from api.iter_recent_trades(since=since, user=addr, max_pages=5)
                time.sleep(0.20)  # rate-limit yumuşatması
    return _fetcher
