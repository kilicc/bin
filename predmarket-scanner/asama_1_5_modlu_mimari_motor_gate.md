# AŞAMA 1 — 5 Modlu Ana Mimari ve Binance Futures Motor Gate

## Amaç

Mevcut projeyi bozmadan 5 modlu paralel evren trading mimarisini netleştir ve güvenli hale getir.

Bu aşamada **hiçbir strateji ayarı değiştirilmemelidir**.

Bu aşamada yapılacak iş sadece şudur:

- 5 modun ayrı çalışmasını garanti etmek
- Her modun kendi verisini, filtresini, stratejisini, işlemini ve öğrenmesini ayrı tutmak
- Binance Futures canlı işlem motorunu sadece seçili moda bağlamak
- Seçili olmayan modları paper/simülasyon modunda çalıştırmak
- Paper modların yanlışlıkla gerçek Binance Futures emri göndermesini engellemek
- Live işlem açan modun, Binance cüzdanı ve pozisyon verileriyle sadece kendi kayıtlarını eşleştirmesini sağlamak

---

## Mevcut Modlar

Sistemde 5 mod vardır:

1. ★ Evrim
2. ◇ Berserk
3. ◇ Hunter
4. ◇ Chop
5. ◇ Sentinel

Bu modların tamamı aynı canlı piyasa havuzunu izlemelidir.

Ancak her mod:

- kendi stratejisiyle çalışmalıdır
- kendi filtrelerini kullanmalıdır
- kendi kararlarını üretmelidir
- kendi DB/tablo alanına yazmalıdır
- kendi işlemlerini ayrı takip etmelidir
- kendi performansından öğrenmelidir

---

## Motor Kavramı

Bu projede **motor**, strateji değildir.

Motor, yalnızca hangi modun gerçek Binance Futures hesabıyla eşleşeceğini belirleyen canlı işlem kapısıdır.

Motor seçimi şu anlama gelir:

> Seçilen mod, kendi mevcut stratejisini ve filtrelerini değiştirmeden Binance Futures hesabıyla eşleşir ve canlı işlem açabilir.

Motor seçimi şu anlama gelmez:

- Modun stratejisi değişmez
- Modun filtreleri değişmez
- Modun risk ayarları değişmez
- Modun TP/SL mantığı değişmez
- Diğer modların davranışı değişmez

---

## Temel Çalışma Mantığı

Örnek 1:

```text
active_futures_mode = "EVRIM"
```

Bu durumda:

- ★ Evrim gerçek Binance Futures hesabıyla eşleşir
- ★ Evrim kendi filtrelerine göre canlı işlem açabilir
- ★ Evrim Binance cüzdan, pozisyon, fee, funding ve işlem verilerini kendi live kayıtlarıyla eşleştirir
- ◇ Berserk paper modda kalır
- ◇ Hunter paper modda kalır
- ◇ Chop paper modda kalır
- ◇ Sentinel paper modda kalır

Örnek 2:

```text
active_futures_mode = "BERSERK"
```

Bu durumda:

- ◇ Berserk gerçek Binance Futures hesabıyla eşleşir
- ◇ Berserk kendi filtrelerine göre canlı işlem açabilir
- ◇ Berserk Binance cüzdan, pozisyon, fee, funding ve işlem verilerini kendi live kayıtlarıyla eşleştirir
- ★ Evrim paper modda kalır
- ◇ Hunter paper modda kalır
- ◇ Chop paper modda kalır
- ◇ Sentinel paper modda kalır

Bu mantık tüm modlar için aynıdır.

---

## Değiştirilmeyecek Şeyler

Bu aşamada aşağıdaki şeyler değiştirilmemelidir:

- Mevcut mod adları
- Mevcut panel yapısı
- Mevcut strateji ayarları
- Mevcut filtre değerleri
- Mevcut TP/SL ayarları
- Mevcut risk ayarları
- Mevcut Binance API bağlantı mantığı
- Mevcut piyasa veri toplama mantığı

Sadece aşağıdaki alanlar sağlamlaştırılmalıdır:

- mode gate
- live/paper routing
- veri izolasyonu
- DB ayrımı
- emir güvenliği
- Binance eşleştirme mantığı
- paper işlem simülasyonu
- live işlem kayıt ayrımı

---

## Kesin Kurallar

1. Her mod kendi strateji ayarlarını korur.
2. Binance Futures motoruna seçilen modun ayarları değişmez.
3. Motor seçimi sadece o modun gerçek Binance Futures hesabıyla eşleşmesini sağlar.
4. Motor modunda olmayan modlar gerçek emir göndermez.
5. Motor modunda olmayan modlar aynı canlı piyasa verisini kullanarak paper işlem simülasyonu yapar.
6. Paper modlar gerçek işlem açıyormuş gibi karar üretir.
7. Paper modlar giriş, çıkış, TP, SL, fee, spread, slippage, funding ve PnL simülasyonu üretir.
8. Paper modların verisi kendi ayrı DB/tablo alanına yazılır.
9. Live modun verisi kendi ayrı live işlem kayıtlarına yazılır.
10. Her modun verisi karışmamalıdır.
11. Her mod kendi geçmişinden öğrenmelidir.
12. Sadece ★ Evrim modu diğer modların özet sonuçlarına erişebilir.
13. ◇ Berserk, ◇ Hunter, ◇ Chop ve ◇ Sentinel birbirlerinin verisine erişemez.
14. Hiçbir paper mod yanlışlıkla Binance Futures gerçek emir fonksiyonunu çağıramaz.
15. active_futures_mode boş/null ise tüm modlar paper çalışmalıdır.

---

## Emir Yönlendirme Katmanı

Her order intent için aşağıdaki alanlar zorunlu olmalıdır:

```text
mode_id
mode_name
active_futures_mode
is_live_candidate
is_paper
strategy_source
symbol
side
entry_reason
score_total
expected_net_pnl
order_route
```

Order route mantığı şu şekilde olmalıdır:

```python
if mode_id == active_futures_mode:
    route = "BINANCE_FUTURES_LIVE_ENGINE"
else:
    route = "PAPER_ENGINE"
```

Ancak route live engine olarak belirlense bile emir doğrudan gönderilmemelidir.

Önce aşağıdaki kontrollerden geçmelidir:

```text
Binance API bağlantısı sağlıklı mı?
Symbol trade edilebilir mi?
Bakiye yeterli mi?
Pozisyon limiti aşılmıyor mu?
Modun kendi risk filtresi izin veriyor mu?
Expected net PnL pozitif mi?
Spread/slippage kabul edilebilir mi?
Günlük risk limiti aşılmamış mı?
```

Bu kontrollerden biri başarısızsa gerçek emir gönderilmez.

Sebep loglanmalıdır.

---

## Paper Engine Davranışı

Motor modunda olmayan tüm modlar paper engine’e yönlendirilmelidir.

Paper engine:

- gerçek Binance order endpoint çağırmamalıdır
- aynı canlı piyasa fiyatlarını kullanmalıdır
- sanal fill hesaplamalıdır
- fee simülasyonu yapmalıdır
- spread simülasyonu yapmalıdır
- slippage simülasyonu yapmalıdır
- funding simülasyonu yapmalıdır
- TP/SL sonucunu hesaplamalıdır
- PnL sonucunu üretmelidir
- sonucu ilgili modun kendi paper kayıtlarına yazmalıdır

Paper engine’de oluşan hiçbir işlem Binance’e gönderilmemelidir.

---

## Live Binance Futures Engine Davranışı

Sadece active_futures_mode olan mod live engine’e ulaşabilir.

Live engine:

- sadece seçili modun order intent’ini kabul eder
- seçili modun kendi filtrelerine göre işlem açar
- Binance Futures hesabında gerçek işlem açar
- Binance’den gelen gerçek işlem, fee, funding, realized PnL, commission ve pozisyon verilerini alır
- bu verileri sadece seçili modun live kayıtlarıyla eşleştirir
- diğer modların kayıtlarına yazmaz

Örnek:

```text
active_futures_mode = "HUNTER"
```

Bu durumda Binance’den alınan canlı işlem verileri sadece Hunter live kayıtlarına yazılmalıdır.

---

## DB / Veri Ayrımı İlkesi

Her modun verisi ayrı tutulmalıdır.

Uygun olan mevcut mimariye göre iki seçenekten biri uygulanabilir.

### Seçenek A — Ayrı DB

```text
db_evrim
db_berserk
db_hunter
db_chop
db_sentinel
```

### Seçenek B — Aynı DB, ayrı tablo grupları

```text
evrim_decisions
evrim_paper_trades
evrim_live_trades
evrim_metrics
evrim_learning

berserk_decisions
berserk_paper_trades
berserk_live_trades
berserk_metrics
berserk_learning

hunter_decisions
hunter_paper_trades
hunter_live_trades
hunter_metrics
hunter_learning

chop_decisions
chop_paper_trades
chop_live_trades
chop_metrics
chop_learning

sentinel_decisions
sentinel_paper_trades
sentinel_live_trades
sentinel_metrics
sentinel_learning
```

Mevcut projeye en az zarar veren seçenek tercih edilmelidir.

---

## Evrim Modu Veri Erişim Kuralı

★ Evrim modu özel bir meta-learning modudur.

Evrim şunları okuyabilir:

```text
berserk_metrics
hunter_metrics
chop_metrics
sentinel_metrics
berserk_paper_summary
hunter_paper_summary
chop_paper_summary
sentinel_paper_summary
```

Evrim şunları yapamaz:

- Diğer modların config dosyalarını otomatik değiştiremez
- Diğer modların canlı/paper kararlarını manipüle edemez
- Diğer modların trade kayıtlarını silemez
- Diğer modların strateji ayarlarını doğrudan değiştiremez

Evrim sadece kendi karar motorunu geliştirmek için diğer modların özet performans verilerini okuyabilir.

---

## Zorunlu Log Alanları

Her modun her kararında şu alanlar loglanmalıdır:

```text
timestamp
mode_id
mode_name
active_futures_mode
symbol
side
market_regime
score_total
score_breakdown
entry_reason
reject_reason
veto_reason
risk_level
expected_net_pnl
spread
slippage_estimate
expected_fee
expected_funding
order_route
is_paper
order_sent
exchange_accepted
entry_price
exit_price
gross_pnl
fee
funding
net_pnl
hold_time
result
learning_tag
```

---

## Unit Test / Güvenlik Testleri

Aşağıdaki testler eklenmelidir.

### Test 1

```text
active_futures_mode = "EVRIM"
Berserk order intent üretirse route PAPER_ENGINE olmalıdır.
```

### Test 2

```text
active_futures_mode = "HUNTER"
Hunter order intent üretirse route BINANCE_FUTURES_LIVE_ENGINE olabilir.
Ancak risk kontrollerinden geçmeden gerçek emir gönderilmemelidir.
```

### Test 3

```text
active_futures_mode = null
Tüm modlar PAPER_ENGINE'e yönlenmelidir.
```

### Test 4

```text
Paper modların hiçbirinde Binance gerçek order fonksiyonu çağrılmamalıdır.
```

### Test 5

```text
Live mod değiştirildiğinde strateji ayarları değişmemelidir.
Sadece live routing değişmelidir.
```

### Test 6

```text
active_futures_mode = "SENTINEL"
Evrim, Berserk, Hunter ve Chop gerçek Binance order endpoint çağırmamalıdır.
```

### Test 7

```text
Binance’den gelen gerçek işlem sonucu sadece active_futures_mode olan modun live kayıtlarına yazılmalıdır.
```

---

## Dashboard’da Gösterilecekler

Dashboard’da açıkça göster:

```text
Aktif Binance Futures modu
Live işlem açabilen mod
Paper çalışan modlar
Her modun ayrı trade sayısı
Her modun ayrı paper PnL’i
Her modun ayrı live PnL’i
Her modun ayrı Fee/Gross oranı
Her modun ayrı red sebepleri
Her modun ayrı öğrenme kayıt sayısı
Her modun order route dağılımı
Son 20 order intent route sonucu
```

Örnek gösterim:

```text
LIVE MODE: EVRIM

PAPER MODES:
- BERSERK
- HUNTER
- CHOP
- SENTINEL
```

---

## Bu Aşamada Yapılmayacaklar

Bu dosyada aşağıdakiler yapılmayacak:

- yeni strateji ekleme
- TP/SL ayarı değiştirme
- risk ayarı değiştirme
- indikatör ağırlığı değiştirme
- mod karakteri değiştirme
- agresiflik artırma
- otomatik learning davranışı değiştirme

Bu aşama sadece güvenli mimari ayrım ve motor yönlendirme aşamasıdır.

---

## Uygulama Talimatı

Cursor bu dosyayı uygularken şu sırayla ilerlemelidir:

1. Mevcut mod yapısını incele.
2. Mevcut active_futures_mode veya benzeri seçici alanı bul.
3. Binance Futures canlı emir fonksiyonlarını tespit et.
4. Paper/simülasyon emir fonksiyonlarını tespit et.
5. Ortak order routing katmanı oluştur.
6. Route kararını mode_id ve active_futures_mode’a göre ver.
7. Live route öncesi güvenlik kontrollerini ekle.
8. Paper route için gerçek Binance endpoint çağrısını engelle.
9. Her route kararını logla.
10. DB/table ayrımını mevcut mimariye en az zarar verecek şekilde uygula.
11. Unit testleri ekle.
12. Dashboard’a canlı/paper mod ayrımını ekle.
13. Mevcut strateji ayarlarını değiştirme.
14. Mevcut filtre değerlerini değiştirme.
15. Mevcut mod isimlerini değiştirme.

---

## Başarı Kriterleri

Bu aşama başarılı sayılırsa:

- Sadece seçili mod gerçek Binance Futures emri gönderebilir.
- Diğer 4 mod paper modda kalır.
- Paper modlar canlı piyasayı izleyip veri üretir.
- Her modun kayıtları ayrı tutulur.
- Evrim diğer modların özet verisini okuyabilir.
- Diğer modlar birbirini okuyamaz.
- Live mod değişince strateji değişmez, sadece canlı motor eşleşmesi değişir.
- Paper modların Binance gerçek order endpoint çağırma riski ortadan kalkar.
- Dashboard’da hangi mod live, hangileri paper açıkça görünür.

---

## Cursor İçin Son Not

Bu aşamada hedef “trade canavarı”nı daha agresif yapmak değildir.

Bu aşamada hedef, trade canavarının iskeletini güvenli kurmaktır.

Strateji, agresiflik, indikatör, TP/SL ve öğrenme geliştirmeleri sonraki aşamalarda ayrı MD dosyalarıyla uygulanacaktır.
