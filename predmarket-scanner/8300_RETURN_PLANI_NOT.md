# 8300 — Return artışı için ayrı plan (not)

Bu dosya **stake/sermaye ayarından bağımsız**dır. 8300’de Kelly + min $1000 + %50 deploy uygulandı; win rate iyi olsa da **return** hâlâ TP/SL ve kapanış mekaniğine bağlı.

## Sorun özeti

- Kazanç oranı yüksek ama **ortalama kazanç << ortalama zarar** hissi (ör. TP ~$7–15, SL ~$25).
- **STALE-TP $0** kapanışları compound sermayeyi büyütmez.
- **Tam unrealized TP** bazen büyük, çoğu zaman erken küçük realize.

## Plan C — Return odaklı (8300’e önerilen 2. aşama)

Uygulama sırası: önce 24–48 saat yeni stake ile ölç, sonra aşağıdakilerden biri.

### Seçenek C1 — TP/SL yeniden denge (8200 Plan A’nın compound versiyonu)

| Parametre | Mevcut (compound) | Öneri |
|-----------|-------------------|--------|
| `ELITE_TP_STAKE_PCT` | 0.007 | **0.012–0.015** |
| `ELITE_TP_TRIGGER_FRAC` | 0.85 | **0.90** |
| `ELITE_SL_STAKE_PCT` | 0.025 | **0.015–0.018** |
| `ELITE_STALE_TP_MIN_AGE_MIN` | 3 | **8–10** (sık $0 çıkışı azalt) |

Hedef: payoff ratio ≥ **1.5** (avg win / |avg loss|).

### Seçenek C2 — Compound koru, kârı büyüt

- `ELITE_TP_STAKE_PCT=0.007` kalır (sık döngü).
- `ELITE_MARKET_COOLDOWN_MIN=5` (daha hızlı tekrar giriş).
- Hedge kapalı kalır.
- **Risk:** paper return şişer, canlıda slippage ile erir.

### Seçenek C3 — Runner’ları koru, küçük TP’yi sınırla (kod)

Yeni env (ileride): `ELITE_TP_REALIZE_MODE=full|floor`  
- `full`: mevcut (unreal ≥ hedef → tam unrealized kapanış).  
- `floor`: kapanış PnL = max(tp_hedef, min(unreal, tp_hedef × 3)) — paper şişmesini azaltır, canlıya daha yakın.

## Ölçüm (her aşamada)

```sql
SELECT ROUND(AVG(CASE WHEN pnl_usd>0 THEN pnl_usd END),2) avg_win,
       ROUND(AVG(CASE WHEN pnl_usd<0 THEN pnl_usd END),2) avg_loss,
       ROUND(SUM(pnl_usd),2) total
FROM positions WHERE closed_at IS NOT NULL AND pnl_usd != 0;
```

Başarı: `avg_win / abs(avg_loss) >= 1.5` ve `total` pozitif trend.

## 8200 vs 8300 rolü

| Port | Rol |
|------|-----|
| **8200** | Sürdürülebilir R:R (Plan A) — canlıya yakın |
| **8300** | Compound + büyük stake — return Plan C ile ayarlanır |

Stake değişikliği return’ü tek başına çözmez; **Plan C** TP/SL ve STALE davranışını hedefler.
