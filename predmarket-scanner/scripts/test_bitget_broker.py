#!/usr/bin/env python3
"""Test Bitget BROKER endpoint for public traders"""
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

console = Console()
load_dotenv()

API_KEY = os.getenv('BITGET_API_KEY', '')
API_SECRET = os.getenv('BITGET_SECRET_KEY', '')
PASSPHRASE = os.getenv('BITGET_PASSPHRASE', '')


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


def test_broker_traders():
    """Test broker endpoint for public traders"""
    console.print("\n[bold cyan]═══ Bitget BROKER: Query Public Traders ═══[/bold cyan]")
    
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    request_path = "/api/v2/copy/mix-broker/query-traders"
    
    # Try different params
    test_cases = [
        ({}, "NO params"),
        ({'pageSize': '20'}, "pageSize only"),
        ({'pageSize': '20', 'productType': 'USDT-FUTURES'}, "with productType"),
    ]
    
    for params, desc in test_cases:
        console.print(f"\n[bold]Test: {desc}[/bold]")
        console.print(f"[dim]Params: {params}[/dim]")
        
        query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())]) if params else ""
        signature = create_signature(timestamp, method, request_path, query_string)
        
        headers = {
            'ACCESS-KEY': API_KEY,
            'ACCESS-SIGN': signature,
            'ACCESS-TIMESTAMP': timestamp,
            'ACCESS-PASSPHRASE': PASSPHRASE,
            'Content-Type': 'application/json',
            'locale': 'en-US'
        }
        
        url = f"https://api.bitget.com{request_path}"
        
        try:
            response = httpx.get(url, params=params, headers=headers, timeout=30.0)
            
            console.print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('code') == '00000':
                    console.print(f"[green]✓ SUCCESS![/green]")
                    
                    traders = data.get('data', [])
                    console.print(f"[bold]Found {len(traders)} traders[/bold]")
                    
                    # DEBUG: Show full first trader
                    if traders:
                        console.print("\n[bold]First trader (full data):[/bold]")
                        import json
                        console.print(json.dumps(traders[0], indent=2))
                    
                    if traders:
                        # Show first 5 traders
                        table = Table(title="Top Traders")
                        table.add_column("Nickname", style="cyan")
                        table.add_column("UID", style="dim")
                        table.add_column("Followers", style="green")
                        table.add_column("ROI", style="yellow")
                        
                        for trader in traders[:5]:
                            nickname = trader.get('traderNickName', 'Unknown')
                            uid = str(trader.get('traderUid', 'N/A'))[:20]
                            followers = str(trader.get('followCount', 0))
                            roi = str(trader.get('roi', 'N/A'))
                            
                            table.add_row(nickname, uid, followers, roi)
                        
                        console.print(table)
                        return True
                    else:
                        console.print("[yellow]Empty result[/yellow]")
                else:
                    console.print(f"[yellow]API Error: {data.get('code')} - {data.get('msg')}[/yellow]")
            else:
                console.print(f"[red]HTTP Error: {response.status_code}[/red]")
                console.print(f"[red]{response.text[:300]}[/red]")
                
        except Exception as e:
            console.print(f"[red]Exception: {e}[/red]")
        
        time.sleep(1)  # Rate limit
    
    return False


if __name__ == "__main__":
    console.print("[bold]Bitget BROKER API Test[/bold]")
    console.print("[dim]Testing public trader discovery[/dim]\n")
    
    if not API_KEY or not API_SECRET or not PASSPHRASE:
        console.print("[red]✗ API credentials missing in .env[/red]")
        sys.exit(1)
    
    success = test_broker_traders()
    
    if success:
        console.print("\n[green bold]✓✓✓ PUBLIC TRADER DISCOVERY WORKS![/green bold]")
        console.print("\n[bold]Next steps:[/bold]")
        console.print("1. Update bitget_signal_source.py to use BROKER endpoint")
        console.print("2. Run: python3 scripts/run_dual_strategy.py run")
    else:
        console.print("\n[red]Broker endpoint didn't work either[/red]")
        console.print("\n[yellow]FALLBACK PLAN:[/yellow]")
        console.print("1. Go to: https://www.bitget.com/copy-trading")
        console.print("2. Manually follow 2-3 successful traders")
        console.print("3. Use follower/query-traders endpoint to get their data")
        console.print("4. System will mirror their positions to Binance")
