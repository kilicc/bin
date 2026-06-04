"""
Evrim — 10 modülü birleştiren tek orchestrator.

Hedef: hızlı, agresif, yüksek işlem, fee-aware, backtest + backup + sınırlı self-tune.
Varsayılan: demo/testnet paper; canlı kapalı (profil bayrağı + risk raporu).
Yalnızca evrim.
"""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODE_ID = "evrim"
_ROOT = Path(__file__).resolve().parent.parent
_BACKUP_DIR = _ROOT / "data" / "backups" / "evrim_unified"

MODULES: tuple[dict[str, str], ...] = (
    {"id": "mtf", "module": "evrim_mtf_indicators", "role": "MTF skor katkısı"},
    {"id": "pa", "module": "evrim_price_action", "role": "Price action + fake breakout"},
    {"id": "vo", "module": "evrim_volume_orderbook", "role": "Volume / orderbook / spread"},
    {"id": "regime", "module": "evrim_market_regime", "role": "8 rejim politikası"},
    {"id": "exit", "module": "evrim_dynamic_exit", "role": "Dinamik TP/SL / trailing"},
    {"id": "expectancy", "module": "evrim_expectancy", "role": "Net expectancy + fee koruma"},
    {"id": "learning", "module": "evrim_trade_learning", "role": "Journal + 50-trade analiz"},
    {"id": "validator", "module": "evrim_param_validator", "role": "BT + forward test onayı"},
    {"id": "radar", "module": "evrim_market_radar", "role": "Risk radar + haber"},
    {"id": "hybrid", "module": "evrim_hybrid_scorer", "role": "0-100 skor orchestrator"},
)

_NEWS_LAST = 0.0
_NEWS_INTERVAL = 300.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_evrim_profile() -> dict[str, Any]:
    from elite_trader.mode_profiles import get_profile

    return dict(get_profile(MODE_ID) or {})


def trading_mode(profile: dict[str, Any] | None = None) -> str:
    """demo | live — varsayılan demo."""
    p = profile or get_evrim_profile()
    return str(p.get("evrim_trading_mode") or "demo").lower()


def is_live_trading_enabled(profile: dict[str, Any] | None = None) -> bool:
    p = profile or get_evrim_profile()
    return bool(p.get("evrim_live_trading_enabled", False))


def is_unified_enabled(profile: dict[str, Any] | None = None) -> bool:
    p = profile or get_evrim_profile()
    return bool(p.get("evrim_unified_engine_enabled", True))


def assert_evrim_live_allowed(profile: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Canlı emir öncesi — aktif Binance motoru Evrim ise profil demo bayraklarını atla."""
    try:
        from elite_trader.panel_strategy import is_live_binance_motor

        if is_live_binance_motor(MODE_ID):
            return True, ""
    except Exception:
        pass
    p = profile or get_evrim_profile()
    if not is_unified_enabled(p):
        return True, ""
    if trading_mode(p) != "live":
        return False, "evrim_demo_only"
    if not is_live_trading_enabled(p):
        return False, "evrim_live_disabled"
    report = build_pre_live_risk_report(p)
    if not report.get("live_ready"):
        return False, "evrim_risk_report_not_ready"
    return True, ""


def maybe_refresh_news(force: bool = False) -> dict[str, Any]:
    global _NEWS_LAST
    now = time.time()
    if not force and now - _NEWS_LAST < _NEWS_INTERVAL:
        return {"ok": True, "skipped": "throttled"}
    try:
        from elite_trader.evrim_news_feed import persist_radar_news_feed

        out = persist_radar_news_feed(force=force)
        _NEWS_LAST = now
        return out
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:80]}


def backup_profile(tag: str = "manual") -> str | None:
    """Profil yedeği — param validator ile uyumlu."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    src = _ROOT / "data" / "mode_profiles.json"
    if not src.is_file():
        return None
    dest = _BACKUP_DIR / f"mode_profiles_{stamp}_{tag}.json"
    shutil.copy2(src, dest)
    return str(dest)


def bootstrap_unified_engine() -> dict[str, Any]:
    """İlk kurulum: promptlar, demo varsayılan, haber çekimi."""
    from elite_trader.mode_profiles import save_profile

    out: dict[str, Any] = {"ok": True, "steps": []}
    try:
        from elite_trader.evrim_training import (
            ensure_dynamic_exit_prompt_ingested,
            ensure_expectancy_prompt_ingested,
            ensure_market_radar_prompt_ingested,
            ensure_mtf_prompt_ingested,
            ensure_pa_prompt_ingested,
            ensure_param_auto_test_prompt_ingested,
            ensure_regime_prompt_ingested,
            ensure_trade_learning_prompt_ingested,
            ensure_vo_prompt_ingested,
            ensure_unified_prompt_ingested,
        )

        for fn in (
            ensure_mtf_prompt_ingested,
            ensure_pa_prompt_ingested,
            ensure_vo_prompt_ingested,
            ensure_regime_prompt_ingested,
            ensure_dynamic_exit_prompt_ingested,
            ensure_expectancy_prompt_ingested,
            ensure_trade_learning_prompt_ingested,
            ensure_param_auto_test_prompt_ingested,
            ensure_market_radar_prompt_ingested,
            ensure_unified_prompt_ingested,
        ):
            try:
                fn()
                out["steps"].append(fn.__name__)
            except Exception as exc:
                out["steps"].append(f"{fn.__name__}:err:{exc}"[:60])
    except Exception as exc:
        out["ok"] = False
        out["error"] = str(exc)[:120]

    save_profile(
        MODE_ID,
        {
            "evrim_unified_engine_enabled": True,
            "evrim_trading_mode": "demo",
            "evrim_live_trading_enabled": False,
            "evrim_market_radar_enabled": True,
            "evrim_live_training": True,
        },
    )
    news = maybe_refresh_news(force=True)
    out["news"] = news
    out["backup"] = backup_profile("bootstrap")
    return out


def build_pre_live_risk_report(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Canlıya geçmeden önce: beklenen PnL, fee oranı, drawdown tahmini.
    """
    p = profile or get_evrim_profile()
    bt_path = _ROOT / "data" / "evrim_mtf_backtest.json"
    bt: dict[str, Any] = {}
    if bt_path.is_file():
        try:
            bt = json.loads(bt_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    exp_m: dict[str, Any] = {}
    radar_st: dict[str, Any] = {}
    journal_n = 0
    try:
        from elite_trader.evrim_training import load_training_state

        st = load_training_state()
        exp_m = dict(st.get("expectancy_metrics") or {})
        radar_st = dict(st.get("market_radar_state") or {})
        journal_n = int(st.get("trade_journal_count") or 0)
    except Exception:
        pass

    wr = float(bt.get("win_rate_pct") or 0)
    trades = int(bt.get("total_trades") or 0)
    enter_rate = float(bt.get("enter_rate_pct") or 0)
    fee_gross = float(exp_m.get("fee_to_gross_profit_pct") or bt.get("expectancy_metrics", {}).get("fee_to_gross_profit_pct") or 0)
    exp_usd = float(exp_m.get("expectancy_usd") or 0)
    avg_win = float(exp_m.get("avg_win_usd") or 0)
    avg_loss = float(exp_m.get("avg_loss_usd") or 0)

    stake = float(p.get("min_stake_usd") or 140)
    est_trades_day = max(5, int(enter_rate * 0.01 * 120))
    est_net_day = exp_usd * est_trades_day if exp_usd else (avg_win * wr / 100 + avg_loss * (1 - wr / 100)) * est_trades_day

    dd_bt = 0.0
    for row in bt.get("per_symbol") or []:
        if row.get("trades"):
            dd_bt = max(dd_bt, abs(float(row.get("win_rate") or 0) - 50))
    dd_radar = abs(float(radar_st.get("day_pnl_pct") or 0))
    est_max_dd_pct = max(8.0, dd_radar, min(25.0, 12.0 + (100 - wr) * 0.1))

    fee_ok = fee_gross < 70
    wr_ok = wr >= 48 and trades >= 30
    exp_ok = exp_usd > 0 or (avg_win > abs(avg_loss) * 0.9)
    live_ready = fee_ok and wr_ok and exp_ok and journal_n >= 20

    warnings: list[str] = []
    if not fee_ok:
        warnings.append("fee_gross_high")
    if not wr_ok:
        warnings.append("backtest_wr_low")
    if not exp_ok:
        warnings.append("negative_expectancy")
    if journal_n < 20:
        warnings.append("journal_sparse")
    if trading_mode(p) == "demo":
        warnings.append("still_demo_mode")

    return {
        "generated_at": _now_iso(),
        "trading_mode": trading_mode(p),
        "live_trading_enabled": is_live_trading_enabled(p),
        "live_ready": live_ready,
        "warnings": warnings,
        "expected": {
            "pnl_per_trade_usd": round(exp_usd, 3),
            "est_trades_per_day": est_trades_day,
            "est_net_pnl_day_usd": round(est_net_day, 2),
            "win_rate_pct_bt": wr,
            "enter_rate_pct_bt": enter_rate,
        },
        "fees": {
            "fee_to_gross_profit_pct": round(fee_gross, 2),
            "protection_mode": exp_m.get("protection_mode", "normal"),
        },
        "drawdown": {
            "radar_day_pnl_pct": float(radar_st.get("day_pnl_pct") or 0),
            "est_max_intraday_dd_pct": round(est_max_dd_pct, 1),
            "halt_threshold_pct": 12,
            "half_risk_threshold_pct": 8,
        },
        "backtest_summary": {
            "total_trades": trades,
            "total_signals": int(bt.get("total_signals") or 0),
            "dominant_regime": bt.get("dominant_regime"),
            "radar_veto_count": bt.get("radar_veto_count"),
        },
        "journal_trades": journal_n,
        "recommendation": (
            "Canlı açılabilir (risk raporu yeşil)."
            if live_ready
            else "Demo/paper devam — canlı kapalı. Backtest + journal iyileşsin."
        ),
    }


def process_entry(
    mode_id: str,
    signal: dict[str, Any],
    profile: dict[str, Any],
    *,
    execution_path: str = "paper",
) -> tuple[bool, str]:
    """
    Birleşik giriş — yalnızca evrim.
    Hybrid scorer + tüm alt modüller (evaluate içinde).
    """
    if mode_id != MODE_ID:
        return True, ""

    from elite_trader.evrim_config_version import bootstrap_active_from_profile, get_trading_profile

    bootstrap_active_from_profile()
    p = get_trading_profile(profile)
    if not is_unified_enabled(p):
        from elite_trader.evrim_opportunity import evrim_entry_gate as legacy

        return legacy(mode_id, signal, p, execution_path=execution_path)

    if execution_path == "live":
        ok_live, msg = assert_evrim_live_allowed(p)
        if not ok_live:
            return False, msg

    maybe_refresh_news()

    from elite_trader.evrim_hybrid_scorer import decision_to_gate_tuple, evaluate

    dec = evaluate(signal, p, execution_path=execution_path, log_decision=True)
    ok, reason, ctx = decision_to_gate_tuple(dec)
    if ok:
        try:
            from elite_trader.evrim_opportunity import _add_xp, _load_state, _save_state

            st = _load_state()
            st["last_opportunity_ctx"] = ctx
            _save_state(st)
            _add_xp(1, "unified_pass")
        except Exception:
            pass
        signal["evrim_hybrid"] = {
            "total_score": dec.total_score,
            "tier": dec.tier,
            "stake_mult": dec.stake_mult,
            "components": dec.components,
            "expected_net_pnl_usd": dec.expected_net_pnl_usd,
        }
        signal["evrim_unified"] = {
            "modules": [m["id"] for m in MODULES],
            "trading_mode": trading_mode(p),
            "execution_path": execution_path,
            "market_radar": (ctx or {}).get("market_radar"),
        }
        if signal.get("evrim_dynamic_exit"):
            signal["evrim_hybrid"]["dynamic_exit"] = signal["evrim_dynamic_exit"]
        if (dec.context or {}).get("expectancy"):
            signal["evrim_hybrid"]["expectancy"] = dec.context["expectancy"]
        signal["evrim_entry_reason"] = reason[:200]
        if signal.get("evrim_regime"):
            ctx["market_regime"] = signal["evrim_regime"].get("id")
        from elite_trader.evrim_v2 import run_evrim_v2_entry_checks

        v2_ok, v2_reason, v2_payload = run_evrim_v2_entry_checks(
            signal,
            ctx or {},
            p,
            execution_path=execution_path,
        )
        if not v2_ok:
            return False, v2_reason[:80]
        signal["evrim_unified"]["v2"] = {
            "final_score": (v2_payload.get("meta") or {}).get("final_score"),
            "meta_tier": (v2_payload.get("meta") or {}).get("meta_tier"),
            "risk_level": (v2_payload.get("risk") or {}).get("risk_level"),
        }
        return True, reason[:80]
    return False, reason[:80]


def unified_status() -> dict[str, Any]:
    p = get_evrim_profile()
    report = build_pre_live_risk_report(p)
    news_feed: dict[str, Any] = {}
    try:
        from elite_trader.evrim_training import load_training_state

        st = load_training_state()
        news_feed = dict(st.get("radar_news_feed") or {})
    except Exception:
        pass
    return {
        "mode_id": MODE_ID,
        "unified_enabled": is_unified_enabled(p),
        "trading_mode": trading_mode(p),
        "live_trading_enabled": is_live_trading_enabled(p),
        "modules": list(MODULES),
        "risk_report": report,
        "radar_news_headline": (news_feed.get("crypto_news") or {}).get("headline"),
        "radar_news_updated": news_feed.get("updated_at"),
    }


def enable_live_trading(*, confirm: bool = False) -> dict[str, Any]:
    """Canlıyı aç — yalnızca risk raporu yeşil + confirm."""
    from elite_trader.mode_profiles import save_profile

    p = get_evrim_profile()
    report = build_pre_live_risk_report(p)
    if not confirm:
        return {
            "ok": False,
            "error": "confirm_required",
            "risk_report": report,
        }
    if not report.get("live_ready"):
        return {
            "ok": False,
            "error": "risk_report_not_ready",
            "risk_report": report,
        }
    backup_profile("pre_live_enable")
    save_profile(
        MODE_ID,
        {
            "evrim_trading_mode": "live",
            "evrim_live_trading_enabled": True,
        },
    )
    return {"ok": True, "trading_mode": "live", "risk_report": report}
