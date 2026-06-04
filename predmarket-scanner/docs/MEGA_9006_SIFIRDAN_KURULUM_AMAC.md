# MEGA 9006 + BERSERK2 — Sıfırdan kurulum belgesi (amaç)

## Bu belge ne için?

Bu dosya, **başka bir bilgisayarda Cursor ile sıfırdan** MEGA (port **9006**) ve BERSERK2 (port **9005**) trading masasını yeniden kurarken kullanılacak **referansın amacını** tanımlar.

Tam mimari rapor (backend modülleri, API listesi, UI dosyaları, env grupları, kurulum adımları) sohbet içinde üretilmiştir; bu `.md` yalnızca **neden var** sorusuna cevap verir.

## Ne hedefleniyor?

- **+$1200 / kârlı rejim** dönemindeki davranışı yeniden üretmek: demo-fapi canlı MEGA, BERSERK2 tarama motoru, ~$5k cüzdan, ~$1000/slot stake, TP-only çıkış, net kapanış eşikleri (ör. tam TP ≥ $10, SPIKE ≥ $4).
- Mevcut repodaki yapıyı (`predmarket-scanner/`) başka ortamda **aynı parçaları** (FastAPI sunucu, `elite_trader/mega_*`, `panel/elite_v2/`, `scenarios/binance_elite_mega_9006_mainnet.env`) bilinçli şekilde kopyalamak veya modül modül yeniden yazmak.

## Kimin için?

- Projeyi **yeni PC / yeni repo** üzerinde sıfırdan kodlayacak geliştirici.
- “Hangi port ne iş yapıyor?”, “9006 neden berserk2 çalıştırmıyor ama tarama kullanıyor?” gibi kararları tek yerden hatırlamak isteyen ekip.

## Ne içermez?

- Günlük işletim komutları, API anahtarları, Telegram token’ları (bunlar `scenarios/.env.mega_9006` vb. git dışı dosyalarda kalır).
- Veri silme / reset prosedürü (ayrı: `DATA_PRESERVATION_9005.md`, reset script’leri).

## İlgili kaynaklar (repoda)

| Dosya | Rol |
|-------|-----|
| `scenarios/binance_elite_mega_9006_mainnet.env` | 9006 canlı parametreleri (~770 satır) |
| `docs/MEGA_SYSTEM_BOT_CHECKPOINT.md` | P0/P1/P2 sistem-bot checkpoint |
| `BERSERK2_MODE_PROFILE.md` | BERSERK2 mod davranışı |
| `deploy/gcp_9006_restore_chat_checkpoint.sh` | Kârlı checkpoint env + kod deploy (veri silmez) |

## Sonraki adım

Detaylı blueprint için sohbetteki **“MEGA 9006 + BERSERK2 — Sıfırdan Kurulum Raporu”** bölümünü kullanın veya ayrıca istenirse aynı içerik `docs/MEGA_9006_SIFIRDAN_KURULUM_BLUEPRINT.md` olarak dosyaya yazılabilir.
