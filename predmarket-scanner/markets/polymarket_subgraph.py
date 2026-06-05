"""Polymarket subgraph fetcher — gerçek WalletTrade üretir.

Polymarket'in resmi subgraph'ı (Polygon, The Graph):
  https://api.thegraph.com/subgraphs/name/polymarket/matic-markets

Bu modül:
  - 90 günlük geri trade'leri pagination ile çeker
  - Order/Trade event'lerini WalletTrade tipine normalize eder
  - Watch-list ile filtre yapabilir

UYARI: Subgraph şemaları zamanla değişir. İlk çalıştırmada query schema'ya
karşı doğrulayıcı bir GET introspection yap. Aşağıdaki query Polymarket'in
"OrdersMatchedEvent" / "FpmmTrade" yapısına göre yazıldı — kullandığın sürüm
farklıysa field adlarını düzelt.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Iterator, Optional

import httpx

from .wallets import WalletTrade


DEFAULT_ENDPOINT = "https://api.thegraph.com/subgraphs/name/polymarket/matic-markets"

# FpmmTrade query — Polymarket'in Fixed Product Market Maker üzerindeki tüm trade'ler.
# Field names: id, type (Buy|Sell), creator, fpmm.id, outcomeIndex, outcomeTokensTraded,
# investmentAmount/feeAmount/collateralTokenAmount, creationTimestamp, transactionHash.
TRADE_QUERY = """
query FpmmTrades($first: Int!, $skip: Int!, $minTs: BigInt!, $users: [Bytes!]) {
  fpmmTrades(
    first: $first
    skip: $skip
    orderBy: creationTimestamp
    orderDirection: desc
    where: { creationTimestamp_gte: $minTs %USER_FILTER% }
  ) {
    id
    type
    creator { id }
    fpmm { id question }
    outcomeIndex
    outcomeTokensTraded
    collateralAmount
    feeAmount
    creationTimestamp
    transactionHash
  }
}
""".strip()


class SubgraphError(Exception):
    pass


class PolymarketSubgraph:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = 30.0,
        page_size: int = 1000,
        sleep_between_pages: float = 0.25,
    ):
        self.endpoint = endpoint
        self.page_size = page_size
        self.sleep_between_pages = sleep_between_pages
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "predmarket-scanner/0.1"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- Core --------------------------------------------------------------

    def _execute(self, query: str, variables: dict) -> dict:
        resp = self._client.post(self.endpoint, json={"query": query, "variables": variables})
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            raise SubgraphError(str(body["errors"]))
        return body["data"]

    # --- Trades ------------------------------------------------------------

    def iter_trades(
        self,
        since: datetime,
        watch_list: Optional[Iterable[str]] = None,
        max_pages: int = 200,
    ) -> Iterator[WalletTrade]:
        """`since` zamanından bu yana tüm trade'leri ver.

        `watch_list` verilirse sadece bu adreslerinkiler döner.
        """
        min_ts = int(since.replace(tzinfo=timezone.utc).timestamp()) if since.tzinfo is None \
                 else int(since.timestamp())

        if watch_list:
            users_arr = [a.lower() for a in watch_list]
            user_filter = ", creator_in: $users"
            base_vars = {"users": users_arr}
        else:
            user_filter = ""
            base_vars = {}

        query = TRADE_QUERY.replace("%USER_FILTER%", user_filter)

        for page in range(max_pages):
            variables = {
                "first": self.page_size,
                "skip": page * self.page_size,
                "minTs": str(min_ts),
                **base_vars,
            }
            try:
                data = self._execute(query, variables)
            except (httpx.HTTPError, SubgraphError) as e:
                print(f"[subgraph] page {page} error: {e}")
                return
            trades = data.get("fpmmTrades") or []
            if not trades:
                return
            for raw in trades:
                t = self._parse(raw)
                if t is not None:
                    yield t
            if len(trades) < self.page_size:
                return
            time.sleep(self.sleep_between_pages)

    # --- Parse -------------------------------------------------------------

    def _parse(self, raw: dict) -> Optional[WalletTrade]:
        try:
            creator = (raw.get("creator") or {}).get("id")
            fpmm = (raw.get("fpmm") or {}).get("id")
            if not creator or not fpmm:
                return None

            # Polymarket binary: outcomeIndex 0=YES, 1=NO (konvansiyon)
            idx = int(raw.get("outcomeIndex", 0))
            side = "YES" if idx == 0 else "NO"

            tokens = float(raw.get("outcomeTokensTraded") or 0) / 1e6   # USDC has 6 decimals
            collateral = float(raw.get("collateralAmount") or 0) / 1e6
            if tokens <= 0:
                return None

            # Buy: USDC ödenir, outcome token alınır → price = collateral / tokens
            # Sell: outcome token verilir, USDC alınır → price = collateral / tokens
            price = collateral / tokens if tokens > 0 else 0.0
            price = max(0.001, min(0.999, price))

            ts = int(raw.get("creationTimestamp") or 0)
            timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)

            direction = "open" if str(raw.get("type", "")).lower() == "buy" else "close"

            return WalletTrade(
                wallet=str(creator).lower(),
                market_id=str(fpmm).lower(),
                side=side,
                price=price,
                size_usd=collateral,
                direction=direction,
                timestamp=timestamp,
                tx_hash=raw.get("transactionHash"),
            )
        except Exception:
            return None

    # --- Convenience -------------------------------------------------------

    def fetch_history(self, days: int = 90, watch_list: Optional[Iterable[str]] = None) -> list[WalletTrade]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        return list(self.iter_trades(since=since, watch_list=watch_list))


def make_live_fetcher(endpoint: str = DEFAULT_ENDPOINT) -> Callable[[Iterable[str], datetime], Iterable[WalletTrade]]:
    """`WhaleTracker`'a verilebilecek hazır fetcher."""
    def _fetcher(watch_list: Iterable[str], since: datetime) -> Iterable[WalletTrade]:
        with PolymarketSubgraph(endpoint=endpoint) as sg:
            yield from sg.iter_trades(since=since, watch_list=watch_list, max_pages=5)
    return _fetcher
