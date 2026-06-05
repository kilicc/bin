"""SL-EMERGENCY kapanışlarından öğren — riskli sembol/yönde temkinli giriş."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_REGISTRY = _ROOT / "data" / "elite_sl_emergency_registry.json"
_LESSONS = _ROOT / "data" / "elite_9005_trade_lessons.json"


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    if not _REGISTRY.is_file():
        return {"events": [], "symbol_stats": {}}
    try:
        return json.loads(_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {"events": [], "symbol_stats": {}}


def _save(data: dict[str, Any]) -> None:
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    _REGISTRY.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _ingest_event(data: dict[str, Any], row: dict[str, Any]) -> None:
    sym = str(row.get("symbol") or "").upper()
    if not sym:
        return
    side = str(row.get("side") or "LONG").upper()
    ts = row.get("ts") or _now_iso()
    events: list[dict[str, Any]] = data.setdefault("events", [])
    events.append(
        {
            "symbol": sym,
            "side": side,
            "ts": ts,
            "final_pnl": float(row.get("final_pnl") or 0),
            "stake_usd": float(row.get("stake_usd") or 0),
            "duration_sec": float(row.get("duration_sec") or 0),
            "signal_strength": row.get("signal_strength"),
        }
    )
    if len(events) > 400:
        data["events"] = events[-400:]
    stats: dict[str, Any] = data.setdefault("symbol_stats", {})
    st = stats.setdefault(sym, {"count": 0, "last_ts": ts, "sides": {}})
    st["count"] = int(st.get("count") or 0) + 1
    st["last_ts"] = ts
    sides: dict[str, int] = st.setdefault("sides", {})
    sides[side] = int(sides.get(side) or 0) + 1


def _import_lessons_file(path: Path, data: dict[str, Any], seen: set[str]) -> None:
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    for t in raw.get("trades") or []:
        ex = str(t.get("exit_reason") or "").upper()
        if "SL-EMERGENCY" not in ex:
            continue
        key = f"{t.get('id')}:{t.get('symbol')}:{ex}"
        if key in seen:
            continue
        seen.add(key)
        _ingest_event(
            data,
            {
                "symbol": t.get("symbol"),
                "side": t.get("side"),
                "final_pnl": t.get("final_pnl"),
                "stake_usd": t.get("stake_usd"),
                "ts": raw.get("updated_at"),
            },
        )


def _import_from_logs(data: dict[str, Any], seen: set[str]) -> None:
    """log satırlarından SL-EMERGENCY sembolleri (yeniden başlatma sonrası öğrenme)."""
    import re

    pat_close = re.compile(
        r"Borsa kapanış\s+(\w+USDT)\s+SL-EMERGENCY",
        re.I,
    )
    pat_pnl = re.compile(r"Closed #\d+:\s+(\w+USDT)\s+\|\s+\$([-\d.]+)")
    log_dir = _ROOT / "logs"
    if not log_dir.is_dir():
        return
    paths = sorted(log_dir.glob("binance_elite_8300_9005.log*"))
    pending_sym: str | None = None
    file_idx = 0
    for path in paths:
        file_idx += 1
        hours_ago = 6.0 + file_idx * 12.0
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in text.splitlines():
            m = pat_close.search(line)
            if m:
                pending_sym = m.group(1).upper()
                continue
            if pending_sym:
                pm = pat_pnl.search(line)
                if pm and pm.group(1).upper() == pending_sym:
                    key = f"log:{pending_sym}:{pm.group(2)}"
                    if key not in seen:
                        seen.add(key)
                        ts_old = (
                            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
                        ).isoformat()
                        _ingest_event(
                            data,
                            {
                                "symbol": pending_sym,
                                "side": "LONG",
                                "final_pnl": float(pm.group(2)),
                                "ts": ts_old,
                            },
                        )
                    pending_sym = None


def bootstrap_from_disk() -> None:
    """İlk kurulum: lessons + yedekler + loglardan SL-EMERGENCY geçmişi."""
    data = _load()
    if data.get("ban_reset_at"):
        return
    if len(data.get("events") or []) >= 12:
        return
    seen: set[str] = set()
    for ev in data.get("events") or []:
        seen.add(f"init:{ev.get('symbol')}:{ev.get('ts')}")
    _import_lessons_file(_LESSONS, data, seen)
    backup_root = _ROOT / "data" / "backups"
    if backup_root.is_dir():
        for p in sorted(backup_root.glob("**/elite_9005_trade_lessons.json")):
            _import_lessons_file(p, data, seen)
    _import_from_logs(data, seen)
    if data.get("events"):
        _save(data)


def record_sl_emergency_close(closed: dict[str, Any]) -> None:
    ex = str(closed.get("exit_reason") or "").upper()
    if "SL-EMERGENCY" not in ex:
        return
    data = _load()
    _ingest_event(
        data,
        {
            "symbol": closed.get("symbol"),
            "side": closed.get("side"),
            "final_pnl": closed.get("final_pnl"),
            "stake_usd": closed.get("stake_usd"),
            "duration_sec": closed.get("duration"),
            "signal_strength": closed.get("signal_strength"),
            "ts": _now_iso(),
        },
    )
    _save(data)
    sym = str(closed.get("symbol") or "")
    print(f"  📛 SL-EMERGENCY kayıt: {sym} — sonraki girişlerde temkin")


def _recent_events(
    data: dict[str, Any],
    *,
    symbol: str | None = None,
    side: str | None = None,
    within_hours: float,
) -> list[dict[str, Any]]:
    cutoff = time.time() - within_hours * 3600.0
    out: list[dict[str, Any]] = []
    for ev in data.get("events") or []:
        sym = str(ev.get("symbol") or "").upper()
        sd = str(ev.get("side") or "").upper()
        if symbol and sym != symbol.upper():
            continue
        if side and sd != side.upper():
            continue
        try:
            ts = datetime.fromisoformat(
                str(ev.get("ts") or "").replace("Z", "+00:00")
            ).timestamp()
        except Exception:
            ts = 0.0
        if ts >= cutoff:
            out.append(ev)
    return out


def entry_risk_check(
    symbol: str,
    side: str,
    strength: str,
    change_pct: float,
    formula_score: float,
    *,
    veto_hours: float | None = None,
    caution_hours: float | None = None,
    cooldown_min: int | None = None,
    veto_count: int | None = None,
    caution_count: int | None = None,
    skip_cautious: bool = False,
    cautious_min_strength: str = "Strong",
) -> tuple[bool, str, str]:
    """
    Dönüş: (izin, neden, tier)
    tier: ok | cautious | veto
    """
    bootstrap_from_disk()
    sym = symbol.upper()
    sd = side.upper()
    data = _load()

    veto_h = veto_hours if veto_hours is not None else _env_float(
        "ELITE_SL_EM_VETO_HOURS", 72.0
    )
    caution_h = caution_hours if caution_hours is not None else _env_float(
        "ELITE_SL_EM_CAUTION_HOURS", 24.0
    )
    cooldown_min = (
        cooldown_min
        if cooldown_min is not None
        else _env_int("ELITE_SL_EM_COOLDOWN_MIN", 50)
    )
    veto_n = (
        veto_count
        if veto_count is not None
        else _env_int("ELITE_SL_EM_VETO_COUNT", 2)
    )
    caution_n = (
        caution_count
        if caution_count is not None
        else _env_int("ELITE_SL_EM_CAUTION_COUNT", 1)
    )
    _rank = {"Weak": 1, "Medium": 2, "Strong": 3}
    min_str_rank = _rank.get(cautious_min_strength, 2)

    if veto_n <= 0:
        return True, "ok", "ok"

    recent_sym = _recent_events(data, symbol=sym, within_hours=veto_h)
    recent_pair = _recent_events(data, symbol=sym, side=sd, within_hours=caution_h)

    if len(recent_sym) >= veto_n:
        return False, f"{sym}: {len(recent_sym)} SL-EMERGENCY / {veto_h:.0f}sa", "veto"

    if recent_pair:
        last = recent_pair[-1]
        try:
            last_ts = datetime.fromisoformat(
                str(last.get("ts") or "").replace("Z", "+00:00")
            ).timestamp()
            age_min = (time.time() - last_ts) / 60.0
        except Exception:
            age_min = 999.0
        # Çok taze kayıt (log import / az önce kapandı) — sadece aynı yön veto
        if age_min < 3.0:
            return (
                False,
                f"{sym} {sd}: SL-EMERGENCY az önce kapandı",
                "veto",
            )
        if age_min < cooldown_min and len(recent_sym) >= 2:
            return (
                False,
                f"{sym} {sd}: tekrarlayan SL-EMERGENCY ({cooldown_min}dk)",
                "veto",
            )

    if len(recent_sym) >= caution_n or recent_pair:
        if skip_cautious:
            return (
                False,
                f"{sym}: SL-EMERGENCY geçmişi — mod temkinli girişi kapalı",
                "cautious",
            )
        min_edge = _env_float("ELITE_MIN_EDGE", 0.045) + _env_float(
            "ELITE_SL_EM_EXTRA_EDGE", 0.025
        )
        min_fs = _env_float("ELITE_MIN_FORMULA_SCORE", 0.52) + _env_float(
            "ELITE_SL_EM_EXTRA_FORMULA", 0.06
        )
        edge = abs(float(change_pct)) / 100.0
        edge = min(0.35, edge * 40.0)
        if _rank.get(strength, 0) < min_str_rank:
            return (
                False,
                f"{sym}: temkin — min {cautious_min_strength} (SL-EMERGENCY geçmişi)",
                "cautious",
            )
        if edge < min_edge:
            return (
                False,
                f"{sym}: temkin — edge {edge:.3f} < {min_edge:.3f}",
                "cautious",
            )
        if formula_score < min_fs:
            return (
                False,
                f"{sym}: temkin — skor {formula_score:.2f} < {min_fs:.2f}",
                "cautious",
            )
        return True, f"{sym}: temkinli giriş (SL-EMERGENCY geçmişi)", "cautious"

    return True, "ok", "ok"


def high_risk_symbols(within_hours: float = 72.0) -> list[dict[str, Any]]:
    """Panel / debug: SL-EMERGENCY yoğun semboller."""
    data = _load()
    counts: dict[str, int] = {}
    for ev in _recent_events(data, within_hours=within_hours):
        sym = str(ev.get("symbol") or "")
        counts[sym] = counts.get(sym, 0) + 1
    return [
        {"symbol": s, "sl_emergency_count": n}
        for s, n in sorted(counts.items(), key=lambda x: -x[1])
    ]


def snapshot_for_ui() -> dict[str, Any]:
    bootstrap_from_disk()
    return {
        "registry_path": str(_REGISTRY.name),
        "high_risk": high_risk_symbols(),
        "total_events": len(_load().get("events") or []),
    }
