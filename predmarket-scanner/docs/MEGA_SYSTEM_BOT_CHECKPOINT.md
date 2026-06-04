# MEGA sistem-bot yedek noktası (2026-06-03)

Bu dosya **mimari karar noktasıdır** — piyasa-tahmin botundan **sistem-merkezli** bota geçiş planı. Kod geri alınsa bile bu belgeye dönülür.

## Hedef

- Piyasa yorumu tek başına değil: **sinyal × yürütme × sistem sağlığı**
- Mikro bias, BTC rejim, liq, macro → **giriş filtresi + sonradan korelasyon**
- Ölçüm: phantom slippage, mark lag, motor/REST gecikmesi, reject_mix

## Üç döngü

| Döngü | Süre | Amaç |
|-------|------|------|
| **Hızlı** | 100–500 ms | Tick/hub mark, fill verify, SPIKE yürütme |
| **Orta** | dk–saat | Rejim, reject_mix, oturum PnL, REST budget |
| **Yavaş** | gün–hafta | Parametre önerisi (9006 learner), A/B profiller |

## Mevcut parçalar (kodda)

- `berserk2_btc_context` + `mega_direction_guard` — BTC/mikro bias
- `mega_market_regime` — quiet/active, reject_mix, slot kilidi
- `btc_liq_feed`, `btc_macro_feed`, `btc_flash_cascade` — panel önbellek
- `mega_close_audit.jsonl` — kapanış denemeleri
- `loss_learner` — yalnızca **9005** (MEGA henüz yok)

## Yol haritası

- **P0** ✅ (2026-06-03) — `elite_trader/mega_system_context.py` + `entry_context` / `exit_context` + audit `system_context` (işlem mantığı değiştirmez)
- **P1** ✅ — `mega_system_report.py` + `scripts/mega_system_report.py` + günlük Telegram/JSON
- **P2** ✅ kod hazır, **şimdilik devre dışı** (`MEGA_SYSTEM_SCORE_GATE=0`) — açılışları etkilemez
- **Zarar kesimi (lab)** — `MEGA_UNDERWATER_CUT` + SL yolu kodda; **9006 canlıda kapalı** (`MEGA_UNDERWATER_CUT=0`, `MEGA_DISABLE_SL_EXIT=1`); test: `scenarios/mega_loss_cut_lab.env` + 9007
- **P3** — Env A/B testleri

## P0 gerçekçi beklenti

**P0 tek başına pozisyon yakalama, açma/kapatma veya PnL doğruluğunu değiştirmez.**  
Yalnızca her işlemde “o an sistem neydi?” kaydı ekler; P1+ ile optimizasyon mümkün olur.

| Alan | P0 sonrası | P1+ gerekir |
|------|------------|-------------|
| Kaç sinyal / kaç açılış | Aynı | `system_score` kapısı |
| Giriş zamanlaması | Aynı | Hub/REST SLA alarmı |
| Kapanış doğruluğu / phantom | Aynı | blend/demo_fast sıkılaştırma |
| Win rate | Ölçülür, artmaz | Öğrenilmiş env önerileri |
| Panel hızı | Aynı (~ms snapshot okuma) | — |

Deploy: `MEGA_SYSTEM_CONTEXT_ENABLED=1` (varsayılan). Kapatmak için `=0`.

## P1 gerçekçi beklenti

**P1 de P0 gibi canlı işlem mantığını değiştirmez** — gün sonu / periyodik rapor + Telegram.

## İlgili env (9006 — bu sohbet checkpoint)

- `MEGA_SYSTEM_CONTEXT_ENABLED=1` / `MEGA_SYSTEM_CONTEXT_AUDIT=1` — P0
- `MEGA_SYSTEM_REPORT_*` — P1 (86400s)
- `MEGA_SYSTEM_SCORE_GATE=0` — **kapı kapalı**
- `MEGA_SYSTEM_SCORE_MONITOR=1` — skor log (blok yok)
- `MEGA_SYSTEM_SCORE_FLASH_BYPASS=1`
- `MEGA_UNDERWATER_CUT=0` — canlıda su-altı kesimi kapalı
- `MEGA_DISABLE_SL_EXIT=1` — SL çıkış kapalı (lab’de test)
- `MEGA_MARK_UNREAL_BLEND=1` — panel/hub uPnL hizası
- `MEGA_BOOT_OBSERVE=0` — 24h loop boot gözlemi geri alındı
- `MEGA_PHANTOM_PANEL_HIDE=1`

## Dosyalar

- `elite_trader/mega_system_context.py` — P0
- `elite_trader/mega_system_report.py` — P1
- `elite_trader/mega_system_score.py` — P2 (gate=0)
- `scenarios/mega_loss_cut_lab.env` — underwater/SL lab (9007)
- `data/mega_9006/mega_live_closed.json` — `entry_context`, `exit_context`
- `data/mega_9006/mega_close_audit.jsonl` — `system_context`
- `deploy/gcp_9006_restore_chat_checkpoint.sh` — bu checkpoint’e GCP deploy

### Retro backfill

```bash
python3 scripts/backfill_mega_system_context.py --instance 9006 --include-archives \
  --consolidate-out mega_live_closed_history.json --audit
```
