#!/usr/bin/env python3
"""Test Bitget API with PUBLIC endpoint first"""
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


def test_public_endpoint():
    """Test PUBLIC endpoint (no signature needed)"""
    console.print("\n[bold cyan]═══ Test 1: PUBLIC Endpoint (No Auth) ═══[/bold cyan]")
    
    url = "https://api.bitget.com/api/v2/mix/market/tickers"
    params = {
        'productType': 'USDT-FUTURES'
    }
    
    try:
        response = httpx.get(url, params=params, timeout=30.0)
        console.print(f"Status: {response.status_code}")
        console.print(f"Response: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '00000':
                console.print("[green]✓ Public endpoint works![/green]")
                return True
            else:
                console.print(f"[red]✗ API Error: {data.get('msg')}[/red]")
        else:
            console.print(f"[red]✗ HTTP Error: {response.status_code}[/red]")
            
    except Exception as e:
        console.print(f"[red]✗ Exception: {e}[/red]")
    
    return False


def create_signature(timestamp: str, method: str, request_path: str, query_string: str = "", body: str = "") -> str:
    """Create Bitget signature"""
    if query_string:
        message = timestamp + method + request_path + "?" + query_string + body
    else:
        message = timestamp + method + request_path + body
    
    console.print(f"[dim]Message to sign: {message}[/dim]")
    
    mac = hmac.new(
        API_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    )
    
    signature = base64.b64encode(mac.digest()).decode()
    console.print(f"[dim]Signature: {signature}[/dim]")
    
    return signature


def test_account_endpoint():
    """Test PRIVATE endpoint (requires auth)"""
    console.print("\n[bold cyan]═══ Test 2: PRIVATE Endpoint (Account Info) ═══[/bold cyan]")
    
    if not API_KEY or not API_SECRET or not PASSPHRASE:
        console.print("[red]✗ API credentials missing in .env[/red]")
        return False
    
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    request_path = "/api/v2/mix/account/accounts"
    
    # Query params
    params = {
        'productType': 'USDT-FUTURES'
    }
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
    
    console.print(f"[dim]Headers: {headers}[/dim]")
    
    # Request
    url = f"https://api.bitget.com{request_path}"
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=30.0)
        console.print(f"Status: {response.status_code}")
        console.print(f"Response: {response.text[:500]}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '00000':
                console.print("[green]✓ Account endpoint works! Signature is CORRECT![/green]")
                return True
            else:
                console.print(f"[red]✗ API Error: {data.get('msg')}[/red]")
        else:
            console.print(f"[red]✗ HTTP Error: {response.status_code}[/red]")
            
    except Exception as e:
        console.print(f"[red]✗ Exception: {e}[/red]")
    
    return False


def test_copy_trading_endpoint():
    """Test COPY TRADING endpoint"""
    console.print("\n[bold cyan]═══ Test 3: COPY TRADING Endpoint ═══[/bold cyan]")
    
    if not API_KEY or not API_SECRET or not PASSPHRASE:
        console.print("[red]✗ API credentials missing in .env[/red]")
        return False
    
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    request_path = "/api/v2/copy/mix-follower/query-traders"
    
    # Query params
    params = {
        'productType': 'umcbl',  # USDT-FUTURES contract
        'sortBy': '1',           # Try numeric format
        'pageSize': '50'
    }
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
    
    console.print(f"[dim]Headers: {headers}[/dim]")
    
    # Request
    url = f"https://api.bitget.com{request_path}"
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=30.0)
        console.print(f"Status: {response.status_code}")
        console.print(f"Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == '00000':
                console.print("[green]✓ Copy trading endpoint works![/green]")
                return True
            else:
                console.print(f"[red]✗ API Error: {data.get('msg')}[/red]")
        else:
            console.print(f"[red]✗ HTTP Error: {response.status_code}[/red]")
            
    except Exception as e:
        console.print(f"[red]✗ Exception: {e}[/red]")
    
    return False


if __name__ == "__main__":
    console.print("[bold]Bitget API Progressive Test[/bold]")
    
    # Test 1: Public endpoint
    if test_public_endpoint():
        console.print("[green]→ Public API is accessible[/green]")
    else:
        console.print("[red]→ Public API failed (network issue?)[/red]")
        sys.exit(1)
    
    # Test 2: Account endpoint (private, requires signature)
    if test_account_endpoint():
        console.print("[green]→ Signature algorithm is CORRECT[/green]")
    else:
        console.print("[red]→ Signature failed OR API key invalid[/red]")
        console.print("[yellow]→ Please check your .env credentials[/yellow]")
    
    # Test 3: Copy trading endpoint
    if test_copy_trading_endpoint():
        console.print("[green]✓✓✓ ALL TESTS PASSED![/green]")
    else:
        console.print("[red]→ Copy trading endpoint failed[/red]")
        console.print("[yellow]→ This might be a permission issue or wrong endpoint/params[/yellow]")
