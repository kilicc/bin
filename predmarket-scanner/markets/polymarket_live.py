"""Polymarket live client — read-only public endpoints.

Tasarim:
  - READ: data-api.polymarket.com/* (auth gerekmez, user= query param)
  - READ: gamma-api.polymarket.com/* (public market metadata)
  - READ: clob.polymarket.com/* (public order book / midpoint)

Canlı emir (CLOB): repoda `live_clob.py` + `momentum_scanner` (`POLYMARKET_LIVE_TRADING`
ve onay ifadesi). Paket: `py-clob-client-v2`. Resmi API özeti:
  https://docs.polymarket.com/api-reference/introduction

Relayer v2 (gazsız tx): `relayer_client.py` — `RELAYER_API_KEY` + `RELAYER_API_KEY_ADDRESS`
header'ları; `POST /submit`, `GET /transaction?id=`.
  https://docs.polymarket.com/api-reference/relayer/submit-a-transaction
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import httpx


GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"


def resolve_proxy_wallet(signer_address: str, client: httpx.Client | None = None) -> str | None:
    """
    Gamma public-profile → proxyWallet (Polymarket'te bakiye/pozisyon bu adreste).
  İmzalayan EOA ile aynı değil.
    """
    addr = (signer_address or "").strip().lower()
    if not addr.startswith("0x") or len(addr) != 42:
        return None
    own = client
    if own is None:
        with httpx.Client(timeout=12.0, headers={"Accept": "application/json"}) as c:
            return resolve_proxy_wallet(addr, c)
    try:
        r = own.get(
            f"{GAMMA_BASE}/public-profile",
            params={"address": addr},
        )
        if r.status_code != 200:
            return None
        data = r.json()
        pw = (data.get("proxyWallet") or data.get("proxy_wallet") or "").strip()
        if pw.startswith("0x") and len(pw) == 42:
            return pw.lower()
    except httpx.HTTPError:
        pass
    return None


def fetch_portfolio_snapshot(user_address: str, client: httpx.Client) -> dict:
    """Data API: cash value + pozisyon sayısı (tek adres)."""
    user = user_address.strip().lower()
    out: dict = {"address": user, "value_usd": 0.0, "positions": 0, "trades_sample": 0}
    try:
        vr = client.get(f"{DATA_API_BASE}/value", params={"user": user}, timeout=12.0)
        if vr.status_code == 200:
            data = vr.json()
            if isinstance(data, list) and data:
                out["value_usd"] = float(data[0].get("value") or 0)
            elif isinstance(data, dict):
                out["value_usd"] = float(data.get("value") or 0)
    except (httpx.HTTPError, TypeError, ValueError):
        pass
    try:
        pr = client.get(
            f"{DATA_API_BASE}/positions",
            params={"user": user, "sizeThreshold": "0"},
            timeout=12.0,
        )
        if pr.status_code == 200:
            data = pr.json()
            out["positions"] = len(data) if isinstance(data, list) else 0
    except httpx.HTTPError:
        pass
    return out


@dataclass(frozen=True)
class LiveCredentials:
    """Read-only icin sadece signer_address gerekli. Order placement icin api_key + secret + passphrase."""
    api_key: str               # UUID — read-only icin opsiyonel, order icin gerekli
    api_key_address: str
    signer_address: str

    @classmethod
    def _valid_eth_address(cls, addr: str) -> bool:
        a = (addr or "").strip()
        return bool(a) and a.startswith("0x") and len(a) == 42

    @classmethod
    def from_env(cls) -> "LiveCredentials":
        ak = os.getenv("RELAYER_API_KEY", "").strip()
        ak_addr = os.getenv("RELAYER_API_KEY_ADDRESS", "").strip()
        signer = os.getenv("SIGNER_ADDRESS", "").strip()
        deposit = (
            os.getenv("POLYMARKET_DEPOSIT_WALLET") or os.getenv("POLYMARKET_PROXY_WALLET") or ""
        ).strip().lower()
        # Sık hata: UUID veya deposit wallet'ı RELAYER_API_KEY_ADDRESS'e yazmak
        if not cls._valid_eth_address(ak_addr) and cls._valid_eth_address(signer):
            ak_addr = signer
        elif (
            cls._valid_eth_address(ak_addr)
            and cls._valid_eth_address(signer)
            and deposit
            and ak_addr.lower() == deposit
        ):
            ak_addr = signer  # Relayer key sahibi = imzalayan, proxy değil
        if not cls._valid_eth_address(ak_addr):
            raise ValueError(
                "RELAYER_API_KEY_ADDRESS imzalayan Ethereum adresi olmali (0x + 40 hex, 42 karakter). "
                "API Key UUID'sini buraya yazma; Polymarket'teki Signer Address ile ayni olmali. "
                "Ornek: SIGNER_ADDRESS=0xc57a... ise RELAYER_API_KEY_ADDRESS de ayni deger."
            )
        return cls(
            api_key=ak or "",
            api_key_address=ak_addr,
            signer_address=signer or ak_addr,
        )


class PolymarketLive:
    """Read-only Polymarket client.

    Tum read endpoint'leri public — auth gerekmez, sadece signer_address ile.
    Order placement guard'li.
    """

    def __init__(self, creds: Optional[LiveCredentials] = None, timeout: float = 15.0):
        self.creds = creds or LiveCredentials.from_env()
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": "predmarket-scanner/0.1",
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ----- HEALTH ------------------------------------------------------------

    def proxy_wallet(self) -> str | None:
        """Polymarket proxy / deposit wallet (gamma profile)."""
        env_pw = (os.getenv("POLYMARKET_DEPOSIT_WALLET") or os.getenv("POLYMARKET_PROXY_WALLET") or "").strip()
        if env_pw.startswith("0x") and len(env_pw) == 42:
            return env_pw.lower()
        return resolve_proxy_wallet(self.creds.signer_address, self._client)

    def health(self) -> dict:
        """Public data-api'ye gecerli bir kullanici sorgusu — auth yok, dogrudan veri."""
        try:
            r = self._client.get(
                f"{DATA_API_BASE}/value",
                params={"user": self.creds.signer_address.lower()},
                timeout=8.0,
            )
            ok = r.status_code == 200
            return {"ok": ok, "status": r.status_code, "body": r.json() if ok else r.text}
        except httpx.HTTPError as e:
            return {"ok": False, "error": str(e)}

    def fetch_portfolio_for_user(self, address: str) -> dict:
        return fetch_portfolio_snapshot(address, self._client)

    # ----- READ-ONLY ---------------------------------------------------------

    def fetch_positions_for(self, user_address: str) -> list[dict]:
        r = self._client.get(
            f"{DATA_API_BASE}/positions",
            params={"user": user_address.lower(), "sizeThreshold": "0"},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else (data.get("data") or [])

    def fetch_positions(self) -> list[dict]:
        pw = self.proxy_wallet()
        user = (pw or self.creds.signer_address).lower()
        return self.fetch_positions_for(user)

    def fetch_value(self) -> dict:
        pw = self.proxy_wallet()
        user = (pw or self.creds.signer_address).lower()
        r = self._client.get(f"{DATA_API_BASE}/value", params={"user": user})
        r.raise_for_status()
        return r.json()

    def fetch_trade_history_for(self, user_address: str, limit: int = 100) -> list[dict]:
        r = self._client.get(
            f"{DATA_API_BASE}/trades",
            params={"user": user_address.lower(), "limit": limit},
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else (data.get("data") or [])

    def fetch_trade_history(self, limit: int = 100) -> list[dict]:
        pw = self.proxy_wallet()
        user = (pw or self.creds.signer_address).lower()
        return self.fetch_trade_history_for(user, limit=limit)

    def fetch_active_markets(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Gamma'dan aktif piyasalar — listing icin."""
        r = self._client.get(
            f"{GAMMA_BASE}/markets",
            params={"active": "true", "closed": "false", "limit": limit, "offset": offset},
        )
        r.raise_for_status()
        return r.json() or []

    def fetch_clob_book(self, token_id: str) -> dict:
        """CLOB order book bir outcome token icin."""
        r = self._client.get(f"{CLOB_BASE}/book", params={"token_id": token_id})
        r.raise_for_status()
        return r.json()

    # ----- ORDER PLACEMENT — KILITLI -----------------------------------------

    def place_order(self, *args, **kwargs) -> None:
        """Bu sınıf read-only. Emirler `live_clob.py` üzerinden `momentum_scanner` ile verilir."""
        raise NotImplementedError(
            "Canlı CLOB: `pip install py-clob-client-v2`, ortam "
            "`POLYMARKET_PRIVATE_KEY`, `POLYMARKET_DEPOSIT_WALLET`, "
            "`POLYMARKET_LIVE_TRADING=1`, `POLYMARKET_LIVE_CONFIRM=I_UNDERSTAND_REAL_MONEY_LOSS`. "
            "Bkz. `live_clob.py` ve https://docs.polymarket.com/developers/CLOB/quickstart"
        )
