#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆓 ÜCRETSİZ TRADER VERİ TOPLAMA (API KEY GEREKMİYOR!)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tamamen ücretsiz yöntemlerle gerçek Binance Futures trader verisi toplar:
- ✅ Web scraping (Playwright)
- ✅ Binance Public API (BAPI)
- ✅ Trader profilleri
- ✅ Mevcut pozisyonlar
- ✅ Performans geçmişi (ROI timeline)

Kullanım:
    python scripts/collect_free_traders.py [seçenekler]
    
Seçenekler:
    --max-traders N         Maksimum N trader topla (default: 100)
    --no-positions          Pozisyon toplama (sadece profil)
    --no-history            Geçmiş performans toplama
    --output-dir PATH       Çıktı dizini (default: data/real_traders)
    
Örnekler:
    # Tam veri seti (profil + pozisyon + geçmiş)
    python scripts/collect_free_traders.py --max-traders 50
    
    # Sadece profiller (en hızlı)
    python scripts/collect_free_traders.py --max-traders 100 --no-positions --no-history
    
    # Top 20 trader, pozisyonlarla
    python scripts/collect_free_traders.py --max-traders 20
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance_futures_trader.free_trader_sources import main


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  İşlem kullanıcı tarafından durduruldu.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Hata: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
