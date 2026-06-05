# Elite 9005 — Loss Learner (uygulama paketi)

Plan modunda kod yazılamadı; Agent moduna geçince bu dosyadaki adımlar uygulanacak.

## Diğer modül: Post-mortem / MFE analizi (ayrı)

Bu modül **geçmişe dönük otopsi** yapar; Loss Learner ise **çalışırken öğrenir**.

| | Loss Learner | Post-mortem (MFE) |
|--|--------------|-------------------|
| Ne zaman | Her yeni zararlı kapanış + 15 dk | Tek sefer veya talep |
| Veri | Kapanış kaydı + örüntü defteri | Binance 1m klines entry→exit |
| Soru | "Tekrar eden hata ne?" | "Kâr gördü mü, TP'ye kaç kaldı?" |
| Çıktı | Öneri kuyruğu (siz onaylarsınız) | JSON rapor + sembol hikâyesi |

## Loss Learner — uygulama checklist

- [x] `elite_trader/loss_learner.py` (kuyruk, worker, registry, proposals)
- [x] `binance_elite_pro.py`: import, `close_position` → `enqueue_loss_analysis`
- [x] `lifespan`: `start_background()`
- [x] `get_snapshot`: `loss_learner` alanı
- [x] `elite_pro_template.html`: Öneriler kartı
- [x] `POST /api/learner/proposals/{id}/approve|reject`
- [x] `scenarios/binance_elite_8300_9005.env`: `ELITE_LEARNER_ENABLED=1`, `ELITE_LEARNER_AUTO_APPLY=0`

## Güvenlik

`ELITE_LEARNER_AUTO_APPLY=0` zorunlu — env değişmez; yalnızca log `📋 ÖNERİ` ve panel.
