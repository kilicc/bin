"""Binance bağlantı uyarıları — IP ban, auth, ağ kopukluğu (panel banner)."""
from __future__ import annotations

import os
import re
import time
from typing import Any

_ip_ban_until_ms: float = 0.0
_last_error: str | None = None
_last_error_ts: float = 0.0
_last_ok_ts: float = 0.0
_outage_hooks: list[Any] = []

_BAN_RE = re.compile(r"banned until (\d+)", re.I)
_CODE_RE = re.compile(r'"code":(-?\d+)')
# Açık emir varken margin/kaldıraç — panelde "son hata" olarak gösterme
_BENIGN_BINANCE_CODES = frozenset({"-4046", "-4047", "-4067", "-2011"})


def register_outage_hook(fn: Any) -> None:
    """9007 outage işaretleyicisi — yalnızca MEGA canlı desk kaydeder."""
    if fn not in _outage_hooks:
        _outage_hooks.append(fn)


def _fire_outage_hooks(msg: str) -> None:
    for fn in list(_outage_hooks):
        try:
            fn(msg)
        except Exception:
            pass


def note_binance_error(msg: str | None) -> None:
    """REST/HTTP hata metninden ban ve auth durumunu güncelle."""
    global _ip_ban_until_ms, _last_error, _last_error_ts
    if not msg:
        return
    text = str(msg)[:800]
    code = _error_code(text)
    if code in _BENIGN_BINANCE_CODES:
        return
    _last_error = text
    _last_error_ts = time.time()
    m = _BAN_RE.search(text)
    if m:
        try:
            until = float(m.group(1))
            _ip_ban_until_ms = max(_ip_ban_until_ms, until)
        except ValueError:
            pass
    try:
        from elite_trader.network_guard import note_failure

        if "418" in text or "429" in text or "-1003" in text or "too many requests" in text.lower():
            note_failure(kind="binance_rate_limit")
            _fire_outage_hooks(text)
    except Exception:
        pass
    if m:
        _fire_outage_hooks(text)


def last_ok_age_sec() -> float | None:
    """Son başarılı Binance REST yanıtından bu yana saniye."""
    if not _last_ok_ts:
        return None
    return max(0.0, time.time() - _last_ok_ts)


def note_binance_success() -> None:
    global _last_ok_ts, _last_error, _last_error_ts
    _last_ok_ts = time.time()
    if _last_error:
        code = _error_code(_last_error)
        if code in ("-1003", "-1007", "-2015", "-2011") or _is_transient_rest_block(
            _last_error
        ):
            _last_error = None
            _last_error_ts = 0.0


def ip_ban_active() -> bool:
    return time.time() * 1000 < _ip_ban_until_ms


def ip_ban_until_ms() -> float:
    return _ip_ban_until_ms if ip_ban_active() else 0.0


def _is_transient_rest_block(msg: str | None) -> bool:
    if not msg:
        return False
    e = msg.lower()
    return (
        "rest paused (network guard)" in e
        or "signed rest disabled (paper port)" in e
        or "binance outbound disabled" in e
    )


def _is_mega9007_demo_desk(desk_id: str | None) -> bool:
    d = (desk_id or _desk_instance_id()).strip()
    return d == "9007" or os.getenv("MEGA_INSTANCE_ID", "").strip() == "9007"


def _is_mega9006_demo_live_desk(desk_id: str | None) -> bool:
    d = (desk_id or _desk_instance_id()).strip()
    if d != "9006" and os.getenv("MEGA_INSTANCE_ID", "").strip() != "9006":
        return False
    try:
        from elite_trader.network_guard import _is_9006_live_desk

        return _is_9006_live_desk()
    except Exception:
        return False


def _desk_instance_id() -> str:
    return (
        os.getenv("MEGA_INSTANCE_ID", "").strip()
        or os.getenv("BINANCE_ELITE_PORT", "").strip()
    )


def _sanitize_auth_error(auth_error: str | None, *, api_ok: bool, api_paper: bool) -> str | None:
    if not auth_error:
        return None
    if _is_transient_rest_block(auth_error):
        return None
    if api_ok and not api_paper and not _error_code(auth_error):
        low = auth_error.lower()
        if "invalid api" not in low and "-2015" not in auth_error:
            return None
    return auth_error


def _error_code(msg: str | None) -> str | None:
    if not msg:
        return None
    m = _CODE_RE.search(msg)
    return m.group(1) if m else None


def _endpoint_label(client: Any) -> str:
    try:
        base = client._api_base()
    except Exception:
        base = ""
    if "demo-fapi" in base:
        return "demo-fapi.binance.com"
    if "testnet" in base:
        return "testnet.binancefuture.com"
    return "fapi.binance.com (mainnet)"


def build_alerts(
    *,
    api_ok: bool,
    api_paper: bool,
    auth_error: str | None,
    client: Any,
    open_positions: int = 0,
    desk_id: str | None = None,
) -> dict[str, Any]:
    """Panel banner için özet — /api/connection/alerts."""
    desk_id = desk_id or _desk_instance_id()
    auth_error = _sanitize_auth_error(auth_error, api_ok=api_ok, api_paper=api_paper)
    endpoint = _endpoint_label(client)
    alerts: list[dict[str, Any]] = []
    severity = "ok"

    def bump(level: str) -> None:
        nonlocal severity
        order = {"ok": 0, "warn": 1, "critical": 2}
        if order.get(level, 0) > order.get(severity, 0):
            severity = level

    if ip_ban_active():
        until = int(_ip_ban_until_ms)
        remain_min = max(0, round((until - time.time() * 1000) / 60000, 1))
        alerts.append(
            {
                "level": "critical",
                "code": "ip_ban",
                "title": "Binance IP geçici banlı (-1003)",
                "detail": (
                    f"GCP IP çok fazla REST isteği gönderdi. Ban ~{remain_min} dk sonra kalkar. "
                    "WebSocket fiyat beslemesi devam eder; emir/pozisyon sync REST ile gelmez."
                ),
                "until_ms": until,
            }
        )
        bump("critical")

    if auth_error:
        code = _error_code(auth_error)
        if code == "-1111":
            alerts.append(
                {
                    "level": "warn",
                    "code": "order_precision",
                    "title": "Emir hassasiyet hatası (-1111)",
                    "detail": (
                        "Miktar veya fiyat adımı (LOT_SIZE/PRICE_FILTER) aşıldı. "
                        "Emir reddedildi; otomatik yuvarlama düzeltmesi uygulandı."
                    ),
                }
            )
            bump("warn")
        elif code == "-1121":
            alerts.append(
                {
                    "level": "warn",
                    "code": "invalid_symbol",
                    "title": "Geçersiz sembol (-1121)",
                    "detail": (
                        "Sembol bu hesabın API ortamında yok (ör. ICP demo-fapi listesinde değil). "
                        "Bot bu coinde emir/margin çağrısı yapmaz; tarama atlanır."
                    ),
                }
            )
            bump("warn")
        elif code == "-2015":
            detail = (
                "API anahtarı geçersiz, IP whitelist'te değil veya Futures izni yok. "
                "binance.com → API Management → IP kısıtlamasına GCP IP ekleyin. "
                "demo.binance.com'da IP whitelist alanı yok — canlı işlem için mainnet anahtarı kullanın."
            )
            alerts.append(
                {
                    "level": "critical",
                    "code": "auth_error",
                    "title": f"Binance kimlik doğrulama hatası ({code})",
                    "detail": detail,
                }
            )
            bump("critical")
        else:
            alerts.append(
                {
                    "level": "critical",
                    "code": "auth_error",
                    "title": f"Binance kimlik doğrulama hatası ({code or '?'})",
                    "detail": auth_error[:240],
                }
            )
            bump("critical")
    elif not api_ok and not api_paper:
        alerts.append(
            {
                "level": "critical",
                "code": "api_down",
                "title": "Binance API yanıt vermiyor",
                "detail": "Bağlantı kopuk veya zaman aşımı. Emir gönderilemez.",
            }
        )
        bump("critical")

    if api_paper:
        if _is_mega9007_demo_desk(desk_id):
            detail = (
                "Demo emir hesabı geçici offline (429/ban veya auth yenileme). "
                "Otomatik recovery deneniyor; fiyat beslemesi devam eder."
            )
        else:
            detail = (
                "Gerçek emir gitmiyor. Mainnet için BN_FUT_MODE=live, demo bayrakları=0 "
                "ve geçerli mainnet API anahtarı gerekir."
            )
        alerts.append(
            {
                "level": "warn",
                "code": "paper_mode",
                "title": "Paper / simülasyon modu",
                "detail": detail,
            }
        )
        bump("warn")

    if (
        "demo-fapi" in endpoint
        and not api_paper
        and not _is_mega9007_demo_desk(desk_id)
        and not _is_mega9006_demo_live_desk(desk_id)
    ):
        alerts.append(
            {
                "level": "warn",
                "code": "demo_endpoint",
                "title": "Demo API uç noktası",
                "detail": (
                    "demo-fapi.binance.com kullanılıyor. Canlı işlem için mainnet anahtarı + "
                    "MEGA_BINANCE_FUTURES_DEMO=0 ayarlayın. Demo panelde IP whitelist yoktur."
                ),
            }
        )
        bump("warn")

    try:
        from elite_trader.network_guard import is_degraded, degraded_remaining_sec

        if is_degraded():
            sec = round(degraded_remaining_sec(), 1)
            alerts.append(
                {
                    "level": "warn",
                    "code": "network_degraded",
                    "title": "Ağ koruması aktif (REST yavaşlatıldı)",
                    "detail": f"Son hatalardan sonra REST {sec}s bekletiliyor — ban riskini azaltır.",
                }
            )
            bump("warn")
    except Exception:
        pass

    if _last_error and not ip_ban_active() and not auth_error:
        age = time.time() - _last_error_ts
        if age < 120:
            code = _error_code(_last_error)
            if code == "-1003":
                pass
            elif code in ("-2015",) and api_ok and not api_paper:
                pass
            elif code == "-1007":
                alerts.append(
                    {
                        "level": "warn",
                        "code": "order_timeout",
                        "title": "Emir zaman aşımı (-1007)",
                        "detail": (
                            "Binance yanıtı gecikti; emir gitmiş veya gitmemiş olabilir. "
                            "Bot positionRisk ve işlem geçmişi ile doğrular — "
                            "aynı pozisyon için manuel tekrar kapatmayın."
                        ),
                    }
                )
                bump("warn")
            else:
                alerts.append(
                    {
                        "level": "warn",
                        "code": "recent_error",
                        "title": "Son Binance hatası",
                        "detail": _last_error[:200],
                    }
                )
                bump("warn")

    return {
        "ok": severity == "ok",
        "severity": severity,
        "alerts": alerts,
        "binance": {
            "api_ok": api_ok,
            "api_paper": api_paper,
            "endpoint": endpoint,
            "auth_error": auth_error,
            "ip_ban_active": ip_ban_active(),
            "ip_ban_until_ms": ip_ban_until_ms(),
            "last_ok_ts": _last_ok_ts or None,
            "open_positions": open_positions,
        },
        "ts": time.time(),
    }
