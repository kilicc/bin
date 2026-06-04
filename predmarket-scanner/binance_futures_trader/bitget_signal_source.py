"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 BITGET SIGNAL SOURCE → BINANCE EXECUTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bitget API'sinden trader sinyalleri al, Binance Futures'da execute et!

AKIŞ:
1. Bitget'ten trader listesi çek
2. En iyi trader'ları seç (ROI, win rate)
3. Trader'ların pozisyonlarını takip et
4. Sinyalleri Binance Futures'a gönder

AVANTAJLAR:
✅ Bitget'in trader discovery API'si (Binance'de yok!)
✅ Binance'in yüksek likiditesi
✅ Gerçek trader sinyalleri
✅ Manuel UID gerekmez
"""

import hashlib
import hmac
import base64
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
import httpx
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class BitgetTrader:
    """Bitget trader profili"""
    trader_id: str
    nickname: str
    roi: float  # ROI (%)
    pnl: float  # Total PnL
    win_rate: float  # Win rate (%)
    followers: int
    trades_count: int
    max_drawdown: float
    
    def score(self) -> float:
        """Trader kalite skoru"""
        return (
            self.roi * 0.4 +
            self.win_rate * 0.3 +
            min(self.followers / 100, 50) * 0.2 +
            (100 - self.max_drawdown) * 0.1
        )


@dataclass
class BitgetPosition:
    """Bitget trader pozisyonu"""
    trader_id: str
    symbol: str  # BTCUSDT
    side: str  # LONG / SHORT
    entry_price: float
    current_price: float
    size: float
    leverage: int
    pnl: float
    pnl_pct: float
    open_time: int  # timestamp
    
    def to_binance_signal(self) -> Dict:
        """Binance signal formatına çevir"""
        return {
            'symbol': self.symbol,
            'side': 'BUY' if self.side == 'LONG' else 'SELL',
            'entry_price': self.entry_price,
            'quantity': self.size,
            'leverage': self.leverage,
            'source': 'bitget',
            'trader_id': self.trader_id,
            'confidence': self._calculate_confidence()
        }
    
    def _calculate_confidence(self) -> float:
        """Signal confidence score (0-100)"""
        base = 70.0
        
        # PnL bazlı
        if self.pnl_pct > 5:
            base += 15
        elif self.pnl_pct > 2:
            base += 10
        elif self.pnl_pct < -3:
            base -= 20
        
        return max(0, min(100, base))


class BitgetClient:
    """Bitget API client"""
    
    def __init__(self, api_key: str, api_secret: str, passphrase: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.base_url = "https://api.bitget.com"
        self.client = httpx.Client(timeout=30.0)
    
    def _sign(self, timestamp: str, method: str, request_path: str, query_string: str = "", body: str = "") -> str:
        """
        Bitget signature with BASE64 encoding
        
        Format: timestamp + method + requestPath + queryString + body
        """
        # Build message
        if query_string:
            message = timestamp + method + request_path + "?" + query_string + body
        else:
            message = timestamp + method + request_path + body
        
        # HMAC SHA256
        mac = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        )
        
        # BASE64 encode (CRITICAL!)
        return base64.b64encode(mac.digest()).decode()
    
    def _headers(self, method: str, request_path: str, query_string: str = "", body: str = "") -> Dict:
        """Request headers"""
        timestamp = str(int(time.time() * 1000))
        sign = self._sign(timestamp, method, request_path, query_string, body)
        
        return {
            'ACCESS-KEY': self.api_key,
            'ACCESS-SIGN': sign,
            'ACCESS-TIMESTAMP': timestamp,
            'ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json',
            'locale': 'en-US'
        }
    
    def get_futures_traders(
        self,
        limit: int = 50,
        min_roi: float = 10.0,
        min_win_rate: float = 55.0,
        max_mdd: float = 50.0
    ) -> List[BitgetTrader]:
        """
        Futures trader listesi çek (BROKER endpoint - public traders)
        
        GET /api/v2/copy/mix-broker/query-traders
        """
        try:
            path = "/api/v2/copy/mix-broker/query-traders"
            
            # NO params needed for broker endpoint
            params = {}
            
            # Signature WITHOUT query string
            headers = self._headers('GET', path, query_string="")
            
            # Full URL
            url = f"{self.base_url}{path}"
            
            response = self.client.get(url, params=params, headers=headers)
            
            # Debug: print response
            console.print(f"[dim]Bitget API status: {response.status_code}[/dim]")
            if response.status_code != 200:
                console.print(f"[red]Response body: {response.text[:500]}[/red]")
            
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('code') != '00000':
                console.print(f"[red]Bitget API Error: {data.get('code')} - {data.get('msg')}[/red]")
                return []
            
            traders_data = data.get('data', [])
            traders = []
            
            for td in traders_data[:limit]:
                # Parse columnList for performance metrics
                columns = {col['describe']: col['value'] for col in td.get('columnList', [])}
                
                try:
                    roi_str = columns.get('ROI', '0').replace('$', '').replace(',', '')
                    pnl_str = columns.get('Total PnL', '$0').replace('$', '').replace(',', '')
                    win_rate_str = columns.get('Win rate', '0')
                    mdd_str = columns.get('MDD', '0')
                    
                    roi = float(roi_str)
                    pnl = float(pnl_str)
                    win_rate = float(win_rate_str)
                    mdd = float(mdd_str)
                except (ValueError, AttributeError) as e:
                    console.print(f"[yellow]Skipping trader {td.get('traderName', 'Unknown')} - parse error: {e}[/yellow]")
                    continue
                
                # Filter: only good traders
                if roi < min_roi:
                    continue
                if win_rate < min_win_rate:
                    continue
                if mdd > max_mdd:
                    continue
                if td.get('canTrace', 'No') != 'Yes':
                    continue
                
                trader = BitgetTrader(
                    trader_id=td.get('traderId', ''),
                    nickname=td.get('traderName', 'Unknown'),
                    roi=roi,
                    pnl=pnl,
                    win_rate=win_rate,
                    followers=int(td.get('followCount', 0)),
                    trades_count=int(td.get('tradeCount', 0)),
                    max_drawdown=mdd
                )
                traders.append(trader)
            
            console.print(f"[green]✓ Found {len(traders)} quality traders (filtered from {len(traders_data)} total)[/green]")
            console.print(f"[dim]Filters: ROI>{min_roi}%, WinRate>{min_win_rate}%, MDD<{max_mdd}%[/dim]")
            return traders
        
        except Exception as e:
            console.print(f"[red]Error fetching traders: {e}[/red]")
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            return []
    
    def get_trader_positions(
        self,
        trader_id: str,
        product_type: str = "USDT-FUTURES"
    ) -> List[BitgetPosition]:
        """
        Trader'ın current positions
        
        GET /api/v2/copy/mix-follower/query-current-orders
        """
        try:
            path = "/api/v2/copy/mix-follower/query-current-orders"
            params = {
                'traderId': trader_id,
                'productType': product_type
            }
            
            # Build query string
            query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
            
            # Signature with query string
            headers = self._headers('GET', path, query_string=query_string)
            url = f"{self.base_url}{path}"
            
            response = self.client.get(url, params=params, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('code') != '00000':
                return []
            
            positions = []
            for item in data.get('data', {}).get('orders', []):
                position = BitgetPosition(
                    trader_id=trader_id,
                    symbol=str(item.get('symbol', '')),
                    side=str(item.get('side', '')),  # LONG / SHORT
                    entry_price=float(item.get('openPriceAvg', 0)),
                    current_price=float(item.get('markPrice', 0)),
                    size=float(item.get('size', 0)),
                    leverage=int(item.get('leverage', 1)),
                    pnl=float(item.get('achievedProfits', 0)),
                    pnl_pct=float(item.get('profitRate', 0)),
                    open_time=int(item.get('cTime', 0))
                )
                positions.append(position)
            
            return positions
        
        except Exception as e:
            console.print(f"[yellow]⚠️  Error fetching positions for {trader_id}: {e}[/yellow]")
            return []
    
    def close(self):
        """Cleanup"""
        self.client.close()


class BitgetSignalAggregator:
    """
    Bitget'ten signal topla ve en iyi trader'ları takip et
    """
    
    def __init__(
        self,
        bitget_api_key: str,
        bitget_api_secret: str,
        bitget_passphrase: str
    ):
        self.bitget = BitgetClient(
            api_key=bitget_api_key,
            api_secret=bitget_api_secret,
            passphrase=bitget_passphrase
        )
        
        self.tracked_traders: List[BitgetTrader] = []
        self.previous_positions: Dict[str, List[BitgetPosition]] = {}
    
    def discover_best_traders(
        self,
        top_n: int = 10,
        min_roi: float = 10.0,
        min_win_rate: float = 55.0
    ) -> List[BitgetTrader]:
        """
        En iyi trader'ları bul
        
        Args:
            top_n: Kaç trader takip edilecek
            min_roi: Minimum ROI (%)
            min_win_rate: Minimum win rate (%)
        """
        console.print("\n[cyan]🔍 Discovering Bitget traders...[/cyan]")
        
        # Trader listesi çek
        all_traders = self.bitget.get_futures_traders(limit=100)
        
        if not all_traders:
            console.print("[red]❌ No traders found![/red]")
            return []
        
        # Filtrele
        filtered = [
            t for t in all_traders
            if t.roi >= min_roi and t.win_rate >= min_win_rate
        ]
        
        # Score'a göre sırala
        filtered.sort(key=lambda t: t.score(), reverse=True)
        
        # Top N
        best = filtered[:top_n]
        
        # Display
        table = Table(title=f"Top {len(best)} Bitget Traders", show_header=True)
        table.add_column("Rank", style="cyan", width=6)
        table.add_column("Trader", style="yellow")
        table.add_column("ROI %", style="green")
        table.add_column("Win Rate %", style="blue")
        table.add_column("Followers", style="magenta")
        table.add_column("Score", style="bold green")
        
        for i, trader in enumerate(best, 1):
            table.add_row(
                str(i),
                trader.nickname[:20],
                f"{trader.roi:.1f}",
                f"{trader.win_rate:.1f}",
                str(trader.followers),
                f"{trader.score():.1f}"
            )
        
        console.print(table)
        
        self.tracked_traders = best
        return best
    
    def get_new_signals(self) -> List[Dict]:
        """
        Yeni sinyalleri çek (yeni açılan veya değişen pozisyonlar)
        """
        new_signals = []
        
        for trader in self.tracked_traders:
            # Current positions
            current = self.bitget.get_trader_positions(trader.trader_id)
            
            # Previous positions
            previous = self.previous_positions.get(trader.trader_id, [])
            
            # Yeni pozisyonları bul
            prev_symbols = {p.symbol for p in previous}
            
            for pos in current:
                if pos.symbol not in prev_symbols:
                    # Yeni pozisyon açılmış!
                    signal = pos.to_binance_signal()
                    signal['trader_name'] = trader.nickname
                    signal['trader_roi'] = trader.roi
                    signal['trader_wr'] = trader.win_rate
                    
                    new_signals.append(signal)
                    
                    console.print(
                        f"[bold green]📡 NEW SIGNAL from {trader.nickname}:[/bold green]\n"
                        f"  {pos.symbol} {pos.side} @ {pos.entry_price}"
                    )
            
            # Update previous
            self.previous_positions[trader.trader_id] = current
        
        return new_signals
    
    def close(self):
        """Cleanup"""
        self.bitget.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEMO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    import asyncio
    
    # Demo credentials (user should replace)
    BITGET_API_KEY = "your_bitget_api_key"
    BITGET_API_SECRET = "your_bitget_api_secret"
    BITGET_PASSPHRASE = "your_bitget_passphrase"
    
    aggregator = BitgetSignalAggregator(
        bitget_api_key=BITGET_API_KEY,
        bitget_api_secret=BITGET_API_SECRET,
        bitget_passphrase=BITGET_PASSPHRASE
    )
    
    # Discover best traders
    best_traders = aggregator.discover_best_traders(
        top_n=10,
        min_roi=15.0,
        min_win_rate=60.0
    )
    
    console.print(f"\n[green]✅ Tracking {len(best_traders)} traders[/green]")
    
    # Monitor for signals (continuous)
    console.print("\n[cyan]👀 Monitoring for new signals...[/cyan]")
    console.print("[dim](Press Ctrl+C to stop)[/dim]\n")
    
    try:
        while True:
            signals = aggregator.get_new_signals()
            
            if signals:
                console.print(f"[bold]📊 {len(signals)} new signal(s) detected![/bold]")
                for sig in signals:
                    console.print(f"  → {sig}")
            
            time.sleep(30)  # Check every 30s
    
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Stopped monitoring[/yellow]")
    
    finally:
        aggregator.close()
