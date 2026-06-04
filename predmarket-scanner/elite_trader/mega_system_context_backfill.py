"""P0 retro — kapalı işlem + audit'ten entry/exit_context (anlık BTC/rejim yok)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_ts_iso(s: str | None) -> float | None:
    if not s:
        return None
    s = str(s).strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def closed_entry_ts(row: dict[str, Any]) -> float | None:
    for k in ("opened_at_iso", "entry_time_str", "entry_time"):
        if k == "entry_time" and isinstance(row.get(k), (int, float)):
            v = float(row[k])
            return v if v > 1e9 else None
        ts = _parse_ts_iso(row.get(k) if k != "entry_time" else str(row.get(k) or ""))
        if ts:
            return ts
    return None


def closed_exit_ts(row: dict[str, Any]) -> float | None:
    v = row.get("exit_time")
    if isinstance(v, (int, float)) and float(v) > 1e9:
        return float(v)
    for k in ("exit_time_iso", "exit_time_str"):
        ts = _parse_ts_iso(row.get(k))
        if ts:
            return ts
    return None


def closed_dedupe_key(row: dict[str, Any]) -> str:
    oid = str(row.get("exchange_close_order_id") or "").strip()
    if oid:
        return f"oid:{oid}"
    pid = int(row.get("id") or 0)
    if pid > 0:
        return f"pos:{pid}"
    sym = str(row.get("symbol") or "")
    side = str(row.get("side") or "").upper()
    net = round(float(row.get("final_pnl") or row.get("net_pnl") or row.get("wallet_pnl") or 0), 2)
    entry = round(float(row.get("entry_price") or 0), 4)
    exit_px = round(float(row.get("exit_price") or 0), 4)
    exit_ts = closed_exit_ts(row) or 0.0
    exit_bucket = int(exit_ts // 60) if exit_ts else 0
    return f"trade:{sym}|{side}|{entry}|{exit_px}|{net}|{exit_bucket}"


@dataclass
class AuditBundle:
    position_id: int
    pre_send_ok: dict[str, Any] | None = None
    close_recorded: dict[str, Any] | None = None
    last_attempt: dict[str, Any] | None = None
    attempt_count: int = 0


def load_audit_index(audit_path: Path) -> dict[int, AuditBundle]:
    out: dict[int, AuditBundle] = {}
    if not audit_path.is_file():
        return out
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        pid = int(ev.get("position_id") or 0)
        if pid <= 0:
            continue
        b = out.setdefault(pid, AuditBundle(position_id=pid))
        et = str(ev.get("event") or "")
        if et == "close_attempt":
            b.attempt_count += 1
            b.last_attempt = ev
        elif et == "close_pre_send_ok":
            b.pre_send_ok = ev
        elif et == "close_recorded":
            b.close_recorded = ev
    return out


def _flash_from_row(row: dict[str, Any]) -> bool:
    er = str(row.get("exit_reason") or "").upper()
    return "FLASH" in er or "SPIKE" in er


def _signal_from_closed(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "strength": row.get("signal_strength"),
        "flash": _flash_from_row(row),
        "elite": bool(row.get("mega_elite_entry")),
        "signal_source": row.get("signal_source"),
    }


def _position_from_closed(row: dict[str, Any], audit: AuditBundle | None) -> dict[str, Any]:
    pre_net = row.get("pre_send_net")
    pre_gross = row.get("pre_send_gross")
    if audit and audit.pre_send_ok:
        pre_net = audit.pre_send_ok.get("pre_send_net", pre_net)
        pre_gross = audit.pre_send_ok.get("pre_send_gross", pre_gross)
    return {
        "id": row.get("id"),
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "stake_usd": row.get("stake_usd"),
        "leverage": row.get("leverage"),
        "entry_price": row.get("entry_price"),
        "pre_send_net": pre_net,
        "pre_send_gross": pre_gross,
        "max_unreal_seen": row.get("max_unreal_seen"),
        "min_unreal_seen": row.get("min_unreal_seen"),
        "phantom_slippage": row.get("phantom_slippage"),
        "phantom_detail": row.get("phantom_detail"),
        "panel_hide": row.get("panel_hide"),
    }


def _exec_from_closed(row: dict[str, Any], audit: AuditBundle | None) -> dict[str, Any]:
    rec = audit.close_recorded if audit else None
    settlement = (rec or {}).get("settlement") if rec else None
    if not isinstance(settlement, dict):
        settlement = row.get("settlement_detail") if isinstance(row.get("settlement_detail"), dict) else {}
    return {
        "pre_send_net": row.get("pre_send_net"),
        "pre_send_gross": row.get("pre_send_gross"),
        "wallet_pnl": row.get("wallet_pnl") or row.get("final_pnl") or row.get("net_pnl"),
        "pnl_gross": row.get("pnl_gross_usd") or row.get("pnl_usd"),
        "phantom_slippage": row.get("phantom_slippage"),
        "close_order_id": row.get("exchange_close_order_id"),
        "close_attempts": audit.attempt_count if audit else None,
        "settlement_wallet_pnl": settlement.get("wallet_pnl") if settlement else None,
    }


def _ts_block(epoch: float | None, phase: str) -> dict[str, Any]:
    if not epoch:
        return {}
    return {
        "ts": epoch,
        "ts_iso": datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase": phase,
    }


def build_retro_context(
    phase: str,
    closed: dict[str, Any],
    *,
    audit: AuditBundle | None = None,
) -> dict[str, Any]:
    """Anlık btc/rejim yok; kapalı satır + audit ile P2 için yeterli kısmi bağlam."""
    phase = str(phase or "unknown")
    entry_ts = closed_entry_ts(closed)
    exit_ts = closed_exit_ts(closed)
    epoch = entry_ts if phase == "entry" else exit_ts
    quality = "audit_enriched" if audit and (audit.pre_send_ok or audit.close_recorded) else "closed_only"
    close_exec = closed.get("close_execution") if isinstance(closed.get("close_execution"), dict) else {}
    return {
        "schema": "mega_system_context_v1",
        "backfill": True,
        "backfill_quality": quality,
        "backfill_sources": ["mega_live_closed"]
        + (["mega_close_audit"] if audit else []),
        "backfill_note": "retro: btc/market_regime/hub/reject_top o anki değil; P2 korelasyon için signal+exec+audit",
        **_ts_block(epoch, phase),
        "signal": _signal_from_closed(closed),
        "btc": None,
        "market_regime": None,
        "system": {
            "reject_top": None,
            "hub": None,
            "motor": None,
            "close_execution_src": close_exec.get("signal_book", {}).get("src")
            if isinstance(close_exec.get("signal_book"), dict)
            else close_exec.get("src"),
        },
        "position": _position_from_closed(closed, audit),
        "exec": _exec_from_closed(closed, audit),
        **({"exit_reason": str(closed.get("exit_reason") or "")[:48]} if phase == "exit" else {}),
    }


def enrich_closed_row(
    row: dict[str, Any],
    audit_by_pid: dict[int, AuditBundle],
    *,
    force: bool = False,
) -> bool:
    """entry_context / exit_context ekle; zaten varsa atla (force hariç)."""
    changed = False
    pid = int(row.get("id") or 0)
    audit = audit_by_pid.get(pid) if pid > 0 else None
    if force or not row.get("entry_context"):
        row["entry_context"] = build_retro_context("entry", row, audit=audit)
        row["entry_context_ts"] = row["entry_context"].get("ts")
        changed = True
    if force or not row.get("exit_context"):
        row["exit_context"] = build_retro_context("exit", row, audit=audit)
        row["exit_context_ts"] = row["exit_context"].get("ts")
        changed = True
    return changed


def load_closed_payload(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {"closed": raw}, raw
    rows = [dict(r) for r in (raw.get("closed") or [])]
    return raw, rows


def save_closed_payload(path: Path, wrapper: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    wrapper = dict(wrapper)
    wrapper["closed"] = rows
    wrapper["updated_at"] = datetime.now(timezone.utc).isoformat()
    text = json.dumps(wrapper, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def merge_closed_unique(sources: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for rows in sources:
        for r in rows:
            k = closed_dedupe_key(r)
            prev = by_key.get(k)
            if not prev:
                by_key[k] = dict(r)
                continue
            for field in (
                "pre_send_net",
                "pre_send_gross",
                "max_unreal_seen",
                "phantom_slippage",
                "phantom_detail",
                "close_execution",
                "wallet_pnl",
            ):
                if prev.get(field) is None and r.get(field) is not None:
                    prev[field] = r.get(field)
    return sorted(by_key.values(), key=lambda x: closed_exit_ts(x) or 0.0)


def backfill_audit_file(
    audit_path: Path,
    closed_rows: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """close_recorded / close_pre_send_ok satırlarına retro system_context."""
    by_pid = {int(r.get("id") or 0): r for r in closed_rows if int(r.get("id") or 0) > 0}
    stats = {"lines": 0, "patched": 0, "skipped": 0}
    if not audit_path.is_file():
        return stats
    lines_out: list[str] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        stats["lines"] += 1
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            lines_out.append(line)
            continue
        sc = ev.get("system_context")
        if isinstance(sc, dict) and sc.get("schema") and not sc.get("backfill"):
            lines_out.append(line)
            stats["skipped"] += 1
            continue
        et = str(ev.get("event") or "")
        if et not in ("close_recorded", "close_pre_send_ok", "close_attempt"):
            lines_out.append(json.dumps(ev, ensure_ascii=False, default=str))
            continue
        pid = int(ev.get("position_id") or 0)
        closed = by_pid.get(pid)
        if not closed:
            lines_out.append(json.dumps(ev, ensure_ascii=False, default=str))
            stats["skipped"] += 1
            continue
        phase = "exit" if et == "close_recorded" else "close_attempt"
        audit = AuditBundle(position_id=pid)
        if et == "close_pre_send_ok":
            audit.pre_send_ok = ev
        if et == "close_recorded":
            audit.close_recorded = ev
        ctx = build_retro_context(phase, closed, audit=audit)
        ev["system_context"] = ctx
        lines_out.append(json.dumps(ev, ensure_ascii=False, default=str))
        stats["patched"] += 1
    if not dry_run and stats["patched"] > 0:
        bak = audit_path.with_suffix(".jsonl.bak_backfill")
        if not bak.is_file():
            audit_path.rename(bak)
        audit_path.write_text("\n".join(lines_out) + ("\n" if lines_out else ""), encoding="utf-8")
    return stats


def find_archive_closed_files(data_root: Path, instance: str) -> list[Path]:
    arch = data_root / "deleted_archives"
    if not arch.is_dir():
        return []
    pat = re.compile(rf"mega_{re.escape(instance)}", re.I)
    found: list[Path] = []
    for p in arch.rglob("mega_live_closed.json"):
        if pat.search(str(p.parent)) or pat.search(p.parent.name):
            found.append(p)
    return sorted(found, key=lambda p: p.stat().st_mtime)
