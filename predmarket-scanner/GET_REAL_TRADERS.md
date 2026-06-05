# 🎯 GERÇEK BINANCE FUTURES TRADER VERİSİ NASIL ALINIR

## ✅ API Key Çalışıyor Ama Futures Erişimi Yok

### Sorun
API key'in sadece SPOT izni var, Futures izni yok.

### Çözüm: Futures İznini Ekle

#### Adım 1: API Key Düzenle

1. https://www.binance.com 'e git
2. Profil > **API Management**
3. Oluşturduğun API key'i bul
4. **Edit** (düzenle) ikonuna tıkla

#### Adım 2: Futures İznini Aktif Et

API Key düzenleme sayfasında:

```
☐ Enable Spot & Margin Trading
☑ Enable Reading                    ← Zaten aktif
☑ Enable Futures                    ← BUNU AKTİF ET! ⭐
☐ Enable Withdrawals
```

**ÖNEMLİ:**
- ✅ "Enable Reading" aktif olsun
- ✅ "Enable Futures" aktif et
- ❌ "Enable Spot & Margin Trading" kapalı kalsın (güvenlik için)
- ❌ "Enable Withdrawals" kapalı kalsın (güvenlik için)

#### Adım 3: IP Restriction

```
IP access restrictions: 
⚪ Restrict access to trusted IPs only (Recommended)
🔘 Unrestricted (only for API Key with withdrawal access)  ← BUNU SEÇ
```

**"Unrestricted" seçmelisin** çünkü IP'n değişebilir.

#### Adım 4: Kaydet

"Save" tıkla ve 2FA ile onayla.

---

## 🧪 Test Et

Terminalden:

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
source .venv/bin/activate

export BINANCE_API_KEY="3qLjlfUeLyGgtB8p4oKTD6YsP5M8bWb67tUemJRc7YOxuC1hJYI4fWOqupZj1Idb"
export BINANCE_API_SECRET="RBuo1px4L5uF2n7plOtPPoZ0VXWAfULnDwbdzS5WxGfGTXxqGxZrLsBwlu34ONeX"

# Test
python scripts/test_binance_api.py
```

**Beklenen çıktı:**
```
2️⃣ Testing Futures API...
✓ Futures API is accessible!     ← Bu satırı görmelisin
Total Balance: $0                 ← Bakiye 0 olabilir (normal)
```

---

## 🚀 Gerçek Trader Verisi Çek

Futures izni aktif olduktan sonra:

```bash
# Gerçek Binance Futures trader'ları çek
python scripts/discover_with_api_key.py

# Sisteme aktar
python scripts/import_discovered_traders.py

# Monitor başlat
python scripts/run_copy_trader.py monitor
```

---

## 📊 Şu Anki API Key Durumu

| İzin | Durum | Gerekli Mi? |
|------|-------|-------------|
| **Enable Reading** | ✅ Aktif | ✅ Evet |
| **Enable Futures** | ❌ İnaktif | ✅ Evet (trader data için) |
| **Enable Spot Trading** | ❓ ? | ❌ Hayır |
| **Enable Withdrawals** | ❓ ? | ❌ Hayır (GÜVENLİK) |

---

## ⚠️ GÜVENLİK NOTU

API Key'de **SADECE** şu izinler aktif olmalı:
- ✅ **Enable Reading** (veri okuma)
- ✅ **Enable Futures** (futures data okuma)
- ❌ **Enable Spot Trading** (KAPALI - güvenlik)
- ❌ **Enable Withdrawals** (KAPALI - GÜVENLİK!)

Bu şekilde API key **SADECE OKUMA** yapabilir, işlem ve para çekme yapamaz. %100 güvenli!

---

## 🎯 Özet

1. Binance'e git: https://www.binance.com
2. API Management > API key düzenle
3. "Enable Futures" aktif et ✅
4. "Unrestricted" seç
5. Kaydet
6. `python scripts/test_binance_api.py` çalıştır
7. Eğer "✓ Futures API is accessible!" görürsen → Başarılı!

---

**Sonraki adım:** Futures iznini aktif et ve gerçek trader verisi çekmeye başla! 🚀
