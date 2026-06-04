#!/usr/bin/env python3
"""Test MY followed traders on Bitget"""
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


def test_my_followed_traders():
    """Test: Takip ettiğim trader'lar"""
    console.print("\n[bold cyan]═══ TAKİP ETTİĞİM TRADER'LAR ═══[/bold cyan]\n")
    
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    request_path = "/api/v2/copy/mix-follower/query-traders"
    
    # NO params (returns MY followed traders)
    params = {}
    query_string = ""
    
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
                console.print(f"[green]✓ SUCCESS![/green]\n")
                
                # Parse response - could be list or dict
                data_content = data.get('data', [])
                
                # Handle different formats
                if isinstance(data_content, dict):
                    result_list = data_content.get('resultList', [])
                elif isinstance(data_content, list):
                    result_list = data_content
                else:
                    result_list = []
                
                if not result_list:
                    console.print("[yellow]Henüz takip ettiğin trader yok[/yellow]")
                    console.print("[dim]Full response:[/dim]")
                    import json
                    console.print(json.dumps(data, indent=2))
                    return False, []
                
                console.print(f"[bold green]🎉 {len(result_list)} trader takip ediyorsun![/bold green]\n")
                
                # Show traders
                table = Table(title="Takip Ettiğim Trader'lar")
                table.add_column("Trader", style="cyan")
                table.add_column("Trader ID", style="dim")
                table.add_column("Followers", style="green")
                table.add_column("Follow Date", style="yellow")
                
                for trader in result_list:
                    name = trader.get('traderName', 'Unknown')
                    trader_id = trader.get('traderId', 'N/A')
                    followers = trader.get('followCount', '0')
                    follow_time = trader.get('followerTime', '0')
                    
                    # Convert timestamp to date
                    try:
                        from datetime import datetime
                        date = datetime.fromtimestamp(int(follow_time) / 1000).strftime('%Y-%m-%d %H:%M')
                    except:
                        date = follow_time
                    
                    table.add_row(name, trader_id[:20] + "...", followers, date)
                
                console.print(table)
                return True, result_list
            else:
                console.print(f"[red]API Error: {data.get('code')} - {data.get('msg')}[/red]")
        else:
            console.print(f"[red]HTTP Error: {response.status_code}[/red]")
            console.print(f"[red]{response.text[:500]}[/red]")
            
    except Exception as e:
        console.print(f"[red]Exception: {e}[/red]")
    
    return False, []


def test_trader_positions(trader_id: str, trader_name: str):
    """Test: Trader'ın pozisyonları"""
    console.print(f"\n[bold cyan]═══ {trader_name} POZİSYONLARI ═══[/bold cyan]\n")
    
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    request_path = "/api/v2/copy/mix-follower/query-current-orders"
    
    # Try different param combinations
    test_cases = [
        ({'traderId': trader_id}, "Only traderId"),
        ({'traderId': trader_id, 'productType': 'USDT-FUTURES'}, "With productType"),
        ({}, "No params (might return all)"),
    ]
    
    for params, desc in test_cases:
        console.print(f"[bold]Test: {desc}[/bold]")
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
                    positions = data.get('data', {}).get('orderList', [])
                    
                    if positions:
                        console.print(f"[green]✓ {len(positions)} pozisyon bulundu![/green]\n")
                        
                        for i, pos in enumerate(positions[:3], 1):
                            console.print(f"[cyan]{i}. {pos.get('symbol', 'N/A')}[/cyan]")
                            console.print(f"   Side: {pos.get('side', 'N/A')}")
                            console.print(f"   Size: {pos.get('size', 'N/A')}")
                            console.print(f"   Entry: ${pos.get('openPriceAvg', '0')}")
                        
                        return True
                    else:
                        console.print("[yellow]Pozisyon yok[/yellow]")
                else:
                    console.print(f"[yellow]API Error: {data.get('code')} - {data.get('msg')}[/yellow]")
            else:
                console.print(f"[red]HTTP Error: {response.status_code}[/red]")
                
        except Exception as e:
            console.print(f"[red]Exception: {e}[/red]")
        
        console.print()
        time.sleep(1)
    
    return False


if __name__ == "__main__":
    # Test 1: My followed traders
    success, traders = test_my_followed_traders()
    
    if success and traders:
        # Test 2: Get positions for first trader
        first_trader = traders[0]
        trader_id = first_trader.get('traderId')
        trader_name = first_trader.get('traderName', 'Unknown')
        
        if trader_id:
            test_trader_positions(trader_id, trader_name)
        
        console.print("\n[bold green]✅ SİSTEM HAZIR![/bold green]")
        console.print("\n[bold]Şimdi sistemi başlat:[/bold]")
        console.print("→ python3 scripts/run_bitget_to_binance.py run")
    else:
        console.print("\n[yellow]Bitget'te trader takip etmelisin:[/yellow]")
        console.print("→ https://www.bitget.com/copy-trading")
