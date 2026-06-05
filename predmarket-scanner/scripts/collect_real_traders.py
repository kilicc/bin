#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 GERÇEK TRADER VERİ TOPLAMA CLI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Kullanım:
    python scripts/collect_real_traders.py [seçenekler]
    
Seçenekler:
    --max-traders N         Maksimum N trader topla (default: 100)
    --no-positions          Pozisyon toplama (sadece profil)
    --data-dir PATH         Veri dizini (default: data/real_traders)
    --apify-token TOKEN     Apify API token (veya APIFY_API_TOKEN env var)
    
Örnekler:
    # 100 trader topla (pozisyonlarla)
    python scripts/collect_real_traders.py --max-traders 100
    
    # Sadece profilleri topla (hızlı)
    python scripts/collect_real_traders.py --max-traders 50 --no-positions
    
    # Apify token ile
    export APIFY_API_TOKEN="your_token_here"
    python scripts/collect_real_traders.py
"""

import sys
import os
import asyncio

# Proje kökünü ekle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance_futures_trader.real_trader_collector import main


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  İşlem kullanıcı tarafından durduruldu.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Hata: {e}")
        sys.exit(1)
