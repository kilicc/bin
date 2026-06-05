# 🎯 GERÇEK TRADER VERİ KAYNAKLARI

Bu doküman, gerçek Binance Futures trader verilerini toplamanın tüm yöntemlerini açıklar.

## 📊 Mevcut Kaynaklar

### 1️⃣ Apify Platform (Ücretli)

**장점:**
- En güvenilir ve kapsamlı veri
- Profesyonel API
- Otomatik güncelleme
- Yapılandırılmış veri

**Servisler:**

#### a) Binance Futures Leaderboard Scraper
- **Actor ID:** `easyapi/binance-futures-leaderboard-scraper`
- **Fiyat:** $19.99/ay + kullanım
- **Veri:**
  - Trader nickname, UID (encrypted)
  - ROI, PNL, rank
  - Follower count
  - Twitter profile
  - Avatar URL
  - Position sharing status

**Kullanım:**
```bash
# API token al: https://console.apify.com/account/integrations
export APIFY_API_TOKEN="your_token_here"

# Veri topla
python scripts/collect_real_traders.py --max-traders 100
```

**Python Kodu:**
```python
from apify_client import ApifyClient

client = ApifyClient("YOUR_API_TOKEN")

run_input = {
    "maxItems": 100,
    "tradeType": "PERPETUAL",
    "statisticsType": "ROI",
    "periodType": "ALL"
}

run = client.actor("easyapi/binance-futures-leaderboard-scraper").call(run_input=run_input)

for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    print(f"{item['nickName']}: ROI={item['roi']}%, PNL=${item['pnl']}")
```

#### b) Binance Smart Money Trader Positions Tracker
- **Actor ID:** `mayanksingh2233/binance-smart-money-trader-positions-tracker-api`
- **Fiyat:** $0.0018 per API call
- **Veri:**
  - Real-time open positions
  - Entry price, mark price, liquidation price
  - Leverage, margin, PNL, ROI
  - Position side (LONG/SHORT)
  - Symbol, amount

**Kullanım:**
```python
from apify_client import ApifyClient

client = ApifyClient("YOUR_API_TOKEN")

run_input = {
    "endpoint": "positions",
    "traderId": "4936522826423009536",
    "marketType": "UM",
    "page": 1,
    "rows": 20
}

run = client.actor("mayanksingh2233/binance-smart-money-trader-positions-tracker-api").call(run_input=run_input)

for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    result = item["results"]
    print(f"Trader: {result['traderName']}")
    print(f"Total Positions: {result['totalPositions']}")
    for pos in result['positions']:
        print(f"  {pos['symbol']} {pos['side']}: PNL=${pos['pnl']}, ROI={pos['roi']*100}%")
```

---

### 2️⃣ Binance Public API (BAPI) - ÜCRETSİZ ✅

**장점:**
- Tamamen ücretsiz
- API key gerekmez
- Authentication gerekmez
- Gerçek zamanlı veri

**Base URL:** `https://www.binance.com/bapi/futures`

#### Mevcut Endpoints:

##### a) Trader Profile Info
```bash
POST https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherLeaderboardBaseInfo

{
  "encryptedUid": "3AFFCB67ED4F1D1D8437BA17F4E8E5ED"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "nickName": "StellarMom",
    "roi": 154.82,
    "pnl": 22418.98,
    "followerCount": 396540,
    "daysActive": 2240,
    "winRate": 0.4551,
    "sharpeRatio": 1.23,
    "maxDrawDown": 0.7009,
    "umMarginBalance": 5386064.38,
    "isPositionShared": true
  }
}
```

##### b) Trader Positions
```bash
POST https://www.binance.com/bapi/futures/v2/public/future/leaderboard/getOtherPosition

{
  "encryptedUid": "3AFFCB67ED4F1D1D8437BA17F4E8E5ED",
  "tradeType": "PERPETUAL"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "otherPositionRetList": [
      {
        "symbol": "BTCUSDT",
        "entryPrice": 95000.0,
        "markPrice": 96500.0,
        "pnl": 1500.0,
        "roe": 0.15,
        "amount": 1.0,
        "leverage": 10,
        "updateTimeStamp": 1747155600000
      }
    ]
  }
}
```

##### c) Performance History
```bash
POST https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getOtherPerformance

{
  "encryptedUid": "3AFFCB67ED4F1D1D8437BA17F4E8E5ED",
  "tradeType": "PERPETUAL"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "performanceRetList": [
      {
        "date": 1747065600000,
        "roi": 5.2,
        "pnl": 1200.50
      }
    ]
  }
}
```

**Python Örnek:**
```python
import httpx

async def get_trader_positions(encrypted_uid: str):
    client = httpx.AsyncClient()
    url = "https://www.binance.com/bapi/futures/v2/public/future/leaderboard/getOtherPosition"
    payload = {"encryptedUid": encrypted_uid, "tradeType": "PERPETUAL"}
    
    response = await client.post(url, json=payload)
    data = response.json()
    
    if data.get("success"):
        return data["data"]["otherPositionRetList"]
    return []
```

---

### 3️⃣ Web Scraping (Playwright) - ÜCRETSİZ ✅

**장점:**
- Tamamen ücretsiz
- Görsel veriyi çekebilir
- API olmayan verilere erişim

**Hedef URL:**
```
https://www.binance.com/en/futures-activity/leaderboard
```

**Kullanım:**
```bash
# Playwright'i yükle
pip install playwright
playwright install chromium

# Veri topla
python scripts/collect_free_traders.py --max-traders 100
```

**Python Kodu:**
```python
from playwright.async_api import async_playwright

async def scrape_leaderboard():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto("https://www.binance.com/en/futures-activity/leaderboard")
        await page.wait_for_selector('[data-test-id="leaderboard-row"]')
        
        rows = await page.query_selector_all('[data-test-id="leaderboard-row"]')
        
        traders = []
        for row in rows:
            nickname = await row.query_selector('[data-test-id="nickname"]')
            roi = await row.query_selector('[data-test-id="roi"]')
            
            # UID'yi link'ten çıkar
            link = await row.query_selector('a[href*="encryptedUid"]')
            href = await link.get_attribute("href")
            uid = href.split("encryptedUid=")[1].split("&")[0]
            
            traders.append({
                "uid": uid,
                "nickname": await nickname.inner_text(),
                "roi": float((await roi.inner_text()).replace("%", ""))
            })
        
        await browser.close()
        return traders
```

---

## 🚀 Hızlı Başlangıç

### Senaryo 1: Ücretsiz Yöntem (Önerilen)

```bash
# 1. Playwright'i yükle
pip install playwright httpx
playwright install chromium

# 2. Top 100 trader'ı topla (profil + pozisyon + geçmiş)
python scripts/collect_free_traders.py --max-traders 100

# Çıktı:
# - data/real_traders/free_traders_full.json (ana veri)
# - data/real_traders/positions_*.json (pozisyonlar)
# - data/real_traders/history_*.json (performans geçmişi)
```

### Senaryo 2: Apify ile (Ücretli ama daha güvenilir)

```bash
# 1. Apify hesabı aç: https://console.apify.com/sign-up
# 2. API token al: https://console.apify.com/account/integrations
# 3. Token'ı ayarla
export APIFY_API_TOKEN="your_token_here"

# 4. Apify client'ı yükle
pip install apify-client

# 5. Veri topla
python scripts/collect_real_traders.py --max-traders 100

# Çıktı:
# - data/real_traders/profiles.json
# - data/real_traders/positions_history/
# - data/real_traders/metadata.json
```

---

## 📁 Çıktı Formatı

### `profiles.json`
```json
{
  "3AFFCB67ED4F1D1D8437BA17F4E8E5ED": {
    "uid": "3AFFCB67ED4F1D1D8437BA17F4E8E5ED",
    "nickname": "StellarMom",
    "source": "apify_leaderboard",
    "roi": 154.82,
    "pnl": 22418.98,
    "win_rate": 0.4551,
    "rank": 61,
    "follower_count": 396540,
    "twitter_url": "https://twitter.com/ICPSCAMCOIN",
    "avatar_url": "https://...",
    "days_active": 2240,
    "max_drawdown": 0.7009,
    "sharpe_ratio": null,
    "um_margin_balance": null,
    "cm_margin_balance": null,
    "position_shared": true,
    "position_history_shared": false,
    "is_active": true,
    "last_update": 1737763200000,
    "collected_at": 1747155600000,
    "data_quality_score": 83.3
  }
}
```

### `positions_history/{uid}/positions_{timestamp}.json`
```json
[
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
    "isolated": true,
    "margin": 9500.0,
    "liq_price": 86500.0,
    "timestamp": 1747155600000,
    "status": "OPEN"
  }
]
```

---

## 🔄 Backtest için Pozisyon Geçmişi

### Sorun:
Binance'in public API'si sadece **mevcut pozisyonları** verir, **geçmiş (kapalı) pozisyonları** vermez.

### Çözüm Yöntemleri:

#### 1️⃣ Forward Testing (Önerilen)
Sistemi şimdi başlat, pozisyonları kaydet, zamanla geçmiş oluştur:

```bash
# Pozisyon tracker'ı başlat (5 saniyede bir poll)
python scripts/run_copy_trader.py monitor

# Her pozisyon değişikliği kaydedilir:
# - data/copy_trading/position_snapshots/{uid}_{timestamp}.json
```

3-7 gün sonra gerçek backtest verisi elde edersin.

#### 2️⃣ Performance History Kullan
Binance API'si günlük ROI/PNL geçmişi verir:

```python
# ROI timeline'dan pozisyon simülasyonu
history = await api.get_trader_history(uid)
for day in history["performanceRetList"]:
    # day["roi"] ve day["pnl"] ile pozisyon tahmin et
    estimated_position = simulate_from_roi(day)
```

#### 3️⃣ Web Archive (İleri Seviye)
Internet Archive'dan geçmiş leaderboard snapshot'ları çek:

```python
import requests

def get_historical_leaderboard(date: str):
    # Wayback Machine API
    url = f"https://archive.org/wayback/available?url=binance.com/futures-activity/leaderboard&timestamp={date}"
    response = requests.get(url)
    # ...
```

---

## 🎯 Backtest İçin Veri Kalitesi

### Veri Kalitesi Skoru (0-100)

Sistem her trader için otomatik skor hesaplar:

```python
quality_score = (
    has_roi * 20 +
    has_pnl * 20 +
    has_rank * 10 +
    has_followers * 10 +
    position_shared * 30 +
    has_twitter * 10
) / 100
```

**Backtest için minimum önerilen skor:** 60+

**Filtreleme örneği:**
```python
good_traders = [
    t for t in traders 
    if t.data_quality_score >= 60 
    and t.position_shared 
    and t.win_rate >= 0.50
]
```

---

## 📊 Gerçek Trader Örnekleri (Mayıs 2026)

Bu trader UID'leri gerçek ve public:

```python
EXAMPLE_TRADERS = [
    {
        "uid": "3AFFCB67ED4F1D1D8437BA17F4E8E5ED",
        "nickname": "StellarMom",
        "roi": 154.82,
        "win_rate": 0.45,
        "followers": 396540
    },
    {
        "uid": "0C2123F5688F316245836C60A66F8240",
        "nickname": "BoinkBoink",  # Örnek, gerçek nickname farklı olabilir
        "roi": 1.13,
        "win_rate": 0.55,
        "followers": 803
    }
]
```

Bu UID'leri `tracked_traders.json` dosyasına ekleyerek hemen test edebilirsin.

---

## 🛠️ Kullanılan Araçlar

| Araç | Amaç | Ücret |
|------|------|-------|
| **Playwright** | Web scraping | Ücretsiz |
| **httpx** | HTTP client (async) | Ücretsiz |
| **Binance BAPI** | Public API | Ücretsiz |
| **Apify** | Professional scraping | Ücretli ($19.99/ay+) |
| **Rich** | Terminal UI | Ücretsiz |

---

## ⚡ Hızlı Komutlar

```bash
# Ücretsiz - Sadece profiller (en hızlı)
python scripts/collect_free_traders.py --max-traders 50 --no-positions --no-history

# Ücretsiz - Profil + pozisyon
python scripts/collect_free_traders.py --max-traders 50 --no-history

# Ücretsiz - Tam veri seti
python scripts/collect_free_traders.py --max-traders 100

# Apify - Tam veri seti (daha güvenilir)
export APIFY_API_TOKEN="your_token"
python scripts/collect_real_traders.py --max-traders 100

# Mevcut veriyi kontrol et
ls -lh data/real_traders/
cat data/real_traders/free_traders_full.json | jq '.[0]'
```

---

## 🔗 Yararlı Linkler

- [Binance Futures Leaderboard](https://www.binance.com/en/futures-activity/leaderboard)
- [Apify Binance Leaderboard Scraper](https://apify.com/easyapi/binance-futures-leaderboard-scraper)
- [Apify Smart Money Positions](https://apify.com/mayanksingh2233/binance-smart-money-trader-positions-tracker-api)
- [Playwright Documentation](https://playwright.dev/python/)
- [Binance API Documentation](https://developers.binance.com/)

---

## ❓ SSS

**S: Apify kullanmak zorunda mıyım?**  
C: Hayır! Tamamen ücretsiz yöntem için `scripts/collect_free_traders.py` kullan.

**S: Geçmiş pozisyon verisi var mı?**  
C: Binance public API'si sadece mevcut pozisyonları verir. Geçmiş için forward testing yapmalısın.

**S: Kaç trader toplamalıyım?**  
C: Top 50-100 trader yeterli. Daha fazlası rate limiting sorununa neden olabilir.

**S: Web scraping yasal mı?**  
C: Binance'in public leaderboard'ı herkes tarafından görülebilir. Makul rate limiting ile scraping soruntu olmaz.

**S: API rate limit ne kadar?**  
C: Binance BAPI: ~100 req/min. Web scraping: daha yavaş (bot detection).

---

## 📝 Not

Bu sistem **eğitim ve araştırma amaçlıdır**. Gerçek trading yaparken:
- Demo hesapla test et
- Risk yönetimi kullan
- Kendi araştırmanı yap
- Kayıpları kaldırabileceğin miktarla çalış
