#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌉 BITGET → BINANCE BRIDGE RUNNER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bitget'ten trader sinyalleri al, Binance Futures'da execute et!

KULLANIM:
    python scripts/run_bitget_to_binance.py --config bitget_config.json
    
    VEYA
    
    python scripts/run_bitget_to_binance.py \\
        --bitget-key YOUR_KEY \\
        --bitget-secret YOUR_SECRET \\
        --bitget-pass YOUR_PASS \\
        --binance-key YOUR_KEY \\
        --binance-secret YOUR_SECRET
"""

import sys
import os
import asyncio
import json
from pathlib import Path
from typing import Dict

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from binance_futures_trader.bitget_to_binance_bridge import BitgetToBinanceBridge
from rich.console import Console
from rich.panel import Panel
import typer

app = typer.Typer()
console = Console()


def load_config(config_path: str) -> Dict:
    """Load config file"""
    if not Path(config_path).exists():
        console.print(f"[red]❌ Config file not found: {config_path}[/red]")
        return {}
    
    with open(config_path, 'r') as f:
        return json.load(f)


def create_default_config(path: str = "bitget_config.json"):
    """Create default config"""
    config = {
        "bitget": {
            "api_key": "YOUR_BITGET_API_KEY",
            "api_secret": "YOUR_BITGET_API_SECRET",
            "passphrase": "YOUR_BITGET_PASSPHRASE",
            "note": "Get from https://www.bitget.com/account/newapi"
        },
        "binance": {
            "api_key": "YOUR_BINANCE_API_KEY",
            "api_secret": "YOUR_BINANCE_API_SECRET",
            "testnet": True,
            "note": "Get from https://www.binance.com/en/my/settings/api-management"
        },
        "trading": {
            "capital_per_trade": 100.0,
            "max_positions": 5,
            "min_signal_confidence": 70.0,
            "check_interval_seconds": 30
        },
        "trader_discovery": {
            "top_n": 10,
            "min_roi": 15.0,
            "min_win_rate": 60.0
        }
    }
    
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
    
    console.print(f"[green]✅ Default config created: {path}[/green]")
    return config


@app.command()
def run(
    config: str = typer.Option("bitget_config.json", help="Config file path"),
    bitget_key: str = typer.Option(None, help="Bitget API key (overrides config)"),
    bitget_secret: str = typer.Option(None, help="Bitget API secret (overrides config)"),
    bitget_pass: str = typer.Option(None, help="Bitget passphrase (overrides config)"),
    binance_key: str = typer.Option(None, help="Binance API key (overrides config)"),
    binance_secret: str = typer.Option(None, help="Binance API secret (overrides config)"),
    testnet: bool = typer.Option(True, help="Use Binance testnet"),
    capital: float = typer.Option(None, help="Capital per trade (USDT)"),
    max_pos: int = typer.Option(None, help="Max positions"),
    interval: int = typer.Option(30, help="Check interval (seconds)")
):
    """
    Start Bitget → Binance bridge
    """
    
    console.print(Panel.fit(
        "[bold cyan]🌉 BITGET → BINANCE BRIDGE[/bold cyan]\n"
        "Bitget signals → Binance execution",
        border_style="cyan"
    ))
    
    # Load or create config
    if not Path(config).exists():
        console.print(f"[yellow]⚠️  Config not found, creating default...[/yellow]")
        cfg = create_default_config(config)
    else:
        cfg = load_config(config)
    
    # Credentials (CLI args override config)
    bitget_cfg = cfg.get('bitget', {})
    binance_cfg = cfg.get('binance', {})
    trading_cfg = cfg.get('trading', {})
    discovery_cfg = cfg.get('trader_discovery', {})
    
    bitget_api_key = bitget_key or bitget_cfg.get('api_key')
    bitget_api_secret = bitget_secret or bitget_cfg.get('api_secret')
    bitget_passphrase = bitget_pass or bitget_cfg.get('passphrase')
    
    binance_api_key = binance_key or binance_cfg.get('api_key')
    binance_api_secret = binance_secret or binance_cfg.get('api_secret')
    
    # Validate
    if not bitget_api_key or 'YOUR_' in bitget_api_key:
        console.print("[red]❌ Bitget API credentials not configured![/red]")
        console.print(f"[yellow]Please edit {config} or use --bitget-key, --bitget-secret, --bitget-pass[/yellow]")
        return
    
    if not binance_api_key or 'YOUR_' in binance_api_key:
        console.print("[yellow]⚠️  Binance API not configured - using paper trading[/yellow]")
    
    # Trading parameters
    capital_per_trade = capital or trading_cfg.get('capital_per_trade', 100.0)
    max_positions = max_pos or trading_cfg.get('max_positions', 5)
    min_confidence = trading_cfg.get('min_signal_confidence', 70.0)
    
    # Initialize bridge
    console.print("\n[cyan]🔧 Initializing bridge...[/cyan]")
    
    bridge = BitgetToBinanceBridge(
        bitget_api_key=bitget_api_key,
        bitget_api_secret=bitget_api_secret,
        bitget_passphrase=bitget_passphrase,
        binance_api_key=binance_api_key,
        binance_api_secret=binance_api_secret,
        binance_testnet=testnet,
        capital_per_trade=capital_per_trade,
        max_positions=max_positions,
        min_signal_confidence=min_confidence
    )
    
    # Discover traders
    console.print("\n[cyan]🔍 Discovering top traders...[/cyan]")
    
    traders = bridge.discover_traders(
        top_n=discovery_cfg.get('top_n', 10),
        min_roi=discovery_cfg.get('min_roi', 15.0),
        min_win_rate=discovery_cfg.get('min_win_rate', 60.0)
    )
    
    if not traders:
        console.print("[red]❌ No traders found! Adjust filter criteria.[/red]")
        return
    
    # Display config
    console.print(f"\n[bold]⚙️  Configuration:[/bold]")
    console.print(f"  Capital per trade: ${capital_per_trade}")
    console.print(f"  Max positions: {max_positions}")
    console.print(f"  Min confidence: {min_confidence}%")
    console.print(f"  Check interval: {interval}s")
    console.print(f"  Binance mode: {'Testnet' if testnet else 'Live'}")
    
    # Start monitoring
    console.print("\n[bold green]🚀 Starting continuous monitoring...[/bold green]")
    console.print("[dim](Press Ctrl+C to stop)[/dim]\n")
    
    try:
        asyncio.run(bridge.run_continuous(check_interval=interval))
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Stopped by user[/yellow]")
    finally:
        bridge.close()


@app.command()
def create_config(
    output: str = typer.Option("bitget_config.json", help="Output file path")
):
    """
    Create default config file
    """
    create_default_config(output)
    
    console.print(f"\n[cyan]Next steps:[/cyan]")
    console.print(f"1. Edit {output}")
    console.print(f"2. Add your Bitget API credentials")
    console.print(f"3. Add your Binance API credentials (optional)")
    console.print(f"4. Run: python scripts/run_bitget_to_binance.py")


@app.command()
def test_bitget(
    api_key: str = typer.Option(None, help="Bitget API key (or use .env)"),
    api_secret: str = typer.Option(None, help="Bitget API secret (or use .env)"),
    passphrase: str = typer.Option(None, help="Bitget passphrase (or use .env)")
):
    """
    Test Bitget API connection
    """
    from binance_futures_trader.bitget_signal_source import BitgetSignalAggregator
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Use .env if not provided
    api_key = api_key or os.getenv('BITGET_API_KEY')
    api_secret = api_secret or os.getenv('BITGET_SECRET_KEY')
    passphrase = passphrase or os.getenv('BITGET_PASSPHRASE')
    
    if not all([api_key, api_secret, passphrase]):
        console.print("[red]❌ Missing Bitget credentials![/red]")
        console.print("[yellow]Either provide --api-key, --api-secret, --passphrase")
        console.print("Or set BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE in .env[/yellow]")
        return
    
    console.print("\n[cyan]🧪 Testing Bitget API...[/cyan]")
    console.print(f"[dim]API Key: {api_key[:20]}...[/dim]")
    
    try:
        aggregator = BitgetSignalAggregator(
            bitget_api_key=api_key,
            bitget_api_secret=api_secret,
            bitget_passphrase=passphrase
        )
        
        traders = aggregator.discover_best_traders(top_n=10, min_roi=10, min_win_rate=55)
        
        if traders:
            console.print(f"[bold green]✅ SUCCESS! Found {len(traders)} quality traders[/bold green]")
            
            # Show top 3
            for i, trader in enumerate(traders[:3], 1):
                console.print(f"\n[cyan]{i}. {trader.nickname}[/cyan]")
                console.print(f"   ROI: {trader.roi:.1f}% | Win Rate: {trader.win_rate:.1f}% | Followers: {trader.followers}")
        else:
            console.print("[yellow]⚠️  API works but no qualifying traders found[/yellow]")
            console.print("[dim]Try lowering filters: min_roi=10, min_win_rate=55[/dim]")
        
        aggregator.close()
    
    except Exception as e:
        console.print(f"[red]❌ FAILED: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


if __name__ == "__main__":
    app()
