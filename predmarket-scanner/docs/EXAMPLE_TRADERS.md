# Örnek Top Binance Futures Traders (Mayıs 2026)

Bu liste, Binance Futures leaderboard'undan alınan örnek başarılı trader UID'lerini içerir.

## Trader UID Nasıl Bulunur?

1. https://www.binance.com/en/futures-activity/leaderboard adresini açın
2. İlgilendiğiniz trader'a tıklayın
3. Adres çubuğundaki URL'yi kopyalayın:
   ```
   https://www.binance.com/en/futures-activity/leaderboard?type=myProfile&encryptedUid=BURASI
   ```
4. `encryptedUid=` kısmından sonraki değer trader'ın UID'sidir

## Örnek Kullanım

```bash
# Örnek trader ekleme
python scripts/add_trader.py add \
  --uid "0C2123F5688F316245836C60A66F8240" \
  --nickname "ExampleTrader" \
  --roi 85.5 \
  --rank 10

# Eklediğiniz traderları görme
python scripts/add_trader.py list-traders

# Position monitoring başlatma
python scripts/run_copy_trader.py monitor --dry-run
```

## CSV Dosyasından Toplu İçe Aktarma

`example_traders.csv` dosyası oluşturun:

```csv
# UID,nickname,roi,rank
0C2123F5688F316245836C60A66F8240,ExampleTrader1,85.5,5
ABC123DEF456,ExampleTrader2,72.3,12
XYZ789UVW012,ExampleTrader3,95.1,2
```

Sonra içe aktarın:

```bash
python scripts/add_trader.py import-uids --file example_traders.csv --format csv
```

## Not

- UID'ler gerçek trader'lardan alınmalıdır
- Leaderboard'da "Position Shared" olarak işaretli traderların pozisyonları görülebilir
- Pozisyon paylaşmayan traderların pozisyonları API'den erişilebilir değildir

## Önerilen Kriterler

**İyi bir copy target için:**
- ✅ ROI > %50
- ✅ Rank < 50 (top 50)
- ✅ Position Shared = True
- ✅ Follower count > 1000 (güvenilirlik göstergesi)
- ✅ Consistent performance (monthly leaderboard'da stabil)

**Kaçınılması gerekenler:**
- ❌ Çok yüksek leverage kullananlar (>20x)
- ❌ Sadece bir coinde işlem yapanlar (diversifiye değil)
- ❌ Yeni çıkmış, track record'u olmayan traders
- ❌ ROI çok yüksek ama trade count çok az (şans faktörü)

## Test İçin Sample Data

Position monitoring'i test etmek için gerçek bir UID eklemelisiniz. 

Leaderboard'dan herhangi bir trader seçip UID'sini alabilirsiniz.
