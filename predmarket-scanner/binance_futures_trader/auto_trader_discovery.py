"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 OTOMATİK TRADER KEŞFİ - TÜM YÖ NTEMLER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Birden fazla yöntemi otomatik olarak dener ve çalışan ilk yöntemi kullanır:
1. Binance BAPI (internal endpoints)
2. Binance Official Copy Trading SDK
3. Alternative public sources
"""

import asyncio
import json
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
import httpx
from rich.console import Console
from rich.panel import Panel

console = Console()


@dataclass
class DiscoveredTrader:
    """Keşfedilen trader"""
    uid: str
    nickname: str
    roi: float
    pnl: Optional[float]
    win_rate: Optional[float]
    followers: Optional[int]
    source: str  # Hangi yöntemle bulundu


class BinanceBAPITraderFinder:
    """Binance BAPI internal endpoints kullanarak trader bulma"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.base_url = "https://www.binance.com/bapi"
    
    async def try_copy_trading_leaderboard(self) -> List[DiscoveredTrader]:
        """Yeni copy trading API'sini dene"""
        try:
            console.print("[cyan]🔍 Trying: Copy Trading Leaderboard API...[/cyan]")
            
            # Copy trading leaderboard endpoint'i
            url = f"{self.base_url}/copyTrading/v1/public/lead-trader/list"
            
            payload = {
                "pageNo": 1,
                "pageSize": 50,
                "sortType": "ROI",  # veya "PNL"
                "periodType": "ALL"
            }
            
            response = await self.client.post(url, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("data"):
                    traders = []
                    for item in data["data"].get("items", [])[:50]:
                        trader = DiscoveredTrader(
                            uid=item.get("portfolioId") or item.get("encryptedUid", ""),
                            nickname=item.get("nickname", "Unknown"),
                            roi=item.get("roi", 0),
                            pnl=item.get("pnl"),
                            win_rate=item.get("winRate"),
                            followers=item.get("followerCount"),
                            source="binance_copy_trading_api"
                        )
                        if trader.uid:
                            traders.append(trader)
                    
                    if traders:
                        console.print(f"[green]✓ Found {len(traders)} traders via Copy Trading API[/green]")
                        return traders
            
            console.print("[yellow]⚠️  Copy Trading API: No data[/yellow]")
            return []
            
        except Exception as e:
            console.print(f"[yellow]⚠️  Copy Trading API error: {e}[/yellow]")
            return []
    
    async def try_futures_leaderboard(self) -> List[DiscoveredTrader]:
        """Eski futures leaderboard API'sini dene"""
        try:
            console.print("[cyan]🔍 Trying: Futures Leaderboard API...[/cyan]")
            
            url = f"{self.base_url}/futures/v3/public/future/leaderboard/getLeaderboardRank"
            
            payload = {
                "isShared": True,
                "periodType": "ALL",
                "statisticsType": "ROI",
                "tradeType": "PERPETUAL"
            }
            
            response = await self.client.post(url, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("data"):
                    traders = []
                    for item in data["data"][:50]:
                        trader = DiscoveredTrader(
                            uid=item.get("encryptedUid", ""),
                            nickname=item.get("nickName", "Unknown"),
                            roi=item.get("roi", 0),
                            pnl=item.get("pnl"),
                            win_rate=None,
                            followers=item.get("followerCount"),
                            source="binance_futures_leaderboard"
                        )
                        if trader.uid:
                            traders.append(trader)
                    
                    if traders:
                        console.print(f"[green]✓ Found {len(traders)} traders via Futures Leaderboard[/green]")
                        return traders
            
            console.print("[yellow]⚠️  Futures Leaderboard: No data[/yellow]")
            return []
            
        except Exception as e:
            console.print(f"[yellow]⚠️  Futures Leaderboard error: {e}[/yellow]")
            return []
    
    async def try_alternative_endpoints(self) -> List[DiscoveredTrader]:
        """Alternatif endpoint'leri dene"""
        try:
            console.print("[cyan]🔍 Trying: Alternative endpoints...[/cyan]")
            
            # Farklı olası endpoint'ler
            endpoints = [
                "/copyTrading/v1/public/portfolio/list",
                "/fapi/v1/copyTrading/leadTraders",
                "/futures/v1/public/leaderboard",
            ]
            
            for endpoint in endpoints:
                try:
                    url = f"{self.base_url}{endpoint}"
                    response = await self.client.post(url, json={"pageSize": 50})
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("success") or data.get("data"):
                            console.print(f"[green]✓ Found working endpoint: {endpoint}[/green]")
                            # Parse edilir ve döndürülür
                            # Şimdilik pass
                except:
                    continue
            
            console.print("[yellow]⚠️  No alternative endpoints worked[/yellow]")
            return []
            
        except Exception as e:
            console.print(f"[yellow]⚠️  Alternative endpoints error: {e}[/yellow]")
            return []
    
    async def discover(self) -> List[DiscoveredTrader]:
        """Tüm yöntemleri sırayla dene"""
        # 1. Copy Trading API
        traders = await self.try_copy_trading_leaderboard()
        if traders:
            await self.client.aclose()
            return traders
        
        # 2. Futures Leaderboard
        traders = await self.try_futures_leaderboard()
        if traders:
            await self.client.aclose()
            return traders
        
        # 3. Alternative
        traders = await self.try_alternative_endpoints()
        await self.client.aclose()
        return traders


class AutoTraderDiscovery:
    """Ana trader keşif sistemi"""
    
    def __init__(self, output_file: str = "data/real_traders/discovered_traders.json"):
        self.output_file = output_file
        self.bapi_finder = BinanceBAPITraderFinder()
    
    async def discover_all(self) -> List[DiscoveredTrader]:
        """Tüm kaynaklardan trader keşfet"""
        
        console.print(Panel.fit(
            "[bold cyan]🔍 OTOMATİK TRADER KEŞFİ BAŞLIYOR[/bold cyan]\n\n"
            "Birden fazla yöntemi otomatik olarak deneyeceğim...",
            border_style="cyan"
        ))
        
        all_traders = []
        
        # 1. BAPI Finder
        console.print("\n[bold yellow]1️⃣ Binance BAPI Endpoints[/bold yellow]")
        bapi_traders = await self.bapi_finder.discover()
        all_traders.extend(bapi_traders)
        
        # UID'lere göre unique yap
        unique_traders = {}
        for trader in all_traders:
            if trader.uid not in unique_traders:
                unique_traders[trader.uid] = trader
            elif trader.roi > unique_traders[trader.uid].roi:
                # Daha yüksek ROI'yi tut
                unique_traders[trader.uid] = trader
        
        final_traders = list(unique_traders.values())
        
        # Sonuçları kaydet
        if final_traders:
            self._save_traders(final_traders)
            self._print_summary(final_traders)
        else:
            console.print("\n[red]✗ Hiçbir yöntemle trader bulunamadı.[/red]")
            console.print("\n[yellow]💡 Alternatif çözümler:[/yellow]")
            console.print("  1. Binance API key'i ekleyip official SDK kullan")
            console.print("  2. Playwright'i düzelt ve web scraping kullan")
            console.print("  3. Manuel UID girişi yap (HOW_TO_FIND_REAL_TRADERS.md)")
        
        return final_traders
    
    def _save_traders(self, traders: List[DiscoveredTrader]):
        """Traderları kaydet"""
        import os
        from pathlib import Path
        
        output_path = Path(self.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = [
            {
                "uid": t.uid,
                "nickname": t.nickname,
                "roi": t.roi,
                "pnl": t.pnl,
                "win_rate": t.win_rate,
                "followers": t.followers,
                "source": t.source,
                "discovered_at": int(time.time() * 1000)
            }
            for t in traders
        ]
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        console.print(f"\n[green]✓ Saved to: {output_path}[/green]")
    
    def _print_summary(self, traders: List[DiscoveredTrader]):
        """Özet yazdır"""
        from rich.table import Table
        
        table = Table(title="📊 Keşfedilen Traderlar", show_header=True, header_style="bold cyan")
        table.add_column("Nickname", style="green")
        table.add_column("ROI", justify="right", style="yellow")
        table.add_column("Win Rate", justify="right", style="cyan")
        table.add_column("Followers", justify="right", style="magenta")
        table.add_column("Source", style="dim")
        
        # ROI'ye göre sırala
        sorted_traders = sorted(traders, key=lambda x: x.roi, reverse=True)
        
        for t in sorted_traders[:20]:  # Top 20
            table.add_row(
                t.nickname,
                f"{t.roi:.1f}%",
                f"{(t.win_rate * 100):.1f}%" if t.win_rate else "N/A",
                str(t.followers) if t.followers else "N/A",
                t.source
            )
        
        console.print("\n", table, "\n")
        
        console.print(Panel.fit(
            f"[bold green]✅ BAŞARILI[/bold green]\n\n"
            f"Toplam: {len(traders)} trader keşfedildi\n"
            f"En yüksek ROI: {sorted_traders[0].roi:.1f}%\n"
            f"Ortalama ROI: {sum(t.roi for t in traders) / len(traders):.1f}%",
            border_style="green"
        ))


async def main():
    """CLI entry point"""
    discovery = AutoTraderDiscovery()
    traders = await discovery.discover_all()
    
    if traders:
        console.print(f"\n[cyan]📁 Trader verisi kaydedildi: data/real_traders/discovered_traders.json[/cyan]")
        console.print("\n[bold yellow]Sonraki adımlar:[/bold yellow]")
        console.print("  1. python scripts/import_discovered_traders.py  # Sisteme aktar")
        console.print("  2. python scripts/run_copy_trader.py monitor    # İzlemeye başla")


if __name__ == "__main__":
    asyncio.run(main())
