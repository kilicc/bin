# Bitget API Setup Guide

## 🎯 Amaç
Bitget'ten başarılı trader'ları otomatik keşfetmek ve pozisyonlarını Binance Futures'ta aynalayabilmek için Bitget API key'e ihtiyacımız var.

---

## 📋 Adım Adım Setup

### 1️⃣ Bitget Hesabı Oluştur (Eğer yoksa)
- Git: https://www.bitget.com/register
- Email + Şifre ile kayıt ol
- Email doğrulamasını yap
- **KYC gerekli değil** (API okuma için)

---

### 2️⃣ API Key Oluştur

#### A. API Yönetim Sayfasına Git
- Git: https://www.bitget.com/account/newapi
- Ya da: Profil → API Management

#### B. Yeni API Key Oluştur
1. **"Create API"** butonuna tıkla
2. **API Passphrase** belirle (güçlü bir şifre, sonra lazım!)
   - Örnek: `MySecurePass2024!`
   - **NOT:** Bu passphrase'i kaydet, tekrar göremezsin!

#### C. İzinler (Permissions) Seç
✅ **Read** (Zorunlu)  
✅ **Copy Trading** (Trader listesi için)  
✅ **Futures** (Pozisyon verileri için)  

❌ **Trade** (GEREKSİZ - biz sadece okuyacağız)  
❌ **Withdraw** (ASLA AKTİF ETME!)

#### D. IP Whitelist (Opsiyonel)
- Eğer sabit IP'n varsa ekle
- Yoksa boş bırak (her IP'den erişim)

#### E. API Key'i Kaydet
API oluşturduktan sonra şunları göreceksin:
- **API Key**: `bg_abc123...`
- **Secret Key**: `def456...`
- **Passphrase**: Daha önce belirlediğin

**🚨 UYARI:** Secret Key'i bir daha göremezsin! Hemen kaydet.

---

### 3️⃣ .env Dosyasına Ekle

```bash
# Open .env file
nano /Users/macbook/Downloads/testtt/predmarket-scanner/.env
```

Aşağıdaki değerleri doldur:

```env
BITGET_API_KEY=bg_abc123xyz...
BITGET_SECRET_KEY=def456uvw...
BITGET_PASSPHRASE=MySecurePass2024!
```

Kaydet ve çık (CTRL+O, Enter, CTRL+X)

---

### 4️⃣ Test Et

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
python3 scripts/test_bitget_public.py
```

**Beklenen Sonuç:**

```
✓ Public endpoint works!
✓ Account endpoint works! Signature is CORRECT!
✓ Copy trading endpoint works!
✓✓✓ ALL TESTS PASSED!
```

---

## 🔧 Sorun Giderme

### "API credentials missing in .env"
- `.env` dosyasındaki değerleri kontrol et
- `your_api_key_here` gibi placeholder'ları sildin mi?

### "sign signature error" (40009)
- **Passphrase yanlış**: Bitget'te oluştururken belirlediğin passphrase'i kullan
- **Secret key yanlış**: Kopyalarken boşluk/satır sonu ekleme
- **İzinler eksik**: API key'de "Copy Trading" ve "Futures" izinleri olmalı

### "API key invalid" (40006)
- API key'i doğru kopyaladığını kontrol et
- Bitget'te API key'i silip yeniden oluştur

### "IP restricted" (40007)
- Bitget API settings'te IP whitelist'i kaldır
- Ya da mevcut IP'ni ekle

---

## ✅ Test Sonrası

Tüm testler başarılı olduktan sonra:

```bash
# Dual strategy'yi başlat
python3 scripts/run_dual_strategy.py run
```

Bu şunları yapacak:
1. **Main Strategy** (5000 USDT) → Binance Futures demo hesap
2. **Copy Trading** (5000 USDC) → Bitget'ten trader sinyalleri alıp Binance'de aynalayacak

---

## 🎓 Ek Bilgiler

### Bitget API Rate Limits
- **Public endpoints**: 20 req/sec
- **Private endpoints**: 10 req/sec
- **Copy trading endpoints**: 5 req/sec

Kodumuz her 60 saniyede bir trader pozisyonlarını kontrol ediyor, rate limit'e takılmayız.

### API Key Güvenliği
- ✅ Sadece **Read** izinleri ver
- ✅ IP whitelist kullan (mümkünse)
- ❌ **Trade** veya **Withdraw** izni VERME
- ❌ API key'i GitHub'a pushlama
- ❌ Public yerlerde paylaşma

---

## 📞 Yardım

Sorun yaşıyorsan:
1. `test_bitget_public.py` çıktısını kontrol et
2. Bitget API dokümantasyonu: https://www.bitget.com/api-doc/common/intro
3. Hata kodları: https://www.bitget.com/api-doc/common/error-code

---

**Hazır mısın?** Bitget'e git ve API key'ini oluştur! 🚀
