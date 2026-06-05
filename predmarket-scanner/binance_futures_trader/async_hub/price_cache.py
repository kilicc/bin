"""Hot-path price cache — read-only dict snapshots for position tick."""
from __future__ import annotations

import threading
import time
from typing import Any


class HotPriceCache:
    """Thread-safe mark + mid prices with recv timestamps."""

    __slots__ = (
        "_lock",
        "_mark",
        "_mid",
        "_mark_ts",
        "_mid_ts",
        "_last_recv_ms",
        "_book_lag_ms",
        "_mark_lag_ms",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mark: dict[str, float] = {}
        self._mid: dict[str, float] = {}
        self._mark_ts: dict[str, int] = {}
        self._mid_ts: dict[str, int] = {}
        self._last_recv_ms: int = 0
        self._book_lag_ms: int | None = None
        self._mark_lag_ms: int | None = None

    def update_mark(self, coin: str, price: float, event_ms: int | None = None) -> None:
        if price <= 0:
            return
        key = coin.upper()
        recv = int(time.time() * 1000)
        with self._lock:
            self._mark[key] = float(price)
            self._mark_ts[key] = int(event_ms or recv)
            self._last_recv_ms = recv
            self._mark_lag_ms = max(0, recv - self._mark_ts[key])

    def update_mid(self, coin: str, bid: float, ask: float, ts_ms: int | None = None) -> None:
        if bid <= 0 or ask <= 0:
            return
        key = coin.upper()
        mid = (bid + ask) / 2.0
        recv = int(time.time() * 1000)
        ts = int(ts_ms or recv)
        with self._lock:
            self._mid[key] = mid
            self._mid_ts[key] = ts
            self._last_recv_ms = recv
            self._book_lag_ms = max(0, recv - ts)

    def ingest_rest_marks(self, prices: dict[str, float]) -> None:
        if not prices:
            return
        recv = int(time.time() * 1000)
        with self._lock:
            for coin, px in prices.items():
                if px and float(px) > 0:
                    k = str(coin).upper()
                    self._mark[k] = float(px)
                    self._mark_ts[k] = recv
            self._last_recv_ms = recv

    def get_prices_for_coins(
        self,
        coins: list[str],
        *,
        max_age_ms: float = 900,
    ) -> dict[str, float]:
        if not coins:
            return {}
        now_ms = int(time.time() * 1000)
        age = int(max(60, max_age_ms))
        out: dict[str, float] = {}
        with self._lock:
            bulk_fresh = (
                self._last_recv_ms > 0
                and (now_ms - self._last_recv_ms) <= 90_000
            )
            if bulk_fresh and self._mark:
                for coin in coins:
                    key = str(coin).upper()
                    px = self._mid.get(key) or self._mark.get(key)
                    if not px or float(px) <= 0:
                        continue
                    ts = self._mid_ts.get(key) or self._mark_ts.get(key) or 0
                    if bulk_fresh or (ts and (now_ms - ts) <= age):
                        out[coin] = float(px)
                if len(out) >= len(coins):
                    return out
            for coin in coins:
                if coin in out:
                    continue
                key = str(coin).upper()
                d_mid = self._mid.get(key)
                ts_mid = self._mid_ts.get(key, 0)
                if d_mid and (now_ms - ts_mid) <= age:
                    out[coin] = float(d_mid)
                    continue
                d_mark = self._mark.get(key)
                ts_mark = self._mark_ts.get(key, 0)
                if d_mark and (now_ms - ts_mark) <= age:
                    out[coin] = float(d_mark)
        return out

    def get_all_marks_if_fresh(self, *, max_recv_age_sec: float = 90) -> dict[str, float]:
        now_ms = int(time.time() * 1000)
        with self._lock:
            if not self._mark:
                return {}
            if self._last_recv_ms and (now_ms - self._last_recv_ms) <= max_recv_age_sec * 1000:
                return {k: float(v) for k, v in self._mark.items() if v and float(v) > 0}
            out: dict[str, float] = {}
            for k, v in self._mark.items():
                ts = self._mark_ts.get(k, 0)
                if ts and (now_ms - ts) <= max_recv_age_sec * 1000:
                    out[k] = float(v)
            return out

    def get_all_prices_bulk(self, *, max_recv_age_sec: float = 60) -> dict[str, float]:
        """Motor/tick — mid önce (sub-s), mark yedek."""
        now_ms = int(time.time() * 1000)
        max_age = int(max_recv_age_sec * 1000)
        out: dict[str, float] = {}
        with self._lock:
            recv_fresh = self._last_recv_ms and (now_ms - self._last_recv_ms) <= max_age
            if not recv_fresh and not self._mid and not self._mark:
                return {}
            for k, mid in self._mid.items():
                ts = self._mid_ts.get(k, 0)
                if recv_fresh or (ts and (now_ms - ts) <= max_age):
                    if mid and float(mid) > 0:
                        out[k] = float(mid)
            for k, mark in self._mark.items():
                if k in out:
                    continue
                ts = self._mark_ts.get(k, 0)
                if recv_fresh or (ts and (now_ms - ts) <= max_age):
                    if mark and float(mark) > 0:
                        out[k] = float(mark)
        return out

    def get_all_mids_snapshot(self, *, max_age_ms: float = 900) -> dict[str, dict[str, float | int]]:
        """bookTicker-compatible mid snapshot for legacy fast_price_ws callers."""
        now_ms = int(time.time() * 1000)
        age = int(max(60, max_age_ms))
        out: dict[str, dict[str, float | int]] = {}
        with self._lock:
            for k, mid in self._mid.items():
                ts = self._mid_ts.get(k, 0)
                if ts and (now_ms - ts) <= age and mid > 0:
                    m = float(mid)
                    out[k] = {"bid": m, "ask": m, "mid": m, "ts_ms": ts}
        return out

    def trim_to_coins(self, allowed: set[str] | list[str]) -> int:
        """BERSERK2/lite — 712 coin RAM şişmesini kes; yalnız izlenen coinler kalsın."""
        keep: set[str] = set()
        for raw in allowed:
            c = str(raw or "").upper().replace("USDT", "").strip()
            if c:
                keep.add(c)
        if not keep:
            return 0
        removed = 0
        with self._lock:
            for store in (self._mark, self._mid, self._mark_ts, self._mid_ts):
                for k in list(store.keys()):
                    if str(k).upper() not in keep:
                        store.pop(k, None)
                        removed += 1
        return removed

    def status(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        with self._lock:
            n_mark = len(self._mark)
            n_mid = len(self._mid)
            last = self._last_recv_ms
            blag = self._book_lag_ms
            mlag = self._mark_lag_ms
        lag = (now_ms - last) if last else None
        ok = (n_mark > 0 or n_mid > 0) and lag is not None and lag < 5000
        return {
            "ok": ok,
            "mark_coins": n_mark,
            "mid_coins": n_mid,
            "lag_ms": lag,
            "book_lag_ms": blag,
            "mark_lag_ms": mlag,
            "last_recv_ms": last,
        }
