"""Claude-based probability estimator — DEMO ONLY.

UYARI: Bu estimator tweet'teki "Claude tahmin etsin" yaklaşımının somut hali.
Production'da YETERSİZ:
  - LLM olasılık kalibrasyonu zayıftır (overconfident).
  - Bilgi cutoff'una bağlı; canlı haber/oran feed'i yok.
  - Aynı prompt'a farklı zamanda farklı sayı dönebilir (variance high).
  - Sample size yetersizken Brier skoru baseline'ı (market price) bile yenmez.

Yine de scanner'ın gerçekten uçtan uca çalıştığını göstermek için içerdik.
Kullanırken: temperature=0, tek bir sayı iste, JSON'a parse et, klip.
Asla canlı parayla bu estimator'a güvenme. Önce backtest + kalibrasyon.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from markets.base import Market

from .base import ProbabilityEstimate, ProbabilityEstimator


SYSTEM_PROMPT = """You estimate calibrated probabilities for prediction-market questions.

Rules:
- Output ONLY a single JSON object: {"p": <float in [0,1]>, "c": <float in [0,1]>, "why": "<<=20 words>"}.
- p = your honest probability that the YES side resolves true.
- c = your confidence in that probability (0=guess, 1=certain).
- If you lack information, return p close to the market price and c<=0.2.
- Do NOT add commentary or markdown."""


class ClaudeEstimator(ProbabilityEstimator):
    name = "claude_llm"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY missing — Claude estimator devre dışı.")
        # Lazy import — anthropic SDK opsiyonel kalsın
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def estimate(self, market: Market) -> Optional[ProbabilityEstimate]:
        p_market = market.yes_price
        if p_market is None:
            return None

        user = (
            f"Question: {market.question}\n"
            f"Category: {market.category or 'unknown'}\n"
            f"Resolves by: {market.end_date.isoformat() if market.end_date else 'unknown'}\n"
            f"Current market price for YES: {p_market:.3f}\n"
            f"24h volume: ${market.volume_24h:,.0f}\n\n"
            f"Return JSON only."
        )

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=120,
                temperature=0.0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(
                block.text for block in msg.content if getattr(block, "type", "") == "text"
            )
            parsed = _extract_json(text)
            if parsed is None:
                return None
            return ProbabilityEstimate(
                market_id=market.market_id,
                true_prob=float(parsed.get("p", p_market)),
                confidence=float(parsed.get("c", 0.1)),
                rationale=str(parsed.get("why", ""))[:120],
                source=self.name,
            )
        except Exception as e:
            # Sessizce skip — scanner devam etsin
            print(f"[claude_llm] error for {market.market_id}: {e}")
            return None


def _extract_json(text: str) -> Optional[dict]:
    """Model bazen markdown bloğu içine atıyor; ilk { … } bloğunu çek."""
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
