"""Kalibrasyon analizi — fetch_calibration_data.py'ın ürettiği veriyi işler.

Çıktılar:
  1. Genel calibration curve (10 bucket)
  2. Time-to-close bazlı 2D calibration (10×4 grid)
  3. Brier score (overall + by bucket)
  4. Mispricing band'ları (sistematik bias > threshold)
  5. Bayesian posterior güvenlerle her bucket için
"""
from __future__ import annotations

import math
import pickle
from collections import defaultdict
from pathlib import Path

DATA = Path("data")
CACHE = DATA / "calibration_data.pkl"


def brier(preds_and_outcomes: list[tuple[float, bool]]) -> float:
    if not preds_and_outcomes:
        return float("nan")
    return sum((p - (1.0 if o else 0.0)) ** 2 for p, o in preds_and_outcomes) \
           / len(preds_and_outcomes)


def wilson_ci(wins: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z*z/n
    centre = p + z*z/(2*n)
    margin = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (max(0.0, (centre - margin)/denom), min(1.0, (centre + margin)/denom))


def main():
    if not CACHE.exists():
        print(f"[X] {CACHE} yok. Önce: python fetch_calibration_data.py")
        return

    data = pickle.load(open(CACHE, "rb"))
    print(f"Yüklendi: {len(data):,} data point\n")
    if not data:
        return

    # === 1. Genel calibration curve (10 bucket) ===
    print("=" * 70)
    print(" 1) Genel Calibration Curve (tüm time horizons)")
    print("=" * 70)
    buckets = defaultdict(lambda: {"sum_p": 0.0, "sum_outcome": 0, "n": 0})
    for p, hours, outcome in data:
        bi = min(9, int(p * 10))
        buckets[bi]["sum_p"] += p
        buckets[bi]["sum_outcome"] += 1 if outcome else 0
        buckets[bi]["n"] += 1

    print(f"  {'bucket':<10}  {'mean_pred':>10}  {'actual_yes':>11}  "
          f"{'CI_95%':>20}  {'count':>8}  {'bias':>7}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*11}  {'-'*20}  {'-'*8}  {'-'*7}")
    total_correct = 0
    overall_brier_terms = []
    for bi in sorted(buckets):
        b = buckets[bi]
        if b["n"] == 0:
            continue
        mean_p = b["sum_p"] / b["n"]
        actual = b["sum_outcome"] / b["n"]
        lo, hi = wilson_ci(b["sum_outcome"], b["n"])
        bias = actual - mean_p
        range_lo = bi / 10
        range_hi = (bi + 1) / 10
        print(f"  {range_lo:.1f}–{range_hi:<5.1f}   {mean_p:>9.4f}   "
              f"{actual:>10.4f}   {lo:.3f}–{hi:.3f}      {b['n']:>8,}  "
              f"{bias:+.4f}")
        total_correct += b["sum_outcome"] if mean_p > 0.5 else (b["n"] - b["sum_outcome"])
        overall_brier_terms.append((mean_p, b["sum_outcome"], b["n"]))

    # Overall Brier
    brier_total = sum((p, b) for p, _, _ in overall_brier_terms) if False else 0.0
    # Brier doğrudan datapoints üzerinden
    brier_total = sum(
        (p - (1.0 if o else 0.0)) ** 2 for p, _, o in data
    ) / len(data)
    print(f"\n  Brier (overall): {brier_total:.4f}  "
          f"(random=0.25; baseline=mevcut piyasa fiyatı kalibrasyon)")
    print(f"  Naive hit rate (price>0.5 → YES): {total_correct/len(data):.2%}")

    # === 2. Time-to-close bazlı 2D matrix ===
    print("\n" + "=" * 70)
    print(" 2) Time-to-Close Bazlı Calibration Matrix")
    print("=" * 70)
    time_buckets = [
        ("<1h",       lambda h: h < 1),
        ("1-24h",     lambda h: 1 <= h < 24),
        ("1-7d",      lambda h: 24 <= h < 168),
        ("7-30d",     lambda h: 168 <= h < 720),
        (">30d",      lambda h: h >= 720),
    ]

    print(f"  {'price_bucket':<14}  {'<1h':>7}  {'1-24h':>9}  {'1-7d':>9}  "
          f"{'7-30d':>9}  {'>30d':>9}")
    for bi in range(10):
        row_data = []
        for tb_name, tb_filter in time_buckets:
            subset = [(p, o) for p, h, o in data
                      if int(p*10) == bi and tb_filter(h)]
            if not subset:
                row_data.append("—")
                continue
            actual = sum(1 for _, o in subset if o) / len(subset)
            mean_p = sum(p for p, _ in subset) / len(subset)
            row_data.append(f"{actual:.2f}({len(subset)})")
        print(f"  {bi/10:.1f}–{(bi+1)/10:.1f}      {'  '.join(f'{c:>9}' for c in row_data)}")
    print("\n  Format: 'actual_yes_rate(sample_count)'.  Beklenen: actual ≈ bucket_pred.")

    # === 3. Mispricing band'ları ===
    print("\n" + "=" * 70)
    print(" 3) Mispricing Detection — istatistiksel olarak anlamlı bias")
    print("=" * 70)
    print(f"  Z-skoru: |actual - mean_pred| / SE > 2.5 olan bucket'lar")
    print(f"  {'bucket':<12}  {'mean_pred':>10}  {'actual':>8}  {'bias':>8}  "
          f"{'z':>6}  {'sample':>8}  {'edge_alanı':>14}")
    findings = []
    for bi, b in buckets.items():
        if b["n"] < 100:
            continue
        mean_p = b["sum_p"] / b["n"]
        actual = b["sum_outcome"] / b["n"]
        se = math.sqrt(actual * (1 - actual) / b["n"]) if 0 < actual < 1 else 0
        if se == 0:
            continue
        z = (actual - mean_p) / se
        if abs(z) >= 2.5:
            edge_str = "BUY YES" if z > 0 else "BUY NO"
            findings.append((bi, mean_p, actual, actual - mean_p, z, b["n"], edge_str))
    findings.sort(key=lambda x: abs(x[4]), reverse=True)
    for bi, mp, ac, bias, z, n, edge in findings[:10]:
        print(f"  {bi/10:.1f}–{(bi+1)/10:<5.1f}   {mp:>9.4f}   "
              f"{ac:>7.4f}   {bias:+.4f}   {z:>+5.2f}   {n:>8,}   {edge:>14}")
    if not findings:
        print("  Anlamlı sistematik bias yok (piyasa iyi kalibre)")

    # === 4. Sonuç + öneri ===
    print("\n" + "=" * 70)
    print(" 4) Sonuç")
    print("=" * 70)
    if findings:
        print(f"  {len(findings)} bucket'ta anlamlı mispricing var.")
        print(f"  Top edge: bucket {findings[0][0]/10:.1f}–{(findings[0][0]+1)/10:.1f}  "
              f"bias={findings[0][3]:+.4f}  n={findings[0][5]:,}")
        print(f"  Strateji: bu bucket'lardaki açık market'lerde otomatik pozisyon.")
        print(f"  Live'a geçmeden önce: forward 30 gün paper-mode'da doğrula.")
    else:
        print(f"  Piyasa iyi kalibre. Mispricing edge yok.")
        print(f"  Sadece price-based mispricing yetmez; ek sinyaller gerekir")
        print(f"  (event kategorisi, volume momentum, time-of-day, vs).")
    print(f"\n  Tüm data: {len(data):,} (market_price, time_to_close, outcome) noktası")


if __name__ == "__main__":
    main()
