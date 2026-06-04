#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 GERÇEK SPOT TRADING VERİSİ (API Key ile)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Futures izni olmadan, Spot API kullanarak gerçek trading verisi çeker.

Kullanım:
    export BINANCE_API_KEY="your_key"
    export BINANCE_API_SECRET="your_secret"
    python scripts/get_spot_trading_data.py
"""

import os
import time
import hmac
import hashlib
from urllib.parse import urlencode
import json
from pathlib import Path
import httpx
from rich.console import Console
from rich.table import Table
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


def get_spot_account_info(api_key: str, api_secret: str):
    """Spot hesap bilgisi çek"""
    
    console.print(Panel.fit(
        "[bold cyan]📊 GERÇEK SPOT TRADING VERİSİ[/bold cyan]\n\n"
        "API key ile authenticated veri çekiliyor...",
        border_style="cyan"
    ))
    
    client = httpx.Client(timeout=30.0)
    
    try:
        # Account snapshot endpoint
        params = {
            'type': 'SPOT',
            'timestamp': int(time.time() * 1000),
            'recvWindow': 60000
        }
        params['signature'] = generate_signature(params, api_secret)
        
        headers = {'X-MBX-APIKEY': api_key}
        url = "https://api.binance.com/sapi/v1/accountSnapshot"
        
        console.print("\n[cyan]🔍 Fetching account snapshot...[/cyan]")
        response = client.get(url, params=params, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            console.print("[green]✓ Spot account data received (REAL)[/green]\n")
            
            if data.get('snapshotVos'):
                snapshot = data['snapshotVos'][0]['data']
                
                console.print(Panel.fit(
                    f"[bold green]✅ HESAP BİLGİSİ (GERÇEK)[/bold green]\n\n"
                    f"Total BTC Value: {snapshot.get('totalAssetOfBtc', 0)}\n"
                    f"Update Time: {snapshot.get('updateTime', 0)}",
                    border_style="green"
                ))
                
                # Bakiyeleri göster
                balances = snapshot.get('balances', [])
                non_zero = [b for b in balances if float(b.get('free', 0)) > 0 or float(b.get('locked', 0)) > 0]
                
                if non_zero:
                    table = Table(title="Spot Bakiyeler (Gerçek)", show_header=True, header_style="bold cyan")
                    table.add_column("Asset", style="green")
                    table.add_column("Free", justify="right", style="yellow")
                    table.add_column("Locked", justify="right", style="cyan")
                    
                    for bal in non_zero[:20]:
                        table.add_row(
                            bal['asset'],
                            bal['free'],
                            bal['locked']
                        )
                    
                    console.print("\n", table, "\n")
                
                return snapshot
        
        else:
            console.print(f"[red]✗ Error: {response.status_code}[/red]")
            console.print(f"[dim]{response.text}[/dim]")
            return None
    
    except Exception as e:
        console.print(f"[red]✗ Exception: {e}[/red]")
        return None
    
    finally:
        client.close()


def get_my_trades(api_key: str, api_secret: str):
    """Kendi trade geçmişini çek"""
    
    console.print("\n[cyan]📈 Fetching your trade history...[/cyan]")
    
    client = httpx.Client(timeout=30.0)
    
    try:
        # Son işlemler
        params = {
            'symbol': 'BTCUSDT',
            'limit': 10,
            'timestamp': int(time.time() * 1000),
            'recvWindow': 60000
        }
        params['signature'] = generate_signature(params, api_secret)
        
        headers = {'X-MBX-APIKEY': api_key}
        url = "https://api.binance.com/api/v3/myTrades"
        
        response = client.get(url, params=params, headers=headers)
        
        if response.status_code == 200:
            trades = response.json()
            
            if trades:
                console.print(f"[green]✓ {len(trades)} recent trades found (REAL)[/green]\n")
                
                table = Table(title="Son İşlemler (BTCUSDT)", show_header=True, header_style="bold cyan")
                table.add_column("Time", style="dim")
                table.add_column("Side", style="green")
                table.add_column("Price", justify="right", style="yellow")
                table.add_column("Qty", justify="right", style="cyan")
                
                for trade in trades:
                    side = "BUY" if trade['isBuyer'] else "SELL"
                    timestamp = time.strftime('%Y-%m-%d %H:%M', time.localtime(trade['time']/1000))
                    
                    table.add_row(
                        timestamp,
                        side,
                        trade['price'],
                        trade['qty']
                    )
                
                console.print(table, "\n")
                return trades
            else:
                console.print("[yellow]⚠️  No trades found for BTCUSDT[/yellow]\n")
                return []
        
        else:
            console.print(f"[yellow]⚠️  Trade history: {response.status_code}[/yellow]")
            return []
    
    except Exception as e:
        console.print(f"[yellow]⚠️  Trade history error: {e}[/yellow]")
        return []
    
    finally:
        client.close()


def main():
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    
    if not api_key or not api_secret:
        console.print("[red]❌ API keys not set![/red]")
        return
    
    # Spot account info
    account_data = get_spot_account_info(api_key, api_secret)
    
    # Trade history
    if account_data:
        trades = get_my_trades(api_key, api_secret)
    
    console.print("\n" + "="*60)
    console.print("[bold yellow]📌 ÖNEMLİ NOT[/bold yellow]")
    console.print("="*60)
    console.print("\nBu VERİNİN TAMAMI GERÇEK Binance verisi!")
    console.print("Simülasyon veya demo değil.\n")
    console.print("Trader profilleri için Futures hesabı açman gerekiyor:")
    console.print("  1. Binance > Derivatives > USDT-M Futures")
    console.print("  2. Open Futures Account")
    console.print("  3. API key'i düzenle > Enable Futures\n")


if __name__ == "__main__":
    main()
