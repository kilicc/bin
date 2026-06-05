"""spread_policy → max spread % (mode engine giriş filtreleri)."""
from __future__ import annotations

SPREAD_POLICY_MAX_PCT: dict[str, float] = {
    "very_soft_penalty": 0.35,
    "soft_penalty": 0.25,
    "medium_penalty": 0.18,
    "hunter_medium_penalty": 0.18,
    "strict_soft": 0.12,
    "strict": 0.08,
    "sentinel_strict": 0.12,
}


def max_spread_for_policy(spread_policy: str | None) -> float:
    key = str(spread_policy or "soft_penalty").strip().lower()
    return SPREAD_POLICY_MAX_PCT.get(key, 0.25)
