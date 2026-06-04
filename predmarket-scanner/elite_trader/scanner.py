"""Formül tabanlı paper tarayıcı — elite başarı formülü + $800/saat hedef."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from elite_trader.db import init_db, record_attribution
from elite_trader.hourly_pacing import HourlyPacing
from elite_trader.decision_mode import (
    decision_mode,
    entry_allowed,
    mode_label_tr,
    stake_multiplier_from_whale,
)
from elite_trader.market_guards import can_trigger_sl, event_cluster_key, should_veto_entry
from elite_trader.pattern_miner import _market_theme
from elite_trader.pnl_engine import PnLEngine
from elite_trader.research import run_full_research
from elite_trader import scan_stats
from elite_trader.capital_allocator import (
    active_capital_pct,
    compute_stake,
    effective_win_rate,
    snapshot as capital_snapshot,
    wr_stake_multiplier,
)
from elite_trader.performance import rolling_win_rate
from elite_trader.hedge_recovery import (
    RecoveryAction,
    RecoveryPlan,
    evaluate_recovery,
    has_open_hedge,
)
from elite_trader.sparse_stake import compute_sparse_stake, sparse_mode_active, status_line as sparse_status_line
from elite_trader.runtime_status import write_heartbeat
from elite_trader.stale_tp import position_age_seconds, should_close_stale


def position_age_minutes(opened_at: str | None) -> float:
    return position_age_seconds(opened_at) / 60.0
from elite_trader.success_formula import MarketFeatures, SuccessFormula

# momentum_scanner yardımcıları
import momentum_scanner as ms

GAMMA = ms.GAMMA
CLOB = ms.CLOB
def _resolve_db_path() -> Path:
    raw = (os.getenv("PAPER_DB_PATH") or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else ROOT / p
    return ROOT / "data" / "elite_formula.db"


DB_PATH = _resolve_db_path()

def _env_int_load(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, str(default))))
    except (TypeError, ValueError):
        return default


SCAN_INTERVAL = _env_int_load("ELITE_SCAN_INTERVAL_SEC", 15)
MAX_OPEN = _env_int_load("ELITE_MAX_OPEN", 24)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


POSITION_CHECK = _env_float("ELITE_POSITION_CHECK_SEC", 2.0)


def stake_bounds() -> tuple[float, float]:
    """Env her çağrıda — ELITE_MAX_STAKE_USD≤0 → üst sınır yok."""
    return (
        _env_float("ELITE_MIN_STAKE_USD", 150),
        _env_float("ELITE_MAX_STAKE_USD", 600),
    )


def _max_stake_label(max_stake: float) -> str:
    return "sınırsız" if max_stake <= 0 else f"${max_stake:.0f}"


def _portfolio_equity(conn) -> float:
    return _env_float("STARTING_BALANCE", 22000) + _realized_pnl(conn)


def max_open_positions() -> int:
    return _env_int("ELITE_MAX_OPEN", MAX_OPEN)
TP_PCT = float(os.getenv("ELITE_TP_STAKE_PCT", "0.007"))
SL_PCT = float(os.getenv("ELITE_SL_STAKE_PCT", "0.025"))
TP_TRIGGER = float(os.getenv("ELITE_TP_TRIGGER_FRAC", "0.96"))
FORMULA_REFRESH_HOURS = float(os.getenv("ELITE_FORMULA_REFRESH_HOURS", "12"))

_CALIB_BRIER_CACHE: float | None = None


def _load_calibration_brier(sample_n: int = 30_000) -> float | None:
    global _CALIB_BRIER_CACHE
    if _CALIB_BRIER_CACHE is not None:
        return _CALIB_BRIER_CACHE
    path = ROOT / "data" / "calibration_data.pkl"
    if not path.is_file():
        return None
    try:
        import pickle

        data = pickle.load(open(path, "rb"))
        if not data:
            return None
        if len(data) > sample_n:
            step = max(1, len(data) // sample_n)
            data = data[::step][:sample_n]
        preds = [(float(p), bool(o)) for p, _h, o in data]
        if not preds:
            return None
        b = sum((p - (1.0 if o else 0.0)) ** 2 for p, o in preds) / len(preds)
        _CALIB_BRIER_CACHE = round(b, 4)
        return _CALIB_BRIER_CACHE
    except Exception:
        return None


def _realized_pnl(conn) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd),0) FROM positions WHERE closed_at IS NOT NULL"
    ).fetchone()
    return float(row[0] if row else 0)


def open_position(
    conn,
    market_id: str,
    question: str,
    side: str,
    entry_price: float,
    true_prob: float,
    score: float,
    edge: float,
    stake: float,
    formula: SuccessFormula,
    condition_id: str | None = None,
    *,
    theme: str = "",
    hours_left: float = 0.0,
    spread: float = 0.0,
    yes_price_at_entry: float = 0.0,
    score_parts: dict | None = None,
    leg_type: str = "primary",
    hedge_of_id: int | None = None,
) -> int | None:
    contracts = stake / max(1e-6, entry_price)
    now = datetime.now(timezone.utc).isoformat()
    dm = decision_mode()
    rationale = f"elite [{dm}] score={score:.3f} v{formula.version}"
    import json as _json

    parts_json = _json.dumps(score_parts or {}, ensure_ascii=False)
    try:
        conn.execute(
            """
            INSERT INTO positions
            (venue, market_id, question, side, entry_price, true_prob, edge,
             stake_usd, contracts, opened_at, rationale, formula_score,
             formula_version, condition_id, theme, hours_left_at_entry,
             spread_at_entry, yes_price_at_entry, score_parts_json,
             leg_type, hedge_of_id)
            VALUES ('polymarket',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                market_id,
                question[:120],
                side,
                entry_price,
                true_prob,
                edge,
                stake,
                contracts,
                now,
                rationale,
                score,
                formula.version,
                condition_id,
                theme,
                hours_left,
                spread,
                yes_price_at_entry,
                parts_json,
                leg_type,
                hedge_of_id,
            ),
        )
        conn.commit()
        pid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        record_attribution(
            conn,
            pid,
            "open",
            yes_price=yes_price_at_entry,
            score=score,
            parts=score_parts,
        )
        return pid
    except Exception:
        return None


def close_position(
    conn,
    pos_id: int,
    yes_price: float,
    reason: str,
) -> float | None:
    row = conn.execute(
        "SELECT side, entry_price, stake_usd, contracts FROM positions WHERE id=? AND closed_at IS NULL",
        (pos_id,),
    ).fetchone()
    if not row:
        return None
    side = row["side"]
    entry = float(row["entry_price"])
    stake = float(row["stake_usd"])
    contracts = float(row["contracts"] or 0)
    side_close = yes_price if side == "YES" else (1.0 - yes_price)
    pnl = PnLEngine.unrealized(
        side, entry, yes_price, stake, contracts=contracts
    )
    if pnl < 0:
        pnl = PnLEngine.cap_sl_pnl(pnl, stake, SL_PCT)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE positions SET closed_at=?, close_price=?, pnl_usd=?, exit_reason=?,
            yes_price_at_exit=?
        WHERE id=?
        """,
        (now, side_close, round(pnl, 4), reason, yes_price, pos_id),
    )
    record_attribution(
        conn,
        pos_id,
        reason.upper()[:16],
        yes_price=yes_price,
        unrealized_usd=round(pnl, 4),
    )
    conn.commit()
    return pnl


def _try_open_hedge(
    conn: sqlite3.Connection,
    pos: sqlite3.Row,
    yes_cur: float,
    plan: RecoveryPlan,
    *,
    side: str,
) -> bool:
    if plan.action != RecoveryAction.OPEN_HEDGE or has_open_hedge(conn, int(pos["id"])):
        return False
    open_stakes = [
        float(r[0])
        for r in conn.execute(
            "SELECT stake_usd FROM positions WHERE closed_at IS NULL"
        ).fetchall()
    ]
    equity = _portfolio_equity(conn)
    min_stake, max_stake = stake_bounds()
    wr = rolling_win_rate(conn)
    wr_mult = wr_stake_multiplier(effective_win_rate(wr))
    hedge_stake = min(
        plan.hedge_stake * wr_mult,
        compute_stake(
            equity,
            open_stakes,
            kelly_stake=plan.hedge_stake,
            max_open=max_open_positions(),
            min_stake=min_stake,
            max_stake=max_stake,
            win_rate=wr,
        ),
    )
    if hedge_stake < min_stake * 0.5:
        return False
    hp = open_position(
        conn,
        str(pos["market_id"]),
        str(pos["question"] or ""),
        plan.hedge_side or ("NO" if side == "YES" else "YES"),
        plan.hedge_entry or (1.0 - yes_cur if side == "YES" else yes_cur),
        float(pos["true_prob"] or 0.5),
        0.0,
        float(pos["edge"] or 0),
        hedge_stake,
        SuccessFormula.load() or SuccessFormula(),
        theme=str(pos["theme"] or ""),
        yes_price_at_entry=yes_cur,
        leg_type="hedge",
        hedge_of_id=int(pos["id"]),
    )
    if hp:
        print(
            f"  🛡 ELITE-HEDGE #{hp} for #{pos['id']} "
            f"{plan.hedge_side} ${hedge_stake:.0f} | {plan.reason}"
        )
        return True
    return False


def check_positions(conn, client: httpx.Client) -> int:
    rows = conn.execute(
        "SELECT * FROM positions WHERE closed_at IS NULL"
    ).fetchall()
    closed = 0
    for pos in rows:
        try:
            lt = pos["leg_type"] or "primary"
        except (KeyError, IndexError):
            lt = "primary"
        if lt == "hedge":
            continue
        m = ms._get_with_retry(client, f"{GAMMA}/markets/{pos['market_id']}")
        if not m:
            continue
        prices = ms._parse_outcome_prices(m.get("outcomePrices"))
        if prices is None:
            continue
        yes_cur, _ = prices
        tokens = ms._parse_tokens(m.get("clobTokenIds"))
        if tokens:
            try:
                clob_r = ms._get_with_retry(
                    client, f"{CLOB}/midpoint", params={"token_id": tokens[0]}, timeout=5.0
                )
                if clob_r and "mid" in clob_r:
                    yes_cur = float(clob_r["mid"])
            except Exception:
                pass
        side = pos["side"]
        entry = float(pos["entry_price"])
        stake = float(pos["stake_usd"])
        contracts = float(pos["contracts"])
        unreal = PnLEngine.unrealized(
            side, entry, yes_cur, stake, contracts=contracts
        )
        tp_tgt = stake * TP_PCT * TP_TRIGGER
        sl_tgt = stake * SL_PCT
        if unreal >= tp_tgt and unreal > 0:
            pnl = close_position(conn, pos["id"], yes_cur, "TP")
            if pnl is not None:
                print(f"  💰 ELITE-TP #{pos['id']} +${pnl:.2f} score={pos['formula_score']:.2f}")
                closed += 1
        elif should_close_stale(
            opened_at=pos["opened_at"],
            unrealized_usd=unreal,
            tp_target_usd=tp_tgt,
        ):
            pnl = close_position(conn, pos["id"], yes_cur, "STALE-TP")
            if pnl is not None:
                age_m = position_age_minutes(pos["opened_at"])
                print(
                    f"  ⏱ ELITE-STALE-TP #{pos['id']} +${pnl:.2f} "
                    f"({age_m:.0f}dk, hedef ${tp_tgt:.2f} yok) — yeniden giriş serbest"
                )
                closed += 1
        elif unreal <= -sl_tgt and can_trigger_sl(
            pos["opened_at"],
            unrealized_usd=unreal,
            sl_target_usd=sl_tgt,
        ):
            plan = evaluate_recovery(conn, pos, yes_cur)
            if _try_open_hedge(conn, pos, yes_cur, plan, side=side):
                pass
            elif plan.action in (
                RecoveryAction.CLOSE_ORIGINAL,
                RecoveryAction.CLOSE_BOTH,
            ):
                pnl = close_position(conn, pos["id"], yes_cur, "SL-R")
                if pnl is not None:
                    print(f"  ⛔ ELITE-SL-R #{pos['id']} ${pnl:.2f} | {plan.reason}")
                    closed += 1
                if plan.action == RecoveryAction.CLOSE_BOTH:
                    hid = conn.execute(
                        "SELECT id FROM positions WHERE hedge_of_id=? AND closed_at IS NULL",
                        (pos["id"],),
                    ).fetchone()
                    if hid:
                        close_position(conn, int(hid["id"]), yes_cur, "HEDGE-C")
            else:
                pnl = close_position(conn, pos["id"], yes_cur, "SL")
                if pnl is not None:
                    print(f"  ⛔ ELITE-SL #{pos['id']} ${pnl:.2f}")
                    closed += 1
        else:
            plan = evaluate_recovery(conn, pos, yes_cur, proactive=True)
            if _try_open_hedge(conn, pos, yes_cur, plan, side=side):
                pass
            elif plan.action == RecoveryAction.CLOSE_BOTH:
                pnl = close_position(conn, pos["id"], yes_cur, "TP-H")
                if pnl is not None:
                    closed += 1
                hid = conn.execute(
                    "SELECT id FROM positions WHERE hedge_of_id=? AND closed_at IS NULL",
                    (pos["id"],),
                ).fetchone()
                if hid:
                    close_position(conn, int(hid["id"]), yes_cur, "HEDGE-C")
    return closed


_markets_cache: tuple[float, list[dict]] = (0.0, [])


def _scan_verbose() -> bool:
    return os.getenv("ELITE_SCAN_VERBOSE", "0").strip().lower() in ("1", "true", "yes")


def _fetch_markets_for_scan(client: httpx.Client) -> list[dict]:
    """Tüm portlar: tam liste. Sadece env ile önbellek/limit (8200 opsiyonel)."""
    global _markets_cache
    cache_sec = (os.getenv("ELITE_MARKETS_CACHE_SEC") or "").strip()
    try:
        limit = int(os.getenv("ELITE_FETCH_MARKETS_LIMIT", "0"))
    except ValueError:
        limit = 0

    if cache_sec:
        try:
            ttl = float(cache_sec)
        except ValueError:
            ttl = 60.0
        now = time.time()
        if _markets_cache[1] and now - _markets_cache[0] < ttl:
            return _markets_cache[1]
        markets = ms.fetch_active_markets(client, limit=limit)
        _markets_cache = (now, markets)
        return markets

    return ms.fetch_active_markets(client, limit=limit)


def _formula_refresh_baseline() -> float:
    """Son formül dosyası zamanı — açılışta gereksiz 15 dk araştırmayı önler."""
    for name in ("elite_success_formula.pkl", "elite_global_wallets.pkl"):
        p = ROOT / "data" / name
        if p.is_file():
            return p.stat().st_mtime
    return 0.0


def scan_and_open(
    conn,
    client: httpx.Client,
    formula: SuccessFormula,
    pacing: HourlyPacing,
    *,
    cycle: int = 0,
) -> int:
    open_n = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE closed_at IS NULL"
    ).fetchone()[0]
    max_open = max_open_positions()
    if open_n >= max_open:
        scan_stats.bump("max_open")
        return 0
    t_scan = time.time()
    verbose = _scan_verbose()

    def _hb_ping(
        *,
        markets_done: int | None = None,
        markets_total: int | None = None,
        scanning: bool = True,
    ) -> None:
        write_heartbeat(
            db_path=DB_PATH,
            cycle=cycle,
            scan_interval_sec=float(SCAN_INTERVAL),
            position_check_sec=float(POSITION_CHECK),
            scan_in_progress=scanning,
            markets_scanned=markets_done,
            markets_total=markets_total,
        )

    _hb_ping(scanning=True)
    if verbose:
        print("  📡 Aktif piyasalar çekiliyor...", flush=True)
    t_fetch = time.time()
    markets = _fetch_markets_for_scan(client)
    if verbose:
        print(
            f"  📡 {len(markets)} piyasa ({time.time() - t_fetch:.1f}s) — sinyal taraması...",
            flush=True,
        )
    opened = 0
    opened_clusters: set[str] = set()
    try:
        floor_score = float(os.getenv("ELITE_MIN_FORMULA_SCORE", "0.58"))
    except ValueError:
        floor_score = 0.58
    min_score = max(formula.min_score + pacing.edge_boost(), floor_score)

    progress_step = 0
    if verbose:
        try:
            progress_step = max(50, int(os.getenv("ELITE_SCAN_PROGRESS_EVERY", "75")))
        except ValueError:
            progress_step = 75

    for i, m in enumerate(markets, 1):
        if progress_step and i % progress_step == 0:
            _hb_ping(markets_done=i, markets_total=len(markets), scanning=True)
            print(
                f"  … {i}/{len(markets)} piyasa tarandı, açılan={opened}",
                flush=True,
            )
        if open_n + opened >= max_open:
            break
        op = ms._parse_outcome_prices(m.get("outcomePrices"))
        if op is None:
            continue
        yes_price, _ = op
        tokens = ms._parse_tokens(m.get("clobTokenIds"))
        if not tokens:
            continue

        # Ucuz filtreler önce — CLOB/entry_signals sadece adaylarda (~10× hızlı tarama)
        sig = ms.signal_for_price(yes_price)
        if sig is None:
            scan_stats.bump("no_signal")
            continue
        side, entry_price, edge = sig
        if edge < float(os.getenv("ELITE_MIN_EDGE", "0.04")):
            scan_stats.bump("edge")
            continue

        end_str = m.get("endDate") or m.get("closedTime")
        if not end_str:
            continue
        try:
            end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            hours_left = (end_dt.timestamp() - time.time()) / 3600.0
        except Exception:
            continue
        if hours_left < 1.0 or hours_left > 48.0:
            continue

        question = m.get("question") or ""
        try:
            min_px = float(os.getenv("ELITE_MIN_ENTRY_PRICE", "0"))
            max_px = float(os.getenv("ELITE_MAX_ENTRY_PRICE", "1"))
            if entry_price < min_px or entry_price > max_px:
                continue
        except ValueError:
            pass

        if ms._veto_sports_totals(hours_left, question):
            continue
        if os.getenv("ELITE_VETO_ALL_SPORTS", "1").strip().lower() in (
            "1",
            "true",
            "yes",
        ) and ms._is_sports_question(question):
            continue
        if ms._same_event_open(conn, question):
            continue
        if ms._is_sports_question(question) and hours_left <= float(
            os.getenv("ELITE_SPORTS_MAX_HOURS", "8")
        ):
            continue

        yes_price, _ = ms._apply_clob_midpoint_yes_price(client, tokens[0], yes_price)
        sig = ms.signal_for_price(yes_price)
        if sig is None:
            continue
        side, entry_price, edge = sig
        if edge < float(os.getenv("ELITE_MIN_EDGE", "0.04")):
            continue

        momentum, _, spread, _ = ms.fetch_entry_signals(client, tokens[0])

        market_id = str(m.get("id") or "")
        veto = should_veto_entry(
            conn,
            question,
            market_id,
            side,
            entry_price,
            opened_clusters=opened_clusters,
        )
        if veto:
            scan_stats.bump("veto")
            continue

        theme = _market_theme(question)

        feats = MarketFeatures(
            yes_price=yes_price,
            side=side,
            edge=edge,
            hours_left=hours_left,
            spread=spread,
            momentum=momentum,
            theme=theme,
            question=question,
        )
        min_edge = float(os.getenv("ELITE_MIN_EDGE", "0.055"))
        allowed, score, parts, _deny = entry_allowed(
            formula,
            feats,
            edge,
            min_edge=min_edge,
            min_score_floor=min_score,
            pacing_edge_boost=pacing.edge_boost(),
        )
        if not allowed:
            scan_stats.bump("whale_score")
            continue

        try:
            max_brier = float(os.getenv("ELITE_MAX_BRIER", "0.28"))
        except ValueError:
            max_brier = 0.28
        brier = _load_calibration_brier()
        if brier is not None and brier > max_brier:
            continue

        dup = conn.execute(
            "SELECT 1 FROM positions WHERE market_id=? AND closed_at IS NULL",
            (market_id,),
        ).fetchone()
        if dup:
            scan_stats.bump("duplicate")
            continue

        stake_mult = pacing.stake_multiplier()
        bi = min(9, int(yes_price * 10))
        cal_yes, _ = ms.CALIBRATION[bi]
        true_prob = cal_yes if side == "YES" else (1.0 - cal_yes)
        kelly = ms.kelly_stake(true_prob, entry_price, yes_price=yes_price)
        whale_stake = stake_multiplier_from_whale(score, theme)
        base = kelly * stake_mult * whale_stake * (0.55 + 0.25 * score)
        if theme == "sports":
            base *= float(os.getenv("ELITE_SPORTS_STAKE_MULT", "0.55"))
        open_stakes = [
            float(r[0])
            for r in conn.execute(
                "SELECT stake_usd FROM positions WHERE closed_at IS NULL"
            ).fetchall()
        ]
        equity = _portfolio_equity(conn)
        min_stake, max_stake = stake_bounds()
        wr = rolling_win_rate(conn)
        stake = compute_stake(
            equity,
            open_stakes,
            kelly_stake=base,
            max_open=max_open,
            min_stake=min_stake,
            max_stake=max_stake,
            win_rate=wr,
        )
        sparse_stake = compute_sparse_stake(
            equity, conn, min_stake=min_stake, max_stake=max_stake
        )
        if sparse_stake is not None and sparse_stake > stake:
            stake = sparse_stake
        if stake <= 0:
            scan_stats.bump("capital_limit")
            continue
        cond = str(m.get("conditionId") or m.get("condition_id") or "")
        pid = open_position(
            conn,
            market_id,
            question,
            side,
            entry_price,
            true_prob,
            score,
            edge,
            stake,
            formula,
            condition_id=cond or None,
            theme=theme,
            hours_left=hours_left,
            spread=spread,
            yes_price_at_entry=yes_price,
            score_parts=parts,
        )
        if pid:
            opened_clusters.add(event_cluster_key(question))
            sparse_tag = " [SPARSE]" if sparse_stake is not None and stake == sparse_stake else ""
            print(
                f"  ➕ ELITE #{pid} {side} @{entry_price:.3f} "
                f"score={score:.2f} edge={edge:+.2f} stake=${stake:.0f}{sparse_tag} | {question[:45]}"
            )
            opened += 1
    scan_dur = time.time() - t_scan
    _hb_ping(
        markets_done=len(markets),
        markets_total=len(markets),
        scanning=False,
    )
    write_heartbeat(
        db_path=DB_PATH,
        cycle=cycle,
        last_scan_duration_sec=scan_dur,
        scan_in_progress=False,
        markets_scanned=len(markets),
        markets_total=len(markets),
        scan_interval_sec=float(SCAN_INTERVAL),
        position_check_sec=float(POSITION_CHECK),
    )
    if verbose:
        print(
            f"  ✓ Tarama bitti {scan_dur:.0f}s | açılan={opened}",
            flush=True,
        )
    return opened


def main() -> None:
    formula = SuccessFormula.load()
    if formula is None:
        print("  Formül yok — araştırma çalıştırılıyor (ilk kurulum, ~5-15 dk)...")
        formula, _ = run_full_research(elite_count=25, history_days=21)

    ms._reload_paper_env_globals()
    min_stake, max_stake = stake_bounds()
    conn = init_db(DB_PATH)
    scan_stats.init(DB_PATH)
    pacing = HourlyPacing.from_env()
    pacing.started_at = datetime.now(timezone.utc)
    pacing.realized_pnl = _realized_pnl(conn)

    client = httpx.Client(timeout=20.0, headers={"User-Agent": "elite-formula/1.0"})
    force_refresh = os.getenv("ELITE_FORCE_FORMULA_REFRESH", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    last_formula_refresh = 0.0 if force_refresh else _formula_refresh_baseline()
    if last_formula_refresh > 0 and not force_refresh:
        age_h = (time.time() - last_formula_refresh) / 3600.0
        print(
            f"  Formül önbellek ({age_h:.1f}h önce) — "
            f"{FORMULA_REFRESH_HOURS:.0f}h dolmadan araştırma atlanır",
            flush=True,
        )
    cycle = 0
    last_full_scan_at: str | None = None

    print("=" * 65)
    print(" ELITE FORMULA TRADER")
    print(f" DB: {DB_PATH}")
    max_open = max_open_positions()
    print(
        f" Stake: ${min_stake:.0f} – {_max_stake_label(max_stake)} | "
        f"max açık={max_open} | aktif sermaye %{active_capital_pct()*100:.0f}"
    )
    print(f" Kelly cap ${ms.MAX_POS_USD:.0f} | WR ölçekli stake açık")
    print(f" Mod: {mode_label_tr()}")
    print(f" {formula.summary_tr()}")
    print(f" {pacing.status_line()}")
    print("=" * 65)

    try:
        while True:
            cycle += 1
            t0 = time.time()
            pacing.realized_pnl = _realized_pnl(conn)

            if time.time() - last_formula_refresh > FORMULA_REFRESH_HOURS * 3600:
                print("\n  🔄 Formül yenileniyor (elite leaderboard + örüntü)...")
                try:
                    formula, _ = run_full_research(elite_count=25, history_days=14)
                    last_formula_refresh = time.time()
                except Exception as exc:
                    print(f"  ⚠ formül yenileme: {exc}")

            write_heartbeat(
                db_path=DB_PATH,
                cycle=cycle,
                closed_last=0,
                opened_last=0,
                last_full_scan_at=last_full_scan_at,
                scan_interval_sec=float(SCAN_INTERVAL),
                position_check_sec=float(POSITION_CHECK),
                scan_in_progress=False,
            )
            closed = check_positions(conn, client)
            write_heartbeat(
                db_path=DB_PATH,
                cycle=cycle,
                closed_last=closed,
                opened_last=0,
                last_full_scan_at=last_full_scan_at,
                scan_interval_sec=float(SCAN_INTERVAL),
                position_check_sec=float(POSITION_CHECK),
                scan_in_progress=False,
            )
            opened = 0
            do_scan = cycle == 1 or cycle % max(
                1, int(SCAN_INTERVAL / max(POSITION_CHECK, 0.5))
            ) == 0
            if do_scan:
                opened = scan_and_open(conn, client, formula, pacing, cycle=cycle)
                last_full_scan_at = datetime.now(timezone.utc).isoformat()
            write_heartbeat(
                db_path=DB_PATH,
                cycle=cycle,
                closed_last=closed,
                opened_last=opened,
                last_full_scan_at=last_full_scan_at,
                scan_interval_sec=float(SCAN_INTERVAL),
                position_check_sec=float(POSITION_CHECK),
                scan_in_progress=False,
            )
            if closed or opened or cycle == 1 or cycle % 20 == 0:
                sparse_ln = sparse_status_line(conn, _portfolio_equity(conn))
                extra = f" | {sparse_ln}" if sparse_ln else ""
                print(
                    f"  [{cycle}] kapalı={closed} açılan={opened} | {pacing.status_line()}{extra}",
                    flush=True,
                )

            elapsed = time.time() - t0
            sleep_s = max(0.5, POSITION_CHECK - elapsed)
            time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("\n  Durduruldu.")
    finally:
        client.close()
        conn.close()


if __name__ == "__main__":
    main()
