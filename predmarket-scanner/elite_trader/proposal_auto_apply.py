"""Öğrenme önerileri — onaylanabilir olanları otomatik senaryoya uygula."""
from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SCENARIO = _ROOT / "scenarios" / "binance_elite_8300_9005.env"

# Otomatik uygulanabilir (düşük risk / kullanıcı onayı önceden)
DEFAULT_AUTO_RULES = frozenset(
    {
        "sl_instant_no_emergency",
        "spike_quick_scalp",
    }
)

# rule_id → yalnızca bu anahtarlar yazılsın (öneride fazla anahtar olsa bile)
RULE_ENV_KEYS: dict[str, frozenset[str]] = {
    "sl_instant_no_emergency": frozenset({"ELITE_SL_EMERGENCY_MULT"}),
    "spike_quick_scalp": frozenset(
        {
            "ELITE_SPIKE_QUICK_TP_ENABLED",
            "ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC",
            "ELITE_SPIKE_QUICK_TP_FEE_MULT",
            "ELITE_SPIKE_QUICK_TP_MAX_FRAC",
            "ELITE_POSITION_CHECK_SEC",
            "ELITE_STALE_TP_ENABLED",
            "ELITE_STALE_TP_MIN_AGE_MIN",
            "ELITE_STALE_MODE",
        }
    ),
}

# Senaryoda değiştirilebilir anahtarlar
ALLOWED_ENV_KEYS = frozenset(
    {
        "ELITE_SL_EMERGENCY_MULT",
        "ELITE_MIN_HOLD_BEFORE_SL_SEC",
        "ELITE_STALE_TP_ENABLED",
        "ELITE_STALE_TP_MIN_AGE_MIN",
        "ELITE_STALE_MODE",
        "ELITE_SPIKE_QUICK_TP_ENABLED",
        "ELITE_SPIKE_QUICK_TP_MIN_AGE_SEC",
        "ELITE_SPIKE_QUICK_TP_FEE_MULT",
        "ELITE_SPIKE_QUICK_TP_MAX_FRAC",
        "ELITE_POSITION_CHECK_SEC",
        "ELITE_SCAN_INTERVAL_SEC",
    }
)


def _env_rules() -> set[str]:
    raw = os.getenv("ELITE_LEARNER_AUTO_APPLY_RULES", "").strip()
    if raw:
        return {x.strip() for x in raw.split(",") if x.strip()}
    return set(DEFAULT_AUTO_RULES)


def auto_apply_enabled() -> bool:
    return os.getenv("ELITE_LEARNER_AUTO_APPLY", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _min_priority() -> int:
    try:
        return int(os.getenv("ELITE_LEARNER_AUTO_APPLY_MIN_PRIORITY", "8"))
    except ValueError:
        return 8


def _scenario_env_map() -> dict[str, str]:
    out: dict[str, str] = {}
    if not _SCENARIO.is_file():
        return out
    for line in _SCENARIO.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def proposal_satisfied(proposal: dict[str, Any]) -> bool:
    """Önerilen değerler senaryoda zaten var mı."""
    cur = _scenario_env_map()
    suggested = proposal.get("suggested_env") or {}
    if not suggested:
        return False
    for key, val in suggested.items():
        if key not in ALLOWED_ENV_KEYS:
            continue
        if cur.get(key) != str(val):
            return False
    return True


def is_approvable(proposal: dict[str, Any]) -> bool:
    """Manuel bekletme yerine otomatik onay için yeterli mi."""
    if proposal.get("status") != "pending":
        return False
    rule = str(proposal.get("rule_id") or "")
    if rule in _env_rules():
        return True
    return int(proposal.get("priority") or 0) >= _min_priority()


def apply_proposal_to_scenario(proposal: dict[str, Any]) -> bool:
    """Önerilen env satırlarını senaryo dosyasına yaz (whitelist)."""
    suggested = proposal.get("suggested_env") or {}
    if not suggested or not _SCENARIO.is_file():
        return False
    lines = _SCENARIO.read_text(encoding="utf-8").splitlines()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = _ROOT / "data" / "backups" / f"env_apply_{stamp}.env.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_SCENARIO, backup)

    rule = str(proposal.get("rule_id") or "")
    allowed_keys = RULE_ENV_KEYS.get(rule, ALLOWED_ENV_KEYS)
    changed: list[str] = []
    for key, val in suggested.items():
        if key not in ALLOWED_ENV_KEYS or key not in allowed_keys:
            continue
        pat = re.compile(rf"^{re.escape(key)}=.*")
        new_line = f"{key}={val}"
        found = False
        for i, line in enumerate(lines):
            if pat.match(line):
                if line != new_line:
                    lines[i] = new_line
                    changed.append(key)
                found = True
                break
        if not found:
            lines.append(new_line)
            changed.append(key)

    if not changed:
        return False
    _SCENARIO.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for key in changed:
        for k, v in suggested.items():
            if k == key:
                os.environ[k] = str(v)
                break
    print(
        f"  ✅ Otomatik uygulandı [{proposal.get('rule_id')}]: "
        + ", ".join(changed)
        + f" (yedek: {backup.relative_to(_ROOT)})"
    )
    return True


def maybe_auto_apply_pending() -> int:
    if not auto_apply_enabled():
        return 0
    from elite_trader.loss_learner import list_proposals, set_proposal_status

    n = 0
    for p in list_proposals(status="pending"):
        if not is_approvable(p):
            continue
        applied = apply_proposal_to_scenario(p)
        if applied or proposal_satisfied(p):
            set_proposal_status(str(p["id"]), "approved")
            p["auto_applied"] = True
            n += 1
    return n


def ensure_spike_quick_proposal() -> None:
    from elite_trader.loss_learner import ensure_bootstrap_proposals

    ensure_bootstrap_proposals()
