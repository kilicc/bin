# MEGA 9006 hibrit checkpoint (2026-06-06)

Kârlı +1200 rejiminin **omurgası** + bu sohbetteki **hız / kapanış / hub** iyileştirmeleri.

## Giriş

- Vol tarama (`MEGA_VOL_SCAN=1`, `MEGA_REGIME_AUTO=0`)
- Flash reversal + pump (`MEGA_FLASH_*`, BERSERK2 flash eşikleri)
- Yön/BTC guard, skor kapısı kapalı (`MEGA_SYSTEM_SCORE_GATE=0`)

## Çıkış

- TP-only, SL kapalı (`MEGA_DISABLE_SL_EXIT=1`, `MEGA_UNDERWATER_CUT=0`)
- SPIKE + borsa dual TP (`MEGA_EXCHANGE_DUAL_TP=1`)
- Hub mark tepe (`MEGA_PEAK_TRACK_HUB_MARK=1`, `MEGA_ASYNC_HUB=1`)
- Hızlı borsa kontrol (`MEGA_EXCHANGE_VELOCITY_TICK=1`, ~50–80 ms)

## Kayıt / panel

- Yeni oturumdan sonra kapalı satır: **Binance API doğrulamalı**
  - `MEGA_CLOSED_REQUIRE_API_FILLS=1`
  - `MEGA_PANEL_CLOSED_VERIFIED_ONLY=1`
  - `MEGA_PANEL_CLOSED_SESSION_ONLY=1`
- Panel geçici API hatasında **son iyi snapshot** gösterir (`paper-dashboard.js`)

## Deploy (GCP, veri arşivlenir)

```bash
./deploy/gcp_9006_hybrid_checkpoint_fresh.sh mega_hybrid_checkpoint_20260606 300 5000
```

- Borsa açık pozisyonları flatten
- `data/mega_9006/` arşiv → `data/deleted_archives/mega_9006_<ts>/`
- 5 dk bekleme, sonra `binance-elite-9006-mainnet` start

## Git

```bash
git tag -a mega-9006-hybrid-20260606 -m "MEGA 9006 hybrid hub/velocity checkpoint"
```
