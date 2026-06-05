"""Plan panosu danışman — sekreter / akıl hocası (Cursor + hafıza)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from elite_trader.plan_memory import memory_summary_for_prompt

_LIVE_ID = "sentinel"
_ROOT = Path(__file__).resolve().parent.parent
_POSTMORTEM = _ROOT / "data" / "elite_9005_loss_postmortem.json"

ADVISOR_SYSTEM_PROMPT = """Sen Binance Elite 9005 ticaret sisteminin kişisel strateji danışmanı, sekreter ve akıl hocasısın.

KİMLİK
- Türkçe konuş; samimi, net, insan gibi. Robot veya formül dili kullanma.
- Kullanıcıya "siz" diye hitap et. Kısa paragraflar; gerektiğinde madde işaretleri.
- Teknik env değişken adı, JSON, kod bloğu yazma — sadece anlaşılır Türkçe.

BİLGİN
- Ana Hat: canlı borsa motoru (gerçek işlemler).
- Paralel evrenler (Avcı, Şimşek, Kalkan): aynı piyasayı tarar; farklı giriş/çıkış kurallarıyla paper kitap.
- Verilen bağlamdaki rakamlar gerçektir; uydurma sayı üretme.
- Geçmiş öğrenme notlarına saygı göster; tutarlı kal.

GÖREVİN
- Zararları mod mod anlat; neden olmuş olabileceğini yorumla.
- "Zararlar olmasaydı kâr ne olurdu" gibi sorularda verilen hypothetic rakamı kullan.
- Strateji planı öner; riskleri söyle; acele uygulama baskısı yapma.
- Her cevabın sonunda 1–4 maddelik "Yapılacaklar" özeti ver (kısa başlıklar).

SINIRLAR
- Bu sohbette ayar DOSYAYA yazılmaz. Kullanıcı ayrıca «Uygula» + PIN ile onaylar.
- Emin olmadığın yerde varsayımı söyle ve soru sor.
- Sadece matematik formülü dökmek yerine yorum + eylem öner."""

_KEY_LABELS: dict[str, str] = {
    "ELITE_MIN_EDGE": "Giriş eşiği",
    "entry_min_edge_mult": "Giriş sıkılığı",
    "spike_enabled": "Spike çıkışı",
}


def fmt_pct(val: Any) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):.1f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_usd(val: Any) -> str:
    try:
        v = float(val)
        return f"+{v:.0f}$" if v >= 0 else f"{v:.0f}$"
    except (TypeError, ValueError):
        return "0$"


def hypothetical_without_losses(
    reports: dict[str, dict[str, Any]],
    dash: dict[str, Any],
    focus_mode: str | None,
) -> str | None:
    """Zararlar olmasaydı oturum/mod PnL tahmini."""
    if not focus_mode or focus_mode not in reports:
        return None
    rep = reports[focus_mode]
    loss_sum = float(rep.get("total_loss_usd") or 0)
    if loss_sum >= 0:
        return None
    mode_row = next(
        (m for m in (dash.get("modes") or []) if m.get("mode_id") == focus_mode),
        {},
    )
    current = float(mode_row.get("total_pnl") or 0)
    hypo = current - loss_sum
    label = rep.get("label") or focus_mode
    return (
        f"{label} için şu an görünen toplam {fmt_usd(current)}. "
        f"Kayıplı işlemlerin toplamı {fmt_usd(loss_sum)} — bunlar olmasaydı "
        f"yaklaşık {fmt_usd(hypo)} civarında olurdu (gerçekleşen kârlar aynı kaldığı varsayımıyla). "
        "Bu bir simülasyon; geçmiş işlemler değişmez."
    )


def build_rich_context(
    dash: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    *,
    focus_mode: str | None = None,
    snapshot: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []
    sess = dash.get("session") or {}
    parts.append(
        f"OTURUM: {sess.get('closed_trades', 0)} kapanan, başarı {fmt_pct(sess.get('win_rate'))}, "
        f"PnL {fmt_usd(sess.get('total_pnl'))}, açık {sess.get('open_count', 0)}."
    )
    parts.append("\nMODLAR:")
    for mid in [_LIVE_ID, "hunter", "berserk", "chop_master", "evrim"]:
        rep = reports.get(mid)
        if not rep:
            continue
        mrow = next((m for m in (dash.get("modes") or []) if m.get("mode_id") == mid), {})
        parts.append(
            f"- {rep.get('label')}: PnL {fmt_usd(mrow.get('total_pnl'))}, "
            f"{rep.get('loss_count', 0)} zararlı kapanış, başarı {fmt_pct(rep.get('win_rate'))}. "
            f"{rep.get('analysis', '')}"
        )
    hypo = hypothetical_without_losses(reports, dash, focus_mode)
    if hypo:
        parts.append(f"\nSİMÜLASYON: {hypo}")
    if _POSTMORTEM.is_file():
        try:
            pm = json.loads(_POSTMORTEM.read_text(encoding="utf-8"))
            s = pm.get("summary") or {}
            parts.append(
                f"\nANA HAT GEÇMİŞ POSTMORTEM: {s.get('total_losses', 0)} zarar kaydı, "
                f"toplam {s.get('total_loss_usd', 0):.0f}$."
            )
        except Exception:
            pass
    mem = memory_summary_for_prompt()
    parts.append(f"\nHAFIZA (önceki konuşmalardan):\n{mem}")
    if snapshot:
        ps = (snapshot.get("elite") or {}).get("panel_strategy") or {}
        parts.append(
            f"\nPANEL: görünüm {ps.get('view_label')}, motor {ps.get('execution_label')}."
        )
    return "\n".join(parts)


def build_action_items(
    reports: dict[str, dict[str, Any]],
    *,
    focus_mode: str | None = None,
    preview: dict[str, Any] | None = None,
    suggested_scope: str = "parallel",
    suggested_mode: str | None = None,
) -> tuple[list[dict[str, str]], str]:
    items: list[dict[str, str]] = []
    detail_parts: list[str] = []

    if preview and preview.get("ok"):
        mode_lbl = suggested_mode or "mod"
        try:
            from elite_trader.panel_strategy import mode_catalog

            mode_lbl = mode_catalog().get(suggested_mode or "", {}).get("label") or mode_lbl
        except Exception:
            pass
        for k, v in (preview.get("after") or {}).items():
            lbl = _KEY_LABELS.get(k, k.replace("_", " "))
            before = preview.get("before", {}).get(k)
            items.append(
                {
                    "title": f"{lbl} ayarla",
                    "detail": f"{before} → {v}",
                    "mode": mode_lbl,
                    "priority": "uygula",
                }
            )
        detail_parts.append("Uygulanmayı bekleyen ayarlar:\n")
        for it in items:
            detail_parts.append(f"• {it['title']}: {it['detail']}")

    focus_reports = (
        {focus_mode: reports[focus_mode]}
        if focus_mode and focus_mode in reports
        else reports
    )
    for _mid, rep in focus_reports.items():
        if not rep or not rep.get("loss_count"):
            continue
        label = rep.get("label") or _mid
        em = (rep.get("by_exit_reason") or {}).get("SL-EMERGENCY", {})
        if em.get("count", 0) >= 2:
            items.append(
                {
                    "title": f"{label}: acil stopları azalt",
                    "detail": f"{em.get('count')} acil kapanış — giriş veya SL bandı gözden geçirilmeli.",
                    "mode": label,
                    "priority": "yüksek",
                }
            )
        detail_parts.append(f"\n{label} detay:\n{rep.get('analysis', '')}")
        for row in rep.get("top_losses") or []:
            detail_parts.append(
                f"  · {row.get('symbol')} {row.get('side')} {row.get('pnl')}$ ({row.get('reason')})"
            )

    if not items:
        items.append(
            {
                "title": "İzlemeye devam",
                "detail": "Acil aksiyon yok; yeni veri gelince tekrar değerlendir.",
                "mode": "—",
                "priority": "düşük",
            }
        )
    return items[:6], "\n".join(detail_parts)


def _rule_reply(
    prompt: str,
    dash: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    focus_mode: str | None,
    *,
    can_apply: bool,
) -> str:
    t = prompt.lower()
    if re.search(r"merhaba|selam|yardım|nasılsın", t):
        return (
            "Merhaba — analiz köşenizdeyim. Modlarınızı, zararları ve strateji fikirlerinizi "
            "birlikte konuşabiliriz. Ayarı sisteme yazmak isterseniz önce burada netleştiririz, "
            "sonra siz «Uygula» ve PIN ile onaylarsınız. Ne üzerinde düşünüyorsunuz?"
        )
    hypo = hypothetical_without_losses(reports, dash, focus_mode)
    if hypo and re.search(r"olmasaydı|hariç|çıkarma|without|simüle|what if", t):
        return hypo + "\n\nİsterseniz bu modda hangi işlemlerin tekrarlandığını da tek tek sayabilirim."
    rep = reports.get(focus_mode) if focus_mode else None
    if rep and re.search(r"zarar|kayıp|kötü|incele|neden|sl", t):
        lines = [
            f"{rep.get('label')} tarafına baktım. {rep.get('loss_count', 0)} kayıplı işlem var, "
            f"toplam zarar {fmt_usd(rep.get('total_loss_usd'))}, başarı {fmt_pct(rep.get('win_rate'))}.",
        ]
        for r in (rep.get("top_losses") or [])[:4]:
            lines.append(
                f"• {r.get('symbol')} ({r.get('side')}): {r.get('pnl')}$ — {r.get('reason')}"
            )
        lines.append("Aşağıdaki yapılacaklar listesine ve «Detaylı rapor»a bakabilirsiniz.")
        return "\n".join(lines)
    if re.search(r"olmasaydı|hariç|çıkarma|without|simüle|what if", t):
        hypo = hypothetical_without_losses(reports, dash, focus_mode)
        if hypo:
            return hypo
    if re.search(r"durum|özet|rapor", t):
        lines = [build_rich_context(dash, reports, focus_mode=focus_mode)[:700]]
        lines.append("Daha derinlemesine bir mod adı yazarsanız odaklanırım.")
        return "\n".join(lines)
    if can_apply:
        return (
            "İsteğinize uygun bir ayar paketi hazır. Listeyi kontrol edin; "
            "onaylıyorsanız PIN girip «Uygula»ya basın."
        )
    return (
        "Sizi dinliyorum. Mod seçerek veya mod adı yazarak (Ana Hat, Avcı…) daha net analiz verebilirim."
    )


def _valid_anthropic_key(key: str) -> bool:
    k = (key or "").strip()
    return k.startswith("sk-ant-") and len(k) > 24


def _plan_backend() -> str:
    return (os.getenv("ELITE_PLAN_BACKEND") or "cursor").strip().lower()


def resolve_anthropic_key() -> str:
    """Geçerli API anahtarı (.env — geçersiz anahtar kullanılmaz)."""
    key = (os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY") or "").strip()
    if _valid_anthropic_key(key):
        return key
    return ""


def advisor_status() -> dict[str, Any]:
    backend = _plan_backend()
    if backend in ("cursor", "cursor_sdk", ""):
        from elite_trader.plan_cursor_bridge import cursor_status

        st = cursor_status()
        acc = st.get("account") or {}
        return {
            "mode": st.get("mode", "cursor"),
            "backend": "cursor",
            "llm_active": bool(st.get("llm_active")),
            "label": st.get("label", "Cursor danışman"),
            "hint": st.get("hint", ""),
            "transcript_bound": st.get("transcript_bound"),
            "session": st.get("session"),
            "account_email": acc.get("email"),
            "account_tier": acc.get("tier"),
            "account_linked": acc.get("linked") or acc.get("cli_logged_in"),
        }
    key = resolve_anthropic_key()
    llm_on = os.getenv("ELITE_PLAN_LLM", "1").strip().lower() not in ("0", "false", "no")
    if not llm_on:
        return {
            "mode": "local",
            "backend": "anthropic",
            "llm_active": False,
            "label": "Yerel danışman",
            "hint": "Claude kapalı (ELITE_PLAN_LLM=0). Tam analiz yerel motorda.",
        }
    if not key:
        return {
            "mode": "local",
            "backend": "anthropic",
            "llm_active": False,
            "label": "Yerel danışman",
            "hint": (
                "Claude API anahtarı yok veya geçersiz. "
                "ELITE_PLAN_BACKEND=cursor ile Cursor kullanın."
            ),
        }
    return {
        "mode": "claude",
        "backend": "anthropic",
        "llm_active": True,
        "label": "Canlı danışman (Claude)",
        "hint": "Claude bağlı — ELITE_PLAN_BACKEND=anthropic.",
    }


def advisor_reply(
    prompt: str,
    *,
    dash: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    focus_mode: str | None = None,
    history: list[dict[str, str]] | None = None,
    snapshot: dict[str, Any] | None = None,
    can_apply: bool = False,
) -> tuple[str, dict[str, Any]]:
    """(yanıt metni, danışman durumu)."""
    status = advisor_status()
    ctx = build_rich_context(dash, reports, focus_mode=focus_mode, snapshot=snapshot)
    backend = _plan_backend()

    if backend in ("cursor", "cursor_sdk", ""):
        from elite_trader.plan_cursor_bridge import cursor_reply

        try:
            text, status = cursor_reply(
                prompt,
                system=ADVISOR_SYSTEM_PROMPT,
                context=ctx,
                history=history,
            )
            if text:
                return text, status
        except Exception:
            status = {
                **status,
                "llm_active": False,
                "label": "Yerel danışman",
                "hint": "Cursor geçici olarak kullanılamıyor; yerel analiz devam ediyor.",
            }
    elif status.get("llm_active"):
        key = resolve_anthropic_key()
        if key:
            try:
                text = _llm_reply(prompt, ctx, history or [], key)
                if text:
                    return text, status
            except Exception as exc:
                err = str(exc).lower()
                if "401" in err or "authentication" in err or "invalid" in err and "api" in err:
                    status = {
                        "mode": "local",
                        "llm_active": False,
                        "label": "Yerel danışman",
                        "hint": (
                            "Claude API anahtarı reddedildi. "
                            "Yanıtlar yerel danışman ile üretiliyor."
                        ),
                    }
                else:
                    status = {
                        **status,
                        "llm_active": False,
                        "label": "Yerel danışman",
                        "hint": "Claude geçici olarak kullanılamıyor; yerel analiz devam ediyor.",
                    }
    text = _rule_reply(prompt, dash, reports, focus_mode, can_apply=can_apply)
    if not status.get("llm_active") and "Sizi dinliyorum" in text:
        bound = status.get("transcript_bound")
        if status.get("mode") == "cursor_context" or bound:
            text = (
                "Merhaba — Cursor IDE oturumunuz panele bağlı (bağlam paylaşımlı). "
                "Canlı Cursor yanıtı için .env içine CURSOR_API_KEY ekleyin. "
                "Şimdilik yerel analizle devam ediyorum — ne incelememi istersiniz?"
            )
        else:
            text = (
                "Merhaba — ben sizin strateji danışmanınızım (yerel mod). "
                "Modlarınızın verisine erişiyorum; zarar, plan ve ayar fikirlerini konuşabiliriz. "
                "Ne incelememi istersiniz?"
            )
    return text, status


def _llm_reply(
    prompt: str,
    context: str,
    history: list[dict[str, str]],
    api_key: str,
) -> str | None:
    from anthropic import Anthropic

    messages: list[dict[str, str]] = []
    for h in history[-10:]:
        role = h.get("role")
        if role == "user":
            messages.append({"role": "user", "content": h.get("content", "")[:2000]})
        elif role in ("assistant", "danışman"):
            messages.append({"role": "assistant", "content": h.get("content", "")[:2000]})
    messages.append(
        {
            "role": "user",
            "content": f"[Güncel sistem verisi]\n{context[:12000]}\n\n[Kullanıcı mesajı]\n{prompt}",
        }
    )
    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=os.getenv("ELITE_PLAN_LLM_MODEL", "claude-sonnet-4-6"),
        max_tokens=1400,
        temperature=0.55,
        system=ADVISOR_SYSTEM_PROMPT,
        messages=messages,
    )
    text = "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    )
    return (text or "").strip() or None
