# Binance Futures Copy Trading Sistemi

## Genel Bakış

Bu modül, Binance Futures'da en iyi performans gösteren yatırımcıları otomatik olarak tespit edip, onların pozisyonlarını gerçek zamanlı olarak aynalar.

**Önemli:** Bu sistem, mevcut eğitim ve strateji modülünden **tamamen bağımsız** çalışır. Her iki sistem de paralel olarak aynı anda çalıştırılabilir.

## Nasıl Çalışır?

### 1. Top Trader Keşfi
- Binance Futures Leaderboard API'sinden en iyi yatırımcıları çeker
- ROI, Win Rate, PnL gibi metriklere göre filtreler
- Belirlediğiniz kriterlere uyan top N trader'ı takip listesine ekler

### 2. Pozisyon İzleme
- Takip edilen her trader'ın açık pozisyonlarını periyodik olarak tarar
- Yeni pozisyon açtıklarında bunu tespit eder
- Pozisyon kapattıklarında bunu tespit eder

### 3. Otomatik Aynalama
- Trader yeni pozisyon açtığında, bizim hesabımızda da aynı pozisyon açılır
- Pozisyon büyüklüğü, trader'ın başarı oranına göre otomatik hesaplanır
- Trader pozisyon kapattığında, bizim pozisyonumuz da otomatik kapanır

### 4. Risk Yönetimi
- Total sermayenin sadece belirli bir yüzdesini (default: %30) copy trading için kullanır
- Her pozisyon için min/max limitler vardır
- Maksimum eş zamanlı pozisyon sayısı sınırlıdır
- Leverage otomatik olarak güvenli seviyelere (max 10x) sınırlanır

## Teknik Detaylar

### API Kullanımı

Sistem, Binance Futures Leaderboard verilerine erişmek için **APIcord** servisini kullanır:
- **Ücretsiz Tier:** 100 request/gün
- **Ücretli Tier:** Unlimited requests

API key olmadan da çalışır ama rate limit vardır.

### Veri Yapısı

**Tracked Traders (`data/copy_trading/tracked_traders.json`):**
```json
{
  "encrypted_uid_123": {
    "uid": "encrypted_uid_123",
    "nickname": "CryptoMaster",
    "rank": 5,
    "pnl": 150000.0,
    "roi": 85.5,
    "win_rate": 0.68,
    "follower_count": 12500,
    "is_active": true,
    "min_position_usd": 50.0,
    "max_position_usd": 500.0,
    "copy_multiplier": 1.0
  }
}
```

**Mirrored Positions (`data/copy_trading/mirrored_positions.json`):**
```json
[
  {
    "trader_uid": "encrypted_uid_123",
    "trader_nickname": "CryptoMaster",
    "symbol": "BTCUSDT",
    "side": "LONG",
    "our_entry_price": 65432.10,
    "our_size_usd": 250.0,
    "our_leverage": 5,
    "opened_at": 1715987654321,
    "is_closed": false
  }
]
```

## Kurulum ve Kullanım

### 1. Konfigürasyon

`scenarios/binance_futures_demo.env` dosyasında copy trading ayarlarını yapın:

```bash
# Copy trading'i aktif et
BN_FUT_COPY_ENABLED=1

# API key (opsiyonel — ücretsiz tier için gerekli değil)
BN_FUT_COPY_API_KEY=your_apicord_key_here

# Maksimum takip edilecek trader sayısı
BN_FUT_COPY_MAX_TRADERS=10

# Minimum trader ROI (%) - bu değerin altındaki traderlar takip edilmez
BN_FUT_COPY_MIN_ROI=50.0

# Minimum trader Win Rate (0-1) - bu değerin altındaki traderlar takip edilmez
BN_FUT_COPY_MIN_WR=0.55

# Maksimum eş zamanlı aynalanan pozisyon sayısı
BN_FUT_COPY_MAX_POSITIONS=5

# Total sermayenin yüzde kaçı copy trading için ayrılacak
BN_FUT_COPY_ALLOCATION_PCT=30.0

# Pozisyon kontrolü aralığı (saniye)
BN_FUT_COPY_REFRESH_SEC=60

# Yeni trader keşif aralığı (saniye)
BN_FUT_COPY_DISCOVER_SEC=3600
```

### 2. Top Traders Keşfet (Dry Run)

```bash
# En iyi 20 trader'ı göster
python scripts/run_copy_trader.py discover --show-limit 20

# Haftalık leaderboard
python scripts/run_copy_trader.py discover --period WEEKLY
```

Çıktı örneği:
```
┏━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Rank ┃ Nickname    ┃ ROI %  ┃ Win Rate % ┃ PnL $     ┃ Followers ┃ UID (first 8)  ┃
┡━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│   #1 │ CryptoKing  │  125.3 │       68.5 │   250,000 │    15,234 │ ABC12345...    │
│   #2 │ TradeMaster │   98.7 │       65.2 │   180,000 │    12,450 │ DEF67890...    │
│   #3 │ AlphaWolf   │   87.2 │       62.8 │   150,000 │    10,123 │ GHI11121...    │
└──────┴─────────────┴────────┴────────────┴───────────┴───────────┴────────────────┘
```

### 3. Monitoring Başlat (Dry Run - Test)

```bash
# Dry run mode — gerçek trade açmaz, sadece simüle eder
python scripts/run_copy_trader.py monitor --dry-run
```

Bu modda:
- Top traderlar bulunur ve takip listesine eklenir
- Pozisyonları izlenir
- Hangi pozisyonların açılacağı/kapanacağı konsola yazdırılır
- **GERÇEK TRADE AÇILMAZ**

### 4. Live Trading Başlat (DİKKAT!)

```bash
# GERÇEK TRADE AÇAR!
python scripts/run_copy_trader.py monitor --live
```

⚠️ **UYARI:** Bu mod gerçek pozisyonlar açar! Önce mutlaka dry-run ile test edin.

### 5. Durum Kontrolü

```bash
# Aktif traderları ve pozisyonları göster
python scripts/run_copy_trader.py status
```

## Çalışma Mantığı Detayları

### Trader Seçimi

Sistem, leaderboard'dan traders çekerken şu kriterleri uygular:

1. **ROI Filtresi:** `BN_FUT_COPY_MIN_ROI` değerinin üstündeki traderlar
2. **Win Rate Filtresi:** `BN_FUT_COPY_MIN_WR` değerinin üstündeki traderlar
3. **Sıralama:** Rank, ROI, Win Rate kombinasyonu
4. **Limit:** En iyi `BN_FUT_COPY_MAX_TRADERS` kadar trader seçilir

### Pozisyon Büyüklüğü Hesaplama

Her aynalanan pozisyon için boyut şöyle hesaplanır:

```python
# Copy trading için ayrılan sermaye
copy_capital = total_capital * (copy_allocation_pct / 100)

# Her trader için base allocation
base_allocation = copy_capital / tracked_trader_count

# Trader'ın ROI'sine göre çarpan (daha başarılı trader = daha fazla sermaye)
roi_multiplier = min(trader_roi / 100, 2.0)  # Max 2x

# Final pozisyon boyutu
position_usd = base_allocation * roi_multiplier * trader_copy_multiplier

# Min/max clamp
position_usd = clamp(position_usd, min_position_usd, max_position_usd)
```

Örnek:
- Total capital: $5000
- Copy allocation: 30% → $1500
- Tracked traders: 10
- Base allocation: $150/trader
- Trader ROI: 85% → multiplier: 0.85
- Position: $150 * 0.85 = $127.50

### Pozisyon Açma Kriterleri

Bir pozisyon aynalanamaz eğer:
- Maksimum pozisyon limitine ulaşılmışsa
- Aynı symbol+side için zaten açık pozisyon varsa
- Trader profili aktif değilse

### Pozisyon Kapatma

Trader pozisyonunu kapattığında, sistem bunu algılar ve bizim pozisyonumuzu da otomatik kapatır.

Kapatma algılama: Her refresh cycle'da trader'ın açık pozisyonları çekilir. Daha önce açık olan bir pozisyon artık listede yoksa, o pozisyon kapatılmıştır.

## Risk Yönetimi

### 1. Sermaye Ayırma
- Total sermayenin sadece `BN_FUT_COPY_ALLOCATION_PCT` kadarı copy trading için kullanılır
- Geri kalan sermaye ana strateji için ayrılır
- İki sistem birbirinden tamamen izole çalışır

### 2. Pozisyon Limitleri
- `BN_FUT_COPY_MAX_POSITIONS`: Maksimum eş zamanlı pozisyon sayısı
- Her trader için `min_position_usd` ve `max_position_usd` limitleri
- Toplam risk exposure kontrol altındadır

### 3. Leverage Limitleri
- Trader'ın leverage'ı ne olursa olsun, bizim leverage'ımız max 10x'e sınırlanır
- Daha güvenli işlem için bu değer düşürülebilir

### 4. Trader Performans Takibi
- Her trader'ın güncel performansı kaydedilir
- Performansı düşen traderlar manuel olarak devre dışı bırakılabilir
- Yeni dönemlerde leaderboard'dan fresh data çekilir

## Manuel Müdahale

### Trader'ı Manuel Devre Dışı Bırakma

`data/copy_trading/tracked_traders.json` dosyasını editleyip:

```json
{
  "trader_uid_123": {
    ...
    "is_active": false  // Bu trader artık takip edilmez
  }
}
```

### Trader Parametrelerini Ayarlama

```json
{
  "trader_uid_123": {
    ...
    "min_position_usd": 100.0,    // Bu trader için min
    "max_position_usd": 300.0,    // Bu trader için max
    "copy_multiplier": 0.5        // Bu trader'ın pozisyonlarını %50 boyutunda aç
  }
}
```

## Binance API Entegrasyonu (TODO)

Şu anda sistem **dry-run mode** ile çalışmaktadır. Gerçek pozisyon açma/kapatma için şu fonksiyonlar implement edilmelidir:

1. **`copy_trader.py`** içinde:
   - `mirror_position()` fonksiyonunda gerçek order placement
   - `sync_mirror_exits()` fonksiyonunda gerçek position close
   
2. **Binance API client** kullanımı:
   - `client.futures_create_order()` ile pozisyon aç
   - `client.futures_close_position()` ile pozisyon kapat
   - Leverage ayarla, margin type ayarla

Örnek kod yapısı:

```python
from binance_futures_trader.client import BinanceFuturesClient

def mirror_position(self, trader_pos: TraderPosition, dry_run: bool = False):
    ...
    
    if not dry_run:
        # Gerçek trade açma
        order_result = self.binance_client.futures_create_order(
            symbol=mirror.symbol,
            side=mirror.side,
            positionSide="BOTH",  # ya da "LONG"/"SHORT" hedge mode için
            type="MARKET",
            quantity=calculated_quantity,
            leverage=mirror.our_leverage
        )
        
        # Order sonucunu kaydet
        mirror.our_entry_price = order_result["avgPrice"]
        ...
```

## Performans Takibi

Sistem, tüm mirrored positionları `data/copy_trading/mirrored_positions.json` dosyasında saklar. Bu dosyadan analiz yapılabilir:

- Toplam PnL
- Win rate
- Trader bazında performans
- Symbol bazında performans

Gelecekte bir analiz/raporlama scripti eklenebilir.

## Sorular ve Cevaplar

### Q: API key gerekli mi?
**A:** Hayır, opsiyonel. Ücretsiz tier: 100 req/day. Yeterli değilse APIcord'dan ücretli key alınabilir.

### Q: Eğitim/strateji modülü ile birlikte çalışır mı?
**A:** Evet! İki sistem tamamen bağımsız. Ana stratejiniz kendi watchlist'inde çalışırken, copy trading kendi sermayesiyle paralel çalışır.

### Q: Trader kapattığında ben de hemen kapatır mıyım?
**A:** Evet. Sistem, trader'ın pozisyonunu kapattığını algıladığında sizin pozisyonunuzu da otomatik kapatır. Delay, `BN_FUT_COPY_REFRESH_SEC` kadardır (default: 60 saniye).

### Q: Hangi traderları takip ediyorum nasıl görürüm?
**A:** `python scripts/run_copy_trader.py status` komutu ile görebilirsiniz.

### Q: Manuel olarak pozisyon kapatsam ne olur?
**A:** Sistem bunu algılar ve kaydı günceller. Çakışma olmaz ama manuel müdahale önerilmez.

### Q: Copy trading sermayemi nasıl değiştiririm?
**A:** `.env` dosyasında `BN_FUT_COPY_ALLOCATION_PCT` değerini güncelleyin. Script'i restart edin.

## İleriye Dönük Geliştirmeler

- [ ] Gerçek Binance API entegrasyonu (order placement/close)
- [ ] Performance analytics ve raporlama
- [ ] Trader scoring sistemi (decay with time, weighted by recent trades)
- [ ] Stop-loss/take-profit offsetleri (trader'dan bağımsız risk yönetimi)
- [ ] Backtesting: Geçmiş leaderboard verisiyle copy trading simülasyonu
- [ ] Multi-exchange desteği (Bybit, OKX, etc.)
- [ ] Telegram/Discord notifikasyonları

## Lisans ve Sorumluluk

⚠️ **DİKKAT:** Finansal işlemler risk içerir. Bu sistem eğitim amaçlıdır. Kayıplardan kullanıcı sorumludur. Kendi risk yönetiminizi yapın ve yalnızca kaybetmeyi göze alabileceğiniz sermaye ile işlem yapın.

---

**Son güncelleme:** 2026-05-18
