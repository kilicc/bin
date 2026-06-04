# ⚡ HIZLI BAŞLANGIÇ: GERÇEK TRADER VERİSİ TOPLAMA

## 🎯 5 Dakikada Başla

### Adım 1: Gereksinimler (2 dk)

```bash
cd predmarket-scanner

# Python bağımlılıkları
pip install httpx rich playwright

# Playwright browser
playwright install chromium
```

### Adım 2: Test Et (1 dk)

```bash
# Binance Public API test
python scripts/test_data_sources.py

# Başarılıysa devam et ✅
```

### Adım 3: İlk Veri Toplama (2 dk)

```bash
# Top 50 trader'ı topla (profil + pozisyon + geçmiş)
python scripts/collect_free_traders.py --max-traders 50

# Çıktı: data/real_traders/free_traders_full.json
```

### Adım 4: Veriyi Kontrol Et

```bash
# Toplanan trader sayısı
cat data/real_traders/free_traders_full.json | jq 'length'

# İlk 3 trader
cat data/real_traders/free_traders_full.json | jq '.[0:3]'

# Top 10 ROI
cat data/real_traders/free_traders_full.json | jq 'sort_by(.roi) | reverse | .[0:10] | .[] | {nickname, roi, win_rate, follower_count}'
```

---

## 🎉 Başarılı! Ne Yapmalısın?

### Seçenek 1: Copy Trading'e Başla

```bash
# 1. Kaliteli traderları filtrele
python -c "
import json
with open('data/real_traders/free_traders_full.json') as f:
    traders = json.load(f)
good = [t for t in traders if t.get('data_quality_score', 0) >= 60 and t.get('position_shared')]
print(f'✓ {len(good)} good traders')
for t in good[:10]:
    print(f\"  {t['nickname']}: ROI={t['roi']:.1f}%, Score={t['data_quality_score']:.0f}\")
"

# 2. İyi bir trader'ı ekle
python scripts/add_trader.py add <UID>

# 3. Monitor'ü başlat (pozisyon takibi)
python scripts/run_copy_trader.py monitor
```

### Seçenek 2: Forward Testing

```bash
# 1. Birden fazla trader ekle
python scripts/add_trader.py add <UID1>
python scripts/add_trader.py add <UID2>
python scripts/add_trader.py add <UID3>

# 2. Monitor'ü 7 gün çalıştır (pozisyon geçmişi topla)
python scripts/run_copy_trader.py monitor

# 3. 7 gün sonra backtest
python scripts/run_copy_trader.py backtest --trader-uid <UID> --days 7
```

### Seçenek 3: Dual Strategy (Ana + Copy)

```bash
# 1. Dual strategy'yi başlat
python scripts/start_dual_system.py

# 2. Talimatları takip et
```

---

## 📊 Örnek: İyi Trader Bulma

```python
import json

# Veriyi yükle
with open("data/real_traders/free_traders_full.json") as f:
    traders = json.load(f)

# Filtreleme kriterleri
CRITERIA = {
    "min_roi": 50.0,           # Minimum %50 ROI
    "min_win_rate": 0.55,      # Minimum %55 win rate
    "min_quality_score": 60,   # Minimum veri kalitesi
    "position_shared": True,   # Pozisyon paylaşmalı
    "min_followers": 1000      # En az 1000 takipçi
}

# İyi traderları filtrele
good_traders = [
    t for t in traders
    if (
        t.get("roi", 0) >= CRITERIA["min_roi"]
        and t.get("win_rate", 0) >= CRITERIA["min_win_rate"]
        and t.get("data_quality_score", 0) >= CRITERIA["min_quality_score"]
        and t.get("position_shared", False) == CRITERIA["position_shared"]
        and t.get("follower_count", 0) >= CRITERIA["min_followers"]
    )
]

# Sonuçları göster
print(f"\n✓ {len(good_traders)} traders match criteria:\n")
for t in sorted(good_traders, key=lambda x: x.get("roi", 0), reverse=True)[:10]:
    print(f"  {t['nickname']:20s}  ROI: {t['roi']:6.1f}%  WR: {t['win_rate']*100:5.1f}%  Score: {t['data_quality_score']:3.0f}")

# En iyisinin UID'sini yazdır
if good_traders:
    best = max(good_traders, key=lambda x: x.get("roi", 0))
    print(f"\n🏆 Best: {best['nickname']} (UID: {best['uid']})")
```

Çalıştır:

```bash
python -c "$(cat filter_traders.py)"
```

---

## 🛠️ Sorun Giderme

### "Playwright executable not found"

```bash
playwright install chromium

# macOS ARM64 için
playwright install chromium --with-deps
```

### "No traders scraped"

Web scraping çalışmadıysa, sadece API kullan:

```bash
# Sadece Binance Public API (web scraping yok)
python -c "
import asyncio
from binance_futures_trader.free_trader_sources import BinancePublicAPI

async def quick_test():
    api = BinancePublicAPI()
    profile = await api.get_trader_profile('3AFFCB67ED4F1D1D8437BA17F4E8E5ED')
    print(f\"✓ API working! Trader: {profile.get('nickName', 'N/A')}\")
    await api.close()

asyncio.run(quick_test())
"
```

### "Rate limit exceeded"

Daha az trader topla:

```bash
python scripts/collect_free_traders.py --max-traders 20
```

---

## 📚 Daha Fazla Bilgi

| Dokuman | Açıklama |
|---------|----------|
| `REAL_TRADERS_COLLECTION.md` | Ana rehber |
| `docs/REAL_TRADER_DATA_SOURCES.md` | Tüm kaynakların detaylı açıklaması |
| `docs/COPY_TRADING.md` | Copy trading sistemi |
| `REAL_TRADERS_GUIDE.md` | Manuel trader ekleme |

---

## ⚡ Hızlı Komutlar Özeti

```bash
# TEST
python scripts/test_data_sources.py

# VERİ TOPLAMA
python scripts/collect_free_traders.py --max-traders 50

# VERİYİ GÖRÜNTÜLEME
cat data/real_traders/free_traders_full.json | jq '.[0:5]'

# TRADER EKLEME
python scripts/add_trader.py add <UID>

# MONITOR BAŞLATMA
python scripts/run_copy_trader.py monitor

# DUAL STRATEGY
python scripts/start_dual_system.py
```

---

## 🎯 Başarı Kriterleri

Sistem başarıyla kuruldu demektir eğer:

- ✅ `python scripts/test_data_sources.py` çalışıyor
- ✅ `data/real_traders/free_traders_full.json` dosyası oluştu
- ✅ En az 10+ trader verisi toplandı
- ✅ Trader'ların %50+ 'si `position_shared: true`

Eğer bunlar tamsa, **gerçek trader verisi toplama sistemi çalışıyor** demektir! 🎉

---

**Sonraki adım:** İyi traderları bul, ekle, ve copy trading'e başla! 🚀
