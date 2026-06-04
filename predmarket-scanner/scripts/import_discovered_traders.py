#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📥 KEŞFEDİLEN TRADERLARI İÇE AKTAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

discover_traders.py ile bulunan traderları tracked_traders.json'a aktarır.

Kullanım:
    python scripts/import_discovered_traders.py [--min-roi 50] [--min-wr 0.55]
"""

import sys
import os
import json
import time
from pathlib import Path
import argparse

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def load_discovered_traders(file_path: str = "data/real_traders/discovered_traders.json"):
    """Keşfedilen traderları yükle"""
    path = Path(file_path)
    if not path.exists():
        console.print(f"[red]✗ Dosya bulunamadı: {path}[/red]")
        console.print("\n[yellow]Önce trader keşfi yapmalısın:[/yellow]")
        console.print("  python scripts/discover_traders.py")
        return []
    
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def filter_traders(traders, min_roi: float = 50.0, min_wr: float = 0.55):
    """Traderları filtrele"""
    filtered = [
        t for t in traders
        if t.get("roi", 0) >= min_roi
        and (t.get("win_rate") is None or t.get("win_rate", 0) >= min_wr)
    ]
    return filtered


def import_to_tracked(traders):
    """tracked_traders.json'a aktar"""
    tracked_file = Path("data/copy_trading/tracked_traders.json")
    tracked_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Mevcut traderları yükle
    if tracked_file.exists():
        with open(tracked_file, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except:
                existing = {}
    else:
        existing = {}
    
    # Yeni traderları ekle
    added_count = 0
    for trader in traders:
        uid = trader["uid"]
        if uid not in existing:
            existing[uid] = {
                "uid": uid,
                "nickname": trader["nickname"],
                "rank": None,
                "pnl": trader.get("pnl"),
                "roi": trader["roi"],
                "win_rate": trader.get("win_rate"),
                "follower_count": trader.get("followers"),
                "last_update": int(time.time() * 1000),
                "is_active": True,
                "min_position_usd": 100.0,
                "max_position_usd": 1000.0,
                "copy_multiplier": 1.0,
                "auto_discovered": True,
                "discovery_source": trader.get("source", "auto_discovery")
            }
            added_count += 1
    
    # Kaydet
    with open(tracked_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    
    return added_count, len(existing)


def main():
    parser = argparse.ArgumentParser(description="Keşfedilen traderları içe aktar")
    parser.add_argument("--min-roi", type=float, default=50.0, help="Minimum ROI (default: 50)")
    parser.add_argument("--min-wr", type=float, default=0.55, help="Minimum Win Rate (default: 0.55)")
    parser.add_argument("--source", default="data/real_traders/discovered_traders.json", help="Kaynak dosya")
    
    args = parser.parse_args()
    
    console.print(Panel.fit(
        "[bold cyan]📥 TRADER İÇE AKTARMA[/bold cyan]\n\n"
        f"Minimum ROI: {args.min_roi}%\n"
        f"Minimum Win Rate: {args.min_wr * 100}%",
        border_style="cyan"
    ))
    
    # Yükle
    traders = load_discovered_traders(args.source)
    if not traders:
        return
    
    console.print(f"\n[cyan]📊 {len(traders)} trader bulundu[/cyan]")
    
    # Filtrele
    filtered = filter_traders(traders, args.min_roi, args.min_wr)
    console.print(f"[green]✓ {len(filtered)} trader kriterleri karşılıyor[/green]\n")
    
    if not filtered:
        console.print("[yellow]⚠️  Kriterleri karşılayan trader yok. Filtreyi gevşet:[/yellow]")
        console.print("  python scripts/import_discovered_traders.py --min-roi 30 --min-wr 0.5")
        return
    
    # Tablo göster
    table = Table(title="İçe Aktarılacak Traderlar", show_header=True, header_style="bold cyan")
    table.add_column("Nickname", style="green")
    table.add_column("ROI", justify="right", style="yellow")
    table.add_column("Win Rate", justify="right", style="cyan")
    table.add_column("Followers", justify="right", style="magenta")
    
    for t in sorted(filtered, key=lambda x: x.get("roi", 0), reverse=True)[:20]:
        table.add_row(
            t["nickname"],
            f"{t['roi']:.1f}%",
            f"{(t.get('win_rate', 0) * 100):.1f}%" if t.get("win_rate") else "N/A",
            str(t.get("followers", "N/A"))
        )
    
    console.print(table, "\n")
    
    # Aktar
    added, total = import_to_tracked(filtered)
    
    console.print(Panel.fit(
        f"[bold green]✅ İÇE AKTARILDI[/bold green]\n\n"
        f"Yeni eklenen: {added}\n"
        f"Toplam trader: {total}",
        border_style="green"
    ))
    
    console.print("\n[bold yellow]Sonraki adım:[/bold yellow]")
    console.print("  python scripts/run_copy_trader.py monitor  # İzlemeye başla")


if __name__ == "__main__":
    main()
