"""
Polymarket CLOB canlı emir köprüsü — py-clob-client-v2.

Dokümantasyon:
  https://docs.polymarket.com/
  https://docs.polymarket.com/developers/CLOB/quickstart
  https://docs.polymarket.com/api-reference/introduction

Ortam değişkenleri (örnek: LIVE_TRADING.example.env):
  POLYMARKET_PRIVATE_KEY     — 0x… imzalayan anahtar (asla repoya commit etme)
  POLYMARKET_DEPOSIT_WALLET  — funder (deposit wallet veya EOA adresi)
  POLYMARKET_SIGNATURE_TYPE  — 0=EOA, 1=PROXY, 2=GNOSIS_SAFE, 3=POLY_1271 (varsayılan 3)

  İsteğe bağlı — Polymarket panelindeki CLOB API üçlüsü (L2). Hepsi doluysa
  otomatik derive/create atlanır (önerilir; konsolda 400 gürültüsü olmaz):
  POLYMARKET_CLOB_API_KEY
  POLYMARKET_CLOB_API_SECRET
  POLYMARKET_CLOB_API_PASSPHRASE

  Otomatik mod: önce derive (mevcut anahtar), olmazsa create.
  "Could not create api key" = anahtar zaten var; derive ile devam edilir.

İşlem:
  • Giriş: GTC limit BUY (token_id, entry_price, size=contracts)
  • TP/SL: önce FOK market SELL; olmazsa GTC limit SELL @ close_price

Gazsız on-chain işlemler (approve, split, redeem vb.) Relayer v2 ile ayrıdır:
  `relayer_client.py` — POST /submit, GET /transaction (poll).
  https://docs.polymarket.com/api-reference/relayer/submit-a-transaction
"""
from __future__ import annotations

import os
from typing import Any

CLOB_HOST = os.getenv("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com")
CHAIN_ID = int(os.getenv("POLYMARKET_CHAIN_ID", "137"))
DEFAULT_MIN_ORDER_SIZE = float(os.getenv("POLYMARKET_MIN_ORDER_SIZE", "5"))


def _sig_type() -> int:
    raw = os.getenv("POLYMARKET_SIGNATURE_TYPE", "3").strip()
    try:
        v = int(raw)
        if 0 <= v <= 3:
            return v
    except ValueError:
        pass
    return 3


def _map_sig_enum():
    from py_clob_client_v2 import SignatureTypeV2

    m = {0: SignatureTypeV2.EOA, 1: SignatureTypeV2.POLY_PROXY, 2: SignatureTypeV2.POLY_GNOSIS_SAFE, 3: SignatureTypeV2.POLY_1271}
    return m.get(_sig_type(), SignatureTypeV2.POLY_1271)


def _derive_or_create_api_creds(client: Any) -> Any:
    """
    Polymarket'te anahtar zaten varsa POST /auth/api-key 400 verir.
    Önce derive — py_clob_client_v2.create_or_derive ters sırada dener ve stderr kirletir.
    """
    from py_clob_client_v2.clob_types import ApiCreds

    try:
        return client.derive_api_key()
    except Exception as derive_exc:
        try:
            return client.create_api_key()
        except Exception:
            raise derive_exc from None


def build_trading_client() -> Any | None:
    """L2 imzalı ClobClient veya yapılandırma eksikse None."""
    try:
        from py_clob_client_v2 import ClobClient
        from py_clob_client_v2.clob_types import ApiCreds
    except ImportError:
        return None

    pk = (os.getenv("POLYMARKET_PRIVATE_KEY") or "").strip()
    funder = (os.getenv("POLYMARKET_DEPOSIT_WALLET") or "").strip()
    if not pk or not funder:
        return None

    sig = _map_sig_enum()
    ak = (os.getenv("POLYMARKET_CLOB_API_KEY") or "").strip()
    sec = (os.getenv("POLYMARKET_CLOB_API_SECRET") or "").strip()
    ph = (os.getenv("POLYMARKET_CLOB_API_PASSPHRASE") or "").strip()
    if ak and sec and ph:
        api_creds = ApiCreds(api_key=ak, api_secret=sec, api_passphrase=ph)
    else:
        temp = ClobClient(
            CLOB_HOST,
            key=pk,
            chain_id=CHAIN_ID,
            signature_type=sig,
            funder=funder,
        )
        api_creds = _derive_or_create_api_creds(temp)
    return ClobClient(
        CLOB_HOST,
        key=pk,
        chain_id=CHAIN_ID,
        creds=api_creds,
        signature_type=sig,
        funder=funder,
    )


def _options(client: Any, token_id: str) -> Any:
    from py_clob_client_v2 import PartialCreateOrderOptions

    tick = client.get_tick_size(token_id)
    neg = client.get_neg_risk(token_id)
    return PartialCreateOrderOptions(tick_size=tick, neg_risk=neg)


def fetch_midpoint_price(client: Any, token_id: str) -> float | None:
    """CLOB midpoint (YES token) — paper giriş fiyatı için."""
    try:
        if hasattr(client, "get_midpoint"):
            raw = client.get_midpoint(token_id)
            if isinstance(raw, dict):
                mid = raw.get("mid") or raw.get("price")
            else:
                mid = raw
            if mid is not None:
                p = float(mid)
                if 0.001 < p < 0.999:
                    return p
    except Exception:
        pass
    return None


def fetch_midpoint_http(http: Any, token_id: str) -> float | None:
    """httpx ile public midpoint (paper tarama)."""
    try:
        r = http.get(
            f"{CLOB_HOST}/midpoint",
            params={"token_id": token_id},
            timeout=8.0,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, dict):
            mid = data.get("mid") or data.get("price")
            if mid is not None:
                p = float(mid)
                if 0.001 < p < 0.999:
                    return p
    except Exception:
        pass
    return None


def validate_live_stack_buy(
    clob_client: Any,
    conn: Any,
    token_id: str,
    additional_contracts: float,
    additional_stake_usd: float,
) -> tuple[bool, str]:
    """
    Canlı katman / ek alım: açık DB pozisyonları + CLOB bakiye/allowance.
    """
    tid = str(token_id)
    add_c = max(0.0, float(additional_contracts))
    add_s = max(0.0, float(additional_stake_usd))

    row = conn.execute(
        """
        SELECT COALESCE(SUM(contracts), 0) AS c, COALESCE(SUM(stake_usd), 0) AS s
        FROM positions
        WHERE outcome_token_id = ? AND closed_at IS NULL
        """,
        (tid,),
    ).fetchone()
    open_c = float(row["c"] or 0) if row else 0.0
    open_s = float(row["s"] or 0) if row else 0.0
    total_c = open_c + add_c

    max_c = float(os.getenv("LIVE_STACK_MAX_CONTRACTS_PER_TOKEN", "500"))
    if total_c > max_c + 0.01:
        return False, f"token_pay_tavanı {total_c:.1f}>{max_c:.0f}"

    if open_c > 0.01:
        bal = get_conditional_balance(clob_client, tid)
        if bal is not None and bal + 0.05 < total_c:
            return (
                False,
                f"conditional_bakiye {bal:.2f} < açık+ yeni {total_c:.2f} pay",
            )

    usdc = get_collateral_usdc(clob_client)
    if usdc is not None:
        need = add_s + float(os.getenv("LIVE_USDC_BUFFER_USD", "0.50"))
        if usdc < need:
            return False, f"USDC {usdc:.2f} < gerekli ${need:.2f}"

    ensure_conditional_allowance(clob_client, tid)
    return True, f"ok açık={open_c:.1f}+{add_c:.1f} stake=${open_s:.0f}+${add_s:.0f}"


def get_min_order_size(client: Any, token_id: str) -> float:
    """CLOB minimum pay (shares) — çoğu markette 5."""
    try:
        ob = client.get_order_book(token_id)
        raw = getattr(ob, "min_order_size", None)
        if raw is None and isinstance(ob, dict):
            raw = ob.get("min_order_size")
        if raw is not None:
            return max(DEFAULT_MIN_ORDER_SIZE, float(raw))
    except Exception:
        pass
    return DEFAULT_MIN_ORDER_SIZE


def plan_live_buy(
    price: float,
    stake_usd: float,
    max_usd: float,
    min_shares: float,
) -> tuple[float, float] | None:
    """
    Kelly stake → CLOB emir boyutu.
    None: min_shares * price > max_usd (ör. $2 tavan + fiyat 0.50+ → 5 pay ≈ $2.50+).
    """
    if price <= 0 or price >= 1:
        return None
    shares = stake_usd / price
    if shares < min_shares:
        shares = min_shares
    actual_stake = shares * price
    tol = float(os.getenv("LIVE_STAKE_TOLERANCE_USD", "0.02"))
    if actual_stake > max_usd + tol:
        return None
    return shares, actual_stake


def _round_size_for_tick(size: float, tick: str) -> float:
    if tick == "0.1":
        return max(0.1, round(size, 1))
    if tick == "0.01":
        return max(0.01, round(size, 2))
    if tick == "0.001":
        return max(0.001, round(size, 3))
    return max(0.0001, round(size, 4))


def _round_price_for_tick(price: float, tick: str) -> float:
    t = float(tick)
    if t <= 0:
        return round(price, 6)
    n = round(price / t) * t
    return float(f"{n:.10f}".rstrip("0").rstrip(".")) if "." in f"{n}" else float(n)


def place_buy_limit(
    client: Any, token_id: str, price: float, size_shares: float
) -> dict[str, Any]:
    from py_clob_client_v2 import OrderArgs, OrderType
    from py_clob_client_v2.order_builder.constants import BUY

    opts = _options(client, token_id)
    tick = opts.tick_size or "0.01"
    px = max(0.001, min(0.999, _round_price_for_tick(price, tick)))
    min_sz = get_min_order_size(client, token_id)
    sz = max(min_sz, _round_size_for_tick(size_shares, tick))
    args = OrderArgs(token_id=token_id, price=float(px), size=float(sz), side=BUY)
    return client.create_and_post_order(
        args, options=opts, order_type=OrderType.GTC, post_only=False
    )


def ensure_conditional_allowance(client: Any, token_id: str) -> None:
    """Outcome token satışı öncesi CLOB allowance senkronu (balance:0 hatasını önler)."""
    from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams
    from py_clob_client_v2 import SignatureTypeV2

    params = BalanceAllowanceParams(
        asset_type=AssetType.CONDITIONAL,
        token_id=str(token_id),
        signature_type=SignatureTypeV2.POLY_1271,
    )
    try:
        client.update_balance_allowance(params)
    except Exception as exc:
        print(f"  [LIVE] allowance güncelleme uyarısı: {exc}")


def get_conditional_balance(client: Any, token_id: str) -> float | None:
    """CLOB'daki outcome token bakiyesi (pay, 6 ondalık)."""
    from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams
    from py_clob_client_v2 import SignatureTypeV2

    try:
        bal = client.get_balance_allowance(
            BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL,
                token_id=str(token_id),
                signature_type=SignatureTypeV2.POLY_1271,
            )
        )
        raw = bal.get("balance") if isinstance(bal, dict) else bal
        return int(raw) / 1_000_000
    except Exception:
        return None


def place_sell_exit(
    client: Any, token_id: str, contracts: float, limit_price: float
) -> dict[str, Any]:
    """
    Pozisyonu kapat: önce market FOK satış; başarısızsa GTC limit @ limit_price.
    """
    from py_clob_client_v2 import MarketOrderArgs, OrderArgs, OrderType
    from py_clob_client_v2.order_builder.constants import SELL

    ensure_conditional_allowance(client, token_id)
    opts = _options(client, token_id)
    tick = opts.tick_size or "0.01"
    sz = _round_size_for_tick(contracts, tick)
    lp = max(0.001, min(0.999, _round_price_for_tick(limit_price, tick)))

    try:
        margs = MarketOrderArgs(
            token_id=token_id, amount=float(sz), side=SELL, price=0, order_type=OrderType.FOK
        )
        out = client.create_and_post_market_order(
            margs, options=opts, order_type=OrderType.FOK
        )
        if isinstance(out, dict) and str(out.get("status", "")).lower() in ("matched", "ok", "live"):
            return out
    except Exception:
        pass

    args = OrderArgs(token_id=token_id, price=float(lp), size=float(sz), side=SELL)
    return client.create_and_post_order(
        args, options=opts, order_type=OrderType.GTC, post_only=False
    )


def get_collateral_usdc(client: Any) -> float | None:
    """CLOB collateral bakiyesi (USDC, 6 ondalık)."""
    try:
        from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams
        from py_clob_client_v2 import SignatureTypeV2

        bal = client.get_balance_allowance(
            BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=SignatureTypeV2.POLY_1271,
            )
        )
        raw = bal.get("balance") if isinstance(bal, dict) else bal
        return int(raw) / 1_000_000
    except Exception:
        return None


def response_ok(resp: Any) -> bool:
    if resp is None:
        return False
    if isinstance(resp, dict):
        st = str(resp.get("status", "")).lower()
        if st in ("matched", "live", "open", "ok"):
            return True
        err = resp.get("error") or resp.get("message")
        if err:
            return False
        return "orderID" in resp or "order_id" in resp
    return True
