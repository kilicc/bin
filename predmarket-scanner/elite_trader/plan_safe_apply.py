"""Plan önerilerini uygula — açık pozisyonlara dokunmadan."""
from __future__ import annotations

import os
from typing import Any

from elite_trader.mode_profiles import get_profile
from elite_trader.plan_mode_analysis import rule_based_safe_patch
from elite_trader.plan_modes import LIVE_ID, normalize_mode_id
from elite_trader.settings_registry import (
    apply_live_settings,
    apply_parallel_settings,
    preview_live_patch,
    preview_parallel_patch,
)

# Ana Hat: yalnızca yeni giriş/çıkış eşiği — açık stake/SL dokunulmaz
_LIVE_SAFE_KEYS = frozenset(
    {
        "ELITE_MIN_EDGE",
        "ELITE_MIN_FORMULA_SCORE",
        "ELITE_SPIKE_QUICK_TP_ENABLED",
        "ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC",
        "ELITE_SPIKE_QUICK_TP_FEE_MULT",
        "ELITE_STALE_TP_ENABLED",
        "ELITE_STALE_TP_MIN_AGE_MIN",
        "ELITE_MARKET_COOLDOWN_MIN",
        "ELITE_SL_EM_VETO_COUNT",
        "ELITE_SL_EM_COOLDOWN_MIN",
        "ELITE_SL_EM_EXTRA_EDGE",
        "ELITE_SL_EM_EXTRA_FORMULA",
        "ELITE_MIN_HOLD_BEFORE_SL_SEC",
    }
)

_PARALLEL_SAFE_KEYS = frozenset(
    {
        "entry_min_edge_mult",
        "entry_min_formula_mult",
        "entry_min_strength",
        "entry_stake_mult",
        "entry_max_open",
        "entry_skip_cautious",
        "entry_block_weak",
        "tp_stake_pct",
        "sl_stake_pct",
        "tp_trigger_frac",
        "stale_enabled",
        "stale_min_age_min",
        "spike_enabled",
        "spike_min_age_sec",
    }
)


def filter_live_patch(patch: dict[str, Any]) -> dict[str, str]:
    return {k: str(v) for k, v in patch.items() if k in _LIVE_SAFE_KEYS}


def filter_parallel_patch(patch: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in patch.items() if k in _PARALLEL_SAFE_KEYS}


def apply_mode_recommendations(
    mode_id: str,
    bundle: dict[str, Any],
    *,
    auto_parallel: bool | None = None,
) -> dict[str, Any]:
    """
    Kural tabanlı güvenli yama uygular.
    - Paralel: varsayılan otomatik (paper, açık pozisyonları bozmaz)
    - Ana Hat: yalnızca güvenli .env anahtarları; açık emirlere dokunulmaz
    """
    mid = normalize_mode_id(mode_id)
    raw = rule_based_safe_patch(bundle)
    if not raw:
        return {"ok": True, "applied": False, "reason": "no_patch", "mode_id": mid}

    if mid == LIVE_ID:
        safe = filter_live_patch(raw)
        if not safe:
            return {"ok": True, "applied": False, "reason": "no_safe_live_keys", "mode_id": mid}
        preview = preview_live_patch(safe)
        if not preview.get("ok"):
            return {"ok": False, "error": preview.get("error"), "mode_id": mid}
        result = apply_live_settings(safe)
        return {
            "ok": True,
            "applied": True,
            "scope": "live",
            "mode_id": mid,
            "patch": safe,
            "result": result,
            "message": (
                "Ana Hat: güvenli giriş/çıkış eşikleri güncellendi. "
                "Açık pozisyonlara dokunulmadı; restart gerekmez."
            ),
        }

    do_auto = auto_parallel if auto_parallel is not None else (
        os.getenv("ELITE_PLAN_AUTO_APPLY_PARALLEL", "1").strip().lower()
        not in ("0", "false", "no")
    )
    safe = filter_parallel_patch(raw)
    if not safe:
        return {"ok": True, "applied": False, "reason": "no_safe_parallel_keys", "mode_id": mid}
    preview = preview_parallel_patch(mid, safe)
    if not preview.get("ok"):
        return {"ok": False, "error": str(preview.get("error")), "mode_id": mid}
    if not do_auto:
        return {
            "ok": True,
            "applied": False,
            "pending": True,
            "mode_id": mid,
            "patch": safe,
            "preview": preview,
            "message": "Paralel öneri hazır — PIN ile «Uygula» veya otomatik uygulama açık.",
        }
    result = apply_parallel_settings(mid, safe)
    return {
        "ok": True,
        "applied": True,
        "scope": "parallel",
        "mode_id": mid,
        "patch": safe,
        "result": result,
        "message": f"{bundle.get('label', mid)} paper profili güncellendi (açık pozisyonlar aynı kurallarla devam).",
    }
