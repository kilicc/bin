# 🚀 BAŞLATMA KOMUTU

## ✅ Bitget API Test (BAŞARILI!)

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
python3 scripts/run_bitget_to_binance.py test-bitget
```

**Sonuç:**  
✅ 2 kaliteli trader bulundu:
1. **CryptoROBÔ** - ROI: 211.8%, Win Rate: 68.2%
2. **SwissCryptoCashCow** - ROI: 33.5%, Win Rate: 91.1%

---

## 🎯 Dual Strategy Sistemi Başlat

### Seçenek 1: Sadece Copy Trading (Bitget → Binance)

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
python3 scripts/run_bitget_to_binance.py run
```

**Ne yapar:**
- Bitget'ten en iyi 10 trader'ı bulur
- Pozisyonlarını 60 saniyede bir kontrol eder
- Yeni pozisyonları Binance Futures'da açar
- 100 USDT per trade
- Max 5 pozisyon aynı anda

### Seçenek 2: Dual Strategy (Main + Copy Trading)

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
python3 scripts/run_dual_strategy.py run
```

**Ne yapar:**
- **Main Strategy** (5000 USDT): Kendi trading algoritmamız
- **Copy Trading** (5000 USDC): Bitget trader'larını aynalama
- İkisi de paralel çalışır
- Live dashboard ile performans takibi

---

## ⚙️ Config Düzenle

```bash
nano dual_config.json
```

Değiştirebileceğin parametreler:
- `capital_main`: Main strategy sermayesi (şu an 5000)
- `capital_copy`: Copy trading sermayesi (şu an 5000)
- `top_n_traders`: Kaç trader takip edilecek (şu an 10)
- `min_roi`: Minimum ROI filtresi (şu an 10%)
- `min_win_rate`: Minimum win rate (şu an 55%)
- `check_interval`: Kontrol sıklığı (şu an 60 saniye)

---

## 📊 Canlı İzleme

Sistem başladıktan sonra göreceksin:

```
╔════════════════════════════════════════════════════════════╗
║           DUAL STRATEGY LIVE DASHBOARD                     ║
╠════════════════════════════════════════════════════════════╣
║ Main Strategy                                              ║
║   Capital: 5000.00 USDT                                    ║
║   Open Positions: 2                                        ║
║   Total PnL: +125.50 USDT (+2.51%)                         ║
╠════════════════════════════════════════════════════════════╣
║ Copy Trading                                               ║
║   Capital: 5000.00 USDC                                    ║
║   Following: 2 traders                                     ║
║   Open Positions: 1                                        ║
║   Total PnL: +67.30 USDC (+1.35%)                          ║
╚════════════════════════════════════════════════════════════╝
```

---

## 🛑 Durdurma

Ctrl+C ile durdur.

---

## 🔧 Sorun Giderme

### "Config file not found"
```bash
python3 scripts/run_dual_strategy.py create-config
```

### "Bitget API error"
- `.env` dosyasında credentials kontrol et
- `python3 scripts/run_bitget_to_binance.py test-bitget` çalıştır

### "Binance API error"
- Binance testnet credentials kontrol et
- `BINANCE_FUTURES_TESTNET=1` olmalı

---

**HAZIR! SİSTEM ÇALIŞIYOR! 🎉**
