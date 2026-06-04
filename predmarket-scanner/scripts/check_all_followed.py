#!/usr/bin/env python3
"""Check ALL followed traders (Spot + Futures)"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import httpx
import hmac
import hashlib
import base64
import time
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv
import json

console = Console()
load_dotenv()

API_KEY = os.getenv('BITGET_API_KEY')
API_SECRET = os.getenv('BITGET_SECRET_KEY')
PASSPHRASE = os.getenv('BITGET_PASSPHRASE')


def create_signature(timestamp: str, method: str, request_path: str, query_string: str = "", body: str = "") -> str:
    """Create Bitget signature"""
    if query_string:
        message = timestamp + method + request_path + "?" + query_string + body
    else:
        message = timestamp + method + request_path + body
    
    mac = hmac.new(
        API_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    )
    
    return base64.b64encode(mac.digest()).decode()


def test_endpoint(endpoint: str, description: str):
    """Test an endpoint"""
    console.print(f"\n[bold cyan]═══ {description} ═══[/bold cyan]")
    
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    
    signature = create_signature(timestamp, method, endpoint, "")
    
    headers = {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': PASSPHRASE,
        'Content-Type': 'application/json',
        'locale': 'en-US'
    }
    
    url = f"https://api.bitget.com{endpoint}"
    
    try:
        response = httpx.get(url, headers=headers, timeout=30.0)
        
        console.print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('code') == '00000':
                result = data.get('data', [])
                
                if result:
                    console.print(f"[green]✓ {len(result) if isinstance(result, list) else 'Data'} found![/green]")
                    console.print(json.dumps(data, indent=2)[:500])
                    return True
                else:
                    console.print("[yellow]Empty result[/yellow]")
            else:
                console.print(f"[yellow]API Error: {data.get('code')} - {data.get('msg')}[/yellow]")
        else:
            console.print(f"[red]HTTP {response.status_code}: {response.text[:200]}[/red]")
            
    except Exception as e:
        console.print(f"[red]Exception: {e}[/red]")
    
    return False


if __name__ == "__main__":
    console.print("[bold]Bitget Takip Kontrolü - Tüm Endpoint'ler[/bold]\n")
    
    endpoints = [
        ("/api/v2/copy/mix-follower/query-traders", "MIX (Futures) - My Followed Traders"),
        ("/api/v2/copy/spot-follower/query-traders", "SPOT - My Followed Traders"),
        ("/api/v2/copy/mix-follower/query-settings", "MIX - Follower Settings"),
        ("/api/v2/copy/spot-follower/query-settings", "SPOT - Follower Settings"),
    ]
    
    results = {}
    for endpoint, desc in endpoints:
        results[desc] = test_endpoint(endpoint, desc)
        time.sleep(1)
    
    # Summary
    console.print("\n[bold]═══ ÖZET ═══[/bold]")
    for desc, success in results.items():
        status = "[green]✓[/green]" if success else "[red]✗[/red]"
        console.print(f"{status} {desc}")
    
    if not any(results.values()):
        console.print("\n[yellow]⚠️  Henüz hiç trader takip etmemişsin![/yellow]")
        console.print("\n[bold]Çözüm:[/bold]")
        console.print("1. Git: https://www.bitget.com/copy-trading")
        console.print("2. Futures veya Spot sekmesinden bir trader seç")
        console.print("3. 'Follow' butonuna tıkla")
        console.print("4. En az 10 USDT ayır")
        console.print("5. Bu script'i tekrar çalıştır")
