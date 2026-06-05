#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🧪 VERİ KAYNAKLARI TEST SCRIPT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tüm veri kaynaklarını test eder:
1. Binance Public API (BAPI)
2. Web Scraping (Playwright) - opsiyonel
3. Apify API - opsiyonel

Kullanım:
    python scripts/test_data_sources.py [--all] [--apify] [--web]
"""

import sys
import os
import asyncio
import json
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

console = Console()


async def test_binance_public_api():
    """Binance Public API (BAPI) test"""
    from binance_futures_trader.free_trader_sources import BinancePublicAPI
    
    console.print("\n[bold cyan]═══ Binance Public API Test ═══[/bold cyan]\n")
    
    api = BinancePublicAPI()
    
    # Test UID (gerçek trader)
    test_uid = "3AFFCB67ED4F1D1D8437BA17F4E8E5ED"
    
    try:
        # 1. Trader profili çek
        console.print(f"[yellow]Testing get_trader_profile({test_uid})...[/yellow]")
        profile = await api.get_trader_profile(test_uid)
        
        if profile:
            console.print("[green]✓ Profile fetched successfully[/green]")
            console.print(f"  Nickname: {profile.get('nickName', 'N/A')}")
            console.print(f"  ROI: {profile.get('roi', 'N/A')}%")
            console.print(f"  Followers: {profile.get('followerCount', 'N/A')}")
        else:
            console.print("[red]✗ Profile fetch failed[/red]")
        
        # 2. Pozisyonları çek
        console.print(f"\n[yellow]Testing get_trader_positions({test_uid})...[/yellow]")
        positions = await api.get_trader_positions(test_uid)
        
        if positions:
            console.print(f"[green]✓ {len(positions)} positions fetched[/green]")
            for pos in positions[:3]:
                console.print(f"  {pos['symbol']} {pos.get('side', 'N/A')}")
        else:
            console.print("[yellow]⚠️  No positions or trader not sharing[/yellow]")
        
        # 3. Performans geçmişi çek
        console.print(f"\n[yellow]Testing get_trader_history({test_uid})...[/yellow]")
        history = await api.get_trader_history(test_uid)
        
        if history and history.get("performanceRetList"):
            console.print(f"[green]✓ {len(history['performanceRetList'])} history records[/green]")
        else:
            console.print("[yellow]⚠️  No history available[/yellow]")
        
        await api.close()
        
        console.print("\n[bold green]✓ Binance Public API: WORKING[/bold green]")
        return True
        
    except Exception as e:
        console.print(f"\n[bold red]✗ Binance Public API: FAILED - {e}[/bold red]")
        await api.close()
        return False


async def test_web_scraping():
    """Web scraping test (Playwright)"""
    console.print("\n[bold cyan]═══ Web Scraping Test ═══[/bold cyan]\n")
    
    try:
        from binance_futures_trader.free_trader_sources import BinanceLeaderboardWebScraper
        
        scraper = BinanceLeaderboardWebScraper()
        
        console.print("[yellow]Scraping top 5 traders from leaderboard...[/yellow]")
        console.print("[dim](This may take 10-20 seconds)[/dim]")
        
        traders = await scraper.scrape_top_traders(period="MONTHLY", max_traders=5)
        
        if traders:
            console.print(f"\n[green]✓ {len(traders)} traders scraped[/green]")
            
            table = Table(title="Top Traders")
            table.add_column("Rank", style="cyan")
            table.add_column("Nickname", style="green")
            table.add_column("ROI", justify="right", style="yellow")
            
            for t in traders[:5]:
                table.add_row(
                    str(t.get("rank", "?")),
                    t.get("nickname", "Unknown"),
                    f"{t.get('roi', 0):.2f}%"
                )
            
            console.print(table)
            console.print("\n[bold green]✓ Web Scraping: WORKING[/bold green]")
            return True
        else:
            console.print("\n[yellow]⚠️  No traders scraped (might need debugging)[/yellow]")
            return False
    
    except ImportError:
        console.print("[yellow]⚠️  Playwright not installed. Run: playwright install chromium[/yellow]")
        return False
    except Exception as e:
        console.print(f"\n[bold red]✗ Web Scraping: FAILED - {e}[/bold red]")
        return False


async def test_apify_api():
    """Apify API test"""
    console.print("\n[bold cyan]═══ Apify API Test ═══[/bold cyan]\n")
    
    api_token = os.getenv("APIFY_API_TOKEN")
    
    if not api_token:
        console.print("[yellow]⚠️  APIFY_API_TOKEN not set. Skipping Apify test.[/yellow]")
        console.print("[dim]To test Apify: export APIFY_API_TOKEN=\"your_token\"[/dim]")
        return None
    
    try:
        from binance_futures_trader.real_trader_collector import ApifyCollector
        
        apify = ApifyCollector(api_token=api_token)
        
        console.print("[yellow]Fetching top 5 traders from Apify Leaderboard...[/yellow]")
        console.print("[dim](This may take 20-30 seconds)[/dim]")
        
        traders = await apify.fetch_leaderboard(max_items=5)
        
        if traders:
            console.print(f"\n[green]✓ {len(traders)} traders fetched[/green]")
            
            table = Table(title="Apify Leaderboard")
            table.add_column("Rank", style="cyan")
            table.add_column("Nickname", style="green")
            table.add_column("ROI", justify="right", style="yellow")
            table.add_column("Quality", justify="right", style="magenta")
            
            for t in traders:
                table.add_row(
                    str(t.rank or "?"),
                    t.nickname,
                    f"{t.roi:.2f}%" if t.roi else "N/A",
                    f"{t.data_quality_score:.0f}%"
                )
            
            console.print(table)
            console.print("\n[bold green]✓ Apify API: WORKING[/bold green]")
            
            await apify.close()
            return True
        else:
            console.print("\n[yellow]⚠️  No traders fetched from Apify[/yellow]")
            await apify.close()
            return False
    
    except Exception as e:
        console.print(f"\n[bold red]✗ Apify API: FAILED - {e}[/bold red]")
        return False


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Test veri kaynakları")
    parser.add_argument("--all", action="store_true", help="Tüm testleri çalıştır")
    parser.add_argument("--apify", action="store_true", help="Sadece Apify test")
    parser.add_argument("--web", action="store_true", help="Sadece web scraping test")
    
    args = parser.parse_args()
    
    console.print(Panel.fit(
        "[bold cyan]🧪 VERİ KAYNAKLARI TEST[/bold cyan]\n\n"
        "Bu script tüm veri kaynaklarını test eder.",
        border_style="cyan"
    ))
    
    results = {}
    
    # Binance Public API (her zaman test et)
    results["binance_api"] = await test_binance_public_api()
    
    # Web scraping (--web veya --all ile)
    if args.web or args.all:
        results["web_scraping"] = await test_web_scraping()
    
    # Apify (--apify veya --all ile)
    if args.apify or args.all:
        results["apify_api"] = await test_apify_api()
    
    # Özet
    console.print("\n" + "="*60)
    console.print("[bold cyan]📊 TEST ÖZETİ[/bold cyan]")
    console.print("="*60 + "\n")
    
    for name, result in results.items():
        if result is True:
            console.print(f"  ✅ {name.replace('_', ' ').title()}: [green]PASSED[/green]")
        elif result is False:
            console.print(f"  ❌ {name.replace('_', ' ').title()}: [red]FAILED[/red]")
        else:
            console.print(f"  ⚠️  {name.replace('_', ' ').title()}: [yellow]SKIPPED[/yellow]")
    
    console.print("\n" + "="*60 + "\n")
    
    # Öneri
    if results.get("binance_api"):
        console.print("[bold green]✓ Binance Public API çalışıyor![/bold green]")
        console.print("\n[cyan]Veri toplamak için şunu çalıştır:[/cyan]")
        console.print("[bold]python scripts/collect_free_traders.py --max-traders 50[/bold]\n")
    else:
        console.print("[bold red]⚠️  Binance Public API çalışmıyor. İnternet bağlantınızı kontrol edin.[/bold red]\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Test kullanıcı tarafından durduruldu.[/yellow]")
        sys.exit(0)
