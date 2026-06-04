#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 DUAL STRATEGY RUNNER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAIN STRATEGY (5000 USDT) + COPY TRADING (5000 USDC) paralel çalıştır!

MODULE 1: Main Portfolio Strategy
  - Capital: 5000 USDT
  - Strategy: adv_alpha_max
  - Multi-coin, MTF, technical indicators

MODULE 2: Copy Trading (Bitget → Binance)
  - Capital: 5000 USDC
  - Source: Bitget top traders
  - Execution: Binance Futures

KULLANIM:
    python scripts/run_dual_strategy.py --config dual_config.json
"""

import sys
import os
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from binance_futures_trader.bitget_to_binance_bridge import BitgetToBinanceBridge
from binance_futures_trader.client import BinanceFuturesClient
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
import typer

app = typer.Typer()
console = Console()


@dataclass
class StrategyStats:
    """Strategy statistics"""
    name: str
    capital: float
    positions_count: int
    total_pnl: float
    win_rate: float
    trades_count: int
    
    def roi_pct(self) -> float:
        """ROI percentage"""
        return (self.total_pnl / self.capital) * 100 if self.capital > 0 else 0.0


class MainStrategyRunner:
    """
    Main portfolio strategy runner
    """
    
    def __init__(
        self,
        capital: float = 5000.0,
        max_positions: int = 6,
        risk_pct: float = 0.02
    ):
        self.capital = capital
        self.max_positions = max_positions
        self.risk_pct = risk_pct
        
        self.binance = BinanceFuturesClient()
        
        # Stats
        self.stats = StrategyStats(
            name="Main Strategy",
            capital=capital,
            positions_count=0,
            total_pnl=0.0,
            win_rate=0.0,
            trades_count=0
        )
        
        # Active positions
        self.active_positions: Dict = {}
    
    async def run_iteration(self):
        """Single strategy iteration"""
        try:
            # TODO: Implement main strategy logic
            # For now, simulate
            
            console.print("[cyan]📊 Main Strategy: Analyzing markets...[/cyan]")
            
            # Simulate some activity
            await asyncio.sleep(1)
            
            # Update stats (demo)
            self.stats.positions_count = len(self.active_positions)
        
        except Exception as e:
            console.print(f"[red]❌ Main Strategy error: {e}[/red]")
    
    def get_stats(self) -> StrategyStats:
        """Get current statistics"""
        return self.stats


class CopyTradingRunner:
    """
    Copy trading strategy runner (Bitget → Binance)
    """
    
    def __init__(
        self,
        bitget_api_key: str,
        bitget_api_secret: str,
        bitget_passphrase: str,
        capital: float = 5000.0,
        max_positions: int = 5
    ):
        self.capital = capital
        
        # Bitget → Binance bridge
        self.bridge = BitgetToBinanceBridge(
            bitget_api_key=bitget_api_key,
            bitget_api_secret=bitget_api_secret,
            bitget_passphrase=bitget_passphrase,
            binance_testnet=True,
            capital_per_trade=capital / max_positions,
            max_positions=max_positions,
            min_signal_confidence=70.0
        )
        
        # Stats
        self.stats = StrategyStats(
            name="Copy Trading",
            capital=capital,
            positions_count=0,
            total_pnl=0.0,
            win_rate=0.0,
            trades_count=0
        )
        
        self.traders_discovered = False
    
    async def discover_traders(self):
        """Discover top traders (one time)"""
        if self.traders_discovered:
            return
        
        console.print("[cyan]🔍 Copy Trading: Discovering traders...[/cyan]")
        
        traders = self.bridge.discover_traders(
            top_n=10,
            min_roi=15.0,
            min_win_rate=60.0
        )
        
        if traders:
            self.traders_discovered = True
            console.print(f"[green]✅ Tracking {len(traders)} traders[/green]")
    
    async def run_iteration(self):
        """Single iteration"""
        try:
            # Get new signals
            signals = self.bridge.bitget.get_new_signals()
            
            if signals:
                console.print(f"[cyan]📡 Copy Trading: {len(signals)} new signal(s)[/cyan]")
                
                for signal in signals:
                    self.bridge.process_signal(signal)
            
            # Monitor positions
            self.bridge.monitor_positions()
            
            # Update stats
            self.stats.positions_count = len(self.bridge.active_positions)
            self.stats.total_pnl = self.bridge.stats['total_pnl']
            self.stats.trades_count = self.bridge.stats['positions_opened']
        
        except Exception as e:
            console.print(f"[red]❌ Copy Trading error: {e}[/red]")
    
    def get_stats(self) -> StrategyStats:
        """Get current statistics"""
        return self.stats
    
    def close(self):
        """Cleanup"""
        self.bridge.close()


class DualStrategyOrchestrator:
    """
    Orchestrates both strategies in parallel
    """
    
    def __init__(
        self,
        main_capital: float = 5000.0,
        copy_capital: float = 5000.0,
        bitget_api_key: str = "",
        bitget_api_secret: str = "",
        bitget_passphrase: str = ""
    ):
        # Main strategy
        self.main_strategy = MainStrategyRunner(
            capital=main_capital,
            max_positions=6,
            risk_pct=0.02
        )
        
        # Copy trading strategy
        self.copy_strategy = CopyTradingRunner(
            bitget_api_key=bitget_api_key,
            bitget_api_secret=bitget_api_secret,
            bitget_passphrase=bitget_passphrase,
            capital=copy_capital,
            max_positions=5
        )
        
        self.start_time = time.time()
    
    def generate_dashboard(self) -> Layout:
        """Generate live dashboard"""
        layout = Layout()
        
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="strategies", size=20),
            Layout(name="footer", size=5)
        )
        
        # Header
        header = Panel(
            "[bold cyan]🎯 DUAL STRATEGY SYSTEM[/bold cyan]\n"
            f"Runtime: {self._format_runtime()}",
            border_style="cyan"
        )
        layout["header"].update(header)
        
        # Strategies comparison
        main_stats = self.main_strategy.get_stats()
        copy_stats = self.copy_strategy.get_stats()
        
        table = Table(title="📊 Strategy Comparison", show_header=True)
        table.add_column("Metric", style="cyan", width=25)
        table.add_column("Main Strategy", style="yellow", justify="right")
        table.add_column("Copy Trading", style="green", justify="right")
        
        table.add_row(
            "Capital",
            f"${main_stats.capital:,.2f} USDT",
            f"${copy_stats.capital:,.2f} USDC"
        )
        table.add_row(
            "Active Positions",
            str(main_stats.positions_count),
            str(copy_stats.positions_count)
        )
        table.add_row(
            "Total Trades",
            str(main_stats.trades_count),
            str(copy_stats.trades_count)
        )
        table.add_row(
            "Total PnL",
            f"${main_stats.total_pnl:+,.2f}",
            f"${copy_stats.total_pnl:+,.2f}"
        )
        table.add_row(
            "ROI %",
            f"{main_stats.roi_pct():+.2f}%",
            f"{copy_stats.roi_pct():+.2f}%"
        )
        table.add_row(
            "Win Rate",
            f"{main_stats.win_rate:.1f}%",
            f"{copy_stats.win_rate:.1f}%"
        )
        
        # Total
        total_capital = main_stats.capital + copy_stats.capital
        total_pnl = main_stats.total_pnl + copy_stats.total_pnl
        total_roi = (total_pnl / total_capital) * 100 if total_capital > 0 else 0
        
        table.add_row("", "", "", style="dim")
        table.add_row(
            "[bold]TOTAL[/bold]",
            f"[bold]${total_capital:,.2f}[/bold]",
            ""
        )
        table.add_row(
            "[bold]Combined PnL[/bold]",
            f"[bold]${total_pnl:+,.2f}[/bold]",
            ""
        )
        table.add_row(
            "[bold]Combined ROI[/bold]",
            f"[bold]{total_roi:+.2f}%[/bold]",
            ""
        )
        
        layout["strategies"].update(table)
        
        # Footer
        footer = Panel(
            "[dim]Press Ctrl+C to stop[/dim]",
            border_style="dim"
        )
        layout["footer"].update(footer)
        
        return layout
    
    def _format_runtime(self) -> str:
        """Format runtime"""
        elapsed = time.time() - self.start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    async def run(self, check_interval: int = 30):
        """
        Run both strategies in parallel
        
        Args:
            check_interval: Check interval in seconds
        """
        console.print(Panel.fit(
            "[bold green]🚀 DUAL STRATEGY SYSTEM STARTED[/bold green]\n"
            f"Main Strategy: ${self.main_strategy.capital:,.0f} USDT\n"
            f"Copy Trading: ${self.copy_strategy.capital:,.0f} USDC\n"
            f"Total Capital: ${self.main_strategy.capital + self.copy_strategy.capital:,.0f}",
            border_style="green"
        ))
        
        # Initial setup
        console.print("\n[cyan]🔧 Initializing strategies...[/cyan]")
        
        # Discover traders for copy trading
        await self.copy_strategy.discover_traders()
        
        console.print("\n[bold green]✅ Both strategies initialized![/bold green]")
        console.print(f"[cyan]Running iterations every {check_interval}s...[/cyan]\n")
        
        iteration = 0
        
        try:
            with Live(self.generate_dashboard(), refresh_per_second=1) as live:
                while True:
                    iteration += 1
                    
                    # Run both strategies in parallel
                    await asyncio.gather(
                        self.main_strategy.run_iteration(),
                        self.copy_strategy.run_iteration()
                    )
                    
                    # Update dashboard
                    live.update(self.generate_dashboard())
                    
                    # Wait
                    await asyncio.sleep(check_interval)
        
        except KeyboardInterrupt:
            console.print("\n\n[yellow]⚠️  Shutting down...[/yellow]")
        
        finally:
            # Cleanup
            self.copy_strategy.close()
            
            # Final stats
            console.print("\n[bold]━━━ FINAL STATISTICS ━━━[/bold]\n")
            console.print(self.generate_dashboard())


def load_config(config_path: str) -> Dict:
    """Load config file"""
    if not Path(config_path).exists():
        return {}
    
    with open(config_path, 'r') as f:
        return json.load(f)


def create_default_config(path: str = "dual_config.json"):
    """Create default config"""
    config = {
        "main_strategy": {
            "capital": 5000.0,
            "currency": "USDT",
            "max_positions": 6,
            "risk_pct": 0.02,
            "strategy": "adv_alpha_max"
        },
        "copy_trading": {
            "capital": 5000.0,
            "currency": "USDC",
            "max_positions": 5,
            "capital_per_trade": 1000.0,
            "min_confidence": 70.0
        },
        "bitget": {
            "api_key": "YOUR_BITGET_API_KEY",
            "api_secret": "YOUR_BITGET_API_SECRET",
            "passphrase": "YOUR_BITGET_PASSPHRASE"
        },
        "binance": {
            "api_key": "3qLjlfUeLyGgtB8p4oKTD6YsP5M8bWb67tUemJRc7YOxuC1hJYI4fWOqupZj1Idb",
            "api_secret": "RBuo1px4L5uF2n7plOtPPoZ0VXWAfULnDwbdzS5WxGfGTXxqGxZrLsBwlu34ONeX",
            "testnet": True
        },
        "system": {
            "check_interval_seconds": 30
        }
    }
    
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
    
    console.print(f"[green]✅ Default config created: {path}[/green]")
    return config


@app.command()
def run(
    config: str = typer.Option("dual_config.json", help="Config file path"),
    main_capital: float = typer.Option(5000.0, help="Main strategy capital (USDT)"),
    copy_capital: float = typer.Option(5000.0, help="Copy trading capital (USDC)"),
    interval: int = typer.Option(30, help="Check interval (seconds)")
):
    """
    Run dual strategy system
    """
    
    # Load or create config
    if not Path(config).exists():
        console.print(f"[yellow]⚠️  Config not found, creating default...[/yellow]")
        cfg = create_default_config(config)
    else:
        cfg = load_config(config)
    
    # Get credentials
    bitget_cfg = cfg.get('bitget', {})
    
    bitget_api_key = bitget_cfg.get('api_key', '')
    bitget_api_secret = bitget_cfg.get('api_secret', '')
    bitget_passphrase = bitget_cfg.get('passphrase', '')
    
    # Validate
    if not bitget_api_key or 'YOUR_' in bitget_api_key:
        console.print("[red]❌ Bitget API credentials not configured![/red]")
        console.print(f"[yellow]Please edit {config} and add Bitget API credentials[/yellow]")
        console.print("\n[cyan]Get Bitget API key from:[/cyan]")
        console.print("https://www.bitget.com/account/newapi")
        return
    
    # Create orchestrator
    orchestrator = DualStrategyOrchestrator(
        main_capital=main_capital,
        copy_capital=copy_capital,
        bitget_api_key=bitget_api_key,
        bitget_api_secret=bitget_api_secret,
        bitget_passphrase=bitget_passphrase
    )
    
    # Run
    try:
        asyncio.run(orchestrator.run(check_interval=interval))
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Stopped by user[/yellow]")


@app.command()
def create_config(
    output: str = typer.Option("dual_config.json", help="Output file path")
):
    """
    Create default config file
    """
    create_default_config(output)
    
    console.print(f"\n[cyan]Next steps:[/cyan]")
    console.print(f"1. Edit {output}")
    console.print(f"2. Add Bitget API credentials")
    console.print(f"3. Run: python scripts/run_dual_strategy.py")


if __name__ == "__main__":
    app()
