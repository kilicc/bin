#!/usr/bin/env python3
"""Test Bitget v1 Copy Trading API"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import httpx
import hmac
import hashlib
import base64
import time
from rich.console import Console
from rich import print as rprint
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
    
    console.print(f"[dim]Message: {message}[/dim]")
    
    mac = hmac.new(
        API_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    )
    
    signature = base64.b64encode(mac.digest()).decode()
    console.print(f"[dim]Signature: {signature}[/dim]")
    
    return signature


def test_v1_trader_list():
    """Test v1 traderList endpoint"""
    console.print("\n[bold cyan]═══ Bitget v1 API: traderList ═══[/bold cyan]")
    
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    request_path = "/api/mix/v1/trace/traderList"
    
    # Required params
    params = {
        'sortRule': 'composite',  # Required
        'sortFlag': 'desc',       # Required (asc or desc)
        'pageSize': '20',
        'pageNo': '1'
    }
    
    # Build query string (alphabetically sorted)
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
    
    # Signature
    signature = create_signature(timestamp, method, request_path, query_string)
    
    # Headers
    headers = {
        'ACCESS-KEY': API_KEY,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': PASSPHRASE,
        'Content-Type': 'application/json',
        'locale': 'en-US'
    }
    
    # Request
    url = f"https://api.bitget.com{request_path}"
    
    console.print(f"\n[bold]URL:[/bold] {url}")
    console.print(f"[bold]Params:[/bold] {params}")
    
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=30.0)
        
        console.print(f"\n[bold]Status:[/bold] {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('code') == '00000':
                console.print(f"[green]✓ SUCCESS![/green]")
                
                traders = data.get('data', [])
                console.print(f"\n[bold]Found {len(traders)} traders:[/bold]")
                
                for i, trader in enumerate(traders[:5], 1):  # Show first 5
                    console.print(f"\n[cyan]{i}. {trader.get('traderNickName', 'Unknown')}[/cyan]")
                    console.print(f"   UID: {trader.get('traderUid', 'N/A')}")
                    console.print(f"   Followers: {trader.get('followCount', 0)}/{trader.get('maxFollowCount', 0)}")
                    console.print(f"   Can follow: {trader.get('canTrace', False)}")
                    
                    # Column list (performance metrics)
                    cols = trader.get('columnList', [])
                    if cols:
                        console.print(f"   Metrics:")
                        for col in cols[:3]:  # Show first 3 metrics
                            console.print(f"     - {col.get('columnName', 'N/A')}: {col.get('columnValue', 'N/A')}")
                
                if len(traders) > 5:
                    console.print(f"\n[dim]... and {len(traders) - 5} more traders[/dim]")
                
                return True
            else:
                console.print(f"[red]✗ API Error: {data.get('code')} - {data.get('msg')}[/red]")
                console.print(f"[dim]Full response: {data}[/dim]")
        else:
            console.print(f"[red]✗ HTTP Error: {response.status_code}[/red]")
            console.print(f"[red]Response: {response.text[:500]}[/red]")
            
    except Exception as e:
        console.print(f"[red]✗ Exception: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
    
    return False


def test_current_track():
    """Test current followed traders"""
    console.print("\n[bold cyan]═══ Bitget v1 API: currentTrack ═══[/bold cyan]")
    
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    request_path = "/api/mix/v1/trace/currentTrack"
    
    # No required params
    params = {
        'pageSize': '20',
        'pageNo': '1'
    }
    
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
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
        
        console.print(f"[bold]Status:[/bold] {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('code') == '00000':
                console.print(f"[green]✓ SUCCESS![/green]")
                
                tracking = data.get('data', [])
                console.print(f"\n[bold]Currently following {len(tracking)} traders[/bold]")
                
                if tracking:
                    for i, track in enumerate(tracking, 1):
                        console.print(f"\n[cyan]{i}. Trader UID: {track.get('traderUid', 'N/A')}[/cyan]")
                        console.print(f"   Symbol: {track.get('symbol', 'N/A')}")
                        console.print(f"   Amount: {track.get('trackingAmount', 0)}")
                else:
                    console.print("[yellow]You're not following any traders yet[/yellow]")
                    console.print("[yellow]→ Go to https://www.bitget.com/copy-trading and follow 1-2 traders[/yellow]")
                
                return True
            else:
                console.print(f"[red]✗ API Error: {data.get('code')} - {data.get('msg')}[/red]")
        else:
            console.print(f"[red]✗ HTTP Error: {response.status_code}[/red]")
            console.print(f"[red]Response: {response.text[:500]}[/red]")
            
    except Exception as e:
        console.print(f"[red]✗ Exception: {e}[/red]")
    
    return False


if __name__ == "__main__":
    console.print("[bold]Bitget v1 API Test[/bold]")
    console.print("[dim]Using the CORRECT v1 endpoints[/dim]\n")
    
    if not API_KEY or not API_SECRET or not PASSPHRASE:
        console.print("[red]✗ API credentials missing in .env[/red]")
        sys.exit(1)
    
    # Test 1: Get trader list (public traders)
    test1 = test_v1_trader_list()
    
    # Test 2: Get current followed traders
    test2 = test_current_track()
    
    # Summary
    console.print("\n[bold]═══ SUMMARY ═══[/bold]")
    if test1:
        console.print("[green]✓ v1 API works! We can query traders![/green]")
    if test2:
        console.print("[green]✓ Can check followed traders![/green]")
    
    if test1 and test2:
        console.print("\n[green bold]✓✓✓ BITGET v1 API WORKS![/green bold]")
        console.print("\n[bold]Next step:[/bold]")
        console.print("→ Update bitget_signal_source.py to use v1 API")
        console.print("→ Run: python3 scripts/run_dual_strategy.py run")
