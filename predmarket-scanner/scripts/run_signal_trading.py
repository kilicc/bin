#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 SIGNAL-BASED COPY TRADING RUNNER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Manuel UID gerekmeden signal sağlayıcılardan otomatik trading!

KULLANIM:
    python scripts/run_signal_trading.py --config signal_config.json

VEYA:
    python scripts/run_signal_trading.py --stockapi-key YOUR_KEY

"""

import sys
import os
import asyncio
import json
from pathlib import Path
from typing import Dict, List

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from binance_futures_trader.signal_to_position import SignalToCopyTrading
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
import typer

app = typer.Typer()
console = Console()


def load_config(config_path: str) -> Dict:
    """Config dosyasını yükle"""
    if not Path(config_path).exists():
        console.print(f"[red]❌ Config file not found: {config_path}[/red]")
        return {}
    
    with open(config_path, 'r') as f:
        return json.load(f)


def create_default_config(path: str = "signal_config.json"):
    """Default config oluştur"""
    config = {
        "binance": {
            "api_key": "YOUR_BINANCE_API_KEY",
            "api_secret": "YOUR_BINANCE_API_SECRET",
            "testnet": True
        },
        "signal_sources": [
            {
                "id": "telegram_crypto_signals",
                "type": "telegram",
                "enabled": True,
                "webhook_url": "http://localhost:8000/webhook/telegram",
                "description": "Telegram crypto signal channels"
            },
            {
                "id": "tradingview_alerts",
                "type": "tradingview",
                "enabled": False,
                "webhook_url": "http://localhost:8000/webhook/tradingview",
                "description": "TradingView custom alerts"
            },
            {
                "id": "stockapi_signals",
                "type": "stockapi",
                "enabled": False,
                "api_key": "YOUR_STOCKAPI_KEY",
                "description": "StockAPI Telegram parser"
            }
        ],
        "trading": {
            "allowed_symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
            "min_confidence": 70.0,
            "max_positions": 5,
            "check_interval_seconds": 60,
            "risk_per_trade": 0.02
        }
    }
    
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
    
    console.print(f"[green]✅ Default config created: {path}[/green]")
    return config


@app.command()
def run(
    config: str = typer.Option("signal_config.json", help="Config file path"),
    api_key: str = typer.Option(None, help="Binance API key (overrides config)"),
    api_secret: str = typer.Option(None, help="Binance API secret (overrides config)"),
    stockapi_key: str = typer.Option(None, help="StockAPI key"),
    testnet: bool = typer.Option(True, help="Use testnet"),
    interval: int = typer.Option(60, help="Check interval in seconds")
):
    """
    Signal-based copy trading başlat
    """
    
    console.print(Panel.fit(
        "[bold cyan]🎯 SIGNAL-BASED COPY TRADING[/bold cyan]\n"
        "Otomatik signal topla ve trade et!",
        border_style="cyan"
    ))
    
    # Config yükle veya oluştur
    if not Path(config).exists():
        console.print(f"[yellow]⚠️  Config not found, creating default...[/yellow]")
        cfg = create_default_config(config)
    else:
        cfg = load_config(config)
    
    # API credentials
    binance_key = api_key or cfg.get('binance', {}).get('api_key')
    binance_secret = api_secret or cfg.get('binance', {}).get('api_secret')
    
    if not binance_key or 'YOUR_' in binance_key:
        console.print("[red]❌ Binance API credentials not configured![/red]")
        console.print(f"[yellow]Please edit {config} or use --api-key and --api-secret[/yellow]")
        return
    
    # Initialize bridge
    console.print("\n[cyan]🔧 Initializing...[/cyan]")
    
    bridge = SignalToCopyTrading(
        api_key=binance_key,
        api_secret=binance_secret,
        testnet=testnet
    )
    
    # Signal sources ekle
    signal_sources = cfg.get('signal_sources', [])
    
    table = Table(title="Signal Sources", show_header=True)
    table.add_column("ID", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Status", style="green")
    
    for source in signal_sources:
        if not source.get('enabled', True):
            continue
        
        source_config = {}
        
        # StockAPI config
        if source['type'] == 'stockapi':
            key = stockapi_key or source.get('api_key')
            if key and 'YOUR_' not in key:
                source_config['api_key'] = key
            else:
                console.print(f"[yellow]⚠️  Skipping {source['id']} (no API key)[/yellow]")
                continue
        
        bridge.add_signal_source(
            source_id=source['id'],
            source_type=source['type'],
            **source_config
        )
        
        table.add_row(
            source['id'],
            source['type'],
            "✅ Active"
        )
    
    console.print(table)
    
    # Trading config
    trading = cfg.get('trading', {})
    
    console.print(f"\n[bold]Trading Configuration:[/bold]")
    console.print(f"  Min Confidence: {trading.get('min_confidence', 70)}%")
    console.print(f"  Max Positions: {trading.get('max_positions', 5)}")
    console.print(f"  Check Interval: {interval}s")
    console.print(f"  Allowed Symbols: {', '.join(trading.get('allowed_symbols', []))}")
    
    # Start continuous monitoring
    console.print("\n[bold green]🚀 Starting signal monitoring...[/bold green]\n")
    
    try:
        asyncio.run(bridge.run_continuous(interval_seconds=interval))
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Bye![/yellow]")


@app.command()
def create_config(
    output: str = typer.Option("signal_config.json", help="Output file path")
):
    """
    Default config dosyası oluştur
    """
    create_default_config(output)


@app.command()
def test_signal_parse():
    """
    Telegram signal parse test
    """
    from binance_futures_trader.signal_aggregator import TelegramSignalParser
    
    console.print("[bold cyan]🧪 Testing Telegram Signal Parser[/bold cyan]\n")
    
    test_messages = [
        """
🚀 LONG #BTCUSDT
Entry: 76500
TP: 77000, 77500, 78000
SL: 75500
Leverage: 10x
        """,
        """
🔴 SHORT ETHUSDT
Entry: 3500
TP: 3400, 3350, 3300
SL: 3600
Leverage: 5x
        """
    ]
    
    parser = TelegramSignalParser()
    
    for i, msg in enumerate(test_messages, 1):
        console.print(f"[bold]Test {i}:[/bold]")
        console.print(f"[dim]{msg.strip()}[/dim]\n")
        
        signal = parser.parse_message(msg)
        
        if signal:
            table = Table(show_header=False)
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="green")
            
            table.add_row("Type", signal.signal_type)
            table.add_row("Symbol", signal.symbol)
            table.add_row("Entry", str(signal.entry_price))
            table.add_row("TP", str(signal.take_profit))
            table.add_row("SL", str(signal.stop_loss))
            table.add_row("Leverage", str(signal.leverage))
            
            console.print(table)
            console.print()
        else:
            console.print("[red]❌ Parse failed[/red]\n")


if __name__ == "__main__":
    app()
