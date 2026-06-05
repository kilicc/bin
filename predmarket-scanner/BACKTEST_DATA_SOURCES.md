# 📊 BACKTEST VERİ KAYNAKLARI

## Main Strateji vs Copy Trading Backtest

---

## ✅ MAIN STRATEJİ (Portfolio Backtest) - GERÇEK VERİ!

### Veri Kaynağı: **Binance API (Gerçek Historical Data)**

```python
# binance_futures_trader/client.py

def klines_history(self, coin: str, interval: str, days: int = 180):
    """Gerçek Binance API'sinden historical kline data çeker"""
    
    # Binance API endpoint
    raw = self._get("/fapi/v1/klines", params)
    #              ↑
    #         GERÇEk BINANCE API!
```

### API Endpoint:
```
GET https://fapi.binance.com/fapi/v1/klines
```

### Parametreler:
- `symbol`: BTCUSDT, ETHUSDT, vb
- `interval`: 15m, 1h, 4h, 1d
- `limit`: 1500 (max per request)
- `endTime`: Backward pagination için

### Veri Formatı:
```json
[
  [
    1499040000000,      // Open time
    "0.01634790",       // Open
    "0.80000000",       // High
    "0.01575800",       // Low
    "0.01577100",       // Close
    "148976.11427815",  // Volume
    1499644799999,      // Close time
    "2434.19055334",    // Quote asset volume
    308,                // Number of trades
    "1756.87402397",    // Taker buy base volume
    "28.46694368",      // Taker buy quote volume
    "17928899.62484339" // Ignore
  ]
]
```

### Cache Sistemi:

```python
# Veriler cache'lenir (tekrar API çağrısı yapılmaz)
cache_file = "data/education/klines_cache/{coin}_{interval}_{days}d.json"

if cache_file.is_file():
    # Cache'den oku (hızlı)
    return cached_data
else:
    # API'den çek, cache'e kaydet
    fetch_from_binance()
```

### Örnek:

```bash
# 6 aylık BTCUSDT 15m data
Cache: data/education/klines_cache/BTC_15m_180d.json

# İçeriği:
- 17,280 mum (180 gün × 96 mum/gün)
- Her mum: open, high, low, close, volume
- Gerçek piyasa verileri!
```

---

## ❌ COPY TRADING BACKTEST - SANAL VERİ!

### Problem: **Binance Trader Position History API YOK!**

```python
# Böyle bir API endpoint YOK:
# GET /sapi/v1/copyTrading/futures/traderHistory/{traderId}  ❌
```

### Neden Sanal Veri?

1. **Binance API kısıtlaması:**
   - Trader position history API yok
   - Sadece anlık (current) positions var
   - Geçmiş pozisyonlar için API endpoint yok

2. **Alternatif yok:**
   - Web scraping: Anti-bot protection
   - Public data: Mevcut değil
   - Historical data: Binance sağlamıyor

### Sanal Veri Yapısı:

```python
# binance_futures_trader/copy_backtest.py

def _generate_demo_positions(self, trader_id: str):
    """
    Simüle edilmiş trader pozisyonları oluştur
    (Gerçek veri olmadığı için)
    """
    
    # Random ama gerçekçi pozisyonlar
    position = {
        'symbol': random.choice(['BTCUSDT', 'ETHUSDT']),
        'side': random.choice(['LONG', 'SHORT']),
        'entry_price': current_price * (1 + random.uniform(-0.02, 0.02)),
        'exit_price': entry_price * (1 + random.uniform(-0.05, 0.10)),
        'pnl': calculate_pnl(entry, exit)
    }
```

### Ne Yapıldı:

```
1. Gerçek kline data çek (Binance API)
2. Trader pozisyonlarını simüle et:
   - Entry/exit points algoritmik
   - TP/SL realistic values
   - Win rate ~55-65%
   - Risk/reward realistic
3. Backtest engine ile test
4. Performance metrics hesapla
```

---

## 📊 KARŞILAŞTIRMA

| Feature | Main Strateji | Copy Trading |
|---------|---------------|--------------|
| **Kline Data** | ✅ Gerçek (Binance API) | ✅ Gerçek (Binance API) |
| **Trader Positions** | N/A (kendi stratejisi) | ❌ **SANAL (simülasyon)** |
| **Entry/Exit Points** | ✅ Gerçek (indicators) | ❌ Simüle edilmiş |
| **TP/SL Levels** | ✅ ATR-based (gerçek) | ❌ Algorithm-generated |
| **Backtest Accuracy** | ⭐⭐⭐⭐⭐ **Yüksek** | ⭐⭐ **Düşük (estimate)** |

---

## 🎯 SONUÇ

### Main Strateji Backtest:

```
✅ %100 GERÇEK VERİ!

Data Source:
- Binance API (/fapi/v1/klines)
- 6 aylık historical kline data
- Cache: data/education/klines_cache/

Güvenilirlik: ⭐⭐⭐⭐⭐
```

### Copy Trading Backtest:

```
❌ SANAL VERİ (Simülasyon)

Neden:
- Binance trader position history API YOK
- Gerçek trader data erişim YOK
- Simülasyon ile estimate edildi

Güvenilirlik: ⭐⭐ (Sadece concept test)
```

---

## 💡 ÇÖZÜM: BITGET KULLAN!

### Bitget ile Gerçek Veri:

**장점:**
- ✅ Trader listesi API var
- ✅ Position history API olabilir (araştır)
- ✅ Gerçek copy trading backtest mümkün!

**Next Step:**

```python
# Bitget API ile gerçek trader data
GET /api/v2/copy/mix-follower/query-traders
GET /api/v2/copy/mix-follower/query-history-orders

# Bu verilerle GERÇEK backtest yapılabilir!
```

---

## 📁 İLGİLİ DOSYALAR

### Main Strateji (Gerçek Veri):
```
binance_futures_trader/client.py
  → klines_history()  # Binance API
  
binance_futures_trader/portfolio_backtest.py
  → run_backtest()    # Gerçek kline data kullanır

data/education/klines_cache/
  → BTC_15m_180d.json  # Cached gerçek data
```

### Copy Trading (Sanal Veri):
```
binance_futures_trader/copy_backtest.py
  → _generate_demo_positions()  # Simülasyon
  
binance_futures_trader/copy_trader.py
  → Real-time için (backtest için değil)
```

---

## ✅ ÖZET

**Main Strateji Backtest:**
- ✅ **GERÇEK VERİ** (Binance API)
- ✅ 6 aylık historical kline data
- ✅ Cache sistemi var
- ✅ %100 güvenilir

**Copy Trading Backtest:**
- ❌ **SANAL VERİ** (Simülasyon)
- ❌ Trader position history API yok
- ❌ Sadece concept test
- ⚠️ Gerçek backtest için Bitget kullan!

**Sonuç:** Main stratejinin backtest'i güvenilir, copy trading'inki sadece tahmini! 📊
