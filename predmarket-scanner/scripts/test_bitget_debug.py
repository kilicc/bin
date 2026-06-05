#!/usr/bin/env python3
"""
Bitget API Debug Tool
"""

import sys
import hashlib
import hmac
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from rich.console import Console
from rich.panel import Panel

console = Console()


def test_bitget_signature():
    """Test Bitget signature calculation"""
    
    console.print(Panel.fit(
        "[bold cyan]🔍 BITGET API DEBUG[/bold cyan]",
        border_style="cyan"
    ))
    
    # Get credentials
    api_key = input("Bitget API Key: ").strip()
    api_secret = input("Bitget API Secret: ").strip()
    passphrase = input("Bitget Passphrase: ").strip()
    
    if not all([api_key, api_secret, passphrase]):
        console.print("[red]❌ All credentials required![/red]")
        return
    
    # Test endpoint
    base_url = "https://api.bitget.com"
    path = "/api/v2/copy/mix-follower/query-traders"
    
    # Prepare request
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    body = ""
    
    # Calculate signature
    message = timestamp + method + path + body
    console.print(f"\n[cyan]📝 Signature Message:[/cyan]")
    console.print(f"  {message}")
    
    signature = hmac.new(
        api_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    console.print(f"\n[cyan]🔐 Signature:[/cyan]")
    console.print(f"  {signature}")
    
    # Prepare headers
    headers = {
        'ACCESS-KEY': api_key,
        'ACCESS-SIGN': signature,
        'ACCESS-TIMESTAMP': timestamp,
        'ACCESS-PASSPHRASE': passphrase,
        'Content-Type': 'application/json',
        'locale': 'en-US'
    }
    
    console.print(f"\n[cyan]📤 Headers:[/cyan]")
    for key, value in headers.items():
        if key in ['ACCESS-KEY', 'ACCESS-SIGN', 'ACCESS-PASSPHRASE']:
            console.print(f"  {key}: {value[:20]}...")
        else:
            console.print(f"  {key}: {value}")
    
    # Test different parameter combinations
    test_cases = [
        {"productType": "USDT-FUTURES", "sortBy": "roi", "pageSize": "10"},
        {"productType": "USDT-FUTURES"},
        {},  # No params
    ]
    
    for i, params in enumerate(test_cases, 1):
        console.print(f"\n[bold]━━━ Test Case {i} ━━━[/bold]")
        console.print(f"Params: {params}")
        
        try:
            url = f"{base_url}{path}"
            
            console.print(f"\n[cyan]📡 Request:[/cyan]")
            console.print(f"  URL: {url}")
            console.print(f"  Method: {method}")
            console.print(f"  Params: {params or 'None'}")
            
            client = httpx.Client(timeout=30.0)
            
            if params:
                response = client.get(url, params=params, headers=headers)
            else:
                response = client.get(url, headers=headers)
            
            console.print(f"\n[cyan]📥 Response:[/cyan]")
            console.print(f"  Status: {response.status_code}")
            console.print(f"  Headers: {dict(response.headers)}")
            
            console.print(f"\n[cyan]📄 Body:[/cyan]")
            try:
                data = response.json()
                import json
                console.print(json.dumps(data, indent=2))
                
                if response.status_code == 200:
                    console.print(f"\n[bold green]✅ SUCCESS![/bold green]")
                    return
            except:
                console.print(response.text)
            
            if response.status_code != 200:
                console.print(f"\n[yellow]❌ Failed with {response.status_code}[/yellow]")
        
        except Exception as e:
            console.print(f"\n[red]❌ Error: {e}[/red]")
        
        finally:
            client.close()
    
    # Try alternative endpoints
    console.print(f"\n[bold]━━━ Testing Alternative Endpoints ━━━[/bold]")
    
    alt_endpoints = [
        "/api/v2/copy/spot-follower/query-traders",  # Spot instead of mix
        "/api/v1/copy/mix-follower/query-traders",   # v1 instead of v2
    ]
    
    for endpoint in alt_endpoints:
        console.print(f"\n[cyan]Testing: {endpoint}[/cyan]")
        
        try:
            # Recalculate signature for new path
            new_timestamp = str(int(time.time() * 1000))
            new_message = new_timestamp + method + endpoint + body
            new_signature = hmac.new(
                api_secret.encode('utf-8'),
                new_message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            new_headers = headers.copy()
            new_headers['ACCESS-SIGN'] = new_signature
            new_headers['ACCESS-TIMESTAMP'] = new_timestamp
            
            url = f"{base_url}{endpoint}"
            client = httpx.Client(timeout=30.0)
            response = client.get(url, headers=new_headers)
            
            console.print(f"  Status: {response.status_code}")
            
            if response.status_code == 200:
                console.print(f"  [green]✅ This endpoint works![/green]")
                try:
                    data = response.json()
                    import json
                    console.print(json.dumps(data, indent=2)[:500])
                except:
                    pass
                return
            else:
                try:
                    error = response.json()
                    console.print(f"  Error: {error}")
                except:
                    console.print(f"  Response: {response.text[:200]}")
            
            client.close()
        
        except Exception as e:
            console.print(f"  [red]Error: {e}[/red]")


if __name__ == "__main__":
    test_bitget_signature()
