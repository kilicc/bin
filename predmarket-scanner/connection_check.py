"""Live connection sanity check — sadece read-only, emir göndermez.

Kullanım (.env hazırken):
  python connection_check.py

Çıktı:
  - Data API (value) — read-only
  - Relayer v2: /deployed, /transactions — submit ile aynı RELAYER_* header'ları
  - Portföy, pozisyonlar, son trade'ler

Bu script her zaman güvenli — hiçbir emir göndermez.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from markets.polymarket_live import LiveCredentials, PolymarketLive
from relayer_client import RelayerApiCredentials, RelayerV2Client


def main():
    print("=" * 70)
    print(" Polymarket Live Connection Check (READ-ONLY)")
    print("=" * 70)

    from markets.polymarket_geoblock import get_geoblock_status, is_trading_blocked

    geo = get_geoblock_status(force_refresh=True)
    blocked, gmsg = is_trading_blocked()
    print(f"\n[0] Geoblock (sunucu IP konumu)")
    print(f"    blocked={geo.get('blocked')}  country={geo.get('country')}  region={geo.get('region')}")
    print(f"    can_open_new_orders={not blocked}  ({gmsg})")
    print("    Not: TR listede yok → genelde blocked=false; US/DE/FR vb. blocked=true")

    # 1) Credentials
    try:
        creds = LiveCredentials.from_env()
    except ValueError as e:
        print(f"\n[X] Credentials error: {e}")
        print("\n.env dosyana ekle:")
        print("  RELAYER_API_KEY=<dashboard-uuid>")
        print("  RELAYER_API_KEY_ADDRESS=0x<42-char-hex>")
        print("  SIGNER_ADDRESS=0x<aynı veya proxy sahibi adres>")
        sys.exit(1)

    print(f"\n[1] Credentials yüklendi")
    print(f"    api_key:         {creds.api_key[:12]}...")
    print(f"    api_key_address: {creds.api_key_address}")
    print(f"    signer_address:  {creds.signer_address}")

    pk = (os.getenv("POLYMARKET_PRIVATE_KEY") or "").strip()
    dep = (os.getenv("POLYMARKET_DEPOSIT_WALLET") or "").strip()
    builder_code = (os.getenv("POLYMARKET_BUILDER_CODE") or "").strip()
    pk_hex = pk.lower().removeprefix("0x")
    bc_hex = builder_code.lower().removeprefix("0x")
    # Builders ekranındaki "Builder code" (bytes32) — private key DEĞİL
    _known_builder = "bd5727bd2fdaf0ef988dbfdbcee0e8c681dafa7f22365cf2a7145fa3b2211b06"
    if pk_hex and (pk_hex == bc_hex or pk_hex == _known_builder):
        print(
            "\n    [!] POLYMARKET_PRIVATE_KEY = Builder code (Builders sekmesi). "
            "Bu emir imzalamaz; yalnızca builder attribution içindir."
        )
        print(
            "        Gerçek private key: Polymarket'e giriş yaptığın cüzdanın export'u "
            f"(SIGNER ile aynı olmalı → {creds.signer_address})."
        )
        print(
            "        Profile/Builders'daki 0xdA04… adresi 'API only' — bakiye orada aranmaz."
        )
    if pk:
        if len(pk) == 42 and pk.startswith("0x"):
            print(
                "\n    [!] POLYMARKET_PRIVATE_KEY bir ADRES gibi görünüyor (42 karakter). "
                "Buraya Signer Address değil, gizli private key (0x + 64 hex = 66 karakter) yazılmalı. "
                "Polymarket export / MetaMask'tan export et; sohbete yapıştırma."
            )
        elif len(pk) != 66 or not pk.startswith("0x"):
            print(
                "\n    [!] POLYMARKET_PRIVATE_KEY formatı beklenmiyor "
                "(genelde 0x ile 66 karakter)."
            )
        else:
            print("    POLYMARKET_PRIVATE_KEY: format OK (uzunluk)")
            try:
                from eth_account import Account

                derived = Account.from_key(pk).address
                if derived.lower() != creds.signer_address.lower():
                    print(
                        f"\n    [!] PRIVATE_KEY başka bir cüzdana ait: {derived}"
                    )
                    print(
                        f"        Polymarket hesabın (SIGNER): {creds.signer_address}"
                    )
                    print(
                        "        Bu iki adres eşleşmeli — yanlış key ile bakiye/emir görünmez."
                    )
                else:
                    print(f"    PRIVATE_KEY ↔ SIGNER eşleşiyor: {derived[:10]}…")
            except ImportError:
                print(
                    "    (eth_account yok — key↔signer eşleşmesi için: pip install eth-account)"
                )
    else:
        print("    POLYMARKET_PRIVATE_KEY: eksik (canlı CLOB emri için gerekli)")
    if dep:
        print(f"    POLYMARKET_DEPOSIT_WALLET: {dep}")
    else:
        print("    POLYMARKET_DEPOSIT_WALLET: eksik (proxy adresi önerilir)")

    # 2) Bağlantı
    with PolymarketLive(creds) as poly:
        print(f"\n[2] Data API (read-only)…")
        h = poly.health()
        if h.get("ok"):
            print(f"    [OK] status={h['status']}")
        else:
            print(f"    [X]  health failed: {h}")
            print("    -> Network erişimi, doğru endpoint, geçerli API key kontrol et.")
            sys.exit(2)

        # 2b) Relayer v2 — dokümandaki header’larla /deployed + /transactions
        rk = RelayerApiCredentials.from_env()
        if rk and rk.api_key:
            print("\n[2b] Relayer v2 (submit-a-transaction ile aynı auth)…")
            try:
                with RelayerV2Client(rk) as rel:
                    dep = rel.deployed(rk.api_key_address, "SAFE")
                    print(f"    deployed SAFE @ key address: {dep}")
                    try:
                        dep_w = rel.deployed(rk.api_key_address, "WALLET")
                        print(f"    deployed WALLET @ key address: {dep_w}")
                    except httpx.HTTPStatusError as e:
                        print(f"    deployed WALLET: HTTP {e.response.status_code} (normal olabilir)")
                    txs = rel.list_transactions()
                    print(f"    recent relayer txs: {len(txs)}")
                    if txs:
                        t0 = txs[0]
                        print(
                            f"    last: id={t0.get('transactionID')} "
                            f"state={t0.get('state')} hash={t0.get('transactionHash')}"
                        )
            except httpx.HTTPStatusError as e:
                print(f"    [X] Relayer HTTP {e.response.status_code}: {e.response.text[:200]}")
            except Exception as e:
                print(f"    [X] Relayer: {e}")
        else:
            print("\n[2b] Relayer v2 atlandı (RELAYER_API_KEY / RELAYER_API_KEY_ADDRESS eksik).")

        # 3) Portföy — imzalayan vs proxy (UI bakiyesi çoğunlukla proxy'de)
        proxy = poly.proxy_wallet()
        print(f"\n[3] Bakiye / portföy (Data API)")
        print(f"    Signer (EOA):     {creds.signer_address}")
        if proxy:
            print(f"    Proxy wallet:     {proxy}")
        else:
            print("    Proxy wallet:     bulunamadı (gamma public-profile)")

        for label, addr in [("Signer", creds.signer_address), ("Proxy", proxy)]:
            if not addr:
                continue
            try:
                snap = poly.fetch_portfolio_for_user(addr)
                print(
                    f"    [{label}]  nakit≈${snap['value_usd']:.2f}  "
                    f"açık pozisyon={snap['positions']}"
                )
            except Exception as e:
                print(f"    [{label}]  [X] {e}")

        print(
            "\n    Not: 'nakit' = serbest USDC/pUSD collateral. UI'daki toplam bakiye "
            "açık pozisyonları da içerebilir. CLOB alım gücü için POLYMARKET_DEPOSIT_WALLET "
            "proxy adresi olmalı."
        )
        dep = (os.getenv("POLYMARKET_DEPOSIT_WALLET") or "").strip()
        if proxy and not dep:
            print(f"    Öneri .env: POLYMARKET_DEPOSIT_WALLET={proxy}")

        # 4) Açık pozisyonlar (proxy öncelikli)
        query_addr = (proxy or creds.signer_address).lower()
        print(f"\n[4] Açık pozisyonlar (user={query_addr[:10]}…)…")
        try:
            pos = poly.fetch_positions_for(query_addr)
        except AttributeError:
            pos = poly.fetch_positions()
        print(f"    {len(pos)} pozisyon")
        for p in pos[:5]:
            if isinstance(p, dict):
                title = (p.get("title") or p.get("question") or "")[:50]
                size = p.get("size") or p.get("currentValue")
                print(f"      {title}  size={size}")
            else:
                print(f"      {p}")

        # 5) Trade geçmişi
        print(f"\n[5] Son 10 trade…")
        try:
            trades = poly.fetch_trade_history_for(query_addr, limit=10)
        except AttributeError:
            trades = poly.fetch_trade_history(limit=10)
        print(f"    {len(trades)} trade")
        for t in trades[:3]:
            print(f"      {t}")

        # 6) CLOB bakiye (venv + geçerli private key gerekir)
        print(f"\n[6] CLOB alım gücü (authenticated)…")
        try:
            import live_clob as lc

            clob = lc.build_trading_client()
            if clob is None:
                print("    CLOB istemcisi oluşturulamadı (key/funder veya py-clob-client-v2).")
                print("    Projede: ./.venv/bin/python connection_check.py")
            else:
                from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams
                from py_clob_client_v2 import SignatureTypeV2

                bal = clob.get_balance_allowance(
                    BalanceAllowanceParams(
                        asset_type=AssetType.COLLATERAL,
                        signature_type=SignatureTypeV2.POLY_1271,
                    )
                )
                print(f"    CLOB signer: {clob.get_address()}")
                raw = bal.get("balance") if isinstance(bal, dict) else bal
                try:
                    usdc = int(raw) / 1_000_000
                    print(f"    collateral (USDC): ≈${usdc:.2f}  (raw={raw})")
                except (TypeError, ValueError):
                    print(f"    collateral balance: {raw}")
        except Exception as e:
            print(f"    [X] CLOB: {e}")

    print("\n" + "=" * 70)
    print(" Bağlantı doğrulandı. Bu script POST /submit veya CLOB emri göndermez.")
    print(" CLOB canlı: ./.venv/bin/python + POLYMARKET_PRIVATE_KEY (SIGNER ile aynı cüzdan).")
    print("=" * 70)


if __name__ == "__main__":
    main()
