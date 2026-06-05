"""Ana döngü — tarama, giriş, %3 TP / %5 SL, hedge."""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "scenarios" / "binance_futures_demo.env")

from binance_futures_trader import config as cfg
from binance_futures_trader.capital import compute_stake
from binance_futures_trader.client import BinanceFuturesClient
from binance_futures_trader.db import (
    equity,
    init_db,
    open_stakes,
    realized_pnl,
    set_meta,
)
from binance_futures_trader.portfolio import effective_equity, total_unrealized, enrich_position
from binance_futures_trader.sync import sync_with_exchange
from binance_futures_trader.backtest import run_startup_backtests
from binance_futures_trader.cex_arb import build_cex_book
from binance_futures_trader.learner import (
    coin_backtest_veto,
    dynamic_min_score,
    get_weights,
    learning_summary,
    passes_signal_confirmation,
    record_close,
)
from binance_futures_trader.fees import (
    close_fee_breakdown,
    estimate_open_fee,
    fetch_close_fees_from_client,
    gross_pnl,
)
from binance_futures_trader.leverage import compute_leverage
from binance_futures_trader.hedge import (
    RecoveryAction,
    evaluate,
    has_hedge,
)
from binance_futures_trader.signals import analyze_coin
from binance_futures_trader.position_mgmt import (
    ExitKind,
    evaluate_exit,
    is_runner_candidate,
    position_age_sec,
)
from binance_futures_trader.entry_filters import (
    effective_sl_frac,
    entry_microstructure_ok,
    has_momentum_tag,
)

try:
    from scanner_runtime import singleton_process_lock, write_heartbeat_atomic
except ImportError:
    from contextlib import contextmanager

    @contextmanager
    def singleton_process_lock(_path):  # type: ignore
        yield

    def write_heartbeat_atomic(path, payload):  # type: ignore
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


LOCK = ROOT / "data" / "binance_futures.lock"
HEARTBEAT = ROOT / "data" / "binance_futures.heartbeat.json"


def _pct_move(side: str, entry: float, cur: float) -> float:
    if entry <= 0:
        return 0.0
    if side == "LONG":
        return (cur - entry) / entry
    return (entry - cur) / entry


def reconcile_ghost_positions(conn, client: BinanceFuturesClient) -> int:
    """Borsada olmayan yerel (simülasyon) pozisyonları kapat."""
    if client.paper:
        return 0
    exch_keys = {
        f"{p['coin']}:{p['side']}" for p in client.exchange_positions()
    }
    rows = conn.execute(
        """
        SELECT id, coin, side, entry_price, last_price,
               COALESCE(on_exchange, 0) AS on_exchange
        FROM positions WHERE closed_at IS NULL
        """
    ).fetchall()
    closed = 0
    for r in rows:
        key = f"{r['coin']}:{r['side']}"
        if int(r["on_exchange"]) or key in exch_keys:
            continue
        cur = float(r["last_price"] or r["entry_price"])
        close_position(conn, client, int(r["id"]), cur, "simulated_local")
        closed += 1
        print(
            f"  🧹 Yerel simülasyon temizlendi #{r['id']} {r['coin']} {r['side']} "
            f"(demo.binancefuture.com'da yoktu)"
        )
    return closed


def open_position(
    conn,
    client: BinanceFuturesClient,
    cs,
    stake: float,
    *,
    leg_type: str = "primary",
    hedge_of_id: int | None = None,
) -> int | None:
    candles = []
    try:
        candles = client.klines(cs.coin, cfg.CANDLE_INTERVAL, 40)
    except Exception:
        pass
    lev, lev_reason = compute_leverage(
        cs.coin,
        confidence=cs.confidence,
        total_score=cs.total_score,
        bt_wr=getattr(cs, "backtest_wr", 0.55),
        candles=candles,
        funding=cs.funding,
        side=cs.side,
    )
    cs.leverage = lev
    cs.leverage_reason = lev_reason
    client.ensure_margin_type(cs.coin)
    client.ensure_leverage(cs.coin, lev)
    notional = stake * lev
    contracts = notional / max(cs.mark_px, 1e-9)
    qty = client.round_qty(cs.coin, contracts)
    if qty <= 0:
        return None
    on_exchange = 0
    order_id: str | None = None
    entry_px = cs.mark_px
    entry_fee = estimate_open_fee(qty, entry_px)
    try:
        order = client.market_order(cs.coin, cs.side, qty, reduce_only=False)
        if not client.paper:
            on_exchange = 1
            order_id = str(order.get("orderId") or "")
            comm = client.order_commission(cs.coin, order_id)
            if comm > 0:
                entry_fee = comm
            if cfg.ORDER_SYNC_SLEEP_SEC > 0:
                time.sleep(cfg.ORDER_SYNC_SLEEP_SEC)
            for ep in client.exchange_positions():
                if ep["coin"] == cs.coin and ep["side"] == cs.side:
                    entry_px = float(ep["entry_price"])
                    contracts = float(ep["contracts"])
                    lev = int(ep.get("leverage") or lev)
                    break
            print(
                f"  ✓ Borsa #{order_id} {cs.side} {cs.coin} {lev}x "
                f"qty={qty} (${notional:.0f}) ücret≈${entry_fee:.3f} · {lev_reason}"
            )
    except Exception as exc:
        print(f"  ⛔ Borsa emri başarısız {cs.coin} {cs.side}: {exc}")
        return None
    now = datetime.now(timezone.utc).isoformat()
    strat = ",".join(p.name for p in cs.parts if abs(p.score) > 0.1)
    runner = (
        1
        if leg_type == "primary"
        and is_runner_candidate(cs.total_score, cs.confidence, strat)
        else 0
    )
    sl_frac = effective_sl_frac(candles)
    tp_frac = cfg.TP_PCT
    if sl_frac > tp_frac * 0.85:
        tp_frac = round(max(cfg.TP_PCT, sl_frac * 1.15), 5)
    from binance_futures_trader.risk_rules import apply_rr_target

    tp_frac = apply_rr_target(tp_frac, sl_frac)
    try:
        cur = conn.execute(
            """
            INSERT INTO positions (
                coin, side, entry_price, stake_usd, contracts, leverage,
                tp_frac, sl_frac, score, strategies, opened_at,
                leg_type, hedge_of_id, last_price, last_update,
                on_exchange, exchange_order_id,
                entry_fee_usd, fees_usd,
                open_confidence, runner_mode, tp_stage, initial_contracts,
                realized_partial_usd
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cs.coin,
                cs.side,
                entry_px,
                stake,
                contracts,
                lev,
                tp_frac,
                sl_frac,
                cs.total_score,
                strat,
                now,
                leg_type,
                hedge_of_id,
                entry_px,
                now,
                on_exchange,
                order_id,
                round(entry_fee, 4),
                round(entry_fee, 4),
                round(cs.confidence, 3),
                runner,
                0,
                contracts,
                0.0,
            ),
        )
        conn.commit()
        tag = " 🎯RUNNER" if runner else ""
        print(
            f"  📈 Açıldı #{cur.lastrowid} {cs.coin} {cs.side} "
            f"conf={cs.confidence:.1f} score={cs.total_score:+.2f}{tag}"
        )
        return int(cur.lastrowid)
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc).upper():
            return None
        raise


def partial_close_position(
    conn,
    client: BinanceFuturesClient,
    pid: int,
    cur: float,
    close_fraction: float,
    reason: str,
    *,
    tp_stage: int | None = None,
) -> tuple[float, bool]:
    """Kısmi kapat; (net_pnl, tamamen_kapandı)."""
    row = conn.execute(
        """
        SELECT coin, side, entry_price, contracts, stake_usd, strategies,
               opened_at, COALESCE(entry_fee_usd, 0) AS entry_fee_usd,
               COALESCE(on_exchange, 0) AS on_exchange,
               COALESCE(realized_partial_usd, 0) AS realized_partial_usd,
               COALESCE(tp_stage, 0) AS tp_stage
        FROM positions WHERE id=? AND closed_at IS NULL
        """,
        (pid,),
    ).fetchone()
    if not row:
        return 0.0, False

    coin = row["coin"]
    side = row["side"]
    entry = float(row["entry_price"])
    contracts = float(row["contracts"])
    stake = float(row["stake_usd"])
    entry_fee = float(row["entry_fee_usd"] or 0)
    on_exchange = int(row["on_exchange"])
    frac = min(1.0, max(0.05, close_fraction))
    close_qty = client.round_qty(coin, contracts * frac)
    if close_qty <= 0:
        return 0.0, False
    if close_qty >= contracts * 0.999:
        pnl = close_position(conn, client, pid, cur, reason)
        return pnl, True

    close_side = "SHORT" if side == "LONG" else "LONG"
    close_order_id: str | None = None
    if not client.paper and on_exchange:
        try:
            order = client.market_order(coin, close_side, close_qty, reduce_only=True)
            close_order_id = str(order.get("orderId") or "")
        except Exception as exc:
            print(f"  ⚠ Kısmi kapatma #{pid} {coin}: {exc}")
            return 0.0, False

    exit_fee = 0.0
    if close_order_id:
        exit_fee = client.order_commission(coin, close_order_id)

    closed_frac = close_qty / contracts if contracts > 0 else frac
    fb = close_fee_breakdown(
        side=side,
        entry=entry,
        close=cur,
        contracts=close_qty,
        entry_fee=entry_fee * closed_frac,
        exit_fee=exit_fee,
        income_commission=0.0,
        income_funding=0.0,
    )
    partial_net = fb["pnl_usd"]
    remain_contracts = max(0.0, contracts - close_qty)
    remain_stake = stake * (1.0 - closed_frac)
    remain_entry_fee = entry_fee * (1.0 - closed_frac)
    partial_sum = float(row["realized_partial_usd"]) + partial_net
    stage = tp_stage if tp_stage is not None else int(row["tp_stage"]) + 1
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        UPDATE positions SET contracts=?, stake_usd=?, entry_fee_usd=?,
               realized_partial_usd=?, tp_stage=?, last_price=?, last_update=?
        WHERE id=?
        """,
        (
            remain_contracts,
            round(remain_stake, 2),
            round(remain_entry_fee, 4),
            round(partial_sum, 4),
            stage,
            cur,
            now,
            pid,
        ),
    )
    conn.commit()
    print(
        f"  📊 Kısmi TP #{pid} {coin} {reason} "
        f"+${partial_net:.2f} ({closed_frac*100:.0f}% kapandı, kalan qty={remain_contracts:.6f})"
    )
    return partial_net, False


def close_position(
    conn,
    client: BinanceFuturesClient,
    pid: int,
    cur: float,
    reason: str,
) -> float:
    row = conn.execute(
        """
        SELECT coin, side, entry_price, contracts, stake_usd, strategies,
               opened_at, COALESCE(entry_fee_usd, 0) AS entry_fee_usd,
               COALESCE(on_exchange, 0) AS on_exchange,
               COALESCE(realized_partial_usd, 0) AS realized_partial_usd
        FROM positions WHERE id=?
        """,
        (pid,),
    ).fetchone()
    if not row:
        return 0.0
    coin = row["coin"]
    side = row["side"]
    entry, contracts = float(row["entry_price"]), float(row["contracts"])
    entry_fee = float(row["entry_fee_usd"] or 0)
    on_exchange = int(row["on_exchange"])
    close_order_id: str | None = None
    if not client.paper and on_exchange:
        close_side = "SHORT" if side == "LONG" else "LONG"
        try:
            order = client.market_order(coin, close_side, contracts, reduce_only=True)
            close_order_id = str(order.get("orderId") or "")
            print(f"  ✓ Borsa kapatıldı #{pid} {coin} {side}")
        except Exception as exc:
            print(f"  ⚠ Borsa kapatma #{pid} {coin}: {exc}")
    exit_fee = 0.0
    if close_order_id:
        exit_fee = client.order_commission(coin, close_order_id)
    income = fetch_close_fees_from_client(client, coin, row["opened_at"])
    prior_partial = float(row["realized_partial_usd"] or 0)
    fb = close_fee_breakdown(
        side=side,
        entry=entry,
        close=cur,
        contracts=contracts,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        income_commission=income["income_commission"],
        income_funding=income["income_funding"],
    )
    total_net = round(prior_partial + fb["pnl_usd"], 4)
    total_gross = round(prior_partial + fb["pnl_gross_usd"], 4)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE positions SET closed_at=?, close_price=?, pnl_gross_usd=?, pnl_usd=?,
               entry_fee_usd=?, exit_fee_usd=?, funding_fee_usd=?, fees_usd=?,
               exit_reason=?, last_price=?, realized_partial_usd=?
        WHERE id=?
        """,
        (
            now,
            cur,
            total_gross,
            total_net,
            fb["entry_fee_usd"],
            fb["exit_fee_usd"],
            fb["funding_fee_usd"],
            fb["fees_usd"],
            reason,
            cur,
            round(prior_partial, 4),
            pid,
        ),
    )
    pnl = total_net
    won = pnl > 0
    try:
        from binance_futures_trader.trade_journal import record_close as journal_close

        tp_row = conn.execute(
            "SELECT tp_frac, sl_frac, score, open_confidence FROM positions WHERE id=?",
            (pid,),
        ).fetchone()
        tp_f = float(tp_row["tp_frac"]) if tp_row and tp_row["tp_frac"] else cfg.TP_PCT
        sl_f = float(tp_row["sl_frac"]) if tp_row and tp_row["sl_frac"] else cfg.SL_PCT
        sc = float(tp_row["score"] or tp_row["open_confidence"] or 0) if tp_row else 0
        journal_close(
            position_id=pid,
            coin=coin,
            side=side,
            setup=cfg.SETUP_NAME,
            entry_reason=(row["strategies"] or cfg.SETUP_NAME)[:120],
            edge_or_score=sc,
            stake_usd=float(row["stake_usd"]),
            tp_frac=tp_f,
            sl_frac=sl_f,
            exit_reason=reason,
            net_pnl=pnl,
            entry_price=entry,
            close_price=cur,
            opened_at=row["opened_at"],
            closed_at=now,
            strategies=row["strategies"] or "",
            rule_ok=True,
        )
    except Exception as exc:
        print(f"  ⚠ Journal: {exc}")
    from binance_futures_trader.learner import SKIP_STRATEGIES

    for strat in (row["strategies"] or "").split(","):
        s = strat.strip()
        if not s or s in SKIP_STRATEGIES:
            continue
        conn.execute(
            """
            INSERT INTO strategy_stats(strategy,wins,losses,total_pnl,updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(strategy) DO UPDATE SET
              wins=wins+excluded.wins, losses=losses+excluded.losses,
              total_pnl=total_pnl+excluded.total_pnl, updated_at=excluded.updated_at
            """,
            (s, 1 if won else 0, 0 if won else 1, round(pnl, 4), now),
        )
    conn.commit()
    if cfg.LEARNING_ENABLED:
        record_close(
            conn,
            position_id=pid,
            coin=coin,
            side=side,
            exit_reason=reason,
            pnl_usd=round(pnl, 4),
            # net PnL after fees
            strategies=row["strategies"] or "",
            snapshot={"entry": entry, "close": cur, "reason": reason},
        )
    return pnl


def check_positions(conn, client: BinanceFuturesClient) -> int:
    try:
        prices = client.all_prices()
    except Exception as exc:
        print(f"  ⚠ fiyat alınamadı (önbellek/DB): {exc}")
        prices = {}
    rows = conn.execute(
        "SELECT * FROM positions WHERE closed_at IS NULL"
    ).fetchall()
    closed = 0
    for pos in rows:
        coin = pos["coin"]
        cur = float(prices.get(coin) or pos["last_price"] or pos["entry_price"])
        if not cur:
            continue
        leg = pos["leg_type"] or "primary"
        pid = int(pos["id"])
        age = position_age_sec(pos["opened_at"])
        plan = evaluate_exit(dict(pos), cur, age_sec=age)

        if plan.kind == ExitKind.STANDARD_SL:
            if leg == "primary":
                ev = evaluate(pos, cur)
                if ev.action == RecoveryAction.OPEN_HEDGE and not has_hedge(conn, pid):
                    hs = min(
                        float(pos["stake_usd"]) * cfg.HEDGE_STAKE_FRAC,
                        float(pos["stake_usd"]),
                    )
                    from binance_futures_trader.signals import CoinSignal

                    hcs = CoinSignal(coin=coin, mark_px=cur, side=ev.hedge_side or "SHORT")
                    hcs.total_score = 0
                    hid = open_position(
                        conn, client, hcs, hs, leg_type="hedge", hedge_of_id=pid
                    )
                    if hid:
                        print(f"  🛡 BN-HEDGE #{hid} for #{pid} {ev.hedge_side} ${hs:.0f}")
                        continue
            pnl = close_position(conn, client, pid, cur, plan.reason or "SL")
            print(
                f"  ⛔ BN-SL #{pid} {coin} ${pnl:.2f} "
                f"(fiyat {plan.move_pct:.2f}% · ROI {plan.roi_pct:.1f}%)"
            )
            closed += 1
            continue

        if plan.kind in (ExitKind.TIER_PARTIAL, ExitKind.TIER_FINAL):
            _, done = partial_close_position(
                conn,
                client,
                pid,
                cur,
                plan.close_fraction,
                plan.reason,
                tp_stage=plan.tier,
            )
            if done:
                closed += 1
            continue

        if plan.kind in (ExitKind.STANDARD_TP, ExitKind.STALE_TP):
            pnl = close_position(conn, client, pid, cur, plan.reason)
            tag = "⏳" if plan.kind == ExitKind.STALE_TP else "💰"
            side = str(pos["side"])
            print(
                f"  {tag} BN-{plan.reason} #{pid} {coin} {side} +${pnl:.2f} "
                f"(fiyat {plan.move_pct:.2f}% · ROI {plan.roi_pct:.1f}% · "
                f"{age/60:.0f}dk)"
            )
            closed += 1
            continue
        if leg == "primary" and cfg.HEDGE_PROACTIVE:
            plan = evaluate(pos, cur, proactive=True)
            if plan.action == RecoveryAction.OPEN_HEDGE and not has_hedge(conn, pid):
                hs = plan.hedge_stake
                from binance_futures_trader.signals import CoinSignal

                hcs = CoinSignal(coin=coin, mark_px=cur, side=plan.hedge_side or "SHORT")
                hid = open_position(
                    conn, client, hcs, hs, leg_type="hedge", hedge_of_id=pid
                )
                if hid:
                    print(f"  🛡 BN-HEDGE+ #{hid} {plan.reason}")

        conn.execute(
            "UPDATE positions SET last_price=?, last_update=? WHERE id=?",
            (cur, datetime.now(timezone.utc).isoformat(), pid),
        )
    conn.commit()
    return closed


def scan_and_open(
    conn,
    client: BinanceFuturesClient,
    *,
    cex_book: dict | None = None,
    bt_wrs: dict[str, float] | None = None,
    strategy_weights: dict[str, float] | None = None,
) -> int:
    from binance_futures_trader.risk_rules import daily_loss_locked

    if daily_loss_locked(conn):
        return 0

    open_n = conn.execute(
        "SELECT COUNT(*) FROM positions WHERE closed_at IS NULL AND leg_type='primary'"
    ).fetchone()[0]
    if open_n >= cfg.MAX_OPEN:
        return 0
    prices = client.all_prices()
    rows = conn.execute(
        "SELECT * FROM positions WHERE closed_at IS NULL"
    ).fetchall()
    open_enriched = [
        enrich_position(dict(r), prices.get(str(r["coin"])))
        for r in rows
    ]
    unrl = total_unrealized(open_enriched)
    exch = client.exchange_balance()
    eq = effective_equity(conn, exch, unrl)
    stakes = open_stakes(conn)
    opened = 0
    for coin in cfg.WATCHLIST:
        if open_n + opened >= cfg.MAX_OPEN:
            break
        mark = prices.get(coin)
        if not mark or mark <= 0:
            continue
        dup = conn.execute(
            "SELECT 1 FROM positions WHERE coin=? AND closed_at IS NULL AND leg_type='primary'",
            (coin,),
        ).fetchone()
        if dup:
            continue
        bt_wr = (bt_wrs or {}).get(coin, 0.5)
        if cfg.LEARNING_ENABLED and coin_backtest_veto(conn, coin, bt_wr):
            continue
        cs = analyze_coin(
            client,
            coin,
            mark,
            cex_book=cex_book,
            strategy_weights=strategy_weights,
            backtest_wr=bt_wr,
        )
        min_s = dynamic_min_score(conn)
        if cs.parts:
            cs.compute(min_score=min_s)
        if not cs.side or not passes_signal_confirmation(cs):
            continue
        strat_preview = ",".join(p.name for p in cs.parts if abs(p.score) > 0.1)
        if cfg.is_scalp() and not has_momentum_tag(strat_preview):
            continue
        ok_micro, why = entry_microstructure_ok(client, coin, cs.side)
        if not ok_micro:
            continue
        if bt_wr < 0.42 and cs.confidence < 4.0:
            continue
        cs.backtest_wr = bt_wr
        est_sl = cfg.SL_PCT
        try:
            kl = client.klines(coin, cfg.CANDLE_INTERVAL, 40)
            est_sl = effective_sl_frac(kl)
        except Exception:
            pass
        stake = compute_stake(
            conn, eq, cs.confidence, open_stakes=stakes, sl_frac=est_sl
        )
        if stake <= 0:
            continue
        pid = open_position(conn, client, cs, stake)
        if pid:
            stakes.append(stake)
            opened += 1
            print(
                f"  ➕ BN #{pid} {cs.side} {coin} @{mark:.4f} "
                f"score={cs.total_score:+.2f} stake=${stake:.0f} "
                f"lev={getattr(cs,'leverage',cfg.LEVERAGE)}x "
                f"TP={cfg.TP_PCT*100:.2f}% SL={cfg.SL_PCT*100:.2f}%"
            )
    return opened


def main() -> None:
    mode = "PAPER" if cfg.MODE != "testnet" or not cfg.API_KEY else "TESTNET"
    with singleton_process_lock(LOCK):
        if cfg.FRESH_START and cfg.DB_PATH.is_file():
            cfg.DB_PATH.unlink()
            print(f"  🆕 Sıfır başlangıç — DB silindi: {cfg.DB_PATH}")
        conn = init_db()
        client = BinanceFuturesClient()
        if cfg.MARK_WS_ENABLED:
            from binance_futures_trader.mark_ws import ensure_mark_feed_started

            ensure_mark_feed_started()
            print("  ✓ Mark price WebSocket (1s) — TP/SL ve panel fiyatları")
        cycle = 0
        bt_wrs: dict[str, float] = {}
        strategy_weights = get_weights(conn) if cfg.LEARNING_ENABLED else {}
        if cfg.BACKTEST_ON_START and not client.paper:
            print("  📊 Backtest (son mumlar) çalışıyor…")
            bt_wrs = run_startup_backtests(client)
            for c, wr in sorted(bt_wrs.items(), key=lambda x: -x[1])[:5]:
                print(f"     {c} WR {wr*100:.0f}%")
        prof = cfg.STRATEGY_PROFILE.upper()
        if cfg.is_scalp():
            print(
                f"  ⚡ SCALP modu · TP {cfg.TP_PCT*100:.2f}% / SL {cfg.SL_PCT*100:.2f}% · "
                f"{cfg.CANDLE_INTERVAL} · lev {cfg.LEVERAGE_MIN}-{cfg.LEVERAGE_MAX}x · "
                f"{len(cfg.WATCHLIST)} market"
            )
        tiers = ", ".join(f"{t*100:.0f}%" for t in cfg.TIER_ROI_PCTS)
        print(
            f"  📐 Margin: {cfg.MARGIN_TYPE.upper()} · stale {cfg.STALE_MIN_AGE_SEC//60}dk+ "
            f"TP fiyat %{cfg.STALE_TP_MOVE_PCT*100:.1f} · runner kademe ROI {tiers}"
        )
        print(
            f"  🧠 [{prof}] CEX={cfg.CEX_ARB_ENABLED} gap={cfg.GAP_ANALYSIS_ENABLED} "
            f"flow={cfg.FLOW_ANALYSIS_ENABLED} news={cfg.NEWS_ENABLED} "
            f"öğrenme={cfg.LEARNING_ENABLED}"
        )
        set_meta(conn, "starting_balance", f"{cfg.STARTING_BALANCE:.2f}")
        exch0 = client.exchange_balance()
        if exch0 is not None and exch0 > 0:
            set_meta(conn, "exchange_balance", f"{exch0:.2f}")
            print(f"  ✓ Testnet bakiye: ${exch0:,.2f} USDT")
        if cfg.LEARNING_ENABLED:
            ls = learning_summary(conn)
            print(
                f"  🧠 Öğrenme: {ls['lessons']} ders · "
                f"{ls['active_adjustments']} ayarlı strateji"
            )
        n_ghost = reconcile_ghost_positions(conn, client)
        if n_ghost:
            print(f"  ℹ {n_ghost} yerel simülasyon pozisyonu temizlendi (borsada yoktu)")
        st = sync_with_exchange(conn, client)
        if any(st.values()):
            print(
                f"  🔄 Senkron: kapatılan={st['closed']} güncellenen={st['updated']} "
                f"içe aktarılan={st['imported']}"
            )
        exch_open = client.exchange_positions()
        if exch_open:
            print(f"  ✓ Binance testnet açık: {len(exch_open)} pozisyon")
            for p in exch_open:
                print(
                    f"     · {p['side']} {p['coin']} "
                    f"qty={p['contracts']} PnL ${p['unrealized_pnl']:+.2f}"
                )
        elif not client.paper:
            print("  ℹ Binance testnet: açık pozisyon yok (yeni emirler burada görünecek)")
        print("=" * 60)
        print(f" BINANCE FUTURES TRADER [{mode}]")
        print(f" DB: {cfg.DB_PATH}")
        bal_label = exch0 if exch0 else cfg.STARTING_BALANCE
        print(f" Bakiye: ${bal_label:.0f} | Aktif %{cfg.ACTIVE_CAPITAL_PCT*100:.0f}")
        print(f" TP {cfg.TP_PCT*100:.1f}% / SL {cfg.SL_PCT*100:.1f}% | Hedef gün %{cfg.TARGET_DAILY_PCT*100:.0f}")
        print(f" Coins: {', '.join(cfg.WATCHLIST)}")
        print("=" * 60)
        try:
            while True:
                cycle += 1
                t0 = time.time()
                if cycle % 3 == 0:
                    st = sync_with_exchange(conn, client)
                    if st["closed"] or st["updated"] or st["imported"]:
                        print(f"  🔄 sync: {st}")
                try:
                    closed = check_positions(conn, client)
                except Exception as exc:
                    print(f"  ⚠ pozisyon kontrolü: {exc}")
                    closed = 0
                opened = 0
                if cycle == 1 or cycle % cfg.SCAN_EVERY_CYCLES == 0:
                    if cfg.LEARNING_ENABLED:
                        strategy_weights = get_weights(conn)
                    try:
                        cex_book = build_cex_book() if cfg.CEX_ARB_ENABLED else {}
                        opened = scan_and_open(
                            conn,
                            client,
                            cex_book=cex_book,
                            bt_wrs=bt_wrs,
                            strategy_weights=strategy_weights,
                        )
                    except Exception as exc:
                        print(f"  ⚠ tarama: {exc}")
                        opened = 0
                prices = client.all_prices()
                open_rows = conn.execute(
                    "SELECT * FROM positions WHERE closed_at IS NULL"
                ).fetchall()
                open_enriched = [
                    enrich_position(dict(r), prices.get(str(r["coin"])))
                    for r in open_rows
                ]
                unrl = total_unrealized(open_enriched)
                exch = client.exchange_balance()
                eq = effective_equity(conn, exch, unrl)
                real = realized_pnl(conn)
                target = cfg.STARTING_BALANCE * cfg.TARGET_DAILY_PCT
                pace = (real / target * 100) if target > 0 else 0
                if closed or opened or cycle % 15 == 0:
                    print(
                        f"  [{cycle}] eq=${eq:.2f} unrl=${unrl:+.2f} realize=${real:+.2f} "
                        f"gün %{pace:.0f} | açık {len(open_rows)} | +{opened} -{closed}"
                    )
                write_heartbeat_atomic(
                    HEARTBEAT,
                    {
                        "cycle": cycle,
                        "equity": round(eq, 2),
                        "exchange_balance": round(exch, 2) if exch else None,
                        "unrealized_pnl": round(unrl, 2),
                        "realized_pnl": round(real, 2),
                        "open_count": len(open_rows),
                        "mode": mode,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    },
                )
                set_meta(conn, "last_equity", f"{eq:.2f}")
                row_sb = conn.execute(
                    "SELECT value FROM meta WHERE key='starting_balance'"
                ).fetchone()
                start_meta = float(
                    row_sb[0] if row_sb else cfg.STARTING_BALANCE
                )
                pct = ((eq - start_meta) / start_meta * 100) if start_meta > 0 else 0
                set_meta(conn, "performance_pct", f"{pct:.3f}")
                rest = cfg.POS_CHECK - (time.time() - t0)
                if rest > 0.05:
                    time.sleep(rest)
        except KeyboardInterrupt:
            print("\n  Durduruldu.")
        finally:
            client.close()
            conn.close()


if __name__ == "__main__":
    main()
