# Tüm Port Ayarları — Özet Tablo

Kaynak: `scenarios/*.env` (snapshot anı). Geri yüklemede bu dosyalar `config/scenarios/` içinden kopyalanır.

---

## Port 8200 — ELITE APEX 2×24H (ana proje)

| Ayar | Değer |
|------|--------|
| `PROFILE_NAME` | elite_apex_2x_24h |
| `PAPER_DB_PATH` | data/elite_apex_2x_24h.db |
| `DASHBOARD_PORT` | 8200 |
| `DISABLE_LIVE_TRADING` | 1 |
| `STARTING_BALANCE` | 22000 |
| `ELITE_DECISION_MODE` | formula_learned |
| `ELITE_TARGET_EQUITY_MULT` | 2.0 |
| `ELITE_TARGET_HOURS` | 24 |
| `ELITE_TARGET_HOURLY_USD` | 917 |
| `ELITE_ACTIVE_CAPITAL_PCT` | 0.62 |
| `ELITE_MIN_STAKE_USD` | **500** (Kelly tabanı; WR ile üstü) |
| `ELITE_MAX_STAKE_USD` | 0 (WR ölçekli, üst sınır yok) |
| `ELITE_MAX_OPEN` | **14** (slot başına daha büyük stake) |
| `ELITE_MIN_EDGE` | 0.048 |
| `ELITE_MIN_FORMULA_SCORE` | 0.52 |
| `ELITE_TP_STAKE_PCT` | **0.018** (Plan A sürdürülebilir R:R) |
| `ELITE_SL_STAKE_PCT` | **0.015** |
| `ELITE_TP_TRIGGER_FRAC` | **0.92** |
| `ELITE_MIN_HOLD_BEFORE_SL_SEC` | **90** |
| `ELITE_SCAN_INTERVAL_SEC` | 10 |
| `ELITE_POSITION_CHECK_SEC` | 2 |
| `ELITE_STALE_TP_ENABLED` | 1 |
| `ELITE_STALE_TP_MIN_AGE_MIN` | **20** |
| `ELITE_MARKET_COOLDOWN_MIN` | 22 |
| `ELITE_VETO_ALL_SPORTS` | **0** (spor açık) |
| `PAPER_ONE_PER_EVENT` | 1 |
| `ELITE_ONE_CLUSTER` | 1 |
| `ELITE_VETO_BRACKETS` | 1 |

**Başlat:** `./run_elite_apex_2x_8200.sh --bg`

### 8200 — Kelly stake vs May 16 “yüksek PnL” yedek

Kelly kodda hâlâ var (`kelly_stake` → `compute_stake` in `elite_trader/scanner.py`). Sabit $1000 görünümü `ELITE_MIN_STAKE_USD=1000` + çok paralel pozisyondan kaynaklanıyordu.

| | May 16 yedek DB | Güncel hedef (May 2026) |
|--|-----------------|-------------------------|
| Ort. stake | ~$1.065 ($525–$1.607) | $500–$1.500+ (Kelly/WR) |
| Paper realize | ~$29.538 (41 kapanış) | Geçmiş oturuma bağlı |
| TP PnL / stake | ~**%91** (tam unrealized kapanış + döngü) | ~%0.7–20 (normal fiyat hareketi) |
| Ana kâr kaynağı | 30× TP, paper tekrar giriş | TP/SL oranı + stake dağılımı |

Yedek DB: `data/backups/apex_8200_20260516T224215Z/elite_apex_2x_24h.db`

**Geri getirilebilir:** değişken stake, döngü (TP sonrası cooldown yok). **Tekrarlanmaz:** otomatik %91 TP satırları ve $29k paper toplamı.

---

## Port 8300 — ELITE APEX Paper Compound (Plan B)

| Ayar | Değer |
|------|--------|
| `PROFILE_NAME` | elite_apex_2x_paper_compound |
| `PAPER_DB_PATH` | data/elite_apex_2x_24h_8300.db |
| `DASHBOARD_PORT` | 8300 |
| `ELITE_TP_STAKE_PCT` | 0.007 |
| `ELITE_TP_TRIGGER_FRAC` | 0.85 |
| `ELITE_SL_STAKE_PCT` | 0.025 |
| `ELITE_STALE_TP_MIN_AGE_MIN` | **3** |
| `ELITE_MARKET_COOLDOWN_MIN` | **8** |
| `ELITE_HEDGE_PROACTIVE` | **0** |
| `ELITE_MAX_OPEN` | 14 |
| `ELITE_ACTIVE_CAPITAL_PCT` | **0.50** (açık toplam ≤ bakiye×50%) |
| `ELITE_MIN_STAKE_USD` | **1000** (Kelly tabanı) |
| `ELITE_MAX_STAKE_USD` | 0 (üst sınır yok) |
| `ELITE_MIN_EDGE` | 0.045 |

**Başlat:** `./run_elite_apex_2x_8300.sh --fresh --bg` (ilk kurulum) · `./run_elite_apex_2x_8300.sh --bg`

**Uyarı:** Paper-only May 16 tarzı compound; canlıda aynı getiri garanti değil. 8200 (Plan A) ile paralel çalışır.

---

## Port 8160 — ELITE FORMULA 800h

| Ayar | Değer |
|------|--------|
| `DASHBOARD_PORT` | 8160 |
| `PAPER_DB_PATH` | data/elite_formula.db |
| `ELITE_MIN_STAKE_USD` | 1000 |
| `ELITE_MAX_STAKE_USD` | 3000 |
| `ELITE_MAX_OPEN` | 18 |
| `ELITE_MIN_EDGE` | 0.055 |
| `ELITE_MIN_FORMULA_SCORE` | 0.58 |
| `ELITE_TP_STAKE_PCT` | 0.007 |
| `ELITE_MARKET_COOLDOWN_MIN` | 45 |

**Başlat:** `./run_elite_formula_restart_8160.sh`

---

## Port 8150 — CAL PRIMARY

| Ayar | Değer |
|------|--------|
| `DASHBOARD_PORT` | 8150 |
| `ELITE_DECISION_MODE` | calibration_primary |
| `ELITE_MAX_STAKE_USD` | 175 |
| `ELITE_MIN_STAKE_USD` | 50 |
| `ELITE_MAX_OPEN` | 36 |

**Başlat:** `./run_elite_cal_primary_stack.sh`

---

## Port 8170 — VELOCITY

| Ayar | Değer |
|------|--------|
| `DASHBOARD_PORT` | 8170 |
| `ELITE_DECISION_MODE` | whale_legacy |
| `ELITE_MIN_STAKE_USD` | 750 |
| `ELITE_MAX_STAKE_USD` | 2000 |
| `ELITE_MAX_OPEN` | 30 |

**Başlat:** `./run_elite_velocity_stack.sh`

---

## Port 8180 — GLOBAL 2×

| Ayar | Değer |
|------|--------|
| `DASHBOARD_PORT` | 8180 |
| `ELITE_ACTIVE_CAPITAL_PCT` | 0.50 |
| `ELITE_MAX_OPEN` | 20 |
| `ELITE_SCAN_INTERVAL_SEC` | 8 |
| `ELITE_HEDGE_STAKE_FRAC` | 0.35 |

**Başlat:** `./run_elite_global_2x_stack.sh`

---

## Port 8190 — FRESH + SPARSE STAKE

| Ayar | Değer |
|------|--------|
| `DASHBOARD_PORT` | 8190 |
| `PAPER_DB_PATH` | data/elite_formula_8190_fresh.db |
| `ELITE_SPARSE_STAKE_ENABLED` | 1 |
| `ELITE_SPARSE_CAPITAL_PCT` | 0.50 |
| `ELITE_SPARSE_MAX_STAKE_USD` | 11000 |

**Başlat:** `./run_elite_formula_fresh_8190.sh`

---

## Port 9004 — Binance Futures (agresif $22k, tam USDT-M evreni)

| Ayar | Değer (kaynak: `scenarios/aggressive_9004.env`) |
|------|--------|
| HTTP | `localhost:9004` |
| `STARTING_BALANCE` | 22000 |
| `ELITE_ACTIVE_CAPITAL_PCT` | 0.50 |
| `ELITE_MIN_STAKE_USD` | 250 |
| `ELITE_MAX_STAKE_USD` | 0 (üst sınır yok) |
| `ELITE_MAX_OPEN` | 20 |
| `ELITE_STALE_TP_MIN_AGE_MIN` | 10 + `ELITE_STALE_TP_FORCE=1` |
| `BINANCE_FULL_UNIVERSE` | 1 (tüm USDT perpetual — borsada ~500+ sembol) |

**Başlat:** `python3 binance_elite_pro_9004.py` (log: `logs/binance_elite_pro_9004.log`, PID: `.pids/binance_elite_pro_9004.pid`)

Varsayılan **9003** için: `python3 binance_elite_pro.py` → `scenarios/elite_apex_2x_24h.env`, tam evren kapalı.

---

## Kök `.env` (tüm portlara önce yüklenir)

`run_elite_*.sh` sırası: `source .env` → `source scenarios/PORT.env`  
**Çakışmada senaryo dosyası kazanır.**

Örnek kök değerler (senaryo override edebilir):
- `STARTING_BALANCE=22000`
- `MAX_POSITION_USD` — 8200 senaryosunda 100000

---

## Kod modülleri (8200 davranışı)

| Dosya | Rol |
|-------|-----|
| `elite_trader/scanner.py` | Ana döngü, tarama, TP/SL |
| `elite_trader/stale_tp.py` | STALE-TP (8200) |
| `elite_trader/market_guards.py` | Cooldown, cluster, veto |
| `elite_trader/capital_allocator.py` | Stake hesabı |
| `elite_trader/sparse_stake.py` | 8190 only |
| `dashboard.py` | Web panel |
