"""Tarama / fiyat hub / motor — pozisyon açmama nedenleri (panel üst banner)."""
from __future__ import annotations

import os
import time
from typing import Any


def _desk_id() -> str:
    return (
        os.getenv("MEGA_INSTANCE_ID", "").strip()
        or os.getenv("BINANCE_ELITE_PORT", "").strip()
    )


def _bump(severity: str, level: str) -> str:
    order = {"ok": 0, "warn": 1, "critical": 2}
    if order.get(level, 0) > order.get(severity, 0):
        return level
    return severity


def _hub_consumer() -> bool:
    try:
        from elite_trader.binance_data_hub import hub_consumer_mode

        return hub_consumer_mode()
    except Exception:
        return False


def _mega_paper_desk() -> bool:
    try:
        from elite_trader.mega_live import mega_paper_sim_only

        return mega_paper_sim_only()
    except Exception:
        return False


def build_pipeline_alerts(
    *,
    live: dict[str, Any] | None = None,
    scanner: dict[str, Any] | None = None,
    heartbeat: dict[str, Any] | None = None,
    motor_candidates: int | None = None,
    motor_signals: int | None = None,
) -> list[dict[str, Any]]:
    """Pozisyon açmayı engelleyen durumlar — kritik önce sıralanır."""
    live = live or {}
    scanner = scanner or {}
    hb = heartbeat or {}
    alerts: list[dict[str, Any]] = []

    wl = int(scanner.get("watchlist_total") or 0)
    ticks = int(scanner.get("symbols_with_ticks") or 0)
    mark = live.get("mark_ws") or {}
    book = live.get("bookticker") or {}
    hub = (live.get("async_hub") or {}).get("data_hub") or {}
    threads = hb.get("threads") or {}

    if _hub_consumer():
        try:
            from elite_trader.binance_data_hub import consumer_resilience_status

            rs = consumer_resilience_status()
            hub_ok = bool(rs.get("ok"))
            hub_coins = int(rs.get("coins") or 0)
            hub_src = str(rs.get("source") or "")
        except Exception:
            hub_ok = False
            hub_coins = int(mark.get("coins") or 0)
            hub_src = ""
        mark_coins = hub_coins or int(mark.get("coins") or 0)
        mark_lag = mark.get("lag_ms")
        hub_age = hub.get("age_ms")
        min_ticks = max(5, int(wl * 0.12)) if wl else 5
        scan_ok = wl < 20 or ticks >= min_ticks
        # Tarama çalışıyorsa veya hub yedek kaynaktan besleniyorsa kritik banner yok
        if not scan_ok and not hub_ok and mark_coins < 15:
            alerts.append(
                {
                    "level": "critical",
                    "code": "hub_feed_down",
                    "title": "9007 fiyat hub kopuk — tarama durdu",
                    "detail": (
                        f"Mark beslemesi yok (coins={mark_coins}, kaynak={hub_src or 'yok'}). "
                        "9007 servisini kontrol edin; disk yedek ve shadow WS devreye giremedi."
                    ),
                }
            )
        elif not scan_ok and hub_ok:
            alerts.append(
                {
                    "level": "warn",
                    "code": "scan_ticks_recovering",
                    "title": "Evren tick yeniden doluyor",
                    "detail": (
                        f"Hub aktif ({hub_coins} mark, {hub_src}) — "
                        f"tarama {ticks}/{wl}, birkaç saniye içinde normale döner."
                    ),
                }
            )
        elif (
            not scan_ok
            and mark_lag is not None
            and int(mark_lag) > 20_000
            and not hub_ok
        ):
            alerts.append(
                {
                    "level": "warn",
                    "code": "hub_feed_stale",
                    "title": "9007 hub fiyatları bayat",
                    "detail": f"Mark gecikmesi {int(mark_lag)} ms — stale yedek kullanılıyor.",
                }
            )
        if hub_age is not None and int(hub_age) > 60_000 and not hub_ok:
            alerts.append(
                {
                    "level": "warn",
                    "code": "hub_cache_stale",
                    "title": "Hub HTTP yanıt vermiyor",
                    "detail": (
                        f"Son HTTP okuma {int(hub_age) // 1000}s önce — "
                        f"disk/stale yedek: {hub_src or 'bekleniyor'}."
                    ),
                }
            )
    else:
        if not book.get("ok") and str(mark.get("health") or "") != "ok":
            alerts.append(
                {
                    "level": "critical",
                    "code": "ws_feed_down",
                    "title": "WebSocket fiyat beslemesi kopuk",
                    "detail": "BookTicker/mark WS bağlı değil — motor aday üretemez.",
                }
            )
        if wl >= 20 and ticks < max(5, int(wl * 0.12)):
            alerts.append(
                {
                    "level": "critical",
                    "code": "scan_ticks_missing",
                    "title": "Evren fiyatı yok — pozisyon açılmaz",
                    "detail": f"Tarama {ticks}/{wl} sembol güncellenmiyor.",
                }
            )

    tick_ago = hb.get("tick_ago")
    if tick_ago is not None and float(tick_ago) > 20.0:
        alerts.append(
            {
                "level": "critical",
                "code": "fast_tick_stale",
                "title": "Fiyat tick döngüsü durdu",
                "detail": f"Son evren tick {float(tick_ago):.0f}s önce — açılış motoru çalışmaz.",
            }
        )

    if threads and not threads.get("fast_tick"):
        alerts.append(
            {
                "level": "critical",
                "code": "fast_tick_thread",
                "title": "Fast-tick worker kapalı",
                "detail": "Fiyat güncelleme thread'i çalışmıyor.",
            }
        )
    if threads and not threads.get("motor_scan"):
        alerts.append(
            {
                "level": "critical",
                "code": "motor_scan_thread",
                "title": "Motor tarama worker kapalı",
                "detail": "Sinyal/motor thread'i çalışmıyor — yeni giriş yok.",
            }
        )

    motor_ago = hb.get("motor_ago")
    motor_iv = float(hb.get("motor_interval_ms") or 900) / 1000.0
    if motor_ago is not None and float(motor_ago) > max(25.0, motor_iv * 6):
        alerts.append(
            {
                "level": "warn",
                "code": "motor_scan_stale",
                "title": "Motor tarama gecikmeli",
                "detail": f"Son motor turu {float(motor_ago):.0f}s önce (hedef ~{motor_iv:.1f}s).",
            }
        )

    try:
        from elite_trader.mega_live import mega_motor_active

        if mega_motor_active():
            from elite_trader.mega_control import allow_new_entries, control_state

            st = control_state()
            block = ""
            try:
                from elite_trader.mega_control import entry_block_reason

                block = entry_block_reason()
            except Exception:
                pass
            if st in ("PAUSED", "RESTARTING"):
                alerts.append(
                    {
                        "level": "info",
                        "code": "mega_paused",
                        "title": f"MEGA duraklatıldı ({st})",
                        "detail": (
                            "Yeni giriş kapalı — açık pozisyonlar TP ile devam eder. "
                            "Panelden Start ile devam."
                        ),
                    }
                )
            elif st == "PAUSING":
                alerts.append(
                    {
                        "level": "info",
                        "code": "mega_pausing",
                        "title": "MEGA duraklatılıyor",
                        "detail": (
                            "Yeni giriş kapalı. Varsayılan: mevcut pozisyonlar "
                            "kapatılmaz (MEGA_PAUSE_SOFT)."
                        ),
                    }
                )
            elif block:
                detail_map = {
                    "btc_regime_unknown": "BTC rejimi henüz bilinmiyor — klines gelene kadar yeni giriş yok.",
                    "btc_context_stale": "BTC rejim verisi bayat — yeni giriş bekletiliyor.",
                    "btc_price_missing": "BTC fiyatı yok — yeni giriş bekletiliyor.",
                    "btc_context_no_timestamp": "BTC bağlamı hazır değil.",
                    "control_pausing": "Duraklatma — yeni giriş kapalı.",
                }
                alerts.append(
                    {
                        "level": "warn",
                        "code": "mega_entries_off",
                        "title": "MEGA yeni giriş kapalı",
                        "detail": detail_map.get(
                            block,
                            f"Giriş engeli: {block.replace('_', ' ')}",
                        ),
                    }
                )
            elif not allow_new_entries():
                alerts.append(
                    {
                        "level": "warn",
                        "code": "mega_entries_off",
                        "title": "MEGA yeni giriş kapalı",
                        "detail": "Kontrol modu yeni açılışı engelliyor.",
                    }
                )
            sig_n = motor_signals if motor_signals is not None else int(
                scanner.get("confirmed_signal_count") or 0
            )
            cand_n = motor_candidates
            if (
                ticks >= max(5, int(wl * 0.5))
                and sig_n == 0
                and (cand_n is None or cand_n == 0)
            ):
                alerts.append(
                    {
                        "level": "warn",
                        "code": "mega_no_candidates",
                        "title": "MEGA aday yok (scoring/filtre)",
                        "detail": (
                            "Fiyat akışı tamam ama skor eşiği veya volatilite filtresi "
                            "giriş üretmiyor — bu normal olabilir."
                        ),
                    }
                )
    except Exception:
        pass

    order = {"critical": 0, "warn": 1, "ok": 2}
    alerts.sort(key=lambda a: order.get(str(a.get("level")), 9))
    return alerts


def merge_into_connection_alerts(
    base: dict[str, Any],
    *,
    live: dict[str, Any] | None = None,
    scanner: dict[str, Any] | None = None,
    heartbeat: dict[str, Any] | None = None,
    motor_candidates: int | None = None,
    skip_paper_mode_banner: bool = False,
) -> dict[str, Any]:
    """connection_alerts.build_alerts çıktısına pipeline uyarılarını birleştir."""
    out = dict(base)
    pipeline = build_pipeline_alerts(
        live=live,
        scanner=scanner,
        heartbeat=heartbeat,
        motor_candidates=motor_candidates,
        motor_signals=int((scanner or {}).get("confirmed_signal_count") or 0),
    )
    if skip_paper_mode_banner:
        out["alerts"] = [
            a
            for a in (out.get("alerts") or [])
            if a.get("code") != "paper_mode"
        ]
    merged: list[dict[str, Any]] = list(pipeline) + list(out.get("alerts") or [])
    severity = "ok"
    for row in merged:
        severity = _bump(severity, str(row.get("level") or "warn"))
    out["alerts"] = merged[:8]
    out["severity"] = severity
    out["ok"] = severity == "ok"
    out["trading_ok"] = severity == "ok" and not merged
    out["pipeline"] = {
        "watchlist_total": (scanner or {}).get("watchlist_total"),
        "symbols_with_ticks": (scanner or {}).get("symbols_with_ticks"),
        "hub_consumer": _hub_consumer(),
        "checked_at": time.time(),
    }
    try:
        from elite_trader.binance_data_hub import consumer_resilience_status

        if _hub_consumer():
            out["pipeline"]["hub_resilience"] = consumer_resilience_status()
    except Exception:
        pass
    return out
