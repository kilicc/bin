#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 MAIN STRATEGY - LIVE RUNNER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

5000 USDT sermaye ile canlı trading!
Binance Futures Testnet

KULLANIM:
    python scripts/run_main_strategy_live.py
"""

import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import time
from datetime import datetime
from typing import Dict, List
from dataclasses import dataclass
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
from dotenv import load_dotenv

from binance_futures_trader.client import BinanceFuturesClient

console = Console()
load_dotenv()


@dataclass
class Position:
    """Açık pozisyon"""
    symbol: str
    side: str  # LONG/SHORT
    entry_price: float
    current_price: float
    size: float
    leverage: int
    pnl: float
    pnl_pct: float
    open_time: float


class LiveMainStrategy:
    """Canlı main strategy runner"""
    
    def __init__(self, capital: float = 5000.0):
        self.capital = capital
        self.starting_capital = capital
        self.positions: List[Position] = []
        self.closed_trades = []
        self.total_pnl = 0.0
        
        # Binance client
        api_key = os.getenv('BINANCE_FUTURES_API_KEY', '')
        api_secret = os.getenv('BINANCE_FUTURES_API_SECRET', '')
        testnet = os.getenv('BINANCE_FUTURES_TESTNET', '1') == '1'
        
        self.client = BinanceFuturesClient(
            api_key=api_key,
            secret_key=api_secret,
            testnet=testnet
        )
        
        self.start_time = time.time()
        self.last_signal_check = 0
        self.check_interval = 60  # 60 saniye
        
    def generate_dashboard(self) -> Panel:
        """Canlı dashboard oluştur"""
        # Stats
        runtime = time.time() - self.start_time
        runtime_str = f"{int(runtime // 3600)}h {int((runtime % 3600) // 60)}m"
        
        pnl_pct = (self.total_pnl / self.starting_capital) * 100
        pnl_color = "green" if self.total_pnl >= 0 else "red"
        
        # Header
        header = f"[bold cyan]MAIN STRATEGY - LIVE[/bold cyan] | Runtime: {runtime_str}"
        
        # Stats table
        stats_table = Table(show_header=False, box=None)
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", style="white")
        
        stats_table.add_row("💰 Capital", f"${self.capital:,.2f} USDT")
        stats_table.add_row("📊 Starting", f"${self.starting_capital:,.2f} USDT")
        stats_table.add_row(
            "💵 Total PnL", 
            f"[{pnl_color}]{self.total_pnl:+.2f} USDT ({pnl_pct:+.2f}%)[/{pnl_color}]"
        )
        stats_table.add_row("📈 Open Positions", f"{len(self.positions)}")
        stats_table.add_row("✅ Closed Trades", f"{len(self.closed_trades)}")
        
        # Positions table
        if self.positions:
            pos_table = Table(title="Open Positions")
            pos_table.add_column("Symbol", style="cyan")
            pos_table.add_column("Side", style="yellow")
            pos_table.add_column("Entry", style="white")
            pos_table.add_column("Current", style="white")
            pos_table.add_column("PnL", style="green")
            
            for pos in self.positions[:5]:  # Max 5 göster
                pnl_color = "green" if pos.pnl >= 0 else "red"
                pos_table.add_row(
                    pos.symbol,
                    pos.side,
                    f"${pos.entry_price:.2f}",
                    f"${pos.current_price:.2f}",
                    f"[{pnl_color}]{pos.pnl:+.2f} ({pos.pnl_pct:+.2f}%)[/{pnl_color}]"
                )
        else:
            pos_table = "[dim]No open positions[/dim]"
        
        # Combine
        content = f"{header}\n\n{stats_table}\n\n{pos_table}"
        
        return Panel(content, border_style="cyan", padding=(1, 2))
    
    async def check_signals(self):
        """Yeni sinyal kontrol et"""
        try:
            # Simulated signal generation
            # Gerçek implementasyonda: portfolio_backtest'ten sinyal al
            
            console.print("[dim]Checking for new signals...[/dim]")
            
            # TODO: Implement real signal generation
            # signals = self.engine.generate_signals(...)
            
            await asyncio.sleep(1)
            
        except Exception as e:
            console.print(f"[red]Signal check error: {e}[/red]")
    
    async def update_positions(self):
        """Pozisyonları güncelle"""
        try:
            for pos in self.positions:
                # Get current price from Binance
                try:
                    ticker = self.client.get_ticker(pos.symbol)
                    pos.current_price = float(ticker.get('lastPrice', pos.entry_price))
                    
                    # Calculate PnL
                    if pos.side == "LONG":
                        pos.pnl = (pos.current_price - pos.entry_price) * pos.size
                    else:  # SHORT
                        pos.pnl = (pos.entry_price - pos.current_price) * pos.size
                    
                    pos.pnl_pct = (pos.pnl / (pos.entry_price * pos.size)) * 100
                    
                except Exception as e:
                    console.print(f"[yellow]Warning: Could not update {pos.symbol}: {e}[/yellow]")
            
            # Update total PnL
            self.total_pnl = sum(p.pnl for p in self.positions)
            self.capital = self.starting_capital + self.total_pnl
            
        except Exception as e:
            console.print(f"[red]Position update error: {e}[/red]")
    
    async def run(self):
        """Ana loop"""
        console.print("\n[bold green]🚀 Main Strategy başlatılıyor...[/bold green]")
        console.print(f"[cyan]Capital: ${self.capital:,.2f} USDT[/cyan]")
        console.print(f"[cyan]Testnet: {os.getenv('BINANCE_FUTURES_TESTNET') == '1'}[/cyan]")
        console.print("\n[dim]Press Ctrl+C to stop[/dim]\n")
        
        # Demo pozisyon ekle (test için)
        self.positions.append(Position(
            symbol="BTCUSDT",
            side="LONG",
            entry_price=76500.0,
            current_price=76500.0,
            size=0.065,  # ~5000 USDT position
            leverage=1,
            pnl=0.0,
            pnl_pct=0.0,
            open_time=time.time()
        ))
        
        try:
            with Live(self.generate_dashboard(), refresh_per_second=1, console=console) as live:
                while True:
                    # Update positions
                    await self.update_positions()
                    
                    # Check for new signals (her 60 saniyede)
                    if time.time() - self.last_signal_check > self.check_interval:
                        await self.check_signals()
                        self.last_signal_check = time.time()
                    
                    # Update dashboard
                    live.update(self.generate_dashboard())
                    
                    await asyncio.sleep(2)  # 2 saniye refresh
                    
        except KeyboardInterrupt:
            console.print("\n[yellow]👋 Stopped by user[/yellow]")
            self.show_final_report()
    
    def show_final_report(self):
        """Final rapor"""
        console.print("\n[bold]═══ FINAL REPORT ═══[/bold]")
        
        runtime = time.time() - self.start_time
        runtime_str = f"{int(runtime // 3600)}h {int((runtime % 3600) // 60)}m {int(runtime % 60)}s"
        
        console.print(f"Runtime: {runtime_str}")
        console.print(f"Starting Capital: ${self.starting_capital:,.2f} USDT")
        console.print(f"Ending Capital: ${self.capital:,.2f} USDT")
        
        pnl_pct = (self.total_pnl / self.starting_capital) * 100
        pnl_color = "green" if self.total_pnl >= 0 else "red"
        console.print(f"Total PnL: [{pnl_color}]{self.total_pnl:+.2f} USDT ({pnl_pct:+.2f}%)[/{pnl_color}]")
        
        console.print(f"\nOpen Positions: {len(self.positions)}")
        console.print(f"Closed Trades: {len(self.closed_trades)}")


if __name__ == "__main__":
    strategy = LiveMainStrategy(capital=5000.0)
    asyncio.run(strategy.run())
