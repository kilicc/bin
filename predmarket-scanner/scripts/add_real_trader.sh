#!/bin/bash
# Gerçek Binance Futures Trader Ekleme Yardımcısı

echo "════════════════════════════════════════════════════════"
echo "  GERÇEK BİNANCE FUTURES TRADER EKLEME"
echo "════════════════════════════════════════════════════════"
echo ""
echo "1. Tarayıcınızda şu sayfayı açın:"
echo "   https://www.binance.com/en/futures-activity/leaderboard"
echo ""
echo "2. ROI'ye göre sıralayın (ROI tab)"
echo ""
echo "3. Top 5-10 trader'dan birini seçin"
echo ""
echo "4. Trader'a tıklayınca URL'de şöyle görünecek:"
echo "   ...encryptedUid=ABC123XYZ456..."
echo ""
echo "5. Bu UID'yi kopyalayın ve aşağıya yapıştırın"
echo ""
echo "════════════════════════════════════════════════════════"
echo ""

# Activate venv
cd /Users/macbook/Downloads/testtt/predmarket-scanner
source .venv/bin/activate

# Interactive trader addition
read -p "Trader UID'si (örn: 0C2123F5688F...): " uid
read -p "Trader Nickname (örn: CryptoKing): " nickname
read -p "ROI % (örn: 85.5): " roi
read -p "Rank (örn: 5): " rank

echo ""
echo "📝 Trader ekleniyor..."

python scripts/add_trader.py add \
  --uid "$uid" \
  --nickname "$nickname" \
  --roi "$roi" \
  --rank "$rank"

echo ""
echo "✅ Trader eklendi!"
echo ""
echo "📊 Güncel trader listesi:"
python scripts/add_trader.py list-traders

echo ""
echo "════════════════════════════════════════════════════════"
echo "🚀 Copy trading'i başlatmak için:"
echo "   python scripts/run_copy_trader.py monitor --dry-run"
echo "════════════════════════════════════════════════════════"
