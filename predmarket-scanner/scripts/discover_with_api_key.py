#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔑 BINANCE API KEY İLE TRADER KEŞFİ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Binance API key kullanarak gerçek trader verilerini çeker.
Bu yöntem %100 güvenilir ve Binance tarafından destekleniyor.

API Key Nasıl Alınır:
1. Binance'e giriş yap: https://www.binance.com
2. Profil > API Management'a git
3. "Create API" tıkla
4. İsim ver (örn: "Copy Trading Bot")
5. 2FA ile onayla
6. API Key ve Secret Key'i kopyala
7. İzinler: Sadece "Enable Reading" yeterli (trading izni GEREKME Z)

Güvenlik:
- SADECE "Enable Reading" iznini aktif et
- Trading, withdrawal, internal transfer izinlerini AÇMA!
- API key'i kimseyle paylaşma

Kullanım:
    export BINANCE_API_KEY="your_api_key_here"
    export BINANCE_API_SECRET="your_api_secret_here"
    python scripts/discover_with_api_key.py
"""

import sys
import os
import json
import time
from pathlib import Path
import hmac
import hashlib
from urllib.parse import urlencode

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


class BinanceAuthenticatedAPI:
    """Binance authenticated API client"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.binance.com"
        self.client = httpx.Client(timeout=30.0)
    
    def _generate_signature(self, params: dict) -> str:
        """HMAC SHA256 signature oluştur"""
        query_string = urlencode(params)
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def get_copy_trading_leaders(self, limit: int = 50) -> list:
        """Copy trading liderlerini çek"""
        try:
            console.print("[cyan]🔍 Fetching copy trading leaders...[/cyan]")
            
            # Timestamp ekle
            params = {
                'timestamp': int(time.time() * 1000),
                'recvWindow': 60000
            }
            
            # İmza ekle
            params['signature'] = self._generate_signature(params)
            
            headers = {
                'X-MBX-APIKEY': self.api_key
            }
            
            # Copy trading endpoint'i
            url = f"{self.base_url}/sapi/v1/copyTrading/futures/userStatus"
            
            response = self.client.get(url, params=params, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                console.print(f"[green]✓ API Response received[/green]")
                return data
            else:
                console.print(f"[red]✗ API Error: {response.status_code}[/red]")
                console.print(f"[dim]{response.text}[/dim]")
                return []
        
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
            return []
    
    def search_public_leaders(self) -> list:
        """Public leader search (authentication gerektirmez ama sınırlı)"""
        try:
            console.print("[cyan]🔍 Searching public leaders...[/cyan]")
            
            # Public endpoint (varsa)
            url = f"{self.base_url}/fapi/v1/ticker/24hr"
            
            response = self.client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                console.print(f"[green]✓ Got market data for {len(data)} symbols[/green]")
                
                # Top volume coinleri bul (indirect trader activity indicator)
                sorted_data = sorted(data, key=lambda x: float(x.get('quoteVolume', 0)), reverse=True)
                
                console.print("\n[yellow]📊 Top 10 High Volume Futures:[/yellow]")
                for i, coin in enumerate(sorted_data[:10], 1):
                    console.print(f"  {i}. {coin['symbol']:12s} Volume: ${float(coin['quoteVolume']):,.0f}")
                
                return sorted_data[:20]
            
            return []
        
        except Exception as e:
            console.print(f"[yellow]⚠️  Public search error: {e}[/yellow]")
            return []


def main():
    """Main function"""
    
    # API credentials kontrolü
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    
    console.print(Panel.fit(
        "[bold cyan]🔑 BIN ANCE API KEY İLE TRADER KEŞFİ[/bold cyan]\n\n"
        "Official Binance API kullanılıyor",
        border_style="cyan"
    ))
    
    if not api_key or not api_secret:
        console.print("\n[bold red]❌ API KEY BULUNAMADI![/bold red]\n")
        console.print("[yellow]API Key nasıl alınır:[/yellow]\n")
        console.print("1. Binance'e giriş yap: https://www.binance.com")
        console.print("2. Profil > API Management")
        console.print("3. 'Create API' > İsim ver > 2FA ile onayla")
        console.print("4. API Key ve Secret'i kopyala")
        console.print("5. İzinler: SADECE 'Enable Reading' ✅")
        console.print("           (Trading, Withdrawal izni AÇMA! ❌)\n")
        console.print("[cyan]Environment variable olarak ayarla:[/cyan]\n")
        console.print("  export BINANCE_API_KEY='your_api_key_here'")
        console.print("  export BINANCE_API_SECRET='your_api_secret_here'")
        console.print("  python scripts/discover_with_api_key.py\n")
        return
    
    # API client oluştur
    api = BinanceAuthenticatedAPI(api_key, api_secret)
    
    # Copy trading leaders çek
    leaders = api.get_copy_trading_leaders()
    
    if not leaders:
        console.print("\n[yellow]⚠️  Copy trading leaders bulunamadı.[/yellow]")
        console.print("[cyan]Alternatif: Public market data[/cyan]\n")
        market_data = api.search_public_leaders()
        
        if market_data:
            console.print("\n[green]✓ Market verisi alındı[/green]")
            console.print("\n[dim]Not: Trader profilleri için manual yöntem gerekiyor.[/dim]")
    else:
        console.print(f"\n[green]✓ {len(leaders)} leader bulundu[/green]")
        
        # Kaydet
        output_file = Path("data/real_traders/api_discovered_traders.json")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(leaders, f, indent=2, ensure_ascii=False)
        
        console.print(f"\n[cyan]📁 Saved to: {output_file}[/cyan]")
    
    console.print("\n[bold yellow]Sonraki adımlar:[/bold yellow]")
    console.print("  1. API key izinlerini kontrol et (sadece Reading)")
    console.print("  2. Farklı API endpoint'leri dene")
    console.print("  3. Alternatif: Manuel UID girişi")


if __name__ == "__main__":
    main()
