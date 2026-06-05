#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 BASİT TRADER VERİ TOPLAMA (Sadece Binance Public API)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Web scraping olmadan, sadece Binance Public API ile bilinen UID'lerden veri toplar.

Kullanım:
    python scripts/collect_simple.py
"""

import sys
import os
import asyncio
import json
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance_futures_trader.free_trader_sources import BinancePublicAPI
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel

console = Console()

# Bilinen gerçek trader UID'leri (Binance leaderboard'dan)
KNOWN_TRADER_UIDS = [
    "3AFFCB67ED4F1D1D8437BA17F4E8E5ED",  # StellarMom - ROI: 154%
    "0C2123F5688F316245836C60A66F8240",  # High ROI trader
    "E5C4F8A5E3B95BC91DFD3E1C8D9E2C4A",  # Example UID
    "B4D6E8F2A7C9D1E3F5A7B9C1D3E5F7A9",  # Example UID
    "C7E9F1A3B5D7E9F1A3B5C7D9E1F3A5B7",  # Example UID
]


async def collect_traders_simple(max_traders: int = 50):
    """Basit veri toplama - sadece Binance Public API"""
    
    console.print(Panel.fit(
        "[bold cyan]🎯 BASİT VERİ TOPLAMA[/bold cyan]\n\n"
        "Sadece Binance Public API kullanılıyor (web scraping yok)",
        border_style="cyan"
    ))
    
    api = BinancePublicAPI()
    output_dir = Path("data/real_traders")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    traders_data = []
    
    console.print(f"\n[cyan]📊 {len(KNOWN_TRADER_UIDS)} bilinen trader için veri toplanıyor...[/cyan]\n")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Processing traders...", total=len(KNOWN_TRADER_UIDS))
        
        for uid in KNOWN_TRADER_UIDS:
            try:
                # Profil bilgisi
                profile = await api.get_trader_profile(uid)
                
                if not profile:
                    progress.advance(task)
                    continue
                
                trader_info = {
                    "uid": uid,
                    "nickname": profile.get("nickName", "Unknown"),
                    "source": "binance_public_api",
                    "roi": profile.get("roi"),
                    "pnl": profile.get("pnl"),
                    "win_rate": profile.get("winRate"),
                    "follower_count": profile.get("followerCount"),
                    "days_active": profile.get("daysActive"),
                    "sharpe_ratio": profile.get("sharpeRatio"),
                    "max_drawdown": profile.get("maxDrawDown"),
                    "um_margin_balance": profile.get("umMarginBalance"),
                    "position_shared": profile.get("isPositionShared", False),
                    "collected_at": int(time.time() * 1000)
                }
                
                # Data quality score
                filled_fields = sum([
                    bool(trader_info.get("roi")),
                    bool(trader_info.get("pnl")),
                    bool(trader_info.get("follower_count")),
                    trader_info.get("position_shared", False),
                    bool(trader_info.get("win_rate")),
                    bool(trader_info.get("days_active"))
                ])
                trader_info["data_quality_score"] = (filled_fields / 6) * 100
                
                # Pozisyonları topla
                if trader_info["position_shared"]:
                    positions = await api.get_trader_positions(uid)
                    if positions:
                        pos_file = output_dir / f"positions_{uid}.json"
                        with open(pos_file, "w", encoding="utf-8") as f:
                            json.dump(positions, f, indent=2, ensure_ascii=False)
                        trader_info["positions_count"] = len(positions)
                        trader_info["positions_file"] = str(pos_file)
                
                # Performans geçmişi
                history = await api.get_trader_history(uid)
                if history and history.get("performanceRetList"):
                    hist_file = output_dir / f"history_{uid}.json"
                    with open(hist_file, "w", encoding="utf-8") as f:
                        json.dump(history, f, indent=2, ensure_ascii=False)
                    trader_info["history_file"] = str(hist_file)
                
                traders_data.append(trader_info)
                console.print(f"[green]✓ {trader_info['nickname']}: ROI={trader_info['roi']:.1f}%[/green]")
                
            except Exception as e:
                console.print(f"[yellow]⚠️  Error for UID {uid}: {e}[/yellow]")
            
            progress.advance(task)
            await asyncio.sleep(0.5)  # Rate limiting
    
    await api.close()
    
    # Kaydet
    if traders_data:
        output_file = output_dir / "simple_traders.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(traders_data, f, indent=2, ensure_ascii=False)
        
        console.print(f"\n[green]✓ {len(traders_data)} traders saved to:[/green]")
        console.print(f"[cyan]  {output_file}[/cyan]\n")
        
        # Özet
        with_positions = sum(1 for t in traders_data if t.get("positions_count", 0) > 0)
        with_history = sum(1 for t in traders_data if "history_file" in t)
        avg_roi = sum(t.get("roi", 0) for t in traders_data) / len(traders_data)
        
        console.print(Panel.fit(
            f"[bold green]✓ VERİ TOPLAMA TAMAMLANDI[/bold green]\n\n"
            f"Toplam trader: {len(traders_data)}\n"
            f"Pozisyon paylaşanlar: {with_positions}\n"
            f"Performans geçmişi olanlar: {with_history}\n"
            f"Ortalama ROI: {avg_roi:.1f}%",
            border_style="green"
        ))
        
        # En iyi trader
        if traders_data:
            best = max(traders_data, key=lambda x: x.get("roi", 0) or 0)
            console.print(f"\n[bold yellow]🏆 En İyi Trader:[/bold yellow]")
            console.print(f"  Nickname: {best['nickname']}")
            console.print(f"  ROI: {best['roi']:.1f}%")
            console.print(f"  Win Rate: {(best.get('win_rate', 0) * 100):.1f}%")
            console.print(f"  UID: {best['uid']}\n")
    else:
        console.print("[red]✗ Hiç trader verisi toplanamadı.[/red]")


if __name__ == "__main__":
    asyncio.run(collect_traders_simple())
