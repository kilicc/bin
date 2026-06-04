"""MEGA — 24h coin sıralama (stake-hacim normalize kâr), yıldız / alt 3."""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from elite_trader.mega_coin_watch import apply_rank_report
from elite_trader.mega_system_report import _parse_exit_ts, _wallet_pnl, load_closed_rows

TR = ZoneInfo("Europe/Istanbul")
_last_rank_ts = 0.0


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool = True) -> bool:
    v = os.getenv(key, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes")


def rank_enabled() -> bool:
    return _env_bool("MEGA_COIN_RANK_ENABLED", True)


def rank_interval_sec() -> float:
    return max(300.0, _env_float("MEGA_COIN_RANK_INTERVAL_SEC", 86400.0))


def rank_output_path(data_dir: Path | None = None) -> Path:
    if data_dir is None:
        try:
            from elite_trader.mega_live import mega_instance_data_dir

            data_dir = mega_instance_data_dir()
        except Exception:
            data_dir = Path(__file__).resolve().parent.parent / "data" / "mega_9006"
    return data_dir / "mega_coin_rank_24h.json"


def _entry_context_summary(row: dict[str, Any]) -> dict[str, Any]:
    ctx = row.get("entry_context") or row.get("system_context") or {}
    if not isinstance(ctx, dict):
        return {}
    btc = ctx.get("btc") if isinstance(ctx.get("btc"), dict) else {}
    mr = ctx.get("market_regime") if isinstance(ctx.get("market_regime"), dict) else {}
    return {
        "btc_regime": btc.get("regime") or btc.get("btc_regime"),
        "market_regime": mr.get("regime"),
        "flash": bool(row.get("mega_flash_reversal") or row.get("flash_reversal")),
    }


def _parse_duration_sec(row: dict[str, Any]) -> float | None:
    d = row.get("duration")
    if isinstance(d, (int, float)) and float(d) > 0:
        return float(d)
    return None


def _build_behavior_playbook(
    trades: list[dict[str, Any]],
    rank_row: dict[str, Any],
) -> dict[str, Any]:
    """
    Kârlı coin — geçmiş kapanışlardan hareket/çıkış kitabı.
    Açılışta 'nasıl davranacağımızı' netleştirmek için registry'ye yazılır.
    """
    if not trades:
        return {"label": "no_sample"}
    wins = [t for t in trades if _wallet_pnl(t) > 0.01]
    sample = wins if wins else trades
    sides = Counter(
        str(t.get("side") or "?").upper()
        for t in sample
        if str(t.get("side") or "").upper() in ("LONG", "SHORT")
    )
    preferred = sides.most_common(1)[0][0] if sides else None
    side_share = (
        round(sides[preferred] / len(sample), 3)
        if preferred and sample
        else 0.0
    )
    exit_w = Counter(
        str(t.get("exit_reason") or "?")[:28].upper() for t in sample
    )
    top_exit = exit_w.most_common(1)[0][0] if exit_w else ""
    flash_n = sum(
        1
        for t in sample
        if t.get("mega_flash_reversal")
        or t.get("flash_reversal")
        or "FLASH" in str(t.get("exit_reason") or "").upper()
    )
    regimes = Counter(
        str(_entry_context_summary(t).get("btc_regime") or "?").lower()
        for t in sample
    )
    best_regime = regimes.most_common(1)[0][0] if regimes else None
    durs = [_parse_duration_sec(t) for t in sample]
    durs = [d for d in durs if d is not None]
    avg_dur = round(sum(durs) / len(durs), 1) if durs else None
    stakes = [float(t.get("stake_usd") or 0) for t in sample if float(t.get("stake_usd") or 0) > 0]
    avg_stake = round(sum(stakes) / len(stakes), 2) if stakes else None
    return {
        "label": "profitable_coin_known",
        "profit_yield": rank_row.get("profit_yield"),
        "net_pnl": rank_row.get("net_pnl"),
        "win_rate_pct": rank_row.get("win_rate_pct"),
        "trade_sample": len(trades),
        "win_sample": len(wins),
        "preferred_side": preferred,
        "preferred_side_share": side_share,
        "typical_exit": top_exit,
        "expects_spike_or_flash_exit": any(
            k in top_exit for k in ("SPIKE", "FLASH", "TIER")
        ),
        "flash_share": round(flash_n / max(1, len(sample)), 3),
        "avg_win_duration_sec": avg_dur,
        "avg_stake_usd": avg_stake,
        "btc_regime_when_winning": best_regime,
        "note": (
            "Geçmiş kârlı hareket bilgisi — giriş yönü/çıkış beklentisi için"
        ),
    }


def _infer_star_boost(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not trades:
        return []
    reasons = Counter(str(t.get("exit_reason") or "?")[:24] for t in trades)
    sides = Counter(str(t.get("side") or "?").upper() for t in trades)
    regimes = Counter(
        (_entry_context_summary(t).get("btc_regime") or "?") for t in trades
    )
    top_reason = reasons.most_common(1)[0][0] if reasons else ""
    top_side = sides.most_common(1)[0][0] if sides else ""
    top_regime = regimes.most_common(1)[0][0] if regimes else ""
    rules: list[dict[str, Any]] = []
    if "SPIKE" in top_reason.upper() or "FLASH" in top_reason.upper():
        rules.append({"stake_mult_add": 0.05, "pattern": "spike_exit"})
    if top_side in ("LONG", "SHORT"):
        rules.append({"stake_mult_add": 0.03, "pattern": f"side_{top_side.lower()}"})
    if top_regime and top_regime != "?":
        rules.append({"min_score_delta": -2, "pattern": f"btc_{top_regime}"})
    return rules


def _infer_bottom_rules(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not trades:
        return []
    rules: list[dict[str, Any]] = []
    phantom_n = sum(1 for t in trades if t.get("phantom_slippage"))
    pre_slip = 0
    regime_mismatch = 0
    for t in trades:
        pre = t.get("pre_send_net")
        try:
            if pre is not None and float(pre) > 0.5 and _wallet_pnl(t) < -0.5:
                pre_slip += 1
        except (TypeError, ValueError):
            pass
        side = str(t.get("side") or "").upper()
        reg = (_entry_context_summary(t).get("btc_regime") or "").lower()
        if side == "LONG" and reg == "trend_down":
            regime_mismatch += 1
        if side == "SHORT" and reg == "trend_up":
            regime_mismatch += 1
    if phantom_n >= max(1, len(trades) // 2):
        rules.append({"min_score_delta": 4, "pattern": "phantom_heavy"})
    if pre_slip >= 1:
        rules.append({"min_score_delta": 3, "pattern": "pre_send_slip"})
    if regime_mismatch >= max(1, len(trades) // 2):
        rules.append({"min_score_delta": 5, "pattern": "btc_regime_mismatch"})
    if not rules:
        rules.append({"min_score_delta": 4, "pattern": "bottom_pnl"})
    return rules


def _trade_dossier(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "side": row.get("side"),
        "stake_usd": row.get("stake_usd"),
        "wallet_pnl": round(_wallet_pnl(row), 2),
        "exit_reason": row.get("exit_reason"),
        "duration": row.get("duration"),
        "context": _entry_context_summary(row),
    }


def build_coin_rank(
    rows: list[dict[str, Any]],
    *,
    window_hours: float = 24.0,
) -> dict[str, Any]:
    now = time.time()
    since = now - window_hours * 3600.0
    window_rows = [r for r in rows if (_parse_exit_ts(r) or 0) >= since]
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in window_rows:
        sym = str(r.get("symbol") or "").upper()
        if sym:
            by_sym[sym].append(r)

    total_stake_all = sum(
        float(r.get("stake_usd") or 0) for r in window_rows
    )
    ranked: list[dict[str, Any]] = []
    for sym, trades in by_sym.items():
        stakes = [float(t.get("stake_usd") or 0) for t in trades]
        pnls = [_wallet_pnl(t) for t in trades]
        total_stake = sum(stakes)
        net = sum(pnls)
        wins = sum(1 for p in pnls if p > 0.01)
        cnt = len(trades)
        profit_yield = round(net / total_stake, 6) if total_stake > 0 else 0.0
        ranked.append(
            {
                "symbol": sym,
                "trade_count": cnt,
                "total_stake_usd": round(total_stake, 2),
                "net_pnl": round(net, 2),
                "win_rate_pct": round(100.0 * wins / cnt, 1) if cnt else 0.0,
                "stake_share_pct": round(
                    100.0 * total_stake / total_stake_all, 2
                )
                if total_stake_all > 0
                else 0.0,
                "profit_yield": profit_yield,
                "avg_stake_usd": round(total_stake / cnt, 2) if cnt else 0.0,
            }
        )

    ranked.sort(key=lambda x: (-x["profit_yield"], -x["net_pnl"]))
    stars = [r["symbol"] for r in ranked[:3]]
    bottom3 = [r["symbol"] for r in ranked[-3:]] if len(ranked) >= 3 else [
        r["symbol"] for r in ranked
    ]

    star_boost: dict[str, list[dict[str, Any]]] = {}
    star_playbook: dict[str, dict[str, Any]] = {}
    star_dossiers: dict[str, list[dict[str, Any]]] = {}
    for sym in stars:
        trades = by_sym.get(sym, [])
        row = next((r for r in ranked if r["symbol"] == sym), {})
        star_boost[sym] = _infer_star_boost(trades)
        star_playbook[sym] = _build_behavior_playbook(trades, row)
        star_dossiers[sym] = [_trade_dossier(t) for t in trades[-12:]]

    bottom_rules: dict[str, list[dict[str, Any]]] = {}
    bottom_dossiers: dict[str, list[dict[str, Any]]] = {}
    for sym in bottom3:
        trades = by_sym.get(sym, [])
        bottom_rules[sym] = _infer_bottom_rules(trades)
        bottom_dossiers[sym] = [_trade_dossier(t) for t in trades[-12:]]

    return {
        "schema": "mega_coin_rank_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": window_hours,
        "window_tr": datetime.fromtimestamp(since, tz=TR).strftime("%Y-%m-%d %H:%M"),
        "trade_count": len(window_rows),
        "symbol_count": len(ranked),
        "ranked": ranked,
        "stars": stars,
        "bottom3": bottom3,
        "star_boost_by_symbol": star_boost,
        "star_playbook_by_symbol": star_playbook,
        "star_trade_dossiers": star_dossiers,
        "bottom_rules_by_symbol": bottom_rules,
        "bottom_trade_dossiers": bottom_dossiers,
    }


def emit_rank(
    *,
    window_hours: float = 24.0,
    data_dir: Path | None = None,
    write_registry: bool = True,
) -> dict[str, Any]:
    rows = load_closed_rows(data_dir)
    report = build_coin_rank(rows, window_hours=window_hours)
    path = rank_output_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if write_registry:
        apply_rank_report(report, data_dir)
    return report


def format_telegram_rank(report: dict[str, Any]) -> str:
    lines = [
        "⭐ MEGA 24h coin sıralama",
        f"⏱ {report.get('window_tr', '?')} — {report.get('trade_count', 0)} işlem",
        "",
    ]
    for sym in report.get("stars") or []:
        row = next(
            (r for r in report.get("ranked") or [] if r.get("symbol") == sym),
            {},
        )
        pb = (report.get("star_playbook_by_symbol") or {}).get(sym) or {}
        lines.append(
            f"★ {sym}: yield {row.get('profit_yield', 0):.4f} | "
            f"net {row.get('net_pnl', 0):+.2f} | WR {row.get('win_rate_pct', 0)}%"
        )
        if pb.get("preferred_side"):
            lines.append(
                f"   kitap: {pb.get('preferred_side')} "
                f"({int(float(pb.get('preferred_side_share') or 0) * 100)}%) | "
                f"çıkış {pb.get('typical_exit', '?')[:20]} | "
                f"rejim {pb.get('btc_regime_when_winning', '?')}"
            )
    lines.append("")
    lines.append("Alt 3:")
    for sym in report.get("bottom3") or []:
        row = next(
            (r for r in report.get("ranked") or [] if r.get("symbol") == sym),
            {},
        )
        lines.append(
            f"  {sym}: yield {row.get('profit_yield', 0):.4f} | "
            f"net {row.get('net_pnl', 0):+.2f} | WR {row.get('win_rate_pct', 0)}%"
        )
    return "\n".join(lines)


def tick_coin_rank() -> dict[str, Any] | None:
    global _last_rank_ts
    if not rank_enabled():
        return None
    now = time.time()
    if now - _last_rank_ts < rank_interval_sec():
        return None
    _last_rank_ts = now
    report = emit_rank()
    if _env_bool("MEGA_COIN_RANK_TELEGRAM", True):
        try:
            from elite_trader.telegram_notify import send_telegram_message

            send_telegram_message(format_telegram_rank(report))
        except Exception:
            pass
    return report
