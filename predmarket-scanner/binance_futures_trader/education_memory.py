"""Eğitim bilgi deposu — sadece kayıtlı eğitim içeriğinden çıkarım.

Dış kaynaklardan gelen bilgilerle sistem ayarı değiştirilmez.
Çelişki veya belirsizlik: çıkarım yapılmaz, log'a not düşülür.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from binance_futures_trader import config as cfg

EDU_DIR = cfg.ROOT / "data" / "education"
KNOWLEDGE_PATH = EDU_DIR / "trader_knowledge.json"
VARIANTS_PATH = EDU_DIR / "strategy_variants.json"
GITHUB_PATH = EDU_DIR / "github_projects.json"
INFERENCES_PATH = EDU_DIR / "inferences.jsonl"
BEST_STRATEGY_PATH = EDU_DIR / "best_strategy.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_knowledge() -> dict[str, Any]:
    return _load_json(KNOWLEDGE_PATH)


def load_variants() -> list[dict[str, Any]]:
    data = _load_json(VARIANTS_PATH)
    return list(data.get("variants") or [])


def load_github_projects() -> dict[str, Any]:
    return _load_json(GITHUB_PATH)


def log_inference(
    topic: str,
    conclusion: str,
    *,
    evidence_ids: list[str] | None = None,
    blocked: bool = False,
    reason: str = "",
) -> None:
    """Çıkarımı kalıcı log'a yaz (eğitim deposundan türetilmiş)."""
    EDU_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "conclusion": conclusion,
        "evidence_ids": evidence_ids or [],
        "blocked": blocked,
        "reason": reason,
    }
    with INFERENCES_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    if blocked:
        return
    kn = load_knowledge()
    log = kn.setdefault("inferences_log", [])
    log.append(row)
    if len(log) > 500:
        kn["inferences_log"] = log[-500:]
    KNOWLEDGE_PATH.write_text(
        json.dumps(kn, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def ta_params_for_module(module: str) -> dict[str, Any]:
    """Eğitim deposundaki TA parametrelerini döndür."""
    kn = load_knowledge()
    concepts = kn.get("ta_concepts") or {}
    return dict(concepts.get(module) or {})


def risk_rules() -> list[dict[str, Any]]:
    kn = load_knowledge()
    return list(kn.get("risk_rules") or [])


def strategy_weights_from_education() -> dict[str, float]:
    """Eğitimde vurgulanan modüllere başlangıç ağırlığı (learner ile birleştirilebilir)."""
    kn = load_knowledge()
    concepts = kn.get("ta_concepts") or {}
    weights: dict[str, float] = {}
    priority = {
        "RSI": 1.15,
        "EMA": 1.12,
        "BB": 1.08,
        "MACD": 1.10,
        "MOM": 1.05,
        "MOM3": 1.05,
        "VOL": 1.0,
        "FG": 0.85,
        "FUND": 0.9,
        "BURST": 1.0,
        "ADX": 1.08,
        "STOCH": 1.06,
        "EMA200": 1.10,
        "CEX_ARB": 0.7,
        "GAP": 0.75,
        "FLOW": 0.8,
        "NEWS": 0.75,
    }
    gh = load_github_projects()
    for rule in gh.get("synthesized_rules") or []:
        rid = rule.get("id")
        if rid == "gh_high_confluence":
            priority["RSI"] = max(priority["RSI"], 1.12)
            priority["EMA"] = max(priority["EMA"], 1.12)
    for name, mod in concepts.items():
        key = str(mod.get("module") or name)
        weights[key] = priority.get(key, 1.0)
    return weights


def save_best_strategy(variant_id: str, report: dict[str, Any]) -> None:
    EDU_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "variant_id": variant_id,
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "source": "education_backtest_6m",
        "report_summary": report,
    }
    BEST_STRATEGY_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log_inference(
        "best_strategy_selection",
        f"Seçilen varyant: {variant_id}",
        evidence_ids=[variant_id],
    )


def load_best_strategy() -> dict[str, Any]:
    return _load_json(BEST_STRATEGY_PATH)


def apply_education_to_learner_weights(
    base: dict[str, float],
) -> dict[str, float]:
    """Mevcut learner ağırlıkları × eğitim öncelikleri (sadece çarpım, dış kaynak yok)."""
    edu = strategy_weights_from_education()
    out = dict(base)
    for k, v in edu.items():
        if k in out:
            out[k] = round(min(1.55, max(0.30, out[k] * v)), 4)
    return out
