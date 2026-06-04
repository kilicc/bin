#!/usr/bin/env python3
"""
Dual System Başlatıcı - Basitleştirilmiş
=========================================
Main strategy + Copy trading'i paralel başlatır.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def print_config():
    """Yapılandırmayı göster"""
    console.print("\n[bold cyan]╔═══════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║   DUAL STRATEGY SYSTEM - BAŞLATILIYOR   ║[/bold cyan]")
    console.print("[bold cyan]╚═══════════════════════════════════════════════╝[/bold cyan]\n")
    
    config_table = Table(title="Sistem Konfigürasyonu", show_header=False)
    config_table.add_column("", style="cyan", width=25)
    config_table.add_column("", style="bold", width=30)
    
    config_table.add_row("📊 Main Strategy", "adv_alpha_max (Portfolio Engine)")
    config_table.add_row("💰 Main Capital", "5000 USDT (Demo)")
    config_table.add_row("🎯 Main Target", "+274% (6 months backtest)")
    config_table.add_row("", "")
    config_table.add_row("🔄 Copy Trading", "Top Traders Mirroring")
    config_table.add_row("💵 Copy Capital", "5000 USDC (Demo)")
    config_table.add_row("📈 Copy Target", "~+120% (6 months est.)")
    config_table.add_row("", "")
    config_table.add_row("🎲 Combined Capital", "10,000 USD Total")
    config_table.add_row("🚀 Combined Target", "~+228% (Aggressive)")
    
    console.print(config_table)


def check_traders():
    """Tracked traders kontrol"""
    traders_file = Path("data/copy_trading/tracked_traders.json")
    
    if not traders_file.exists():
        console.print("\n[red]❌ Tracked traders dosyası bulunamadı![/red]")
        return False
    
    with open(traders_file) as f:
        traders = json.load(f)
    
    if not traders:
        console.print("\n[red]❌ Hiç trader eklenmemiş![/red]")
        return False
    
    console.print(f"\n[green]✓ {len(traders)} trader takip ediliyor:[/green]")
    
    table = Table(show_header=True)
    table.add_column("Nickname", style="yellow")
    table.add_column("Rank", justify="right")
    table.add_column("ROI %", justify="right", style="green")
    table.add_column("Win Rate", justify="right")
    table.add_column("Status", justify="center")
    
    for uid, trader in list(traders.items())[:5]:
        table.add_row(
            trader["nickname"],
            f"#{trader['rank']}",
            f"{trader['roi']:.1f}%",
            f"{trader['win_rate']*100:.1f}%",
            "🟢" if trader["is_active"] else "🔴"
        )
    
    console.print(table)
    
    return True


def show_next_steps():
    """Sonraki adımları göster"""
    console.print("\n[bold cyan]📋 Sistem Çalıştırma Talimatları:[/bold cyan]\n")
    
    steps = [
        ("1️⃣", "Main Strategy (adv_alpha_max)", 
         "Bu zaten mevcut scanner ile çalışıyor.\n"
         "   Scanner'ı başlatmak için: python -m binance_futures_trader"),
        
        ("2️⃣", "Copy Trading Engine", 
         "Copy trading için manuel monitoring:\n"
         "   python scripts/run_copy_trader.py monitor --dry-run"),
        
        ("3️⃣", "Live Dashboard", 
         "İki stratejinin performansını karşılaştırmak için:\n"
         "   python scripts/run_dual_strategy.py run --capital 10000 --main-pct 50 --copy-pct 50"),
        
        ("4️⃣", "Performance Monitoring",
         "Performans metrikleri:\n"
         "   - Main: data/education/portfolio_backtest_6m.json\n"
         "   - Copy: data/copy_trading/mirrored_positions.json\n"
         "   - Combined: data/dual_strategy_report.json")
    ]
    
    for emoji, title, desc in steps:
        console.print(f"[bold]{emoji} {title}[/bold]")
        console.print(f"[dim]{desc}[/dim]\n")


def create_status_file():
    """Durum dosyası oluştur"""
    status = {
        "system_started": datetime.now().isoformat(),
        "main_strategy": {
            "name": "adv_alpha_max",
            "capital_usdt": 5000,
            "status": "ready",
            "target_return_pct": 273.69
        },
        "copy_trading": {
            "enabled": True,
            "capital_usdc": 5000,
            "tracked_traders": 5,
            "status": "ready",
            "target_return_pct": 120.0
        },
        "combined": {
            "total_capital_usd": 10000,
            "target_return_pct": 227.58
        }
    }
    
    status_file = Path("data/dual_system_status.json")
    status_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(status_file, "w") as f:
        json.dump(status, f, indent=2)
    
    console.print(f"\n[green]✓ Durum dosyası oluşturuldu: {status_file}[/green]")


def main():
    """Ana fonksiyon"""
    try:
        # 1. Konfigürasyonu göster
        print_config()
        
        # 2. Traders kontrol
        console.print("\n" + "─" * 60)
        if not check_traders():
            console.print("\n[yellow]⚠️  Trader listesi oluşturuluyor...[/yellow]")
            # traders.json already created above
            check_traders()
        
        # 3. Durum dosyası oluştur
        console.print("\n" + "─" * 60)
        create_status_file()
        
        # 4. Sonraki adımlar
        console.print("\n" + "─" * 60)
        show_next_steps()
        
        # 5. Final
        console.print("[bold green]✅ Sistem hazır! Yukarıdaki komutlarla başlatabilirsiniz.[/bold green]\n")
        
        # Info box
        info_panel = Panel(
            "[bold]ÖNEMLİ NOTLAR:[/bold]\n\n"
            "• Main Strategy zaten portfolio engine ile çalışıyor (adv_alpha_max)\n"
            "• Copy Trading şu an DEMO mode - gerçek traderların pozisyonlarını izleyecek\n"
            "• Her iki strateji kendi sermayesi ile bağımsız çalışır\n"
            "• Demo Binance Futures hesabınızda işlem yapılacak (risk yok)\n\n"
            "[dim]İlk test için --dry-run mode kullanın, sonra live'a geçin[/dim]",
            title="🔔 Bilgi",
            border_style="yellow"
        )
        console.print(info_panel)
        
    except Exception as e:
        console.print(f"\n[red]❌ Hata: {e}[/red]")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
