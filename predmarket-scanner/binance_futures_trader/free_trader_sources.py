"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆓 ÜCRETSİZ TRADER VERİ KAYNAKLARI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Ücret gerektirmeyen yöntemlerle gerçek trader verisi toplama:
1. Binance Public API (BAPI) - Tamamen ücretsiz
2. Web Scraping (Playwright) - Tamamen ücretsiz
3. Public JSON endpoints - Tamamen ücretsiz
"""

import asyncio
import json
import time
from typing import List, Dict, Optional
from pathlib import Path
import httpx
from playwright.async_api import async_playwright
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


class BinanceLeaderboardWebScraper:
    """
    Binance Futures Leaderboard web scraping (Playwright)
    Tamamen ücretsiz, API key gerekmez
    """
    
    def __init__(self):
        self.url = "https://www.binance.com/en/futures-activity/leaderboard"
    
    async def scrape_top_traders(
        self,
        period: str = "MONTHLY",
        max_traders: int = 100
    ) -> List[Dict]:
        """
        Web sayfasından top traderları çek
        """
        console.print(f"[cyan]🌐 Scraping Binance Leaderboard (web)...[/cyan]")
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # Leaderboard sayfasına git
                await page.goto(self.url, wait_until="networkidle", timeout=30000)
                
                # Period seçimini yap (DAILY, WEEKLY, MONTHLY, ALL)
                try:
                    await page.click(f'text="{period}"', timeout=5000)
                    await asyncio.sleep(2)
                except:
                    pass
                
                traders = []
                
                # Trader satırlarını bul ve parse et
                rows = await page.query_selector_all('[data-test-id="leaderboard-row"]')
                
                for i, row in enumerate(rows[:max_traders]):
                    try:
                        # Trader bilgilerini çıkar
                        nickname_elem = await row.query_selector('[data-test-id="nickname"]')
                        nickname = await nickname_elem.inner_text() if nickname_elem else f"Trader_{i+1}"
                        
                        roi_elem = await row.query_selector('[data-test-id="roi"]')
                        roi_text = await roi_elem.inner_text() if roi_elem else "0"
                        roi = float(roi_text.replace("%", "").replace(",", "").strip())
                        
                        pnl_elem = await row.query_selector('[data-test-id="pnl"]')
                        pnl_text = await pnl_elem.inner_text() if pnl_elem else "0"
                        pnl = float(pnl_text.replace("$", "").replace(",", "").strip())
                        
                        # UID'yi link'ten çıkar
                        link_elem = await row.query_selector('a[href*="encryptedUid"]')
                        uid = ""
                        if link_elem:
                            href = await link_elem.get_attribute("href")
                            if "encryptedUid=" in href:
                                uid = href.split("encryptedUid=")[1].split("&")[0]
                        
                        if uid:
                            traders.append({
                                "uid": uid,
                                "nickname": nickname,
                                "roi": roi,
                                "pnl": pnl,
                                "rank": i + 1,
                                "source": "web_scrape",
                                "collected_at": int(time.time() * 1000)
                            })
                    
                    except Exception as e:
                        console.print(f"[yellow]⚠️  Row {i} parse error: {e}[/yellow]")
                        continue
                
                await browser.close()
                
                console.print(f"[green]✓ Web Scraping: {len(traders)} traders found[/green]")
                return traders
        
        except Exception as e:
            console.print(f"[red]✗ Web scraping error: {e}[/red]")
            return []


class BinancePublicAPI:
    """
    Binance Public API (BAPI) kullanımı
    Tamamen ücretsiz, authentication gerekmez
    """
    
    def __init__(self):
        self.base_url = "https://www.binance.com/bapi/futures"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def get_trader_profile(self, encrypted_uid: str) -> Optional[Dict]:
        """
        Trader profil detaylarını çek
        """
        try:
            url = f"{self.base_url}/v1/public/future/leaderboard/getOtherLeaderboardBaseInfo"
            payload = {"encryptedUid": encrypted_uid}
            
            response = await self.client.post(url, json=payload)
            if response.status_code != 200:
                return None
            
            data = response.json()
            if not data.get("success"):
                return None
            
            return data.get("data", {})
        
        except Exception as e:
            console.print(f"[yellow]⚠️  API error for {encrypted_uid}: {e}[/yellow]")
            return None
    
    async def get_trader_positions(self, encrypted_uid: str) -> List[Dict]:
        """
        Trader'ın mevcut pozisyonlarını çek
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
            
            return data.get("data", {}).get("otherPositionRetList", [])
        
        except Exception as e:
            console.print(f"[yellow]⚠️  Positions API error: {e}[/yellow]")
            return []
    
    async def get_trader_history(self, encrypted_uid: str, days: int = 90) -> Dict:
        """
        Trader'ın performans geçmişini çek (ROI history)
        """
        try:
            url = f"{self.base_url}/v1/public/future/leaderboard/getOtherPerformance"
            payload = {
                "encryptedUid": encrypted_uid,
                "tradeType": "PERPETUAL"
            }
            
            response = await self.client.post(url, json=payload)
            if response.status_code != 200:
                return {}
            
            data = response.json()
            if not data.get("success"):
                return {}
            
            return data.get("data", {})
        
        except Exception as e:
            console.print(f"[yellow]⚠️  History API error: {e}[/yellow]")
            return {}
    
    async def close(self):
        await self.client.aclose()


class FreeTraderCollector:
    """
    Tamamen ücretsiz kaynaklardan trader verisi toplama
    """
    
    def __init__(self, output_dir: str = "data/real_traders"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.scraper = BinanceLeaderboardWebScraper()
        self.api = BinancePublicAPI()
    
    async def collect_full_dataset(
        self,
        max_traders: int = 100,
        include_positions: bool = True,
        include_history: bool = True
    ):
        """
        Tam veri seti topla (profil + pozisyon + geçmiş)
        """
        console.print("\n[bold cyan]🆓 ÜCRETSİZ VERİ TOPLAMA BAŞLIYOR[/bold cyan]\n")
        
        # 1️⃣ Web scraping ile top traderları bul
        traders = await self.scraper.scrape_top_traders(
            period="MONTHLY",
            max_traders=max_traders
        )
        
        if not traders:
            console.print("[red]✗ No traders found via web scraping.[/red]")
            return
        
        console.print(f"\n[cyan]📊 Enriching data for {len(traders)} traders...[/cyan]\n")
        
        enriched_traders = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Processing traders...", total=len(traders))
            
            for trader in traders:
                uid = trader["uid"]
                nickname = trader["nickname"]
                
                # 2️⃣ API'den detaylı profil bilgisi çek
                profile = await self.api.get_trader_profile(uid)
                if profile:
                    trader.update({
                        "follower_count": profile.get("followerCount"),
                        "days_active": profile.get("daysActive"),
                        "win_rate": profile.get("winRate"),
                        "sharpe_ratio": profile.get("sharpeRatio"),
                        "max_drawdown": profile.get("maxDrawDown"),
                        "um_margin_balance": profile.get("umMarginBalance"),
                        "position_shared": profile.get("isPositionShared", False),
                    })
                
                # 3️⃣ Mevcut pozisyonları çek
                if include_positions and trader.get("position_shared"):
                    positions = await self.api.get_trader_positions(uid)
                    if positions:
                        # Pozisyonları kaydet
                        pos_file = self.output_dir / f"positions_{uid}.json"
                        with open(pos_file, "w", encoding="utf-8") as f:
                            json.dump(positions, f, indent=2, ensure_ascii=False)
                        trader["positions_count"] = len(positions)
                        trader["positions_file"] = str(pos_file)
                
                # 4️⃣ Performans geçmişini çek
                if include_history:
                    history = await self.api.get_trader_history(uid)
                    if history:
                        hist_file = self.output_dir / f"history_{uid}.json"
                        with open(hist_file, "w", encoding="utf-8") as f:
                            json.dump(history, f, indent=2, ensure_ascii=False)
                        trader["history_file"] = str(hist_file)
                
                enriched_traders.append(trader)
                progress.advance(task)
                
                # Rate limiting
                await asyncio.sleep(0.5)
        
        # 5️⃣ Tüm veriyi kaydet
        profiles_file = self.output_dir / "free_traders_full.json"
        with open(profiles_file, "w", encoding="utf-8") as f:
            json.dump(enriched_traders, f, indent=2, ensure_ascii=False)
        
        console.print(f"\n[green]✓ {len(enriched_traders)} traders saved to:[/green]")
        console.print(f"[cyan]  {profiles_file}[/cyan]\n")
        
        # Özet
        with_positions = sum(1 for t in enriched_traders if t.get("positions_count", 0) > 0)
        with_history = sum(1 for t in enriched_traders if "history_file" in t)
        
        console.print(f"[green]📊 Summary:[/green]")
        console.print(f"  Total traders: {len(enriched_traders)}")
        console.print(f"  With positions: {with_positions}")
        console.print(f"  With history: {with_history}")
    
    async def close(self):
        await self.api.close()


async def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Ücretsiz kaynaklardan trader verisi toplama")
    parser.add_argument("--max-traders", type=int, default=100)
    parser.add_argument("--no-positions", action="store_true")
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--output-dir", default="data/real_traders")
    
    args = parser.parse_args()
    
    collector = FreeTraderCollector(output_dir=args.output_dir)
    
    try:
        await collector.collect_full_dataset(
            max_traders=args.max_traders,
            include_positions=not args.no_positions,
            include_history=not args.no_history
        )
    finally:
        await collector.close()


if __name__ == "__main__":
    asyncio.run(main())
