"""
Polymarket Relayer v2 — gazsız zincir işlemleri (submit + poll).

Resmi sözleşme:
  https://docs.polymarket.com/api-reference/relayer/submit-a-transaction
  https://docs.polymarket.com/api-reference/relayer/get-a-transaction-by-id
  OpenAPI: https://docs.polymarket.com/api-spec/relayer-openapi.yaml
  Base URL: https://relayer-v2.polymarket.com

Kimlik (Relayer API key):
  Header: RELAYER_API_KEY
  Header: RELAYER_API_KEY_ADDRESS  (anahtarı sahip adres — dokümandaki gibi)

Not: CLOB limit/market emirleri `live_clob.py` + `clob.polymarket.com` üzerinden;
Relayer ise imzalı `from` / `proxyWallet` / `data` / `nonce` gövdeleriyle on-chain
SAFE/PROXY çağrılarını gazsız yürütmek içindir (split/redeem/approve vb. akışlar).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

DeployedWalletType = Literal["SAFE", "WALLET"]
NonceKind = Literal["PROXY", "SAFE"]


DEFAULT_RELAYER_BASE = "https://relayer-v2.polymarket.com"


@dataclass(frozen=True)
class RelayerApiCredentials:
    api_key: str
    api_key_address: str

    @classmethod
    def _valid_eth_address(cls, addr: str) -> bool:
        a = (addr or "").strip()
        return bool(a) and a.startswith("0x") and len(a) == 42

    @classmethod
    def from_env(cls) -> "RelayerApiCredentials | None":
        key = (os.getenv("RELAYER_API_KEY") or "").strip()
        addr = (os.getenv("RELAYER_API_KEY_ADDRESS") or "").strip()
        signer = (os.getenv("SIGNER_ADDRESS") or "").strip()
        if not key:
            return None
        deposit = (
            os.getenv("POLYMARKET_DEPOSIT_WALLET") or os.getenv("POLYMARKET_PROXY_WALLET") or ""
        ).strip().lower()
        if not cls._valid_eth_address(addr) and cls._valid_eth_address(signer):
            addr = signer
        elif (
            cls._valid_eth_address(addr)
            and cls._valid_eth_address(signer)
            and deposit
            and addr.lower() == deposit
        ):
            addr = signer
        if not cls._valid_eth_address(addr):
            return None
        return cls(api_key=key, api_key_address=addr)


class RelayerV2Client:
    """Thin HTTP client for relayer-v2.polymarket.com (Relayer API key auth)."""

    def __init__(
        self,
        creds: RelayerApiCredentials,
        *,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._creds = creds
        self._base = (base_url or os.getenv("POLY_RELAYER_BASE_URL") or DEFAULT_RELAYER_BASE).rstrip(
            "/"
        )
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "User-Agent": "predmarket-scanner-relayer/0.1",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "RELAYER_API_KEY": creds.api_key,
                "RELAYER_API_KEY_ADDRESS": creds.api_key_address,
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RelayerV2Client":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def submit(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /submit — döner: transactionID, state (örn. STATE_NEW)."""
        r = self._client.post(f"{self._base}/submit", json=body)
        r.raise_for_status()
        out = r.json()
        if not isinstance(out, dict):
            raise ValueError("Relayer /submit beklenmeyen cevap")
        return out

    def get_transaction(self, transaction_id: str) -> list[dict[str, Any]]:
        """GET /transaction?id= — çoğunlukla tek elemanlı dizi."""
        r = self._client.get(f"{self._base}/transaction", params={"id": transaction_id})
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    def list_transactions(self) -> list[dict[str, Any]]:
        """GET /transactions — son relayer işlemleri (auth ile kullanıcıya göre)."""
        r = self._client.get(f"{self._base}/transactions")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return []

    def get_nonce(self, address: str, kind: NonceKind) -> dict[str, Any]:
        """GET /nonce?address=&type=PROXY|SAFE"""
        r = self._client.get(
            f"{self._base}/nonce",
            params={"address": address, "type": kind},
        )
        r.raise_for_status()
        out = r.json()
        if not isinstance(out, dict):
            raise ValueError("Relayer /nonce beklenmeyen cevap")
        return out

    def relay_payload(self, address: str, kind: NonceKind) -> dict[str, Any]:
        """GET /relay-payload — relayer adresi + nonce."""
        r = self._client.get(
            f"{self._base}/relay-payload",
            params={"address": address, "type": kind},
        )
        r.raise_for_status()
        out = r.json()
        if not isinstance(out, dict):
            raise ValueError("Relayer /relay-payload beklenmeyen cevap")
        return out

    def deployed(self, address: str, wallet_type: DeployedWalletType | None = None) -> dict[str, Any]:
        """GET /deployed?address=&type=SAFE|WALLET (type atlanırsa SAFE)."""
        params: dict[str, str] = {"address": address}
        if wallet_type is not None:
            params["type"] = wallet_type
        r = self._client.get(f"{self._base}/deployed", params=params)
        r.raise_for_status()
        out = r.json()
        if not isinstance(out, dict):
            raise ValueError("Relayer /deployed beklenmeyen cevap")
        return out

    def poll_transaction(
        self,
        transaction_id: str,
        *,
        timeout_sec: float = 120.0,
        interval_sec: float = 2.0,
        terminal_states: frozenset[str] = frozenset(
            ("STATE_CONFIRMED", "STATE_FAILED", "STATE_INVALID")
        ),
    ) -> list[dict[str, Any]]:
        """
        GET /transaction ile transactionHash veya terminal state gelene kadar bekler.
        """
        deadline = time.monotonic() + timeout_sec
        last: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            last = self.get_transaction(transaction_id)
            if last:
                st = str(last[0].get("state", ""))
                if st in terminal_states:
                    return last
                if last[0].get("transactionHash"):
                    return last
            time.sleep(interval_sec)
        return last


def relayer_from_env() -> RelayerV2Client | None:
    c = RelayerApiCredentials.from_env()
    if c is None:
        return None
    return RelayerV2Client(c)


if __name__ == "__main__":
    _creds = RelayerApiCredentials.from_env()
    if _creds is None:
        print("RELAYER_API_KEY ve RELAYER_API_KEY_ADDRESS .env içinde tanımlı değil.")
        raise SystemExit(1)
    with RelayerV2Client(_creds) as c:
        print("deployed (SAFE):", c.deployed(_creds.api_key_address, "SAFE"))
        txs = c.list_transactions()
        print(f"recent transactions: {len(txs)}")
