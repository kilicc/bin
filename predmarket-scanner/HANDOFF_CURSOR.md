# Elite 9005 — Cursor Handoff (devam rehberi)

Bu dosya, projeyi **başka bir Cursor hesabı / makinede** aynı noktadan sürdürmek içindir.  
Son güncelleme: **2026-05-27**

---

## 1. Proje özeti

| Alan | Değer |
|------|--------|
| Klasör | `predmarket-scanner/` (repo kökü: `binancex/`) |
| Ana bot | `binance_elite_pro.py` → giriş: `binance_elite_pro_9005.py` |
| Panel | http://127.0.0.1:9005 |
| Mod | **BERSERK2** — yalnızca canlı demo emir (`ELITE_LIVE_ONLY=1`) |
| Borsa | Binance Futures **Demo** — `demo-fapi.binance.com` |
| Max açık | 10 pozisyon |
| Min net kapanış | **$0.40** (`ELITE_EXIT_MIN_NET_USD=0.40`) |

**Temel ilke (kullanıcı kararı):** Pozisyon uPnL, mark, fill ve kapalı işlem PnL/komisyonu **yalnızca Binance REST API** (`positionRisk`, `bookTicker`, `userTrades`). WS/cache/tahmin ile pozisyon gerçeği **ezilmez**.

---

## 2. Yeni makinede kurulum

```bash
cd predmarket-scanner

# Python venv (projede .venv varsa onu kullan)
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt   # veya projedeki mevcut kurulum adımları

# API anahtarları — .env dosyasını ESKİ makineden kopyala (GİZLİ)
# Zorunlu: BINANCE_API_KEY, BINANCE_API_SECRET (demo futures)
cp /eski/makine/predmarket-scanner/.env .env

# Senaryo env (repo içinde — commit edilebilir)
# scenarios/binance_elite_8300_9005.env
```

**Kontrol:** `.env` + `scenarios/binance_elite_8300_9005.env` birlikte yüklenir (`run_binance_elite_8300_9005.sh`).

---

## 3. Çalıştırma / durdurma

```bash
cd predmarket-scanner

# Tercih edilen (tek örnek, port temizliği)
./scripts/elite_9005_process_ctl.sh start
./scripts/elite_9005_process_ctl.sh status
./scripts/elite_9005_process_ctl.sh restart
./scripts/elite_9005_process_ctl.sh stop

# Terminal izleyici (ayrı terminal)
python3 scripts/position_monitor.py

# Log
tail -f logs/binance_elite_8300_9005.log
```

**Heartbeat:** `.pids/elite_9005_heartbeat.json`  
**API canlılık:** `curl -s http://127.0.0.1:9005/api/heartbeat | python3 -m json.tool`

---

## 4. Mimari (son oturumda yapılanlar)

### 4.1 Pozisyon motoru (ayrı thread)

- **`exchange-poll` thread** → yalnızca REST `positionRisk` (`_refresh_positions_cache_only`)
- Ayrı executor + lock (`exchange-pos-poll`) — panel/cüzdan fetch'i bloklamaz
- **`refresh_exchange_cache()`** → açık pozisyon varken çoğunlukla **cüzdan**; pozisyon taze ise `positionRisk` tekrar çekilmez
- Reconcile/dust → arka plan (`_schedule_exchange_reconcile`, ~60s throttle)

### 4.2 Zamanlama (demo-fapi benchmark)

30 REST ölçümü (idle):

| Endpoint | min | p50 | p95 |
|----------|-----|-----|-----|
| positionRisk | ~323 ms | ~340 ms | ~360 ms |
| bookTicker | ~311 ms | ~321 ms | ~341 ms |
| wallet | ~328 ms | ~342 ms | ~359 ms |

**Env (`scenarios/binance_elite_8300_9005.env`):**

```
ELITE_EXCHANGE_POSITION_REFRESH_SEC=0.34   # poll ≥ API RTT
ELITE_EXCHANGE_POSITION_TIMEOUT_SEC=2.5    # httpx global lock kuyruğu
ELITE_EXCHANGE_WALLET_REFRESH_SEC=5.0      # positionRisk'i bloklamasın
ELITE_POSITION_CHECK_SEC=0.015             # berserk2 profili 0.02 → ~20ms exit tick
```

**Not:** `client._get` tek `_api_lock` kullanır — eşzamanlı wallet + bookTicker + positionRisk kuyruk yapar. Gereksiz REST çağrılarından kaçının.

### 4.3 Exit / fee ekonomisi

- Kapanış: fill uPnL − komisyon − Est. Funding **> $0.40**
- `ELITE_PAPER_TAX_RATE=0` (paper vergi yok)
- Kapalı kayıt: **`settle_position_close()` / userTrades** zorunlu (`ELITE_EXCHANGE_TRUTH=1`)
- Fill doğrulama: REST `bookTicker` (WS değil); `mark_fallback` kaldırıldı
- TP yakın değilse bookTicker her tick'te çağrılmaz (API tıkanması önlendi)

### 4.4 Kopya kayıt temizliği

Hayalet/kopya kapalı işlemler silindi. Kriter: `is_verified_exchange_trade()` (`elite_trader/exchange_trade_truth.py`):

- `exchange_settled=true`
- `fee_source` + `pnl_source` = `binance_api`
- `exit_reason` ∉ `EXCHANGE-SYNC`, `SYNC-EXCHANGE`
- `signal_source` ≠ `ExchangeSync` (borsadan import kopyası)

```bash
# Önce say
python3 scripts/purge_copy_trades_9005.py --dry-run

# Uygula
python3 scripts/purge_copy_trades_9005.py --yes --reason "..."
```

Arşiv: `data/deleted_archives/copy_purge_*.json`  
Panel: `isBinanceApiTrade()` — yalnızca doğrulanmış satırlara **API** rozeti.

---

## 5. Kritik dosyalar

| Dosya | Rol |
|-------|-----|
| `binance_elite_pro.py` | Ana bot, worker'lar, `/api/live`, close path |
| `elite_trader/exchange_trade_truth.py` | API fee/PnL, backfill, `is_verified_exchange_trade`, purge |
| `elite_trader/exchange_settlement.py` | `settle_position_close`, userTrades |
| `elite_trader/exchange_fill_truth.py` | REST bookTicker fill, net gate |
| `elite_trader/exchange_position_sync.py` | TP/SL eval, `light_sync_exchange_fields` |
| `elite_trader/fee_economics.py` | Min net $0.40, `live_close_record_ok` |
| `elite_pro_state.py` | SQLite kapalı işlem kalıcılığı |
| `elite_pro_template.html` | Panel UI |
| `scripts/position_monitor.py` | Terminal monitor (bot API'den okur, ayrı positionRisk yok) |
| `scripts/elite_9005_process_ctl.sh` | start/stop/restart |
| `scenarios/binance_elite_8300_9005.env` | Tüm timing + mod ayarları |
| `DATA_PRESERVATION_9005.md` | Veri silme kuralları |

**State DB:** `data/binance_elite_8300_9005_state.db`  
**Paralel kitap:** `data/parallel_universes.json` (live-only modda hafif kullanım)

---

## 6. Veri koruma (agent kuralları)

**Asla** kullanıcı açıkça istemeden silme:

- `binance_elite_8300_9005_state.db`
- lessons, learner registry, proposals, SL registry, postmortem

Tam silme:

```bash
python3 scripts/delete_9005_history.py --reason "..." --yes
# veya
./scripts/reset_binance_elite_9005.sh --wipe-data --reason "..."
```

---

## 7. Bilinen sorunlar / dikkat

1. **positionRisk timeout** — startup'ta senkron + reconcile API'yi doldurur; ısınma sonrası düzelir. `exchange_poll_timeouts` heartbeat'te izlenir.
2. **position-price thread restart** — watchdog `stale 4s` uyarıları; genelde startup yükü.
3. **400 Bad Request positionRisk** — imza/timestamp veya çok sık signed call; tek motor + wallet 5s kuralına uy.
4. **Kopya kayıt tekrarı** — `ExchangeSync` import + ghost `SYNC-EXCHANGE` yeni kopya üretebilir; periyodik `purge_copy_trades_9005.py --dry-run`.
5. **`BN_FUT_ASYNC_HUB=0`** — async hub kapalı; pozisyon truth REST-only.

---

## 8. Cursor'da devam ederken

1. Workspace rule: `.cursor/rules/9005-data-preservation.mdc` — DB silme yasağı.
2. Yeni agent'e önce şunu söyle: *"HANDOFF_CURSOR.md oku; REST-only truth ve pozisyon motoru mimarisine uy."*
3. Değişiklik sonrası test:
   ```bash
   python3 -m py_compile binance_elite_pro.py
   ./scripts/elite_9005_process_ctl.sh restart
   curl -s http://127.0.0.1:9005/api/heartbeat
   ```
4. Panel hız: `/api/live` timeout olmamalı (~ms); closed backfill arka planda (`schedule_closed_backfill`).

---

## 9. Oturum geçmişi (kısa)

- Exit min net **$0.40**, paper tax **0**
- WS/UDS ile mark/uPnL overlay **kaldırıldı**
- Panel `/api/live` timeout → closed API backfill arka plana alındı
- Pozisyon motoru ayrıldı; cache timeout 4s → adaptif ~750ms–2.5s
- Kopya kapalı işlemler purge edildi (`purge_copy_trades_9005.py`)
- Monitor artık bot motorundan REST metrik okur (ayrı positionRisk poll yok)

---

## 10. Hızlı teşhis komutları

```bash
# Süreç
./scripts/elite_9005_process_ctl.sh status

# Heartbeat
curl -s http://127.0.0.1:9005/api/heartbeat | python3 -m json.tool

# Kapalı işlem sayısı
sqlite3 data/binance_elite_8300_9005_state.db "SELECT COUNT(*) FROM closed_trades;"

# Doğrulanmış vs kopya (dry-run)
python3 scripts/purge_copy_trades_9005.py --dry-run

# Son log
tail -50 logs/binance_elite_8300_9005.log
```

---

## 11. Taşınacak dosyalar checklist

- [ ] `predmarket-scanner/` tüm repo (git clone veya zip)
- [ ] `.env` (**API secret — ayrı güvenli kanal**)
- [ ] `data/binance_elite_8300_9005_state.db` (devam etmek istiyorsan)
- [ ] `data/deleted_archives/` (isteğe bağlı arşiv)
- [ ] `.venv` taşıma yerine yeni makinede yeniden kur

---

*Sorular için önce bu dosya + `DATA_PRESERVATION_9005.md` + `scenarios/binance_elite_8300_9005.env`.*
