# Sohbet Referansı — Predmarket Elite (8200 APEX)

Bu dosya, Cursor sohbetinde alınan kararların özetidir. Tam konuşma için Cursor transcript’ine bakın.

## Transcript konumu

```
~/.cursor/projects/Users-macbook-Downloads-testtt/agent-transcripts/
  6fcc18d6-3e6b-47cb-8313-bfb4da1becde/6fcc18d6-3e6b-47cb-8313-bfb4da1becde.jsonl
```

Cursor UI: sohbeti aç → menüden **Export** → yedek klasörüne `SOHBET_EXPORT.md` kaydet.

---

## Proje özeti

- **Klasör:** `/Users/macbook/Downloads/testtt/predmarket-scanner`
- **Ana stack:** Elite formula paper trader (Polymarket)
- **Odak port:** **8200** — `elite_apex_2x_24h` (APEX 2×24h, $22k hedef)

---

## Aktif elite portlar (bu sohbet)

| Port | Senaryo | DB | Başlatma |
|------|---------|-----|----------|
| 8150 | `elite_formula_cal_primary` | `elite_formula_cal.db` | `run_elite_cal_primary_stack.sh` |
| 8160 | `elite_formula_800h` | `elite_formula.db` | `run_elite_formula_restart_8160.sh` |
| 8170 | `elite_formula_velocity` | `elite_formula_velocity.db` | `run_elite_velocity_stack.sh` |
| 8180 | `elite_global_2x` | `elite_global_2x.db` | `run_elite_global_2x_stack.sh` |
| 8190 | `elite_formula_8190_fresh` | `elite_formula_8190_fresh.db` | `run_elite_formula_fresh_8190.sh` |
| **8200** | **`elite_apex_2x_24h`** | **`elite_apex_2x_24h.db`** | **`run_elite_apex_2x_8200.sh`** |

---

## 8200’de yapılan önemli özellikler

1. **APEX 2×24h** — 5 port sentezi; `ELITE_TARGET_EQUITY_MULT=2.0`, %62 aktif sermaye, WR ölçekli stake.
2. **STALE-TP** — `elite_trader/stale_tp.py`: uzun süre açık, zararda değil, TP’ye ulaşamayan pozisyonu kapatır (8200’e özel).
3. **Sparse stake** — sadece **8190** (`elite_trader/sparse_stake.py`).
4. **Market guards** — cluster, cooldown, bracket veto (`elite_trader/market_guards.py`).
5. **Paper only** — `DISABLE_LIVE_TRADING=1`; gerçek para yok.
6. **TP sonrası cooldown yok** — aynı markete hızlı tekrar giriş mümkün (paper); canlıda farklı.
7. **Tam reset** — `scripts/reset_all_ports_22k.sh` tüm portları $22k sıfırlar.
8. **İlk apex yedek** — `data/backups/apex_8200_20260516T224215Z/`

---

## Bilinen uyarılar (sohbetten)

- Paper PnL ≠ gerçek para (slippage, likidite, ücret, tekrar giriş döngüsü).
- Panel/tarayıcı terminal kapanınca **8200 düşer** → `--bg` kullan.
- Script **predmarket-scanner** içinden çalıştırılmalı (`testtt` kökünden değil).
- `ELITE_VETO_ALL_SPORTS=1` → çoğu turda `açılan=0` normal.

---

## 8200 güncel ayar notları (snapshot anı)

- **8200 Plan A:** `scenarios/elite_apex_2x_24h.env` — TP **0.018** / SL **0.015** / STALE **20 dk**
- **8300 Plan B:** `scenarios/elite_apex_2x_24h_paper_compound.env` — TP **0.007**×**0.85**, STALE **3 dk**, cooldown **8 dk**, hedge kapalı

Tam tablo: `AYARLAR_TUM_PORTLAR.md`

## 8200 stake (May 2026)

- Kelly hâlâ aktif; `ELITE_MIN_STAKE_USD=500`, `ELITE_MAX_OPEN=14` (May 16 dağılımına yakın).
- May 16 ~$29k: paper TP’de tam unrealized (~%91 stake), döngü — bkz. `AYARLAR_TUM_PORTLAR.md` → “Kelly stake vs May 16”.
