"""Common types for prediction-market data."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Outcome(BaseModel):
    """Bir piyasanın olası bir çözüm sonucu (Yes/No veya çok kategorili)."""
    name: str
    price: float = Field(..., ge=0.0, le=1.0, description="Market-implied probability, [0,1]")
    token_id: Optional[str] = None  # Polymarket CLOB için outcome token id


class Market(BaseModel):
    """Prediction market kontratı."""
    venue: str                        # "polymarket" | "kalshi" | ...
    market_id: str
    question: str                     # Doğal dil event sorusu
    category: Optional[str] = None    # "crypto" | "politics" | "weather" | ...
    end_date: Optional[datetime] = None
    volume_24h: float = 0.0
    liquidity: float = 0.0
    outcomes: list[Outcome] = Field(default_factory=list)
    url: Optional[str] = None
    raw: dict = Field(default_factory=dict, exclude=True)  # debug için orijinal payload

    @property
    def yes_price(self) -> Optional[float]:
        """Binary piyasalarda 'Yes' tarafının fiyatı."""
        for o in self.outcomes:
            if o.name.lower() in {"yes", "evet"}:
                return o.price
        # binary fallback: 2 outcome varsa ilki
        if len(self.outcomes) == 2:
            return self.outcomes[0].price
        return None

    def __str__(self) -> str:
        p = self.yes_price
        ptxt = f"{p:.2%}" if p is not None else "?"
        return f"[{self.venue}:{self.category}] {self.question}  yes={ptxt}  vol24h=${self.volume_24h:,.0f}"
