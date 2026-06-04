# 🔍 GERÇEK TRADER UID'LERİNİ BULMA REHBERİ

## 📋 Problem

Playwright web scraping şu anda çalışmıyor ve test için kullandığımız örnek UID'ler geçerli değil.

## ✅ Çözüm: Manuel UID Bulma (5 Dakika)

### Adım 1: Binance Leaderboard'a Git

Tarayıcını aç ve şu adrese git:
```
https://www.binance.com/en/futures-activity/leaderboard
```

### Adım 2: Trader Seç

1. Sayfada **Top Traders** listesini gör
2. Filtreler:
   - **Time Period**: `ALL` veya `MONTHLY` seç
   - **Stat Type**: `ROI` seç (en yüksek kazançlılar)
   - **Position Sharing**: `All` veya `Shared` seç (pozisyon paylaşanlar önemli!)

3. Bir trader'a tıkla (örn. en yüksek ROI'li)

### Adım 3: UID'yi Kopyala

Trader profiline gittiğinde URL şöyle görünür:
```
https://www.binance.com/en/futures-activity/leaderboard?type=myProfile&encryptedUid=3AFFCB67ED4F1D1D8437BA17F4E8E5ED
```

**`encryptedUid=`** kısmından sonraki değeri kopyala:
```
3AFFCB67ED4F1D1D8437BA17F4E8E5ED
```

Bu trader'ın **gerçek UID'si**!

### Adım 4: Sisteme Ekle

Terminal'de:

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
source .venv/bin/activate

# UID'yi ekle (yukarıda kopyaladığın)
python scripts/add_trader.py add 3AFFCB67ED4F1D1D8437BA17F4E8E5ED
```

### Adım 5: Daha Fazla Trader Ekle

1. Leaderboard sayfasına dön
2. Başka bir trader seç
3. UID'yi kopyala
4. `python scripts/add_trader.py add <UID>` ile ekle
5. 5-10 trader ekle

---

## 🎯 İyi Trader Seçim Kriterleri

Leaderboard'da bu özelliklere dikkat et:

| Özellik | Önerilen Değer | Neden Önemli |
|---------|----------------|--------------|
| **ROI** | +50% veya üzeri | Yüksek kazanç |
| **Win Rate** | %55+ | Başarılı işlem oranı |
| **Followers** | 1000+ | Güvenilirlik göstergesi |
| **Position Sharing** | ✅ | Pozisyonlarını görmen gerekli |
| **Days Active** | 90+ gün | Deneyimli trader |

---

## 📊 Örnek: İyi Bir Trader Profili

```
Nickname: CryptoMaster
ROI: +127.5%
Win Rate: 58.3%
Followers: 15,420
Position Sharing: ✅ Yes
Days Active: 245

URL: ...&encryptedUid=A1B2C3D4E5F6...
          UID: ^^^^^^^^^^^^^^^^^ (Bunu kopyala)
```

---

## 🚀 Hızlı Başlangıç (5 Dakika)

```bash
# 1. Binance Leaderboard'a git
open https://www.binance.com/en/futures-activity/leaderboard

# 2. Top 5 trader'ın UID'sini bul ve not et

# 3. Terminal'de sisteme ekle
cd /Users/macbook/Downloads/testtt/predmarket-scanner
source .venv/bin/activate

# Her UID için tekrarla
python scripts/add_trader.py add <UID_1>
python scripts/add_trader.py add <UID_2>
python scripts/add_trader.py add <UID_3>
python scripts/add_trader.py add <UID_4>
python scripts/add_trader.py add <UID_5>

# 4. Kontrol et
python scripts/add_trader.py list

# 5. Monitor başlat
python scripts/run_copy_trader.py monitor
```

---

## 💡 İpucu: Toplu Ekleme

Birden fazla UID'yi bir dosyaya yazıp toplu ekleyebilirsin:

```bash
# trader_uids.txt dosyası oluştur
cat > trader_uids.txt << 'EOF'
3AFFCB67ED4F1D1D8437BA17F4E8E5ED
0C2123F5688F316245836C60A66F8240
A5B7C9D1E3F5A7B9C1D3E5F7A9B1C3D5
EOF

# Toplu ekle
while read uid; do
    python scripts/add_trader.py add "$uid"
done < trader_uids.txt
```

---

## ❓ SSS

**S: Kaç trader eklemeliyim?**  
C: Başlangıç için 5-10 trader yeterli. Daha sonra başarılı olanları tutup, başarısızları kaldırabilirsin.

**S: Position Sharing kapalı olan traderları ekleyebilir miyim?**  
C: Hayır! Pozisyonlarını göremezsen copy trading yapamazsın. Sadece `Position Sharing: Yes` olanları ekle.

**S: UID'yi nasıl anlarım geçerli mi?**  
C: Add komutu çalıştırdığında sistem kontrol eder. Geçersizse hata verir.

**S: Web scraping ne zaman çalışacak?**  
C: Playwright kurulumu düzeldiğinde otomatik olarak çalışacak. Şimdilik manuel yöntem daha hızlı.

---

## 🔗 Yararlı Linkler

- [Binance Futures Leaderboard](https://www.binance.com/en/futures-activity/leaderboard)
- [ROI Sıralaması](https://www.binance.com/en/futures-activity/leaderboard?statisticsType=ROI)
- [Pozisyon Paylaşanlar](https://www.binance.com/en/futures-activity/leaderboard?isShared=true)

---

## ✅ Başarı Kontrolü

Sistem çalışıyor mu kontrol et:

```bash
# Eklediğin traderları listele
python scripts/add_trader.py list

# En az 1 trader görmeli ve "Active: True" olmalı
```

Eğer liste doluysa: **✅ Başarılı! Monitor'ü başlatabilirsin:**

```bash
python scripts/run_copy_trader.py monitor
```

---

**🎯 İlk adım: Binance Leaderboard'a git ve gerçek trader UID'lerini bul!**

https://www.binance.com/en/futures-activity/leaderboard
