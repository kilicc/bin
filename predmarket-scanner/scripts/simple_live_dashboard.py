#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 SIMPLE LIVE DASHBOARD - 5000 USDT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import asyncio
import time
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.layout import Layout
import random

console = Console()


class SimpleLiveDashboard:
    def __init__(self):
        self.capital = 5000.0
        self.starting_capital = 5000.0
        self.total_pnl = 0.0
        self.open_positions = 1
        self.closed_trades = 0
        self.start_time = time.time()
        
        # Demo position
        self.btc_entry = 76500.0
        self.btc_current = 76500.0
        self.btc_size = 0.065
        
    def generate_layout(self) -> Layout:
        """Generate dashboard layout"""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3)
        )
        
        # Header
        runtime = time.time() - self.start_time
        runtime_str = f"{int(runtime // 3600)}h {int((runtime % 3600) // 60)}m {int(runtime % 60)}s"
        layout["header"].update(
            Panel(
                f"[bold cyan]MAIN STRATEGY - LIVE[/bold cyan] | Runtime: {runtime_str} | {datetime.now().strftime('%H:%M:%S')}",
                style="cyan"
            )
        )
        
        # Body
        pnl_pct = (self.total_pnl / self.starting_capital) * 100
        pnl_color = "green" if self.total_pnl >= 0 else "red"
        
        table = Table(show_header=True, header_style="bold cyan", box=None, expand=True)
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value", style="white")
        
        table.add_row("💰 Current Capital", f"${self.capital:,.2f} USDT")
        table.add_row("📊 Starting Capital", f"${self.starting_capital:,.2f} USDT")
        table.add_row(
            "💵 Total PnL", 
            f"[{pnl_color}]{self.total_pnl:+,.2f} USDT ({pnl_pct:+.2f}%)[/{pnl_color}]"
        )
        table.add_row("", "")
        table.add_row("📈 Open Positions", str(self.open_positions))
        table.add_row("✅ Closed Trades", str(self.closed_trades))
        
        # Position details
        btc_pnl = (self.btc_current - self.btc_entry) * self.btc_size
        btc_pnl_pct = ((self.btc_current - self.btc_entry) / self.btc_entry) * 100
        btc_pnl_color = "green" if btc_pnl >= 0 else "red"
        
        table.add_row("", "")
        table.add_row("[bold yellow]Position: BTCUSDT LONG[/bold yellow]", "")
        table.add_row("  Entry Price", f"${self.btc_entry:,.2f}")
        table.add_row("  Current Price", f"${self.btc_current:,.2f}")
        table.add_row("  Size", f"{self.btc_size} BTC")
        table.add_row(
            "  PnL", 
            f"[{btc_pnl_color}]{btc_pnl:+,.2f} USDT ({btc_pnl_pct:+.2f}%)[/{btc_pnl_color}]"
        )
        
        layout["body"].update(Panel(table, title="Portfolio Status", border_style="cyan"))
        
        # Footer
        layout["footer"].update(
            Panel(
                "[dim]Press Ctrl+C to stop | Updates every 2 seconds[/dim]",
                style="dim"
            )
        )
        
        return layout
    
    async def update_prices(self):
        """Simulate price updates"""
        # Simulated BTC price movement
        change = random.uniform(-0.002, 0.002)  # ±0.2%
        self.btc_current = self.btc_current * (1 + change)
        
        # Calculate PnL
        btc_pnl = (self.btc_current - self.btc_entry) * self.btc_size
        self.total_pnl = btc_pnl
        self.capital = self.starting_capital + self.total_pnl
    
    async def run(self):
        """Main loop"""
        console.print("\n[bold green]🚀 Main Strategy Dashboard başlatılıyor...[/bold green]")
        console.print(f"[cyan]Capital: ${self.capital:,.2f} USDT[/cyan]\n")
        
        try:
            with Live(self.generate_layout(), refresh_per_second=1, console=console, screen=True) as live:
                while True:
                    await self.update_prices()
                    live.update(self.generate_layout())
                    await asyncio.sleep(2)
                    
        except KeyboardInterrupt:
            console.print("\n[yellow]👋 Durduruldu[/yellow]\n")
            self.show_summary()
    
    def show_summary(self):
        """Final summary"""
        runtime = time.time() - self.start_time
        runtime_str = f"{int(runtime // 3600)}h {int((runtime % 3600) // 60)}m {int(runtime % 60)}s"
        
        console.print("[bold]═══ FINAL SUMMARY ═══[/bold]")
        console.print(f"Runtime: {runtime_str}")
        console.print(f"Starting: ${self.starting_capital:,.2f} USDT")
        console.print(f"Ending: ${self.capital:,.2f} USDT")
        
        pnl_pct = (self.total_pnl / self.starting_capital) * 100
        pnl_color = "green" if self.total_pnl >= 0 else "red"
        console.print(f"PnL: [{pnl_color}]{self.total_pnl:+,.2f} USDT ({pnl_pct:+.2f}%)[/{pnl_color}]")


if __name__ == "__main__":
    dashboard = SimpleLiveDashboard()
    asyncio.run(dashboard.run())
