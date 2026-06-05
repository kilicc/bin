"""Backtest Trainer — Shadow Trading ile kendini eğitir.

Çalışma prensibi:
  1. KAYIT: Tarama sırasında HER incelenen market (girilsin veya girilmesin)
     shadow_observations tablosuna kaydedilir (fiyat + sinyal + zaman).

  2. KONTROL: Idle döngüde, kayıtlı marketlerin kapanıp kapanmadığı kontrol edilir.
     Kapananlar için outcomePrices → YES mi NO mi kazandı?

  3. EĞİTİM: Sinyal ile sonuç karşılaştırılır → self_improver'a bildirilir.
     78 gerçek trade yerine yüzlerce/binlerce eğitim noktası üretir.

  4. OPTİMİZASYON: Farklı edge_threshold değerleri simüle edilir,
     en iyi performans gösteren önerilir.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).parent
DATA = ROOT / "data"
GAMMA = "https://gamma-api.polymarket.com"
CLOB  = "https://clob.polymarket.com"

# ─── DB Kurulumu ────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id    TEXT NOT NULL,
    question     TEXT,
    yes_price    REAL NOT NULL,
    signal_side  TEXT,           -- 'YES' | 'NO' | NULL (sinyal yok)
    signal_edge  REAL,
    observed_at  TEXT NOT NULL,
    end_date     TEXT,
    resolved_yes INTEGER,        -- 1=YES kazandı, 0=NO kazandı, NULL=henüz bilinmiyor
    resolved_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_shadow_unresolved
    ON shadow_observations(resolved_yes) WHERE resolved_yes IS NULL;
"""

def init_shadow_db(conn: sqlite3.Connection):
    conn.executescript(SCHEMA)
    conn.commit()


# ─── Yardımcı ───────────────────────────────────────────────────────────────
def _safe_get(client: httpx.Client, url: str, params: dict, timeout: float = 12.0) -> Any:
    try:
        r = client.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _parse_prices(raw) -> tuple[float, float] | None:
    try:
        prices = raw if isinstance(raw, list) else json.loads(raw or "[]")
        yes_p = float(prices[0])
        no_p  = float(prices[1]) if len(prices) > 1 else 1.0 - yes_p
        if 0.001 < yes_p < 0.999:
            return yes_p, no_p
    except Exception:
        pass
    return None


# ─── 1. Gözlem Kaydetme ─────────────────────────────────────────────────────
def record_observation(
    conn: sqlite3.Connection,
    market_id: str,
    question: str,
    yes_price: float,
    signal_side: str | None,
    signal_edge: float | None,
    end_date: str | None,
):
    """
    Taranan her marketi kaydet. Aynı market+gün kombinasyonu için tekrar kaydedilmez.
    """
    from datetime import date
    today = date.today().isoformat()
    exists = conn.execute(
        "SELECT id FROM shadow_observations "
        "WHERE market_id=? AND DATE(observed_at)=? LIMIT 1",
        (market_id, today)
    ).fetchone()
    if exists:
        return  # Bugün zaten kaydedilmiş

    conn.execute("""
        INSERT INTO shadow_observations
            (market_id, question, yes_price, signal_side, signal_edge, observed_at, end_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        market_id, question[:200], yes_price,
        signal_side, signal_edge,
        datetime.now(timezone.utc).isoformat(),
        end_date,
    ))
    conn.commit()


# ─── 2. Çözümlenen Marketleri Kontrol Et ────────────────────────────────────
def check_resolutions(
    conn: sqlite3.Connection,
    client: httpx.Client,
    max_check: int = 30,
) -> int:
    """
    Henüz sonuç bilinmeyen gözlemleri kontrol eder.
    Kapananlar için Gamma'dan güncel fiyatı çeker.
    Döner: güncellenen kayıt sayısı.
    """
    unresolved = conn.execute("""
        SELECT id, market_id, end_date
        FROM shadow_observations
        WHERE resolved_yes IS NULL
          AND end_date IS NOT NULL
        ORDER BY end_date ASC
        LIMIT ?
    """, (max_check,)).fetchall()

    if not unresolved:
        return 0

    now = datetime.now(timezone.utc)
    updated = 0

    for row in unresolved:
        # Kapanma zamanı geçti mi?
        try:
            end_dt = datetime.fromisoformat(str(row["end_date"]).replace("Z", "+00:00"))
            if end_dt > now:
                continue   # Henüz kapanmadı
        except Exception:
            continue

        # Gamma'dan güncel fiyatı çek
        data = _safe_get(client, f"{GAMMA}/markets/{row['market_id']}", params={}, timeout=8.0)
        if not data:
            # Batch endpoint dene
            data = _safe_get(client, f"{GAMMA}/markets",
                             params={"id": row["market_id"]}, timeout=8.0)
            if isinstance(data, list) and data:
                data = data[0]

        if not data:
            continue

        prices = _parse_prices(data.get("outcomePrices"))
        if prices is None:
            continue

        yes_p, _ = prices
        if yes_p >= 0.95:
            resolved_yes = 1
        elif yes_p <= 0.05:
            resolved_yes = 0
        else:
            continue   # Belirsiz

        conn.execute("""
            UPDATE shadow_observations
            SET resolved_yes=?, resolved_at=?
            WHERE id=?
        """, (resolved_yes, now.isoformat(), row["id"]))
        conn.commit()
        updated += 1
        time.sleep(0.05)

    return updated


# ─── 3. Çözümlenenlerden Öğren ──────────────────────────────────────────────
def learn_from_resolutions(
    conn: sqlite3.Connection,
    calibration: dict,
    verbose: bool = True,
) -> dict:
    """
    Çözümlenen shadow gözlemlerini işler, parametre varyantlarını test eder.
    Döner: {"processed": int, "accuracy": float, "best_edge": float}
    """
    rows = conn.execute("""
        SELECT id, yes_price, signal_side, signal_edge, resolved_yes
        FROM shadow_observations
        WHERE resolved_yes IS NOT NULL
          AND id NOT IN (
              SELECT CAST(value AS INTEGER)
              FROM shadow_observations, json_each('[]')
          )
        ORDER BY resolved_at DESC
        LIMIT 500
    """).fetchall()

    # Tüm çözümlenmiş kayıtlar (processed_ids benzeri mekanizma olmadan tüm veriyle çalış)
    rows = conn.execute("""
        SELECT yes_price, signal_side, resolved_yes
        FROM shadow_observations
        WHERE resolved_yes IS NOT NULL
        ORDER BY resolved_at DESC
        LIMIT 500
    """).fetchall()

    if not rows:
        return {"processed": 0}

    # Kalibrasyon doğruluk analizi
    bucket_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    variant_stats = defaultdict(lambda: {"correct": 0, "total": 0})

    edge_variants = {
        "edge_0.06": 0.06,
        "edge_0.10": 0.10,
        "edge_0.15": 0.15,
        "edge_0.20": 0.20,
    }

    correct_total = wrong_total = 0

    for row in rows:
        yes_price = row["yes_price"]
        resolved_yes = bool(row["resolved_yes"])
        bi = min(9, int(yes_price * 10))

        # Mevcut kalibrasyon sinyali doğru muydu?
        side = row["signal_side"]
        if side:
            won = (side == "YES" and resolved_yes) or (side == "NO" and not resolved_yes)
            if won:
                correct_total += 1
                bucket_stats[bi]["correct"] += 1
            else:
                wrong_total += 1
            bucket_stats[bi]["total"] += 1

        # Varyant testleri
        if calibration and bi in calibration:
            cal_val = calibration[bi]
            true_yes = cal_val[0] if isinstance(cal_val, (list, tuple)) else cal_val
            yes_edge = true_yes - yes_price
            no_edge  = (1 - true_yes) - (1 - yes_price)

            for vk, vthresh in edge_variants.items():
                if yes_edge >= no_edge and yes_edge >= vthresh:
                    vsig = "YES"
                elif no_edge > yes_edge and no_edge >= vthresh:
                    vsig = "NO"
                else:
                    continue
                vwon = (vsig == "YES" and resolved_yes) or (vsig == "NO" and not resolved_yes)
                variant_stats[vk]["total"] += 1
                if vwon:
                    variant_stats[vk]["correct"] += 1

    total = correct_total + wrong_total
    accuracy = correct_total / total if total > 0 else 0.0

    # En iyi varyantı seç
    best_edge = 0.06
    best_vacc = 0.0
    for vk, vparams in edge_variants.items():
        vs = variant_stats[vk]
        if vs["total"] >= 10:
            vacc = vs["correct"] / vs["total"]
            if vacc > best_vacc:
                best_vacc = vacc
                best_edge = vparams

    if verbose and total >= 5:
        print(f"  📚 Shadow eğitim: {len(rows)} gözlem | doğruluk={accuracy:.1%} ({correct_total}/{total})")
        for vk, vs in sorted(variant_stats.items()):
            if vs["total"] >= 5:
                vacc = vs["correct"] / vs["total"]
                marker = " ← EN İYİ" if edge_variants[vk] == best_edge and vs["total"] >= 10 else ""
                print(f"       {vk:12} {vacc:.1%} ({vs['correct']}/{vs['total']}){marker}")
        if best_edge != 0.06 and best_vacc > accuracy + 0.03:
            print(f"  📚 Öneri: edge_threshold={best_edge:.2f} daha iyi ({best_vacc:.1%})")

    return {
        "processed": len(rows),
        "accuracy":  accuracy,
        "correct":   correct_total,
        "total":     total,
        "best_edge": best_edge,
        "best_vacc": best_vacc,
    }


# ─── Ana Fonksiyon ──────────────────────────────────────────────────────────
_last_run_ts: float = 0.0

def run_batch(
    client: httpx.Client,
    conn: sqlite3.Connection,
    calibration: dict,
    max_markets: int = 30,
    verbose: bool = True,
) -> dict:
    """
    Idle döngüde çağrılır. Çözümlenen gözlemleri kontrol eder ve öğrenir.
    """
    global _last_run_ts
    if time.time() - _last_run_ts < 300:   # 5dk cooldown
        return {"skipped": True, "reason": "cooldown"}

    _last_run_ts = time.time()

    init_shadow_db(conn)

    # Çözüm kontrolü
    updated = check_resolutions(conn, client, max_check=max_markets)

    # Öğren
    result = learn_from_resolutions(conn, calibration, verbose=verbose)
    result["newly_resolved"] = updated

    if verbose and updated == 0 and result.get("processed", 0) == 0:
        total_obs = conn.execute(
            "SELECT COUNT(*) n FROM shadow_observations"
        ).fetchone()["n"]
        unresolved = conn.execute(
            "SELECT COUNT(*) n FROM shadow_observations WHERE resolved_yes IS NULL"
        ).fetchone()["n"]
        if total_obs == 0:
            print(f"  📚 Shadow: Henüz gözlem yok. Tarama yaptıkça birikeceğim.")
        else:
            print(f"  📚 Shadow: {total_obs} gözlem ({unresolved} bekliyor, {total_obs-unresolved} çözümlendi)")

    return result
