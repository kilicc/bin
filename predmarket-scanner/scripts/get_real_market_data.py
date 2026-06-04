#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 GERÇEK BINANCE MARKET VERİSİ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Futures iznin yokken gerçek Binance market verisi çeker.
625+ coin'in real-time fiyat ve volume verisi.

NOT: Bu trader profilleri değil, market data. Trader profilleri için
Futures API iznini aktif etmelisin (GET_REAL_TRADERS.md'ye bak).

Kullanım:
    python scripts/get_real_market_data.py
"""

import json
import time
from pathlib import Path
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def get_real_futures_market_data():
    """Gerçek Binance Futures market verisi çek (public, auth gerektirmez)"""
    
    console.print(Panel.fit(
        "[bold cyan]📊 GERÇEK BINANCE MARKET VERİSİ[/bold cyan]\n\n"
        "625+ Futures coin'in real-time verisi çekiliyor...",
        border_style="cyan"
    ))
    
    client = httpx.Client(timeout=30.0)
    
    try:
        # Binance Futures 24hr ticker (public endpoint)
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        
        console.print("\n[cyan]🔍 Fetching real-time market data...[/cyan]")
        response = client.get(url)
        
        if response.status_code == 200:
            data = response.json()
            
            console.print(f"[green]✓ {len(data)} coin verisi alındı (GERÇEK VERİ)[/green]\n")
            
            # Volume'e göre sırala
            sorted_data = sorted(
                data,
                key=lambda x: float(x.get('quoteVolume', 0)),
                reverse=True
            )
            
            # Top 20 göster
            table = Table(
                title="Top 20 Yüksek Volume Futures (Son 24 Saat)",
                show_header=True,
                header_style="bold cyan"
            )
            table.add_column("#", style="dim")
            table.add_column("Symbol", style="green")
            table.add_column("Price", justify="right", style="yellow")
            table.add_column("24h Change", justify="right", style="cyan")
            table.add_column("24h Volume", justify="right", style="magenta")
            
            for i, coin in enumerate(sorted_data[:20], 1):
                symbol = coin['symbol']
                price = float(coin['lastPrice'])
                change = float(coin['priceChangePercent'])
                volume = float(coin['quoteVolume'])
                
                # Renk değişime göre
                change_color = "green" if change >= 0 else "red"
                
                table.add_row(
                    str(i),
                    symbol,
                    f"${price:,.4f}",
                    f"[{change_color}]{change:+.2f}%[/{change_color}]",
                    f"${volume:,.0f}"
                )
            
            console.print(table, "\n")
            
            # Kaydet
            output_dir = Path("data/real_traders")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / "real_market_data.json"
            
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": int(time.time() * 1000),
                    "data_type": "REAL_BINANCE_FUTURES_24HR",
                    "total_coins": len(data),
                    "top_volume_coins": sorted_data[:50]
                }, f, indent=2, ensure_ascii=False)
            
            console.print(f"[green]✓ Kaydedildi: {output_file}[/green]\n")
            
            # İstatistikler
            total_volume = sum(float(c.get('quoteVolume', 0)) for c in data)
            avg_change = sum(float(c.get('priceChangePercent', 0)) for c in data) / len(data)
            
            console.print(Panel.fit(
                f"[bold green]✅ GERÇEK VERİ ALINDI[/bold green]\n\n"
                f"Toplam Coin: {len(data)}\n"
                f"Toplam 24h Volume: ${total_volume:,.0f}\n"
                f"Ortalama 24h Değişim: {avg_change:+.2f}%\n\n"
                f"[dim]Not: Bu market data. Trader profilleri için\n"
                f"Futures API iznini aktif et (GET_REAL_TRADERS.md)[/dim]",
                border_style="green"
            ))
            
            return sorted_data[:50]
        
        else:
            console.print(f"[red]✗ Error: {response.status_code}[/red]")
            return []
    
    except Exception as e:
        console.print(f"[red]✗ Exception: {e}[/red]")
        return []
    
    finally:
        client.close()


def main():
    # Gerçek market verisi çek
    data = get_real_futures_market_data()
    
    if data:
        console.print("\n[bold yellow]📌 ÖNEMLİ:[/bold yellow]")
        console.print("Bu market data (fiyat, volume, change).")
        console.print("Trader profilleri için:")
        console.print("  1. cat GET_REAL_TRADERS.md")
        console.print("  2. Futures API iznini aktif et")
        console.print("  3. python scripts/discover_with_api_key.py\n")


if __name__ == "__main__":
    main()
