# Elite Formula — Piyasa vs Formül Attribution

**Üretim:** 2026-05-16T21:00:06.351695+00:00
**Kapalı işlem:** 371 | **Net PnL:** $+2880.37 | **WR:** 77.4%

## Darboğaz
- **Birincil:** `formula`
- Paylar: hedef matematiği **28.9%** | piyasa **14.2%** | formül **56.8%**

## Hedef boşluğu
- Aspirasyon: $917/s
- Gerçekçi tavan: $0/s
- Realize: $94.28/s | Pace: 10%
- Aspirasyon $917/s ile mevcut stake/TP yapısında teorik tavan ~$0/s (WR≈77%, saatte ~4 kapanış varsayımı).

## Piyasa vs formül
- edge≥0.05 ama zarar: **84** işlem
- edge≥0.05 ve kâr: **287**
- edge≥0.05 iken zarar: fiyat/spread/volatilite (piyasa); düşük edge ile zarar: formül/kalibrasyon seçimi.

### Çıkış nedeni
- **SL:** n=79, PnL=$-1152.10
- **TP:** n=283, PnL=$+3834.54
- **RESOLVED:** n=8, PnL=$+198.09
- **MAX_HOLD:** n=1, PnL=$-0.17

## Tema
- **crypto:** n=155, WR=0.774, PnL=$+254.99
- **other:** n=120, WR=0.742, PnL=$+2654.89
- **sports_ou:** n=38, WR=0.868, PnL=$-1116.96
- **sports_other:** n=24, WR=0.75, PnL=$+965.24
- **sports_match:** n=20, WR=0.85, PnL=$-3.54
- **politics:** n=14, WR=0.714, PnL=$+125.74

## Dönem (era)
- **v1:** n=84, WR=0.81, PnL=$+2534.90
- **v2:** n=253, WR=0.739, PnL=$+285.51
- **mid:** n=34, WR=0.941, PnL=$+59.95

## Kalibrasyon (örneklem)
- Brier: **0.0578** (n=50000)

## İyileştirme maddeleri
1. Whale theme_wr ile paper WR farkı büyük — tema bazlı min_score kullanın.
2. Stake/TP ile $800/saat aspirasyonu gerçekçi tavanın çok üstünde; panelde ikili hedef kullanın.
3. Spor O/U ve canlı maç segmentlerini tam veto veya çok yüksek skor eşiği ile sınırlayın.
4. Formül skoru kuintilleri — düşük skor bandı negatifse min_score artırın.
5. Her işlemde score_parts + giriş YES fiyatı kaydı (shadow) ile attribution doğruluğu.
6. Kalibrasyon Brier yüksekse edge tahmini piyasa kaynaklı sapma üretir; calibration yenileyin.
