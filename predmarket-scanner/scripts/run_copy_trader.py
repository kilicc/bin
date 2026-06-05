#!/usr/bin/env python3
"""
Binance Futures Copy Trading Runner
====================================
En iyi yatırımcıları otomatik takip edip pozisyonlarını aynalar.

Usage:
    python scripts/run_copy_trader.py --dry-run  # Test mode
    python scripts/run_copy_trader.py --live      # Live trading (DİKKAT!)
    python scripts/run_copy_trader.py --discover  # Sadece top traders keşfet
"""
import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv

from binance_futures_trader.copy_trader import CopyTradingEngine

console = Console()
app = typer.Typer()


def load_config():
    """Env dosyasından copy trading ayarlarını yükle"""
    # Önce genel .env
    load_dotenv()
    
    # Sonra scenario-specific
    env_file = Path("scenarios/binance_futures_demo.env")
    if env_file.exists():
        load_dotenv(env_file, override=True)
    
    config = {
        "api_key": os.getenv("BN_FUT_COPY_API_KEY"),
        "max_traders": int(os.getenv("BN_FUT_COPY_MAX_TRADERS", "10")),
        "min_trader_roi": float(os.getenv("BN_FUT_COPY_MIN_ROI", "50.0")),
        "min_trader_wr": float(os.getenv("BN_FUT_COPY_MIN_WR", "0.55")),
        "max_mirror_positions": int(os.getenv("BN_FUT_COPY_MAX_POSITIONS", "5")),
        "total_capital_usd": float(os.getenv("BN_FUT_START_BALANCE", "5000.0")),
        "copy_allocation_pct": float(os.getenv("BN_FUT_COPY_ALLOCATION_PCT", "30.0")),
        "refresh_interval_sec": int(os.getenv("BN_FUT_COPY_REFRESH_SEC", "60")),
        "discover_interval_sec": int(os.getenv("BN_FUT_COPY_DISCOVER_SEC", "3600")),
    }
    
    return config


@app.command()
def discover(
    period: str = typer.Option("MONTHLY", help="Leaderboard period: DAILY, WEEKLY, MONTHLY, ALL"),
    show_limit: int = typer.Option(20, help="Show top N traders")
):
    """
    Sadece top traders keşfet ve göster (trade açmaz)
    """
    console.print("\n[bold cyan]🔍 Discovering Top Binance Futures Traders[/bold cyan]\n")
    
    config = load_config()
    engine = CopyTradingEngine(
        api_key=config["api_key"],
        max_traders=config["max_traders"],
        min_trader_roi=config["min_trader_roi"],
        min_trader_wr=config["min_trader_wr"],
        max_mirror_positions=config["max_mirror_positions"],
        total_capital_usd=config["total_capital_usd"],
        copy_allocation_pct=config["copy_allocation_pct"]
    )
    
    top_traders = engine.discover_top_traders(period=period)
    
    if not top_traders:
        console.print("[red]❌ No traders found matching criteria[/red]")
        return
    
    # Rich table ile göster
    table = Table(title=f"Top {len(top_traders)} Traders ({period})")
    table.add_column("Rank", style="cyan", justify="right")
    table.add_column("Nickname", style="bold yellow")
    table.add_column("ROI %", style="green", justify="right")
    table.add_column("Win Rate %", style="blue", justify="right")
    table.add_column("PnL $", style="magenta", justify="right")
    table.add_column("Followers", style="white", justify="right")
    table.add_column("UID (first 8)", style="dim")
    
    for trader in top_traders[:show_limit]:
        table.add_row(
            f"#{trader.rank}",
            trader.nickname,
            f"{trader.roi:.1f}",
            f"{trader.win_rate:.1f}",
            f"{trader.pnl:,.0f}",
            f"{trader.follower_count:,}",
            trader.uid[:8] + "..."
        )
    
    console.print(table)
    
    console.print(f"\n[green]✓ Found {len(top_traders)} qualified traders[/green]")
    console.print(f"[dim]Criteria: ROI ≥ {config['min_trader_roi']}%, WR ≥ {config['min_trader_wr']*100}%[/dim]")


@app.command()
def monitor(
    dry_run: bool = typer.Option(True, "--dry-run/--live", help="Dry run mode (no real trades)"),
    period: str = typer.Option("MONTHLY", help="Leaderboard period for discovery")
):
    """
    Copy trading monitoring döngüsünü başlat
    
    --dry-run: Sadece simülasyon (gerçek trade açmaz) [DEFAULT]
    --live: Gerçek trade açar (DİKKAT!)
    """
    if not dry_run:
        confirm = typer.confirm(
            "⚠️  LIVE TRADING MODE! Real trades will be placed. Continue?",
            default=False
        )
        if not confirm:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit()
    
    config = load_config()
    
    console.print("\n[bold cyan]═══ Copy Trading Configuration ═══[/bold cyan]")
    console.print(f"  Mode: [bold]{'DRY RUN' if dry_run else '🔴 LIVE TRADING'}[/bold]")
    console.print(f"  Total Capital: ${config['total_capital_usd']:,.2f}")
    console.print(f"  Copy Allocation: {config['copy_allocation_pct']}% (${config['total_capital_usd'] * config['copy_allocation_pct'] / 100:,.2f})")
    console.print(f"  Max Traders: {config['max_traders']}")
    console.print(f"  Max Mirror Positions: {config['max_mirror_positions']}")
    console.print(f"  Min Trader ROI: {config['min_trader_roi']}%")
    console.print(f"  Min Trader WR: {config['min_trader_wr']*100}%")
    console.print(f"  Refresh Interval: {config['refresh_interval_sec']}s")
    console.print(f"  Discovery Interval: {config['discover_interval_sec']}s")
    console.print()
    
    engine = CopyTradingEngine(
        api_key=config["api_key"],
        max_traders=config["max_traders"],
        min_trader_roi=config["min_trader_roi"],
        min_trader_wr=config["min_trader_wr"],
        max_mirror_positions=config["max_mirror_positions"],
        total_capital_usd=config["total_capital_usd"],
        copy_allocation_pct=config["copy_allocation_pct"]
    )
    
    engine.run_monitoring_loop(
        refresh_interval_sec=config["refresh_interval_sec"],
        discover_interval_sec=config["discover_interval_sec"],
        dry_run=dry_run
    )


@app.command()
def status():
    """
    Aktif copy trading durumunu göster
    """
    console.print("\n[bold cyan]📊 Copy Trading Status[/bold cyan]\n")
    
    config = load_config()
    engine = CopyTradingEngine(
        api_key=config["api_key"],
        max_traders=config["max_traders"],
        min_trader_roi=config["min_trader_roi"],
        min_trader_wr=config["min_trader_wr"],
        max_mirror_positions=config["max_mirror_positions"],
        total_capital_usd=config["total_capital_usd"],
        copy_allocation_pct=config["copy_allocation_pct"]
    )
    
    # Tracked traders
    if engine.tracked_traders:
        table = Table(title="Tracked Traders")
        table.add_column("Nickname", style="yellow")
        table.add_column("Rank", justify="right")
        table.add_column("ROI %", style="green", justify="right")
        table.add_column("WR %", style="blue", justify="right")
        table.add_column("Active", justify="center")
        
        for uid, trader in engine.tracked_traders.items():
            table.add_row(
                trader.nickname,
                f"#{trader.rank}",
                f"{trader.roi:.1f}",
                f"{trader.win_rate:.1f}",
                "✓" if trader.is_active else "✗"
            )
        
        console.print(table)
    else:
        console.print("[yellow]No tracked traders yet. Run 'discover' first.[/yellow]")
    
    # Mirrored positions
    active_positions = [p for p in engine.mirrored_positions if not p.is_closed]
    closed_positions = [p for p in engine.mirrored_positions if p.is_closed]
    
    if active_positions:
        table = Table(title=f"Active Mirrored Positions ({len(active_positions)})")
        table.add_column("Trader", style="yellow")
        table.add_column("Symbol", style="cyan")
        table.add_column("Side", style="bold")
        table.add_column("Entry $", justify="right")
        table.add_column("Size $", justify="right")
        table.add_column("Leverage", justify="right")
        
        for pos in active_positions:
            side_color = "green" if pos.side == "LONG" else "red"
            table.add_row(
                pos.trader_nickname,
                pos.symbol,
                f"[{side_color}]{pos.side}[/{side_color}]",
                f"{pos.our_entry_price:.4f}",
                f"{pos.our_size_usd:.2f}",
                f"{pos.our_leverage}x"
            )
        
        console.print("\n", table)
    else:
        console.print("\n[dim]No active mirrored positions[/dim]")
    
    if closed_positions:
        console.print(f"\n[dim]Closed positions: {len(closed_positions)}[/dim]")


if __name__ == "__main__":
    app()
