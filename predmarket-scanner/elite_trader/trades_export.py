"""Tüm modlar — işlem hareketleri Excel/CSV dışa aktarım."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from elite_trader.mode_profiles import get_profile
from elite_trader.mode_registry import resolve_mode_id
from elite_trader.panel_strategy import active_execution_mode, mode_catalog, mode_order
from elite_trader.parallel_universe_engine import get_books

_EXPORT_COLUMNS = [
    ("mode_label", "Mod"),
    ("universe", "Evren ID"),
    ("status", "Durum"),
    ("id", "İşlem #"),
    ("symbol", "Sembol"),
    ("side", "Yön"),
    ("leverage", "Kaldıraç"),
    ("entry_price", "Giriş fiyat"),
    ("exit_price", "Çıkış fiyat"),
    ("current_price", "Güncel fiyat"),
    ("size", "Miktar"),
    ("stake_usd", "Stake USD"),
    ("position_value", "Pozisyon değeri"),
    ("gross_pnl", "Brüt PnL"),
    ("entry_fee", "Giriş ücret"),
    ("exit_fee", "Çıkış ücret"),
    ("total_fees", "Toplam ücret"),
    ("net_pnl", "Net PnL"),
    ("tax", "Vergi"),
    ("final_pnl", "Final PnL"),
    ("pnl_pct", "PnL %"),
    ("exit_reason", "Çıkış nedeni"),
    ("signal_source", "Sinyal kaynağı"),
    ("signal_strength", "Sinyal gücü"),
    ("edge", "Edge"),
    ("formula_score", "Formül skoru"),
    ("entry_time", "Açılış"),
    ("exit_time", "Kapanış"),
    ("max_unreal_seen", "Max unreal"),
    ("panel_mode", "Panel modu"),
]


def _fmt_time(v: Any) -> str:
    if not v:
        return ""
    s = str(v).replace("T", " ")[:19]
    return s


def _row(
    trade: dict[str, Any],
    *,
    mode_id: str,
    mode_label: str,
    status: str,
) -> dict[str, Any]:
    return {
        "mode_label": mode_label,
        "universe": mode_id,
        "status": status,
        "id": trade.get("id"),
        "symbol": trade.get("symbol"),
        "side": trade.get("side"),
        "leverage": trade.get("leverage"),
        "entry_price": trade.get("entry_price"),
        "exit_price": trade.get("exit_price"),
        "current_price": trade.get("current_price"),
        "size": trade.get("size"),
        "stake_usd": trade.get("stake_usd"),
        "position_value": trade.get("position_value"),
        "gross_pnl": trade.get("pnl_usd") if status == "closed" else trade.get("unrealized_pnl"),
        "entry_fee": trade.get("entry_fee"),
        "exit_fee": trade.get("exit_fee"),
        "total_fees": trade.get("total_fees"),
        "net_pnl": trade.get("net_pnl"),
        "tax": trade.get("tax"),
        "final_pnl": trade.get("final_pnl") if status == "closed" else trade.get("unrealized_pnl"),
        "pnl_pct": trade.get("net_pnl_pct") or trade.get("pnl_pct"),
        "exit_reason": trade.get("exit_reason") if status == "closed" else "OPEN",
        "signal_source": trade.get("signal_source"),
        "signal_strength": trade.get("signal_strength"),
        "edge": trade.get("edge"),
        "formula_score": trade.get("formula_score"),
        "entry_time": _fmt_time(
            trade.get("entry_time_str") or trade.get("entry_time") or trade.get("opened_at_iso")
        ),
        "exit_time": _fmt_time(trade.get("exit_time") if status == "closed" else ""),
        "max_unreal_seen": trade.get("max_unreal_seen"),
        "panel_mode": trade.get("panel_mode") or mode_id,
    }


def gather_all_rows(
    *,
    live_closed: list[dict[str, Any]] | None = None,
    live_open: list[dict[str, Any]] | None = None,
    scope: str = "all",
    mode_id: str | None = None,
) -> list[dict[str, Any]]:
    """Canlı motor (active_futures_mode) + paper kitaplar."""
    rows: list[dict[str, Any]] = []
    modes = mode_catalog()
    motor = active_execution_mode()
    motor_lbl = modes.get(motor, {}).get("label") or motor
    sc = (scope or "all").strip().lower()
    mid_filter = resolve_mode_id(mode_id) if mode_id else None

    if mid_filter == motor:
        sc = "live" if sc == "all" else sc
    elif mid_filter and mid_filter in mode_order():
        sc = "parallel" if sc == "all" else sc

    want_live = sc in ("all", "live", "history", "open")
    want_parallel = sc in ("all", "parallel")
    live_open_rows = live_open
    live_closed_rows = live_closed
    if sc == "history":
        want_parallel = False
        live_open_rows = []
    elif sc == "open":
        want_parallel = False
        live_closed_rows = []

    if want_live and (not mid_filter or mid_filter == motor):
        if live_open_rows is not None and sc != "history":
            for p in live_open_rows or []:
                rows.append(_row(p, mode_id=motor, mode_label=motor_lbl, status="open"))
        if live_closed_rows is not None:
            for c in live_closed_rows or []:
                rows.append(_row(c, mode_id=motor, mode_label=motor_lbl, status="closed"))

    if want_parallel:
        books = get_books()
        parallel_ids = (
            [mid_filter]
            if mid_filter and mid_filter in mode_order()
            else list(mode_order())
        )
        for mid in parallel_ids:
            if mid == motor and want_live:
                continue
            prof = get_profile(mid) or {}
            lbl = prof.get("short_label") or prof.get("label") or mid
            book = books.get(mid) or {}
            for p in book.get("open") or []:
                rows.append(_row(p, mode_id=mid, mode_label=lbl, status="open"))
            for c in book.get("closed") or []:
                rows.append(_row(c, mode_id=mid, mode_label=lbl, status="closed"))

    rows.sort(
        key=lambda r: (
            r.get("mode_label") or "",
            r.get("status") or "",
            r.get("exit_time") or r.get("entry_time") or "",
            int(r.get("id") or 0),
        )
    )
    return rows


def export_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mod özeti satırları."""
    by_mode: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = r.get("mode_label") or "?"
        if k not in by_mode:
            by_mode[k] = {"mod": k, "acik": 0, "kapali": 0, "final_sum": 0.0, "zarar": 0, "kazanc": 0}
        b = by_mode[k]
        if r.get("status") == "open":
            b["acik"] += 1
        else:
            b["kapali"] += 1
            fp = float(r.get("final_pnl") or 0)
            b["final_sum"] += fp
            if fp < 0:
                b["zarar"] += 1
            elif fp > 0:
                b["kazanc"] += 1
    out = []
    for k, b in sorted(by_mode.items()):
        out.append(
            {
                "Mod": k,
                "Açık": b["acik"],
                "Kapanan": b["kapali"],
                "Toplam Final PnL": round(b["final_sum"], 2),
                "Kazançlı": b["kazanc"],
                "Zararlı": b["zarar"],
            }
        )
    return out


def _csv_bytes(
    rows: list[dict[str, Any]],
    field_keys: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    if not rows:
        rows = [{"bilgi": "Kayıt yok"}]
        field_keys = ["bilgi"]
        headers = None
    buf = io.StringIO()
    if field_keys and headers:
        hdrs = [headers.get(k, k) for k in field_keys]
        w = csv.DictWriter(buf, fieldnames=field_keys, extrasaction="ignore")
        w.writerow(dict(zip(field_keys, hdrs)))
        for r in rows:
            w.writerow({k: r.get(k, "") for k in field_keys})
    else:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _export_slug(scope: str, mode_id: str | None) -> str:
    sc = (scope or "all").strip().lower()
    if mode_id:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in mode_id)
        return f"mod_{safe}"
    return sc


def export_trades_zip(
    rows: list[dict[str, Any]],
    *,
    scope: str = "all",
    mode_id: str | None = None,
) -> bytes:
    """CSV + özet — zip."""
    summary = export_summary(rows)
    slug = _export_slug(scope, mode_id)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    keys = [k for k, _ in _EXPORT_COLUMNS]
    hdrs = {k: v for k, v in _EXPORT_COLUMNS}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"trades_{slug}_{ts}.csv", _csv_bytes(rows, keys, hdrs))
        zf.writestr(
            f"summary_{slug}_{ts}.csv",
            _csv_bytes(summary, list(summary[0].keys()) if summary else None),
        )
        zf.writestr(
            "meta.json",
            json.dumps(
                {"scope": scope, "mode_id": mode_id, "rows": len(rows), "ts": ts},
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
    return buf.getvalue()


def build_csv_export(
    *,
    live_closed: list[dict[str, Any]] | None = None,
    live_open: list[dict[str, Any]] | None = None,
    scope: str = "all",
    mode_id: str | None = None,
) -> tuple[bytes, str]:
    rows = gather_all_rows(
        live_closed=live_closed,
        live_open=live_open,
        scope=scope,
        mode_id=mode_id,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = _export_slug(scope, mode_id)
    keys = [k for k, _ in _EXPORT_COLUMNS]
    hdrs = {k: v for k, v in _EXPORT_COLUMNS}
    return _csv_bytes(rows, keys, hdrs), f"trades_{slug}_{ts}.csv"


def build_zip_export(
    *,
    live_closed: list[dict[str, Any]] | None = None,
    live_open: list[dict[str, Any]] | None = None,
    scope: str = "all",
    mode_id: str | None = None,
) -> tuple[bytes, str]:
    rows = gather_all_rows(
        live_closed=live_closed,
        live_open=live_open,
        scope=scope,
        mode_id=mode_id,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = _export_slug(scope, mode_id)
    return export_trades_zip(rows, scope=scope, mode_id=mode_id), f"trades_{slug}_{ts}.zip"
