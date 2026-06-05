#!/usr/bin/env python3
"""
Official Binance Copy Trading SDK ile trader keşfi
"""

import os
import json
import time
from pathlib import Path
from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import COPY_TRADING_REST_API_PROD_URL
from binance_sdk_copy_trading.copy_trading import CopyTrading
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def discover_with_sdk():
    """Official SDK kullanarak trader keşfet"""
    
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")
    
    if not api_key or not api_secret:
        console.print("[red]❌ API keys not set![/red]")
        return []
    
    console.print(Panel.fit(
        "[bold cyan]🔑 OFFICIAL BINANCE SDK[/bold cyan]\n\n"
        "binance-sdk-copy-trading kullanılıyor...",
        border_style="cyan"
    ))
    
    try:
        # SDK configuration
        config = ConfigurationRestAPI(
            api_key=api_key,
            api_secret=api_secret,
            base_path=COPY_TRADING_REST_API_PROD_URL
        )
        
        client = CopyTrading(config_rest_api=config)
        
        # Lead trader status
        console.print("\n[cyan]🔍 Getting lead trader status...[/cyan]")
        status = client.get_futures_lead_trader_status()
        console.print(f"[green]✓ Response received[/green]")
        console.print(f"[dim]{json.dumps(status, indent=2)}[/dim]\n")
        
        # Lead symbol whitelist
        console.print("[cyan]🔍 Getting lead trading symbols...[/cyan]")
        symbols = client.get_futures_lead_symbol()
        console.print(f"[green]✓ {len(symbols.get('data', []))} symbols found[/green]\n")
        
        # Kaydet
        output_dir = Path("data/real_traders")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(output_dir / "sdk_lead_status.json", "w") as f:
            json.dump(status, f, indent=2)
        
        with open(output_dir / "sdk_lead_symbols.json", "w") as f:
            json.dump(symbols, f, indent=2)
        
        console.print(Panel.fit(
            "[bold green]✅ SDK VERİSİ ALINDI[/bold green]\n\n"
            f"Lead Trader Status: {status.get('data', {}).get('isLeadTrader', False)}\n"
            f"Available Symbols: {len(symbols.get('data', []))}\n\n"
            f"[dim]Not: SDK'den lead trader list endpoint'i bulunamadı.\n"
            f"Binance bu veriyi sadece kendi platform'unda gösteriyor.[/dim]",
            border_style="green"
        ))
        
        return {
            "status": status,
            "symbols": symbols
        }
    
    except Exception as e:
        console.print(f"[red]✗ SDK Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        return {}


if __name__ == "__main__":
    discover_with_sdk()
