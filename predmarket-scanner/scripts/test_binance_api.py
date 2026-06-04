#!/usr/bin/env python3
"""
Test Binance API connection and find working endpoints
"""

import os
import time
import hmac
import hashlib
from urllib.parse import urlencode
import httpx
from rich.console import Console
from rich.panel import Panel

console = Console()


def generate_signature(params: dict, secret: str) -> str:
    """Generate HMAC SHA256 signature"""
    query_string = urlencode(params)
    return hmac.new(
        secret.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def test_api_key(api_key: str, api_secret: str):
    """Test if API key is valid"""
    console.print(Panel.fit(
        "[bold cyan]🔑 BINANCE API KEY TEST[/bold cyan]\n\n"
        f"API Key: {api_key[:20]}...\n"
        f"Secret: {api_secret[:20]}...",
        border_style="cyan"
    ))
    
    client = httpx.Client(timeout=30.0)
    
    # Test 1: Account Status (simplest test)
    console.print("\n[cyan]1️⃣ Testing Account Status...[/cyan]")
    try:
        params = {
            'timestamp': int(time.time() * 1000),
            'recvWindow': 60000
        }
        params['signature'] = generate_signature(params, api_secret)
        
        headers = {'X-MBX-APIKEY': api_key}
        url = "https://api.binance.com/api/v3/account"
        
        response = client.get(url, params=params, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            console.print(f"[green]✓ API Key is VALID![/green]")
            console.print(f"[dim]Account Type: {data.get('accountType', 'N/A')}[/dim]")
            console.print(f"[dim]Can Trade: {data.get('canTrade', False)}[/dim]")
            return True
        else:
            console.print(f"[red]✗ Error {response.status_code}: {response.text}[/red]")
            
            if "Invalid API-key" in response.text:
                console.print("\n[yellow]💡 API Key sorunu:[/yellow]")
                console.print("  1. API key doğru kopyalandı mı kontrol et")
                console.print("  2. Binance'de API key'in 'Enabled' olduğundan emin ol")
                console.print("  3. IP restriction varsa kaldır veya IP'ni ekle")
            
            return False
    
    except Exception as e:
        console.print(f"[red]✗ Exception: {e}[/red]")
        return False
    
    finally:
        client.close()


def test_futures_api(api_key: str, api_secret: str):
    """Test Futures API"""
    console.print("\n[cyan]2️⃣ Testing Futures API...[/cyan]")
    
    client = httpx.Client(timeout=30.0)
    
    try:
        params = {
            'timestamp': int(time.time() * 1000),
            'recvWindow': 60000
        }
        params['signature'] = generate_signature(params, api_secret)
        
        headers = {'X-MBX-APIKEY': api_key}
        
        # Futures account endpoint
        url = "https://fapi.binance.com/fapi/v2/account"
        
        response = client.get(url, params=params, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            console.print(f"[green]✓ Futures API is accessible![/green]")
            console.print(f"[dim]Total Balance: ${data.get('totalWalletBalance', 0)}[/dim]")
            return True
        else:
            console.print(f"[yellow]⚠️  Futures API: {response.status_code}[/yellow]")
            console.print(f"[dim]{response.text[:200]}[/dim]")
            return False
    
    except Exception as e:
        console.print(f"[yellow]⚠️  Futures API error: {e}[/yellow]")
        return False
    
    finally:
        client.close()


def get_public_leaderboard():
    """Try to get public leaderboard data (no auth)"""
    console.print("\n[cyan]3️⃣ Testing Public Leaderboard (no auth)...[/cyan]")
    
    client = httpx.Client(timeout=30.0)
    
    # Try different public endpoints
    endpoints = [
        "https://www.binance.com/bapi/futures/v1/public/future/leaderboard/getLeaderboardRank",
        "https://www.binance.com/bapi/copyTrading/v1/public/lead-trader/list",
        "https://fapi.binance.com/fapi/v1/ticker/24hr",  # Market data
    ]
    
    for url in endpoints:
        try:
            console.print(f"[dim]Trying: {url.split('/')[3:]}[/dim]")
            
            if 'bapi' in url:
                # BAPI endpoints need POST with payload
                response = client.post(url, json={
                    "isShared": True,
                    "periodType": "ALL",
                    "statisticsType": "ROI",
                    "tradeType": "PERPETUAL"
                })
            else:
                response = client.get(url)
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    console.print(f"[green]✓ Found {len(data)} items from public endpoint[/green]")
                    return data
                elif isinstance(data, dict) and data.get('success'):
                    console.print(f"[green]✓ Public endpoint works![/green]")
                    return data.get('data', [])
        
        except Exception as e:
            console.print(f"[dim]  Failed: {e}[/dim]")
            continue
    
    console.print("[yellow]⚠️  No public leaderboard found[/yellow]")
    client.close()
    return None


def main():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    
    if not api_key or not api_secret:
        console.print("[red]❌ API keys not set![/red]")
        console.print("\nSet them with:")
        console.print('  export BINANCE_API_KEY="your_key"')
        console.print('  export BINANCE_API_SECRET="your_secret"')
        return
    
    # Test API key validity
    is_valid = test_api_key(api_key, api_secret)
    
    if not is_valid:
        console.print("\n[red]❌ API Key geçersiz veya sorunlu[/red]")
        console.print("\n[yellow]Kontrol listesi:[/yellow]")
        console.print("  1. Binance'de API Management'a git")
        console.print("  2. API key'in 'Status: Enabled' olduğunu kontrol et")
        console.print("  3. 'Edit' tıkla > 'Enable Reading' aktif mi?")
        console.print("  4. IP Restriction varsa 'Unrestricted' seç")
        console.print("  5. API key ve secret'i tekrar kopyala")
        return
    
    # Test Futures API
    test_futures_api(api_key, api_secret)
    
    # Try public endpoints
    get_public_leaderboard()
    
    console.print("\n" + "="*60)
    console.print("[bold green]✅ TEST TAMAMLANDI[/bold green]")
    console.print("="*60 + "\n")


if __name__ == "__main__":
    main()
