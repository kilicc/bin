"""Adaptive self-improvement — kapalı pozisyonlardan öğrenir, parametreleri günceller.

Nasıl çalışır:
  Her scanner döngüsünde çağrılır. Kapalı pozisyonları okur, şunları yapar:

  1. Bayesian Kalibrasyon Güncellemesi
     ─ 2.3M tarihsel data prior olarak kullanılır (çok güçlü prior)
     ─ Her kapanan live trade posterior'ı Bayes kuralıyla günceller
     ─ Zamanla CALIBRATION tablosu live performansa yakınsıyor

  2. Momentum Filtre Kalibrasyonu
     ─ Momentum'un yönü doğruysa (örn. NO pozisyonu ve fiyat gerçekten düştüyse)
       MOMENTUM_VETO eşiği sıkılaştırılır; yanlışsa gevşetilir

  3. Edge Eşiği Adaptasyonu
     ─ Edge < 0.10 bölgesindeki win rate düşükse EDGE_THRESHOLD yükseltilir
     ─ Tüm edge'lerde win rate yüksekse threshold düşürülür (daha fazla trade)

  4. Periyodik rapor (her 10 kapanışta bir)
"""
from __future__ import annotations

import math
import os
import pickle
import sqlite3
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
LEARNING_PATH = DATA / "learning_state.pkl"

# ─── Prior: 2.3M data point'ten gelen kalibrasyon ───────────────────────────
# Her bucket için (true_yes_prob, n_equivalent_prior)
# n_equivalent_prior: prior'ın gücü — live trade'lerin etki etmesi için
# kaç live trade gerektiğini belirler. 500 = 500 live trade sonra %50 ağırlık.
PRIOR: dict[int, tuple[float, int]] = {
    0: (0.0098,  10_000),   # çok stabil, live data etkisi az
    1: (0.1265,  1_000),
    2: (0.3466,  500),
    3: (0.3604,  500),
    4: (0.1828,  2_000),    # en önemli bucket — büyük prior
    5: (0.8495,  2_000),    # en önemli bucket
    6: (0.9072,  1_000),
    7: (0.9603,  1_000),
    8: (0.9620,  500),
    9: (0.9951,  2_000),
}

# Parametre sınırları
MOMENTUM_VETO_MIN = 0.005
MOMENTUM_VETO_MAX = 0.050
EDGE_THRESHOLD_MIN = 0.06
EDGE_THRESHOLD_MAX = 0.25


def _apex_mode() -> bool:
    return os.getenv("APEX_2X_24H", "").strip().lower() in ("1", "true", "yes")


def _edge_threshold_bounds() -> tuple[float, float]:
    if _apex_mode():
        return 0.035, 0.22
    return EDGE_THRESHOLD_MIN, EDGE_THRESHOLD_MAX


def _env_edge_threshold() -> float:
    try:
        return float(os.getenv("EDGE_THRESHOLD", "0.06"))
    except ValueError:
        return 0.06


def _sync_apex_edge(state: LearningState) -> None:
    """APEX: öğrenme edge'i env tabanının çok üstüne çıkarmasın."""
    if not _apex_mode():
        return
    env_et = _env_edge_threshold()
    et_min, et_max = _edge_threshold_bounds()
    if state.edge_threshold > env_et + 0.008:
        state.edge_threshold = env_et
    state.edge_threshold = max(et_min, min(et_max, state.edge_threshold))


class LearningState:
    """Scanner'ın öğrenme durumu — diskte saklanır."""

    def __init__(self):
        # Per-bucket live trade istatistikleri
        # bucket_idx → {"yes_wins": int, "yes_n": int, "no_wins": int, "no_n": int}
        self.bucket_stats: dict[int, dict] = {
            i: {"yes_wins": 0, "yes_n": 0, "no_wins": 0, "no_n": 0}
            for i in range(10)
        }

        # Momentum etkinliği: momentum sinyali doğru mu?
        # {"confirmed_wins": int, "confirmed_n": int, "borderline_wins": int, "borderline_n": int}
        self.momentum_stats = {
            "confirmed_wins": 0, "confirmed_n": 0,    # |momentum| > veto × 0.5
            "borderline_wins": 0, "borderline_n": 0,  # |momentum| < veto × 0.5
        }

        # Edge katmanı performansı
        # edge_bin (0=<0.10, 1=0.10-0.20, 2=0.20-0.30, 3=0.30+) → {wins, n}
        self.edge_stats: dict[int, dict] = {
            i: {"wins": 0, "n": 0} for i in range(4)
        }

        # Güncel parametreler (scanner bu değerleri kullanır)
        self.momentum_veto: float = 0.015
        self.edge_threshold: float = 0.06
        # Tema bazlı ek edge (TP/SL öğrenmesi — crypto_px, eurovision vb.)
        self.theme_edge_boost: dict[str, float] = {}
        # exit_reason × tema: {"tp","sl","tp_pnl","sl_pnl","high_yes_sl","high_yes_n"}
        self.theme_exits: dict[str, dict] = {}

        # Kaç kapanış işlendi
        self.processed_ids: set[int] = set()
        self.last_report_n: int = 0
        self.updated_at: str = ""
        # APEX 2×24H oturum takibi
        self.session_start_equity: float = 0.0
        self.session_target_equity: float = 0.0
        self.profile_name: str = ""
        self.profile_version: int = 0

    @classmethod
    def load(cls) -> "LearningState":
        if LEARNING_PATH.exists():
            try:
                st = pickle.load(open(LEARNING_PATH, "rb"))
                _migrate_learning_state(st)
                _sync_apex_edge(st)
                return st
            except Exception:
                pass
        st = cls()
        if _apex_mode():
            st.edge_threshold = _env_edge_threshold()
        return st

    def save(self):
        DATA.mkdir(exist_ok=True)
        pickle.dump(self, open(LEARNING_PATH, "wb"))

    def posterior_yes_prob(self, bucket: int) -> float:
        """Bayesian posterior: prior + live data."""
        prior_p, prior_n = PRIOR[bucket]
        st = self.bucket_stats[bucket]
        live_wins = st["yes_wins"]
        live_n    = st["yes_n"]
        # Weighted: (prior_p × prior_n + live_wins) / (prior_n + live_n)
        return (prior_p * prior_n + live_wins) / (prior_n + live_n)

    def calibration_dict(self) -> dict[int, tuple[float, float]]:
        """Güncellenmiş (true_yes_prob, bias) tablosu — CALIBRATION yerine kullanılır."""
        result = {}
        for bi in range(10):
            prior_p, _ = PRIOR[bi]
            post_p = self.posterior_yes_prob(bi)
            # bucket midpoint: (bi + 0.5) / 10
            mid = (bi + 0.5) / 10
            bias = post_p - mid
            result[bi] = (round(post_p, 4), round(bias, 4))
        return result


def _migrate_learning_state(state: LearningState) -> None:
    """Eski learning_state.pkl ile uyumluluk."""
    if not hasattr(state, "theme_edge_boost"):
        state.theme_edge_boost = {}
    if not hasattr(state, "theme_exits"):
        state.theme_exits = {}
    if not hasattr(state, "session_start_equity"):
        state.session_start_equity = 0.0
    if not hasattr(state, "session_target_equity"):
        state.session_target_equity = 0.0
    if not hasattr(state, "profile_name"):
        state.profile_name = ""
    if not hasattr(state, "profile_version"):
        state.profile_version = 0


def _theme_exit_slot(state: LearningState, theme: str) -> dict:
    if theme not in state.theme_exits:
        state.theme_exits[theme] = {
            "tp": 0,
            "sl": 0,
            "tp_pnl": 0.0,
            "sl_pnl": 0.0,
            "high_yes_sl": 0,
            "high_yes_n": 0,
        }
    return state.theme_exits[theme]


# ═══════════════════════════════════════════════════════════════════════════════

def _win_from_row(row: sqlite3.Row) -> bool | None:
    """Kapalı pozisyon kazanmış mı? TP/SL/resolved hepsini kapsıyor."""
    if row["pnl_usd"] is None:
        return None
    # Tam sıfır P&L: öğrenme / istatistikte kullanılmaz
    try:
        p = float(row["pnl_usd"])
    except (TypeError, ValueError):
        return None
    if abs(p) <= 0.0001:
        return None
    return p > 0


def _edge_bin(edge: float) -> int:
    if edge < 0.10: return 0
    if edge < 0.20: return 1
    if edge < 0.30: return 2
    return 3


def _momentum_abs_from_rationale(rationale: str | None) -> float | None:
    """Rationale string'inden momentum değerini parse et."""
    if not rationale:
        return None
    import re
    m = re.search(r"momentum=([+-]?\d+\.?\d*(?:e[+-]?\d+)?)", rationale)
    if m:
        try:
            return abs(float(m.group(1)))
        except ValueError:
            pass
    return None


def _bucket_from_entry(entry_price: float) -> int:
    return min(9, int(entry_price * 10))


def process_closed_positions(
    state: LearningState,
    conn: sqlite3.Connection,
) -> int:
    """Yeni kapanmış pozisyonları işler, state'i günceller. Yeni işlenen sayısını döner."""
    rows = conn.execute("""
        SELECT id, side, entry_price, edge, pnl_usd, rationale,
               exit_reason, question
        FROM positions
        WHERE closed_at IS NOT NULL
          AND ABS(COALESCE(pnl_usd, 0)) > 0.0001
    """).fetchall()

    new_count = 0
    for row in rows:
        if row["id"] in state.processed_ids:
            continue
        win = _win_from_row(row)
        if win is None:
            state.processed_ids.add(row["id"])
            continue

        # ── 1. Bucket istatistiği ────────────────────────────────────────────
        side = row["side"]
        entry = row["entry_price"]
        # YES bucket: YES pozisyonlarda giriş fiyatı = YES fiyatı
        # NO  bucket: giriş fiyatı = NO fiyatı → YES fiyatı = 1 - entry
        yes_price_at_entry = entry if side == "YES" else (1.0 - entry)
        bi = _bucket_from_entry(yes_price_at_entry)
        st = state.bucket_stats[bi]

        # Outcome: YES pozisyon kazandıysa YES olayı gerçekleşti, NO pozisyon
        # kazandıysa YES olayı gerçekleşmedi.
        yes_outcome = (side == "YES" and win) or (side == "NO" and not win)

        if side == "YES":
            st["yes_n"] += 1
            if yes_outcome:
                st["yes_wins"] += 1
        else:
            st["no_n"] += 1
            if not yes_outcome:  # NO kazandı → YES olayı olmadı
                st["no_wins"] += 1
            # Aynı bucket'ın yes_n/yes_wins'ini de güncelle (dolaylı veri)
            st["yes_n"] += 1
            if yes_outcome:
                st["yes_wins"] += 1

        # ── 2. Momentum istatistiği ──────────────────────────────────────────
        mom = _momentum_abs_from_rationale(row["rationale"])
        if mom is not None:
            half_veto = state.momentum_veto * 0.5
            if mom > half_veto:
                state.momentum_stats["confirmed_n"] += 1
                if win:
                    state.momentum_stats["confirmed_wins"] += 1
            else:
                state.momentum_stats["borderline_n"] += 1
                if win:
                    state.momentum_stats["borderline_wins"] += 1

        # ── 3. Edge istatistiği ──────────────────────────────────────────────
        try:
            edge = float(row["edge"])
            eb = _edge_bin(edge)
            state.edge_stats[eb]["n"] += 1
            if win:
                state.edge_stats[eb]["wins"] += 1
        except (TypeError, ValueError):
            pass

        # ── 4. TP / SL × tema ────────────────────────────────────────────────
        er = (row["exit_reason"] or "").strip().upper()
        if er in ("TP", "SL"):
            th = _position_theme_bucket(row["question"])
            slot = _theme_exit_slot(state, th)
            pnl = float(row["pnl_usd"] or 0)
            if er == "TP":
                slot["tp"] = int(slot["tp"]) + 1
                slot["tp_pnl"] = float(slot["tp_pnl"]) + pnl
            else:
                slot["sl"] = int(slot["sl"]) + 1
                slot["sl_pnl"] = float(slot["sl_pnl"]) + pnl
                if side == "YES" and yes_price_at_entry >= 0.75:
                    slot["high_yes_n"] = int(slot["high_yes_n"]) + 1
                    slot["high_yes_sl"] = int(slot["high_yes_sl"]) + 1

        state.processed_ids.add(row["id"])
        new_count += 1

    return new_count


def adapt_parameters(state: LearningState) -> list[str]:
    """Win-rate'e göre parametreleri otomatik ayarlar. Değişim mesajlarını döner."""
    changes: list[str] = []
    total_closed = sum(st["n"] for st in state.edge_stats.values())
    if total_closed < 5:
        return []  # Henüz yeterli data yok

    # ── Edge threshold adaptasyonu ───────────────────────────────────────────
    low_edge = state.edge_stats[0]   # edge < 0.10
    if low_edge["n"] >= 5:
        wr = low_edge["wins"] / low_edge["n"]
        et_min, et_max = _edge_threshold_bounds()
        if wr < 0.40 and state.edge_threshold < et_max:
            new_et = min(et_max, round(state.edge_threshold + 0.01, 3))
            changes.append(
                f"edge_threshold  {state.edge_threshold:.3f} → {new_et:.3f}  "
                f"(edge<0.10 win rate={wr:.0%}, {low_edge['n']} trade)"
            )
            state.edge_threshold = new_et
        elif wr > 0.65 and total_closed >= 20 and state.edge_threshold > et_min:
            new_et = max(et_min, round(state.edge_threshold - 0.005, 3))
            changes.append(
                f"edge_threshold  {state.edge_threshold:.3f} → {new_et:.3f}  "
                f"(genel performans iyi, threshold gevşetildi)"
            )
            state.edge_threshold = new_et

    # ── Momentum veto adaptasyonu ────────────────────────────────────────────
    ms = state.momentum_stats
    if ms["confirmed_n"] >= 5 and ms["borderline_n"] >= 5:
        conf_wr  = ms["confirmed_wins"]  / ms["confirmed_n"]
        bord_wr  = ms["borderline_wins"] / ms["borderline_n"]
        diff = conf_wr - bord_wr

        if diff > 0.15 and state.momentum_veto < MOMENTUM_VETO_MAX:
            # Momentum sinyali çok etkili → eşiği sıkılaştır
            new_mv = min(MOMENTUM_VETO_MAX, round(state.momentum_veto + 0.003, 4))
            changes.append(
                f"momentum_veto  {state.momentum_veto:.4f} → {new_mv:.4f}  "
                f"(confirmed={conf_wr:.0%} vs border={bord_wr:.0%}, diff=+{diff:.0%})"
            )
            state.momentum_veto = new_mv
        elif diff < -0.05 and state.momentum_veto > MOMENTUM_VETO_MIN:
            # Momentum filtresi fark yaratmıyor → gevşet
            new_mv = max(MOMENTUM_VETO_MIN, round(state.momentum_veto - 0.002, 4))
            changes.append(
                f"momentum_veto  {state.momentum_veto:.4f} → {new_mv:.4f}  "
                f"(momentum etkisi zayıf, filtre gevşetildi)"
            )
            state.momentum_veto = new_mv

    # ── Tema edge boost (yüksek SL oranı → o temada daha yüksek edge şart) ──
    boosts: dict[str, float] = {}
    for th, slot in state.theme_exits.items():
        tp_n = int(slot.get("tp", 0))
        sl_n = int(slot.get("sl", 0))
        exits = tp_n + sl_n
        if exits < 6:
            continue
        sl_rate = sl_n / exits
        if sl_rate >= 0.25:
            boost = min(0.08, round((sl_rate - 0.18) * 0.14, 3))
            if boost >= 0.015:
                boosts[th] = boost
        if th == "eurovision":
            hy_n = int(slot.get("high_yes_n", 0))
            if hy_n >= 3:
                hy_sl = int(slot.get("high_yes_sl", 0)) / hy_n
                if hy_sl >= 0.45:
                    boosts[th] = max(boosts.get(th, 0.0), 0.04)
    prev = dict(state.theme_edge_boost)
    state.theme_edge_boost = boosts
    for th, b in boosts.items():
        if abs(b - prev.get(th, 0.0)) > 1e-4:
            changes.append(
                f"theme_edge_boost[{th}]  +{b:.3f}  "
                f"(TP/SL çıkışlarında SL oranı yüksek)"
            )

    return changes


def _wilson_ci(wins: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    z = 1.645  # %90 CI
    p = wins / n
    denom = 1 + z*z/n
    centre = p + z*z/(2*n)
    margin = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return max(0.0, (centre-margin)/denom), min(1.0, (centre+margin)/denom)


def print_recent_loss_digest(
    conn: sqlite3.Connection, n: int = 8, min_loss_usd: float = 0.05
) -> None:
    """Son SL/kayıp kapanışlarının kısa özeti — hangi soru tipleri zarar etti."""
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, question, side, edge, pnl_usd
            FROM positions
            WHERE closed_at IS NOT NULL AND COALESCE(pnl_usd, 0) < ?
            ORDER BY datetime(closed_at) DESC
            LIMIT ?
            """,
            (-min_loss_usd, n),
        ).fetchall()
    except sqlite3.OperationalError:
        return
    if not rows:
        return
    print(f"  📉 Son kayıplar (PnL < -${min_loss_usd:.2f}, en fazla {n}):")
    for r in rows:
        q = (r["question"] or "")[:56]
        e = float(r["edge"] or 0)
        p = float(r["pnl_usd"] or 0)
        sid = r["side"] or "?"
        print(f"     #{r['id']} {sid} edge={e:+.2f} PnL=${p:.2f}  {q}")


def _position_theme_bucket(question: str | None) -> str:
    """Açık / kapalı pozisyon soruları için kaba tema (SL özeti ile uyumlu)."""
    ql = (question or "").lower()
    if "eurovision" in ql:
        return "eurovision"
    if "up or down" in ql:
        return "up_or_down"
    if "elon" in ql and "tweet" in ql:
        return "musk_tweets"
    if "wti" in ql or "crude" in ql:
        return "oil"
    if any(
        k in ql
        for k in ("bitcoin", "ethereum", "solana", "xrp", "ripple", "dogecoin")
    ):
        return "crypto_px"
    if "trump" in ql or "iran" in ql or "xi jinping" in ql:
        return "politics_live"
    if "lol:" in ql or "dota" in ql or "counter-strike" in ql or "esports" in ql:
        return "esports"
    if " o/u" in ql or ": o/u" in ql or "over/under" in ql or "spread:" in ql or "/o/u" in ql:
        return "sports_line"
    if " vs." in ql or " vs " in ql:
        return "sports_match"
    return "other"


def _hold_minutes(opened_at: str | None, closed_at: str | None) -> float | None:
    if not opened_at or not closed_at:
        return None
    try:
        o = datetime.fromisoformat(str(opened_at).replace("Z", "+00:00"))
        c = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
        if o.tzinfo is None:
            o = o.replace(tzinfo=timezone.utc)
        if c.tzinfo is None:
            c = c.replace(tzinfo=timezone.utc)
        return max(0.0, (c - o).total_seconds() / 60.0)
    except Exception:
        return None


def _classify_exit_for_report(row: sqlite3.Row) -> str:
    """exit_reason yoksa eski kayıtlar için kaba sınıf (* = türetilmiş)."""
    er = row["exit_reason"]
    if er:
        return str(er)
    if row["resolved_yes"] is not None:
        return "RESOLVED*"
    p = float(row["pnl_usd"] or 0)
    if p > 0.001:
        return "MTM+*"
    if p < -0.001:
        return "MTM-*"
    return "MTM~0*"


def print_closed_trade_report(conn: sqlite3.Connection, n: int = 60) -> None:
    """
    Son N kapalı pozisyon: çıkış sebebi, kazanma oranı, ort./medyan tutma (dk), toplam PnL.
    Yeni kapanışlarda exit_reason dolu; * ile bitenler geçmiş satırlar için sezgisel gruptur.
    """
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, opened_at, closed_at, stake_usd, pnl_usd, exit_reason, resolved_yes
            FROM positions
            WHERE closed_at IS NOT NULL
            ORDER BY datetime(closed_at) DESC
            LIMIT ?
            """,
            (max(1, n),),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"  [işlem raporu] sorgu hatası: {exc}")
        return

    if not rows:
        return

    by_reason: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "wins": 0, "pnl": 0.0, "holds": []}
    )
    holds_tp: list[float] = []
    total_pnl = 0.0
    wins = 0

    for r in rows:
        reason = _classify_exit_for_report(r)
        st = by_reason[reason]
        st["n"] = int(st["n"]) + 1
        pnl = float(r["pnl_usd"] or 0)
        st["pnl"] = float(st["pnl"]) + pnl
        total_pnl += pnl
        if pnl > 1e-6:
            st["wins"] = int(st["wins"]) + 1
            wins += 1
        hm = _hold_minutes(r["opened_at"], r["closed_at"])
        if hm is not None:
            holds: list[float] = st["holds"]
            holds.append(hm)
            if reason == "TP":
                holds_tp.append(hm)

    nrows = len(rows)
    wr = wins / nrows if nrows else 0.0
    all_holds = [
        h for r in rows
        if (h := _hold_minutes(r["opened_at"], r["closed_at"])) is not None
    ]
    med_hold = statistics.median(all_holds) if all_holds else 0.0
    med_tp = statistics.median(holds_tp) if holds_tp else None

    print(f"\n  {'─'*62}")
    print(f"  📈 İŞLEM RAPORU  (son {nrows} kapanış)")
    print(f"  {'─'*62}")
    line = (
        f"  Özet: kazanan {wins}/{nrows}  ({wr:.0%})  ΣPnL=${total_pnl:+.2f}  "
        f"tutma medyan={med_hold:.0f} dk"
    )
    if med_tp is not None:
        line += f"  |  TP medyan={med_tp:.0f} dk"
    print(line)

    order = (
        "TP", "SL", "RESOLVED", "SWAP", "EXP", "STALE", "MAX_HOLD",
        "RESOLVED*", "MTM+*", "MTM-*", "MTM~0*",
    )
    keys_sorted = sorted(
        by_reason.keys(),
        key=lambda k: (order.index(k) if k in order else 99, k),
    )

    print(f"\n  {'Sebep':<12} {'n':>4} {'kzn':>4} {'WR':>6} "
          f"{'ort dk':>8} {'med dk':>8} {'ΣPnL':>10}")
    for key in keys_sorted:
        st = by_reason[key]
        ni = int(st["n"])
        wi = int(st["wins"])
        hi: list[float] = st["holds"]
        wr_i = wi / ni if ni else 0.0
        avg_h = sum(hi) / len(hi) if hi else 0.0
        med_h = statistics.median(hi) if hi else 0.0
        print(
            f"  {key:<12} {ni:>4} {wi:>4} {wr_i:>5.0%} "
            f"{avg_h:>8.0f} {med_h:>8.0f} {float(st['pnl']):>+10.2f}"
        )

    print(f"  {'─'*62}\n")


def print_tp_sl_learning_report(conn: sqlite3.Connection) -> None:
    """Tüm kapalı işlemler: TP/SL tema özeti + öğrenilen edge boost."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, side, entry_price, edge, stake_usd, pnl_usd, exit_reason,
               opened_at, closed_at, question
        FROM positions
        WHERE closed_at IS NOT NULL
        ORDER BY datetime(closed_at) DESC
        """
    ).fetchall()
    if not rows:
        print("\n  (kapalı işlem yok)\n")
        return

    by_theme: dict[str, dict] = defaultdict(
        lambda: {"tp": 0, "sl": 0, "tp_pnl": 0.0, "sl_pnl": 0.0, "other": 0}
    )
    sl_rows: list[sqlite3.Row] = []
    tp_rows: list[sqlite3.Row] = []

    for r in rows:
        th = _position_theme_bucket(r["question"])
        er = (r["exit_reason"] or "").strip().upper()
        pnl = float(r["pnl_usd"] or 0)
        if er == "TP":
            by_theme[th]["tp"] += 1
            by_theme[th]["tp_pnl"] += pnl
            tp_rows.append(r)
        elif er == "SL":
            by_theme[th]["sl"] += 1
            by_theme[th]["sl_pnl"] += pnl
            sl_rows.append(r)
        else:
            by_theme[th]["other"] += 1

    total_tp = sum(1 for r in rows if (r["exit_reason"] or "").upper() == "TP")
    total_sl = sum(1 for r in rows if (r["exit_reason"] or "").upper() == "SL")
    tp_pnl = sum(float(r["pnl_usd"] or 0) for r in rows if (r["exit_reason"] or "").upper() == "TP")
    sl_pnl = sum(float(r["pnl_usd"] or 0) for r in rows if (r["exit_reason"] or "").upper() == "SL")

    print(f"\n  {'═'*62}")
    print(f"  📚 TP / SL ÖĞRENME RAPORU  ({len(rows)} kapalı işlem)")
    print(f"  {'═'*62}")
    print(
        f"  TP: {total_tp} adet  ΣPnL=${tp_pnl:+.2f}  |  "
        f"SL: {total_sl} adet  ΣPnL=${sl_pnl:+.2f}  |  "
        f"net TP+SL=${tp_pnl + sl_pnl:+.2f}"
    )
    print(f"\n  {'Tema':<14} {'TP':>4} {'SL':>4} {'SL%':>6} {'ΣTP':>9} {'ΣSL':>9}")
    for th in sorted(by_theme.keys(), key=lambda k: -(by_theme[k]["tp"] + by_theme[k]["sl"])):
        st = by_theme[th]
        ex = st["tp"] + st["sl"]
        if ex == 0:
            continue
        sl_pct = st["sl"] / ex
        print(
            f"  {th:<14} {st['tp']:>4} {st['sl']:>4} {sl_pct:>5.0%} "
            f"{st['tp_pnl']:>+9.2f} {st['sl_pnl']:>+9.2f}"
        )

  # SL öğrenme notları
    print(f"\n  ⛔ SL dersleri (son {min(8, len(sl_rows))}):")
    for r in sl_rows[:8]:
        hm = _hold_minutes(r["opened_at"], r["closed_at"])
        yp = float(r["entry_price"]) if r["side"] == "YES" else (1.0 - float(r["entry_price"] or 0))
        print(
            f"    #{r['id']} {r['side']} YES≈{yp:.2f} edge={float(r['edge']):+.2f}  "
            f"PnL=${float(r['pnl_usd']):.2f}  {hm:.0f}dk  "
            f"[{_position_theme_bucket(r['question'])}]  "
            f"{(r['question'] or '')[:42]}"
        )

    print(f"\n  💰 TP örnekleri (son {min(5, len(tp_rows))}):")
    for r in tp_rows[:5]:
        hm = _hold_minutes(r["opened_at"], r["closed_at"])
        print(
            f"    #{r['id']} {r['side']} edge={float(r['edge']):+.2f}  "
            f"PnL=${float(r['pnl_usd']):+.2f}  {hm:.0f}dk  "
            f"[{_position_theme_bucket(r['question'])}]"
        )

    state = LearningState.load()
    _migrate_learning_state(state)
    if state.theme_edge_boost:
        print("\n  🔧 Öğrenilen tema edge boost (girişte ek edge şartı):")
        for th, b in sorted(state.theme_edge_boost.items(), key=lambda x: -x[1]):
            print(f"     {th}: +{b:.3f}")
    else:
        print("\n  (Henüz tema edge boost yok — yeterli TP/SL örneği birikince güncellenir.)")
    print(f"  {'═'*62}\n")


def audit_all_trades(conn: sqlite3.Connection, *, force_relearn: bool = False) -> dict:
    """
    Tüm kapalı işlemleri yeniden işle, parametreleri güncelle, TP/SL raporu bas.
    force_relearn=True → learning_state.pkl sıfırdan.
    """
    if force_relearn and LEARNING_PATH.exists():
        LEARNING_PATH.unlink()
    state = LearningState.load()
    _migrate_learning_state(state)
    if force_relearn:
        state.processed_ids.clear()
        state.theme_exits.clear()
        state.theme_edge_boost.clear()
    else:
        state.processed_ids.clear()

    new_n = process_closed_positions(state, conn)
    changes = adapt_parameters(state)
    state.updated_at = datetime.now(timezone.utc).isoformat()
    state.save()

    print_tp_sl_learning_report(conn)
    print_report(state)
    if changes:
        print("  Uygulanan ayarlar:")
        for c in changes:
            print(f"    • {c}")

    return {
        "momentum_veto": state.momentum_veto,
        "edge_threshold": state.edge_threshold,
        "calibration": state.calibration_dict(),
        "theme_edge_boost": dict(state.theme_edge_boost),
        "processed_new": new_n,
    }


def print_sl_digest(conn: sqlite3.Connection, n: int = 15) -> None:
    """Son SL (veya güçlü kayıp) kapanışları — hangi soru tipleri SL yedi."""
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, side, edge, pnl_usd, exit_reason, opened_at, closed_at, question
            FROM positions
            WHERE closed_at IS NOT NULL
              AND (
                exit_reason = 'SL'
                OR (exit_reason IS NULL AND resolved_yes IS NULL AND COALESCE(pnl_usd, 0) < -0.04)
              )
            ORDER BY datetime(closed_at) DESC
            LIMIT ?
            """,
            (max(1, n),),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"  [SL özeti] sorgu hatası: {exc}")
        return
    if not rows:
        return

    def bucket(q: str) -> str:
        return _position_theme_bucket(q)

    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[bucket(r["question"] or "")] += 1

    print(f"\n  {'─'*62}")
    print(f"  ⛔ SL ÖZETİ  (son {len(rows)} güçlü kayıp / SL)")
    print(f"  {'─'*62}")
    top = sorted(counts.items(), key=lambda x: -x[1])[:6]
    print("  Tür dağılımı:  " + "  ".join(f"{k}={v}" for k, v in top))
    print("  Örnekler:")
    for r in rows[:8]:
        hm = _hold_minutes(r["opened_at"], r["closed_at"])
        ht = f"{hm:.0f}dk" if hm is not None else "?"
        q = (r["question"] or "")[:52]
        er = r["exit_reason"] or "—"
        print(
            f"    #{r['id']} {r['side']} {er}  edge={float(r['edge']):+.2f}  "
            f"PnL=${float(r['pnl_usd']):.2f}  {ht}  [{bucket(r['question'] or '')}]  {q}"
        )
    print(f"  {'─'*62}\n")


def print_open_positions_digest(conn: sqlite3.Connection) -> None:
    """Açık pozisyonlar: tema dağılımı, toplam stake, benzer soru önekleri."""
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, side, edge, stake_usd, entry_price, opened_at, question
            FROM positions
            WHERE closed_at IS NULL
            ORDER BY datetime(opened_at) ASC
            """
        ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"  [açık kitap] sorgu hatası: {exc}")
        return
    if not rows:
        print("\n  📂 Açık pozisyon yok.\n")
        return

    by_theme: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"n": 0, "stake": 0.0}
    )
    by_prefix: dict[str, int] = defaultdict(int)

    for r in rows:
        q = r["question"] or ""
        th = _position_theme_bucket(q)
        by_theme[th]["n"] = int(by_theme[th]["n"]) + 1  # type: ignore[assignment]
        by_theme[th]["stake"] = float(by_theme[th]["stake"]) + float(r["stake_usd"] or 0)  # type: ignore[assignment]
        pref = (q[:44] + "…") if len(q) > 45 else q
        by_prefix[pref] += 1

    tot_st = sum(float(r["stake_usd"] or 0) for r in rows)
    print(f"\n  {'─'*62}")
    print(f"  📂 AÇIK POZİSYON ÖZETİ  ({len(rows)} adet, Σstake≈${tot_st:.2f})")
    print(f"  {'─'*62}")
    print(f"  {'Tema':<16} {'adet':>5}  {'Σ stake':>10}")
    for th in sorted(by_theme.keys(), key=lambda k: (-int(by_theme[k]["n"]), k)):  # type: ignore[arg-type]
        st = by_theme[th]
        print(f"  {th:<16} {int(st['n']):>5}  ${float(st['stake']):>9.2f}")
    dup = [(p, n) for p, n in by_prefix.items() if n > 1]
    dup.sort(key=lambda x: -x[1])
    if dup:
        print(f"\n  Aynı önek (≥2): {len(dup)} grup")
        for p, n in dup[:6]:
            print(f"    ×{n}  {p[:58]}")
    print("\n  Satırlar:")
    for r in rows:
        q = (r["question"] or "")[:56]
        th = _position_theme_bucket(r["question"])
        print(
            f"    #{r['id']} {r['side']} @{float(r['entry_price']):.3f}  "
            f"edge={float(r['edge']):+.2f}  ${float(r['stake_usd']):.2f}  "
            f"[{th}]  {q}"
        )
    print(f"  {'─'*62}\n")


def print_recent_closed_digest(
    conn: sqlite3.Connection, days: int = 7, limit: int = 80
) -> None:
    """Son `days` gün içinde kapananlar: tema + exit_reason özeti ve örnek liste."""
    conn.row_factory = sqlite3.Row
    d = max(1, min(int(days), 120))
    lim = max(5, min(int(limit), 500))
    cut = (datetime.now(timezone.utc) - timedelta(days=d)).strftime("%Y-%m-%d")
    try:
        rows = conn.execute(
            """
            SELECT id, side, edge, pnl_usd, exit_reason, resolved_yes,
                   opened_at, closed_at, question
            FROM positions
            WHERE closed_at IS NOT NULL AND substr(closed_at, 1, 10) >= ?
            ORDER BY datetime(closed_at) DESC
            LIMIT ?
            """,
            (cut, lim),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"  [son kapanışlar] sorgu hatası: {exc}")
        return

    print(f"\n  {'─'*62}")
    print(f"  📅 SON {d} GÜN KAPANIŞLAR  (en fazla {lim} kayıt, closed_at ≥ {cut})")
    print(f"  {'─'*62}")
    if not rows:
        print("  (kayıt yok)\n")
        return

    wins = sum(1 for r in rows if float(r["pnl_usd"] or 0) > 1e-6)
    losses = sum(1 for r in rows if float(r["pnl_usd"] or 0) < -1e-6)
    pnl_sum = sum(float(r["pnl_usd"] or 0) for r in rows)
    wr = wins / len(rows) if rows else 0.0
    print(f"  Örneklem: {len(rows)}  kazanan={wins}  kayıp={losses}  WR≈{wr:.0%}  ΣPnL=${pnl_sum:+.2f}")

    by_theme: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"n": 0, "pnl": 0.0, "wins": 0}
    )
    by_exit: dict[str, int] = defaultdict(int)
    for r in rows:
        th = _position_theme_bucket(r["question"])
        st = by_theme[th]
        st["n"] = int(st["n"]) + 1  # type: ignore[assignment]
        p = float(r["pnl_usd"] or 0)
        st["pnl"] = float(st["pnl"]) + p  # type: ignore[assignment]
        if p > 1e-6:
            st["wins"] = int(st["wins"]) + 1  # type: ignore[assignment]
        er = r["exit_reason"] or "(null)"
        by_exit[str(er)] += 1

    print(f"\n  {'Tema':<16} {'n':>5} {'WR':>7} {'ΣPnL':>10}")
    for th in sorted(by_theme.keys(), key=lambda k: (-int(by_theme[k]["n"]), k)):  # type: ignore[arg-type]
        st = by_theme[th]
        ni = int(st["n"])
        wi = int(st["wins"])
        wr_t = wi / ni if ni else 0.0
        print(
            f"  {th:<16} {ni:>5} {wr_t:>6.0%} {float(st['pnl']):>+10.2f}"
        )
    print(f"\n  exit_reason:  " + "  ".join(f"{k}={v}" for k, v in sorted(by_exit.items(), key=lambda x: -x[1])[:8]))

    print("\n  Son kapanışlar (örnek):")
    for r in rows[:14]:
        hm = _hold_minutes(r["opened_at"], r["closed_at"])
        ht = f"{hm:.0f}dk" if hm is not None else "?"
        er = r["exit_reason"] or "—"
        th = _position_theme_bucket(r["question"])
        q = (r["question"] or "")[:48]
        print(
            f"    #{r['id']} {r['side']} {er}  [{th}]  "
            f"PnL=${float(r['pnl_usd']):+.2f}  {ht}  {q}"
        )
    print(f"  {'─'*62}\n")


def print_report(state: LearningState) -> None:
    """Kapsamlı öğrenme raporu basar."""
    total_closed = sum(st["n"] for st in state.edge_stats.values())
    total_wins   = sum(st["wins"] for st in state.edge_stats.values())
    wr = total_wins / total_closed if total_closed > 0 else 0.0

    print(f"\n  {'─'*62}")
    print(f"  📊 SELF-IMPROVE RAPORU  [{total_closed} kapalı, {total_wins} kazanç, {wr:.0%} win rate]")
    print(f"  {'─'*62}")

    # Per-bucket kalibrasyon güncellemesi
    print(f"  {'Bucket':<10} {'Prior':>7} {'Posterior':>10} {'Live':>8} {'CI90%':>16}  Δ")
    for bi in range(10):
        prior_p, prior_n = PRIOR[bi]
        post_p = state.posterior_yes_prob(bi)
        st = state.bucket_stats[bi]
        live_n = st["yes_n"]
        live_wins = st["yes_wins"]
        lo, hi = _wilson_ci(live_wins, live_n) if live_n > 0 else (0.0, 1.0)
        delta = post_p - prior_p
        delta_str = f"{delta:+.4f}" if live_n > 0 else "    —  "
        live_str  = f"{live_wins}/{live_n}" if live_n > 0 else "—"
        ci_str    = f"{lo:.2f}–{hi:.2f}" if live_n > 0 else "—"
        print(f"  {bi/10:.1f}–{(bi+1)/10:.1f}     {prior_p:>6.4f}   {post_p:>9.4f}  "
              f"{live_str:>8}  {ci_str:>15}  {delta_str}")

    # Edge performansı
    print(f"\n  Edge Katmanı Performansı:")
    labels = ["<0.10", "0.10-0.20", "0.20-0.30", "0.30+"]
    for i, lbl in enumerate(labels):
        st = state.edge_stats[i]
        if st["n"] == 0:
            print(f"    {lbl:<12} —")
        else:
            wr_e = st["wins"] / st["n"]
            bar = "█" * int(wr_e * 20)
            print(f"    {lbl:<12} {wr_e:>5.0%}  {bar:<20}  ({st['wins']}/{st['n']})")

    # Momentum
    ms = state.momentum_stats
    print(f"\n  Momentum Etkinliği:")
    if ms["confirmed_n"] > 0:
        cwr = ms["confirmed_wins"] / ms["confirmed_n"]
        print(f"    Onaylı (|mom|>veto/2):   {cwr:.0%}  ({ms['confirmed_wins']}/{ms['confirmed_n']})")
    if ms["borderline_n"] > 0:
        bwr = ms["borderline_wins"] / ms["borderline_n"]
        print(f"    Sınır  (|mom|<veto/2):   {bwr:.0%}  ({ms['borderline_wins']}/{ms['borderline_n']})")

    print(f"\n  Güncel Parametreler:")
    print(f"    momentum_veto  = {state.momentum_veto:.4f}")
    print(f"    edge_threshold = {state.edge_threshold:.4f}")
    print(f"  {'─'*62}\n")


def load_learned_snapshot() -> dict:
    """Paper öğrenmesini canlı tarayıcıya salt-okunur aktarır (learning_state.pkl)."""
    state = LearningState.load()
    _migrate_learning_state(state)
    return {
        "momentum_veto": state.momentum_veto,
        "edge_threshold": state.edge_threshold,
        "calibration": state.calibration_dict(),
        "theme_edge_boost": dict(state.theme_edge_boost),
    }


def _ensure_apex_session(state: LearningState, conn: sqlite3.Connection) -> None:
    """APEX oturum başlangıç/hedef equity — sıfır DB'de bir kez ayarla."""
    if not _apex_mode():
        return
    try:
        start_bal = float(os.getenv("STARTING_BALANCE", "22000"))
    except ValueError:
        start_bal = 22_000.0
    try:
        mult = float(os.getenv("APEX_TARGET_MULTIPLIER", "2"))
    except ValueError:
        mult = 2.0
    state.profile_name = os.getenv("PROFILE_NAME", "apex_2x_24h")
    try:
        state.profile_version = int(os.getenv("PROFILE_VERSION", "0"))
    except ValueError:
        state.profile_version = 0
    if state.session_start_equity <= 0:
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) t FROM positions WHERE closed_at IS NOT NULL"
        ).fetchone()
        realized = float(row["t"] if row else 0)
        state.session_start_equity = start_bal
        state.session_target_equity = start_bal * mult
        if realized != 0:
            state.session_start_equity = max(start_bal, start_bal - realized)


def print_apex_progress(conn: sqlite3.Connection, state: LearningState) -> None:
    if not _apex_mode() or state.session_target_equity <= 0:
        return
    row = conn.execute(
        "SELECT COALESCE(SUM(pnl_usd),0) t, COUNT(*) n FROM positions "
        "WHERE closed_at IS NOT NULL AND ABS(COALESCE(pnl_usd,0)) > 0.0001"
    ).fetchone()
    realized = float(row["t"] if row else 0)
    n = int(row["n"] if row else 0)
    start = state.session_start_equity or float(os.getenv("STARTING_BALANCE", "22000"))
    target = state.session_target_equity or start * 2
    equity = start + realized
    need = target - equity
    pct = (realized / max(start, 1)) * 100
    tgt_pct = ((equity - start) / max(target - start, 1)) * 100
    print(f"\n  {'═'*62}")
    print(f"  🎯 APEX 2×24H  profil={state.profile_name} v{state.profile_version}")
    print(f"  {'═'*62}")
    print(
        f"  Başlangıç: ${start:,.2f}  |  Şimdi: ${equity:,.2f}  "
        f"|  Hedef: ${target:,.2f}"
    )
    print(
        f"  Realize: ${realized:+,.2f} ({pct:+.1f}% / 2× için {tgt_pct:.0f}% yol)  "
        f"|  Kalan: ${need:+,.2f}  |  {n} kapalı işlem"
    )
    print(f"  {'═'*62}\n")


def run(conn: sqlite3.Connection) -> dict:
    """
    Ana giriş noktası — scanner her döngüde bu fonksiyonu çağırır.
    Güncel parametreleri döner: {"momentum_veto": ..., "edge_threshold": ..., "calibration": ...}
    """
    state = LearningState.load()
    _ensure_apex_session(state, conn)
    new_count = process_closed_positions(state, conn)

    if new_count > 0:
        changes = adapt_parameters(state)
        _sync_apex_edge(state)
        total_closed = sum(st["n"] for st in state.edge_stats.values())

        if changes:
            print(f"  🔧 Parametre güncellendi:")
            for c in changes:
                print(f"     {c}")

        try:
            report_every = int(os.getenv("APEX_REPORT_EVERY_CLOSES", "6"))
        except ValueError:
            report_every = 6
        if _apex_mode():
            report_every = min(report_every, 10)
        # APEX: daha sık rapor; varsayılan 10
        if total_closed - state.last_report_n >= report_every:
            print_report(state)
            print_recent_loss_digest(conn)
            try:
                tr_n = int(os.getenv("TRADE_REPORT_LAST_N", "60"))
            except ValueError:
                tr_n = 60
            print_closed_trade_report(conn, n=max(10, tr_n))
            try:
                sl_n = int(os.getenv("SL_DIGEST_LAST_N", "15"))
            except ValueError:
                sl_n = 15
            print_sl_digest(conn, n=max(5, sl_n))
            print_apex_progress(conn, state)
            state.last_report_n = total_closed

        state.updated_at = datetime.now(timezone.utc).isoformat()
        state.save()
    elif _apex_mode() and state.session_target_equity <= 0:
        _ensure_apex_session(state, conn)
        state.save()

    return {
        "momentum_veto":  state.momentum_veto,
        "edge_threshold": state.edge_threshold,
        "calibration":    state.calibration_dict(),
        "theme_edge_boost": dict(state.theme_edge_boost),
    }
