"""Ana Hat — gerçek Binance komisyonlarına göre net kâr hedefi (giriş / çıkış)."""
from __future__ import annotations

import os
from typing import Any

from elite_trader.panel_strategy import active_execution_mode, stake_targets


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def fee_rate_per_side() -> float:
    """
    Taker tarafı — Binance API'den gerçek commission rate
    NOT: Bu fonksiyon her çağrıldığında client'a erişmeye çalışır,
    başarısız olursa fallback kullanır
    """
    # Fallback to env var or config (fastest path)
    try:
        from binance_futures_trader import config as cfg
        return float(
            os.getenv("ELITE_FEE_RATE_PER_SIDE", str(cfg.TAKER_FEE_RATE))
        )
    except Exception:
        return _env_float("ELITE_FEE_RATE_PER_SIDE", 0.0004)


def round_trip_fee_usd(
    stake_usd: float,
    leverage: int,
    *,
    fee_mult: float = 1.0,
    extra_sides: int = 2,
) -> float:
    """
    Giriş + çıkış komisyonu (notional = stake × lev).
    extra_sides=2 → açılış + kapanış taker.
    """
    s = max(float(stake_usd), 0.0)
    lev = max(int(leverage), 1)
    notional = s * lev
    rate = fee_rate_per_side()
    return round(notional * rate * max(1, int(extra_sides)) * float(fee_mult), 4)


def net_tp_target_usd(stake_usd: float, mode_id: str | None = None) -> float:
    """Plan hedefi: stake üzerinden net cüzdan kârı (fee hariç tanım)."""
    mid = mode_id or active_execution_mode()
    s = max(float(stake_usd), 0.0)
    gross_tp, _ = stake_targets(s, mid)
    stake_based = round(max(float(gross_tp), 0.0), 4)
    fixed: float | None = None
    if mid:
        try:
            from elite_trader.mode_profiles import get_profile

            p = get_profile(mid) or {}
            raw = p.get("berserk2_net_tp_usd") or p.get("net_tp_usd")
            if raw is not None:
                fixed = float(raw)
        except Exception:
            pass
    if mid == "berserk2":
        env_tp = os.getenv("BERSERK2_NET_TP_USD", "").strip()
        if env_tp:
            try:
                fixed = float(env_tp)
            except ValueError:
                pass
    if fixed is None:
        return stake_based
    fixed_f = round(max(fixed, 0.0), 4)
    lev = max(int(os.getenv("BINANCE_DEFAULT_LEVERAGE", "5") or 5), 1)
    rt = round_trip_fee_usd(s, lev)
    cover = _env_float("ELITE_TP_FEE_COVER_MULT", 1.25)
    min_viable = round(rt * cover + entry_min_net_usd(mid), 4)
    return round(max(fixed_f, stake_based, min_viable), 4)


def net_sl_budget_usd(stake_usd: float, mode_id: str | None = None) -> float:
    _, sl = stake_targets(stake_usd, mode_id)
    return round(max(float(sl), 0.0), 4)


def tp_sl_gross_triggers(
    stake_usd: float,
    leverage: int,
    mode_id: str | None = None,
) -> tuple[float, float, float, float]:
    """
    Çıkış karşılaştırması için brüt unrealized eşikleri.
    Dönüş: (tp_trigger_gross, sl_trigger_gross, net_tp, round_trip_fee)
    """
    mid = mode_id or active_execution_mode()
    net_tp = net_tp_target_usd(stake_usd, mid)
    net_sl = net_sl_budget_usd(stake_usd, mid)
    rt_fee = round_trip_fee_usd(stake_usd, leverage)
    # TP: unrealized brüt ≥ net hedef + tahmini ücret
    tp_gross = round(net_tp + rt_fee, 4)
    # SL: brüt zarar ≤ -(net sl bütçesi + ücret tamponu)
    sl_gross = round(net_sl + rt_fee * 0.5, 4)
    return tp_gross, sl_gross, net_tp, rt_fee


def entry_min_net_usd(mode_id: str | None = None) -> float:
    """Giriş kapısı — TP planı sonrası minimum net cüzdan hedefi."""
    if mode_id:
        try:
            from elite_trader.mode_profiles import get_profile

            p = get_profile(mode_id) or {}
            v = p.get("entry_min_net_usd") or p.get("berserk2_entry_min_net_usd")
            if v is not None:
                return float(v)
        except Exception:
            pass
    return _env_float("ELITE_ENTRY_MIN_NET_USD", 0.35)


def entry_gate(
    stake_usd: float,
    leverage: int,
    *,
    mode_id: str | None = None,
    observed_entry_fee: float | None = None,
    client: Any | None = None,
) -> tuple[bool, str]:
    """
    Plan TP (net cüzdan hedefi) ücretler düşülünce kâr etmiyorsa işlem açma.
    observed_entry_fee: borsa fill sonrası gerçek giriş ücreti (userTrades).
    """
    mid = mode_id or active_execution_mode()
    if mid:
        try:
            from elite_trader.mode_profiles import get_profile

            p = get_profile(mid) or {}
            if p.get("entry_require_net_tp") is False:
                return True, "ok"
        except Exception:
            pass
    if not _env_bool("ELITE_ENTRY_REQUIRE_NET_TP", True):
        return True, "ok"
    if stake_usd <= 0:
        return False, "stake=0"
    s = max(float(stake_usd), 1.0)
    lev = max(int(leverage), 1)
    mid = mode_id or active_execution_mode()
    net_tp = net_tp_target_usd(s, mid)
    if observed_entry_fee and observed_entry_fee > 0:
        rt = round(float(observed_entry_fee) * 2.05, 4)
    else:
        rate = api_taker_rate(None, client=client)
        if rate is None:
            rate = fee_rate_per_side()
        rt = round(s * lev * rate * 2.0, 4)
    min_net = entry_min_net_usd(mid)
    cover = _env_float("ELITE_TP_FEE_COVER_MULT", 1.25)
    expected_wallet_at_tp = net_tp - rt
    if expected_wallet_at_tp < min_net:
        return (
            False,
            f"TP net ~${expected_wallet_at_tp:.2f} < min ${min_net:.2f} "
            f"(plan ${net_tp:.2f} − ücret ${rt:.2f}, {s:.0f}$ {lev}x)",
        )
    if net_tp < rt * cover:
        return (
            False,
            f"plan TP ${net_tp:.2f} < ücret×{cover:.2f} (${rt:.2f})",
        )
    return True, "ok"


def unrealized_net_after_fees(
    unrealized_gross: float,
    stake_usd: float,
    leverage: int,
    *,
    include_exit_fee: bool = True,
) -> float:
    """Açık pozisyon — tahmini cüzdan net (çıkış ücreti düşülmüş)."""
    u = float(unrealized_gross)
    rt = round_trip_fee_usd(stake_usd, leverage)
    if include_exit_fee:
        exit_only = rt / 2.0
        return round(u - exit_only, 4)
    return round(u - rt, 4)


def apply_net_targets_to_position(pos: dict[str, Any], mode_id: str | None = None) -> None:
    """tp_target_usd / sl_target_usd — çıkış döngüsü brüt eşikleri (net+ hedef)."""
    if not use_net_exit_targets(mode_id):
        return
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 5), 1)
    tp_g, sl_g, net_tp, rt_fee = tp_sl_gross_triggers(stake, lev, mode_id)
    pos["tp_target_usd"] = tp_g
    pos["sl_target_usd"] = sl_g
    pos["tp_net_target_usd"] = net_tp
    pos["round_trip_fee_est_usd"] = rt_fee
    pos["exit_min_gross_usd"] = min_gross_for_final_net(stake, lev, mode_id=mode_id)


def hedge_loss_ratio(
    pos: dict[str, Any],
) -> tuple[float, float, float]:
    """
    Hedge danışmanı: net unrealized / net SL bütçesi.
    Dönüş: (ratio, net_unreal, net_sl_budget)
    """
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 5), 1)
    unreal = float(pos.get("unrealized_pnl") or 0)
    net_u = unrealized_net_after_fees(unreal, stake, lev)
    _mid = pos.get("panel_mode") or None
    _, sl_g, _, _ = tp_sl_gross_triggers(stake, lev, _mid)
    if sl_g <= 1e-9:
        return 0.0, net_u, sl_g
    return net_u / -sl_g, net_u, sl_g


def use_net_exit_targets(mode_id: str | None = None) -> bool:
    return _env_bool("ELITE_TP_NET_AFTER_FEE", True)


def paper_tax_rate() -> float:
    """Legacy — kullanılmıyor (ELITE_PAPER_TAX_RATE=0)."""
    return _env_float("ELITE_PAPER_TAX_RATE", 0.0)


_funding_rate_cache: dict[str, tuple[float, float]] = {}
_FUNDING_RATE_TTL_SEC = _env_float("ELITE_FUNDING_RATE_CACHE_SEC", 90.0)


def _fetch_funding_rate(symbol: str, *, client: Any | None = None) -> float | None:
    """premiumIndex lastFundingRate — sembol başına kısa önbellek."""
    import time

    sym = str(symbol or "").upper()
    if sym and not sym.endswith("USDT"):
        sym = f"{sym}USDT"
    if not sym:
        return None
    now = time.time()
    hit = _funding_rate_cache.get(sym)
    if hit and now - hit[1] < _FUNDING_RATE_TTL_SEC:
        return hit[0]
    if client is None:
        try:
            from binance_elite_pro import client as c

            client = c
        except Exception:
            client = None
    if client is None:
        return None
    try:
        pi = client._get("/fapi/v1/premiumIndex", {"symbol": sym})
        rate = float(pi.get("lastFundingRate") or 0)
        _funding_rate_cache[sym] = (rate, now)
        return rate
    except Exception:
        return None


def estimate_next_funding_fee_usd(
    pos: dict[str, Any],
    *,
    client: Any | None = None,
    refresh: bool = False,
) -> float:
    """
    Binance Est. Funding Fee (sonraki funding):
    + = ödeyeceksin (netten düş), - = alacaksın (nete ekle).
    final = brüt uPnL − komisyon − est_funding
    """
    if not refresh:
        cached = pos.get("est_funding_fee_usd")
        if cached is not None:
            try:
                return float(cached)
            except (TypeError, ValueError):
                pass

    side = str(pos.get("side") or "LONG").upper()
    notional = abs(float(pos.get("position_value") or pos.get("notional_usd") or 0))
    if notional <= 0:
        size = float(pos.get("size") or 0)
        mark = float(pos.get("current_price") or pos.get("entry_price") or 0)
        if size > 0 and mark > 0:
            notional = size * mark

    rate = pos.get("funding_rate")
    if rate is None or refresh:
        sym = str(pos.get("symbol") or "")
        fetched = _fetch_funding_rate(sym, client=client)
        if fetched is not None:
            rate = fetched
            pos["funding_rate"] = fetched

    if rate is None or notional <= 0:
        pos["est_funding_fee_usd"] = 0.0
        return 0.0

    rate_f = float(rate)
    est = round(notional * rate_f, 4) if side == "LONG" else round(-notional * rate_f, 4)
    pos["est_funding_fee_usd"] = est
    return est


def entry_fee_api_ready(pos: dict[str, Any] | None) -> bool:
    """Giriş ücreti userTrades'ten doğrulandı mı."""
    if not pos:
        return False
    return (
        str(pos.get("fee_source") or "") == "binance_api"
        and float(pos.get("entry_fee") or 0) > 0
    )


def api_taker_rate(
    pos: dict[str, Any] | None,
    *,
    client: Any | None = None,
) -> float | None:
    """Gerçek taker oranı — giriş fill commission veya Binance commissionRate API."""
    if pos:
        entry_fee = float(pos.get("entry_fee") or 0)
        entry = float(pos.get("entry_price") or 0)
        size = float(pos.get("size") or 0)
        if entry_fee > 0 and entry > 0 and size > 0:
            return entry_fee / (size * entry)
    if client is not None and not getattr(client, "paper", True):
        try:
            from binance_futures_trader.commission_fetcher import get_commission_rates

            return float(get_commission_rates(client)["taker"])
        except Exception:
            return None
    return None


def api_exit_fee_usd(
    pos: dict[str, Any],
    exit_px: float,
    *,
    client: Any | None = None,
) -> float | None:
    """Çıkış komisyonu — giriş fill oranı veya commissionRate API × fill notional."""
    size = float(pos.get("size") or 0)
    if size <= 0 or exit_px <= 0:
        return None
    rate = api_taker_rate(pos, client=client)
    if rate is None:
        return None
    return round(size * float(exit_px) * rate, 8)


def funding_fee_api_usd(
    pos: dict[str, Any],
    *,
    client: Any | None = None,
    refresh: bool = False,
) -> float | None:
    """premiumIndex lastFundingRate × notional — API yoksa None (tahmin yok)."""
    side = str(pos.get("side") or "LONG").upper()
    notional = abs(float(pos.get("position_value") or pos.get("notional_usd") or 0))
    if notional <= 0:
        size = float(pos.get("size") or 0)
        mark = float(pos.get("current_price") or pos.get("entry_price") or 0)
        if size > 0 and mark > 0:
            notional = size * mark
    if notional <= 0:
        return None

    rate = pos.get("funding_rate")
    if rate is None or refresh:
        fetched = _fetch_funding_rate(str(pos.get("symbol") or ""), client=client)
        if fetched is None:
            return None
        rate = fetched
        pos["funding_rate"] = fetched

    rate_f = float(rate)
    funding = round(notional * rate_f, 4) if side == "LONG" else round(-notional * rate_f, 4)
    pos["est_funding_fee_usd"] = funding
    return funding


def close_pnl_at_fill_api(
    pos: dict[str, Any],
    fill_gross: float,
    exit_px: float,
    *,
    client: Any | None = None,
) -> dict[str, Any] | None:
    """bookTicker fill + API giriş/çıkış fee + premiumIndex funding — tahmin yok."""
    if not entry_fee_api_ready(pos):
        return None
    entry_fee = float(pos["entry_fee"])
    exit_fee = api_exit_fee_usd(pos, exit_px, client=client)
    if exit_fee is None:
        return None
    funding = funding_fee_api_usd(pos, client=client, refresh=True)
    if funding is None:
        return None
    total_fees = round(entry_fee + exit_fee, 4)
    net_pnl = round(float(fill_gross) - total_fees, 4)
    final_pnl = round(float(fill_gross) - total_fees - funding, 4)
    return {
        "gross_unreal": round(float(fill_gross), 4),
        "entry_fee": entry_fee,
        "exit_fee": exit_fee,
        "total_fees": total_fees,
        "net_pnl": net_pnl,
        "est_funding_fee": funding,
        "tax": 0.0,
        "final_pnl": final_pnl,
        "fee_source": "binance_api",
    }


def exit_min_net_usd(mode_id: str | None = None, exit_reason: str | None = None) -> float:
    """Kârlı kapanışta minimum cüzdan net (komisyon + Est. Funding sonrası)."""
    mid = str(mode_id or active_execution_mode() or "").lower()
    if mid == "mega":
        try:
            from elite_trader.mega_live import (
                _mega_is_spike_exit,
                _mega_min_close_net_usd,
                _mega_spike_min_close_net_usd,
            )

            if _mega_is_spike_exit(exit_reason):
                return _mega_spike_min_close_net_usd()
            return _mega_min_close_net_usd()
        except Exception:
            pass
    if mode_id:
        try:
            from elite_trader.mode_profiles import get_profile

            p = get_profile(mode_id) or {}
            v = p.get("exit_min_net_usd") or p.get("berserk2_min_final_net_usd")
            if v is not None:
                return float(v)
        except Exception:
            pass
    return _env_float(
        "ELITE_EXIT_MIN_NET_USD",
        _env_float("ELITE_ENTRY_MIN_NET_USD", 0.35),
    )


def exit_net_passes(
    final_pnl: float,
    mode_id: str | None = None,
    *,
    exit_reason: str | None = None,
) -> bool:
    """Kapanış izni — MEGA: net ≥ min; diğer modlar: net > min."""
    mid = str(mode_id or active_execution_mode() or "").lower()
    floor = exit_min_net_usd(mode_id, exit_reason=exit_reason)
    final = float(final_pnl)
    if mid == "mega":
        return final >= floor
    return final > floor


def exit_net_passes_with_est(
    est: dict[str, float],
    mode_id: str | None = None,
) -> tuple[bool, float, float]:
    floor = exit_min_net_usd(mode_id)
    final = float(est.get("final_pnl") or 0)
    return exit_net_passes(final, mode_id), final, floor


def no_loss_close_required(mode_id: str | None = None) -> bool:
    """TP/SPIKE — borsa settlement net- değilse kapanış kaydı yok; emir öncesi de sıkı."""
    if not _env_bool("ELITE_NO_LOSS_CLOSE", True):
        return False
    if mode_id:
        try:
            from elite_trader.mode_profiles import get_profile

            p = get_profile(mode_id) or {}
            if p.get("no_loss_close") is False:
                return False
        except Exception:
            pass
    return True


def require_net_profitable_exit(mode_id: str | None = None) -> bool:
    if mode_id:
        try:
            from elite_trader.mode_profiles import get_profile

            p = get_profile(mode_id) or {}
            if p.get("exit_require_net_positive") is False:
                return False
        except Exception:
            pass
    return _env_bool("ELITE_EXIT_REQUIRE_NET_POSITIVE", True)


PROFIT_TP_EXIT_REASONS = frozenset(
    {
        "TP",
        "TP-PEAK",
        "TP-RECOVER",
        "SPIKE-QUICK",
        "SPIKE-PEAK",
        "SPIKE-FLASH",
        "TP-TIMER",
        "TIER-5",
        "TIER-10",
        "TIER-20",
    }
)

STOP_LOSS_EXIT_REASONS = frozenset(
    {"SL", "SL-TRAIL", "SL-EMERGENCY", "NET-LOSS", "TIME-STOP"}
)

# Operasyonel istisnalar — borsa senkronu / manuel / kötü giriş düzeltmesi / TP timer / kurtarma
_EXIT_OPS_ALLOW = frozenset(
    {
        "SYNC-EXCHANGE",
        "MANUAL",
        "MANUAL CLOSE",
        "MODE-RESET",
        "FEE-GATE",
        "TP-TIMER",
        "RESCUE-REVERSE",
        "RESCUE-HEDGE",
        "HEDGE-NET",
        "EXCHANGE-SYNC",
    }
)


def exit_tp_only(mode_id: str | None = None) -> bool:
    """Yalnızca TP / SPIKE ile kapanış — SL/STALE vb. engellenir."""
    if _env_bool("ELITE_EXIT_TP_ONLY", False):
        return True
    if mode_id:
        try:
            from elite_trader.mode_profiles import get_profile

            p = get_profile(mode_id) or {}
            if p.get("exit_tp_only"):
                return True
        except Exception:
            pass
    return False


def is_profit_tp_exit(reason: str) -> bool:
    r = str(reason or "").strip().upper()
    if r in PROFIT_TP_EXIT_REASONS:
        return True
    return r.startswith("TIER-")


def is_stop_loss_exit(reason: str) -> bool:
    r = str(reason or "").strip().upper()
    return r in STOP_LOSS_EXIT_REASONS or r.startswith("SL")


def exit_ops_allowed(reason: str) -> bool:
    return str(reason or "").strip().upper() in _EXIT_OPS_ALLOW


_exit_gate_stats: dict[str, Any] = {
    "blocked_non_tp": 0,
    "blocked_net_negative": 0,
    "blocked_max_open": 0,
    "blocked_spike_premature": 0,
    "blocked_upnl_mismatch": 0,
    "last_block": None,
    "last_block_ts": 0.0,
}
_exit_block_log_last: dict[str, float] = {}


def report_exit_gate_block(
    *,
    kind: str,
    symbol: str = "",
    reason: str = "",
    detail: str = "",
    throttle_sec: float = 25.0,
) -> None:
    """Engellenen çıkış/giriş — throttle ile log + istatistik."""
    import time as _t

    if kind in _exit_gate_stats:
        _exit_gate_stats[kind] = int(_exit_gate_stats.get(kind) or 0) + 1
    key = f"{kind}:{symbol}:{reason}"
    now = _t.time()
    _exit_gate_stats["last_block"] = {
        "kind": kind,
        "symbol": symbol,
        "reason": reason,
        "detail": detail[:200],
    }
    _exit_gate_stats["last_block_ts"] = now
    if now - _exit_block_log_last.get(key, 0) < throttle_sec:
        return
    _exit_block_log_last[key] = now
    sym = f" {symbol}" if symbol else ""
    extra = f" — {detail}" if detail else ""
    print(f"  🚫 ENGEL{sym}: {kind} ({reason}){extra}")


def exit_gate_stats() -> dict[str, Any]:
    return dict(_exit_gate_stats)


def settled_exit_record_reason(
    exit_reason: str,
    exchange_settled: dict[str, Any] | None,
    *,
    mode_id: str | None = None,
) -> str:
    """
    Settlement sonrası çıkış etiketi — yalnızca gerçek net+ kapanışlar TP/SPIKE kalır.
    TP tetiklendi ama fill sonrası zararsa NET-LOSS / FEE-KILL.
    """
    raw = str(exit_reason or "Manual").strip()
    r = raw.upper()
    if not exchange_settled:
        return raw or "Manual"

    wallet = float(
        exchange_settled.get("wallet_pnl")
        or exchange_settled.get("net_pnl")
        or 0
    )
    gross = float(
        exchange_settled.get("pnl_gross_usd")
        or exchange_settled.get("pnl_usd")
        or 0
    )
    mid = mode_id or active_execution_mode()
    floor = exit_min_net_usd(mid) + exit_slippage_buffer_usd(mid)

    if r == "SYNC-EXCHANGE":
        if wallet >= floor and wallet > 0:
            return "TP"
        return "EXCHANGE-SYNC"

    if exit_ops_allowed(exit_reason):
        return raw or "Manual"

    if not is_profit_tp_exit(exit_reason):
        return raw or "Manual"

    if wallet >= floor and wallet > 0:
        return raw

    if gross > 0 and wallet < 0:
        return "FEE-KILL"
    if wallet < 0:
        return "NET-LOSS"
    return "BELOW-FLOOR"


def live_close_record_ok(
    *,
    exit_reason: str,
    exchange_settled: dict[str, Any] | None,
    mode_id: str | None = None,
    on_exchange: bool = False,
) -> tuple[bool, str, str]:
    """
    Kapalı işlem tablosu — borsa settlement varsa kaydet (Binance gerçeği, NET-LOSS dahil).
    Min net eşiği yalnızca motor emri (allow_position_close) için; MEGA_RECORD_NET_LOSS=0 ile filtre.
    """
    mid = mode_id or active_execution_mode()

    if on_exchange:
        if not exchange_settled:
            return False, "", "borsa settlement yok (ELITE_EXCHANGE_TRUTH)"
        from elite_trader.exchange_settlement import settlement_has_api_close_fills

        if not settlement_has_api_close_fills(exchange_settled):
            return False, "", "borsa kapanış fill yok (userTrades)"
        record_reason = settled_exit_record_reason(
            exit_reason, exchange_settled, mode_id=mid
        )
        if str(mid).lower() == "mega" and not _env_bool("MEGA_RECORD_NET_LOSS", True):
            wallet = float(
                exchange_settled.get("wallet_pnl")
                or exchange_settled.get("net_pnl")
                or 0
            )
            floor = exit_min_net_usd(mid) + exit_slippage_buffer_usd(mid)
            if wallet < floor or record_reason in (
                "NET-LOSS",
                "FEE-KILL",
                "BELOW-FLOOR",
            ):
                return False, "", f"kayıt yok — {record_reason} net=${wallet:.2f}"
        return True, record_reason, ""

    if exit_ops_allowed(exit_reason):
        return True, str(exit_reason or "Manual"), ""

    return True, str(exit_reason or "Manual"), ""


def live_close_learning_ok(
    *,
    wallet_pnl: float,
    mode_id: str | None = None,
) -> bool:
    """Öğrenme/ingest — yalnızca net+ kapanışlar."""
    mid = mode_id or active_execution_mode()
    if not exit_tp_only(mid):
        return True
    floor = exit_min_net_usd(mid) + exit_slippage_buffer_usd(mid)
    return float(wallet_pnl) >= floor and float(wallet_pnl) > 0


def spike_min_gross_usd(
    stake_usd: float,
    leverage: int,
    *,
    mode_id: str | None = None,
) -> float:
    """SPIKE/TP emri — fee + slippage sonrası net+ için minimum brüt uPnL."""
    mid = mode_id or active_execution_mode()
    lev = max(int(leverage), 1)
    stake = max(float(stake_usd), 1.0)
    base = min_gross_for_final_net(stake, lev, mode_id=mid)
    slip_usd = exit_slippage_buffer_usd(mid)
    extra = _env_float("ELITE_SPIKE_CLOSE_SLIPPAGE_USD", 0.28)
    try:
        from elite_trader.mode_profiles import get_profile

        p = get_profile(mid) or {}
        slip_pct = float(p.get("exit_slippage_buffer_pct") or 0.15)
    except Exception:
        slip_pct = 0.15
    floor_gross = base * (1.0 + slip_pct) + slip_usd + extra
    try:
        from elite_trader.mode_profiles import get_profile

        p = get_profile(mid) or {}
        sq = p.get("berserk2_spike_quick_gross_usd") or p.get("spike_quick_gross_usd")
        if sq is not None and float(sq) > 0:
            floor_gross = max(floor_gross, float(sq))
    except Exception:
        pass
    env_sq = os.getenv("BERSERK2_SPIKE_QUICK_GROSS_USD", "").strip()
    if env_sq:
        try:
            floor_gross = max(floor_gross, float(env_sq))
        except ValueError:
            pass
    return round(floor_gross, 4)


def fast_scalp_min_gross_usd(
    stake_usd: float,
    leverage: int,
    *,
    mode_id: str | None = None,
) -> float:
    """SPIKE-FLASH — net+ bölgeye girince anında kapat (bekleme yok)."""
    mid = mode_id or active_execution_mode()
    lev = max(int(leverage), 1)
    stake = max(float(stake_usd), 1.0)
    base = min_gross_for_final_net(stake, lev, mode_id=mid)
    mult = _env_float("ELITE_FAST_SCALP_GROSS_MULT", 1.05)
    slip = exit_slippage_buffer_usd(mid) * 0.5
    floor = base * mult + slip
    env_v = os.getenv("BERSERK2_SPIKE_FLASH_GROSS_USD", "").strip()
    if env_v:
        try:
            floor = max(floor, float(env_v))
        except ValueError:
            pass
    return round(floor, 4)


def spike_peak_min_gross_usd(
    stake_usd: float,
    leverage: int,
    *,
    mode_id: str | None = None,
) -> float:
    """SPIKE-PEAK — tepe geri çekilmesi; tam SPIKE-QUICK eşiğinden düşük, net+ tamponlu."""
    mid = mode_id or active_execution_mode()
    lev = max(int(leverage), 1)
    stake = max(float(stake_usd), 1.0)
    base = min_gross_for_final_net(stake, lev, mode_id=mid)
    slip = exit_slippage_buffer_usd(mid) + _env_float("ELITE_SPIKE_PEAK_SLIPPAGE_USD", 0.12)
    return round(base * 1.04 + slip, 4)


def profit_exit_send_ok(
    pos: dict[str, Any],
    exit_reason: str,
    *,
    mode_id: str | None = None,
    client: Any | None = None,
) -> tuple[bool, str]:
    """Canlı emir göndermeden önce — book fill net+ (SPIKE/TP)."""
    r = str(exit_reason or "").upper()
    if r.startswith("RESCUE-"):
        return True, ""
    if not is_profit_tp_exit(exit_reason):
        return True, ""
    mid = mode_id or active_execution_mode()
    if str(mid).lower() == "mega" and pos.get("fill_verify_ok"):
        return True, str(pos.get("fill_verify_detail") or "")
    if (
        str(mid).lower() == "mega"
        and pos.get("tp_fast_close")
        and pos.get("on_exchange")
    ):
        try:
            from elite_trader.mega_live import _mega_scalp_hub_trusted

            if _mega_scalp_hub_trusted():
                gross = float(pos.get("unrealized_pnl") or pos.get("fill_gross_unreal") or 0)
                if gross > 0 and exit_net_passes(
                    float(
                        pos.get("fill_net_est")
                        or estimate_close_from_position(pos, client=client).get("final_pnl")
                        or 0
                    ),
                    mid,
                ):
                    pos["fill_gross_unreal"] = gross
                    return True, ""
        except Exception:
            pass
    gross = float(pos.get("fill_gross_unreal") or pos.get("unrealized_pnl") or 0)
    if pos.get("on_exchange"):
        try:
            from elite_trader.exchange_fill_truth import fill_net_close_ready

            if client is None:
                try:
                    from binance_elite_pro import client as c

                    client = c
                except Exception:
                    client = None
            if client is not None and not getattr(client, "paper", True):
                ok, final, floor, est = fill_net_close_ready(
                    pos,
                    client=client,
                    mode_id=mid,
                    exit_reason=exit_reason,
                    fast=str(mid).lower() == "mega",
                )
                gross = float(est.get("fill_gross") or gross)
                pos["fill_gross_unreal"] = gross
                pos["fill_net_est"] = final
                if not ok:
                    op = "<" if str(mid).lower() == "mega" else "≤"
                    return (
                        False,
                        f"fill net ${final:.4f} {op} min ${floor:.2f} "
                        f"(fill brüt ${gross:.4f} @ ${est.get('fill_price')})",
                    )
                if not use_net_exit_targets(mid):
                    stake = float(pos.get("stake_usd") or 1)
                    lev = max(int(pos.get("leverage") or 5), 1)
                    r = str(exit_reason or "").upper()
                    if r == "SPIKE-FLASH":
                        min_g = fast_scalp_min_gross_usd(stake, lev, mode_id=mid)
                    elif r == "SPIKE-PEAK":
                        min_g = spike_peak_min_gross_usd(stake, lev, mode_id=mid)
                    else:
                        min_g = spike_min_gross_usd(stake, lev, mode_id=mid)
                    if gross < min_g:
                        return (
                            False,
                            f"fill brüt ${gross:.4f} < min ${min_g:.4f} (fee+slippage tamponu)",
                        )
                return True, ""
        except Exception:
            pass
        return False, "fill/API fee doğrulanamadı — kapanış yok"
    if gross <= 0:
        return False, f"brüt ${gross:.4f} ≤ 0"
    est = estimate_close_from_position(pos, client=client)
    floor = exit_min_net_usd(mid)
    final = float(est["final_pnl"])
    if not exit_net_passes(final, mid):
        op = "<" if str(mid).lower() == "mega" else "≤"
        return (
            False,
            f"tahmini net ${final:.4f} {op} min ${floor:.2f} "
            f"(uPnL−fee−funding, brüt=${gross:.4f})",
        )
    if not use_net_exit_targets(mid):
        stake = float(pos.get("stake_usd") or 1)
        lev = max(int(pos.get("leverage") or 5), 1)
        r = str(exit_reason or "").upper()
        if r == "SPIKE-FLASH":
            min_g = fast_scalp_min_gross_usd(stake, lev, mode_id=mid)
        elif r == "SPIKE-PEAK":
            min_g = spike_peak_min_gross_usd(stake, lev, mode_id=mid)
        else:
            min_g = spike_min_gross_usd(stake, lev, mode_id=mid)
        if gross < min_g:
            return (
                False,
                f"brüt ${gross:.4f} < min ${min_g:.4f} (fee+slippage tamponu)",
            )
    return True, ""


def estimate_close_pnl(
    gross_unreal: float,
    stake_usd: float,
    leverage: int,
    *,
    entry_fee: float | None = None,
    exit_fee: float | None = None,
    est_funding_fee: float | None = None,
    pos: dict[str, Any] | None = None,
    client: Any | None = None,
) -> dict[str, float]:
    """Tahmini kapanış: brüt uPnL − komisyon − Est. Funding Fee → final."""
    gross = float(gross_unreal)
    stake = max(float(stake_usd), 0.0)
    lev = max(int(leverage), 1)
    rt = round_trip_fee_usd(stake, lev)
    ef = float(entry_fee) if entry_fee is not None else rt / 2.0
    xf = float(exit_fee) if exit_fee is not None else rt / 2.0
    total_fees = round(ef + xf, 4)
    funding = est_funding_fee
    if funding is None and pos is not None:
        funding = estimate_next_funding_fee_usd(pos, client=client)
    funding = round(float(funding or 0), 4)
    net_pnl = round(gross - total_fees, 4)
    final_pnl = round(gross - total_fees - funding, 4)
    return {
        "gross_unreal": gross,
        "total_fees": total_fees,
        "net_pnl": net_pnl,
        "est_funding_fee": funding,
        "tax": 0.0,
        "final_pnl": final_pnl,
    }


def _observed_exit_fee(
    pos: dict[str, Any],
    *,
    client: Any | None = None,
) -> float | None:
    """Çıkış komisyonu — giriş fill oranı veya commissionRate API."""
    exit_px = float(pos.get("current_price") or pos.get("entry_price") or 0)
    if not entry_fee_api_ready(pos):
        return None
    return api_exit_fee_usd(pos, exit_px, client=client)


def estimate_close_from_position(
    pos: dict[str, Any],
    *,
    client: Any | None = None,
) -> dict[str, float]:
    gross = float(pos.get("unrealized_pnl") or 0)
    stake = float(pos.get("stake_usd") or 1)
    lev = max(int(pos.get("leverage") or 5), 1)
    if pos.get("on_exchange") and entry_fee_api_ready(pos):
        exit_px = float(pos.get("current_price") or pos.get("entry_price") or 0)
        api = close_pnl_at_fill_api(pos, gross, exit_px, client=client)
        if api is not None:
            return api
        return {
            "gross_unreal": gross,
            "total_fees": 0.0,
            "net_pnl": gross,
            "est_funding_fee": 0.0,
            "tax": 0.0,
            "final_pnl": -1e9,
            "api_incomplete": True,
        }
    entry_fee = float(pos.get("entry_fee") or 0)
    exit_fee = _observed_exit_fee(pos, client=client)
    return estimate_close_pnl(
        gross,
        stake,
        lev,
        entry_fee=entry_fee or None,
        exit_fee=exit_fee,
        pos=pos,
        client=client,
    )


def net_scalp_close_ready(
    *,
    unrealized_usd: float,
    stake_usd: float,
    leverage: int,
    entry_fee: float = 0.0,
    mode_id: str | None = None,
) -> tuple[bool, float, float]:
    """uPnL − komisyon − Est. Funding > exit_min ise kapat."""
    mid = mode_id or active_execution_mode()
    pos = {
        "unrealized_pnl": unrealized_usd,
        "stake_usd": stake_usd,
        "leverage": leverage,
        "entry_fee": entry_fee,
    }
    est = estimate_close_from_position(pos)
    floor = exit_min_net_usd(mid)
    final = float(est["final_pnl"])
    return exit_net_passes(final, mid), final, floor


def min_gross_for_final_net(
    stake_usd: float,
    leverage: int,
    *,
    min_final_usd: float | None = None,
    mode_id: str | None = None,
    pos: dict[str, Any] | None = None,
    client: Any | None = None,
) -> float:
    """final_pnl > min_final için gereken minimum brüt unrealized."""
    target = min_final_usd if min_final_usd is not None else exit_min_net_usd(mode_id)
    rt = round_trip_fee_usd(stake_usd, leverage)
    funding = 0.0
    if pos:
        funding = estimate_next_funding_fee_usd(pos, client=client)
    return round(rt + target + funding, 4)


def is_loss_management_exit(reason: str, gross_unreal: float) -> bool:
    """Zararda planlı kapanış yok — tüm çıkışlar net+ filtresinden geçer."""
    return False


def exit_slippage_buffer_usd(mode_id: str | None = None) -> float:
    """Market emir kayması — brüt eşiğe güvenlik payı."""
    if mode_id:
        try:
            from elite_trader.mode_profiles import get_profile

            p = get_profile(mode_id) or {}
            v = p.get("exit_slippage_buffer_usd")
            if v is not None:
                return max(0.0, float(v))
        except Exception:
            pass
    return max(0.0, _env_float("ELITE_EXIT_SLIPPAGE_BUFFER_USD", 0.06))


def allow_position_close(
    *,
    gross_unreal: float,
    stake_usd: float,
    leverage: int,
    exit_reason: str,
    mode_id: str | None = None,
    entry_fee: float | None = None,
    exit_fee: float | None = None,
    pos: dict[str, Any] | None = None,
    client: Any | None = None,
) -> bool:
    """Kapanış emri — fill uPnL − komisyon − Est. Funding > min net (SYNC/reconcile hariç)."""
    r = str(exit_reason or "").upper()
    mid = str(mode_id or active_execution_mode() or "").lower()
    mega_strict = mid == "mega"
    if r in ("SYNC-EXCHANGE", "EXCHANGE-SYNC"):
        return True
    if r.startswith("RESCUE-"):
        return True
    if mega_strict:
        try:
            from elite_trader.mega_live import (
                mega_sl_exit_disabled,
                mega_underwater_cut_enabled,
            )

            if r == "TIME-STOP" and mega_underwater_cut_enabled():
                return True
            if mega_sl_exit_disabled() and (
                is_stop_loss_exit(exit_reason) or r.startswith("SL")
            ):
                return False
            try:
                from elite_trader.mega_live import mega_blocks_sl_close

                if mega_blocks_sl_close(exit_reason):
                    return False
            except Exception:
                pass
        except Exception:
            if is_stop_loss_exit(exit_reason):
                return False
    elif r in ("MANUAL", "MANUAL CLOSE", "MODE-RESET"):
        return True
    if r == "FEE-GATE":
        return no_loss_close_required(mode_id) is False
    if not require_net_profitable_exit(mode_id):
        return True
    if pos and pos.get("on_exchange") and is_stop_loss_exit(exit_reason):
        if mega_strict:
            try:
                from elite_trader.mega_live import (
                    mega_sl_exit_disabled,
                    mega_underwater_cut_enabled,
                )

                if r == "TIME-STOP" and mega_underwater_cut_enabled():
                    return True
                if not mega_sl_exit_disabled():
                    return True
            except Exception:
                return False
            return False
        return True
    if pos and pos.get("on_exchange") and is_profit_tp_exit(exit_reason):
        if client and not getattr(client, "paper", True):
            try:
                from elite_trader.exchange_trade_truth import enrich_open_entry_fee_api

                enrich_open_entry_fee_api(pos, client, allow_fetch=True)
            except Exception:
                pass
        tp_g, _, _, _ = tp_sl_gross_triggers(stake_usd, leverage, mode_id)
        if pos.get("tp_fast_close") and gross_unreal > 0:
            try:
                from elite_trader.mega_live import mega_fast_profit_close_allowed

                if mega_fast_profit_close_allowed(
                    pos,
                    exit_reason,
                    gross_unreal,
                    stake_usd,
                    leverage,
                    mode_id=mode_id,
                    client=client,
                ):
                    return True
            except Exception:
                pass
            min_g = min_gross_for_final_net(
                stake_usd, leverage, mode_id=mode_id, pos=pos, client=client
            )
            if gross_unreal >= min_g:
                return True
        try:
            from elite_trader.exchange_fill_truth import fill_net_close_ready

            ok, _, _, est = fill_net_close_ready(
                pos, client=client, mode_id=mode_id
            )
            # Book fill iyimser değilse mark uPnL ≥ TP brüt eşiğinde tahmine düş
            if est.get("source") == "book_fill_api" and ok:
                return True
        except Exception:
            pass
        if gross_unreal >= tp_g:
            est = estimate_close_pnl(
                gross_unreal,
                stake_usd,
                leverage,
                entry_fee=entry_fee,
                exit_fee=exit_fee,
                pos=pos,
                client=client,
            )
            return exit_net_passes(float(est["final_pnl"]), mode_id)
        return False
    if pos and pos.get("on_exchange"):
        return False
    est = estimate_close_pnl(
        gross_unreal,
        stake_usd,
        leverage,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        pos=pos,
        client=client,
    )
    return exit_net_passes(float(est["final_pnl"]), mode_id)


def net_profit_exit_ok(
    gross_unreal: float,
    stake_usd: float,
    leverage: int,
    *,
    entry_fee: float | None = None,
    exit_fee: float | None = None,
    mode_id: str | None = None,
    pos: dict[str, Any] | None = None,
    client: Any | None = None,
) -> bool:
    if not require_net_profitable_exit(mode_id):
        return True
    if pos and pos.get("on_exchange"):
        try:
            from elite_trader.exchange_fill_truth import fill_net_close_ready

            ok, _, _, est = fill_net_close_ready(
                pos, client=client, mode_id=mode_id
            )
            src = est.get("source")
            if src == "book_fill_api":
                return ok
            if src not in ("mark_fallback", "bookTicker_missing", "api_fee_missing"):
                return ok
        except Exception:
            pass
    est = estimate_close_pnl(
        gross_unreal,
        stake_usd,
        leverage,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        pos=pos,
        client=client,
    )
    return exit_net_passes(float(est["final_pnl"]), mode_id)


def filter_profitable_exit_reason(
    reason: str | None,
    *,
    gross_unreal: float,
    stake_usd: float,
    leverage: int,
    entry_fee: float | None = None,
    exit_fee: float | None = None,
    mode_id: str | None = None,
    pos: dict[str, Any] | None = None,
    client: Any | None = None,
) -> str | None:
    """Kâr amaçlı çıkış — fill uPnL − fee − Est. Funding > min net değilse iptal."""
    if not reason:
        return None
    mid = str(mode_id or active_execution_mode() or "").lower()
    if mid == "mega" and is_stop_loss_exit(reason):
        try:
            from elite_trader.mega_live import (
                mega_sl_exit_disabled,
                mega_underwater_cut_enabled,
            )

            r = str(reason or "").strip().upper()
            if r == "TIME-STOP" and mega_underwater_cut_enabled():
                return reason
            if not mega_sl_exit_disabled():
                return reason
        except Exception:
            pass
        return None
    if not net_profit_exit_ok(
        gross_unreal,
        stake_usd,
        leverage,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        mode_id=mode_id,
        pos=pos,
        client=client,
    ):
        return None
    if pos and pos.get("on_exchange"):
        return reason
    est = estimate_close_pnl(
        gross_unreal,
        stake_usd,
        leverage,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        pos=pos,
        client=client,
    )
    if not exit_net_passes(float(est["final_pnl"]), mode_id):
        return None
    return reason
