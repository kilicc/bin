# 🎯 GERÇEK BINANCE FUTURES TRADER VERİ TOPLAMA SİSTEMİ

## 📋 Özet

Bu sistem, **gerçek Binance Futures trader**larının verilerini toplar ve backtest için hazırlar.

### ✨ Özellikler

- ✅ **Tamamen Ücretsiz Seçenek** (Web scraping + Binance Public API)
- ✅ **Premium Seçenek** (Apify API - daha güvenilir)
- ✅ **Trader Profilleri** (ROI, PNL, win rate, followers)
- ✅ **Mevcut Pozisyonlar** (real-time)
- ✅ **Performans Geçmişi** (ROI timeline)
- ✅ **Backtest Uyumlu** Format

---

## 🚀 Hızlı Başlangıç (3 Adım)

### Yöntem 1: Ücretsiz (Önerilen)

```bash
# 1. Playwright'i yükle
pip install playwright
playwright install chromium

# 2. Top 50 trader'ı topla
python scripts/collect_free_traders.py --max-traders 50

# 3. Çıktıyı kontrol et
cat data/real_traders/free_traders_full.json | jq '.[0:3]'
```

**Çıktı:**
```
data/real_traders/
├── free_traders_full.json       # Ana veri (profil + metadata)
├── positions_<UID>.json         # Her trader için pozisyonlar
└── history_<UID>.json           # Her trader için performans geçmişi
```

### Yöntem 2: Apify (Ücretli ama daha güvenilir)

```bash
# 1. Apify hesabı aç ve API token al
# https://console.apify.com/sign-up

# 2. Token'ı ayarla
export APIFY_API_TOKEN="apify_api_xxxxxxxxxxxxx"

# 3. Apify client'ı yükle
pip install apify-client

# 4. Veri topla
python scripts/collect_real_traders.py --max-traders 100
```

**Çıktı:**
```
data/real_traders/
├── profiles.json                          # Trader profilleri
├── positions_history/<UID>/               # Pozisyon geçmişi
│   └── positions_20260518_180000.json
└── metadata.json                          # İstatistikler
```

---

## 📊 Veri Kaynakları

| Kaynak | Ücret | Veri Kalitesi | API Key Gerekli? |
|--------|-------|---------------|------------------|
| **Web Scraping** | Ücretsiz | İyi | Hayır ✅ |
| **Binance BAPI** | Ücretsiz | İyi | Hayır ✅ |
| **Apify Leaderboard** | $19.99/ay | Mükemmel | Evet |
| **Apify Positions** | $0.0018/call | Mükemmel | Evet |

**Detaylı bilgi:** [docs/REAL_TRADER_DATA_SOURCES.md](docs/REAL_TRADER_DATA_SOURCES.md)

---

## 📁 Toplanan Veri Formatı

### Trader Profili
```json
{
  "uid": "3AFFCB67ED4F1D1D8437BA17F4E8E5ED",
  "nickname": "StellarMom",
  "source": "web_scrape",
  "roi": 154.82,
  "pnl": 22418.98,
  "win_rate": 0.4551,
  "rank": 61,
  "follower_count": 396540,
  "days_active": 2240,
  "max_drawdown": 0.7009,
  "position_shared": true,
  "data_quality_score": 83.3
}
```

### Trader Pozisyonu
```json
{
  "trader_uid": "3AFFCB67ED4F1D1D8437BA17F4E8E5ED",
  "symbol": "BTCUSDT",
  "side": "LONG",
  "entry_price": 95000.0,
  "current_price": 96500.0,
  "amount": 1.0,
  "leverage": 10,
  "pnl": 1500.0,
  "roi": 0.15,
  "timestamp": 1747155600000
}
```

---

## 🔄 Backtest İçin Geçmiş Pozisyon Verisi

### ⚠️ Önemli Not

Binance'in public API'si **sadece mevcut pozisyonları** verir.  
**Geçmiş (closed) pozisyonlar** için 2 yöntem var:

#### 1️⃣ Forward Testing (Önerilen ⭐)

Sistemi şimdi başlat, pozisyonları kaydet, zamanla gerçek geçmiş oluştur:

```bash
# Copy trader monitor'ü başlat
python scripts/run_copy_trader.py monitor

# 3-7 gün boyunca çalıştır
# Her pozisyon değişikliği otomatik kaydedilir:
# data/copy_trading/position_snapshots/{uid}_{timestamp}.json
```

**장점:**
- Gerçek pozisyon verisi
- Açılış/kapanış zamanları doğru
- Backtest için en güvenilir

#### 2️⃣ Performance History Simülasyonu

Binance API'nin verdiği günlük ROI/PNL geçmişinden pozisyon simüle et:

```python
# ROI timeline'dan pozisyon tahmin et
history = await api.get_trader_history(uid)

for day in history["performanceRetList"]:
    daily_roi = day["roi"]  # Günlük ROI
    daily_pnl = day["pnl"]  # Günlük PNL
    
    # Pozisyon tahmini (basit yöntem)
    if daily_roi > 2.0:  # %2+ ROI = büyük kazanç
        # LONG pozisyon kapalı olabilir
        simulated_position = {
            "date": day["date"],
            "estimated_action": "CLOSE_LONG",
            "estimated_pnl": daily_pnl
        }
```

**Not:** Bu yöntem **tahmin** bazlıdır, gerçek pozisyon verisi değildir.

---

## 🎯 Backtest Hazırlığı

### Adım 1: Gerçek Trader Verisi Topla

```bash
# Top 100 trader (profil + pozisyon + geçmiş)
python scripts/collect_free_traders.py --max-traders 100
```

### Adım 2: Kaliteli Traderları Filtrele

```python
import json

with open("data/real_traders/free_traders_full.json") as f:
    traders = json.load(f)

# Backtest için iyi traderlar
good_traders = [
    t for t in traders
    if t.get("data_quality_score", 0) >= 60
    and t.get("position_shared", False)
    and t.get("win_rate", 0) >= 0.50
    and t.get("roi", 0) >= 20.0
]

print(f"✓ {len(good_traders)} good traders found for backtest")
```

### Adım 3: Forward Testing Başlat

```bash
# İyi traderları tracked_traders.json'a ekle
python scripts/add_trader.py import --file good_traders.json

# Monitor'ü başlat (pozisyonları kaydet)
python scripts/run_copy_trader.py monitor

# 7 gün sonra gerçek backtest verisi hazır olur
```

### Adım 4: Backtest Çalıştır

```bash
# 7 gün sonra
python scripts/run_copy_trader.py backtest --trader-uid <UID> --days 7
```

---

## 📊 Veri Kalitesi Skoru

Sistem her trader için otomatik skor hesaplar (0-100):

```python
quality_score = (
    has_roi * 20 +           # ROI verisi var mı?
    has_pnl * 20 +           # PNL verisi var mı?
    has_rank * 10 +          # Rank bilgisi var mı?
    has_followers * 10 +     # Follower sayısı var mı?
    position_shared * 30 +   # Pozisyon paylaşıyor mu? (en önemli)
    has_twitter * 10         # Twitter profili var mı?
)
```

**Backtest için önerilen minimum skor:** 60+

---

## 🛠️ Kurulum

### Gereksinimler

```bash
# Python 3.8+
python --version

# Bağımlılıklar
pip install playwright httpx rich

# Playwright browser
playwright install chromium

# (Opsiyonel) Apify için
pip install apify-client
```

### Tam Kurulum

```bash
cd predmarket-scanner

# Tüm gereksinimleri yükle
pip install -r requirements.txt

# Playwright browser
playwright install chromium

# Test et
python scripts/collect_free_traders.py --max-traders 5
```

---

## 📚 Komutlar

### Ücretsiz Veri Toplama

```bash
# Tam veri seti (profil + pozisyon + geçmiş)
python scripts/collect_free_traders.py --max-traders 100

# Sadece profiller (en hızlı)
python scripts/collect_free_traders.py --max-traders 100 --no-positions --no-history

# Sadece profil + pozisyon (geçmiş yok)
python scripts/collect_free_traders.py --max-traders 50 --no-history

# Özel dizine kaydet
python scripts/collect_free_traders.py --max-traders 50 --output-dir custom_data/
```

### Apify ile Veri Toplama

```bash
# API token ayarla
export APIFY_API_TOKEN="apify_api_xxxxxxxxxxxxx"

# Tam veri seti
python scripts/collect_real_traders.py --max-traders 100

# Sadece profiller (pozisyon yok)
python scripts/collect_real_traders.py --max-traders 100 --no-positions

# Özel dizine kaydet
python scripts/collect_real_traders.py --max-traders 100 --data-dir apify_data/
```

### Veriyi Görüntüleme

```bash
# Toplanan trader sayısı
cat data/real_traders/free_traders_full.json | jq 'length'

# İlk 3 trader
cat data/real_traders/free_traders_full.json | jq '.[0:3]'

# Top 10 ROI
cat data/real_traders/free_traders_full.json | jq 'sort_by(.roi) | reverse | .[0:10] | .[] | {nickname, roi, win_rate}'

# Pozisyon paylaşanlar
cat data/real_traders/free_traders_full.json | jq '[.[] | select(.position_shared == true)] | length'

# Kaliteli traderlar (score >= 60)
cat data/real_traders/free_traders_full.json | jq '[.[] | select(.data_quality_score >= 60)] | length'
```

---

## ⚡ Gerçek Trader Örnekleri

Bu UID'ler gerçek ve public, hemen test edebilirsin:

```python
REAL_TRADERS = [
    "3AFFCB67ED4F1D1D8437BA17F4E8E5ED",  # StellarMom - ROI: 154%
    "0C2123F5688F316245836C60A66F8240",  # High ROI trader
    # ... daha fazlası için veri toplama scriptini çalıştır
]
```

Test için:

```bash
# Bu traderları ekle
python scripts/add_trader.py add 3AFFCB67ED4F1D1D8437BA17F4E8E5ED

# Pozisyonlarını kontrol et
python scripts/run_copy_trader.py status
```

---

## 🔗 İlgili Dosyalar

| Dosya | Açıklama |
|-------|----------|
| `binance_futures_trader/real_trader_collector.py` | Apify ile veri toplama (ücretli) |
| `binance_futures_trader/free_trader_sources.py` | Ücretsiz kaynaklardan veri toplama |
| `scripts/collect_real_traders.py` | Apify CLI |
| `scripts/collect_free_traders.py` | Ücretsiz veri toplama CLI |
| `docs/REAL_TRADER_DATA_SOURCES.md` | Tüm kaynakların detaylı açıklaması |

---

## ❓ Sık Sorulan Sorular

**S: Ücretsiz yöntem yeterli mi?**  
C: Evet! Web scraping + Binance BAPI ile güvenilir veri topla. Apify daha az hata verir ama zorunlu değil.

**S: Geçmiş pozisyon verisi alabilir miyim?**  
C: Binance API'si sadece mevcut pozisyonları verir. Geçmiş için forward testing yapmalısın (monitor 7 gün çalıştır).

**S: Kaç trader toplamalıyım?**  
C: Top 50-100 yeterli. Daha fazla trader = daha yavaş + rate limiting riski.

**S: Web scraping yasal mı?**  
C: Binance leaderboard public bir sayfa. Makul rate limiting (örn. 1 sayfa/saniye) ile soruntu olmaz.

**S: Apify ne kadar?**  
C: Leaderboard scraper: $19.99/ay + kullanım. Position tracker: $0.0018/çağrı.

**S: Veri ne kadar güncel?**  
C: Binance leaderboard ~1 saatte bir güncellenir. Pozisyonlar ~5 saniyede bir (monitor polling rate).

---

## 📝 Önemli Notlar

1. **Forward Testing Gerekli**  
   Gerçek backtest için sistemi en az 7 gün çalıştırmalısın. İlk gün sadece profil verisi topla, sonraki günler pozisyon geçmişi biriktir.

2. **Rate Limiting**  
   - Web scraping: Max 1 sayfa/saniye
   - Binance BAPI: Max ~100 req/dakika
   - Apify: Sınırsız (ücretli)

3. **Veri Kalitesi**  
   Backtest için minimum `data_quality_score: 60` ve `position_shared: true` olan traderları kullan.

4. **Yasal Uyarı**  
   Bu sistem eğitim ve araştırma amaçlıdır. Gerçek trading yaparken kendi riski altında hareket et.

---

## 🎯 Sonraki Adımlar

```bash
# 1. Gerçek trader verisi topla
python scripts/collect_free_traders.py --max-traders 100

# 2. Kaliteli traderları filtrele (Python)
# (Yukarıdaki "Backtest Hazırlığı" bölümüne bak)

# 3. Monitörü başlat (pozisyon geçmişi topla)
python scripts/run_copy_trader.py monitor

# 4. 7 gün sonra backtest çalıştır
python scripts/run_copy_trader.py backtest --trader-uid <UID> --days 7

# 5. En iyi traderları copy trading için kullan
python scripts/run_dual_strategy.py run
```

---

## 📞 Destek

Sorular için:
- `docs/REAL_TRADER_DATA_SOURCES.md` - Detaylı dokümantasyon
- `docs/COPY_TRADING.md` - Copy trading sistemi
- `REAL_TRADERS_GUIDE.md` - Manuel trader ekleme rehberi

---

**🎉 Başarılar! Gerçek trader verisi toplamaya hazırsın.**
