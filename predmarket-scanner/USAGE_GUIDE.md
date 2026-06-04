# 🎯 Hızlı Kullanım Kılavuzu - Gelişmiş Copy Trading Sistemi

## 📋 Gerekli Adımlar (İlk Kurulum)

### 1. Dependencies Yükleyin

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
source .venv/bin/activate

# Yeni paketler
pip install playwright beautifulsoup4 lxml

# Playwright browser install
playwright install chromium
```

**Tahmini süre:** 2-3 dakika

---

## 🚀 Kullanım Senaryoları

### Senaryo 1: Otomatik Trader Keşfi (İlk Test)

```bash
# Terminal 1: Auto-discovery çalıştır
python -m binance_futures_trader.trader_discovery
```

**Ne yapar:**
- Binance Leaderboard'ı scrape eder
- Top 15 trader'ı otomatik bulur
- `data/copy_trading/tracked_traders.json`'a kaydar

**Beklenen çıktı:**
```
🔍 Scraping Binance Leaderboard (MONTHLY, ROI)...
Found 50 trader rows
  ✓ #1 CryptoKing - ROI: 125.3%
  ✓ #2 TradeMaster - ROI: 98.7%
  ✓ #5 AlphaWolf - ROI: 87.2%
  ...
✓ Scraped 15 qualified traders
✓ Discovery Complete: 15 added, 0 updated
```

---

### Senaryo 2: Copy Trading Backtest

```bash
# Terminal 1: Backtest çalıştır
python -m binance_futures_trader.copy_backtest
```

**Ne yapar:**
- 30 günlük simülasyon yapar
- Copy trading performansını ölçer
- `data/copy_trading/backtest_result_sample.json`'a kaydeder

**Beklenen sonuç:**
```
Copy Trading Backtest Results
══════════════════════════════
Duration:      30 days
Start Balance: $5,000.00
End Balance:   $5,847.32
Total PnL:     +$847.32
Total Return:  +16.95%
Max Drawdown:  8.34%
Calmar Ratio:  2.03

Total Trades:  47
Win Rate:      68.1%
Profit Factor: 2.34
```

---

### Senaryo 3: Backtest Karşılaştırma

```bash
# Main strategy backtest sonucu zaten var
# Copy trading backtest yaptıysanız:

python scripts/run_dual_strategy.py compare-backtests
```

**Ne yapar:**
- Main strategy vs Copy trading performansını karşılaştırır
- Hangi stratejinin daha iyi olduğunu gösterir

**Beklenen çıktı:**
```
📊 Strategy Backtest Comparison

┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Metric       ┃ Main Strategy ┃ Copy Trading  ┃ Winner ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ Return %     │    +273.69%   │     +16.95%   │ 🏆 Main│
│ Win Rate     │      62.8%    │      68.1%    │ 🏆 Copy│
│ Max Drawdown │      32.6%    │       8.3%    │ 🏆 Copy│
│ Total Trades │        156    │         47    │   -    │
└──────────────┴───────────────┴───────────────┴────────┘

Summary:
✓ Main Strategy performed better (+256.74%)
```

---

### Senaryo 4: Dual Strategy (Dry-Run Test)

```bash
# Terminal 1: Dual strategy başlat (test mode)
python scripts/run_dual_strategy.py run \
  --capital 5000 \
  --main-pct 70 \
  --copy-pct 30
```

**Ne yapar:**
- Her iki stratejiyi paralel çalıştırır
- Live dashboard gösterir
- Real-time performans karşılaştırır

**Beklenen ekran:**
```
═══ Live Dashboard - 18:45:32 ═══

Strategy Performance Comparison
┏━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Metric              ┃ Main Strategy ┃ Copy Trading  ┃ Combined      ┃
┡━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ Capital Allocated   │  $3,500.00    │  $1,500.00    │  $5,000.00    │
│ Current Balance     │  $3,758.45    │  $1,584.12    │  $5,342.57    │
│ Total PnL           │    +$258.45   │     +$84.12   │    +$342.57   │
│ Return %            │      +7.38%   │      +5.61%   │      +6.85%   │
│ Total Trades        │          12   │           6   │          18   │
│ Win Rate            │       66.7%   │       66.7%   │       66.7%   │
│ Open Positions      │           3   │           1   │           4   │
│ Max Drawdown        │        4.2%   │        2.1%   │        3.5%   │
└─────────────────────┴───────────────┴───────────────┴───────────────┘

Press Ctrl+C to stop
```

---

### Senaryo 5: Manuel Trader Ekleme (Alternatif)

Auto-discovery yerine manuel olarak trader eklemek isterseniz:

```bash
# Leaderboard'dan UID alın:
# https://www.binance.com/en/futures-activity/leaderboard
# Trader'a tıklayın, URL'den UID'yi kopyalayın

python scripts/add_trader.py add \
  --uid "0C2123F5688F316245836C60A66F8240" \
  --nickname "CryptoKing" \
  --roi 85.5 \
  --rank 5

# Eklenen traderları görün
python scripts/add_trader.py list-traders
```

---

## 🔄 Normal Çalışma Akışı

### Günlük Kullanım:

1. **Sabah:** Auto-discovery çalıştır (yeni traders check)
   ```bash
   python -m binance_futures_trader.trader_discovery
   ```

2. **Gün içi:** Dual strategy monitoring
   ```bash
   python scripts/run_dual_strategy.py run --capital 5000
   ```

3. **Akşam:** Performance review
   ```bash
   # Dashboard'dan metrikleri gözlemleyin
   # Report dosyasını kontrol edin: data/dual_strategy_report.json
   ```

### Haftalık:

1. **Backtest comparison**
   ```bash
   python scripts/run_dual_strategy.py compare-backtests
   ```

2. **Trader performance review**
   ```bash
   python scripts/add_trader.py list-traders
   # Kötü performans gösterenleri pasif yapın:
   python scripts/add_trader.py toggle --uid "TRADER_UID"
   ```

---

## 🎛️ Konfigürasyon

### Copy Trading Ayarları (`.env` dosyası):

```bash
# scenarios/binance_futures_demo.env

# Copy trading
BN_FUT_COPY_ENABLED=1
BN_FUT_COPY_MAX_TRADERS=10
BN_FUT_COPY_MIN_ROI=50.0
BN_FUT_COPY_MIN_WR=0.55
BN_FUT_COPY_MAX_POSITIONS=5
BN_FUT_COPY_ALLOCATION_PCT=30.0
BN_FUT_COPY_REFRESH_SEC=5    # 5 saniye polling
BN_FUT_COPY_DISCOVER_SEC=86400  # 24 saat discovery
```

### Dual Strategy Ayarları:

```bash
# Sermaye dağılımı
python scripts/run_dual_strategy.py run \
  --capital 5000 \      # Total capital
  --main-pct 70 \       # Main strategy %70
  --copy-pct 30         # Copy trading %30
```

---

## 📊 Dosya Konumları

### Output Files:

```
data/
├── copy_trading/
│   ├── tracked_traders.json        # Takip edilen traderlar
│   ├── mirrored_positions.json     # Açık pozisyonlar
│   ├── discovery_log.json          # Discovery geçmişi
│   ├── backtest_result_sample.json # Backtest sonucu
│   └── klines_cache/               # Kline cache
│
├── education/
│   └── portfolio_backtest_6m.json  # Main strategy backtest
│
├── dual_strategy_report.json       # Dual strategy raporu
│
└── backups/
    └── settings/                    # Ayar yedekleri
```

### Logs:

```
# Real-time console output
# Her iki strategy'nin pozisyonları, PnL, metrikleri

# Discovery log
data/copy_trading/discovery_log.json
```

---

## 🐛 Troubleshooting

### Problem: Playwright bulunamadı

```bash
pip install playwright
playwright install chromium
```

### Problem: Auto-discovery çalışmıyor

**Neden:** Leaderboard sayfası yüklenmedi ya da HTML yapısı değişti

**Çözüm:**
1. İnternet bağlantısını kontrol edin
2. Manuel trader ekleme kullanın (`add_trader.py`)
3. Discovery log'u kontrol edin: `data/copy_trading/discovery_log.json`

### Problem: Backtest dosyası bulunamadı

```bash
# Main strategy backtest yoksa:
python scripts/run_portfolio_final.py

# Copy trading backtest yoksa:
python -m binance_futures_trader.copy_backtest
```

### Problem: Real-time tracking yavaş

**Neden:** 5 saniye polling delay var (tasarım gereği)

**Çözüm:**
- `.env` dosyasında `BN_FUT_COPY_REFRESH_SEC=3` yapın (3 saniyeye düşürün)
- Daha hızlı için WebSocket gerekir (Binance'da public değil)

---

## ✅ Checklist (İlk Çalıştırma)

- [ ] Dependencies yüklendi (`playwright`, `beautifulsoup4`)
- [ ] Playwright browser kuruldu (`playwright install chromium`)
- [ ] Auto-discovery test edildi
- [ ] En az 5 trader otomatik eklendi
- [ ] Copy trading backtest çalıştırıldı
- [ ] Main strategy backtest mevcut
- [ ] Backtest comparison yapıldı
- [ ] Dual strategy dry-run test edildi
- [ ] Dashboard çalışıyor
- [ ] Report dosyaları oluşuyor

---

## 🎯 Sonraki Adımlar

1. ✅ **İlk test:** Auto-discovery + backtest
2. ✅ **Karşılaştırma:** Main vs Copy performance
3. ✅ **Dry-run:** Dual strategy test mode
4. ⏳ **Live mode:** Her iki strateji canlı (kullanıcı kararı)
5. ⏳ **Monitoring:** Günlük performans takibi
6. ⏳ **Optimization:** Kötü performans gösteren traders'ı disable et

---

## 📞 Destek

Sorularınız için:
- `ADVANCED_COPY_TRADING_COMPLETE.md` - Tam sistem özeti
- `docs/COPY_TRADING.md` - Teknik dokümantasyon
- Her modülün docstring'leri - Kod içi açıklamalar

---

**Hazırlayan:** Claude Sonnet 4.5  
**Tarih:** 2026-05-18  
**Versiyon:** 2.0  
**Durum:** ✅ Ready to Use
