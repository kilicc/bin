#!/usr/bin/env python3
"""Test Bitget v2 API WITHOUT params"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import httpx
import hmac
import hashlib
import base64
import time
from rich.console import Console
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
    return signature


def test_endpoint(endpoint: str, params: dict, description: str):
    """Test an endpoint"""
    console.print(f"\n[bold cyan]═══ {description} ═══[/bold cyan]")
    console.print(f"[dim]Endpoint: {endpoint}[/dim]")
    console.print(f"[dim]Params: {params}[/dim]")
    
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    
    # Build query string
    query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())]) if params else ""
    
    # Signature
    signature = create_signature(timestamp, method, endpoint, query_string)
    
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
    url = f"https://api.bitget.com{endpoint}"
    
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=30.0)
        
        console.print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('code') == '00000':
                console.print(f"[green]✓ SUCCESS![/green]")
                console.print(f"[dim]Response: {str(data)[:500]}...[/dim]")
                return True
            else:
                console.print(f"[yellow]API Error: {data.get('code')} - {data.get('msg')}[/yellow]")
                console.print(f"[dim]Full: {data}[/dim]")
        else:
            console.print(f"[red]HTTP Error: {response.status_code}[/red]")
            console.print(f"[red]Response: {response.text}[/red]")
            
    except Exception as e:
        console.print(f"[red]Exception: {e}[/red]")
    
    return False


if __name__ == "__main__":
    console.print("[bold]Bitget v2 API Test - Minimal Params[/bold]\n")
    
    if not API_KEY or not API_SECRET or not PASSPHRASE:
        console.print("[red]✗ API credentials missing in .env[/red]")
        sys.exit(1)
    
    results = []
    
    # Test 1: NO params at all
    results.append({
        'test': 'Mix Follower - NO params',
        'success': test_endpoint(
            "/api/v2/copy/mix-follower/query-traders",
            {},
            "Mix Follower Query Traders (NO PARAMS)"
        )
    })
    
    # Test 2: Only pageSize
    results.append({
        'test': 'Mix Follower - pageSize only',
        'success': test_endpoint(
            "/api/v2/copy/mix-follower/query-traders",
            {'pageSize': '10'},
            "Mix Follower Query Traders (pageSize only)"
        )
    })
    
    # Test 3: pageSize + pageNo
    results.append({
        'test': 'Mix Follower - page params',
        'success': test_endpoint(
            "/api/v2/copy/mix-follower/query-traders",
            {'pageSize': '10', 'pageNo': '1'},
            "Mix Follower Query Traders (pageSize + pageNo)"
        )
    })
    
    # Test 4: Spot follower (for comparison)
    results.append({
        'test': 'Spot Follower - NO params',
        'success': test_endpoint(
            "/api/v2/copy/spot-follower/query-traders",
            {},
            "Spot Follower Query Traders (NO PARAMS)"
        )
    })
    
    # Summary
    console.print("\n[bold]═══ SUMMARY ═══[/bold]")
    for result in results:
        status = "✓ PASS" if result['success'] else "✗ FAIL"
        color = "green" if result['success'] else "red"
        console.print(f"[{color}]{status}[/{color}] {result['test']}")
    
    passed = sum(1 for r in results if r['success'])
    console.print(f"\n[bold]Total: {passed}/{len(results)} passed[/bold]")
    
    if passed > 0:
        console.print("\n[green]✓ At least one endpoint works![/green]")
        console.print("[yellow]Note: query-traders returns YOUR followed traders, not all available traders[/yellow]")
    else:
        console.print("\n[red]All tests failed. Possible issues:[/red]")
        console.print("1. You need to manually follow at least one trader first")
        console.print("2. Copy trading feature not enabled for your account")
        console.print("\n[bold]Action required:[/bold]")
        console.print("→ Go to: https://www.bitget.com/copy-trading")
        console.print("→ Manually follow 1-2 successful traders")
        console.print("→ Then re-run this test")
