"""MEGA P1 — sistem skor kartı (kapalı işlem + canlı önbellek, karar değiştirmez)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TR = ZoneInfo("Europe/Istanbul")

_last_report_ts = 0.0


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def report_enabled() -> bool:
    return _env_bool("MEGA_SYSTEM_REPORT_ENABLED", True)


def report_interval_sec() -> float:
    return max(300.0, _env_float("MEGA_SYSTEM_REPORT_INTERVAL_SEC", 86400.0))


def _wallet_pnl(r: dict[str, Any]) -> float:
    return float(r.get("wallet_pnl") or r.get("final_pnl") or r.get("net_pnl") or 0)


def _parse_exit_ts(r: dict[str, Any]) -> float | None:
    v = r.get("exit_time")
    if isinstance(v, (int, float)) and float(v) > 1e9:
        return float(v)
    for k in ("exit_time_iso", "exit_time_str"):
        s = str(r.get(k) or "").strip()
        if not s:
            continue
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s[:26]).timestamp()
        except ValueError:
            pass
    return None


def _closed_paths(data_dir: Path) -> list[Path]:
    hist = data_dir / "mega_live_closed_history.json"
    live = data_dir / "mega_live_closed.json"
    if hist.is_file():
        return [hist]
    if live.is_file():
        return [live]
    return []


def load_closed_rows(data_dir: Path | None = None) -> list[dict[str, Any]]:
    if data_dir is None:
        try:
            from elite_trader.mega_live import mega_instance_data_dir

            data_dir = mega_instance_data_dir()
        except Exception:
            data_dir = Path(__file__).resolve().parent.parent / "data" / "mega_9006"
    rows: list[dict[str, Any]] = []
    for p in _closed_paths(data_dir):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        part = raw if isinstance(raw, list) else list(raw.get("closed") or [])
        rows.extend(dict(r) for r in part)
    return rows


def _live_system_slice() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from elite_trader.mega_system_context import build_system_context

        snap = build_system_context("report")
        out = {
            "btc_regime": (snap.get("btc") or {}).get("regime"),
            "market_regime": (snap.get("market_regime") or {}).get("regime"),
            "hub_lag_ms": (snap.get("system") or {}).get("hub", {}).get("mark_lag_ms"),
            "reject_top": (snap.get("system") or {}).get("reject_top"),
        }
    except Exception:
        pass
    try:
        from elite_trader.mega_market_regime import snapshot as regime_snapshot

        r = regime_snapshot() or {}
        out["regime_locked"] = r.get("regime_locked")
        out["reject_mix"] = r.get("reject_mix")
    except Exception:
        pass
    return out


def analyze_closed(
    rows: list[dict[str, Any]],
    *,
    since_ts: float | None = None,
) -> dict[str, Any]:
    if since_ts:
        rows = [r for r in rows if (_parse_exit_ts(r) or 0) >= since_ts]
    n = len(rows)
    if not n:
        return {"trade_count": 0}

    wins = losses = flat = 0
    net_sum = 0.0
    phantom = 0
    flash_n = flash_loss = 0
    slip_n = slip_loss = 0
    by_reason: dict[str, list[float]] = {}

    for r in rows:
        wp = _wallet_pnl(r)
        net_sum += wp
        if wp > 0.01:
            wins += 1
        elif wp < -0.01:
            losses += 1
        else:
            flat += 1
        if r.get("phantom_slippage"):
            phantom += 1
        er = str(r.get("exit_reason") or "?")
        by_reason.setdefault(er, []).append(wp)
        if "FLASH" in er.upper() or "SPIKE" in er.upper():
            flash_n += 1
            if wp < -0.01:
                flash_loss += 1
        pre = r.get("pre_send_net")
        try:
            pre_f = float(pre) if pre is not None else None
        except (TypeError, ValueError):
            pre_f = None
        if pre_f is not None and pre_f > 1.0 and wp < -0.5:
            slip_n += 1
            slip_loss += 1

    reason_stats = []
    for reason, pnls in sorted(by_reason.items(), key=lambda x: -len(x[1]))[:8]:
        cnt = len(pnls)
        reason_stats.append(
            {
                "reason": reason,
                "count": cnt,
                "net_sum": round(sum(pnls), 2),
                "win_rate": round(100.0 * sum(1 for p in pnls if p > 0.01) / cnt, 1) if cnt else 0,
            }
        )

    return {
        "trade_count": n,
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "win_rate_pct": round(100.0 * wins / n, 1) if n else 0,
        "net_usd": round(net_sum, 2),
        "phantom_count": phantom,
        "phantom_rate_pct": round(100.0 * phantom / n, 1) if n else 0,
        "flash_trades": flash_n,
        "flash_loss_rate_pct": round(100.0 * flash_loss / flash_n, 1) if flash_n else 0,
        "pre_send_positive_then_loss": slip_n,
        "slip_loss_rate_pct": round(100.0 * slip_loss / slip_n, 1) if slip_n else 0,
        "top_exit_reasons": reason_stats,
    }


def build_report(*, window_hours: float = 24.0) -> dict[str, Any]:
    now = time.time()
    since = now - window_hours * 3600.0
    rows = load_closed_rows()
    window_rows = [r for r in rows if (_parse_exit_ts(r) or 0) >= since]
    all_stats = analyze_closed(rows)
    win_stats = analyze_closed(window_rows, since_ts=since)
    live = _live_system_slice()
    return {
        "schema": "mega_system_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": window_hours,
        "window_tr": datetime.fromtimestamp(since, tz=TR).strftime("%Y-%m-%d %H:%M"),
        "all_time": all_stats,
        "window": win_stats,
        "live": live,
    }


def format_telegram(report: dict[str, Any]) -> str:
    w = report.get("window") or {}
    a = report.get("all_time") or {}
    live = report.get("live") or {}
    lines = [
        "📊 MEGA sistem kartı",
        f"⏱ Son {int(report.get('window_hours') or 24)} saat (TR {report.get('window_tr', '?')})",
        "",
        f"Pencere: {w.get('trade_count', 0)} işlem | WR {w.get('win_rate_pct', 0)}% | "
        f"net {w.get('net_usd', 0):+.2f} USD",
        f"Phantom: {w.get('phantom_count', 0)} ({w.get('phantom_rate_pct', 0)}%) | "
        f"FLASH kayıp oranı: {w.get('flash_loss_rate_pct', 0)}%",
        f"pre_send+ sonra zarar: {w.get('pre_send_positive_then_loss', 0)}",
        "",
        f"Tüm zaman: {a.get('trade_count', 0)} işlem | WR {a.get('win_rate_pct', 0)}% | "
        f"net {a.get('net_usd', 0):+.2f} USD",
    ]
    tops = w.get("top_exit_reasons") or a.get("top_exit_reasons") or []
    if tops:
        lines.append("")
        lines.append("Çıkış (pencere):")
        for t in tops[:5]:
            lines.append(
                f"  • {t.get('reason')}: {t.get('count')}x net {t.get('net_sum'):+.1f} "
                f"WR {t.get('win_rate')}%"
            )
    if live:
        lines.extend(
            [
                "",
                f"Canlı: BTC {live.get('btc_regime') or '?'} | "
                f"rejim {live.get('market_regime') or '?'} | "
                f"hub {live.get('hub_lag_ms')}ms",
            ]
        )
        rm = live.get("reject_mix")
        if isinstance(rm, dict) and rm:
            top = sorted(rm.items(), key=lambda x: -float(x[1] or 0))[:3]
            lines.append("reject_mix: " + ", ".join(f"{k}:{v:.0%}" for k, v in top))
    return "\n".join(lines)


def write_report_json(report: dict[str, Any], data_dir: Path | None = None) -> Path:
    if data_dir is None:
        from elite_trader.mega_live import mega_instance_data_dir

        data_dir = mega_instance_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "mega_system_report_latest.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def emit_report(*, telegram: bool | None = None, window_hours: float = 24.0) -> dict[str, Any]:
    report = build_report(window_hours=window_hours)
    write_report_json(report)
    send_tg = telegram if telegram is not None else _env_bool("MEGA_SYSTEM_REPORT_TELEGRAM", True)
    if send_tg:
        try:
            from elite_trader.telegram_notify import enqueue_message, telegram_enabled

            if telegram_enabled():
                enqueue_message(format_telegram(report))
        except Exception:
            pass
    return report


def tick_scheduled_report() -> None:
    """mega_position_tick — günde bir (env ile) Telegram + JSON."""
    global _last_report_ts
    if not report_enabled():
        return
    now = time.time()
    if (now - _last_report_ts) < report_interval_sec():
        return
    _last_report_ts = now
    try:
        emit_report()
    except Exception as exc:
        print(f"  ⚠ MEGA sistem raporu: {exc}")
