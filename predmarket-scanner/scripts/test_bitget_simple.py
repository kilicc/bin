#!/usr/bin/env python3
"""
Simple Bitget API test with exact official format
"""

import hashlib
import hmac
import base64
import time
import httpx
from rich.console import Console

console = Console()

# Get credentials
api_key = input("Bitget API Key: ").strip()
api_secret = input("Bitget API Secret: ").strip()
passphrase = input("Bitget Passphrase: ").strip()

# Prepare request
timestamp = str(int(time.time() * 1000))
method = "GET"
request_path = "/api/v2/copy/mix-follower/query-traders"

# Parameters (will be added as query string)
params = {
    "productType": "USDT-FUTURES",
    "sortBy": "roi",
    "pageSize": "10"
}

# Build query string (alphabetic order)
query_items = sorted(params.items())
query_string = "&".join([f"{k}={v}" for k, v in query_items])

console.print(f"\n[cyan]Query String:[/cyan] {query_string}")

# Build message to sign
# Format: timestamp + method + requestPath + "?" + queryString
message = timestamp + method + request_path + "?" + query_string

console.print(f"\n[cyan]Message to Sign:[/cyan]")
console.print(f"  {message}")

# Calculate signature
mac = hmac.new(
    bytes(api_secret, encoding='utf8'),
    bytes(message, encoding='utf8'),
    hashlib.sha256
)
signature = base64.b64encode(mac.digest()).decode()

console.print(f"\n[cyan]Signature (base64):[/cyan]")
console.print(f"  {signature}")

# Prepare headers
headers = {
    "ACCESS-KEY": api_key,
    "ACCESS-SIGN": signature,
    "ACCESS-TIMESTAMP": timestamp,
    "ACCESS-PASSPHRASE": passphrase,
    "Content-Type": "application/json",
    "locale": "en-US"
}

console.print(f"\n[cyan]Headers:[/cyan]")
for k, v in headers.items():
    if k in ["ACCESS-KEY", "ACCESS-SIGN", "ACCESS-PASSPHRASE"]:
        console.print(f"  {k}: {v[:20]}...")
    else:
        console.print(f"  {k}: {v}")

# Make request
url = f"https://api.bitget.com{request_path}"

console.print(f"\n[cyan]Full URL:[/cyan] {url}?{query_string}")
console.print(f"\n[cyan]Sending request...[/cyan]")

try:
    client = httpx.Client(timeout=30.0)
    response = client.get(url, params=params, headers=headers)
    
    console.print(f"\n[cyan]Response Status:[/cyan] {response.status_code}")
    
    if response.status_code == 200:
        console.print(f"\n[bold green]✅ SUCCESS![/bold green]")
        data = response.json()
        
        import json
        console.print(json.dumps(data, indent=2)[:1000])
    else:
        console.print(f"\n[red]❌ FAILED[/red]")
        console.print(f"Response: {response.text}")
    
    client.close()

except Exception as e:
    console.print(f"\n[red]❌ Error: {e}[/red]")
