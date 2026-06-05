#!/usr/bin/env python3
"""
Manuel Trader Ekleme Scripti
=============================
Binance Futures leaderboard'dan bulduğunuz başarılı traderları
takip listesine manuel olarak ekler.

Trader UID'sini nasıl bulursunuz:
1. https://www.binance.com/en/futures-activity/leaderboard adresini açın
2. Bir trader'a tıklayın
3. URL'den encrypted UID'yi kopyalayın:
   https://www.binance.com/en/futures-activity/leaderboard?type=myProfile&encryptedUid=BURASI
   
Kullanım:
    python scripts/add_trader.py --uid "ABC123..." --nickname "CryptoKing" --roi 85.5
"""
import json
import sys
from pathlib import Path
from datetime import datetime
import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

console = Console()
app = typer.Typer()

TRADERS_FILE = Path("data/copy_trading/tracked_traders.json")


def load_traders():
    """Mevcut traderları yükle"""
    if not TRADERS_FILE.exists():
        TRADERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        return {}
    
    with open(TRADERS_FILE) as f:
        return json.load(f)


def save_traders(traders):
    """Traderları kaydet"""
    TRADERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRADERS_FILE, "w") as f:
        json.dump(traders, f, indent=2)


@app.command()
def add(
    uid: str = typer.Option(..., "--uid", help="Trader'ın encrypted UID'si"),
    nickname: str = typer.Option(..., "--nickname", help="Trader'ın nickname'i"),
    roi: float = typer.Option(0.0, "--roi", help="Trader'ın ROI'si (%)"),
    rank: int = typer.Option(999, "--rank", help="Trader'ın leaderboard rank'i"),
    min_position: float = typer.Option(50.0, "--min-position", help="Bu trader için min pozisyon ($)"),
    max_position: float = typer.Option(500.0, "--max-position", help="Bu trader için max pozisyon ($)"),
    multiplier: float = typer.Option(1.0, "--multiplier", help="Pozisyon büyüklüğü çarpanı"),
    active: bool = typer.Option(True, "--active/--inactive", help="Aktif olarak takip et")
):
    """
    Yeni bir trader ekle
    """
    traders = load_traders()
    
    if uid in traders:
        console.print(f"[yellow]⚠️  Trader {nickname} ({uid[:8]}...) zaten listede![/yellow]")
        update = typer.confirm("Güncellemek ister misiniz?")
        if not update:
            return
    
    trader = {
        "uid": uid,
        "nickname": nickname,
        "rank": rank,
        "pnl": 0.0,
        "roi": roi,
        "win_rate": 0.0,  # Manuel eklemede bilinmiyor
        "follower_count": 0,
        "last_update": int(datetime.now().timestamp() * 1000),
        "is_active": active,
        "min_position_usd": min_position,
        "max_position_usd": max_position,
        "copy_multiplier": multiplier
    }
    
    traders[uid] = trader
    save_traders(traders)
    
    console.print(f"[green]✅ Trader eklendi: {nickname} (ROI: {roi}%, Rank: #{rank})[/green]")
    console.print(f"[dim]   UID: {uid}[/dim]")
    console.print(f"[dim]   Position limits: ${min_position} - ${max_position}[/dim]")
    console.print(f"[dim]   Multiplier: {multiplier}x[/dim]")


@app.command()
def remove(
    uid: str = typer.Option(..., "--uid", help="Silinecek trader'ın UID'si")
):
    """
    Bir trader'ı listeden sil
    """
    traders = load_traders()
    
    if uid not in traders:
        console.print(f"[red]❌ Trader {uid[:8]}... bulunamadı[/red]")
        return
    
    nickname = traders[uid]["nickname"]
    del traders[uid]
    save_traders(traders)
    
    console.print(f"[green]✅ Trader silindi: {nickname}[/green]")


@app.command()
def list_traders():
    """
    Tüm tracked traderları listele
    """
    traders = load_traders()
    
    if not traders:
        console.print("[yellow]Henüz tracked trader yok. 'add' komutu ile ekleyin.[/yellow]")
        console.print("\n[dim]Örnek:[/dim]")
        console.print("[dim]python scripts/add_trader.py add --uid YOUR_UID --nickname CryptoKing --roi 85.5[/dim]")
        return
    
    table = Table(title=f"Tracked Traders ({len(traders)})")
    table.add_column("Nickname", style="yellow")
    table.add_column("UID", style="dim")
    table.add_column("ROI %", justify="right", style="green")
    table.add_column("Rank", justify="right")
    table.add_column("Position Limits", justify="right")
    table.add_column("Multiplier", justify="right")
    table.add_column("Active", justify="center")
    
    for uid, trader in traders.items():
        table.add_row(
            trader["nickname"],
            uid[:12] + "...",
            f"{trader['roi']:.1f}",
            f"#{trader['rank']}",
            f"${trader['min_position_usd']:.0f}-${trader['max_position_usd']:.0f}",
            f"{trader['copy_multiplier']}x",
            "✓" if trader["is_active"] else "✗"
        )
    
    console.print(table)


@app.command()
def toggle(
    uid: str = typer.Option(..., "--uid", help="Toggle edilecek trader'ın UID'si")
):
    """
    Bir trader'ı aktif/pasif yap
    """
    traders = load_traders()
    
    if uid not in traders:
        console.print(f"[red]❌ Trader {uid[:8]}... bulunamadı[/red]")
        return
    
    trader = traders[uid]
    trader["is_active"] = not trader["is_active"]
    save_traders(traders)
    
    status = "aktif" if trader["is_active"] else "pasif"
    console.print(f"[green]✅ {trader['nickname']} artık {status}[/green]")


@app.command()
def import_uids(
    file: str = typer.Option(..., "--file", help="UID listesi içeren dosya (her satırda: UID,nickname,roi)"),
    format_type: str = typer.Option("csv", "--format", help="Dosya formatı: csv veya json")
):
    """
    UID listesini dosyadan toplu olarak içe aktar
    
    CSV formatı:
        UID,nickname,roi,rank
        ABC123...,CryptoKing,85.5,1
        DEF456...,TradeMaster,72.3,5
    
    JSON formatı:
        [
          {"uid": "ABC123...", "nickname": "CryptoKing", "roi": 85.5, "rank": 1},
          ...
        ]
    """
    import_file = Path(file)
    if not import_file.exists():
        console.print(f"[red]❌ Dosya bulunamadı: {file}[/red]")
        return
    
    traders = load_traders()
    added = 0
    
    if format_type == "csv":
        with open(import_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                parts = line.split(",")
                if len(parts) < 2:
                    continue
                
                uid = parts[0].strip()
                nickname = parts[1].strip()
                roi = float(parts[2].strip()) if len(parts) > 2 else 0.0
                rank = int(parts[3].strip()) if len(parts) > 3 else 999
                
                if uid not in traders:
                    trader = {
                        "uid": uid,
                        "nickname": nickname,
                        "rank": rank,
                        "pnl": 0.0,
                        "roi": roi,
                        "win_rate": 0.0,
                        "follower_count": 0,
                        "last_update": int(datetime.now().timestamp() * 1000),
                        "is_active": True,
                        "min_position_usd": 50.0,
                        "max_position_usd": 500.0,
                        "copy_multiplier": 1.0
                    }
                    traders[uid] = trader
                    added += 1
    
    elif format_type == "json":
        with open(import_file) as f:
            data = json.load(f)
            for item in data:
                uid = item["uid"]
                if uid not in traders:
                    trader = {
                        "uid": uid,
                        "nickname": item.get("nickname", "Unknown"),
                        "rank": item.get("rank", 999),
                        "pnl": 0.0,
                        "roi": item.get("roi", 0.0),
                        "win_rate": 0.0,
                        "follower_count": 0,
                        "last_update": int(datetime.now().timestamp() * 1000),
                        "is_active": True,
                        "min_position_usd": item.get("min_position_usd", 50.0),
                        "max_position_usd": item.get("max_position_usd", 500.0),
                        "copy_multiplier": item.get("copy_multiplier", 1.0)
                    }
                    traders[uid] = trader
                    added += 1
    
    save_traders(traders)
    console.print(f"[green]✅ {added} yeni trader eklendi[/green]")


if __name__ == "__main__":
    app()
