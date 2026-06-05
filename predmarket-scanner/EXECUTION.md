# Operational Playbook — Bot Niye Para Kaybeder

İkinci tweet (Polymarket bot fix guide) operasyonel sorunlara odaklanıyor:
strateji ikinci derecede; **execution ve state management** birinci. Bu doküman
o noktaları somut kod modüllerine bağlar.

## 1. Latency bütçesi

| Aşama | Hedef | Bu repodaki yeri |
|---|---|---|
| Sinyal → order build | <0.5ms (hot path) | `core/timing.py` instrumentation |
| Local → CLOB P50 RT | 6-8ms | infra seçimi (Ireland/Montreal, AWS eu-west-1 / ca-central-1) |
| Imza/header oluşturma | 0ms at fire | `execution/prebuilt.py` — startup'ta hazırla |
| Order status reconcile | her 30s | `core/reconciler.py` |

**Bu repo paper-mode** olduğu için latency optimizasyonu örnek amaçlı yer alıyor;
gerçek CLOB entegrasyonunda hot-path Python yerine Rust/Go düşün.

## 2. Pre-staged execution artifacts

Hot path'te yapma:
- JSON serializasyon
- HMAC hesaplama (CLOB API request signature)
- DNS lookup / TCP open
- Yeni httpx client kurma

Bunların hepsi **startup'ta** veya en kötü **sinyal tetiklenmeden önce** hazır
olmalı. Order objeleri "clone-and-fire" template'i olarak tutulur; fiyat ve
size son anda yamanır.

## 3. Order types — likidite öldüğünde

Thin book'ta saf FAK (Fill-or-Kill all) çoğunlukla başarısız. Üç alternatif:

1. **GTC mid+1tick:** Spread'in ortasına bir tick fazla limit ver, dur. Doldurma şansı düşer ama maliyet kontrollü.
2. **Naked-sell opposite side:** YES almak istiyorsan, NO'yu satabilirsin (synthetic YES). Likidite YES kitabında bitse bile NO'da olabilir.
3. **Pre-split + GTC rest:** Pozisyonu parçalara böl; bir kısmı market, geri kalanı karşı tarafta GTC olarak dinlenir. Trade kendi kendine doldurabilir.

`execution/order_types.py` bu üç stratejinin paper-mode simülasyonunu içerir
(gerçek CLOB API call'ı yapılmaz).

## 4. Silent fill bug — reconciliation

**Asla** sadece API exception'a güvenme. Timeout = belirsizlik, fail değil.

Kural: her timeout sonrası `GET /order/{id}` ile durumu doğrula; her 30 saniyede
bir full reconciliation (tüm local pozisyon ↔ exchange state) çalıştır.

`core/reconciler.py` periyodik reconcile pattern'ini gösterir.

## 5. Sinyal sadeliği

Tweet'in tavsiyesi (deneyimle uyumlu): üst üste indikatör yığma. Uzun vadede
hayatta kalan baseline'lar:

| Sinyal | Mantık | Bu repodaki yer |
|---|---|---|
| CLOB momentum | son N tick'te order flow yönü | `core/signals.py: clob_momentum` |
| Spot distance from strike | underlying spot ile market strike farkı | `core/signals.py: spot_distance` |
| Time-weighted signal | event yaklaştıkça volatilite/sapma ağırlığı | `core/signals.py: time_weighted` |
| Day-of-week edge | haftanın gününe göre conditional edge | `core/signals.py: day_of_week_bias` |

Bu sinyalleri `ProbabilityEstimator` içine sok — ya direkt birini kullan, ya da
hepsinin ağırlıklı ortalamasını al.

## 6. Window seçimi

5-min BTC bot'u brütal: gürültü > sinyal. 15-min aynı mantıkla print eder. Daha
geniş pencere = daha az microstructure noise.

## 7. Position sizing

- Tek seferde all-in YOK.
- Net kaybedenlerde agresif stop (örn. -25% açık zararda kapat).
- Açık kazananlarda DCA (mean-reversion riski varsa kademeli ekle).
- Capital preservation > mükemmel giriş.

Kelly + fractional çarpan (`config.py: kelly_fraction = 0.25`) zaten bu disiplini
matematik olarak uyguluyor. Üzerine **max_position_usd** sertçe sınırla.
