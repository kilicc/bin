#!/usr/bin/env python3
"""Test live signals from Bitget traders"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from binance_futures_trader.bitget_signal_source import BitgetSignalAggregator
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv
import time

console = Console()
load_dotenv()

API_KEY = os.getenv('BITGET_API_KEY')
API_SECRET = os.getenv('BITGET_SECRET_KEY')
PASSPHRASE = os.getenv('BITGET_PASSPHRASE')


def test_live_signals():
    """Test canlı sinyal akışı"""
    console.print("\n[bold cyan]═══ CANLI SİNYAL TESTİ ═══[/bold cyan]\n")
    
    if not all([API_KEY, API_SECRET, PASSPHRASE]):
        console.print("[red]❌ Bitget credentials missing in .env[/red]")
        return
    
    try:
        # 1. Aggregator oluştur
        console.print("[cyan]1️⃣  Bitget Signal Aggregator başlatılıyor...[/cyan]")
        aggregator = BitgetSignalAggregator(
            bitget_api_key=API_KEY,
            bitget_api_secret=API_SECRET,
            bitget_passphrase=PASSPHRASE
        )
        
        # 2. Trader'ları bul
        console.print("\n[cyan]2️⃣  En iyi trader'lar aranıyor...[/cyan]")
        traders = aggregator.discover_best_traders(
            top_n=5,
            min_roi=10.0,
            min_win_rate=55.0
        )
        
        if not traders:
            console.print("[yellow]⚠️  Kaliteli trader bulunamadı (filtreler çok sıkı olabilir)[/yellow]")
            console.print("[dim]Daha düşük filtrelerle tekrar deneyin: min_roi=0, min_win_rate=0[/dim]")
            return
        
        console.print(f"[green]✓ {len(traders)} trader bulundu[/green]\n")
        
        # Trader listesi
        table = Table(title="Takip Edilecek Trader'lar")
        table.add_column("#", style="dim")
        table.add_column("Nickname", style="cyan")
        table.add_column("Trader ID", style="dim")
        table.add_column("ROI %", style="yellow")
        table.add_column("Win Rate %", style="green")
        table.add_column("Followers", style="blue")
        
        for i, trader in enumerate(traders, 1):
            table.add_row(
                str(i),
                trader.nickname,
                trader.trader_id[:20] + "...",
                f"{trader.roi:.1f}",
                f"{trader.win_rate:.1f}",
                str(trader.followers)
            )
        
        console.print(table)
        
        # 3. Canlı sinyalleri al
        console.print("\n[cyan]3️⃣  Canlı pozisyonlar çekiliyor...[/cyan]\n")
        
        # İlk çağrı - mevcut tüm pozisyonları göster
        signals = aggregator.get_new_signals()
        
        console.print(f"[green]✓ {len(signals)} canlı pozisyon bulundu[/green]\n")
        
        if signals:
            # Sinyalleri göster
            sig_table = Table(title="Canlı Pozisyonlar")
            sig_table.add_column("Trader", style="cyan")
            sig_table.add_column("Symbol", style="yellow")
            sig_table.add_column("Side", style="green")
            sig_table.add_column("Entry", style="white")
            sig_table.add_column("Leverage", style="blue")
            sig_table.add_column("Confidence", style="magenta")
            
            for sig in signals[:10]:  # Max 10 göster
                sig_table.add_row(
                    sig.get('trader_name', 'Unknown'),
                    sig['symbol'],
                    sig['side'],
                    f"${sig['entry_price']:.2f}",
                    f"{sig['leverage']}x",
                    f"{sig.get('confidence', 0):.0f}%"
                )
            
            console.print(sig_table)
        
        total_signals = len(signals)
        
        # 4. Sonuç
        console.print(f"\n[bold]═══ SONUÇ ═══[/bold]")
        console.print(f"[green]✓ Toplam {total_signals} canlı sinyal bulundu[/green]")
        
        if total_signals > 0:
            console.print("\n[bold green]🎉 SİSTEM CANLI SİNYAL ALIYOR![/bold green]")
            console.print("\n[bold]Şimdi yapılacak:[/bold]")
            console.print("→ python3 scripts/run_bitget_to_binance.py run")
            console.print("   (Bu sinyaller Binance Futures'ta execute edilecek)")
        else:
            console.print("\n[yellow]⚠️  Trader'ların şu an açık pozisyonu yok[/yellow]")
            console.print("[dim]Bu normal - trader'lar sürekli pozisyon açmaz[/dim]")
            console.print("[dim]Sistem çalıştırıldığında otomatik olarak bekleyecek ve yeni pozisyonları yakalayacak[/dim]")
        
        aggregator.close()
        
    except Exception as e:
        console.print(f"[red]❌ Hata: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


if __name__ == "__main__":
    test_live_signals()
