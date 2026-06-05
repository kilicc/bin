"""Panel strateji — canlı .env dokunulmaz; 3 paralel evren (aynı piyasa + geçmiş)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.mode_profiles import ALL_MODE_IDS as _ALL_PROFILE_IDS
from elite_trader.mode_profiles import MODE_IDS as _MODE_IDS
from elite_trader.mode_profiles import all_mode_profiles, parallel_profiles
from elite_trader.mode_registry import (
    DEFAULT_ACTIVE_FUTURES_MODE,
    MODE_META,
    berserk2_paper_only,
    default_execution_mode_id,
    enabled_mode_ids,
    is_berserk_family,
    resolve_mode_id as _registry_resolve,
)

__all__ = (
    "DEFAULT_ACTIVE_FUTURES_MODE",
    "active_futures_mode",
    "active_execution_mode",
    "active_view_mode",
    "live_mode_id",
    "live_only_execution",
    "mode_catalog",
    "mode_order",
    "resolve_mode_id",
)

_ROOT = Path(__file__).resolve().parent.parent
_STATE = _ROOT / "data" / "panel_strategy_state.json"
_PARALLEL_IDS = _MODE_IDS


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def live_only_execution() -> bool:
    """Yalnızca Binance canlı emir — paper/gölge/paralel kitap kapalı."""
    if _env_bool("ELITE_PAPER_PARALLEL", False):
        return False
    if not _env_bool("ELITE_LIVE_ONLY", False):
        return False
    return os.getenv("BINANCE_LIVE_ORDERS", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def mode_catalog() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for mid, prof in all_mode_profiles().items():
        meta = MODE_META.get(mid) or {}
        out[mid] = {
            "shadow_only": bool(meta.get("default_paper", mid != "evrim")),
            "is_live": False,
            "parallel": True,
            "display_name": meta.get("display_name", mid),
            **prof,
        }
    return out


def parallel_mode_ids() -> tuple[str, ...]:
    return _PARALLEL_IDS


def mode_order() -> list[str]:
    """Panel sırası — ELITE_ENABLED_MODES ile daraltılabilir."""
    enabled = enabled_mode_ids()
    if len(enabled) < len(_MODE_IDS):
        return [m for m in _MODE_IDS if m in enabled]
    return list(_MODE_IDS)


def _default_state() -> dict[str, Any]:
    ex = default_execution_mode_id()
    return {
        "execution_mode": ex,
        "active_futures_mode": ex,
        "view_mode": ex,
        "current_mode": ex,
    }


def _load_state() -> dict[str, Any]:
    if not _STATE.is_file():
        return _default_state()
    try:
        st = json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()
    ex = resolve_mode_id(
        str(
            st.get("active_futures_mode")
            or st.get("execution_mode")
            or st.get("current_mode")
            or default_execution_mode_id()
        )
    )
    vw = resolve_mode_id(str(st.get("view_mode") or ex))
    allowed = set(enabled_mode_ids())
    if len(allowed) < len(_MODE_IDS):
        if ex not in allowed:
            ex = next(iter(allowed))
        if vw not in allowed:
            vw = ex
    st["execution_mode"] = ex
    st["active_futures_mode"] = ex
    st["view_mode"] = vw
    st["current_mode"] = ex
    return st


def _save_state(data: dict[str, Any]) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_mode_id(mode_id: str) -> str:
    mid = _registry_resolve(mode_id)
    if mid in mode_catalog():
        return mid
    return DEFAULT_ACTIVE_FUTURES_MODE


def active_futures_mode() -> str:
    """Canlı Binance emir motoru."""
    return active_execution_mode()


def active_execution_mode() -> str:
    """Binance çıkış emirlerinin modu (.env dosyası değişmez)."""
    return resolve_mode_id(
        str(_load_state().get("execution_mode") or DEFAULT_ACTIVE_FUTURES_MODE)
    )


def active_view_mode() -> str:
    """Panel görünümü — veri silinmez, yalnızca ekran o moda döner."""
    enabled = enabled_mode_ids()
    if len(enabled) == 1:
        return enabled[0]
    st = _load_state()
    vw = resolve_mode_id(str(st.get("view_mode") or active_execution_mode()))
    if enabled and vw not in set(enabled):
        vw = enabled[0]
    return vw


def current_mode_id() -> str:
    return active_execution_mode()


def live_mode_id() -> str:
    """Geriye uyumluluk — Ana Hat kaldırıldı; sentinel referans."""
    return "sentinel"


def execution_profile() -> dict[str, Any]:
    """Seçili Binance motorunun birleşik profili."""
    mid = active_execution_mode()
    return dict(mode_catalog().get(mid) or mode_catalog()[DEFAULT_ACTIVE_FUTURES_MODE])


def execution_max_open() -> int:
    m = execution_profile()
    cap: int | None = None
    if m.get("max_open") is not None:
        cap = int(m["max_open"])
    elif m.get("entry_max_open") is not None:
        cap = int(m["entry_max_open"])
    else:
        from elite_trader.scanner import max_open_positions

        cap = max_open_positions()
    try:
        env_cap = int(os.getenv("ELITE_MAX_OPEN", "0"))
        if env_cap > 0:
            cap = min(cap, env_cap)
    except ValueError:
        pass
    return max(1, cap)


def execution_min_stake() -> float:
    m = execution_profile()
    if m.get("min_stake_usd") is not None:
        return float(m["min_stake_usd"])
    try:
        return float(os.getenv("ELITE_MIN_STAKE_USD", "200"))
    except ValueError:
        return 200.0


def execution_active_capital_pct() -> float:
    m = execution_profile()
    if m.get("active_capital_pct") is not None:
        return float(m["active_capital_pct"])
    return active_capital_pct()


def signal_passes_mode(mode_id: str, signal: dict[str, Any]) -> tuple[bool, str]:
    """Belirli mod profiline göre giriş (canlı veya paper yolu)."""
    mode_id = resolve_mode_id(mode_id)
    m = mode_catalog().get(mode_id) or mode_catalog()[DEFAULT_ACTIVE_FUTURES_MODE]
    ex = mode_id
    ch = float(signal.get("change") or 0)
    strength = str(signal.get("strength") or "Medium")

    if m.get("entry_block_weak") and strength == "Weak":
        return False, "weak"
    min_strength = str(m.get("entry_min_strength") or "Medium")
    rank = {"Weak": 1, "Medium": 2, "Strong": 3}
    if rank.get(strength, 0) < rank.get(min_strength, 2):
        return False, "strength"

    from binance_elite_pro import (
        MIN_EDGE,
        MIN_FORMULA_SCORE,
        _edge_from_signal,
        _formula_score_from_signal,
    )

    edge = _edge_from_signal(ch)
    fs = _formula_score_from_signal(ch)

    hybrid_evrim = False
    if ex == "evrim":
        try:
            from elite_trader.evrim_training import is_live_training_enabled

            hybrid_evrim = is_live_training_enabled(m)
        except Exception:
            hybrid_evrim = bool(m.get("evrim_live_training", True))

    if not hybrid_evrim:
        if m.get("min_edge") is not None:
            if edge < float(m["min_edge"]):
                return False, "edge"
        elif edge < MIN_EDGE:
            return False, "edge"
        if m.get("min_formula_score") is not None:
            if fs < float(m["min_formula_score"]):
                return False, "formula"
        elif fs < MIN_FORMULA_SCORE:
            return False, "formula"

    if ex == "evrim":
        from elite_trader.evrim_opportunity import evrim_entry_gate

        path = "live" if ex == active_execution_mode() else "paper"
        ok, reason = evrim_entry_gate(ex, signal, m, execution_path=path)
        if not ok:
            return False, reason or "evrim_filter"

    return True, ""


def signal_passes_execution_mode(signal: dict[str, Any]) -> tuple[bool, str]:
    """Seçili Binance motoru için giriş."""
    return signal_passes_mode(active_execution_mode(), signal)


def entry_risk_for_execution(
    symbol: str,
    side: str,
    strength: str,
    change_pct: float,
    formula_score: float,
) -> tuple[bool, str, str]:
    """SL-EMERGENCY — seçili motor profil parametreleri."""
    from elite_trader.sl_emergency_guard import entry_risk_check

    prof = execution_profile()
    veto_n = prof.get("sl_em_veto_count")
    cool = prof.get("sl_em_cooldown_min")
    return entry_risk_check(
        symbol,
        side,
        strength,
        change_pct,
        formula_score,
        veto_count=int(veto_n) if veto_n is not None else None,
        cooldown_min=int(cool) if cool is not None else None,
        skip_cautious=bool(prof.get("entry_skip_cautious")),
        cautious_min_strength=str(prof.get("entry_min_strength") or "Medium"),
    )


def is_live_binance_motor(mode_id: str | None = None) -> bool:
    """Bu mod şu an canlı emir motoru mu (paper değil)."""
    import os

    mid = resolve_mode_id(mode_id or active_execution_mode())
    if mid == "berserk2" and berserk2_paper_only():
        return False
    if mid == "mega":
        try:
            from elite_trader.mega_live import mega_live_enabled

            return mega_live_enabled()
        except Exception:
            return False
    if os.getenv("BINANCE_LIVE_ORDERS", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    return mid == active_execution_mode()


def paper_parallel_mode_ids() -> list[str]:
    """Canlı Binance motoru hariç paper — yalnızca etkin modlar."""
    return [m for m in mode_order() if not is_live_binance_motor(m)]


def stake_targets(stake_usd: float, mode_id: str | None = None) -> tuple[float, float]:
    mid = resolve_mode_id(mode_id or active_execution_mode())
    m = mode_catalog().get(mid) or mode_catalog()[DEFAULT_ACTIVE_FUTURES_MODE]
    s = max(float(stake_usd), 1.0)
    return (
        s * float(m["tp_stake_pct"]) * float(m["tp_trigger_frac"]),
        s * float(m["sl_stake_pct"]),
    )


def _stale_release_reason_mode(
    *,
    mode_id: str,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    stake_usd: float,
    min_unreal_seen: float,
) -> str:
    m = mode_catalog().get(mode_id) or {}
    if not m.get("stale_enabled"):
        return ""
    if unrealized_usd >= tp_target_usd * 0.995:
        return ""
    from elite_trader.fee_economics import round_trip_fee_usd

    lev = 5
    fee = round_trip_fee_usd(stake_usd, lev, fee_mult=1.15) / 2.0
    min_tp = max(0.30, stake_usd * 0.0015, fee)
    if unrealized_usd < min_tp:
        return ""
    age = position_age_seconds({"opened_at_iso": opened_at, "entry_time": None})
    if age < float(m.get("stale_min_age_min", 2)) * 60.0:
        return ""
    loss_thr = -max(0.60, stake_usd * 0.002)
    if min_unreal_seen <= loss_thr and unrealized_usd >= min_tp and age >= 30:
        return "STALE-RECOVER"
    return "STALE-RELEASE"


def _berserk_tp_grace_sec(mode_id: str) -> float:
    if not is_berserk_family(mode_id):
        return 0.0
    from elite_trader.berserk_exit import berserk_grace_sec

    m = mode_catalog().get(resolve_mode_id(mode_id)) or {}
    return berserk_grace_sec(m)


def _sl_blocked_by_grace(
    *,
    mode_id: str,
    opened_at: str | None,
    unrealized_usd: float,
    sl_target_usd: float,
) -> bool:
    """Berserk micro-scalp: spike/TP penceresi dolmadan planlı SL yok."""
    if unrealized_usd > -float(sl_target_usd):
        return False
    grace = _berserk_tp_grace_sec(mode_id)
    if grace <= 0:
        m = mode_catalog().get(mode_id) or {}
        grace = float(m.get("min_hold_before_sl_sec") or 0)
    if grace <= 0:
        return False
    age = position_age_seconds({"opened_at_iso": opened_at})
    return age < grace


def _spike_reason_mode(
    *,
    mode_id: str,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    stake_usd: float,
    max_unreal_seen: float,
    leverage: int = 5,
    entry_fee: float | None = None,
) -> str:
    from elite_trader.fee_economics import (
        net_scalp_close_ready,
        use_net_exit_targets,
    )

    m = mode_catalog().get(mode_id) or {}
    if not m.get("spike_enabled") or tp_target_usd <= 0:
        return ""
    age = position_age_seconds({"opened_at_iso": opened_at})
    env_min = float(os.getenv("ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC", "0.15") or 0.15)
    min_age = min(
        float(m.get("spike_min_age_sec", 40)),
        float(m.get("berserk2_spike_min_age_sec") or env_min),
        env_min,
    )
    grace_sec = _berserk_tp_grace_sec(mode_id)
    grace_spike_min = float(m.get("berserk_spike_grace_min_age_sec") or 0.12)
    in_grace = is_berserk_family(mode_id) and grace_sec > 0 and age < grace_sec
    if in_grace:
        min_age = min(min_age, grace_spike_min)
    if age < min_age:
        return ""

    lev = max(int(leverage), 1)
    ef = float(entry_fee or 0)

    # Net-aware anında scalp — brüt eşik beklemek yerine fee sonrası ≥ min net
    use_net_spike = (
        is_berserk_family(mode_id) and _env_bool("ELITE_SPIKE_QUICK_TP_ENABLED", True)
    ) or (mode_id == "mega" and _env_bool("MEGA_SPIKE_QUICK", True))
    if use_net_spike:
        ready, final_net, floor = net_scalp_close_ready(
            unrealized_usd=unrealized_usd,
            stake_usd=stake_usd,
            leverage=lev,
            entry_fee=ef,
            mode_id=mode_id,
        )
        if ready:
            return "SPIKE-FLASH"

    from elite_trader.fee_economics import (
        fast_scalp_min_gross_usd,
        round_trip_fee_usd,
        spike_min_gross_usd,
    )

    skip_gross_flash = mode_id == "mega" and not (
        _env_bool("MEGA_SPIKE_GROSS_ONLY", False) or _env_bool("MEGA_MARK_SPIKE", True)
    )
    flash_floor = fast_scalp_min_gross_usd(stake_usd, lev, mode_id=mode_id)
    if not skip_gross_flash and float(unrealized_usd) >= flash_floor:
        return "SPIKE-FLASH"
    spike_floor = spike_min_gross_usd(stake_usd, lev, mode_id=mode_id)
    if float(unrealized_usd) < spike_floor:
        return ""
    if unrealized_usd >= tp_target_usd * 0.92:
        return "SPIKE-QUICK" if float(unrealized_usd) >= spike_floor else ""
    fee = round_trip_fee_usd(stake_usd, lev) * float(
        m.get("spike_fee_mult", 1.08)
    ) / 2.0
    if use_net_exit_targets(mode_id):
        quick = spike_floor
    else:
        tp_frac = float(m.get("spike_max_tp_frac", 0.72))
        if in_grace:
            tp_frac = min(
                tp_frac,
                float(m.get("berserk_spike_grace_max_tp_frac") or 0.52),
            )
        quick = max(fee, tp_target_usd * tp_frac)
        if is_berserk_family(mode_id):
            quick = max(quick, fee * float(m.get("berserk_spike_min_net_fee_mult") or 1.22))
    if unrealized_usd < quick:
        return ""
    if unrealized_usd >= tp_target_usd * 0.92:
        return ""
    # Net hazırsa tepe beklemeden kapat
    if is_berserk_family(mode_id):
        ready, _, _ = net_scalp_close_ready(
            unrealized_usd=unrealized_usd,
            stake_usd=stake_usd,
            leverage=lev,
            entry_fee=ef,
            mode_id=mode_id,
        )
        if ready:
            return "SPIKE-QUICK"
    peak = max(max_unreal_seen, unrealized_usd)
    if peak < quick * 0.85:
        return ""
    if unrealized_usd >= quick and unrealized_usd <= quick * 1.05:
        return "SPIKE-QUICK"
    if peak >= quick and unrealized_usd >= quick and unrealized_usd < peak * 0.85:
        return "SPIKE-QUICK"
    return ""


def evaluate_position_exit(
    *,
    opened_at: str | None,
    unrealized_usd: float,
    tp_target_usd: float,
    sl_target_usd: float,
    stake_usd: float,
    min_unreal_seen: float = 0.0,
    max_unreal_seen: float = 0.0,
    mode_id: str | None = None,
    leverage: int = 5,
    entry_fee: float | None = None,
    pos: dict[str, Any] | None = None,
    client: Any | None = None,
) -> str | None:
    """Seçili moda göre kapanış nedeni (paper + Binance emirleri)."""
    from elite_trader.fee_economics import (
        filter_profitable_exit_reason,
        tp_sl_gross_triggers,
        use_net_exit_targets,
    )

    mid = resolve_mode_id(mode_id or active_execution_mode())
    lev = max(int(leverage), 1)
    tp_thr = float(tp_target_usd)
    sl_thr = float(sl_target_usd)
    if use_net_exit_targets(mid):
        tp_thr, sl_thr, _, _ = tp_sl_gross_triggers(stake_usd, lev, mid)

    reason: str | None = None
    if unrealized_usd >= tp_thr and unrealized_usd > 0:
        reason = "TP"
    if not reason:
        spike = _spike_reason_mode(
            mode_id=mid,
            opened_at=opened_at,
            unrealized_usd=unrealized_usd,
            tp_target_usd=tp_thr if use_net_exit_targets(mid) else tp_target_usd,
            stake_usd=stake_usd,
            max_unreal_seen=max_unreal_seen,
            leverage=lev,
            entry_fee=entry_fee,
        )
        if spike:
            reason = spike
    if not reason and is_berserk_family(mid):
        from elite_trader.berserk_exit import (
            berserk_sl_exit_allowed,
            evaluate_berserk_exit_addons,
        )

        prof = mode_catalog().get(mid) or {}
        addon = evaluate_berserk_exit_addons(
            opened_at=opened_at,
            unrealized_usd=unrealized_usd,
            tp_target_usd=tp_thr if use_net_exit_targets(mid) else tp_target_usd,
            sl_target_usd=sl_thr,
            stake_usd=stake_usd,
            min_unreal_seen=min_unreal_seen,
            max_unreal_seen=max_unreal_seen,
            leverage=lev,
            mode_id=mid,
            profile=prof,
            pos=pos,
            client=client,
        )
        if addon:
            reason = addon
    if not reason and unrealized_usd <= -sl_thr:
        mega_no_sl = str(mid or "").lower() == "mega" and os.getenv(
            "MEGA_DISABLE_SL_EXIT", "1"
        ).strip().lower() in ("1", "true", "yes")
        if mega_no_sl:
            pass
        elif is_berserk_family(mid):
            from elite_trader.berserk_exit import berserk_sl_exit_allowed

            prof = mode_catalog().get(mid) or {}
            if berserk_sl_exit_allowed(
                opened_at=opened_at,
                unrealized_usd=unrealized_usd,
                sl_target_usd=sl_thr,
                stake_usd=stake_usd,
                max_unreal_seen=max_unreal_seen,
                profile=prof,
            ):
                reason = "SL"
        elif not _sl_blocked_by_grace(
            mode_id=mid,
            opened_at=opened_at,
            unrealized_usd=unrealized_usd,
            sl_target_usd=sl_thr,
        ):
            reason = "SL"
    if not reason:
        if is_berserk_family(mid):
            from elite_trader.berserk_exit import berserk_stale_reason

            prof = mode_catalog().get(mid) or {}
            stale = berserk_stale_reason(
                opened_at=opened_at,
                unrealized_usd=unrealized_usd,
                tp_target_usd=tp_thr if use_net_exit_targets(mid) else tp_target_usd,
                stake_usd=stake_usd,
                min_unreal_seen=min_unreal_seen,
                max_unreal_seen=max_unreal_seen,
                leverage=lev,
                mode_id=mid,
                profile=prof,
            )
        else:
            stale = _stale_release_reason_mode(
                mode_id=mid,
                opened_at=opened_at,
                unrealized_usd=unrealized_usd,
                tp_target_usd=tp_target_usd,
                stake_usd=stake_usd,
                min_unreal_seen=min_unreal_seen,
            )
        if stale:
            reason = stale

    from elite_trader.fee_economics import (
        exit_tp_only,
        is_profit_tp_exit,
        is_stop_loss_exit,
        report_exit_gate_block,
    )

    if reason and exit_tp_only(mid) and not is_profit_tp_exit(reason):
        allow_mega_loss = False
        if str(mid).lower() == "mega":
            try:
                from elite_trader.mega_live import (
                    mega_sl_exit_disabled,
                    mega_underwater_cut_enabled,
                )

                rloss = str(reason).upper()
                if rloss == "TIME-STOP" and mega_underwater_cut_enabled():
                    allow_mega_loss = True
                elif is_stop_loss_exit(reason) and not mega_sl_exit_disabled():
                    allow_mega_loss = True
            except Exception:
                pass
        if not allow_mega_loss:
            report_exit_gate_block(
                kind="blocked_non_tp",
                symbol="",
                reason=reason,
                detail=f"uPnL=${unrealized_usd:.4f} — yalnızca TP/SPIKE",
            )
            reason = None

    return filter_profitable_exit_reason(
        reason,
        gross_unreal=unrealized_usd,
        stake_usd=stake_usd,
        leverage=lev,
        entry_fee=entry_fee,
        mode_id=mid,
        pos=pos,
        client=client,
    )


def set_view_mode(mode_id: str) -> str:
    mode_id = resolve_mode_id(mode_id)
    if mode_id not in mode_catalog():
        raise ValueError(f"unknown mode: {mode_id}")
    st = _load_state()
    old = resolve_mode_id(str(st.get("view_mode") or active_execution_mode()))
    st["view_mode"] = mode_id
    _save_state(st)
    if old != mode_id:
        try:
            from elite_trader.system_checkpoint_md import on_view_change

            on_view_change(old, mode_id)
        except Exception:
            pass
    return mode_id


def set_execution_mode(mode_id: str, *, note: str = "") -> tuple[str, str]:
    """Binance çıkış motoru — .env dokunulmaz; motor değişince oturum/borsa senkronu."""
    mode_id = resolve_mode_id(mode_id)
    if mode_id not in mode_catalog():
        raise ValueError(f"unknown mode: {mode_id}")
    st = _load_state()
    old = active_execution_mode()
    st["execution_mode"] = mode_id
    st["current_mode"] = mode_id
    st["last_execution_change_at"] = datetime.now(timezone.utc).isoformat()
    st["last_execution_note"] = note or f"emir motoru {old} → {mode_id}"
    _save_state(st)
    try:
        from elite_trader.system_checkpoint_md import on_motor_change

        on_motor_change(old, mode_id, note=note or "")
    except Exception:
        pass
    return old, mode_id


def position_age_seconds(pos: dict[str, Any]) -> float:
    et = pos.get("entry_time")
    if et is not None:
        try:
            fv = float(et)
            if fv > 1e9:
                return max(0.0, time.time() - fv)
        except (TypeError, ValueError):
            pass
        s = str(et).strip()
        if s:
            for parser in (
                lambda x: datetime.fromisoformat(x.replace("Z", "+00:00").replace(" ", "T", 1)),
                lambda x: datetime.strptime(x[:19], "%Y-%m-%d %H:%M:%S"),
            ):
                try:
                    dt = parser(s)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
                except Exception:
                    continue
    opened = pos.get("opened_at_iso") or pos.get("entry_time_str")
    if opened:
        try:
            dt = datetime.fromisoformat(str(opened).replace("Z", "+00:00").replace(" ", "T", 1))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
        except Exception:
            pass
    return 0.0


def shadow_targets(stake_usd: float, mode_id: str) -> dict[str, float]:
    m = mode_catalog().get(mode_id) or mode_catalog()[DEFAULT_ACTIVE_FUTURES_MODE]
    s = max(float(stake_usd), 1.0)
    return {
        "tp_usd": s * float(m["tp_stake_pct"]) * float(m["tp_trigger_frac"]),
        "sl_usd": s * float(m["sl_stake_pct"]),
    }


def shadow_action(
    *,
    unrealized_usd: float,
    stake_usd: float,
    mode_id: str,
    age_sec: float = 0.0,
    leverage: int = 5,
) -> str | None:
    t = shadow_targets(stake_usd, mode_id)
    m = mode_catalog().get(mode_id) or {}
    if unrealized_usd >= t["tp_usd"]:
        return "TP"
    if unrealized_usd <= -t["sl_usd"]:
        return "SL"
    if m.get("spike_enabled") and age_sec >= float(m.get("spike_min_age_sec", 40)):
        fee = stake_usd * max(int(leverage), 1) * 0.0008
        quick = max(
            fee * float(m.get("spike_fee_mult", 1.08)),
            t["tp_usd"] * float(m.get("spike_max_tp_frac", 0.72)),
        )
        if fee <= unrealized_usd < t["tp_usd"] * 0.92 and unrealized_usd <= quick * 1.05:
            return "SPIKE"
    if m.get("stale_enabled") and age_sec >= float(m.get("stale_min_age_min", 2)) * 60:
        fee = stake_usd * max(int(leverage), 1) * 0.0008
        if unrealized_usd >= fee * 1.1 and unrealized_usd < t["tp_usd"] * 0.99:
            return "STALE"
    return None


def _action_bucket(action: str | None) -> str:
    if not action:
        return "BEKLE"
    return action


def _fee_net(gross: float, fees: float) -> float:
    net = gross - fees
    return net - max(0.0, net * 0.10)


def counterfactual_final_pnl(
    closed: dict[str, Any], mode_id: str, *, is_live: bool = False
) -> float:
    if is_live:
        return float(closed.get("final_pnl") or closed.get("net_pnl") or 0)

    stake = float(closed.get("stake_usd") or 250)
    lev = int(closed.get("leverage") or 5)
    gross = float(closed.get("pnl_usd") or 0)
    duration = max(float(closed.get("duration") or 0), 1.0)
    fees = float(closed.get("total_fees") or 0)
    if fees <= 0:
        fees = stake * max(lev, 1) * 0.0008

    tgt = shadow_targets(stake, mode_id)
    tp, sl = tgt["tp_usd"], tgt["sl_usd"]
    ex = str(closed.get("exit_reason") or "").upper()

    act = _action_bucket(
        shadow_action(
            unrealized_usd=gross,
            stake_usd=stake,
            mode_id=mode_id,
            age_sec=duration,
            leverage=lev,
        )
    )

    if "SL-EMERGENCY" in ex or gross < -sl * 1.35:
        return round(_fee_net(-sl, fees), 2)
    if gross >= tp * 0.98:
        return round(_fee_net(tp, fees), 2)
    if gross <= -sl:
        return round(_fee_net(-sl, fees), 2)
    if act == "TP" and gross > 0:
        return round(_fee_net(min(gross, tp), fees), 2)
    if act in ("SPIKE", "STALE") and gross > 0:
        return round(_fee_net(gross, fees), 2)
    if act == "SL":
        return round(_fee_net(-sl, fees), 2)

    bounded = max(-sl, min(gross, tp))
    return round(_fee_net(bounded, fees), 2)


def _session_start_capital(
    starting_capital: float, live_summary: dict[str, Any] | None
) -> float:
    if live_summary:
        for key in ("starting_capital", "session_start_capital"):
            v = float(live_summary.get(key) or 0)
            if v > 0:
                return v
    return starting_capital if starting_capital > 0 else 5000.0


def _mode_dashboard_block(
    open_positions: list[dict[str, Any]],
    closed_positions: list[dict[str, Any]],
    mode_id: str,
    *,
    session_start: float,
    is_live: bool = False,
    live_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if is_live and live_summary:
        oc = int(live_summary.get("open_trades") or len(open_positions))
        cc = int(live_summary.get("closed_trades") or len(closed_positions))
        wc = int(live_summary.get("win_count") or 0)
        unreal = float(live_summary.get("unrealized_pnl") or 0)
        cur = float(live_summary.get("current_capital") or 0)
        if cur <= 0:
            cur = session_start + float(live_summary.get("realized_pnl") or 0) + unreal
        return {
            "balance": round(cur, 2),
            "available": round(float(live_summary.get("available_capital") or 0), 2),
            "starting_capital": round(session_start, 2),
            "open_count": oc,
            "open_stake": round(float(live_summary.get("total_active_stake") or 0), 2),
            "open_notional": round(
                float(live_summary.get("total_position_value") or 0), 2
            ),
            "open_win": len(
                [p for p in open_positions if float(p.get("unrealized_pnl") or 0) > 0]
            ),
            "open_loss": len(
                [p for p in open_positions if float(p.get("unrealized_pnl") or 0) <= 0]
            ),
            "unrealized_pnl": round(unreal, 2),
            "realized_pnl": round(float(live_summary.get("realized_pnl") or 0), 2),
            "total_pnl": round(float(live_summary.get("total_pnl") or 0), 2),
            "total_pnl_pct": round(float(live_summary.get("total_pnl_pct") or 0), 2),
            "win_rate": round(float(live_summary.get("win_rate") or 0), 1),
            "closed_trades": cc,
            "closed_wins": wc,
            "closed_losses": max(0, cc - wc),
            "is_live": True,
        }

    realized = 0.0
    wins = 0
    paper_book = bool(
        closed_positions
        and (closed_positions[0].get("universe_id") or closed_positions[0].get("signal_source", "").startswith("Parallel-"))
    )
    for c in closed_positions:
        if is_live:
            fp = float(c.get("final_pnl") or c.get("net_pnl") or 0)
        elif paper_book:
            fp = float(c.get("final_pnl") or c.get("net_pnl") or 0)
        else:
            fp = counterfactual_final_pnl(c, mode_id, is_live=False)
        realized += fp
        if fp > 0:
            wins += 1

    closed_n = len(closed_positions)
    wr = (wins / closed_n * 100.0) if closed_n else None

    open_stake = sum(float(p.get("stake_usd") or 0) for p in open_positions)
    open_notional = sum(
        float(p.get("position_value") or 0)
        or float(p.get("size") or 0) * float(p.get("current_price") or 0)
        for p in open_positions
    )
    unreal_all = sum(float(p.get("unrealized_pnl") or 0) for p in open_positions)
    open_win = len([p for p in open_positions if float(p.get("unrealized_pnl") or 0) > 0])
    open_loss = len(open_positions) - open_win

    total_pnl = realized + unreal_all
    balance = session_start + total_pnl
    available = balance - open_stake
    pct = (total_pnl / session_start * 100.0) if session_start else 0.0

    return {
        "balance": round(balance, 2),
        "available": round(available, 2),
        "starting_capital": round(session_start, 2),
        "open_count": len(open_positions),
        "open_stake": round(open_stake, 2),
        "open_notional": round(open_notional, 2),
        "open_win": open_win,
        "open_loss": open_loss,
        "unrealized_pnl": round(unreal_all, 2),
        "realized_pnl": round(realized, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(pct, 2),
        "win_rate": round(wr, 1) if wr is not None else None,
        "closed_trades": closed_n,
        "closed_wins": wins,
        "closed_losses": max(0, closed_n - wins),
        "is_live": False,
    }


def parallel_universe_report(
    open_positions: list[dict[str, Any]],
    closed_positions: list[dict[str, Any]] | None = None,
    *,
    starting_capital: float = 5000.0,
    live_summary: dict[str, Any] | None = None,
    parallel_books: dict[str, dict[str, Any]] | None = None,
    exchange_open_ui: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    closed_positions = closed_positions or []
    session_start = _session_start_capital(starting_capital, live_summary)
    exec_mid = active_execution_mode()
    live_binance = exchange_open_ui is not None

    if live_only_execution():
        mode_open = list(exchange_open_ui or [])
        if parallel_books is None:
            try:
                from elite_trader.parallel_universe_engine import all_universe_books

                parallel_books = all_universe_books()
            except Exception:
                parallel_books = {}
        book = parallel_books.get(exec_mid) or {}
        mode_closed = list(book.get("closed") or [])[-200:]
        modes = mode_catalog()
        m = modes.get(exec_mid) or {}
        counts = {"TP": 0, "SL": 0, "SPIKE": 0, "STALE": 0, "BEKLE": 0}
        position_hints: list[dict[str, Any]] = []
        for pos in mode_open:
            unreal = float(pos.get("unrealized_pnl") or 0)
            stake = float(pos.get("stake_usd") or 1)
            age = position_age_seconds(pos)
            lev = int(pos.get("leverage") or 5)
            act = _action_bucket(
                shadow_action(
                    unrealized_usd=unreal,
                    stake_usd=stake,
                    mode_id=exec_mid,
                    age_sec=age,
                    leverage=lev,
                )
            )
            counts[act] = counts.get(act, 0) + 1
            tgt = shadow_targets(stake, exec_mid)
            position_hints.append(
                {
                    "id": pos.get("id"),
                    "symbol": pos.get("symbol"),
                    "side": pos.get("side"),
                    "unrealized_usd": round(unreal, 2),
                    "action": act,
                    "age_min": round(age / 60.0, 1),
                    "tp_usd": round(tgt["tp_usd"], 2),
                    "sl_usd": round(tgt["sl_usd"], 2),
                }
            )
        ah_ls = dict(live_summary or {})
        ah_ls["open_trades"] = len(mode_open)
        ah_ls["closed_trades"] = len(mode_closed)
        dash = _mode_dashboard_block(
            mode_open,
            mode_closed,
            exec_mid,
            session_start=session_start,
            is_live=True,
            live_summary=ah_ls,
        )
        dash["open_count"] = len(mode_open)
        dash["unrealized_pnl"] = round(
            sum(float(p.get("unrealized_pnl") or 0) for p in mode_open), 4
        )
        return {
            "live_only": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "starting_capital": session_start,
            "live_mode_id": exec_mid,
            "live_open_count": len(mode_open),
            "live_closed_count": len(mode_closed),
            "paper_open_count": 0,
            "paper_closed_count": 0,
            "open_count": len(mode_open),
            "closed_count": len(mode_closed),
            "sim_note": "Yalnızca Binance canlı emir — paper/gölge kapalı",
            "modes": [
                {
                    "mode_id": exec_mid,
                    "label": m.get("label", exec_mid),
                    "short_label": m.get("short_label") or exec_mid,
                    "is_live": True,
                    "is_execution_motor": True,
                    "uses_binance_book": True,
                    "is_paper": False,
                    "is_view_mode": exec_mid == active_view_mode(),
                    "parallel": False,
                    "counts": counts,
                    "open_n": len(mode_open),
                    "closed_n": len(mode_closed),
                    "positions": position_hints,
                    "dashboard": dash,
                }
            ],
            "by_symbol": [],
        }

    modes = mode_catalog()
    per_mode: list[dict[str, Any]] = []
    per_symbol: list[dict[str, Any]] = []
    if parallel_books is None:
        try:
            from elite_trader.parallel_universe_engine import all_universe_books

            parallel_books = all_universe_books()
        except Exception:
            parallel_books = {}

    exec_mid = active_execution_mode()
    live_binance = exchange_open_ui is not None
    pu_open_total = 0
    pu_closed_total = 0
    pu_paper_open = 0
    pu_paper_closed = 0
    live_open_n = 0
    live_closed_n = 0
    for mid in mode_order():
        if mid not in modes:
            continue
        m = modes[mid]
        is_exec_motor = mid == exec_mid and live_binance
        book = parallel_books.get(mid) or {}
        mode_open = list(book.get("open") or [])
        mode_closed = list(book.get("closed") or [])
        if is_exec_motor and exchange_open_ui is not None:
            mode_open = list(exchange_open_ui)
            live_open_n += len(mode_open)
            live_closed_n += len(mode_closed)
        else:
            pu_paper_open += len(mode_open)
            pu_paper_closed += len(mode_closed)
        pu_open_total += len(mode_open)
        pu_closed_total += len(mode_closed)
        counts = {"TP": 0, "SL": 0, "SPIKE": 0, "STALE": 0, "BEKLE": 0}
        position_hints: list[dict[str, Any]] = []

        for pos in mode_open:
            unreal = float(pos.get("unrealized_pnl") or 0)
            stake = float(pos.get("stake_usd") or 1)
            age = position_age_seconds(pos)
            lev = int(pos.get("leverage") or 5)
            act = _action_bucket(
                shadow_action(
                    unrealized_usd=unreal,
                    stake_usd=stake,
                    mode_id=mid,
                    age_sec=age,
                    leverage=lev,
                )
            )
            counts[act] = counts.get(act, 0) + 1
            tgt = shadow_targets(stake, mid)
            position_hints.append(
                {
                    "id": pos.get("id"),
                    "symbol": pos.get("symbol"),
                    "side": pos.get("side"),
                    "unrealized_usd": round(unreal, 2),
                    "action": act,
                    "age_min": round(age / 60.0, 1),
                    "tp_usd": round(tgt["tp_usd"], 2),
                    "sl_usd": round(tgt["sl_usd"], 2),
                }
            )

        for c in mode_closed:
            ex = str(c.get("exit_reason") or "").upper()
            if ex.startswith("TP"):
                counts["TP"] += 1
            elif ex.startswith("SL"):
                counts["SL"] += 1
            elif "SPIKE" in ex:
                counts["SPIKE"] += 1
            elif "STALE" in ex:
                counts["STALE"] += 1
        if is_exec_motor and live_summary is not None:
            ah_ls = dict(live_summary)
            ah_ls["open_trades"] = len(mode_open)
            ah_ls["closed_trades"] = len(mode_closed)
            ah_ls["win_count"] = len(
                [
                    c
                    for c in mode_closed
                    if float(c.get("final_pnl") or c.get("net_pnl") or 0) > 0
                ]
            )
            ah_ls["win_rate"] = round(
                ah_ls["win_count"] / len(mode_closed) * 100, 1
            ) if mode_closed else 0
            ah_ls["realized_pnl"] = round(
                sum(float(c.get("final_pnl") or 0) for c in mode_closed), 2
            )
            dash = _mode_dashboard_block(
                mode_open,
                mode_closed,
                mid,
                session_start=session_start,
                is_live=True,
                live_summary=ah_ls,
            )
        else:
            try:
                from elite_trader.parallel_universe_engine import (
                    build_summary as pu_build_summary,
                )

                s = pu_build_summary(mid)
                dash = {
                    "balance": s["current_capital"],
                    "available": s["available_capital"],
                    "starting_capital": s["starting_capital"],
                    "open_count": s["open_trades"],
                    "open_stake": s.get("total_active_stake", 0),
                    "open_notional": s.get("total_position_value", 0),
                    "open_win": len(
                        [
                            p
                            for p in mode_open
                            if float(p.get("unrealized_pnl") or 0) > 0
                        ]
                    ),
                    "open_loss": len(
                        [
                            p
                            for p in mode_open
                            if float(p.get("unrealized_pnl") or 0) <= 0
                        ]
                    ),
                    "unrealized_pnl": s["unrealized_pnl"],
                    "realized_pnl": s["realized_pnl"],
                    "total_pnl": s["total_pnl"],
                    "total_pnl_pct": s["total_pnl_pct"],
                    "win_rate": s["win_rate"],
                    "closed_trades": s["closed_trades"],
                    "closed_wins": s["win_count"],
                    "closed_losses": max(0, s["closed_trades"] - s["win_count"]),
                    "is_live": False,
                }
            except Exception:
                dash = _mode_dashboard_block(
                    mode_open,
                    mode_closed,
                    mid,
                    session_start=session_start,
                    is_live=False,
                    live_summary=None,
                )
        if is_exec_motor and exchange_open_ui is not None:
            dash["open_count"] = len(mode_open)
            dash["unrealized_pnl"] = round(
                sum(float(p.get("unrealized_pnl") or 0) for p in mode_open), 4
            )
        entry: dict[str, Any] = {
                "mode_id": mid,
                "label": m["label"],
                "short_label": m.get("short_label") or mid,
                "is_live": bool(is_exec_motor and is_live_binance_motor(mid)),
                "is_execution_motor": mid == exec_mid,
                "uses_binance_book": bool(is_exec_motor and is_live_binance_motor(mid)),
                "is_paper": not (is_exec_motor and is_live_binance_motor(mid)),
                "is_view_mode": mid == active_view_mode(),
                "parallel": bool(m.get("parallel")),
                "counts": counts,
                "open_n": len(mode_open),
                "closed_n": len(mode_closed),
                "positions": position_hints,
                "dashboard": dash,
            }
        if mid == "berserk":
            from elite_trader.berserk_metrics import build_berserk_health

            entry["berserk_health"] = build_berserk_health(book)
        if mid == "berserk2":
            from elite_trader.berserk2_metrics import build_berserk2_health

            entry["berserk2_health"] = build_berserk2_health(book)
        if mid == "hunter":
            from elite_trader.hunter_metrics import build_hunter_health, hunter_scan_meta

            entry["hunter_health"] = build_hunter_health(
                book, scan_meta=hunter_scan_meta()
            )
        if mid == "chop_master":
            from elite_trader.chop_metrics import build_chop_health

            entry["chop_health"] = build_chop_health(book)
        if mid == "sentinel":
            from elite_trader.sentinel_metrics import build_sentinel_health

            entry["sentinel_health"] = build_sentinel_health(book)
        per_mode.append(entry)

    mode_open_map: dict[str, list[dict[str, Any]]] = {}
    keys_seen: set[tuple[str, str]] = set()
    for mid in mode_order():
        if mid not in modes:
            continue
        mo = list((parallel_books.get(mid) or {}).get("open") or [])
        if mid == exec_mid and live_binance and exchange_open_ui is not None:
            mo = list(exchange_open_ui)
        mode_open_map[mid] = mo
        for pos in mo:
            keys_seen.add((str(pos.get("symbol")), str(pos.get("side"))))

    for sym, side in sorted(keys_seen):
        row: dict[str, Any] = {
            "symbol": sym,
            "side": side,
            "unrealized_usd": 0.0,
            "by_mode": {},
        }
        for mid in mode_order():
            if mid not in modes:
                continue
            hit = next(
                (
                    p
                    for p in mode_open_map.get(mid, [])
                    if p.get("symbol") == sym and p.get("side") == side
                ),
                None,
            )
            if not hit:
                row["by_mode"][mid] = "—"
                continue
            unreal = float(hit.get("unrealized_pnl") or 0)
            stake = float(hit.get("stake_usd") or 1)
            age = position_age_seconds(hit)
            lev = int(hit.get("leverage") or 5)
            row["by_mode"][mid] = _action_bucket(
                shadow_action(
                    unrealized_usd=unreal,
                    stake_usd=stake,
                    mode_id=mid,
                    age_sec=age,
                    leverage=lev,
                )
            )
            if mid == active_view_mode():
                row["unrealized_usd"] = round(unreal, 2)
        per_symbol.append(row)

    exec_label = (modes.get(exec_mid) or {}).get("short_label") or exec_mid
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_futures_mode": exec_mid,
        "live_mode_id": "sentinel",
        "execution_mode_id": exec_mid,
        "execution_label": exec_label,
        "parallel_mode_ids": list(_PARALLEL_IDS),
        "open_count": pu_open_total,
        "closed_count": pu_closed_total,
        "live_open_count": live_open_n,
        "live_closed_count": live_closed_n,
        "paper_open_count": pu_paper_open,
        "paper_closed_count": pu_paper_closed,
        "starting_capital": round(session_start, 2),
        "sim_note": (
            "Ortak piyasa zekâ havuzu (Binance + haber, dezenformasyon filtreli) → "
            "her mod kendi filtresi. Motor olmayan modlar paper; canlı motor Binance demo. "
            f"Şu an canlı motor: {exec_label}."
        ),
        "modes": per_mode,
        "by_symbol": per_symbol,
    }


def snapshot_for_ui() -> dict[str, Any]:
    st = _load_state()
    modes = mode_catalog()
    ex = active_execution_mode()
    vw = active_view_mode()
    listed = [modes[i] for i in _MODE_IDS]
    return {
        "current_mode": ex,
        "current_label": modes[ex]["label"],
        "execution_mode": ex,
        "active_futures_mode": ex,
        "execution_label": modes[ex]["label"],
        "view_mode": vw,
        "view_label": modes[vw]["label"],
        "live_mode_id": ex if is_live_binance_motor(ex) else "sentinel",
        "live_only": live_only_execution(),
        "parallel_mode_ids": list(_MODE_IDS),
        "previous_mode": st.get("previous_mode"),
        "last_change_at": st.get("last_change_at"),
        "last_change_note": st.get("last_change_note"),
        "last_execution_change_at": st.get("last_execution_change_at"),
        "last_execution_note": st.get("last_execution_note"),
        "modes": [
            {
                "id": m["id"],
                "label": m["label"],
                "short_label": m.get("short_label") or m["id"],
                "description": m["description"],
                "shadow_only": m.get("shadow_only", True),
                "is_live": m["id"] == ex and is_live_binance_motor(ex),
                "is_paper": m["id"] != ex or not is_live_binance_motor(ex),
                "parallel": m.get("parallel", False),
            }
            for m in listed
        ],
        "mode_params": {m["id"]: m for m in listed},
    }


def switch_mode(new_mode: str, *, note: str = "") -> tuple[str, str]:
    """Geriye uyumluluk — yalnızca görünüm (pozisyon kapatmaz)."""
    old = active_view_mode()
    set_view_mode(new_mode)
    if note:
        st = _load_state()
        st["last_change_note"] = note
        _save_state(st)
    return old, active_view_mode()


def ensure_spike_quick_proposal() -> None:
    from elite_trader.loss_learner import ensure_bootstrap_proposals

    ensure_bootstrap_proposals()
