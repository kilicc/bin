#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚀 HIZLI BAŞLANGIÇ - DEMO TRADER İLE TEST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

API key gerekmeden sistemi test et.
Demo trader'larla copy trading sistemini çalıştır.

Kullanım:
    python scripts/quick_start_demo.py
"""

import json
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def create_demo_traders():
    """Gerçekçi demo trader'lar oluştur"""
    
    demo_traders = {
        "DEMO_BTC_MASTER": {
            "uid": "DEMO_BTC_MASTER",
            "nickname": "BTC Master (DEMO)",
            "rank": 12,
            "pnl": 58420.50,
            "roi": 127.3,
            "win_rate": 0.68,
            "follower_count": 8540,
            "last_update": int(time.time() * 1000),
            "is_active": True,
            "min_position_usd": 200.0,
            "max_position_usd": 1000.0,
            "copy_multiplier": 1.0,
            "auto_discovered": False,
            "description": "BTC uzmanı, trend takibi stratejisi"
        },
        "DEMO_ETH_TRADER": {
            "uid": "DEMO_ETH_TRADER",
            "nickname": "ETH Whale (DEMO)",
            "rank": 25,
            "pnl": 42180.30,
            "roi": 89.5,
            "win_rate": 0.61,
            "follower_count": 5230,
            "last_update": int(time.time() * 1000),
            "is_active": True,
            "min_position_usd": 150.0,
            "max_position_usd": 800.0,
            "copy_multiplier": 1.0,
            "auto_discovered": False,
            "description": "ETH ve altcoin uzmanı"
        },
        "DEMO_SCALPER": {
            "uid": "DEMO_SCALPER",
            "nickname": "Quick Scalper (DEMO)",
            "rank": 45,
            "pnl": 28950.75,
            "roi": 72.1,
            "win_rate": 0.74,
            "follower_count": 3120,
            "last_update": int(time.time() * 1000),
            "is_active": True,
            "min_position_usd": 100.0,
            "max_position_usd": 500.0,
            "copy_multiplier": 0.5,
            "auto_discovered": False,
            "description": "Hızlı scalping stratejisi"
        }
    }
    
    return demo_traders


def save_demo_traders(traders):
    """Demo trader'ları kaydet"""
    output_file = Path("data/copy_trading/tracked_traders.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Mevcut veriyi yükle veya yeni oluştur
    if output_file.exists():
        with open(output_file, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except:
                existing = {}
    else:
        existing = {}
    
    # Demo trader'ları ekle
    for uid, trader in traders.items():
        existing[uid] = trader
    
    # Kaydet
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    
    return output_file


def main():
    console.print(Panel.fit(
        "[bold cyan]🚀 HIZLI BAŞLANGIÇ - DEMO TRADER[/bold cyan]\n\n"
        "API key olmadan sistemi test edebilirsin!\n"
        "Demo trader'larla copy trading sistemini çalıştır.",
        border_style="cyan"
    ))
    
    # Demo trader'ları oluştur
    console.print("\n[cyan]📊 3 Demo Trader oluşturuluyor...[/cyan]")
    traders = create_demo_traders()
    
    # Tablo göster
    table = Table(title="Demo Traderlar", show_header=True, header_style="bold cyan")
    table.add_column("Nickname", style="green")
    table.add_column("ROI", justify="right", style="yellow")
    table.add_column("Win Rate", justify="right", style="cyan")
    table.add_column("Followers", justify="right", style="magenta")
    table.add_column("Strategy", style="dim")
    
    for t in traders.values():
        table.add_row(
            t["nickname"],
            f"{t['roi']:.1f}%",
            f"{t['win_rate']*100:.1f}%",
            f"{t['follower_count']:,}",
            t["description"]
        )
    
    console.print("\n", table, "\n")
    
    # Kaydet
    output_file = save_demo_traders(traders)
    
    console.print(Panel.fit(
        f"[bold green]✅ DEMO TRADERLAR HAZIR[/bold green]\n\n"
        f"Kaydedildi: {output_file}\n\n"
        f"Demo traderlar gerçekçi performans metrikleriyle\n"
        f"sistemini test etmeni sağlar.",
        border_style="green"
    ))
    
    console.print("\n[bold yellow]Sonraki adımlar:[/bold yellow]\n")
    console.print("1. Sistemi kontrol et:")
    console.print("   [cyan]python scripts/add_trader.py list[/cyan]\n")
    console.print("2. Copy trading'i başlat:")
    console.print("   [cyan]python scripts/run_copy_trader.py monitor[/cyan]\n")
    console.print("3. Demo'dan gerçek trader'a geçiş:")
    console.print("   [dim]API key sorununu çözünce gerçek trader ekle[/dim]\n")
    
    console.print("[bold]💡 İpucu:[/bold] Demo trader'lar gerçek pozisyon açmaz,")
    console.print("   sadece sistemi test etmeni sağlar.")


if __name__ == "__main__":
    main()
