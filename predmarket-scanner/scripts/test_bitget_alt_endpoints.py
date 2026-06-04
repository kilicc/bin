#!/usr/bin/env python3
"""Test alternative Bitget Copy Trading endpoints"""
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


def test_endpoint(endpoint: str, params: dict, description: str):
    """Test a Bitget endpoint"""
    console.print(f"\n[bold cyan]Testing: {description}[/bold cyan]")
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
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '00000':
                console.print(f"[green]✓ SUCCESS[/green]")
                console.print(f"[dim]Response: {str(data)[:200]}...[/dim]")
                return True
            else:
                console.print(f"[yellow]✗ API Error: {data.get('code')} - {data.get('msg')}[/yellow]")
        else:
            console.print(f"[red]✗ HTTP {response.status_code}: {response.text[:200]}[/red]")
            
    except Exception as e:
        console.print(f"[red]✗ Exception: {e}[/red]")
    
    return False


if __name__ == "__main__":
    console.print("[bold]Bitget Copy Trading Alternative Endpoints Test[/bold]\n")
    
    if not API_KEY or not API_SECRET or not PASSPHRASE:
        console.print("[red]✗ API credentials missing in .env[/red]")
        sys.exit(1)
    
    results = []
    
    # Test 1: Original endpoint with different params
    results.append({
        'test': 'Original (USDT-FUTURES)',
        'success': test_endpoint(
            "/api/v2/copy/mix-follower/query-traders",
            {'productType': 'USDT-FUTURES', 'sortBy': 'roi', 'pageSize': '50'},
            "Original with USDT-FUTURES"
        )
    })
    
    # Test 2: Without sortBy
    results.append({
        'test': 'Without sortBy',
        'success': test_endpoint(
            "/api/v2/copy/mix-follower/query-traders",
            {'productType': 'USDT-FUTURES', 'pageSize': '50'},
            "Without sortBy parameter"
        )
    })
    
    # Test 3: Minimal params
    results.append({
        'test': 'Minimal params',
        'success': test_endpoint(
            "/api/v2/copy/mix-follower/query-traders",
            {'productType': 'USDT-FUTURES'},
            "Only productType"
        )
    })
    
    # Test 4: No params at all
    results.append({
        'test': 'No params',
        'success': test_endpoint(
            "/api/v2/copy/mix-follower/query-traders",
            {},
            "No parameters"
        )
    })
    
    # Test 5: Current followed traders (different endpoint)
    results.append({
        'test': 'Current followed',
        'success': test_endpoint(
            "/api/v2/copy/mix-follower/current-track-traders",
            {'productType': 'USDT-FUTURES'},
            "Current followed traders"
        )
    })
    
    # Test 6: Query history (v1 API)
    results.append({
        'test': 'Query history (v1)',
        'success': test_endpoint(
            "/api/mix/v1/copy/query-history-traders",
            {'pageSize': '50'},
            "Query history traders (v1)"
        )
    })
    
    # Test 7: Query settings
    results.append({
        'test': 'Query settings',
        'success': test_endpoint(
            "/api/v2/copy/mix-follower/query-settings",
            {},
            "Query follower settings"
        )
    })
    
    # Summary
    console.print("\n[bold]═══ TEST SUMMARY ═══[/bold]")
    table = Table()
    table.add_column("Test", style="cyan")
    table.add_column("Result", style="green")
    
    for result in results:
        status = "✓ PASS" if result['success'] else "✗ FAIL"
        color = "green" if result['success'] else "red"
        table.add_row(result['test'], f"[{color}]{status}[/{color}]")
    
    console.print(table)
    
    # Recommendation
    passed = sum(1 for r in results if r['success'])
    console.print(f"\n[bold]Passed: {passed}/{len(results)}[/bold]")
    
    if passed > 0:
        console.print("\n[green]✓ At least one endpoint works! Check the results above.[/green]")
    else:
        console.print("\n[red]✗ All copy trading endpoints failed.[/red]")
        console.print("[yellow]Possible causes:[/yellow]")
        console.print("1. API key doesn't have 'Copy Trading' permission")
        console.print("2. You need to manually follow at least one trader first")
        console.print("3. Copy trading feature not enabled for your account")
        console.print("\n[bold]Next steps:[/bold]")
        console.print("→ Go to: https://www.bitget.com/copy-trading")
        console.print("→ Manually follow 1-2 traders")
        console.print("→ Then re-run this test")
