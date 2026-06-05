"""Demo Binance — gerçekçi kapanış: book bid/ask fill, komisyon + Est. Funding sonrası net."""
from __future__ import annotations

import os
import threading
import time
from typing import Any

from elite_trader.fee_economics import (
    close_pnl_at_fill_api,
    entry_fee_api_ready,
    exit_min_net_usd,
    exit_net_passes,
    is_profit_tp_exit,
)


def _coin(sym: str) -> str:
    return str(sym or "").replace("USDT", "").upper()


_book_cache: dict[str, tuple[dict[str, Any], float]] = {}
_book_cache_lock = threading.Lock()


def _book_ticker(coin: str, *, client: Any = None, max_age_ms: float = 400) -> dict[str, Any] | None:
    """bookTicker bid/ask — MEGA hub WS önce, genel WS, demo-fapi REST yedek."""
    coin_u = _coin(coin if "USDT" not in coin else coin.replace("USDT", ""))
    ttl = max(0.25, float(max_age_ms) / 1000.0)
    now = time.time()
    with _book_cache_lock:
        hit = _book_cache.get(coin_u)
        if hit and (now - hit[1]) < ttl:
            return dict(hit[0])
    try:
        from elite_trader.mega_async_hub import get_hub_book

        hub_book = get_hub_book(coin_u, max_age_ms=min(200.0, max_age_ms))
        if hub_book:
            with _book_cache_lock:
                _book_cache[coin_u] = (hub_book, time.time())
            return dict(hub_book)
    except Exception:
        pass
    try:
        from binance_futures_trader.fast_price_ws import get_fast_price

        ws = get_fast_price(coin_u, max_age_ms=int(max(80, max_age_ms)))
        if ws:
            bid = float(ws.get("bid") or 0)
            ask = float(ws.get("ask") or 0)
            mid = float(ws.get("mid") or 0)
            if bid > 0 and ask > 0:
                row_out = {
                    "bid": bid,
                    "ask": ask,
                    "mid": mid or (bid + ask) / 2.0,
                    "ts_ms": int(time.time() * 1000),
                    "src": "ws_book",
                }
                with _book_cache_lock:
                    _book_cache[coin_u] = (row_out, time.time())
                return row_out
    except Exception:
        pass
    if client is None:
        try:
            from binance_elite_pro import client as c

            client = c
        except Exception:
            client = None
    if client is None or getattr(client, "paper", True):
        return None
    try:
        t0 = time.perf_counter()
        row = client._get(
            "/fapi/v1/ticker/bookTicker",
            params={"symbol": f"{coin_u}USDT"},
        )
        rest_ms = (time.perf_counter() - t0) * 1000.0
        bid = float(row.get("bidPrice") or 0)
        ask = float(row.get("askPrice") or 0)
        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
            row_out = {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "ts_ms": int(time.time() * 1000),
                "src": "demo_rest",
                "rest_ms": round(rest_ms, 2),
            }
            with _book_cache_lock:
                _book_cache[coin_u] = (row_out, time.time())
            return row_out
    except Exception:
        pass
    return None


def _fill_book_max_age_ms() -> float:
    raw = os.getenv("MEGA_FILL_BOOK_MAX_MS", "90").strip()
    try:
        return max(50.0, min(350.0, float(raw)))
    except ValueError:
        return 90.0


def _is_mega_spike_reason(exit_reason: str | None) -> bool:
    return str(exit_reason or "").upper() in (
        "SPIKE-FLASH",
        "SPIKE-QUICK",
        "SPIKE-PEAK",
        "TP-PEAK",
    )


def _mega_spike_take_gross_env() -> float:
    raw = os.getenv("MEGA_SPIKE_TAKE_GROSS_USD", "14").strip()
    try:
        return max(8.0, float(raw))
    except ValueError:
        return 14.0


def _book_spread_cost_usd(pos: dict[str, Any], book: dict[str, Any] | None) -> float:
    """LONG kapanış bid−mid; SHORT kapanış ask−mid — panel mark vs fill farkı."""
    if not book:
        return 0.0
    size = float(pos.get("size") or 0)
    if size <= 0:
        return 0.0
    bid = float(book.get("bid") or 0)
    ask = float(book.get("ask") or 0)
    mid = float(book.get("mid") or 0)
    if mid <= 0 and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
    side = str(pos.get("side") or "LONG").upper()
    if side == "LONG" and mid > 0 and bid > 0:
        return max(0.0, round((mid - bid) * size, 4))
    if side == "SHORT" and mid > 0 and ask > 0:
        return max(0.0, round((ask - mid) * size, 4))
    return 0.0


def fill_slippage_reject(
    mark_gross: float,
    fill_gross: float,
    *,
    pre_send_gross: float = 0.0,
    strict: bool = False,
) -> bool:
    """API/mark kâr iken fill çökmesi (ARB tipi) — emir yok."""
    mark_g = float(mark_gross or 0)
    fill_g = float(fill_gross or 0)
    pre_g = float(pre_send_gross or mark_g or 0)
    slip_ratio = _env_float(
        "MEGA_SEND_FILL_SLIP_RATIO" if strict else "MEGA_SPIKE_FILL_SLIP_RATIO",
        0.42 if strict else 0.28,
    )
    pre_ratio = _env_float(
        "MEGA_SEND_PRE_SEND_SLIP_RATIO" if strict else "MEGA_FILL_PRE_SEND_SLIP_RATIO",
        0.50 if strict else 0.35,
    )
    if mark_g >= _mega_spike_take_gross_env():
        ratio = max(0.22, min(0.55, slip_ratio))
        if fill_g < mark_g * ratio:
            return True
    if pre_g >= 10.0 and fill_g < pre_g * max(0.35, min(0.60, pre_ratio)):
        return True
    if strict and pre_g >= 8.0 and fill_g <= 0:
        return True
    if mark_g > 6.0 and fill_g < 0:
        return True
    if strict and mark_g >= 12.0 and fill_g < 4.0:
        return True
    return False


def clear_fill_verify_cache(pos: dict[str, Any]) -> None:
    for key in (
        "fill_verify_ok",
        "fill_verify_detail",
        "fill_verify_at_ms",
        "fill_gross_unreal",
        "fill_net_est",
    ):
        pos.pop(key, None)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def exit_fill_price(
    pos: dict[str, Any],
    *,
    client: Any = None,
    max_book_age_ms: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """
    Market kapanış fill tahmini.
    LONG kapat = satış → bid; SHORT kapat = alış → ask.
    """
    sym = str(pos.get("symbol") or "")
    side = str(pos.get("side") or "LONG").upper()
    age = _fill_book_max_age_ms() if max_book_age_ms is None else max(50.0, float(max_book_age_ms))
    book = _book_ticker(sym, client=client, max_age_ms=age)
    meta: dict[str, Any] = {"book": book or {}}
    if not book:
        return None, meta
    px = float(book["bid"]) if side == "LONG" else float(book["ask"])
    meta["fill_side"] = "bid" if side == "LONG" else "ask"
    return px, meta



def fill_gross_unreal(
    pos: dict[str, Any],
    *,
    client: Any = None,
    max_age_ms: float = 0.0,
) -> float | None:
    """Bid/ask fill — hub/WS bookTicker (ms)."""
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    if entry <= 0 or size <= 0:
        return None
    age = max_age_ms if max_age_ms > 0 else _fill_book_max_age_ms()
    fill_px, _ = exit_fill_price(pos, client=client, max_book_age_ms=age)
    if fill_px is None or fill_px <= 0:
        return None
    side = str(pos.get("side") or "LONG").upper()
    if side == "LONG":
        gross = round((fill_px - entry) * size, 4)
    else:
        gross = round((entry - fill_px) * size, 4)
    return gross


def _ensure_entry_fee_api(pos: dict[str, Any], *, client: Any = None) -> bool:
    if entry_fee_api_ready(pos):
        return True
    if client is None:
        try:
            from binance_elite_pro import client as c

            client = c
        except Exception:
            client = None
    if client is None or getattr(client, "paper", True):
        return False
    try:
        from elite_trader.exchange_trade_truth import enrich_open_entry_fee_api

        enrich_open_entry_fee_api(pos, client, allow_fetch=True)
    except Exception:
        pass
    return entry_fee_api_ready(pos)


def estimate_close_at_fill(
    pos: dict[str, Any],
    *,
    client: Any = None,
    fill_px: float | None = None,
    max_book_age_ms: float | None = None,
    skip_fee_fetch: bool = False,
) -> dict[str, Any]:
    """Fill fiyatında brüt uPnL − API komisyon − premiumIndex funding → cüzdan net."""
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    mark_unreal = float(
        pos.get("exchange_unrealized_pnl") or pos.get("unrealized_pnl") or 0
    )
    if client is None:
        try:
            from binance_elite_pro import client as c

            client = c
        except Exception:
            client = None
    book_age = max_book_age_ms if max_book_age_ms is not None else _fill_book_max_age_ms()
    if fill_px is None:
        fill_px, book_meta = exit_fill_price(
            pos, client=client, max_book_age_ms=book_age
        )
    else:
        _, book_meta = exit_fill_price(
            pos, client=client, max_book_age_ms=book_age
        )
    if fill_px is None or fill_px <= 0 or entry <= 0 or size <= 0:
        return {
            "ok": False,
            "fill_price": None,
            "mark_unreal": mark_unreal,
            "fill_gross": None,
            "net_pnl": None,
            "book": book_meta.get("book") or {},
            "source": "bookTicker_missing",
        }
    side = str(pos.get("side") or "LONG").upper()
    if side == "LONG":
        fill_gross = round((float(fill_px) - entry) * size, 4)
    else:
        fill_gross = round((entry - float(fill_px)) * size, 4)
    if not skip_fee_fetch and not _ensure_entry_fee_api(pos, client=client):
        return {
            "ok": False,
            "fill_price": round(float(fill_px), 8),
            "mark_unreal": mark_unreal,
            "fill_gross": fill_gross,
            "net_pnl": None,
            "book": book_meta.get("book") or {},
            "source": "api_fee_missing",
        }
    if skip_fee_fetch and not entry_fee_api_ready(pos):
        skip_fee_fetch = False
        if not _ensure_entry_fee_api(pos, client=client):
            return {
                "ok": False,
                "fill_price": round(float(fill_px), 8),
                "mark_unreal": mark_unreal,
                "fill_gross": fill_gross,
                "net_pnl": None,
                "book": book_meta.get("book") or {},
                "source": "api_fee_missing",
            }
    api = close_pnl_at_fill_api(pos, fill_gross, float(fill_px), client=client)
    if api is None:
        return {
            "ok": False,
            "fill_price": round(float(fill_px), 8),
            "mark_unreal": mark_unreal,
            "fill_gross": fill_gross,
            "net_pnl": None,
            "book": book_meta.get("book") or {},
            "source": "api_fee_missing",
        }
    return {
        **api,
        "ok": True,
        "fill_price": round(float(fill_px), 8),
        "mark_unreal": mark_unreal,
        "fill_gross": fill_gross,
        "book": book_meta.get("book") or {},
        "book_meta": book_meta,
        "source": "book_fill_api",
    }


def exchange_bid_profit_ok(
    pos: dict[str, Any],
    client: Any = None,
    *,
    mode_id: str | None = None,
    min_net: float | None = None,
    max_book_age_ms: float | None = None,
) -> tuple[bool, str]:
    """
    Borsa TP/kilit öncesi — mevcut bid/ask ile kapanış gerçekten net kâr mı?
    Hub/WS book önbelleği; ek REST yok (taze değilse tek bookTicker).
    """
    mid = str(mode_id or "mega").lower()
    floor = float(min_net) if min_net is not None else exit_min_net_usd(mid)
    book_ms = (
        float(max_book_age_ms)
        if max_book_age_ms is not None
        else max(60.0, min(120.0, _env_float("MEGA_EXCHANGE_FILL_BOOK_MAX_MS", 90.0)))
    )
    est = estimate_close_at_fill(
        pos,
        client=client,
        max_book_age_ms=book_ms,
        skip_fee_fetch=entry_fee_api_ready(pos),
    )
    src = str(est.get("source") or "")
    if src in ("mark_fallback", "bookTicker_missing"):
        return False, "bookTicker yok — borsa algo yok"
    if src == "api_fee_missing":
        return False, "giriş fee API yok — borsa algo yok"
    fill_g = float(est.get("fill_gross") or 0)
    final = float(est.get("final_pnl") or est.get("net_pnl") or 0)
    mark_u = float(
        est.get("mark_unreal")
        or pos.get("exchange_unrealized_pnl")
        or pos.get("unrealized_pnl")
        or 0
    )
    pos["fill_gross_unreal"] = fill_g
    pos["fill_net_est"] = final
    if fill_g <= 0:
        return (
            False,
            f"bid fill brüt ${fill_g:.2f} ≤ 0 @ {est.get('fill_price')}",
        )
    if not exit_net_passes(final, mid) or final < floor - 0.02:
        return (
            False,
            f"bid fill net ${final:.2f} < min ${floor:.2f}",
        )
    if mark_u > 0.5 and fill_slippage_reject(
        mark_u, fill_g, pre_send_gross=mark_u, strict=True
    ):
        return (
            False,
            f"mark/fill slip mark=${mark_u:.2f} fill=${fill_g:.2f}",
        )
    return True, ""


def fill_gross_sane_vs_mark(
    est: dict[str, Any],
    pos: dict[str, Any],
    *,
    exit_reason: str | None = None,
) -> bool:
    """Fill çok iyimserse reddet; LONG bid<mark normal — yalnızca aşırı iyimserlik."""
    fill_g = est.get("fill_gross")
    if fill_g is None:
        return False
    fill_g = float(fill_g)
    mark = float(
        est.get("mark_unreal")
        if est.get("mark_unreal") is not None
        else pos.get("exchange_unrealized_pnl") or pos.get("unrealized_pnl") or 0
    )
    if mark <= 0.01:
        return fill_g > 0
    if fill_g < 0:
        return False
    gap = fill_g - mark
    cap = max(0.55, abs(mark) * 2.5)
    if gap > cap:
        return False
    if _is_mega_spike_reason(exit_reason) and mark >= _mega_spike_take_gross_env() * 0.65:
        mark_tol = max(0.28, min(0.55, _env_float("MEGA_SPIKE_FILL_MARK_RATIO", 0.38)))
        spread_tol = max(0.5, _env_float("MEGA_SPIKE_SPREAD_TOL_USD", 1.25))
        book = est.get("book") or {}
        spread_cost = _book_spread_cost_usd(pos, book)
        adj = mark - spread_cost - spread_tol
        if fill_g >= mark * mark_tol or fill_g >= adj:
            return True
    return True


def fill_net_close_ready(
    pos: dict[str, Any],
    *,
    client: Any = None,
    mode_id: str | None = None,
    exit_reason: str | None = None,
    fast: bool = False,
) -> tuple[bool, float, float, dict[str, Any]]:
    est = estimate_close_at_fill(
        pos,
        client=client,
        max_book_age_ms=_fill_book_max_age_ms() if fast else None,
        skip_fee_fetch=fast and entry_fee_api_ready(pos),
    )
    floor = exit_min_net_usd(mode_id, exit_reason=exit_reason)
    final = float(est.get("final_pnl") or est.get("net_pnl") or 0)
    sane = fill_gross_sane_vs_mark(est, pos, exit_reason=exit_reason)
    ok = (
        exit_net_passes(final, mode_id)
        and est.get("source") == "book_fill_api"
        and est.get("ok") is not False
        and sane
    )
    if not sane and est.get("source") == "book_fill_api":
        est = {**est, "fill_mark_divergence": True}
    return ok, final, floor, est


def _fill_verify_snap(est: dict[str, Any], final: float) -> dict[str, Any]:
    return {
        "signal_fill_px": est.get("fill_price"),
        "signal_mark_unreal": est.get("mark_unreal"),
        "signal_fill_gross": est.get("fill_gross"),
        "signal_est_net": final,
        "signal_est_fees": est.get("total_fees"),
        "signal_est_funding": est.get("est_funding_fee"),
        "signal_est_net_pnl": est.get("net_pnl"),
        "signal_book": est.get("book") or {},
        "signal_at_ms": int(time.time() * 1000),
        "signal_verify_ms": est.get("verify_ms"),
    }


def mega_profit_fill_verify_fast(
    pos: dict[str, Any],
    exit_reason: str,
    *,
    client: Any = None,
    mode_id: str | None = None,
    force_fresh: bool = False,
    at_send: bool = False,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Tek geçiş kâr/spike kapanış doğrulama — hub book ms, spread toleransı, slippage koruması.
    Sonuç pos üzerinde önbelleğe yazılır (çift REST/book yok).
    at_send=True: önbellek yok, soft bypass yok — MARKET/IOC öncesi son kontrol.
    """
    if not is_profit_tp_exit(exit_reason):
        return True, "", {}
    try:
        from elite_trader.mega_live import _mega_arm_demo_fast_close

        if pos.get("demo_fast_close") or _mega_arm_demo_fast_close(pos, client):
            pos["demo_fast_close"] = True
    except Exception:
        pass
    if force_fresh or at_send:
        clear_fill_verify_cache(pos)
    elif not at_send:
        cache_ms = max(40.0, min(200.0, _env_float("MEGA_FILL_VERIFY_CACHE_MS", 85.0)))
        cached_at = float(pos.get("fill_verify_at_ms") or 0)
        if pos.get("fill_verify_ok") and cached_at:
            if (time.time() * 1000.0 - cached_at) < cache_ms:
                return True, str(pos.get("fill_verify_detail") or ""), dict(
                    pos.get("close_signal") or {}
                )

    if pos.get("on_exchange"):
        try:
            from elite_trader.mega_live import (
                _mega_positions_cache,
                _sync_pos_from_exchange,
                refresh_mega_positions_cache,
            )

            refresh_mega_positions_cache(
                force=True, skip_wallet=True, panel_critical=True
            )
            _sync_pos_from_exchange(pos, list(_mega_positions_cache), mode_id="mega")
        except Exception:
            pass
    t0 = time.perf_counter()
    mid = str(mode_id or "mega").lower()
    book_ms = (
        max(40.0, min(120.0, _env_float("MEGA_SEND_FILL_BOOK_MAX_MS", 60.0)))
        if at_send
        else _fill_book_max_age_ms()
    )
    est = estimate_close_at_fill(
        pos,
        client=client,
        max_book_age_ms=book_ms,
        skip_fee_fetch=entry_fee_api_ready(pos),
    )
    est["verify_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    floor = exit_min_net_usd(mid, exit_reason=exit_reason)
    final = float(est.get("final_pnl") or est.get("net_pnl") or 0)
    fill_g = float(est.get("fill_gross") or 0)
    mark_u = float(
        est.get("mark_unreal")
        or pos.get("exchange_unrealized_pnl")
        or pos.get("unrealized_pnl")
        or 0
    )
    pre_g = float(pos.get("pre_send_gross") or mark_u or 0)
    snap = _fill_verify_snap(est, final)

    if est.get("source") in ("mark_fallback", "bookTicker_missing"):
        return False, "bookTicker yok — fill doğrulanamadı", snap
    if est.get("source") == "api_fee_missing":
        return False, "giriş fee API yok — kapanış yok", snap

    soft = max(2.0, _env_float("MEGA_SPIKE_FILL_SOFT_NET", 2.5))
    spike = _is_mega_spike_reason(exit_reason)
    take = _mega_spike_take_gross_env()
    if (
        at_send
        and spike
        and _env_bool("MEGA_SPIKE_TRUST_MARK_SEND", True)
        and mark_u >= take
        and fill_g > 0
        and mark_u >= floor
    ):
        mark_tol = max(
            0.28, min(0.55, _env_float("MEGA_SPIKE_SEND_MARK_RATIO", 0.38))
        )
        if fill_g >= mark_u * mark_tol or fill_g >= soft:
            pos["fill_gross_unreal"] = fill_g
            pos["fill_net_est"] = max(final, mark_u * 0.85)
            pos["fill_verify_ok"] = True
            pos["fill_verify_detail"] = "spike_mark_send"
            pos["fill_verify_at_ms"] = snap["signal_at_ms"]
            pos["close_signal"] = snap
            return True, "", snap

    slip_strict = at_send and not pos.get("demo_fast_close")
    if fill_slippage_reject(mark_u, fill_g, pre_send_gross=pre_g, strict=slip_strict):
        detail = (
            f"slippage fill brüt ${fill_g:.2f} << mark ${mark_u:.2f} "
            f"(pre ${pre_g:.2f}) @ {est.get('fill_price')}"
        )
        pos["fill_verify_ok"] = False
        pos["fill_verify_detail"] = detail
        pos["fill_verify_at_ms"] = snap["signal_at_ms"]
        return False, detail, snap

    sane = fill_gross_sane_vs_mark(est, pos, exit_reason=exit_reason)
    if not sane:
        detail = (
            f"fill/mark uyumsuz fill=${fill_g:.2f} mark=${mark_u:.2f} "
            f"@ {est.get('fill_price')}"
        )
        pos["fill_verify_ok"] = False
        pos["fill_verify_detail"] = detail
        pos["fill_verify_at_ms"] = snap["signal_at_ms"]
        return False, detail, snap

    pre_net = float(pos.get("pre_send_net") or 0)
    if at_send and pre_net >= 8.0:
        net_frac = max(0.45, min(0.75, _env_float("MEGA_SEND_FILL_NET_FRAC", 0.52)))
        if final < pre_net * net_frac:
            demo_api_ok = False
            if pos.get("demo_fast_close") and mark_u >= 8.0 and fill_g > 0:
                demo_slip = max(
                    0.15, min(0.50, _env_float("MEGA_DEMO_FAST_FILL_SLIP_RATIO", 0.22))
                )
                # Demo book ask/bid mark'tan geride kalabiliyor; API uPnL TP üstündeyse gönder.
                if fill_g >= mark_u * demo_slip and exit_net_passes(pre_net, mid):
                    demo_api_ok = True
                    snap["demo_fast_api_net"] = True
            if not demo_api_ok:
                detail = (
                    f"send fill net ${final:.2f} < pre_net×{net_frac:.2f} "
                    f"(${pre_net:.2f}) @ {est.get('fill_price')}"
                )
                pos["fill_verify_ok"] = False
                pos["fill_verify_detail"] = detail
                pos["fill_verify_at_ms"] = snap["signal_at_ms"]
                return False, detail, snap

    ok = (
        est.get("source") == "book_fill_api"
        and est.get("ok") is not False
        and fill_g > 0
        and exit_net_passes(final, mid, exit_reason=exit_reason)
    )
    if at_send:
        send_gross_ratio = max(
            0.35, min(0.58, _env_float("MEGA_SEND_FILL_GROSS_RATIO", 0.42))
        )
        if mark_u > 0 and fill_g < mark_u * send_gross_ratio:
            detail = (
                f"send fill brüt ${fill_g:.2f} < mark×{send_gross_ratio:.2f} "
                f"(${mark_u:.2f}) @ {est.get('fill_price')}"
            )
            pos["fill_verify_ok"] = False
            pos["fill_verify_detail"] = detail
            pos["fill_verify_at_ms"] = snap["signal_at_ms"]
            return False, detail, snap
    if ok:
        pos["fill_gross_unreal"] = fill_g
        pos["fill_net_est"] = final
        pos["fill_verify_ok"] = True
        pos["fill_verify_detail"] = ""
        pos["fill_verify_at_ms"] = snap["signal_at_ms"]
        pos["close_signal"] = snap
        return True, "", snap

    if spike and mark_u >= take * 0.72 and fill_g > 0:
        try:
            from elite_trader.mega_live import (
                _mega_estimated_wallet_net,
                _mega_spike_exit_net_ok,
            )

            stake = float(pos.get("stake_usd") or 1)
            lev = max(int(pos.get("leverage") or 2), 1)
            mark_net = _mega_estimated_wallet_net(
                pos, mark_u, stake=stake, lev=lev, mc=client
            )
            book = est.get("book") or {}
            spread_cost = _book_spread_cost_usd(pos, book)
            mark_tol = max(0.30, min(0.55, _env_float("MEGA_SPIKE_FILL_MARK_RATIO", 0.38)))
            spread_adj_g = mark_u - spread_cost
            fill_ok_gross = fill_g >= mark_u * mark_tol or fill_g >= spread_adj_g * 0.92
            net_ok = final >= floor or (
                final >= soft
                and mark_net >= floor
                and fill_ok_gross
                and _mega_spike_exit_net_ok(
                    pos, mark_u, mark_net, stake=stake, lev=lev, mc=client
                )
            )
            if net_ok and fill_ok_gross:
                pos["fill_gross_unreal"] = fill_g
                pos["fill_net_est"] = final
                pos["fill_verify_ok"] = True
                pos["fill_verify_detail"] = "spike_spread_tol"
                pos["fill_verify_at_ms"] = snap["signal_at_ms"]
                pos["close_signal"] = snap
                return True, "", snap
        except Exception:
            pass

    detail = (
        f"fill net ${final:.2f} < min ${floor:.2f} "
        f"(fill brüt ${fill_g:.4f} mark ${mark_u:.4f} @ {est.get('fill_price')})"
    )
    pos["fill_verify_ok"] = False
    pos["fill_verify_detail"] = detail
    pos["fill_verify_at_ms"] = snap["signal_at_ms"]
    pos["close_signal"] = snap
    return False, detail, snap


def pre_close_fill_verify_ok(
    pos: dict[str, Any],
    exit_reason: str,
    *,
    client: Any = None,
    mode_id: str | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Kapanış emri öncesi — book fill net > min; mark-only TP engeli."""
    if not is_profit_tp_exit(exit_reason):
        return True, "", {}

    if client is None:
        try:
            from binance_elite_pro import client as c

            client = c
        except Exception:
            pass

    if str(mode_id or "").lower() == "mega":
        return mega_profit_fill_verify_fast(
            pos, exit_reason, client=client, mode_id=mode_id
        )

    ok, final, floor, est = fill_net_close_ready(
        pos, client=client, mode_id=mode_id, fast=True
    )
    snap = {
        "signal_fill_px": est.get("fill_price"),
        "signal_mark_unreal": est.get("mark_unreal"),
        "signal_fill_gross": est.get("fill_gross"),
        "signal_est_net": final,
        "signal_est_fees": est.get("total_fees"),
        "signal_est_funding": est.get("est_funding_fee"),
        "signal_est_net_pnl": est.get("net_pnl"),
        "signal_book": est.get("book") or {},
        "signal_at_ms": int(time.time() * 1000),
    }
    if est.get("source") in ("mark_fallback", "bookTicker_missing", "api_fee_missing"):
        if est.get("source") == "api_fee_missing":
            return False, "giriş/çıkış fee API yok — kapanış yok", snap
        return False, "bookTicker yok — fill doğrulanamadı", snap
    if not ok:
        mark_u = float(est.get("mark_unreal") or pos.get("unrealized_pnl") or 0)
        fill_g = float(est.get("fill_gross") or 0)
        if est.get("fill_mark_divergence"):
            return (
                False,
                f"fill brüt ${fill_g:.4f} mark uPnL ${mark_u:.4f} uyumsuz "
                f"(stale book?) @ ${est.get('fill_price')}",
                snap,
            )
        stake = float(pos.get("stake_usd") or 1)
        lev = max(int(pos.get("leverage") or 2), 1)
        if str(mode_id or "").lower() == "mega" and is_profit_tp_exit(exit_reason):
            try:
                from elite_trader.mega_live import (
                    _mega_is_spike_exit,
                    _mega_spike_exit_net_ok,
                    _mega_spike_take_gross_usd,
                    _mega_estimated_wallet_net,
                )

                if _mega_is_spike_exit(exit_reason) and mark_u >= _mega_spike_take_gross_usd():
                    mark_net = _mega_estimated_wallet_net(
                        pos, mark_u, stake=stake, lev=lev, client=client
                    )
                    if _mega_spike_exit_net_ok(
                        pos, mark_u, mark_net, stake=stake, lev=lev, mc=client
                    ):
                        return True, "", snap
            except Exception:
                pass
        try:
            from elite_trader.fee_economics import (
                estimate_close_pnl,
                exit_net_passes,
                tp_sl_gross_triggers,
            )

            tp_g, _, _, _ = tp_sl_gross_triggers(stake, lev, mode_id)
            if mark_u >= tp_g:
                mark_est = estimate_close_pnl(
                    mark_u,
                    stake,
                    lev,
                    entry_fee=float(pos.get("entry_fee") or 0) or None,
                    pos=pos,
                    client=client,
                )
                if exit_net_passes(float(mark_est["final_pnl"]), mode_id):
                    return True, "", snap
        except Exception:
            pass
        return (
            False,
            f"fill net ${final:.4f} ≤ min ${floor:.2f} "
            f"(fill brüt ${fill_g:.4f} fee ${float(est.get('total_fees') or 0):.4f} "
            f"funding ${float(est.get('est_funding_fee') or 0):+.4f} @ ${est.get('fill_price')})",
            snap,
        )
    return True, "", snap


def fetch_entry_fee_from_exchange(
    client: Any,
    symbol: str,
    side: str,
    *,
    entry_order_id: str | int | None = None,
    opened_at_iso: str | None = None,
    lookback_hours: float = 72.0,
) -> float:
    """Giriş commission — orderId userTrades (tahmin yok)."""
    if client is None or getattr(client, "paper", True):
        return 0.0
    try:
        from elite_trader.exchange_trade_truth import fetch_entry_fee_api

        return fetch_entry_fee_api(
            client,
            symbol=symbol,
            side=side,
            entry_order_id=entry_order_id,
            opened_at_iso=opened_at_iso,
        )
    except Exception:
        pass
    coin = _coin(symbol)
    if entry_order_id:
        try:
            from elite_trader.exchange_settlement import fetch_order_fills

            row = fetch_order_fills(client, coin, entry_order_id)
            if row.get("commission", 0) > 0:
                return round(float(row["commission"]), 8)
        except Exception:
            pass
    try:
        from elite_trader.exchange_settlement import fetch_symbol_trades_since
        from datetime import datetime, timezone, timedelta

        since = opened_at_iso or (
            datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        ).isoformat()
        trades = fetch_symbol_trades_since(client, coin, since, extra_ms=3600_000)
    except Exception:
        return 0.0
    side_u = str(side or "LONG").upper()
    want_buy = side_u == "LONG"
    entry_comm = 0.0
    for t in sorted(trades, key=lambda x: int(x.get("time") or 0)):
        buyer = bool(t.get("buyer"))
        if want_buy and not buyer:
            continue
        if not want_buy and buyer:
            continue
        entry_comm += abs(float(t.get("commission") or 0))
        if float(t.get("realizedPnl") or 0) != 0:
            break
    return round(entry_comm, 8)


def enrich_open_position_fill_fields(
    pos: dict[str, Any],
    *,
    client: Any = None,
    mode_id: str | None = None,
) -> None:
    """Panel/monitor — fill tabanlı net alanları."""
    ok, final, floor, est = fill_net_close_ready(pos, client=client, mode_id=mode_id)
    pos["fill_price_est"] = est.get("fill_price")
    pos["fill_gross_unreal"] = est.get("fill_gross")
    pos["fill_net_est"] = final
    pos["fill_net_ready"] = ok
    pos["exit_min_net_usd"] = floor
    pos["fill_net_fees_est"] = est.get("total_fees")
    pos["fill_net_funding_est"] = est.get("est_funding_fee")
    pos["mark_unrealized_pnl"] = est.get("mark_unreal")
    book = est.get("book") or {}
    if book:
        pos["book_bid"] = book.get("bid")
        pos["book_ask"] = book.get("ask")
        pos["book_src"] = book.get("src")
