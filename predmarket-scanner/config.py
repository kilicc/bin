"""Central configuration. Reads .env, exposes typed settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).parent

# override=False: run_live_scanner.sh ortam değişkenlerini .env ile ezmez
load_dotenv(override=False)
# Paper $22k: shell/conda STARTING_BALANCE=20 → .env (ana panel). Senaryo panelleri ezilmez.
_env_file = ROOT / ".env"
if _env_file.is_file():
    _from_env = dotenv_values(_env_file)
    if _from_env.get("STARTING_BALANCE") and not (
        os.getenv("SCENARIO_NAME") or os.getenv("PAPER_DB_PATH")
    ):
        os.environ["STARTING_BALANCE"] = str(_from_env["STARTING_BALANCE"])
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

_POLY_LIVE_FLAG = os.getenv("POLYMARKET_LIVE_TRADING", "0").strip().lower() in ("1", "true", "yes")
_POLY_LIVE_PHRASE = os.getenv("POLYMARKET_LIVE_CONFIRM", "").strip()
_POLY_LIVE_REQUIRED = "I_UNDERSTAND_REAL_MONEY_LOSS"


@dataclass(frozen=True)
class Settings:
    mode: str = os.getenv("MODE", "paper")
    """Polymarket CLOB gerçek emir — POLYMARKET_LIVE_TRADING=1 ve POLYMARKET_LIVE_CONFIRM tam eşleşme."""
    polymarket_live_armed: bool = _POLY_LIVE_FLAG and (_POLY_LIVE_PHRASE == _POLY_LIVE_REQUIRED)
    live_db: Path = Path(os.getenv("LIVE_DB_PATH", str(DATA_DIR / "live.db")))
    edge_threshold: float = float(os.getenv("EDGE_THRESHOLD", "0.06"))
    max_position_usd: float = float(os.getenv("MAX_POSITION_USD", "50"))
    kelly_fraction: float = float(os.getenv("KELLY_FRACTION", "0.25"))
    scan_interval_sec: int = int(os.getenv("SCAN_INTERVAL_SEC", "60"))

    # Likidite filtresi
    min_volume_24h: float = 1_000.0   # USD
    min_price: float = 0.05            # < 5c kontratları yoksay (gürültü)
    max_price: float = 0.95            # > 95c benzer şekilde

    # Zaman filtresi
    max_hours_to_close: float = float(os.getenv("MAX_HOURS_TO_CLOSE", "720"))  # 30 gün
    min_hours_to_close: float = float(os.getenv("MIN_HOURS_TO_CLOSE", "2"))    # 2 saat

    # Risk yönetimi — stake yüzdesi bazlı TP/SL
    take_profit_stake_pct: float = float(os.getenv("TAKE_PROFIT_STAKE_PCT", "0.035"))
    stop_loss_stake_pct:   float = float(os.getenv("STOP_LOSS_STAKE_PCT",   "0.035"))
    stop_loss_threshold: float = float(os.getenv("STOP_LOSS_THRESHOLD", "0.15"))
    # Likidite filtresi
    max_spread: float = float(os.getenv("MAX_SPREAD", "0.04"))

    # API
    polymarket_base: str = "https://gamma-api.polymarket.com"
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = "claude-sonnet-4-6"

    # Paper trading
    paper_starting_balance: float = float(os.getenv("STARTING_BALANCE", "22000"))
    paper_db: Path = Path(
        os.getenv("PAPER_DB_PATH", str(DATA_DIR / "paper.db"))
    )


settings = Settings()


def assert_paper_mode() -> None:
    """Kazara canlı emir veya MODE=live ile paper-only kod yollarını karıştırmayı önler."""
    if settings.polymarket_live_armed:
        return
    if settings.mode != "paper":
        raise RuntimeError(
            f"Mode='{settings.mode}'. Polymarket canlı emir devre dışı. "
            "Paper: MODE=paper. Canlı CLOB: POLYMARKET_LIVE_TRADING=1 ve "
            f"POLYMARKET_LIVE_CONFIRM={_POLY_LIVE_REQUIRED} — ayrıca momentum_scanner + live_clob kurulumu gerekir."
        )
