"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 GERÇEK TRADER VERİ TOPLAMA SİSTEMİ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Birden fazla kaynaktan gerçek Binance Futures trader verilerini toplar:
1. Apify Binance Futures Leaderboard Scraper
2. Apify Smart Money Trader Positions Tracker
3. Binance Public API (BAPI)
4. Web Scraping (Playwright - yedek yöntem)

Çıktı:
- data/real_traders/profiles.json: Trader profilleri
- data/real_traders/positions_history/: Pozisyon geçmişleri
- data/real_traders/metadata.json: Toplama istatistikleri
"""

import os
import json
import asyncio
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.panel import Panel

console = Console()


@dataclass
class RealTraderProfile:
    """Gerçek trader profil verisi"""
    # Zorunlu alanlar
    uid: str
    nickname: str
    source: str  # "apify_leaderboard", "apify_positions", "binance_bapi", "web_scrape"
    
    # Performans metrikleri
    roi: Optional[float] = None
    pnl: Optional[float] = None
    win_rate: Optional[float] = None
    rank: Optional[int] = None
    
    # Takipçi ve sosyal
    follower_count: Optional[int] = None
    twitter_url: Optional[str] = None
    avatar_url: Optional[str] = None
    
    # İşlem istatistikleri
    days_active: Optional[int] = None
    max_drawdown: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    um_margin_balance: Optional[float] = None
    cm_margin_balance: Optional[float] = None
    
    # Durum
    position_shared: bool = False
    position_history_shared: bool = False
    is_active: bool = True
    
    # Metadata
    last_update: int = 0
    collected_at: int = 0
    data_quality_score: float = 0.0  # 0-100


@dataclass
class TraderPosition:
    """Trader pozisyon verisi (anlık veya geçmiş)"""
    trader_uid: str
    symbol: str
    side: str  # LONG, SHORT
    entry_price: float
    current_price: Optional[float] = None
    amount: float = 0
    leverage: int = 1
    pnl: Optional[float] = None
    roi: Optional[float] = None
    isolated: bool = True
    margin: Optional[float] = None
    liq_price: Optional[float] = None
    timestamp: int = 0
    status: str = "OPEN"  # OPEN, CLOSED


class ApifyCollector:
    """Apify API kullanarak veri toplama"""
    
    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or os.getenv("APIFY_API_TOKEN", "")
        self.base_url = "https://api.apify.com/v2"
        self.client = httpx.AsyncClient(timeout=120.0)
    
    async def fetch_leaderboard(
        self,
        max_items: int = 100,
        trade_type: str = "PERPETUAL",
        statistics_type: str = "ROI",
        period_type: str = "ALL"
    ) -> List[RealTraderProfile]:
        """
        Apify Binance Futures Leaderboard Scraper kullanarak top traderları çek
        Actor: easyapi/binance-futures-leaderboard-scraper
        """
        if not self.api_token:
            console.print("[yellow]⚠️  APIFY_API_TOKEN not set. Skipping Apify leaderboard.[/yellow]")
            return []
        
        console.print(f"[cyan]🔍 Fetching top {max_items} traders from Apify Leaderboard...[/cyan]")
        
        try:
            actor_id = "easyapi/binance-futures-leaderboard-scraper"
            input_data = {
                "maxItems": max_items,
                "tradeType": trade_type,
                "statisticsType": statistics_type,
                "periodType": period_type
            }
            
            # Actor'ü çalıştır
            run_url = f"{self.base_url}/acts/{actor_id}/run-sync-get-dataset-items?token={self.api_token}"
            response = await self.client.post(run_url, json=input_data)
            response.raise_for_status()
            
            items = response.json()
            traders = []
            
            for item in items:
                data = item.get("item", {})
                if not data:
                    continue
                
                profile = RealTraderProfile(
                    uid=data.get("encryptedUid", ""),
                    nickname=data.get("nickName", "Unknown"),
                    source="apify_leaderboard",
                    roi=data.get("roi"),
                    pnl=data.get("pnl"),
                    rank=data.get("rank"),
                    follower_count=data.get("followerCount"),
                    twitter_url=data.get("twitterUrl"),
                    avatar_url=data.get("userPhotoUrl"),
                    position_shared=data.get("positionShared", False),
                    last_update=data.get("updateTime", 0),
                    collected_at=int(time.time() * 1000)
                )
                
                # Data quality score hesapla (kaç alan dolu)
                filled_fields = sum([
                    bool(profile.roi),
                    bool(profile.pnl),
                    bool(profile.rank),
                    bool(profile.follower_count),
                    bool(profile.twitter_url),
                    profile.position_shared
                ])
                profile.data_quality_score = (filled_fields / 6) * 100
                
                traders.append(profile)
            
            console.print(f"[green]✓ Apify Leaderboard: {len(traders)} traders collected[/green]")
            return traders
            
        except Exception as e:
            console.print(f"[red]✗ Apify Leaderboard error: {e}[/red]")
            return []
    
    async def fetch_trader_positions(self, trader_id: str) -> Dict[str, Any]:
        """
        Apify Smart Money Trader Positions Scraper ile trader'ın mevcut pozisyonlarını çek
        Actor: mayanksingh2233/binance-smart-money-trader-positions-tracker-api
        """
        if not self.api_token:
            return {}
        
        try:
            actor_id = "mayanksingh2233/binance-smart-money-trader-positions-tracker-api"
            input_data = {
                "endpoint": "positions",
                "traderId": trader_id,
                "marketType": "UM",
                "page": 1,
                "rows": 20
            }
            
            run_url = f"{self.base_url}/acts/{actor_id}/run-sync-get-dataset-items?token={self.api_token}"
            response = await self.client.post(run_url, json=input_data, timeout=60.0)
            response.raise_for_status()
            
            items = response.json()
            if items:
                return items[0].get("results", {})
            return {}
            
        except Exception as e:
            console.print(f"[yellow]⚠️  Could not fetch positions for {trader_id}: {e}[/yellow]")
            return {}
    
    async def close(self):
        await self.client.aclose()


class BinancePublicCollector:
    """Binance Public API (BAPI) kullanarak veri toplama"""
    
    def __init__(self):
        self.base_url = "https://www.binance.com/bapi/futures"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def fetch_trader_positions(self, encrypted_uid: str) -> List[TraderPosition]:
        """
        Binance BAPI'den trader pozisyonlarını çek (ücretsiz, authentication gerekmez)
        """
        try:
            url = f"{self.base_url}/v2/public/future/leaderboard/getOtherPosition"
            payload = {
                "encryptedUid": encrypted_uid,
                "tradeType": "PERPETUAL"
            }
            
            response = await self.client.post(url, json=payload)
            if response.status_code != 200:
                return []
            
            data = response.json()
            if not data.get("success"):
                return []
            
            positions = []
            for pos_data in data.get("data", {}).get("otherPositionRetList", []):
                position = TraderPosition(
                    trader_uid=encrypted_uid,
                    symbol=pos_data.get("symbol", ""),
                    side="LONG" if pos_data.get("amount", 0) > 0 else "SHORT",
                    entry_price=pos_data.get("entryPrice", 0),
                    current_price=pos_data.get("markPrice"),
                    amount=abs(pos_data.get("amount", 0)),
                    leverage=pos_data.get("leverage", 1),
                    pnl=pos_data.get("pnl"),
                    roi=pos_data.get("roe"),
                    timestamp=pos_data.get("updateTimeStamp", int(time.time() * 1000))
                )
                positions.append(position)
            
            return positions
            
        except Exception as e:
            console.print(f"[yellow]⚠️  Binance BAPI error for {encrypted_uid}: {e}[/yellow]")
            return []
    
    async def close(self):
        await self.client.aclose()


class RealTraderCollector:
    """Ana veri toplama orchestrator"""
    
    def __init__(self, data_dir: str = "data/real_traders"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.profiles_path = self.data_dir / "profiles.json"
        self.metadata_path = self.data_dir / "metadata.json"
        self.positions_dir = self.data_dir / "positions_history"
        self.positions_dir.mkdir(exist_ok=True)
        
        self.apify = ApifyCollector()
        self.binance = BinancePublicCollector()
        
        self.profiles: Dict[str, RealTraderProfile] = {}
        self.metadata: Dict[str, Any] = {}
        
        self._load_existing_data()
    
    def _load_existing_data(self):
        """Mevcut veriyi yükle"""
        if self.profiles_path.exists():
            with open(self.profiles_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.profiles = {
                    uid: RealTraderProfile(**profile_dict)
                    for uid, profile_dict in data.items()
                }
            console.print(f"[green]✓ Loaded {len(self.profiles)} existing trader profiles[/green]")
        
        if self.metadata_path.exists():
            with open(self.metadata_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
    
    def _save_data(self):
        """Veriyi kaydet"""
        # Profilleri kaydet
        with open(self.profiles_path, "w", encoding="utf-8") as f:
            json.dump(
                {uid: asdict(profile) for uid, profile in self.profiles.items()},
                f,
                indent=2,
                ensure_ascii=False
            )
        
        # Metadata kaydet
        self.metadata["last_update"] = int(time.time())
        self.metadata["total_traders"] = len(self.profiles)
        self.metadata["sources"] = list(set(p.source for p in self.profiles.values()))
        
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)
        
        console.print(f"[green]✓ Saved {len(self.profiles)} trader profiles[/green]")
    
    def _save_positions(self, trader_uid: str, positions: List[TraderPosition]):
        """Pozisyonları kaydet"""
        if not positions:
            return
        
        trader_pos_dir = self.positions_dir / trader_uid
        trader_pos_dir.mkdir(exist_ok=True)
        
        # Timestamp'li dosya adı
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pos_file = trader_pos_dir / f"positions_{timestamp}.json"
        
        with open(pos_file, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(pos) for pos in positions],
                f,
                indent=2,
                ensure_ascii=False
            )
    
    async def collect_from_all_sources(
        self,
        max_traders: int = 100,
        fetch_positions: bool = True
    ):
        """
        Tüm kaynaklardan veri topla
        """
        console.print(Panel.fit(
            "[bold cyan]🚀 GERÇEK TRADER VERİ TOPLAMA BAŞLIYOR[/bold cyan]\n"
            f"Hedef: {max_traders} trader\n"
            f"Pozisyon toplama: {'✓' if fetch_positions else '✗'}",
            border_style="cyan"
        ))
        
        start_time = time.time()
        
        # 1️⃣ Apify Leaderboard'dan traderları çek
        apify_traders = await self.apify.fetch_leaderboard(max_items=max_traders)
        
        for trader in apify_traders:
            if trader.uid in self.profiles:
                # Mevcut profili güncelle (daha yeni veri varsa)
                existing = self.profiles[trader.uid]
                if trader.collected_at > existing.collected_at:
                    self.profiles[trader.uid] = trader
            else:
                self.profiles[trader.uid] = trader
        
        # 2️⃣ Pozisyonları topla (isteğe bağlı)
        if fetch_positions and self.profiles:
            console.print(f"\n[cyan]📊 Fetching positions for {len(self.profiles)} traders...[/cyan]")
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                console=console
            ) as progress:
                task = progress.add_task("Collecting positions...", total=len(self.profiles))
                
                for trader_uid, profile in list(self.profiles.items()):
                    if not profile.position_shared:
                        progress.advance(task)
                        continue
                    
                    # Binance BAPI'den pozisyonları çek
                    positions = await self.binance.fetch_trader_positions(trader_uid)
                    
                    if positions:
                        self._save_positions(trader_uid, positions)
                        console.print(f"[green]  ✓ {profile.nickname}: {len(positions)} positions saved[/green]")
                    
                    progress.advance(task)
                    await asyncio.sleep(0.5)  # Rate limiting
        
        # 3️⃣ Veriyi kaydet
        self._save_data()
        
        elapsed = time.time() - start_time
        
        # Özet rapor
        self._print_summary(elapsed)
    
    def _print_summary(self, elapsed_sec: float):
        """Toplama özeti"""
        table = Table(title="📊 Veri Toplama Özeti", show_header=True, header_style="bold cyan")
        table.add_column("Metrik", style="cyan")
        table.add_column("Değer", style="green", justify="right")
        
        table.add_row("Toplam Trader", str(len(self.profiles)))
        table.add_row("Pozisyon Paylaşanlar", str(sum(1 for p in self.profiles.values() if p.position_shared)))
        
        sources = {}
        for p in self.profiles.values():
            sources[p.source] = sources.get(p.source, 0) + 1
        for source, count in sources.items():
            table.add_row(f"  └─ {source}", str(count))
        
        avg_quality = sum(p.data_quality_score for p in self.profiles.values()) / len(self.profiles) if self.profiles else 0
        table.add_row("Ortalama Veri Kalitesi", f"{avg_quality:.1f}%")
        table.add_row("Toplam Süre", f"{elapsed_sec:.1f}s")
        
        console.print("\n", table, "\n")
        
        # Dosya konumları
        console.print(Panel.fit(
            f"[bold green]✓ Veriler kaydedildi[/bold green]\n\n"
            f"📁 Profiller: [cyan]{self.profiles_path}[/cyan]\n"
            f"📁 Pozisyonlar: [cyan]{self.positions_dir}[/cyan]\n"
            f"📁 Metadata: [cyan]{self.metadata_path}[/cyan]",
            border_style="green"
        ))
    
    async def close(self):
        """Temizlik"""
        await self.apify.close()
        await self.binance.close()


async def main():
    """Ana fonksiyon"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gerçek Binance Futures Trader Verisi Toplama")
    parser.add_argument("--max-traders", type=int, default=100, help="Maksimum trader sayısı")
    parser.add_argument("--no-positions", action="store_true", help="Pozisyon toplama (daha hızlı)")
    parser.add_argument("--data-dir", default="data/real_traders", help="Veri dizini")
    
    args = parser.parse_args()
    
    collector = RealTraderCollector(data_dir=args.data_dir)
    
    try:
        await collector.collect_from_all_sources(
            max_traders=args.max_traders,
            fetch_positions=not args.no_positions
        )
    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(main())
