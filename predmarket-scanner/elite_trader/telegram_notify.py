"""MEGA — Telegram grup bildirimleri (açık pozisyon, kapanış, sistem durumu)."""
from __future__ import annotations

import html
import json
import os
import queue
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_send_q: queue.Queue[tuple[str | None, str, str]] = queue.Queue(maxsize=500)
_worker: threading.Thread | None = None
_worker_stop = threading.Event()
_last_send_ts = 0.0
_open_digest_ts = 0.0
_last_open_sig = ""
_close_notify_seen: dict[str, float] = {}


def _close_notify_persist_path() -> Path:
    from elite_trader.mega_live import mega_instance_data_dir

    return mega_instance_data_dir() / "telegram_close_notify.json"


def _load_close_notify_persisted() -> None:
    global _close_notify_seen
    path = _close_notify_persist_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("keys") if isinstance(data, dict) else data
        if not isinstance(raw, dict):
            return
        now = time.time()
        ttl = max(30.0, _env_float("MEGA_TELEGRAM_CLOSE_DEDUPE_SEC", 86400 * 14))
        for key, ts in raw.items():
            try:
                t = float(ts)
            except (TypeError, ValueError):
                continue
            if now - t < ttl:
                _close_notify_seen[str(key)] = t
    except Exception:
        pass


def _persist_close_notify_key(key: str) -> None:
    if not key:
        return
    path = _close_notify_persist_path()
    try:
        data: dict[str, Any] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        keys = data.get("keys") if isinstance(data, dict) else {}
        if not isinstance(keys, dict):
            keys = {}
        keys[key] = time.time()
        if len(keys) > 600:
            cutoff = time.time() - max(
                3600.0, _env_float("MEGA_TELEGRAM_CLOSE_DEDUPE_SEC", 86400 * 14)
            )
            keys = {k: t for k, t in keys.items() if float(t) >= cutoff}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"keys": keys, "updated_at": time.time()}, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _should_telegram_notify_close(closed: dict[str, Any]) -> bool:
    """Yalnızca bot kapanışı — sync/backfill ve borsa reconcile spam yok."""
    if _env_bool("MEGA_TELEGRAM_NOTIFY_ALL_CLOSES", False):
        return True
    try:
        from elite_trader.mega_live import _is_sync_backfill_close

        if _is_sync_backfill_close(closed):
            return _env_bool("MEGA_TELEGRAM_NOTIFY_SYNC_CLOSE", False)
    except Exception:
        pass
    reason = str(closed.get("exit_reason") or "").upper()
    if reason in ("EXCHANGE-MANUAL", "EXCHANGE-SYNC", "VANISHED"):
        return _env_bool("MEGA_TELEGRAM_NOTIFY_SYNC_CLOSE", False)
    return str(closed.get("close_initiator") or "bot").lower() == "bot"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def telegram_enabled() -> bool:
    if not _env_bool("MEGA_TELEGRAM_ENABLED", False) and not _env_bool(
        "TELEGRAM_NOTIFY_ENABLED", False
    ):
        return False
    if _env_bool("MEGA_TELEGRAM_GCP_ONLY", True) and not (
        os.getenv("MEGA_TELEGRAM_SOURCE", "").strip()
    ):
        return False
    return bool(_bot_token() and _chat_id())


def _bot_token() -> str:
    return (
        os.getenv("MEGA_TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )


def _chat_id() -> str:
    return (
        os.getenv("MEGA_TELEGRAM_CHAT_ID", "").strip()
        or os.getenv("TELEGRAM_CHAT_ID", "").strip()
    )


def _closes_chat_ids() -> list[str]:
    """Yalnızca kapanış logu — MEGA_TELEGRAM_CLOSES_CHAT_ID (virgülle çoklu)."""
    raw = (
        os.getenv("MEGA_TELEGRAM_CLOSES_CHAT_ID", "").strip()
        or os.getenv("TELEGRAM_CLOSES_CHAT_ID", "").strip()
    )
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _instance_label() -> str:
    return os.getenv("MEGA_INSTANCE_ID", "9006").strip() or "9006"


def _min_send_gap_sec() -> float:
    return max(0.35, _env_float("MEGA_TELEGRAM_MIN_GAP_SEC", 1.2))


def _esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""), quote=False)


def _fmt_usd(v: Any, *, signed: bool = False) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if signed and x > 0:
        return f"+${x:,.2f}"
    if signed:
        return f"${x:,.2f}"
    return f"${x:,.2f}"


def _fmt_px(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.6f}".rstrip("0").rstrip(".")


def _fmt_pct(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{x:+.2f}%" if abs(x) >= 0.01 else f"{x:+.4f}%"


_DIV = "────────────────"


def _instance_tag() -> str:
    host = (
        os.getenv("MEGA_TELEGRAM_SOURCE", "").strip()
        or os.getenv("HOSTNAME", "").strip()
    )
    if host:
        return f"MEGA {_esc(_instance_label())} · {_esc(host)}"
    return f"MEGA {_esc(_instance_label())}"


def _tr_tz() -> ZoneInfo:
    name = (
        os.getenv("MEGA_TELEGRAM_TZ", "Europe/Istanbul").strip()
        or "Europe/Istanbul"
    )
    return ZoneInfo(name)


def _parse_dt_utc(raw: str) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        if "T" in s:
            dt = datetime.fromisoformat(s)
        else:
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _dt_to_tr_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tr_tz()).strftime("%d.%m.%Y %H:%M") + " TR"


def _fmt_tr_from_ts(ts: float | None) -> str | None:
    if ts is None or ts <= 0:
        return None
    return _dt_to_tr_str(datetime.fromtimestamp(float(ts), tz=timezone.utc))


def _fmt_tr_from_str(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        return _fmt_tr_from_ts(ts) if ts > 0 else None
    s = str(raw).strip()
    if re.match(r"^\d+(\.\d+)?$", s):
        try:
            ts = float(s)
            if ts > 1e12:
                ts /= 1000.0
            return _fmt_tr_from_ts(ts) if ts > 0 else None
        except (TypeError, ValueError):
            return None
    dt = _parse_dt_utc(s)
    return _dt_to_tr_str(dt) if dt else None


def _fmt_position_open_tr(pos: dict[str, Any]) -> str:
    try:
        from elite_trader.mega_live import mega_position_open_ts

        ts = mega_position_open_ts(pos)
        if ts:
            tr = _fmt_tr_from_ts(ts)
            if tr:
                return tr
    except Exception:
        pass
    for key in ("entry_time", "opened_at_iso", "entry_time_str", "entry_time_iso"):
        tr = _fmt_tr_from_str(pos.get(key))
        if tr:
            return tr
    return "—"


def _now_footer(ts: str | None = None) -> str:
    if ts:
        tr = _fmt_tr_from_str(ts)
        if tr:
            return f"<i>{_esc(tr)}</i>"
    return f"<i>{_esc(_dt_to_tr_str(datetime.now(_tr_tz())))}</i>"


def _symbol_short(symbol: Any) -> str:
    s = str(symbol or "").upper().strip()
    if s.endswith("USDT"):
        return s[:-4]
    return s or "—"


def _side_label(side: Any) -> str:
    s = str(side or "").upper()
    if s in ("LONG", "BUY"):
        return "LONG"
    if s in ("SHORT", "SELL"):
        return "SHORT"
    return _esc(side or "—")


def _pnl_icon(net: float) -> str:
    if net > 0.05:
        return "✅"
    if net < -0.05:
        return "🔴"
    return "⚪"


def _duration_human(sec: Any) -> str:
    try:
        s = float(sec)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        return ""
    if s < 90:
        return f"{int(s)} sn"
    m, r = divmod(int(s), 60)
    if m < 90:
        return f"{m} dk {r} sn" if r else f"{m} dk"
    h, r = divmod(m, 60)
    return f"{h} sa {r} dk" if r else f"{h} sa"


def _reason_human(reason: Any) -> str:
    raw = str(reason or "").strip() or "CLOSE"
    key = raw.upper()
    labels: dict[str, str] = {
        "SPIKE-FLASH": "Flash spike — kâr kilidi",
        "SPIKE": "Spike — hızlı kâr kilidi",
        "MEGA-SPIKE": "MEGA spike çıkışı",
        "TIER-5": "Kademeli kilit (+$5 net)",
        "TIER-10": "Kademeli kilit (+$10 net)",
        "TIER-20": "Kademeli kilit (+$20 net)",
        "TP": "Take-profit",
        "TP-NET": "Net take-profit",
        "TRAIL": "İz süren kilit",
        "TRAIL-LOCK": "İz süren kilit",
        "EXCHANGE-TP": "Borsa TP",
        "EXCHANGE-TRAIL": "Borsa iz süren",
        "MANUAL": "Manuel kapanış",
        "SYNC": "Borsa senkron",
        "VANISHED": "Pozisyon borsada kapandı",
        "STOP": "Stop-loss",
        "SL": "Stop-loss",
        "TIMEOUT": "Zaman aşımı",
        "MOMENTUM-FADE": "Momentum zayıflaması",
    }
    if key in labels:
        return labels[key]
    if key.startswith("TIER-"):
        return f"Kademeli kilit ({raw})"
    return raw


def _source_human(src: Any) -> str:
    raw = str(src or "MEGA").strip()
    key = raw.lower().replace("-", "_")
    labels: dict[str, str] = {
        "mega": "MEGA elite",
        "mega_elite": "MEGA elite",
        "mega_flash_reversal": "Flash reversal",
        "mega_flash": "Flash reversal",
        "berserk2": "Berserk2",
        "berserk2_flash": "Flash reversal",
    }
    return labels.get(key, raw)


def _mode_human(on_exchange: Any) -> str:
    return "Canlı (borsa)" if on_exchange else "Simülasyon"


def _headline(emoji: str, title: str) -> str:
    return f"{emoji} <b>{_esc(title)}</b>\n<code>{_instance_tag()}</code>"


def _line(label: str, value: str, *, bold_value: bool = False) -> str:
    val = f"<b>{value}</b>" if bold_value else value
    return f"{_esc(label)} · {val}"


def _bool_icon(ok: Any) -> str:
    if ok is True or str(ok).lower() in ("true", "ok", "healthy", "connected", "1", "yes"):
        return "✅"
    if ok is False or str(ok).lower() in ("false", "error", "down", "0", "no"):
        return "🔴"
    return "⚪"


def enqueue_message(
    text: str,
    *,
    parse_mode: str = "HTML",
    chat_id: str | None = None,
) -> None:
    if not telegram_enabled() or not text.strip():
        return
    try:
        _send_q.put_nowait((chat_id, parse_mode, text.strip()))
    except queue.Full:
        print("  ⚠ Telegram kuyruk dolu — mesaj atlandı")


def _send_telegram_now(
    text: str,
    parse_mode: str,
    *,
    chat_id: str | None = None,
) -> bool:
    token = _bot_token()
    chat = str(chat_id or _chat_id() or "").strip()
    if not token or not chat:
        return False
    try:
        import urllib.parse
        import urllib.request

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        body = urllib.parse.urlencode(
            {
                "chat_id": chat,
                "text": text[:4090],
                "parse_mode": parse_mode,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            return 200 <= int(resp.status) < 300
    except Exception as exc:
        print(f"  ⚠ Telegram gönderim: {exc}")
        return False


def _worker_loop() -> None:
    global _last_send_ts
    while not _worker_stop.is_set():
        try:
            reply_chat, parse_mode, text = _send_q.get(timeout=1.0)
        except queue.Empty:
            continue
        gap = _min_send_gap_sec()
        wait = gap - (time.time() - _last_send_ts)
        if wait > 0:
            time.sleep(wait)
        if _send_telegram_now(text, parse_mode, chat_id=reply_chat):
            _last_send_ts = time.time()
        _send_q.task_done()


def seed_close_notify_dedupe_from_disk() -> None:
    """Restart/deploy — geçmiş kapanışları tekrar Telegram'a gönderme."""
    try:
        from elite_trader.mega_live import (
            _closed_dedupe_key,
            _ensure_mega_closed_loaded,
            _mega_closed,
        )

        _ensure_mega_closed_loaded()
        for row in _mega_closed or []:
            key = _closed_dedupe_key(row)
            if key:
                _close_notify_seen[key] = time.time()
                _persist_close_notify_key(key)
    except Exception:
        pass


def start_telegram_notifier() -> None:
    global _worker
    if not telegram_enabled():
        return
    if _worker and _worker.is_alive():
        return
    _worker_stop.clear()
    _load_close_notify_persisted()
    seed_close_notify_dedupe_from_disk()
    _worker = threading.Thread(
        target=_worker_loop, name="mega-telegram", daemon=True
    )
    _worker.start()
    _register_bot_commands()
    enqueue_message(
        "\n".join(
            [
                _headline("🟢", "Bildirimler aktif"),
                _DIV,
                _line("Komutlar", "/yardim · /durum · /pozisyon"),
                _now_footer(),
            ]
        )
    )


def stop_telegram_notifier() -> None:
    _worker_stop.set()
    if _worker and _worker.is_alive():
        _worker.join(timeout=2.0)


def notify_position_opened(pos: dict[str, Any]) -> None:
    try:
        from elite_trader.mega_live import enrich_mega_positions_open_times

        enrich_mega_positions_open_times([pos])
    except Exception:
        pass
    sym = _symbol_short(pos.get("symbol"))
    side = _side_label(pos.get("side"))
    entry = float(pos.get("entry_price") or 0)
    stake = float(pos.get("stake_usd") or 0)
    lev = int(pos.get("leverage") or 0)
    tp_g = float(pos.get("tp_target_usd") or 0)
    tp_n = float(pos.get("tp_net_target_usd") or 0)
    src = _esc(_source_human(pos.get("signal_source")))
    mode = _esc(_mode_human(pos.get("on_exchange")))
    oid = pos.get("order_id") or pos.get("exchange_order_id")
    lines = [
        _headline("🟢", "Yeni pozisyon"),
        f"<b>{_esc(sym)}</b> · {side}",
        _DIV,
        _line("Mod", mode),
        _line("Kaynak", src),
        _line("Giriş", f"<code>{_fmt_px(entry)}</code>"),
        _line("Boyut", f"{_fmt_usd(stake)} · <b>{lev}x</b>", bold_value=False),
    ]
    if tp_g > 0 or tp_n > 0:
        lines.append(
            _line(
                "Hedef",
                f"brüt {_fmt_usd(tp_g)} · net {_fmt_usd(tp_n)}",
            )
        )
    lines.extend(
        [
            _line("Pozisyon", f"<code>#{_esc(pos.get('id'))}</code>"),
        ]
    )
    if oid:
        lines.append(_line("Emir", f"<code>{_esc(oid)}</code>"))
    open_tr = _fmt_position_open_tr(pos)
    if open_tr != "—":
        lines.append(_line("Açılış", f"<code>{_esc(open_tr)}</code>"))
    lines.append(_now_footer())
    enqueue_message("\n".join(lines))


def _closed_pnl_fields(closed: dict[str, Any]) -> dict[str, Any]:
    gross = float(closed.get("pnl_gross_usd") or closed.get("pnl_usd") or 0)
    net = float(
        closed.get("wallet_pnl")
        or closed.get("net_pnl")
        or closed.get("final_pnl")
        or 0
    )
    stake = float(closed.get("stake_usd") or 0)
    try:
        net_pct = float(closed.get("net_pnl_pct") or 0)
    except (TypeError, ValueError):
        net_pct = (net / stake * 100.0) if stake > 0 else 0.0
    return {
        "gross": gross,
        "net": net,
        "stake": stake,
        "net_pct": net_pct,
        "fees": float(closed.get("total_fees") or 0),
        "fund": float(closed.get("funding_fee") or 0),
        "entry_fee": float(closed.get("entry_fee") or 0),
        "exit_fee": float(closed.get("exit_fee") or 0),
    }


def _settlement_dict(
    closed: dict[str, Any], settlement: dict[str, Any] | None
) -> dict[str, Any] | None:
    if isinstance(settlement, dict) and settlement:
        return settlement
    detail = closed.get("settlement_detail")
    return detail if isinstance(detail, dict) and detail else None


def format_position_closed(
    closed: dict[str, Any],
    *,
    exit_reason: str | None = None,
    settlement: dict[str, Any] | None = None,
) -> str:
    """Ana kanal — kısa kapanış özeti."""
    raw_reason = exit_reason or closed.get("exit_reason") or "CLOSE"
    sym = _symbol_short(closed.get("symbol"))
    side = _side_label(closed.get("side"))
    entry = float(closed.get("entry_price") or 0)
    exit_px = float(closed.get("exit_price") or 0)
    pnl = _closed_pnl_fields(closed)
    gross, net = pnl["gross"], pnl["net"]
    fees, fund = pnl["fees"], pnl["fund"]
    stake = pnl["stake"]
    lev = int(closed.get("leverage") or 0)
    hold = closed.get("duration_sec") or closed.get("hold_sec")
    oid = closed.get("exchange_close_order_id") or closed.get("exchange_order_id")
    max_u = closed.get("max_unreal_seen")
    max_n = closed.get("max_net_seen")
    pre_g = closed.get("pre_send_gross")
    pre_n = closed.get("pre_send_net")
    settle = _settlement_dict(closed, settlement)
    icon = _pnl_icon(net)
    reason_lbl = _esc(_reason_human(raw_reason))
    reason_code = _esc(str(raw_reason).strip())
    exit_tr = _fmt_tr_from_str(closed.get("exit_time_str")) or _fmt_tr_from_str(
        closed.get("exit_time")
    )
    lines = [
        _headline(icon, "Pozisyon kapandı"),
        f"<b>{_esc(sym)}</b> · {side}",
        _DIV,
    ]
    if exit_tr:
        lines.append(_line("Kapanış (TR)", f"<code>{_esc(exit_tr)}</code>"))
    lines.extend(
        [
            _line("Sebep", f"<b>{reason_lbl}</b> (<code>{reason_code}</code>)"),
            _line(
                "Fiyat",
                f"<code>{_fmt_px(entry)}</code> → <code>{_fmt_px(exit_px)}</code>",
            ),
            _line(
                "Sonuç",
                f"brüt <b>{_fmt_usd(gross, signed=True)}</b> · net <b>{_fmt_usd(net, signed=True)}</b>",
                bold_value=False,
            ),
            _line(
                "Maliyet",
                f"ücret {_fmt_usd(fees)} · funding {_fmt_usd(fund, signed=True)}",
            ),
        ]
    )
    pos_meta = f"{_fmt_usd(stake)} · {lev}x"
    dur = _duration_human(hold)
    if dur:
        pos_meta += f" · {dur}"
    lines.append(_line("Pozisyon", pos_meta))
    if max_u is not None:
        peak = f"brüt {_fmt_usd(max_u, signed=True)}"
        if max_n is not None:
            peak += f" · net tepe {_fmt_usd(max_n, signed=True)}"
        lines.append(_line("Tepe uPnL", peak))
    if pre_g or pre_n:
        lines.append(
            _line(
                "Emir öncesi",
                f"brüt {_fmt_usd(pre_g, signed=True)} · net {_fmt_usd(pre_n, signed=True)}",
            )
        )
    if settle:
        lines.append(
            _line(
                "Borsa mutabakat",
                f"realize {_fmt_usd(settle.get('exchange_realized_pnl'), signed=True)} · "
                f"komisyon {_fmt_usd(settle.get('exchange_commission'))}",
            )
        )
    lines.append(_line("Kayıt", f"<code>#{_esc(closed.get('id'))}</code>"))
    if oid:
        lines.append(_line("Kapanış emri", f"<code>{_esc(oid)}</code>"))
    lines.append(
        _now_footer(str(closed.get("exit_time_str") or "").strip() or None)
    )
    return "\n".join(lines)


def format_position_closed_detailed(
    closed: dict[str, Any],
    *,
    exit_reason: str | None = None,
    settlement: dict[str, Any] | None = None,
) -> str:
    """Kapanış kanalı — tam işlem günlüğü."""
    raw_reason = exit_reason or closed.get("exit_reason") or "CLOSE"
    sym_full = str(closed.get("symbol") or "").upper()
    sym = _symbol_short(sym_full)
    side = _side_label(closed.get("side"))
    pnl = _closed_pnl_fields(closed)
    net = pnl["net"]
    icon = _pnl_icon(net)
    settle = _settlement_dict(closed, settlement)
    close_exec = closed.get("close_execution") or {}
    if not isinstance(close_exec, dict):
        close_exec = {}

    entry = float(closed.get("entry_price") or 0)
    exit_px = float(closed.get("exit_price") or 0)
    size = float(closed.get("size") or 0)
    lev = int(closed.get("leverage") or 0)
    stake = pnl["stake"]
    notional = stake * max(lev, 1) if stake and lev else 0

    lines = [
        _headline(icon, "Kapanış logu"),
        f"<b>{_esc(sym)}</b> · {side} · <code>{_esc(sym_full)}</code>",
        _DIV,
        _line("Kayıt", f"<code>#{_esc(closed.get('id'))}</code>"),
        _line(
            "Zaman",
            f"kapanış <code>{_esc(_fmt_tr_from_str(closed.get('exit_time_str')) or '—')}</code>"
            + (
                f" · açılış <code>{_esc(_fmt_tr_from_str(closed.get('entry_time_str')) or '—')}</code>"
                if closed.get("entry_time_str") or closed.get("opened_at_iso")
                else ""
            ),
        ),
        _line(
            "Süre",
            _esc(_duration_human(closed.get("duration_sec") or closed.get("hold_sec")) or "—"),
        ),
        _line(
            "Çıkış",
            f"<b>{_esc(_reason_human(raw_reason))}</b> · <code>{_esc(str(raw_reason).strip())}</code>",
        ),
        _line("Mod", _esc(_mode_human(closed.get("on_exchange")))),
        _line("Kaynak", _esc(_source_human(closed.get("signal_source")))),
        _DIV,
        "<b>Fiyat &amp; boyut</b>",
        _line("Giriş", f"<code>{_fmt_px(entry)}</code>"),
        _line("Çıkış", f"<code>{_fmt_px(exit_px)}</code>"),
        _line("Miktar", f"<code>{_esc(size)}</code> kontrat"),
        _line("Stake", f"{_fmt_usd(stake)} · <b>{lev}x</b> · notional ~{_fmt_usd(notional)}"),
    ]
    if closed.get("tp_target_usd") or closed.get("tp_net_target_usd"):
        lines.append(
            _line(
                "Hedef (açılış)",
                f"brüt {_fmt_usd(closed.get('tp_target_usd'))} · "
                f"net {_fmt_usd(closed.get('tp_net_target_usd'))}",
            )
        )
    lines.extend(
        [
            _DIV,
            "<b>Sonuç (cüzdan)</b>",
            _line(
                "PnL",
                f"brüt <b>{_fmt_usd(pnl['gross'], signed=True)}</b> · "
                f"net <b>{_fmt_usd(net, signed=True)}</b> · "
                f"<b>{_fmt_pct(pnl['net_pct'])}</b> stake",
            ),
            _line(
                "Ücretler",
                f"giriş {_fmt_usd(pnl['entry_fee'])} · çıkış {_fmt_usd(pnl['exit_fee'])} · "
                f"toplam {_fmt_usd(pnl['fees'])} · funding {_fmt_usd(pnl['fund'], signed=True)}",
            ),
        ]
    )
    max_u = closed.get("max_unreal_seen")
    min_u = closed.get("min_unreal_seen")
    max_n = closed.get("max_net_seen")
    if max_u is not None or min_u is not None:
        peak_parts: list[str] = []
        if max_u is not None:
            peak_parts.append(f"tepe brüt {_fmt_usd(max_u, signed=True)}")
        if min_u is not None:
            peak_parts.append(f"dip brüt {_fmt_usd(min_u, signed=True)}")
        if max_n is not None:
            peak_parts.append(f"tepe net {_fmt_usd(max_n, signed=True)}")
        lines.append(_line("uPnL seyri", " · ".join(peak_parts)))
    pre_g = closed.get("pre_send_gross")
    pre_n = closed.get("pre_send_net")
    if pre_g is not None or pre_n is not None:
        lines.append(
            _line(
                "Emir öncesi (book)",
                f"brüt {_fmt_usd(pre_g, signed=True)} · net {_fmt_usd(pre_n, signed=True)}",
            )
        )
    fill_px = close_exec.get("signal_fill_px") or closed.get("signal_fill_px")
    mark_u = close_exec.get("signal_mark_unreal") or closed.get("signal_mark_unreal")
    est_net = close_exec.get("signal_est_net") or closed.get("signal_est_net")
    if fill_px or mark_u or est_net:
        lines.append(
            _line(
                "Kapanış sinyali",
                f"fill <code>{_fmt_px(fill_px)}</code> · mark uPnL {_fmt_usd(mark_u, signed=True)} · "
                f"est net {_fmt_usd(est_net, signed=True)}",
            )
        )
    exec_mode = close_exec.get("_close_exec_mode") or close_exec.get("close_exec_mode")
    if exec_mode:
        lines.append(_line("Emir tipi", f"<code>{_esc(exec_mode)}</code>"))
    open_oid = closed.get("exchange_order_id") or closed.get("order_id")
    close_oid = closed.get("exchange_close_order_id")
    if open_oid or close_oid:
        lines.append(
            _line(
                "Emir ID",
                f"açılış <code>{_esc(open_oid or '—')}</code> · "
                f"kapanış <code>{_esc(close_oid or '—')}</code>",
            )
        )
    if settle:
        lines.extend(
            [
                _DIV,
                "<b>Borsa mutabakat (API)</b>",
                _line(
                    "Realized",
                    f"{_fmt_usd(settle.get('exchange_realized_pnl'), signed=True)} · "
                    f"komisyon {_fmt_usd(settle.get('exchange_commission'))}",
                ),
                _line(
                    "Kaynak",
                    f"{_esc(settle.get('fee_source') or '—')} · "
                    f"{_esc(settle.get('pnl_source') or '—')}",
                ),
            ]
        )
        if settle.get("trade_count_close") is not None:
            lines.append(
                _line("Fill sayısı", f"<code>{_esc(settle.get('trade_count_close'))}</code>")
            )
        if settle.get("income_settled"):
            lines.append(_line("Income", _esc(settle.get("income_settled"))))
    lines.append(
        _line(
            "Veri",
            f"{_esc(closed.get('data_source') or '—')} · "
            f"initiator <code>{_esc(closed.get('close_initiator') or 'bot')}</code>",
        )
    )
    lines.append(_now_footer(str(closed.get("exit_time_str") or "").strip() or None))
    return "\n".join(lines)


def _close_notify_dedupe_key(closed: dict[str, Any]) -> str:
    try:
        from elite_trader.mega_live import _closed_dedupe_key

        disk_key = _closed_dedupe_key(closed)
        if disk_key:
            return disk_key
    except Exception:
        pass
    sym = str(closed.get("symbol") or "").upper()
    side = str(closed.get("side") or "LONG").upper()
    oid = str(
        closed.get("exchange_close_order_id")
        or closed.get("close_order_id")
        or closed.get("exit_order_id")
        or closed.get("order_id")
        or ""
    ).strip()
    try:
        net = round(
            float(
                closed.get("wallet_pnl")
                or closed.get("net_pnl")
                or closed.get("final_pnl")
                or 0
            ),
            4,
        )
    except (TypeError, ValueError):
        net = 0.0
    exit_ts = str(closed.get("exit_time_str") or closed.get("exit_time") or "").strip()
    return f"{sym}:{side}:{oid}:{net}:{exit_ts}"


def notify_position_closed(
    closed: dict[str, Any],
    *,
    exit_reason: str | None = None,
    settlement: dict[str, Any] | None = None,
) -> None:
    if not telegram_enabled():
        return
    if not _should_telegram_notify_close(closed):
        return
    ttl = max(30.0, _env_float("MEGA_TELEGRAM_CLOSE_DEDUPE_SEC", 86400 * 14))
    key = _close_notify_dedupe_key(closed)
    now = time.time()
    global _close_notify_seen
    if not _close_notify_seen:
        _load_close_notify_persisted()
    if key and key in _close_notify_seen and (now - _close_notify_seen[key]) < ttl:
        return
    if key:
        _close_notify_seen[key] = now
        _persist_close_notify_key(key)
        if len(_close_notify_seen) > 400:
            cutoff = now - ttl
            for stale in [k for k, t in _close_notify_seen.items() if t < cutoff]:
                _close_notify_seen.pop(stale, None)
    settle = _settlement_dict(closed, settlement)
    main_cid = _chat_id()
    standard = format_position_closed(
        closed, exit_reason=exit_reason, settlement=settle
    )
    detailed = format_position_closed_detailed(
        closed, exit_reason=exit_reason, settlement=settle
    )
    enqueue_message(standard, chat_id=main_cid or None)
    for cid in _closes_chat_ids():
        if cid == main_cid:
            continue
        enqueue_message(detailed, chat_id=cid)


def _open_positions_snapshot() -> list[dict[str, Any]]:
    try:
        from elite_trader.mega_live import (
            _mega_positions,
            enrich_mega_positions_open_times,
            refresh_mega_positions_cache,
        )

        refresh_mega_positions_cache(force=False, skip_wallet=True)
        rows = [dict(p) for p in (_mega_positions or [])]
        enrich_mega_positions_open_times(rows)
        return rows
    except Exception:
        return []


def _open_signature(rows: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for p in sorted(rows, key=lambda x: (str(x.get("symbol")), int(x.get("id") or 0))):
        parts.append(
            f"{p.get('id')}:{p.get('symbol')}:{p.get('side')}:"
            f"{round(float(p.get('unrealized_pnl') or 0), 2)}"
        )
    return "|".join(parts)


def format_open_positions_digest(rows: list[dict[str, Any]]) -> str:
    if not rows:
        today_n, today_net, all_n, all_net = _closed_counts_tr_today()
        lines: list[str] = [_headline("📭", "Açık pozisyon yok")]
        if today_n > 0 or all_n > 0:
            val = f"bugün <b>{_fmt_usd(today_net, signed=True)}</b> · {today_n} kapanış"
            if all_n > today_n:
                val += f" · oturum {_fmt_usd(all_net, signed=True)} ({all_n})"
            lines.append(_line("Gerçekleşen net", val))
        lines.append(_now_footer())
        return "\n".join(lines)
    total_u = sum(
        float(p.get("unrealized_pnl") or p.get("exchange_unrealized_pnl") or 0)
        for p in rows
    )
    lines = [
        _headline("📊", f"Açık pozisyonlar ({len(rows)})"),
        _line_open_upnl_summary(total_u),
    ]
    lines.extend(_format_open_positions_system_lines())
    lines.append(_DIV)
    for p in rows[:12]:
        sym = _esc(_symbol_short(p.get("symbol")))
        side = _side_label(p.get("side"))
        u = float(p.get("unrealized_pnl") or p.get("exchange_unrealized_pnl") or 0)
        max_u = float(p.get("max_unreal_seen") or 0)
        stake = float(p.get("stake_usd") or 0)
        lev = int(p.get("leverage") or 0)
        icon = _pnl_icon(u)
        open_tr = _fmt_position_open_tr(p)
        lines.append(
            f"{icon} <b>{sym}</b> {side}\n"
            f"   uPnL <b>{_fmt_usd(u, signed=True)}</b> · tepe {_fmt_usd(max_u, signed=True)}\n"
            f"   {_fmt_usd(stake)} · {lev}x · açılış <code>{_esc(open_tr)}</code>"
        )
    if len(rows) > 12:
        lines.append(f"<i>+{len(rows) - 12} pozisyon daha</i>")
    lines.append(_now_footer())
    return "\n".join(lines)


def _fetch_connection_status() -> dict[str, Any]:
    port = os.getenv("BINANCE_ELITE_PORT", "9006").strip() or "9006"
    try:
        import json
        import urllib.request

        out: dict[str, Any] = {}
        for path in ("/api/connection/live", "/api/connection/alerts"):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=6
                ) as resp:
                    out[path] = json.load(resp)
            except Exception as exc:
                out[path] = {"error": str(exc)}
        return out
    except Exception as exc:
        return {"error": str(exc)}


def format_system_status() -> str:
    conn = _fetch_connection_status()
    live = conn.get("/api/connection/live") or {}
    alerts = conn.get("/api/connection/alerts") or {}
    bt = live.get("bookticker") or {}
    mw = live.get("mark_ws") or {}
    pl = alerts.get("pipeline") or {}
    sev = str(alerts.get("severity") or "—").strip()
    api_ok = live.get("api_connected")
    lines = [
        _headline("⚙️", "Sistem durumu"),
        _DIV,
        _line(
            "API",
            f"{_bool_icon(api_ok)} "
            f"{'Bağlı' if api_ok else 'Kesik'} · canlı emir {_esc(live.get('live_orders') or '—')}",
        ),
        _line(
            "BookTicker",
            f"{_bool_icon(bt.get('ok'))} lag {bt.get('lag_ms', '—')} ms · "
            f"{bt.get('coins', '—')} coin",
        ),
        _line(
            "Mark WS",
            f"{_bool_icon(mw.get('health'))} {_esc(mw.get('health') or '—')} · "
            f"lag {mw.get('lag_ms', '—')} ms",
        ),
        _line("Uyarı", f"<b>{_esc(sev)}</b>"),
    ]
    if pl:
        pl_state = pl.get("state") or pl.get("status") if isinstance(pl, dict) else pl
        lines.append(_line("Pipeline", _esc(pl_state)))
    try:
        from elite_trader.mega_live import mega_live_enabled, mega_motor_active

        motor = mega_motor_active()
        live_on = mega_live_enabled()
        lines.append(
            _line(
                "MEGA",
                f"motor {_bool_icon(motor)} {_esc(motor)} · "
                f"live {_bool_icon(live_on)} {_esc(live_on)}",
            )
        )
    except Exception:
        pass
    lines.append(_now_footer())
    return "\n".join(lines)


def maybe_send_open_digest(*, force: bool = False) -> None:
    global _open_digest_ts, _last_open_sig
    iv = max(60.0, _env_float("MEGA_TELEGRAM_OPEN_DIGEST_SEC", 180.0))
    now = time.time()
    rows = _open_positions_snapshot()
    sig = _open_signature(rows)
    changed = sig != _last_open_sig
    if not force and not changed and (now - _open_digest_ts) < iv:
        return
    _last_open_sig = sig
    _open_digest_ts = now
    enqueue_message(format_open_positions_digest(rows))


def maybe_send_status(*, force: bool = False) -> None:
    iv = max(45.0, _env_float("MEGA_TELEGRAM_STATUS_SEC", 120.0))
    if not hasattr(maybe_send_status, "_last_ts"):
        maybe_send_status._last_ts = 0.0  # type: ignore[attr-defined]
    now = time.time()
    if not force and (now - float(maybe_send_status._last_ts)) < iv:  # type: ignore[attr-defined]
        return
    maybe_send_status._last_ts = now  # type: ignore[attr-defined]
    enqueue_message(format_system_status())


def _status_worker_loop() -> None:
    while not _worker_stop.is_set():
        try:
            if telegram_enabled():
                maybe_send_status()
                maybe_send_open_digest()
        except Exception as exc:
            print(f"  ⚠ Telegram status döngüsü: {exc}")
        sleep_iv = max(30.0, _env_float("MEGA_TELEGRAM_POLL_SEC", 45.0))
        _worker_stop.wait(sleep_iv)


_status_thread: threading.Thread | None = None


def start_telegram_status_loop() -> None:
    global _status_thread
    if not telegram_enabled():
        return
    if _status_thread and _status_thread.is_alive():
        return
    _status_thread = threading.Thread(
        target=_status_worker_loop, name="mega-telegram-status", daemon=True
    )
    _status_thread.start()


# ─── Telegram komutları (getUpdates) ─────────────────────────────────────────


def _commands_enabled() -> bool:
    if not telegram_enabled():
        return False
    return _env_bool("MEGA_TELEGRAM_COMMANDS", True)


def _allowed_chat_ids() -> set[str]:
    raw = os.getenv("MEGA_TELEGRAM_ALLOWED_CHATS", "").strip()
    ids = {_chat_id()}
    ids.update(_closes_chat_ids())
    if raw:
        for part in raw.split(","):
            p = part.strip()
            if p:
                ids.add(p)
    return {x for x in ids if x}


def _telegram_api(method: str, **params: Any) -> dict[str, Any]:
    token = _bot_token()
    if not token:
        return {}
    try:
        import json
        import urllib.parse
        import urllib.request

        url = f"https://api.telegram.org/bot{token}/{method}"
        if params:
            body = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            ).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST")
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        print(f"  ⚠ Telegram API {method}: {exc}")
        return {}


def _register_bot_commands() -> None:
    if not _commands_enabled():
        return
    _telegram_api("deleteWebhook", drop_pending_updates=False)
    commands = [
        ("yardim", "Komut listesi"),
        ("help", "Command list (EN)"),
        ("durum", "Sistem durumu"),
        ("status", "System status"),
        ("pozisyon", "Açık pozisyonlar (detay)"),
        ("positions", "Open positions"),
        ("kapali", "Son kapanan işlemler"),
        ("closed", "Recent closed trades"),
        ("ozet", "Kâr/zarar özeti"),
        ("baglanti", "API / WS bağlantı"),
        ("coin", "Sembol detayı (örn /coin PEOPLE)"),
    ]
    import json

    payload = json.dumps(
        [{"command": c, "description": d} for c, d in commands]
    )
    _telegram_api("setMyCommands", commands=payload)


def _reply(chat_id: str, text: str) -> None:
    enqueue_message(text, chat_id=str(chat_id))


def _parse_command(text: str) -> tuple[str, list[str]]:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return "", []
    head, _, rest = raw.partition(" ")
    cmd = head.split("@")[0].lower().lstrip("/")
    args = [a for a in rest.split() if a]
    return cmd, args


def _closed_row_net(row: dict[str, Any]) -> float:
    return float(
        row.get("wallet_pnl")
        or row.get("net_pnl")
        or row.get("final_pnl")
        or 0
    )


def _all_closed_rows() -> list[dict[str, Any]]:
    try:
        from elite_trader.mega_live import _ensure_mega_closed_loaded, _mega_closed

        _ensure_mega_closed_loaded()
        return list(_mega_closed or [])
    except Exception:
        return []


def _closed_realized_net_total() -> tuple[float, int]:
    """Oturumdaki tüm kapalı işlemler — cüzdan net toplamı."""
    rows = _all_closed_rows()
    return sum(_closed_row_net(r) for r in rows), len(rows)


def _closed_counts_tr_today() -> tuple[int, float, int, float]:
    """(bugün TR kapanış, bugün net, oturum kapanış, oturum net)."""
    rows = _all_closed_rows()
    try:
        from elite_trader.mega_live import _closed_exit_ts

        exit_ts = _closed_exit_ts
    except Exception:
        exit_ts = _closed_exit_ts
    today = datetime.now(_tr_tz()).strftime("%Y-%m-%d")
    today_n, today_net, all_n, all_net = 0, 0.0, len(rows), 0.0
    for r in rows:
        net = _closed_row_net(r)
        all_net += net
        ts = exit_ts(r)
        if ts is None:
            continue
        if datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(_tr_tz()).strftime(
            "%Y-%m-%d"
        ) == today:
            today_n += 1
            today_net += net
    return today_n, today_net, all_n, all_net


def _line_open_upnl_summary(total_u: float) -> str:
    today_n, today_net, all_n, all_net = _closed_counts_tr_today()
    val = (
        f"<b>{_fmt_usd(total_u, signed=True)}</b> · "
        f"bugün net <b>{_fmt_usd(today_net, signed=True)}</b>"
    )
    if today_n > 0:
        val += f" <i>({today_n} kapanış)</i>"
    if all_n > today_n:
        val += f" · oturum {_fmt_usd(all_net, signed=True)} ({all_n})"
    return _line("Toplam uPnL", val, bold_value=False)


def _format_open_positions_system_lines() -> list[str]:
    """BTC rejim, piyasa, hub — açık pozisyon digest üst bilgisi."""
    lines: list[str] = []
    snap: dict[str, Any] = {}
    try:
        from elite_trader.mega_direction_guard import btc_context_snapshot

        snap = btc_context_snapshot() or {}
    except Exception:
        pass

    regime_lbl = snap.get("regime_label") or snap.get("regime") or "—"
    ready_lbl = snap.get("ready_label") or ("Hazır" if snap.get("ready") else "Bekle")
    btc_bits = [f"<b>{_esc(regime_lbl)}</b>", f"giriş {_esc(ready_lbl)}"]
    if not snap.get("ready") and snap.get("block_reason"):
        btc_bits.append(f"<i>{_esc(snap.get('block_reason'))}</i>")
    ch24 = snap.get("btc_24h_change")
    if ch24 is not None:
        try:
            btc_bits.append(f"24s {_fmt_pct(ch24)}")
        except (TypeError, ValueError):
            pass
    px = snap.get("btc_price")
    if px:
        try:
            btc_bits.append(f"<code>{_fmt_px(float(px))}</code>")
        except (TypeError, ValueError):
            pass
    age = snap.get("context_age_sec")
    if age is not None:
        try:
            btc_bits.append(f"ctx {float(age):.0f}s")
        except (TypeError, ValueError):
            pass
    lines.append(_line("BTC", " · ".join(btc_bits), bold_value=False))

    if snap.get("bearish"):
        bear_tag = snap.get("bear_tag") or "ayı bias"
        lines.append(_line("Bias", f"SHORT lehine · {_esc(bear_tag)}", bold_value=False))
    elif snap.get("long_allowed"):
        lines.append(_line("Bias", "LONG açık (ayı yok)", bold_value=False))

    cascade = snap.get("btc_cascade") if isinstance(snap.get("btc_cascade"), dict) else {}
    phase = cascade.get("phase_label") or cascade.get("phase")
    if phase and str(phase).lower() not in ("idle", "none", "", "off"):
        casc_bits = [_esc(str(phase))]
        if cascade.get("active"):
            casc_bits.append("aktif")
        lines.append(_line("Şelale", " · ".join(casc_bits), bold_value=False))

    macro = snap.get("btc_macro") if isinstance(snap.get("btc_macro"), dict) else {}
    macro_lbl = macro.get("tag") or macro.get("label") or macro.get("headline")
    if macro_lbl:
        lines.append(_line("Makro", _esc(str(macro_lbl)[:48]), bold_value=False))

    liq = snap.get("btc_liq") if isinstance(snap.get("btc_liq"), dict) else {}
    liq_lbl = liq.get("label") or liq.get("bias") or liq.get("phase")
    if liq_lbl:
        lines.append(_line("Liq", _esc(str(liq_lbl)[:40]), bold_value=False))

    try:
        from elite_trader.mega_market_regime import snapshot as regime_snapshot

        mr = regime_snapshot() or {}
    except Exception:
        mr = {}
    mr_bits = [_esc(str(mr.get("regime") or "—"))]
    if mr.get("regime_locked"):
        mr_bits.append("kilit")
    if mr.get("transition_active"):
        tr = str(mr.get("transition_reason") or "geçiş")[:28]
        mr_bits.append(_esc(tr))
    rmix = mr.get("reject_mix")
    if isinstance(rmix, dict) and rmix:
        top = sorted(rmix.items(), key=lambda x: -float(x[1] or 0))[:2]
        mr_bits.append(
            "rej "
            + ", ".join(f"{_esc(str(k)[:12])}:{float(v) * 100:.0f}%" for k, v in top)
        )
    lines.append(_line("Piyasa", " · ".join(mr_bits), bold_value=False))

    try:
        from elite_trader.mega_system_context import build_system_context

        ctx = build_system_context("report") or {}
        hub = (ctx.get("system") or {}).get("hub") or {}
        lag = hub.get("mark_lag_ms")
        alive = hub.get("alive")
        if lag is not None or alive is not None:
            hub_bits = []
            if alive is not None:
                hub_bits.append("canlı" if alive else "kopuk")
            if lag is not None:
                try:
                    hub_bits.append(f"lag {float(lag):.0f}ms")
                except (TypeError, ValueError):
                    pass
            if hub_bits:
                lines.append(_line("Hub", " · ".join(hub_bits), bold_value=False))
        rejects = (ctx.get("system") or {}).get("reject_top") or []
        if isinstance(rejects, list) and rejects:
            r0 = rejects[0] if isinstance(rejects[0], dict) else {}
            reason = r0.get("reason")
            share = r0.get("share")
            if reason:
                sh_txt = ""
                if share is not None:
                    try:
                        sh_txt = f" %{float(share) * 100:.0f}"
                    except (TypeError, ValueError):
                        pass
                lines.append(
                    _line("Son red", f"{_esc(str(reason)[:32])}{sh_txt}", bold_value=False)
                )
    except Exception:
        pass

    try:
        from elite_trader.mega_control import get_status

        st = get_status() or {}
        motor = st.get("motor_active")
        ctrl = _esc(str(st.get("state") or "—"))
        if motor is not None:
            ctrl += f" · motor {_bool_icon(motor)}"
        lines.append(_line("Kontrol", ctrl, bold_value=False))
    except Exception:
        pass

    return lines


def _closed_rows_recent(limit: int = 5) -> list[dict[str, Any]]:
    rows = _all_closed_rows()
    rows.sort(
        key=lambda r: float(_closed_exit_ts(r) or 0),
        reverse=True,
    )
    return rows[: max(1, min(limit, 20))]


def _closed_exit_ts(row: dict[str, Any]) -> float | None:
    raw = row.get("exit_time")
    if raw is not None:
        try:
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            if ts > 0:
                return ts
        except (TypeError, ValueError):
            pass
    for key in ("exit_time_iso", "exit_time_str"):
        raw = row.get(key)
        if not raw:
            continue
        try:
            s = str(raw).strip().replace("Z", "+00:00")
            if "T" in s:
                dt = datetime.fromisoformat(s)
            else:
                dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            return dt.timestamp()
        except Exception:
            continue
    return None


def format_position_detail(pos: dict[str, Any]) -> str:
    sym = _symbol_short(pos.get("symbol"))
    side = _side_label(pos.get("side"))
    u = float(pos.get("unrealized_pnl") or pos.get("exchange_unrealized_pnl") or 0)
    max_u = float(pos.get("max_unreal_seen") or 0)
    max_n = float(pos.get("max_net_seen") or 0)
    entry = float(pos.get("entry_price") or 0)
    mark = float(pos.get("current_price") or pos.get("mark_price") or 0)
    stake = float(pos.get("stake_usd") or 0)
    lev = int(pos.get("leverage") or 0)
    fill_net = pos.get("fill_net_est")
    icon = _pnl_icon(u)
    lines = [
        f"{icon} <b>{_esc(sym)}</b> · {side} · <code>#{_esc(pos.get('id'))}</code>",
        _line("Fiyat", f"<code>{_fmt_px(entry)}</code> → mark <code>{_fmt_px(mark)}</code>"),
        _line(
            "uPnL",
            f"<b>{_fmt_usd(u, signed=True)}</b> · tepe brüt {_fmt_usd(max_u, signed=True)}",
            bold_value=False,
        ),
        _line("Tepe net", _fmt_usd(max_n, signed=True)),
        _line("Boyut", f"{_fmt_usd(stake)} · {lev}x"),
        _line("Açılış", f"<code>{_esc(_fmt_position_open_tr(pos))}</code>"),
    ]
    if fill_net is not None:
        lines.append(_line("Fill tahmini", _fmt_usd(fill_net, signed=True)))
    tp_g = float(pos.get("tp_target_usd") or 0)
    tp_n = float(pos.get("tp_net_target_usd") or 0)
    if tp_g > 0 or tp_n > 0:
        lines.append(_line("Hedef", f"brüt {_fmt_usd(tp_g)} · net {_fmt_usd(tp_n)}"))
    src = pos.get("signal_source")
    if src:
        lines.append(_line("Kaynak", _esc(_source_human(src))))
    return "\n".join(lines)


def format_open_positions_full(rows: list[dict[str, Any]]) -> str:
    if not rows:
        today_n, today_net, all_n, all_net = _closed_counts_tr_today()
        lines: list[str] = [_headline("📭", "Açık pozisyon yok")]
        if today_n > 0 or all_n > 0:
            val = f"bugün <b>{_fmt_usd(today_net, signed=True)}</b> · {today_n} kapanış"
            if all_n > today_n:
                val += f" · oturum {_fmt_usd(all_net, signed=True)} ({all_n})"
            lines.append(_line("Gerçekleşen net", val))
        lines.append(_now_footer())
        return "\n".join(lines)
    total_u = sum(
        float(p.get("unrealized_pnl") or p.get("exchange_unrealized_pnl") or 0)
        for p in rows
    )
    lines = [
        _headline("📊", f"Açık pozisyonlar ({len(rows)})"),
        _line_open_upnl_summary(total_u),
    ]
    lines.extend(_format_open_positions_system_lines())
    lines.append(_DIV)
    for i, p in enumerate(rows[:10]):
        if i:
            lines.append("")
        lines.append(format_position_detail(p))
    if len(rows) > 10:
        lines.append(f"\n<i>+{len(rows) - 10} pozisyon (kısaltıldı)</i>")
    lines.append(_now_footer())
    return "\n".join(lines)


def format_closed_recent(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "\n".join([_headline("📭", "Son kapanış yok"), _now_footer()])
    lines = [_headline("📕", f"Son kapanışlar ({len(rows)})"), _DIV]
    for c in rows:
        sym = _esc(_symbol_short(c.get("symbol")))
        side = _side_label(c.get("side"))
        net = float(c.get("wallet_pnl") or c.get("net_pnl") or 0)
        gross = float(c.get("pnl_gross_usd") or c.get("pnl_usd") or 0)
        icon = _pnl_icon(net)
        reason = _esc(_reason_human(c.get("exit_reason")))
        ts = _esc(_fmt_tr_from_str(c.get("exit_time_str")) or "")
        lines.append(
            f"{icon} <b>{sym}</b> {side}\n"
            f"   Sebep · {reason}\n"
            f"   brüt <b>{_fmt_usd(gross, signed=True)}</b> · net <b>{_fmt_usd(net, signed=True)}</b>"
            + (f"\n   <i>{ts}</i>" if ts else "")
        )
    lines.append(_now_footer())
    return "\n".join(lines)


def format_pnl_summary() -> str:
    all_closed = _all_closed_rows()
    if not all_closed:
        return "📭 Kapalı işlem verisi yok."
    total_net = sum(_closed_row_net(c) for c in all_closed)
    wins = sum(1 for c in all_closed if _closed_row_net(c) >= 0)
    recent = _closed_rows_recent(50)
    open_rows = _open_positions_snapshot()
    open_u = sum(
        float(p.get("unrealized_pnl") or p.get("exchange_unrealized_pnl") or 0)
        for p in open_rows
    )
    wr = (100.0 * wins / len(all_closed)) if all_closed else 0.0
    return "\n".join(
        [
            _headline("📈", "Performans özeti"),
            _DIV,
            _line("Kapanış (oturum)", f"{len(all_closed)} işlem"),
            _line("Gerçekleşen net", f"<b>{_fmt_usd(total_net, signed=True)}</b>"),
            _line("Başarı", f"{wins}/{len(all_closed)} ({wr:.0f}%)"),
            _line("Son liste", f"son {len(recent)} kapanış gösterilir (/kapanis)"),
            _line(
                "Açık pozisyon",
                f"{len(open_rows)} adet · uPnL {_fmt_usd(open_u, signed=True)} · "
                f"gerçekleşen {_fmt_usd(total_net, signed=True)}",
            ),
            _now_footer(),
        ]
    )


def format_help_text() -> str:
    return "\n".join(
        [
            _headline("🤖", "Komutlar"),
            _DIV,
            "<b>Durum</b>",
            "/durum — API, WebSocket, motor",
            "/baglanti — bağlantı + teknik özet",
            "",
            "<b>Pozisyon</b>",
            "/pozisyon — açık pozisyonlar (detaylı)",
            "/kapali [N] — son N kapanış (varsayılan 5)",
            "/coin SEMBOL — tek sembol (örn <code>/coin ETH</code>)",
            "",
            "<b>Özet</b>",
            "/ozet — net P&amp;L ve başarı oranı",
            "/yardim — bu liste",
        ]
    )


def _find_open_by_symbol(query: str) -> list[dict[str, Any]]:
    q = query.upper().replace("USDT", "")
    rows = _open_positions_snapshot()
    out: list[dict[str, Any]] = []
    for p in rows:
        sym = str(p.get("symbol") or "").upper()
        if q in sym or sym.replace("USDT", "") == q:
            out.append(p)
    return out


def handle_telegram_command(text: str, chat_id: str) -> None:
    cmd, args = _parse_command(text)
    if not cmd:
        return
    if cmd in ("yardim", "help", "start", "komutlar"):
        _reply(chat_id, format_help_text())
        return
    if cmd in ("durum", "status", "sistem"):
        _reply(chat_id, format_system_status())
        return
    if cmd in ("pozisyon", "positions", "acik", "open"):
        refresh = True
        try:
            from elite_trader.mega_live import refresh_mega_positions_cache

            refresh_mega_positions_cache(force=refresh, skip_wallet=True)
        except Exception:
            pass
        _reply(chat_id, format_open_positions_full(_open_positions_snapshot()))
        return
    if cmd in ("kapali", "closed", "kapanis"):
        n = 5
        if args:
            try:
                n = int(args[0])
            except ValueError:
                pass
        _reply(chat_id, format_closed_recent(_closed_rows_recent(n)))
        return
    if cmd in ("ozet", "summary"):
        _reply(chat_id, format_pnl_summary())
        return
    if cmd in ("baglanti", "connection", "conn"):
        conn = _fetch_connection_status()
        import json

        live = conn.get("/api/connection/live") or {}
        alerts = conn.get("/api/connection/alerts") or {}
        snippet = json.dumps(
            {"live": {k: live.get(k) for k in list(live)[:12]}, "severity": alerts.get("severity")},
            ensure_ascii=False,
            indent=0,
        )[:1200]
        _reply(
            chat_id,
            format_system_status()
            + "\n\n<pre>"
            + _esc(snippet)
            + "</pre>",
        )
        return
    if cmd in ("coin", "sembol", "sym"):
        if not args:
            _reply(
                chat_id,
                "\n".join(
                    [
                        _headline("ℹ️", "Coin sorgusu"),
                        _line("Kullanım", "<code>/coin ETH</code> veya <code>/coin PEOPLE</code>"),
                    ]
                ),
            )
            return
        hits = _find_open_by_symbol(args[0])
        if not hits:
            _reply(
                chat_id,
                "\n".join(
                    [
                        _headline("🔍", "Pozisyon bulunamadı"),
                        _line("Sembol", f"<code>{_esc(args[0])}</code>"),
                        _line("Durum", "Bu sembolde açık pozisyon yok"),
                    ]
                ),
            )
            return
        parts = [format_position_detail(p) for p in hits]
        _reply(chat_id, "\n\n".join(parts))
        return
    _reply(
        chat_id,
        "\n".join(
            [
                _headline("⚠️", "Bilinmeyen komut"),
                _line("Girdi", f"<code>/{_esc(cmd)}</code>"),
                _line("Yardım", "<code>/yardim</code>"),
            ]
        ),
    )


_cmd_offset = 0
_cmd_thread: threading.Thread | None = None


def _commands_worker_loop() -> None:
    global _cmd_offset
    poll_iv = max(1.0, _env_float("MEGA_TELEGRAM_CMD_POLL_SEC", 2.0))
    allowed = _allowed_chat_ids()
    while not _worker_stop.is_set():
        if not _commands_enabled():
            _worker_stop.wait(poll_iv)
            continue
        data = _telegram_api(
            "getUpdates",
            offset=_cmd_offset,
            timeout=25,
            allowed_updates='["message"]',
        )
        for upd in data.get("result") or []:
            try:
                uid = int(upd.get("update_id", 0))
                _cmd_offset = max(_cmd_offset, uid + 1)
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                cid = str(chat.get("id", ""))
                if cid not in allowed:
                    continue
                text = str(msg.get("text") or "")
                if text.startswith("/"):
                    handle_telegram_command(text, cid)
            except Exception as exc:
                print(f"  ⚠ Telegram komut işleme: {exc}")
        _worker_stop.wait(poll_iv)


def start_telegram_commands_loop() -> None:
    global _cmd_thread
    if not _commands_enabled():
        return
    if _cmd_thread and _cmd_thread.is_alive():
        return
    _cmd_thread = threading.Thread(
        target=_commands_worker_loop, name="mega-telegram-cmd", daemon=True
    )
    _cmd_thread.start()
