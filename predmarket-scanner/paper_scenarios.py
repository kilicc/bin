"""Çoklu paper senaryoları — $110 / $220 / $2200 senkron tarama."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

# Senkron paper TP/SL — insane_24h.env ile hizalı (hızlı dönüş)
SCENARIO_TP = float(os.getenv("TAKE_PROFIT_STAKE_PCT", "0.008"))
SCENARIO_SL = float(os.getenv("STOP_LOSS_STAKE_PCT", "0.038"))
REF_BALANCE = 22_000.0
REF_TARGET_STAKE = 1_000.0


@dataclass(frozen=True)
class PaperScenario:
    name: str
    label: str
    port: int
    db_path: Path
    starting_balance: float
    take_profit_pct: float = SCENARIO_TP
    stop_loss_pct: float = SCENARIO_SL
    target_stake_usd: float = 0.0
    min_stake_usd: float = 5.0
    max_position_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.max_position_usd <= 0:
            object.__setattr__(self, "max_position_usd", self.starting_balance * 0.5)
        if self.target_stake_usd <= 0:
            ratio = self.starting_balance / REF_BALANCE
            tgt = max(self.min_stake_usd, round(REF_TARGET_STAKE * ratio, 2))
            object.__setattr__(self, "target_stake_usd", tgt)


DEFAULT_SCENARIOS: tuple[PaperScenario, ...] = (
    PaperScenario(
        name="paper_110",
        label="Paper $110",
        port=8010,
        db_path=DATA_DIR / "paper_110.db",
        starting_balance=110.0,
        min_stake_usd=5.0,
    ),
    PaperScenario(
        name="paper_220",
        label="Paper $220",
        port=8020,
        db_path=DATA_DIR / "paper_220.db",
        starting_balance=220.0,
        min_stake_usd=5.0,
    ),
    PaperScenario(
        name="paper_2200",
        label="Paper $2200",
        port=8030,
        db_path=DATA_DIR / "paper_2200.db",
        starting_balance=2200.0,
        min_stake_usd=25.0,
    ),
)

def init_scenario_db(scenario: PaperScenario) -> sqlite3.Connection:
    import momentum_scanner as ms

    scenario.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = ms.init_db(scenario.db_path)
    try:
        import backtest_trainer as bt

        bt.init_shadow_db(conn)
    except Exception:
        pass
    conn.close()
    return sqlite3.connect(str(scenario.db_path))


@contextmanager
def apply_scenario(scenario: PaperScenario) -> Iterator[None]:
    """momentum_scanner global'lerini senaryo ayarlarına geçir."""
    import momentum_scanner as ms

    saved: dict[str, Any] = {
        "STARTING_BALANCE": ms.STARTING_BALANCE,
        "TAKE_PROFIT_STAKE_PCT": ms.TAKE_PROFIT_STAKE_PCT,
        "STOP_LOSS_STAKE_PCT": ms.STOP_LOSS_STAKE_PCT,
        "MAX_POS_USD": ms.MAX_POS_USD,
        "FAST_TP_MAX_HOURS": ms.FAST_TP_MAX_HOURS,
        "QUICK_TP_EDGE_MIN": ms.QUICK_TP_EDGE_MIN,
        "NANO_TP_MAX_HOURS": ms.NANO_TP_MAX_HOURS,
    }
    env_saved = {
        "PAPER_TARGET_STAKE_USD": os.environ.get("PAPER_TARGET_STAKE_USD"),
        "PAPER_MIN_POSITION_USD": os.environ.get("PAPER_MIN_POSITION_USD"),
    }
    ms.STARTING_BALANCE = scenario.starting_balance
    ms.TAKE_PROFIT_STAKE_PCT = float(
        os.getenv("TAKE_PROFIT_STAKE_PCT", str(scenario.take_profit_pct))
    )
    ms.STOP_LOSS_STAKE_PCT = float(
        os.getenv("STOP_LOSS_STAKE_PCT", str(scenario.stop_loss_pct))
    )
    ms.MAX_POS_USD = scenario.max_position_usd
    os.environ["PAPER_TARGET_STAKE_USD"] = str(scenario.target_stake_usd)
    os.environ["PAPER_MIN_POSITION_USD"] = str(scenario.min_stake_usd)
    pct = scenario.starting_balance / REF_BALANCE
    if os.getenv("PAPER_MAX_OPEN_STAKE_PCT"):
        pass  # senaryo .env'de tanımlı
    else:
        os.environ["PAPER_MAX_OPEN_STAKE_PCT"] = str(min(0.9, 0.82 * max(1.0, pct * 22)))
    ms._reload_paper_env_globals()
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(ms, k, v)
        for k, v in env_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def load_scenarios() -> list[PaperScenario]:
    raw = (os.getenv("PAPER_SCENARIOS") or "").strip()
    if not raw or raw in ("1", "true", "yes", "default"):
        return list(DEFAULT_SCENARIOS)
    names = [x.strip() for x in raw.split(",") if x.strip()]
    by_name = {s.name: s for s in DEFAULT_SCENARIOS}
    return [by_name[n] for n in names if n in by_name]
