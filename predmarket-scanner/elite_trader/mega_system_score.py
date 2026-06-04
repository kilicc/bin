"""MEGA P2 — canlı system_score + giriş kapısı (ölçüme dayalı)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_history_cache: dict[str, Any] | None = None
_history_cache_ts = 0.0


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def gate_enabled() -> bool:
    return _env_bool("MEGA_SYSTEM_SCORE_GATE", False)


def monitor_only() -> bool:
    """Kapı kapalıyken skor logla."""
    return _env_bool("MEGA_SYSTEM_SCORE_MONITOR", True)


def min_score() -> float:
    return max(0.0, min(100.0, _env_float("MEGA_SYSTEM_SCORE_MIN", 48.0)))


def flash_bypass() -> bool:
    return _env_bool("MEGA_SYSTEM_SCORE_FLASH_BYPASS", True)


def _is_flash_signal(signal: dict[str, Any]) -> bool:
    return bool(
        signal.get("mega_flash_reversal")
        or signal.get("flash_reversal")
        or signal.get("mega_flash_pump")
        or signal.get("flash_pump_reversal")
        or "FLASH" in str(signal.get("exit_reason") or "").upper()
    )


def _wallet_pnl(r: dict[str, Any]) -> float:
    return float(r.get("wallet_pnl") or r.get("final_pnl") or r.get("net_pnl") or 0)


def load_history_baseline(data_dir: Path | None = None) -> dict[str, Any]:
    global _history_cache, _history_cache_ts
    ttl = max(60.0, _env_float("MEGA_SYSTEM_SCORE_HISTORY_CACHE_SEC", 600.0))
    now = time.time()
    if _history_cache and (now - _history_cache_ts) < ttl:
        return _history_cache
    if data_dir is None:
        try:
            from elite_trader.mega_live import mega_instance_data_dir

            data_dir = mega_instance_data_dir()
        except Exception:
            data_dir = Path(__file__).resolve().parent.parent / "data" / "mega_9006"
    rows: list[dict[str, Any]] = []
    for name in ("mega_live_closed_history.json", "mega_live_closed.json"):
        p = data_dir / name
        if not p.is_file():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            rows.extend(raw if isinstance(raw, list) else list(raw.get("closed") or []))
        except (OSError, json.JSONDecodeError):
            continue
    n = len(rows)
    flash_n = flash_loss = phantom = slip_bad = 0
    wins = 0
    for r in rows:
        wp = _wallet_pnl(r)
        if wp > 0.01:
            wins += 1
        if r.get("phantom_slippage"):
            phantom += 1
        er = str(r.get("exit_reason") or "")
        if "FLASH" in er.upper() or "SPIKE" in er.upper():
            flash_n += 1
            if wp < -0.01:
                flash_loss += 1
        try:
            pre = float(r.get("pre_send_net") or 0)
        except (TypeError, ValueError):
            pre = 0.0
        if pre > 1.0 and wp < -0.5:
            slip_bad += 1
    baseline = {
        "trade_count": n,
        "win_rate_pct": round(100.0 * wins / n, 1) if n else 50.0,
        "flash_loss_rate_pct": round(100.0 * flash_loss / flash_n, 1) if flash_n else 0.0,
        "phantom_rate_pct": round(100.0 * phantom / n, 1) if n else 0.0,
        "slip_bad_count": slip_bad,
    }
    _history_cache = baseline
    _history_cache_ts = now
    return baseline


def compute_live_score(
    signal: dict[str, Any] | None = None,
    *,
    baseline: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    """0–100; yüksek = sistem sağlıklı, giriş uygun."""
    score = 100.0
    parts: dict[str, Any] = {}
    bl = baseline or load_history_baseline()

    try:
        from elite_trader.mega_system_context import build_system_context

        snap = build_system_context("entry", signal=signal)
    except Exception:
        snap = {}

    hub = (snap.get("system") or {}).get("hub") or {}
    lag = hub.get("mark_lag_ms")
    if lag is not None:
        lag_f = float(lag)
        if lag_f > 1500:
            score -= 28
            parts["hub_lag"] = "critical"
        elif lag_f > 800:
            score -= 14
            parts["hub_lag"] = "high"
        elif lag_f > 400:
            score -= 6
            parts["hub_lag"] = "elevated"

    btc = snap.get("btc") or {}
    age = btc.get("context_age_sec")
    if age is not None and float(age) > 90:
        score -= 18
        parts["btc_stale"] = age
    regime = str(btc.get("regime") or "")
    if regime in ("unknown", ""):
        score -= 22
        parts["btc_regime"] = "unknown"

    mr = snap.get("market_regime") or {}
    if mr.get("transition_active"):
        score -= 8
        parts["regime_transition"] = True
    rmix = mr.get("reject_mix")
    if isinstance(rmix, dict) and rmix:
        top_share = max(float(v or 0) for v in rmix.values())
        if top_share > 0.45:
            score -= 12
            parts["reject_mix_high"] = round(top_share, 3)

    rejects = (snap.get("system") or {}).get("reject_top") or []
    if isinstance(rejects, list) and rejects:
        top = rejects[0] if rejects else {}
        reason = str(top.get("reason") or "")
        share = float(top.get("share") or 0)
        if share > 0.35 and "btc" in reason.lower():
            score -= 10
            parts["reject_btc_block"] = share

    if signal and _is_flash_signal(signal):
        flr = float(bl.get("flash_loss_rate_pct") or 0)
        if flr >= 55.0 and bl.get("trade_count", 0) >= 15:
            score -= 15
            parts["history_flash_loss_rate"] = flr
        if not flash_bypass():
            pass
    elif bl.get("win_rate_pct", 50) < 40 and bl.get("trade_count", 0) >= 30:
        score -= 5
        parts["history_low_wr"] = bl.get("win_rate_pct")

    if bl.get("phantom_rate_pct", 0) >= 8 and bl.get("trade_count", 0) >= 20:
        score -= 8
        parts["history_phantom_rate"] = bl.get("phantom_rate_pct")

    score = max(0.0, min(100.0, round(score, 1)))
    parts["baseline_trades"] = bl.get("trade_count")
    return score, parts


def mega_system_entry_allowed(
    signal: dict[str, Any],
) -> tuple[bool, str, float]:
    """
    P2 giriş kapısı. GATE=0 iken her zaman True (monitor log opsiyonel).
    """
    score, detail = compute_live_score(signal)
    if flash_bypass() and _is_flash_signal(signal):
        return True, "", score
    if not gate_enabled():
        if monitor_only() and score < min_score():
            return True, f"system_score_low_{score:.0f}", score
        return True, "", score
    if score < min_score():
        top = ",".join(f"{k}" for k in list(detail.keys())[:4])
        return False, f"system_score_{score:.0f}<{min_score():.0f}:{top}", score
    return True, "", score
