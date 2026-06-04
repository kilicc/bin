"""Piyasa vs formül vs hedef — birleşik performans attribution raporu."""
from __future__ import annotations

import json
import math
import os
import pickle
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from elite_trader.hourly_pacing import HourlyPacing
from elite_trader.pattern_miner import _market_theme
from elite_trader.success_formula import SuccessFormula

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPORTS = DATA / "reports"
LATEST_JSON = REPORTS / "attribution_latest.json"
LATEST_MD = REPORTS / "attribution_latest.md"


@dataclass
class TradeRow:
    source: str
    id: int
    market_id: str
    question: str
    side: str
    entry_price: float
    close_price: float | None
    stake_usd: float
    pnl_usd: float | None
    edge: float | None
    true_prob: float | None
    formula_score: float | None
    exit_reason: str | None
    opened_at: str
    closed_at: str | None
    theme: str = ""
    era: str = "unknown"

    def __post_init__(self) -> None:
        if not self.theme:
            self.theme = _classify_theme(self.question)


def _classify_theme(q: str) -> str:
    ql = (q or "").lower()
    if "o/u" in ql or "over/under" in ql:
        if " vs" in ql or " vs." in ql:
            return "sports_ou"
    if " vs" in ql or " vs." in ql:
        return "sports_match"
    t = _market_theme(q)
    if t == "sports":
        return "sports_other"
    return t


def _era_label(source: str, stake: float, opened_at: str) -> str:
    if "pre_v2" in source or stake >= 500:
        return "v1"
    if stake <= 200:
        return "v2"
    return "mid"


def _discover_dbs(include_backups: bool = True) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for p in sorted(DATA.glob("*.db")):
        if p.name.startswith("."):
            continue
        out.append((p.stem, p))
    if include_backups:
        for p in sorted(DATA.glob("backups/**/*.db")):
            tag = p.parent.name
            out.append((f"backup/{tag}/{p.name}", p))
    return out


def _load_trades_from_db(label: str, path: Path) -> list[TradeRow]:
    if not path.is_file():
        return []
    rows: list[TradeRow] = []
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "positions" not in tables:
            conn.close()
            return []
        cols = {r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()}
        sel = [
            "id",
            "market_id",
            "question",
            "side",
            "entry_price",
            "close_price",
            "stake_usd",
            "pnl_usd",
            "opened_at",
            "closed_at",
        ]
        for c in ("edge", "true_prob", "formula_score", "exit_reason"):
            if c in cols:
                sel.append(c)
            else:
                sel.append(f"NULL AS {c}")
        q = f"SELECT {', '.join(sel)} FROM positions ORDER BY opened_at"
        for r in conn.execute(q):
            stake = float(r["stake_usd"] or 0)
            opened = str(r["opened_at"] or "")
            rows.append(
                TradeRow(
                    source=label,
                    id=int(r["id"]),
                    market_id=str(r["market_id"] or ""),
                    question=str(r["question"] or ""),
                    side=str(r["side"] or "YES"),
                    entry_price=float(r["entry_price"] or 0),
                    close_price=float(r["close_price"])
                    if r["close_price"] is not None
                    else None,
                    stake_usd=stake,
                    pnl_usd=float(r["pnl_usd"])
                    if r["pnl_usd"] is not None
                    else None,
                    edge=float(r["edge"]) if r["edge"] is not None else None,
                    true_prob=float(r["true_prob"])
                    if r["true_prob"] is not None
                    else None,
                    formula_score=float(r["formula_score"])
                    if r["formula_score"] is not None
                    else None,
                    exit_reason=str(r["exit_reason"])
                    if r["exit_reason"] is not None
                    else None,
                    opened_at=opened,
                    closed_at=str(r["closed_at"]) if r["closed_at"] else None,
                    era=_era_label(label, stake, opened),
                )
            )
        conn.close()
    except sqlite3.Error:
        pass
    return rows


def _brier_from_calibration(sample_n: int = 50_000) -> dict[str, Any]:
    path = DATA / "calibration_data.pkl"
    if not path.is_file():
        return {"available": False}
    try:
        data = pickle.load(open(path, "rb"))
    except Exception as exc:
        return {"available": False, "error": str(exc)[:80]}
    if not data:
        return {"available": False}
    if len(data) > sample_n:
        step = max(1, len(data) // sample_n)
        data = data[::step][:sample_n]
    preds: list[tuple[float, bool]] = []
    for p, _hours, outcome in data:
        preds.append((float(p), bool(outcome)))
    if not preds:
        return {"available": False}
    brier = sum((p - (1.0 if o else 0.0)) ** 2 for p, o in preds) / len(preds)
    return {
        "available": True,
        "brier": round(brier, 4),
        "n_sampled": len(preds),
        "interpretation": "Düşük daha iyi; >0.25 zayıf kalibrasyon",
    }


def _target_analysis(closed: list[TradeRow]) -> dict[str, Any]:
    try:
        target = float(os.getenv("ELITE_TARGET_HOURLY_USD", "800"))
        max_stake = float(os.getenv("ELITE_MAX_STAKE_USD", "175"))
        max_open = float(os.getenv("ELITE_MAX_OPEN", "36"))
        tp_pct = float(os.getenv("ELITE_TP_STAKE_PCT", "0.007"))
        tp_trig = float(os.getenv("ELITE_TP_TRIGGER_FRAC", "0.96"))
        realistic_override = os.getenv("ELITE_TARGET_REALISTIC_USD", "").strip()
    except ValueError:
        target, max_stake, max_open, tp_pct, tp_trig = 800, 175, 36, 0.007, 0.96
        realistic_override = ""

    wins = [t for t in closed if (t.pnl_usd or 0) > 0]
    wr = len(wins) / len(closed) if closed else 0.55
    tp_per_trade = max_stake * tp_pct * tp_trig

    if realistic_override:
        try:
            realistic_hr = float(realistic_override)
        except ValueError:
            realistic_hr = max_open * tp_per_trade * wr * 4
    else:
        closes_per_hour = 4.0
        realistic_hr = max_open * tp_per_trade * wr * closes_per_hour

    total_pnl = sum(t.pnl_usd or 0 for t in closed)
    hours_span = 1.0
    if closed:
        try:
            t0 = min(
                datetime.fromisoformat(t.opened_at.replace("Z", "+00:00"))
                for t in closed
            )
            t1 = max(
                datetime.fromisoformat(
                    (t.closed_at or t.opened_at).replace("Z", "+00:00")
                )
                for t in closed
            )
            hours_span = max(0.1, (t1 - t0).total_seconds() / 3600.0)
        except Exception:
            hours_span = 1.0
    realized_per_hour = total_pnl / hours_span

    gap_asp = target - realized_per_hour
    gap_real = realistic_hr - realized_per_hour
    pace = realized_per_hour / target if target else 0

    return {
        "target_aspiration_usd_h": target,
        "target_realistic_usd_h": round(realistic_hr, 2),
        "realized_usd_h": round(realized_per_hour, 2),
        "pace_vs_aspiration": round(pace, 4),
        "gap_vs_aspiration": round(gap_asp, 2),
        "gap_vs_realistic": round(gap_real, 2),
        "max_stake": max_stake,
        "tp_usd_per_win_est": round(tp_per_trade, 2),
        "note_tr": (
            f"Aspirasyon ${target:.0f}/s ile mevcut stake/TP yapısında teorik tavan "
            f"~${realistic_hr:.0f}/s (WR≈{wr:.0%}, saatte ~4 kapanış varsayımı)."
        ),
    }


def _theme_stats(closed: list[TradeRow]) -> dict[str, Any]:
    by: dict[str, list[TradeRow]] = defaultdict(list)
    for t in closed:
        by[t.theme].append(t)
    out = {}
    for th, ts in sorted(by.items(), key=lambda x: -len(x[1])):
        n = len(ts)
        wins = sum(1 for t in ts if (t.pnl_usd or 0) > 0)
        out[th] = {
            "n": n,
            "wr": round(wins / n, 3) if n else None,
            "pnl": round(sum(t.pnl_usd or 0 for t in ts), 2),
            "avg_stake": round(sum(t.stake_usd for t in ts) / n, 2) if n else 0,
        }
    return out


def _score_quintiles(closed: list[TradeRow]) -> list[dict[str, Any]]:
    scored = [t for t in closed if t.formula_score is not None]
    if len(scored) < 3:
        return []
    scored.sort(key=lambda t: t.formula_score or 0)
    n = len(scored)
    buckets: list[dict[str, Any]] = []
    for i in range(5):
        lo = int(i * n / 5)
        hi = int((i + 1) * n / 5)
        chunk = scored[lo:hi] if hi > lo else []
        if not chunk:
            continue
        wins = sum(1 for t in chunk if (t.pnl_usd or 0) > 0)
        buckets.append(
            {
                "quintile": i + 1,
                "score_lo": round(chunk[0].formula_score or 0, 3),
                "score_hi": round(chunk[-1].formula_score or 0, 3),
                "n": len(chunk),
                "wr": round(wins / len(chunk), 3),
                "pnl": round(sum(t.pnl_usd or 0 for t in chunk), 2),
            }
        )
    return buckets


def _market_vs_formula(closed: list[TradeRow]) -> dict[str, Any]:
    edge_pos_loss = 0
    edge_pos_win = 0
    edge_low_loss = 0
    weak_edge_thr = 0.05
    for t in closed:
        pnl = t.pnl_usd or 0
        edge = t.edge or 0
        if edge >= weak_edge_thr:
            if pnl < 0:
                edge_pos_loss += 1
            else:
                edge_pos_win += 1
        elif pnl < 0:
            edge_low_loss += 1
    by_exit: dict[str, dict[str, float]] = defaultdict(
        lambda: {"n": 0, "pnl": 0.0}
    )
    for t in closed:
        ex = (t.exit_reason or "unknown").upper()
        if "CLEANUP" in ex:
            ex = "cleanup"
        elif ex.startswith("SL"):
            ex = "SL"
        elif ex.startswith("TP"):
            ex = "TP"
        by_exit[ex]["n"] += 1
        by_exit[ex]["pnl"] += t.pnl_usd or 0
    return {
        "edge_positive_but_loss": edge_pos_loss,
        "edge_positive_and_win": edge_pos_win,
        "low_edge_losses": edge_low_loss,
        "market_signal_tr": (
            "edge≥0.05 iken zarar: fiyat/spread/volatilite (piyasa); "
            "düşük edge ile zarar: formül/kalibrasyon seçimi."
        ),
        "by_exit": {k: {"n": int(v["n"]), "pnl": round(v["pnl"], 2)} for k, v in by_exit.items()},
    }


def _whale_theme_gap(formula: SuccessFormula | None, paper_themes: dict[str, Any]) -> dict[str, Any]:
    if formula is None:
        return {}
    gaps = {}
    for th, whale_wr in formula.theme_wr.items():
        ours = paper_themes.get(th, {})
        our_wr = ours.get("wr")
        if our_wr is not None:
            gaps[th] = {
                "whale_wr": round(whale_wr, 3),
                "paper_wr": our_wr,
                "gap": round(our_wr - whale_wr, 3),
            }
    return gaps


def _bottleneck(
    target: dict[str, Any],
    market: dict[str, Any],
    closed: list[TradeRow],
) -> tuple[str, dict[str, float]]:
    """Yüzde paylar — hedef / piyasa / formül (toplam 100)."""
    if not closed:
        return "insufficient_data", {"target_math": 40, "market": 30, "formula": 30}

    pace = float(target.get("pace_vs_aspiration") or 0)
    target_pct = 35.0 if pace < 0.15 else (20.0 if pace < 0.5 else 10.0)

    edge_loss = int(market.get("edge_positive_but_loss") or 0)
    n = len(closed)
    market_pct = min(45.0, 15.0 + 30.0 * (edge_loss / max(1, n)))

    sports_pnl = sum(
        t.pnl_usd or 0
        for t in closed
        if t.theme.startswith("sports")
    )
    formula_pct = 100.0 - target_pct - market_pct
    if sports_pnl < -50:
        formula_pct = min(55.0, formula_pct + 15)
        market_pct = max(10.0, market_pct - 8)
        target_pct = max(5.0, target_pct - 7)

    total = target_pct + market_pct + formula_pct
    shares = {
        "target_math": round(100 * target_pct / total, 1),
        "market": round(100 * market_pct / total, 1),
        "formula": round(100 * formula_pct / total, 1),
    }
    primary = max(shares, key=shares.get)
    return primary, shares


@dataclass
class AttributionReport:
    generated_at: str = ""
    trade_count: int = 0
    closed_count: int = 0
    total_pnl: float = 0.0
    win_rate: float | None = None
    target: dict[str, Any] = field(default_factory=dict)
    market: dict[str, Any] = field(default_factory=dict)
    formula: dict[str, Any] = field(default_factory=dict)
    themes: dict[str, Any] = field(default_factory=dict)
    score_quintiles: list[dict[str, Any]] = field(default_factory=list)
    by_era: dict[str, Any] = field(default_factory=dict)
    by_source: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    whale_theme_gap: dict[str, Any] = field(default_factory=dict)
    bottleneck: str = ""
    bottleneck_shares_pct: dict[str, float] = field(default_factory=dict)
    improvements_tr: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)



def velocity_metrics(db_path: Path, *, hours: float = 24.0) -> dict[str, Any]:
    """Son N saat açılış/kapanış hızı (tek DB)."""
    import sqlite3
    from datetime import datetime, timedelta, timezone

    if not db_path.is_file():
        return {"opens_per_hour": 0.0, "closes_per_hour": 0.0, "avg_hold_minutes": None}
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(str(db_path))
    try:
        o = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE opened_at >= ?", (since,)
        ).fetchone()[0]
        c = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE closed_at IS NOT NULL AND closed_at >= ?",
            (since,),
        ).fetchone()[0]
        holds = conn.execute(
            """SELECT AVG((julianday(closed_at)-julianday(opened_at))*1440)
               FROM positions WHERE closed_at IS NOT NULL AND closed_at >= ?""",
            (since,),
        ).fetchone()[0]
    finally:
        conn.close()
    h = max(hours, 0.01)
    return {
        "window_hours": hours,
        "opens": int(o),
        "closes": int(c),
        "opens_per_hour": round(o / h, 2),
        "closes_per_hour": round(c / h, 2),
        "avg_hold_minutes": round(float(holds), 1) if holds else None,
    }

def build_report(*, include_backups: bool = True) -> AttributionReport:
    all_trades: list[TradeRow] = []
    by_source: dict[str, int] = defaultdict(int)
    for label, path in _discover_dbs(include_backups):
        batch = _load_trades_from_db(label, path)
        by_source[label] = len(batch)
        all_trades.extend(batch)

    closed = [t for t in all_trades if t.closed_at and t.pnl_usd is not None]
    closed_main = [
        t
        for t in closed
        if "cleanup" not in (t.exit_reason or "").lower()
        and abs(t.pnl_usd or 0) > 0.0001
    ]
    if not closed_main:
        closed_main = closed

    wins = sum(1 for t in closed_main if (t.pnl_usd or 0) > 0)
    wr = wins / len(closed_main) if closed_main else None
    total_pnl = sum(t.pnl_usd or 0 for t in closed_main)

    target = _target_analysis(closed_main)
    market = _market_vs_formula(closed_main)
    themes = _theme_stats(closed_main)
    quintiles = _score_quintiles(
        [t for t in closed_main if t.source.endswith("elite_formula") or "elite" in t.source]
    ) or _score_quintiles(closed_main)

    by_era: dict[str, Any] = {}
    for era in ("v1", "v2", "mid", "unknown"):
        ts = [t for t in closed_main if t.era == era]
        if not ts:
            continue
        w = sum(1 for t in ts if (t.pnl_usd or 0) > 0)
        by_era[era] = {
            "n": len(ts),
            "wr": round(w / len(ts), 3),
            "pnl": round(sum(t.pnl_usd or 0 for t in ts), 2),
        }

    formula = SuccessFormula.load()
    whale_gap = _whale_theme_gap(formula, themes)
    cal = _brier_from_calibration()
    bottleneck, shares = _bottleneck(target, market, closed_main)

    improvements = [
        "Stake/TP ile $800/saat aspirasyonu gerçekçi tavanın çok üstünde; panelde ikili hedef kullanın.",
        "Spor O/U ve canlı maç segmentlerini tam veto veya çok yüksek skor eşiği ile sınırlayın.",
        "Formül skoru kuintilleri — düşük skor bandı negatifse min_score artırın.",
        "Her işlemde score_parts + giriş YES fiyatı kaydı (shadow) ile attribution doğruluğu.",
        "Kalibrasyon Brier yüksekse edge tahmini piyasa kaynaklı sapma üretir; calibration yenileyin.",
    ]
    if shares.get("formula", 0) > 40:
        improvements.insert(
            0, "Whale theme_wr ile paper WR farkı büyük — tema bazlı min_score kullanın."
        )

    return AttributionReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        trade_count=len(all_trades),
        closed_count=len(closed_main),
        total_pnl=round(total_pnl, 2),
        win_rate=round(wr, 4) if wr is not None else None,
        target=target,
        market=market,
        formula={"score_quintiles": quintiles, "loaded": formula is not None},
        themes=themes,
        score_quintiles=quintiles,
        by_era=by_era,
        by_source=dict(by_source),
        calibration=cal,
        whale_theme_gap=whale_gap,
        bottleneck=bottleneck,
        bottleneck_shares_pct=shares,
        improvements_tr=improvements,
    )


def _render_md(r: AttributionReport) -> str:
    lines = [
        "# Elite Formula — Piyasa vs Formül Attribution",
        "",
        f"**Üretim:** {r.generated_at}",
        f"**Kapalı işlem:** {r.closed_count} | **Net PnL:** ${r.total_pnl:+.2f} | "
        f"**WR:** {(r.win_rate or 0):.1%}",
        "",
        "## Darboğaz",
        f"- **Birincil:** `{r.bottleneck}`",
        f"- Paylar: hedef matematiği **{r.bottleneck_shares_pct.get('target_math', 0)}%** | "
        f"piyasa **{r.bottleneck_shares_pct.get('market', 0)}%** | "
        f"formül **{r.bottleneck_shares_pct.get('formula', 0)}%**",
        "",
        "## Hedef boşluğu",
        f"- Aspirasyon: ${r.target.get('target_aspiration_usd_h', 0):.0f}/s",
        f"- Gerçekçi tavan: ${r.target.get('target_realistic_usd_h', 0):.0f}/s",
        f"- Realize: ${r.target.get('realized_usd_h', 0):.2f}/s | Pace: "
        f"{(r.target.get('pace_vs_aspiration') or 0):.0%}",
        f"- {r.target.get('note_tr', '')}",
        "",
        "## Piyasa vs formül",
        f"- edge≥0.05 ama zarar: **{r.market.get('edge_positive_but_loss', 0)}** işlem",
        f"- edge≥0.05 ve kâr: **{r.market.get('edge_positive_and_win', 0)}**",
        f"- {r.market.get('market_signal_tr', '')}",
        "",
        "### Çıkış nedeni",
    ]
    for ex, v in (r.market.get("by_exit") or {}).items():
        lines.append(f"- **{ex}:** n={v['n']}, PnL=${v['pnl']:+.2f}")
    lines.extend(["", "## Tema"])
    for th, v in r.themes.items():
        lines.append(
            f"- **{th}:** n={v['n']}, WR={v.get('wr')}, PnL=${v['pnl']:+.2f}"
        )
    lines.extend(["", "## Dönem (era)"])
    for era, v in r.by_era.items():
        lines.append(f"- **{era}:** n={v['n']}, WR={v.get('wr')}, PnL=${v['pnl']:+.2f}")
    if r.calibration.get("available"):
        lines.extend(
            [
                "",
                "## Kalibrasyon (örneklem)",
                f"- Brier: **{r.calibration.get('brier')}** (n={r.calibration.get('n_sampled')})",
            ]
        )
    lines.extend(["", "## İyileştirme maddeleri"])
    for i, imp in enumerate(r.improvements_tr, 1):
        lines.append(f"{i}. {imp}")
    return "\n".join(lines) + "\n"


def write_report(report: AttributionReport | None = None) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = report or build_report()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = REPORTS / f"attribution_{ts}.json"
    md_path = REPORTS / f"attribution_{ts}.md"
    payload = report.to_dict()
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    LATEST_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    LATEST_MD.write_text(_render_md(report), encoding="utf-8")
    return json_path


def load_latest() -> dict[str, Any] | None:
    if not LATEST_JSON.is_file():
        try:
            write_report()
        except Exception:
            return None
    try:
        return json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Elite attribution raporu")
    p.add_argument("--no-backups", action="store_true")
    args = p.parse_args()
    rep = build_report(include_backups=not args.no_backups)
    path = write_report(rep)
    print(f"Rapor: {path}")
    print(f"Darboğaz: {rep.bottleneck} | PnL ${rep.total_pnl:+.2f} | WR {(rep.win_rate or 0):.1%}")
    print(f"Paylar: {rep.bottleneck_shares_pct}")


if __name__ == "__main__":
    main()
