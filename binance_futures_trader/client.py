"""Binance USDT-M — public veri + paper / testnet emir."""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import threading
import time
import urllib.parse
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

import httpx

from binance_futures_trader import config as cfg
from binance_futures_trader.network_ssl import apply_cert_env, httpx_verify

apply_cert_env()

# margin/leverage setup — açık emir varken -4047/-4067 spam önleme
_SETUP_BLOCK_CODES = ("-4046", "-4047", "-4067")
_symbol_setup_cooldown: dict[str, float] = {}
_symbol_setup_logged: set[str] = set()
_global_setup_block_until: float = 0.0


def _setup_cooldown_sec() -> float:
    try:
        return max(60.0, float(os.getenv("BINANCE_SYMBOL_SETUP_COOLDOWN_SEC", "600")))
    except ValueError:
        return 600.0


def _skip_symbol_setup_on_orders() -> bool:
    return os.getenv("BINANCE_SKIP_SYMBOL_SETUP_ON_ORDERS", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _is_setup_block_error(body: str) -> bool:
    return any(code in body for code in _SETUP_BLOCK_CODES)


def _is_invalid_symbol_error(body: str) -> bool:
    return "-1121" in body or "Invalid symbol" in body


def _is_unknown_order_error(body: str) -> bool:
    """İptal/sorgu — emir zaten dolmuş veya yok (-2011)."""
    return "-2011" in body or "Unknown order sent" in body


def _note_symbol_setup_block(
    coin: str,
    body: str,
    *,
    margin_type: str | None = None,
    leverage: int | None = None,
    client: "BinanceFuturesClient | None" = None,
) -> None:
    global _global_setup_block_until
    if not _is_setup_block_error(body):
        return
    until = time.time() + _setup_cooldown_sec()
    _symbol_setup_cooldown[coin] = until
    _global_setup_block_until = max(_global_setup_block_until, until)
    if client is not None:
        if margin_type:
            client._margin_set[coin] = margin_type
        if leverage is not None:
            client._leverage_set[coin] = leverage
    log_key = f"{coin}:{body[:48]}"
    if log_key in _symbol_setup_logged:
        return
    _symbol_setup_logged.add(log_key)
    if len(_symbol_setup_logged) > 120:
        _symbol_setup_logged.clear()
    print(
        f"  ℹ {coin} margin/kaldıraç ayarı atlandı (açık emir) — "
        f"{body[:100]}"
    )


def _step_precision(step: float) -> int:
    """LOT_SIZE stepSize / PRICE_FILTER tickSize ondalık basamak."""
    if step <= 0:
        return 8
    s = f"{step:.12f}".rstrip("0").rstrip(".")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def _quantize_to_step(value: float, step: float, max_prec: int) -> Decimal:
    """Binance LOT_SIZE/PRICE_FILTER — float artefaktı olmadan."""
    step_d = Decimal(str(step if step > 0 else "1"))
    v = Decimal(str(value))
    if step_d > 0:
        v = (v / step_d).to_integral_value(rounding=ROUND_DOWN) * step_d
    prec = max(0, int(max_prec))
    if prec >= 0:
        exp = Decimal("1").scaleb(-prec)
        v = v.quantize(exp, rounding=ROUND_DOWN)
    return v


def _format_decimal(value: Decimal, max_prec: int) -> str:
    """Binance REST — quantityPrecision/tickSize üst sınırı (fazla ondalık -1111)."""
    prec = max(0, int(max_prec))
    if prec <= 0:
        return str(int(value))
    return format(value, f".{prec}f")


def _rule_from_symbol_row(s: dict[str, Any]) -> dict[str, Any]:
    """exchangeInfo satırı → LOT_SIZE + MARKET_LOT_SIZE + PRICE_FILTER."""
    step, min_qty, min_notional = 0.001, 0.001, 5.0
    market_step, market_min_qty = step, min_qty
    tick, min_price = 0.01, 0.0
    qty_prec = int(s.get("quantityPrecision") or 8)
    price_prec = int(s.get("pricePrecision") or 8)
    for f in s.get("filters") or []:
        ft = f.get("filterType")
        if ft == "LOT_SIZE":
            step = float(f.get("stepSize") or step)
            min_qty = float(f.get("minQty") or min_qty)
        elif ft == "MARKET_LOT_SIZE":
            market_step = float(f.get("stepSize") or market_step)
            market_min_qty = float(f.get("minQty") or market_min_qty)
        elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
            min_notional = float(
                f.get("notional") or f.get("minNotional") or min_notional
            )
        elif ft == "PRICE_FILTER":
            tick = float(f.get("tickSize") or tick)
            min_price = float(f.get("minPrice") or min_price)
    qty_step_prec = _step_precision(step)
    market_step_prec = _step_precision(market_step)
    return {
        "valid": True,
        "step": step,
        "min_qty": min_qty,
        "market_step": market_step,
        "market_min_qty": market_min_qty,
        "min_notional": min_notional,
        "tick": tick,
        "min_price": min_price,
        "qty_prec": max(0, min(qty_prec, qty_step_prec)),
        "market_qty_prec": max(0, min(qty_prec, market_step_prec)),
        "price_prec": max(0, min(price_prec, _step_precision(tick))),
    }


_INVALID_SYMBOL_RULE: dict[str, Any] = {
    "valid": False,
    "step": 1.0,
    "min_qty": 1.0,
    "market_step": 1.0,
    "market_min_qty": 1.0,
    "min_notional": 5.0,
    "tick": 0.01,
    "min_price": 0.0,
    "qty_prec": 0,
    "market_qty_prec": 0,
    "price_prec": 2,
}


def _recv_window_ms() -> int:
    try:
        return max(5000, int(os.getenv("BINANCE_RECV_WINDOW", "15000")))
    except ValueError:
        return 15000

MAIN_BASE = "https://fapi.binance.com"
# Eski testnet (legacy)
TESTNET_BASE = "https://testnet.binancefuture.com"
# Binance Futures Demo — https://developers.binance.com/docs/derivatives/
DEMO_BASE = "https://demo-fapi.binance.com"


def api_base() -> str:
    custom = (getattr(cfg, "API_REST_BASE", None) or "").strip()
    if custom:
        return custom.rstrip("/")
    if cfg.MODE == "testnet" or (cfg.TESTNET and cfg.API_KEY):
        if getattr(cfg, "FUTURES_DEMO", False):
            return DEMO_BASE
        return TESTNET_BASE
    return MAIN_BASE


def ssl_verify_path() -> str | bool:
    return httpx_verify()


def _make_http_client(
    *,
    connect_timeout: float = 15.0,
    read_timeout: float = 20.0,
    use_proxy: bool = True,
    ssl_verify: bool | str | None = None,
) -> "httpx.Client":
    """httpx istemcisi — certifi + keep-alive (TLS el sıkışması tekrarlanmaz)."""
    verify: bool | str = ssl_verify if ssl_verify is not None else httpx_verify()
    http_kw: dict[str, Any] = {
        "timeout": httpx.Timeout(read_timeout, connect=connect_timeout),
        "verify": verify,
        "headers": {"User-Agent": "bn-fut-trader/1.0", "Connection": "keep-alive"},
        "http2": False,
        "limits": httpx.Limits(
            max_connections=8,
            max_keepalive_connections=6,
            keepalive_expiry=120.0,
        ),
    }
    if use_proxy:
        proxy = (
            os.getenv("BINANCE_HTTP_PROXY")
            or os.getenv("HTTPS_PROXY")
            or os.getenv("https_proxy")
            or ""
        ).strip()
        if proxy:
            http_kw["proxy"] = proxy
    return httpx.Client(**http_kw)


def _is_transient_rest_block(err: str | None) -> bool:
    """Ağ koruması / paper-port guard — gerçek auth hatası değil."""
    if not err:
        return False
    e = err.lower()
    return (
        "rest paused (network guard)" in e
        or "signed rest disabled (paper port)" in e
        or "binance outbound disabled" in e
    )


def _sign(
    params: dict[str, Any],
    *,
    api_secret: str | None = None,
    time_offset_ms: int = 0,
) -> dict[str, Any]:
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000) + int(time_offset_ms)
    params.setdefault("recvWindow", _recv_window_ms())
    qs = urllib.parse.urlencode(params)
    secret = (api_secret if api_secret is not None else cfg.API_SECRET).encode()
    sig = hmac.new(secret, qs.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params


class BinanceFuturesClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        testnet: bool | None = None,
        futures_demo: bool | None = None,
        rest_base: str | None = None,
        mode: str | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else cfg.API_KEY).strip()
        self._api_secret = (
            api_secret if api_secret is not None else cfg.API_SECRET
        ).strip()
        self._testnet = cfg.TESTNET if testnet is None else bool(testnet)
        self._futures_demo = (
            cfg.FUTURES_DEMO if futures_demo is None else bool(futures_demo)
        )
        self._rest_base = (
            (rest_base if rest_base is not None else cfg.API_REST_BASE).strip()
        )
        self._mode = (mode if mode is not None else cfg.MODE).strip().lower()
        verify = httpx_verify()
        # Tek havuz — REST çağrıları aynı TLS oturumunu yeniden kullanır
        self._http = _make_http_client(
            connect_timeout=15.0,
            read_timeout=20.0,
            use_proxy=False,
            ssl_verify=verify,
        )
        self._price_http = self._http
        self._verify = verify
        self._last_prices: dict[str, float] = {}
        self._symbol_rules: dict[str, dict[str, Any]] = {}
        self._symbol_rules_warmed = False
        self._leverage_set: dict[str, int] = {}
        self._margin_set: dict[str, str] = {}
        self._api_lock = threading.Lock()
        self._time_offset_ms: int = 0
        self._time_sync_at: float = 0.0
        _live_modes = frozenset({"testnet", "live", "mainnet"})
        self.paper = self._mode not in _live_modes or not self._api_key
        self._auth_error: str | None = None
        if self._api_key and not self.paper:
            self.sync_server_time(force=True)
        if self._mode == "testnet" and self._api_key:
            quick = os.getenv("BINANCE_AUTH_QUICK", "1").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            try:
                max_att = int(os.getenv("BINANCE_AUTH_MAX_ATTEMPTS", "1" if quick else "5"))
            except ValueError:
                max_att = 1 if quick else 5
            if not quick:
                max_att = max(3, max_att)
            ok, err = self._auth_ok(max_attempts=max(1, max_att))
            if not ok:
                if _is_transient_rest_block(err):
                    self._auth_error = None
                else:
                    self._auth_error = err
                    print(f"  ⚠ Binance API: {err}")
                    print(
                        "     Emirler PAPER simülasyonda. Demo API: "
                        "https://demo.binance.com → API Management (Futures)"
                    )
                    self.paper = True
        elif self._mode in _live_modes and self._api_key and not self.paper:
            ok, err = self._auth_ok(max_attempts=1)
            if not ok and not _is_transient_rest_block(err):
                self._auth_error = err
                try:
                    from elite_trader.connection_alerts import note_binance_error

                    note_binance_error(err)
                except Exception:
                    pass
                print(f"  ⚠ Binance mainnet API: {err}")

    def _note_http_error(self, exc: BaseException) -> None:
        body = str(exc)
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            body = exc.response.text or body
        if _is_setup_block_error(body):
            return
        try:
            from elite_trader.connection_alerts import note_binance_error

            note_binance_error(body)
        except Exception:
            pass
        if self._is_auth_failure(body):
            self._auth_error = body[:300]

    def _is_auth_failure(self, body: str) -> bool:
        b = body.lower()
        if any(c in body for c in ("-2015", "-2014", "-1022")):
            return True
        if "invalid api-key" in b or "invalid api key" in b:
            return True
        if "signature" in b and "-1022" in body:
            return True
        return False

    def _note_http_success(self) -> None:
        if self._auth_error and not self._is_auth_failure(self._auth_error):
            self._auth_error = None
        try:
            from elite_trader.connection_alerts import note_binance_success

            note_binance_success()
        except Exception:
            pass

    def try_restore_live(self, *, max_attempts: int = 1) -> tuple[bool, str | None]:
        """429/ban sonrası paper fallback'ten canlı moda dön (singleton yenilemeden)."""
        _live_modes = frozenset({"testnet", "live", "mainnet"})
        if not self._api_key or self._mode not in _live_modes:
            return False, "no_key_or_mode"
        if not self.paper:
            return True, None
        ok, err = self._auth_ok(max_attempts=max(1, max_attempts))
        if not ok:
            return False, err
        self.paper = False
        self._auth_error = None
        try:
            from elite_trader.connection_alerts import note_binance_success

            note_binance_success()
        except Exception:
            pass
        return True, None

    def _api_base(self) -> str:
        if self._rest_base:
            return self._rest_base.rstrip("/")
        if self._mode == "testnet" or (self._testnet and self._api_key):
            if self._futures_demo:
                return DEMO_BASE
            return TESTNET_BASE
        return MAIN_BASE

    def sync_server_time(self, *, force: bool = False) -> None:
        """Binance serverTime — -1021 timestamp hatalarını önler."""
        now = time.time()
        if not force and self._time_sync_at and (now - self._time_sync_at) < 300.0:
            return
        try:
            data = self._get_price("/fapi/v1/time")
            server_ms = int((data or {}).get("serverTime") or 0)
            if server_ms > 0:
                local_ms = int(time.time() * 1000)
                self._time_offset_ms = server_ms - local_ms
                self._time_sync_at = now
        except Exception:
            pass

    def _sign_params(self, params: dict[str, Any]) -> dict[str, Any]:
        self.sync_server_time()
        return _sign(
            params,
            api_secret=self._api_secret,
            time_offset_ms=self._time_offset_ms,
        )

    @staticmethod
    def _is_timestamp_error(exc: BaseException) -> bool:
        body = ""
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            body = exc.response.text or ""
        return "-1021" in body or "Timestamp" in body

    def _auth_ok(self, max_attempts: int = 3) -> tuple[bool, str | None]:
        last_err: str | None = None
        for attempt in range(max(1, max_attempts)):
            try:
                self._get("/fapi/v2/balance", signed=True)
                return True, None
            except httpx.HTTPStatusError as exc:
                last_err = f"HTTP {exc.response.status_code}"
                break
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
                last_err = str(exc)[:100]
                if attempt < max_attempts - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            except Exception as exc:
                last_err = str(exc)[:120]
                if attempt < max_attempts - 1 and "timeout" in str(exc).lower():
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
        if last_err:
            if "CERTIFICATE_VERIFY_FAILED" in last_err:
                return False, "SSL sertifika hatası (certifi / macOS sertifikaları)"
            return False, last_err
        return False, "auth failed"

    def close(self) -> None:
        self._http.close()

    def api_ping(self) -> bool:
        """Hafif ping — TLS oturumunu canlı tutar."""
        try:
            self._get_price("/fapi/v1/ping")
            return True
        except Exception:
            return False

    def _await_rest_budget(self) -> None:
        try:
            from elite_trader.binance_rest_budget import acquire_rest_slot

            if not acquire_rest_slot():
                raise RuntimeError("REST paused (network guard)")
        except ImportError:
            pass

    def _get(self, path: str, params: dict | None = None, signed: bool = False) -> Any:
        url = f"{self._api_base()}{path}"
        p = params or {}
        headers: dict[str, str] = {}
        if signed:
            try:
                from elite_trader.network_guard import (
                    binance_signed_rest_port_allowed,
                    skip_rest,
                )

                if not binance_signed_rest_port_allowed():
                    raise RuntimeError("Signed REST disabled (paper port)")
                if skip_rest():
                    raise RuntimeError("REST paused (network guard)")
            except ImportError:
                pass
            self._await_rest_budget()
            if not self._api_key or not self._api_secret:
                raise RuntimeError("API anahtarı yok")
            p = self._sign_params(p)
            headers["X-MBX-APIKEY"] = self._api_key
        else:
            try:
                from elite_trader.network_guard import binance_outbound_enabled

                if not binance_outbound_enabled():
                    raise RuntimeError("Binance outbound disabled (9007 hub consumer)")
            except ImportError:
                pass
            self._await_rest_budget()
        for attempt in range(2):
            try:
                with self._api_lock:
                    r = self._http.get(url, params=p, headers=headers)
                r.raise_for_status()
                if signed:
                    self._note_http_success()
                return r.json()
            except httpx.HTTPStatusError as exc:
                if signed and attempt == 0 and self._is_timestamp_error(exc):
                    self.sync_server_time(force=True)
                    p = dict(params or {})
                    p = self._sign_params(p)
                    continue
                if signed:
                    self._note_http_error(exc)
                raise

    def _get_price(self, path: str, params: dict | None = None) -> Any:
        """Fiyat sorgusu — aynı TLS havuzu."""
        try:
            from elite_trader.network_guard import binance_outbound_enabled

            if not binance_outbound_enabled():
                raise RuntimeError("Binance outbound disabled (9007 hub consumer)")
        except ImportError:
            pass
        self._await_rest_budget()
        url = f"{self._api_base()}{path}"
        with self._api_lock:
            r = self._price_http.get(url, params=params or {})
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, params: dict | None = None) -> Any:
        if self.paper:
            return {"paper": True, "params": params}
        self._await_rest_budget()
        url = f"{self._api_base()}{path}"
        base_params = dict(params or {})
        headers = {"X-MBX-APIKEY": self._api_key}
        for attempt in range(2):
            p = self._sign_params(dict(base_params))
            with self._api_lock:
                r = self._http.post(url, params=p, headers=headers)
            if r.status_code < 400:
                self._note_http_success()
                return r.json()
            body = r.text[:300]
            if attempt == 0 and self._is_timestamp_error(
                httpx.HTTPStatusError(
                    f"Binance {r.status_code}: {body}",
                    request=r.request,
                    response=r,
                )
            ):
                self.sync_server_time(force=True)
                continue
            err_exc = httpx.HTTPStatusError(
                f"Binance {r.status_code}: {body}",
                request=r.request,
                response=r,
            )
            self._note_http_error(err_exc)
            raise err_exc
        return {"error": "timestamp_retry_failed"}

    def _delete(self, path: str, params: dict | None = None) -> Any:
        if self.paper:
            return {"paper": True, "params": params}
        self._await_rest_budget()
        url = f"{self._api_base()}{path}"
        base_params = dict(params or {})
        headers = {"X-MBX-APIKEY": self._api_key}
        for attempt in range(2):
            p = self._sign_params(dict(base_params))
            with self._api_lock:
                r = self._http.delete(url, params=p, headers=headers)
            if r.status_code < 400:
                self._note_http_success()
                return r.json()
            body = r.text[:300]
            if attempt == 0 and self._is_timestamp_error(
                httpx.HTTPStatusError(
                    f"Binance {r.status_code}: {body}",
                    request=r.request,
                    response=r,
                )
            ):
                self.sync_server_time(force=True)
                continue
            if _is_unknown_order_error(body):
                self._note_http_success()
                return {
                    "status": "CANCELED",
                    "already_gone": True,
                    **{k: base_params[k] for k in ("symbol", "orderId", "algoId") if k in base_params},
                }
            err_exc = httpx.HTTPStatusError(
                f"Binance {r.status_code}: {body}",
                request=r.request,
                response=r,
            )
            self._note_http_error(err_exc)
            raise err_exc
        return {"error": "timestamp_retry_failed"}

    def _warm_symbol_rules(self) -> None:
        if self._symbol_rules_warmed or self.paper:
            return
        try:
            info = self._get("/fapi/v1/exchangeInfo")
            for s in info.get("symbols") or []:
                sym = str(s.get("symbol") or "")
                if not sym:
                    continue
                self._symbol_rules[sym] = _rule_from_symbol_row(s)
            self._symbol_rules_warmed = True
        except Exception:
            pass

    def _symbol_rule(self, coin: str) -> dict[str, Any]:
        sym = f"{coin}USDT"
        if sym in self._symbol_rules:
            return self._symbol_rules[sym]
        self._warm_symbol_rules()
        if sym in self._symbol_rules:
            return self._symbol_rules[sym]
        # exchangeInfo'da yok — varsayılan 0.001 adım -1111 üretir; işlem açma
        self._symbol_rules[sym] = dict(_INVALID_SYMBOL_RULE)
        return self._symbol_rules[sym]

    def symbol_tradable(self, coin: str) -> bool:
        """Sembol bu REST uç noktasında (demo/main) işlem görebilir mi."""
        return bool(self._symbol_rule(coin).get("valid"))

    def _mark_symbol_untradable(self, coin: str) -> None:
        c = coin.upper().replace("USDT", "")
        self._symbol_rules[f"{c}USDT"] = dict(_INVALID_SYMBOL_RULE)

    def list_tradeable_usdt_perpetuals(self) -> list[str]:
        """Tüm TRADING USDT-M perpetual sembolleri (tek istek, cache)."""
        cached = getattr(self, "_usdt_perp_symbols_cache", None)
        if cached is not None:
            return cached
        out: list[str] = []
        try:
            info = self._get("/fapi/v1/exchangeInfo")
            for s in info.get("symbols") or []:
                if s.get("contractType") != "PERPETUAL":
                    continue
                if s.get("quoteAsset") != "USDT":
                    continue
                if s.get("status") != "TRADING":
                    continue
                sym = s.get("symbol")
                if sym and isinstance(sym, str):
                    out.append(sym)
        except Exception:
            pass
        out = sorted(set(out))
        self._usdt_perp_symbols_cache = out
        return out

    def usdt_perpetuals_by_volume(
        self,
        *,
        min_quote_volume_usd: float = 0,
        max_symbols: int = 0,
    ) -> list[str]:
        """24s USDT quote hacmine göre sıralı perpetual listesi."""
        try:
            tickers = self._get("/fapi/v1/ticker/24hr")
        except Exception:
            return self.list_tradeable_usdt_perpetuals()
        rows: list[tuple[str, float]] = []
        for t in tickers or []:
            sym = str(t.get("symbol") or "")
            if not sym.endswith("USDT"):
                continue
            vol = float(t.get("quoteVolume") or 0)
            if vol >= min_quote_volume_usd:
                rows.append((sym, vol))
        rows.sort(key=lambda x: x[1], reverse=True)
        out = [s for s, _ in rows]
        if max_symbols > 0:
            out = out[:max_symbols]
        return out

    def prices_by_usdt_symbol(self) -> dict[str, float]:
        """Tek REST çağrısı — tüm USDT mark/last fiyatları."""
        raw = self.all_prices()
        return {f"{c}USDT": float(p) for c, p in raw.items() if p and p > 0}

    def round_qty(self, coin: str, qty: float, *, for_market: bool = False) -> float:
        rule = self._symbol_rule(coin)
        if not rule.get("valid"):
            raise ValueError(
                f"{coin}USDT bu ortamda exchangeInfo'da yok — miktar yuvarlanamadı"
            )
        if for_market:
            step = float(rule["market_step"])
            min_q = float(rule["market_min_qty"])
            max_prec = int(rule.get("market_qty_prec") or _step_precision(step))
        else:
            step = float(rule["step"])
            min_q = float(rule["min_qty"])
            max_prec = int(rule.get("qty_prec") or _step_precision(step))
        q = _quantize_to_step(float(qty), step, max_prec)
        q = max(q, Decimal(str(min_q)))
        return float(q)

    def format_qty(self, coin: str, qty: float, *, for_market: bool = False) -> str:
        rule = self._symbol_rule(coin)
        if not rule.get("valid"):
            raise ValueError(
                f"{coin}USDT bu ortamda exchangeInfo'da yok — miktar formatlanamadı"
            )
        if for_market:
            step = float(rule["market_step"])
            min_q = float(rule["market_min_qty"])
            max_prec = int(rule.get("market_qty_prec") or _step_precision(step))
        else:
            step = float(rule["step"])
            min_q = float(rule["min_qty"])
            max_prec = int(rule.get("qty_prec") or _step_precision(step))
        q = _quantize_to_step(float(qty), step, max_prec)
        q = max(q, Decimal(str(min_q)))
        return _format_decimal(q, max_prec)

    def round_price(self, coin: str, price: float) -> float:
        rule = self._symbol_rule(coin)
        tick = float(rule.get("tick") or 0.0001)
        max_prec = int(rule.get("price_prec") or _step_precision(tick))
        px = _quantize_to_step(float(price), tick, max_prec)
        min_px = float(rule.get("min_price") or 0)
        if min_px > 0 and px < Decimal(str(min_px)):
            px = Decimal(str(min_px))
        return float(px)

    def format_price(self, coin: str, price: float) -> str:
        rule = self._symbol_rule(coin)
        tick = float(rule.get("tick") or 0.0001)
        max_prec = int(rule.get("price_prec") or _step_precision(tick))
        p = _quantize_to_step(float(price), tick, max_prec)
        return _format_decimal(p, max_prec)

    def query_order(self, coin: str, order_id: int | str) -> dict[str, Any] | None:
        """Tek emir — açılış transactTime için."""
        if self.paper or not order_id:
            return None
        sym = f"{coin}USDT"
        try:
            raw = self._get(
                "/fapi/v1/order",
                {"symbol": sym, "orderId": int(order_id)},
                signed=True,
            )
            return dict(raw) if isinstance(raw, dict) else None
        except Exception:
            return None

    def cancel_order(self, coin: str, order_id: int | str) -> dict[str, Any]:
        sym = f"{coin}USDT"
        if self.paper:
            return {"paper": True, "symbol": sym, "orderId": order_id, "status": "CANCELED"}
        try:
            return self._delete(
                "/fapi/v1/order",
                {"symbol": sym, "orderId": int(order_id)},
            )
        except httpx.HTTPStatusError as exc:
            body = exc.response.text if exc.response is not None else str(exc)
            if _is_unknown_order_error(body):
                return {
                    "symbol": sym,
                    "orderId": order_id,
                    "status": "CANCELED",
                    "already_gone": True,
                }
            try:
                return self.cancel_algo_order(coin, order_id)
            except httpx.HTTPStatusError as exc2:
                body2 = exc2.response.text if exc2.response is not None else str(exc2)
                if _is_unknown_order_error(body2):
                    return {
                        "symbol": sym,
                        "algoId": order_id,
                        "status": "CANCELED",
                        "already_gone": True,
                    }
                raise
        except Exception:
            return self.cancel_algo_order(coin, order_id)

    def cancel_algo_order(self, coin: str, algo_id: int | str) -> dict[str, Any]:
        sym = f"{coin}USDT"
        if self.paper:
            return {"paper": True, "symbol": sym, "algoId": algo_id, "status": "CANCELED"}
        return self._delete(
            "/fapi/v1/algoOrder",
            {"symbol": sym, "algoId": int(algo_id)},
        )

    def open_algo_orders(self, coin: str | None = None) -> list[dict[str, Any]]:
        """Açık conditional/algo emirleri — TP/SL/stop."""
        if self.paper:
            return []
        params: dict[str, Any] = {}
        if coin:
            params["symbol"] = f"{coin}USDT"
        raw = self._get("/fapi/v1/openAlgoOrders", params, signed=True)
        if isinstance(raw, list):
            return [dict(x) for x in raw]
        if isinstance(raw, dict):
            rows = raw.get("orders") or raw.get("data") or []
            return [dict(x) for x in rows] if isinstance(rows, list) else []
        return []

    def cancel_all_open_algo_orders(self, coin: str) -> dict[str, Any]:
        """Semboldeki tüm açık algo emirlerini iptal et."""
        sym = f"{coin}USDT"
        if self.paper:
            return {"paper": True, "symbol": sym, "code": 200}
        return self._delete("/fapi/v1/algoOpenOrders", {"symbol": sym})

    def take_profit_market_order(
        self,
        coin: str,
        position_side: str,
        quantity: float,
        stop_price: float,
        *,
        working_type: str = "MARK_PRICE",
    ) -> dict[str, Any]:
        """Reduce-only TAKE_PROFIT_MARKET — Binance Algo Order API (2025+ zorunlu)."""
        sym = f"{coin}USDT"
        qty = self.round_qty(coin, quantity, for_market=True)
        sp = self.round_price(coin, stop_price)
        if qty <= 0 or sp <= 0:
            raise ValueError(f"Geçersiz TP {coin}: qty={quantity} stop={stop_price}")
        side = str(position_side or "LONG").upper()
        side_bn = "SELL" if side == "LONG" else "BUY"
        if self.paper:
            return {
                "paper": True,
                "symbol": sym,
                "side": side_bn,
                "qty": qty,
                "triggerPrice": sp,
                "type": "TAKE_PROFIT_MARKET",
                "algoId": "paper_tp",
                "orderId": "paper_tp",
            }
        params: dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": sym,
            "side": side_bn,
            "type": "TAKE_PROFIT_MARKET",
            "quantity": self.format_qty(coin, qty, for_market=True),
            "triggerPrice": self.format_price(coin, sp),
            "reduceOnly": "true",
            "workingType": working_type,
        }
        raw = self._post("/fapi/v1/algoOrder", params)
        if isinstance(raw, dict):
            aid = raw.get("algoId") or raw.get("orderId")
            if aid is not None:
                raw.setdefault("orderId", aid)
                raw["algoId"] = aid
                raw["is_algo_order"] = True
        return raw

    def stop_market_order(
        self,
        coin: str,
        position_side: str,
        quantity: float,
        stop_price: float,
        *,
        working_type: str = "MARK_PRICE",
    ) -> dict[str, Any]:
        """Reduce-only STOP_MARKET — trailing kâr kilidi (fiyat geri çekilince kapat)."""
        sym = f"{coin}USDT"
        qty = self.round_qty(coin, quantity, for_market=True)
        sp = self.round_price(coin, stop_price)
        if qty <= 0 or sp <= 0:
            raise ValueError(f"Geçersiz stop {coin}: qty={quantity} stop={stop_price}")
        side = str(position_side or "LONG").upper()
        side_bn = "SELL" if side == "LONG" else "BUY"
        if self.paper:
            return {
                "paper": True,
                "symbol": sym,
                "side": side_bn,
                "qty": qty,
                "triggerPrice": sp,
                "type": "STOP_MARKET",
                "algoId": "paper_lock",
                "orderId": "paper_lock",
            }
        params: dict[str, Any] = {
            "algoType": "CONDITIONAL",
            "symbol": sym,
            "side": side_bn,
            "type": "STOP_MARKET",
            "quantity": self.format_qty(coin, qty, for_market=True),
            "triggerPrice": self.format_price(coin, sp),
            "reduceOnly": "true",
            "workingType": working_type,
        }
        raw = self._post("/fapi/v1/algoOrder", params)
        if isinstance(raw, dict):
            aid = raw.get("algoId") or raw.get("orderId")
            if aid is not None:
                raw.setdefault("orderId", aid)
                raw["algoId"] = aid
                raw["is_algo_order"] = True
        return raw

    def open_orders(self, coin: str | None = None) -> list[dict[str, Any]]:
        """Açık limit/stop emirleri — sembol setup öncesi kontrol."""
        if self.paper:
            return []
        params: dict[str, Any] = {}
        if coin:
            params["symbol"] = f"{coin}USDT"
        raw = self._get("/fapi/v1/openOrders", params, signed=True)
        if isinstance(raw, list):
            return [dict(x) for x in raw]
        return []

    def symbol_has_open_orders(self, coin: str) -> bool:
        """Sembolde açık emir (normal + algo) var mı — teşhis/test."""
        if self.paper or not coin:
            return False
        try:
            if self.open_orders(coin):
                return True
            return bool(self.open_algo_orders(coin))
        except Exception:
            return False

    def _symbol_setup_blocked(self, coin: str) -> bool:
        """Önceki -4047/-4067 sonrası margin/leverage REST atla."""
        if not _skip_symbol_setup_on_orders():
            return False
        now = time.time()
        if now < _global_setup_block_until:
            return True
        return now < float(_symbol_setup_cooldown.get(coin) or 0)

    def ensure_leverage(self, coin: str, leverage: int | None = None) -> int:
        lev = int(leverage or cfg.LEVERAGE_DEFAULT)
        lev = max(cfg.LEVERAGE_MIN, min(cfg.LEVERAGE_MAX, lev))
        if self.paper:
            return lev
        if self._leverage_set.get(coin) == lev:
            return lev
        if self._symbol_setup_blocked(coin):
            self._leverage_set[coin] = lev
            return lev
        if not self.symbol_tradable(coin):
            return lev
        sym = f"{coin}USDT"
        try:
            self._post(
                "/fapi/v1/leverage",
                {"symbol": sym, "leverage": lev},
            )
            self._leverage_set[coin] = lev
        except httpx.HTTPStatusError as exc:
            body = exc.response.text if exc.response is not None else str(exc)
            if _is_invalid_symbol_error(body):
                self._mark_symbol_untradable(coin)
            elif _is_setup_block_error(body):
                _note_symbol_setup_block(coin, body, leverage=lev, client=self)
            else:
                print(f"  ⚠ leverage {coin} {lev}x: {body[:120]}")
        except Exception as exc:
            body = str(exc)
            if _is_invalid_symbol_error(body):
                self._mark_symbol_untradable(coin)
            elif _is_setup_block_error(body):
                _note_symbol_setup_block(coin, body, leverage=lev, client=self)
            else:
                print(f"  ⚠ leverage {coin} {lev}x: {body[:120]}")
        return lev

    def ensure_margin_type(self, coin: str, margin_type: str | None = None) -> str:
        """ISOLATED: pozisyon riski diğerlerinden ayrı (çoklu scalp için önerilir)."""
        mt = (margin_type or cfg.MARGIN_TYPE or "isolated").strip().upper()
        if mt not in ("ISOLATED", "CROSSED"):
            mt = "ISOLATED"
        if self.paper:
            return mt
        if self._margin_set.get(coin) == mt:
            return mt
        if self._symbol_setup_blocked(coin):
            self._margin_set[coin] = mt
            return mt
        if not self.symbol_tradable(coin):
            return mt
        sym = f"{coin}USDT"
        try:
            self._post(
                "/fapi/v1/marginType",
                {"symbol": sym, "marginType": mt},
            )
            self._margin_set[coin] = mt
        except httpx.HTTPStatusError as exc:
            body = exc.response.text if exc.response is not None else str(exc)
            if _is_invalid_symbol_error(body):
                self._mark_symbol_untradable(coin)
            elif "-4046" in body or "No need to change" in body:
                self._margin_set[coin] = mt
            elif _is_setup_block_error(body):
                _note_symbol_setup_block(coin, body, margin_type=mt, client=self)
            else:
                print(f"  ⚠ margin {coin} {mt}: {body[:120]}")
        except Exception as exc:
            body = str(exc)
            if _is_invalid_symbol_error(body):
                self._mark_symbol_untradable(coin)
            elif _is_setup_block_error(body):
                _note_symbol_setup_block(coin, body, margin_type=mt, client=self)
            else:
                print(f"  ⚠ margin {coin} {mt}: {body[:120]}")
        return mt

    def all_prices(self) -> dict[str, float]:
        if cfg.MARK_WS_ENABLED:
            try:
                from binance_futures_trader.mark_ws import get_mark_prices

                ws = get_mark_prices()
                if len(ws) >= max(1, len(cfg.WATCHLIST) // 2):
                    merged = dict(self._last_prices)
                    merged.update(ws)
                    self._last_prices = merged
                    return merged
            except Exception:
                pass
        # Kısa timeout istemciyle REST fallback
        for attempt in range(2):
            try:
                raw = self._get_price("/fapi/v1/ticker/price")
                out: dict[str, float] = {}
                if not isinstance(raw, list):
                    return dict(self._last_prices)
                for row in raw:
                    try:
                        sym = str(row["symbol"])
                        if sym.endswith("USDT"):
                            coin = sym.replace("USDT", "")
                            out[coin] = float(row["price"])
                    except Exception:
                        pass
                if out:
                    self._last_prices = out
                return out or dict(self._last_prices)
            except Exception as exc:
                if attempt == 0:
                    time.sleep(1)
                    continue
                print(f"  ⚠ Binance API price fetch: {str(exc)[:80]}")
        return dict(self._last_prices)

    def mark_price(self, coin: str) -> float | None:
        sym = f"{coin}USDT"
        try:
            d = self._get_price("/fapi/v1/premiumIndex", {"symbol": sym})
            return float(d.get("markPrice") or d.get("indexPrice") or 0)
        except Exception:
            return self.all_prices().get(coin)

    def klines(self, coin: str, interval: str = "15m", limit: int = 60) -> list[dict]:
        batch = self._klines_raw(coin, interval, limit=limit)
        return self._parse_klines(batch)

    def _parse_klines(self, raw: list) -> list[dict]:
        out: list[dict] = []
        if not isinstance(raw, list):
            return out
        for c in raw:
            try:
                out.append(
                    {
                        "t": int(c[0]),
                        "o": float(c[1]),
                        "h": float(c[2]),
                        "l": float(c[3]),
                        "c": float(c[4]),
                        "v": float(c[5]),
                    }
                )
            except Exception:
                pass
        return out

    def _klines_raw(
        self,
        coin: str,
        interval: str,
        *,
        limit: int = 500,
        end_time_ms: int | None = None,
    ) -> list:
        sym = f"{coin}USDT"
        params: dict[str, Any] = {
            "symbol": sym,
            "interval": interval,
            "limit": min(limit, 1500),
        }
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        try:
            raw = self._get("/fapi/v1/klines", params)
        except Exception:
            return []
        return raw if isinstance(raw, list) else []

    def klines_history(
        self,
        coin: str,
        interval: str,
        days: int = 180,
        *,
        cache_dir: Path | None = None,
    ) -> list[dict]:
        """Sayfalı geçmiş mum — 6 ay backtest için (disk önbelleği opsiyonel)."""
        cache_root = cache_dir or (cfg.ROOT / "data" / "education" / "klines_cache")
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_file = cache_root / f"{coin}_{interval}_{days}d.json"
        if cache_file.is_file():
            try:
                import json

                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(data, list) and len(data) > 100:
                    return data
            except Exception:
                pass

        bars_per_day = {
            "1m": 1440,
            "5m": 288,
            "15m": 96,
            "1h": 24,
            "4h": 6,
            "1d": 1,
        }.get(interval, 96)
        need = days * bars_per_day + 50
        all_rows: list[dict] = []
        end_ms: int | None = None
        while len(all_rows) < need:
            raw = self._klines_raw(coin, interval, limit=1500, end_time_ms=end_ms)
            if not raw:
                break
            batch = self._parse_klines(raw)
            if not batch:
                break
            all_rows = batch + all_rows
            end_ms = int(raw[0][0]) - 1
            if len(raw) < 1500:
                break
            time.sleep(0.12)

        # Tekrarlı zaman damgalarını temizle
        seen: set[int] = set()
        deduped: list[dict] = []
        for row in all_rows:
            t = int(row.get("t") or 0)
            if t in seen:
                continue
            seen.add(t)
            deduped.append(row)
        deduped.sort(key=lambda x: x["t"])

        if deduped:
            try:
                import json

                cache_file.write_text(json.dumps(deduped), encoding="utf-8")
            except Exception:
                pass
        return deduped

    def funding_rate(self, coin: str) -> float | None:
        sym = f"{coin}USDT"
        try:
            data = self._get("/fapi/v1/fundingRate", {"symbol": sym, "limit": 1})
            if data and isinstance(data, list):
                return float(data[0]["fundingRate"])
        except Exception:
            pass
        return None

    def exchange_balance(self) -> float | None:
        w = self.exchange_wallet()
        if not w:
            return None
        return float(w.get("available_balance") or w.get("total_wallet_balance") or 0)

    def exchange_wallet(self) -> dict[str, Any] | None:
        """Demo/canlı futures cüzdan — tek /fapi/v2/account çağrısı (SSL yükü yarıya)."""
        if self.paper:
            return None
        try:
            acct = self._get("/fapi/v2/account", signed=True)
        except Exception as exc:
            print(f"  ⚠ account: {exc}")
            return None
        if not acct:
            return None
        total_wb = float(acct.get("totalWalletBalance") or 0)
        avail = float(acct.get("availableBalance") or 0)
        margin = float(acct.get("totalMarginBalance") or total_wb)
        unrl = float(acct.get("totalUnrealizedProfit") or 0)
        return {
            "total_wallet_balance": round(total_wb, 4),
            "available_balance": round(avail, 4),
            "total_margin_balance": round(margin, 4),
            "total_unrealized_pnl": round(unrl, 4),
            "usdt_balance": round(total_wb, 4),
            "usdt_available": round(avail, 4),
            "usdt_cross_wallet": round(total_wb, 4),
            "can_trade": bool(acct.get("canTrade", True)),
            "api_base": api_base(),
            "source": "binance_demo" if getattr(cfg, "FUTURES_DEMO", False) else "binance_futures",
        }

    def exchange_positions(self) -> list[dict[str, Any]]:
        """Binance testnet'te gerçekten açık pozisyonlar (demo.binancefuture.com)."""
        if self.paper:
            return []
        try:
            raw = self._get("/fapi/v2/positionRisk", signed=True)
        except Exception as exc:
            print(f"  ⚠ exchange positions: {exc}")
            return []
        out: list[dict[str, Any]] = []
        for p in raw or []:
            amt = float(p.get("positionAmt") or 0)
            if abs(amt) < 1e-12:
                continue
            coin = str(p["symbol"]).replace("USDT", "")
            side = "LONG" if amt > 0 else "SHORT"
            entry = float(p.get("entryPrice") or 0)
            mark = float(p.get("markPrice") or 0)
            iso_margin = float(p.get("isolatedMargin") or 0)
            init_margin = float(p.get("positionInitialMargin") or 0)
            margin_used = iso_margin if iso_margin > 0 else init_margin
            amt_abs = abs(amt)
            exchange_raw = {
                "entryPrice": str(p.get("entryPrice") or ""),
                "markPrice": str(p.get("markPrice") or ""),
                "unRealizedProfit": str(p.get("unRealizedProfit") or ""),
                "percentage": str(p.get("percentage") or ""),
                "notional": str(p.get("notional") or ""),
                "positionAmt": str(p.get("positionAmt") or ""),
                "breakEvenPrice": str(p.get("breakEvenPrice") or ""),
                "isolatedMargin": str(p.get("isolatedMargin") or ""),
                "positionInitialMargin": str(p.get("positionInitialMargin") or ""),
                "marginType": str(p.get("marginType") or ""),
                "updateTime": str(p.get("updateTime") or ""),
                "leverage": str(p.get("leverage") or ""),
            }
            out.append(
                {
                    "coin": coin,
                    "symbol": p["symbol"],
                    "side": side,
                    "contracts": amt_abs,
                    "entry_price": entry,
                    "mark_price": mark,
                    "unrealized_pnl": float(p.get("unRealizedProfit") or 0),
                    "leverage": int(float(p.get("leverage") or cfg.LEVERAGE_DEFAULT)),
                    "notional_usd": abs(float(p.get("notional") or 0)),
                    "margin_used": margin_used,
                    "break_even_price": float(p.get("breakEvenPrice") or 0),
                    "margin_type": str(p.get("marginType") or ""),
                    "exchange_raw": exchange_raw,
                    "exchange_update_ms": int(p.get("updateTime") or 0),
                    "source": "binance_demo" if getattr(cfg, "FUTURES_DEMO", False) else "binance_testnet",
                }
            )
        return out

    def market_order(
        self,
        coin: str,
        side: str,
        quantity: float,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        sym = f"{coin}USDT"
        qty = self.round_qty(coin, quantity, for_market=True)
        if qty <= 0:
            raise ValueError(f"Geçersiz miktar {coin}: {quantity}")
        side_bn = "BUY" if side == "LONG" else "SELL"
        if not reduce_only:
            px = self.mark_price(coin) or 0.0
            rule = self._symbol_rule(coin)
            if px * qty < rule["min_notional"]:
                raise ValueError(
                    f"{coin} notional ${px * qty:.1f} < min ${rule['min_notional']:.0f}"
                )
        params: dict[str, Any] = {
            "symbol": sym,
            "side": side_bn,
            "type": "MARKET",
            "quantity": self.format_qty(coin, qty, for_market=True),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        if self.paper:
            px = self.mark_price(coin) or 0.0
            return {
                "paper": True,
                "symbol": sym,
                "side": side,
                "qty": qty,
                "price": px,
                "reduce_only": reduce_only,
            }
        return self._post("/fapi/v1/order", params)

    def limit_order(
        self,
        coin: str,
        side: str,
        quantity: float,
        price: float,
        *,
        reduce_only: bool = False,
        post_only: bool = False,
        time_in_force: str = "GTC",
    ) -> dict[str, Any]:
        sym = f"{coin}USDT"
        qty = self.round_qty(coin, quantity)
        if qty <= 0:
            raise ValueError(f"Geçersiz miktar {coin}: {quantity}")
        px = float(price)
        if px <= 0:
            raise ValueError(f"Geçersiz fiyat {coin}: {price}")
        side_bn = "BUY" if side == "LONG" else "SELL"
        tif = str(time_in_force or "GTC").upper()
        if post_only:
            tif = "GTX"
        params: dict[str, Any] = {
            "symbol": sym,
            "side": side_bn,
            "type": "LIMIT",
            "quantity": self.format_qty(coin, qty),
            "price": self.format_price(coin, px),
            "timeInForce": tif,
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        if self.paper:
            return {
                "paper": True,
                "symbol": sym,
                "side": side,
                "qty": qty,
                "price": px,
                "type": "LIMIT",
                "post_only": post_only,
                "reduce_only": reduce_only,
            }
        return self._post("/fapi/v1/order", params)

    def user_trades(
        self,
        coin: str,
        *,
        order_id: int | str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if self.paper:
            return []
        sym = f"{coin}USDT"
        params: dict[str, Any] = {"symbol": sym, "limit": min(limit, 1000)}
        if order_id is not None:
            params["orderId"] = int(order_id)
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        try:
            raw = self._get("/fapi/v1/userTrades", params, signed=True)
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for row in raw or []:
            try:
                out.append(
                    {
                        "id": row.get("id"),
                        "orderId": row.get("orderId"),
                        "price": float(row.get("price") or 0),
                        "qty": float(row.get("qty") or 0),
                        "quoteQty": float(row.get("quoteQty") or 0),
                        "commission": float(row.get("commission") or 0),
                        "commissionAsset": str(row.get("commissionAsset") or ""),
                        "realizedPnl": float(row.get("realizedPnl") or 0),
                        "side": str(row.get("side") or ""),
                        "time": int(row.get("time") or 0),
                    }
                )
            except Exception:
                continue
        return out

    def order_commission(self, coin: str, order_id: str | int | None) -> float:
        if self.paper or not order_id:
            return 0.0
        try:
            trades = self.user_trades(coin, order_id=order_id, limit=50)
            return round(
                sum(abs(float(t.get("commission") or 0)) for t in trades),
                6,
            )
        except Exception:
            return 0.0

    def income_history(
        self,
        coin: str,
        *,
        start_ms: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if self.paper:
            return []
        sym = f"{coin}USDT"
        params: dict[str, Any] = {"symbol": sym, "limit": limit}
        if start_ms:
            params["startTime"] = start_ms
        try:
            raw = self._get("/fapi/v1/income", params, signed=True)
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for row in raw or []:
            try:
                out.append(
                    {
                        "type": str(row.get("incomeType") or ""),
                        "income": float(row.get("income") or 0),
                        "asset": str(row.get("asset") or "USDT"),
                        "time": int(row.get("time") or 0),
                    }
                )
            except Exception:
                pass
        return out
