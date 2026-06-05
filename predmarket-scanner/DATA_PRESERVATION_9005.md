# 9005 — Veri koruma politikası

## Kurallar (agent / geliştirme)

1. **Geçmiş veriyi siz söylemeden silmeyin:** `binance_elite_8300_9005_state.db`, `elite_9005_trade_lessons.json`, `elite_9005_learning_registry.json`, `elite_9005_proposals.json`, `elite_sl_emergency_registry.json`, postmortem dosyaları.
2. **Reset script varsayılanı:** `./scripts/reset_binance_elite_9005.sh` yalnızca botu yeniden başlatır; DB korunur.
3. **Silme yalnızca açık emirle:** Kullanıcı "sil", "sıfırla", "wipe" dediğinde ve **neden** belirtildiğinde.

## Kullanıcı komutları

| Amaç | Komut |
|------|--------|
| Bot restart, veri kalır | `./scripts/reset_binance_elite_9005.sh` |
| Veri sil + arşiv | `python3 scripts/delete_9005_history.py -r "deney notu"` |
| Son silinen arşivler | `python3 scripts/list_9005_deleted_archives.py` |
| Reset + veri sil | `./scripts/reset_binance_elite_9005.sh --wipe-data --reason "..."` |

## Arşiv yapısı

- Manifest: `data/deleted_archives/manifest.json`
- Her silme: `data/deleted_archives/9005_YYYYMMDDTHHMMSSZ_neden/`
  - `meta.json` — tarih, neden, tetikleyen, dosya listesi, kapanan işlem sayısı
  - Kopyalanan dosyalar (geri yüklemek için)

## Geri yükleme

```bash
# Örnek: son arşivden state DB geri al
cp data/deleted_archives/9005_*/binance_elite_8300_9005_state.db data/
./run_binance_elite_8300_9005.sh
```
