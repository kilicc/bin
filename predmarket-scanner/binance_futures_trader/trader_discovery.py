"""
Otomatik Trader Keşfi - Web Scraping
=====================================
Binance Futures Leaderboard'ından otomatik olarak en iyi traderları tespit eder.

Playwright ile tarayıcı otomasyonu kullanarak gerçek zamanlı veri çeker.
"""
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict
from rich.console import Console

try:
    from playwright.async_api import async_playwright, Page, Browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠️  Playwright not installed. Run: pip install playwright && playwright install chromium")

console = Console()


@dataclass
class TraderStats:
    """Trader istatistikleri"""
    uid: str
    nickname: str
    rank: int
    roi: float  # %
    pnl: float  # $
    win_rate: float  # 0-1
    follower_count: int
    position_shared: bool
    trade_count: int
    avg_leverage: float
    discovered_at: int  # timestamp


class BinanceLeaderboardScraper:
    """
    Binance Futures Leaderboard web scraper
    """
    
    BASE_URL = "https://www.binance.com/en/futures-activity/leaderboard"
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
    
    async def __aenter__(self):
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright not installed")
        
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page()
        
        # Set realistic user agent
        await self.page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
    
    async def fetch_top_traders(
        self,
        period: str = "MONTHLY",  # DAILY, WEEKLY, MONTHLY, ALL
        stat_type: str = "ROI",  # ROI, PNL
        limit: int = 50,
        min_roi: float = 50.0,
        min_win_rate: float = 0.0
    ) -> List[TraderStats]:
        """
        Leaderboard'dan top traderları fetch et
        """
        console.print(f"\n[cyan]🔍 Scraping Binance Leaderboard ({period}, {stat_type})...[/cyan]")
        
        if not self.page:
            raise RuntimeError("Browser not initialized. Use 'async with' context.")
        
        # Navigate to leaderboard
        url = f"{self.BASE_URL}?statisticsType={stat_type}&period={period}"
        console.print(f"[dim]Navigating to: {url}[/dim]")
        
        await self.page.goto(url, wait_until="networkidle", timeout=30000)
        
        # Wait for leaderboard to load
        try:
            await self.page.wait_for_selector(".leaderboard-table", timeout=15000)
        except Exception as e:
            console.print(f"[red]❌ Leaderboard table not found: {e}[/red]")
            return []
        
        # Extract trader data
        traders = []
        
        try:
            # Get all trader rows
            rows = await self.page.query_selector_all(".leaderboard-row, [data-testid='leaderboard-row']")
            
            console.print(f"[blue]Found {len(rows)} trader rows[/blue]")
            
            for idx, row in enumerate(rows[:limit]):
                if idx >= limit:
                    break
                
                try:
                    trader = await self._parse_trader_row(row, idx + 1)
                    
                    if trader and trader.roi >= min_roi and trader.win_rate >= min_win_rate:
                        traders.append(trader)
                        console.print(
                            f"  [green]✓[/green] #{trader.rank} {trader.nickname} - "
                            f"ROI: {trader.roi:.1f}%, WR: {trader.win_rate*100:.1f}%"
                        )
                
                except Exception as e:
                    console.print(f"[yellow]⚠ Error parsing row {idx}: {e}[/yellow]")
                    continue
            
        except Exception as e:
            console.print(f"[red]❌ Error extracting traders: {e}[/red]")
        
        console.print(f"\n[green]✓ Scraped {len(traders)} qualified traders[/green]")
        return traders
    
    async def _parse_trader_row(self, row, rank: int) -> Optional[TraderStats]:
        """Parse a single trader row"""
        try:
            # Extract UID from link
            uid_link = await row.query_selector("a[href*='encryptedUid']")
            if not uid_link:
                return None
            
            href = await uid_link.get_attribute("href")
            uid = self._extract_uid_from_url(href)
            
            # Extract nickname
            nickname_elem = await row.query_selector(".nickname, [data-testid='nickname']")
            nickname = await nickname_elem.inner_text() if nickname_elem else f"Trader{rank}"
            
            # Extract ROI
            roi_elem = await row.query_selector(".roi, [data-testid='roi']")
            roi_text = await roi_elem.inner_text() if roi_elem else "0%"
            roi = self._parse_percentage(roi_text)
            
            # Extract PnL
            pnl_elem = await row.query_selector(".pnl, [data-testid='pnl']")
            pnl_text = await pnl_elem.inner_text() if pnl_elem else "$0"
            pnl = self._parse_dollar_amount(pnl_text)
            
            # Extract Win Rate (may not be visible on main page)
            win_rate = 0.0  # Will be fetched separately if needed
            
            # Extract Follower Count
            follower_elem = await row.query_selector(".followers, [data-testid='followers']")
            follower_text = await follower_elem.inner_text() if follower_elem else "0"
            follower_count = self._parse_number(follower_text)
            
            return TraderStats(
                uid=uid,
                nickname=nickname.strip(),
                rank=rank,
                roi=roi,
                pnl=pnl,
                win_rate=win_rate,
                follower_count=follower_count,
                position_shared=True,  # Assume true for now
                trade_count=0,  # Not available on main page
                avg_leverage=0.0,  # Not available on main page
                discovered_at=int(time.time() * 1000)
            )
        
        except Exception as e:
            console.print(f"[dim red]Error parsing trader row: {e}[/dim red]")
            return None
    
    async def fetch_trader_details(self, uid: str) -> Optional[Dict]:
        """
        Belirli bir trader'ın detay sayfasından ek bilgi çek
        (Win rate, trade count, avg leverage, etc.)
        """
        if not self.page:
            raise RuntimeError("Browser not initialized")
        
        url = f"{self.BASE_URL}?type=myProfile&encryptedUid={uid}"
        
        try:
            await self.page.goto(url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(2)  # Wait for dynamic content
            
            # Extract additional stats
            details = {}
            
            # Win rate
            wr_elem = await self.page.query_selector("[data-testid='win-rate'], .win-rate")
            if wr_elem:
                wr_text = await wr_elem.inner_text()
                details["win_rate"] = self._parse_percentage(wr_text) / 100.0
            
            # Trade count
            tc_elem = await self.page.query_selector("[data-testid='trade-count'], .trade-count")
            if tc_elem:
                tc_text = await tc_elem.inner_text()
                details["trade_count"] = self._parse_number(tc_text)
            
            return details
        
        except Exception as e:
            console.print(f"[dim yellow]⚠ Error fetching details for {uid[:8]}...: {e}[/dim yellow]")
            return None
    
    @staticmethod
    def _extract_uid_from_url(url: str) -> str:
        """Extract encrypted UID from URL"""
        if "encryptedUid=" in url:
            return url.split("encryptedUid=")[1].split("&")[0]
        return ""
    
    @staticmethod
    def _parse_percentage(text: str) -> float:
        """Parse percentage string like '+85.5%' or '85.5%'"""
        try:
            cleaned = text.replace("%", "").replace("+", "").replace(",", "").strip()
            return float(cleaned)
        except:
            return 0.0
    
    @staticmethod
    def _parse_dollar_amount(text: str) -> float:
        """Parse dollar amount like '$1,234.56' or '1.23K'"""
        try:
            text = text.replace("$", "").replace(",", "").strip()
            
            if "K" in text:
                return float(text.replace("K", "")) * 1000
            elif "M" in text:
                return float(text.replace("M", "")) * 1_000_000
            else:
                return float(text)
        except:
            return 0.0
    
    @staticmethod
    def _parse_number(text: str) -> int:
        """Parse number string like '1,234' or '1.2K'"""
        try:
            text = text.replace(",", "").strip()
            
            if "K" in text:
                return int(float(text.replace("K", "")) * 1000)
            elif "M" in text:
                return int(float(text.replace("M", "")) * 1_000_000)
            else:
                return int(text)
        except:
            return 0


class AutoDiscoveryEngine:
    """
    Otomatik trader keşif motoru
    
    - Periyodik olarak leaderboard'ı tarar
    - En iyi traderları tespit eder
    - Kriterlere göre filtreler
    - tracked_traders.json'a ekler
    """
    
    def __init__(
        self,
        data_dir: str = "data/copy_trading",
        min_roi: float = 50.0,
        min_win_rate: float = 0.55,
        min_followers: int = 500,
        max_traders: int = 20,
        refresh_hours: int = 24
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.min_roi = min_roi
        self.min_win_rate = min_win_rate
        self.min_followers = min_followers
        self.max_traders = max_traders
        self.refresh_hours = refresh_hours
        
        self.traders_file = self.data_dir / "tracked_traders.json"
        self.discovery_log_file = self.data_dir / "discovery_log.json"
    
    def load_tracked_traders(self) -> Dict:
        """Mevcut tracked traders'ı yükle"""
        if not self.traders_file.exists():
            return {}
        
        with open(self.traders_file) as f:
            return json.load(f)
    
    def save_tracked_traders(self, traders: Dict):
        """Tracked traders'ı kaydet"""
        with open(self.traders_file, "w") as f:
            json.dump(traders, f, indent=2)
    
    def log_discovery(self, stats: List[TraderStats]):
        """Discovery log'a kaydet"""
        log_entry = {
            "timestamp": int(time.time() * 1000),
            "date": datetime.now().isoformat(),
            "discovered_count": len(stats),
            "traders": [
                {
                    "uid": t.uid,
                    "nickname": t.nickname,
                    "rank": t.rank,
                    "roi": t.roi,
                    "pnl": t.pnl
                }
                for t in stats
            ]
        }
        
        # Append to log
        logs = []
        if self.discovery_log_file.exists():
            with open(self.discovery_log_file) as f:
                logs = json.load(f)
        
        logs.append(log_entry)
        
        # Keep last 30 days
        logs = logs[-30:]
        
        with open(self.discovery_log_file, "w") as f:
            json.dump(logs, f, indent=2)
    
    async def discover_and_update(
        self,
        period: str = "MONTHLY",
        stat_type: str = "ROI",
        enrich_details: bool = False
    ) -> int:
        """
        Traderları keşfet ve güncelle
        
        Returns:
            Eklenen yeni trader sayısı
        """
        console.print("\n[bold cyan]═══ Auto Discovery Starting ═══[/bold cyan]")
        
        async with BinanceLeaderboardScraper(headless=True) as scraper:
            # Fetch traders
            traders = await scraper.fetch_top_traders(
                period=period,
                stat_type=stat_type,
                limit=100,
                min_roi=self.min_roi,
                min_win_rate=0.0  # Will filter after enrichment
            )
            
            if not traders:
                console.print("[yellow]⚠️  No traders found[/yellow]")
                return 0
            
            # Enrich with details (win rate, trade count)
            if enrich_details:
                console.print(f"\n[cyan]📊 Enriching top {min(10, len(traders))} traders with details...[/cyan]")
                for idx, trader in enumerate(traders[:10]):  # Only top 10 to save time
                    details = await scraper.fetch_trader_details(trader.uid)
                    if details:
                        trader.win_rate = details.get("win_rate", 0.0)
                        trader.trade_count = details.get("trade_count", 0)
                    await asyncio.sleep(1)  # Rate limit
            
            # Filter by criteria
            qualified = [
                t for t in traders
                if t.roi >= self.min_roi
                and t.follower_count >= self.min_followers
                and (not enrich_details or t.win_rate >= self.min_win_rate)
            ]
            
            console.print(f"\n[green]✓ {len(qualified)} traders meet criteria[/green]")
            
            # Load existing
            existing = self.load_tracked_traders()
            
            # Update or add
            added = 0
            updated = 0
            
            for trader in qualified[:self.max_traders]:
                trader_data = {
                    "uid": trader.uid,
                    "nickname": trader.nickname,
                    "rank": trader.rank,
                    "pnl": trader.pnl,
                    "roi": trader.roi,
                    "win_rate": trader.win_rate,
                    "follower_count": trader.follower_count,
                    "last_update": trader.discovered_at,
                    "is_active": True,
                    "min_position_usd": 50.0,
                    "max_position_usd": 500.0,
                    "copy_multiplier": 1.0,
                    "auto_discovered": True
                }
                
                if trader.uid in existing:
                    # Update existing
                    existing[trader.uid].update(trader_data)
                    updated += 1
                    console.print(f"  [blue]↻[/blue] Updated: {trader.nickname} (ROI: {trader.roi:.1f}%)")
                else:
                    # Add new
                    existing[trader.uid] = trader_data
                    added += 1
                    console.print(f"  [green]➕[/green] Added: {trader.nickname} (ROI: {trader.roi:.1f}%)")
            
            # Save
            self.save_tracked_traders(existing)
            
            # Log
            self.log_discovery(qualified)
            
            console.print(f"\n[bold green]✓ Discovery Complete: {added} added, {updated} updated[/bold green]")
            
            return added
    
    async def run_periodic_discovery(
        self,
        period: str = "MONTHLY",
        stat_type: str = "ROI"
    ):
        """
        Periyodik discovery döngüsü
        """
        console.print(f"\n[bold cyan]🔄 Starting Periodic Discovery (every {self.refresh_hours}h)[/bold cyan]")
        
        while True:
            try:
                await self.discover_and_update(period=period, stat_type=stat_type, enrich_details=False)
                
                console.print(f"\n[dim]Next discovery in {self.refresh_hours} hours...[/dim]")
                await asyncio.sleep(self.refresh_hours * 3600)
                
            except KeyboardInterrupt:
                console.print("\n[yellow]⏹  Discovery stopped by user[/yellow]")
                break
            except Exception as e:
                console.print(f"\n[red]❌ Discovery error: {e}[/red]")
                await asyncio.sleep(600)  # Wait 10 min on error


async def main():
    """Test / Demo"""
    engine = AutoDiscoveryEngine(
        min_roi=50.0,
        min_win_rate=0.55,
        min_followers=500,
        max_traders=15
    )
    
    # Single discovery
    added = await engine.discover_and_update(period="MONTHLY", stat_type="ROI", enrich_details=False)
    
    console.print(f"\n[bold green]✓ Discovered {added} new traders[/bold green]")


if __name__ == "__main__":
    if not PLAYWRIGHT_AVAILABLE:
        console.print("[red]❌ Playwright not installed![/red]")
        console.print("[yellow]Run: pip install playwright && playwright install chromium[/yellow]")
    else:
        asyncio.run(main())
