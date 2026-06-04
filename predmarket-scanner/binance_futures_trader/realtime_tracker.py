"""
Real-time Position Tracker
===========================
WebSocket kullanarak trader pozisyonlarını gerçek zamanlı takip eder.

Normal polling (60 saniye): Yavaş, gecikmeli
WebSocket yaklaşım: Pozisyon değişikliklerini anında algılar

NOT: Binance'ın trader pozisyonları için public WebSocket'i yok,
     bu yüzden hızlı polling (5-10 saniye) + smart caching kullanacağız.
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Callable
from collections import defaultdict
from rich.console import Console

console = Console()


@dataclass
class PositionSnapshot:
    """Pozisyon snapshot"""
    trader_uid: str
    symbol: str
    side: str
    entry_price: float
    size: float
    leverage: int
    timestamp: int


@dataclass
class PositionEvent:
    """Pozisyon değişikliği event'i"""
    event_type: str  # "OPENED", "CLOSED", "MODIFIED"
    trader_uid: str
    trader_nickname: str
    position: PositionSnapshot
    detected_at: int


class RealtimePositionTracker:
    """
    Gerçek zamanlı pozisyon tracker
    
    Hızlı polling (5-10s) + delta detection ile near-real-time tracking
    """
    
    def __init__(
        self,
        fetch_callback: Callable,  # async function to fetch positions for a trader
        poll_interval_sec: float = 5.0,  # 5 saniye polling
        max_age_sec: float = 30.0  # 30 saniye içinde değişmeyen pozisyon stale
    ):
        self.fetch_callback = fetch_callback
        self.poll_interval_sec = poll_interval_sec
        self.max_age_sec = max_age_sec
        
        # State tracking
        self.last_snapshots: Dict[str, Dict[str, PositionSnapshot]] = defaultdict(dict)
        # trader_uid -> {position_key -> PositionSnapshot}
        
        self.tracked_traders: Dict[str, str] = {}  # uid -> nickname
        
        # Event callbacks
        self.on_position_opened: Optional[Callable] = None
        self.on_position_closed: Optional[Callable] = None
        self.on_position_modified: Optional[Callable] = None
        
        self._running = False
        self._tasks: List[asyncio.Task] = []
    
    def register_trader(self, uid: str, nickname: str):
        """Takip edilecek trader ekle"""
        self.tracked_traders[uid] = nickname
        console.print(f"[green]✓[/green] Registered trader for real-time tracking: {nickname}")
    
    def unregister_trader(self, uid: str):
        """Trader'ı takipten çıkar"""
        if uid in self.tracked_traders:
            nickname = self.tracked_traders.pop(uid)
            console.print(f"[yellow]✗[/yellow] Unregistered trader: {nickname}")
    
    async def start(self):
        """Tracking'i başlat"""
        if self._running:
            console.print("[yellow]⚠️  Tracker already running[/yellow]")
            return
        
        self._running = True
        console.print(f"\n[bold cyan]🔴 Real-time Tracker Started[/bold cyan]")
        console.print(f"  Poll interval: {self.poll_interval_sec}s")
        console.print(f"  Tracking {len(self.tracked_traders)} traders\n")
        
        # Start tracking tasks for each trader
        for uid, nickname in self.tracked_traders.items():
            task = asyncio.create_task(self._track_trader(uid, nickname))
            self._tasks.append(task)
        
        # Monitor task
        monitor_task = asyncio.create_task(self._monitor_health())
        self._tasks.append(monitor_task)
    
    async def stop(self):
        """Tracking'i durdur"""
        if not self._running:
            return
        
        self._running = False
        console.print("\n[yellow]⏹  Stopping real-time tracker...[/yellow]")
        
        for task in self._tasks:
            task.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        
        console.print("[green]✓ Tracker stopped[/green]")
    
    async def _track_trader(self, uid: str, nickname: str):
        """Bir trader'ı sürekli takip et"""
        while self._running:
            try:
                # Fetch current positions
                positions = await self.fetch_callback(uid)
                
                # Convert to snapshots
                current_snapshots = {}
                for pos in positions:
                    key = f"{pos['symbol']}_{pos['side']}"
                    snapshot = PositionSnapshot(
                        trader_uid=uid,
                        symbol=pos['symbol'],
                        side=pos['side'],
                        entry_price=pos.get('entryPrice', 0.0),
                        size=pos.get('amount', 0.0),
                        leverage=pos.get('leverage', 1),
                        timestamp=int(time.time() * 1000)
                    )
                    current_snapshots[key] = snapshot
                
                # Detect changes
                await self._detect_changes(uid, nickname, current_snapshots)
                
                # Update state
                self.last_snapshots[uid] = current_snapshots
                
                # Wait for next poll
                await asyncio.sleep(self.poll_interval_sec)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                console.print(f"[red]❌ Error tracking {nickname}: {e}[/red]")
                await asyncio.sleep(self.poll_interval_sec * 2)
    
    async def _detect_changes(
        self,
        uid: str,
        nickname: str,
        current_snapshots: Dict[str, PositionSnapshot]
    ):
        """Pozisyon değişikliklerini tespit et"""
        previous = self.last_snapshots.get(uid, {})
        
        current_keys = set(current_snapshots.keys())
        previous_keys = set(previous.keys())
        
        # Newly opened positions
        opened_keys = current_keys - previous_keys
        for key in opened_keys:
            snapshot = current_snapshots[key]
            event = PositionEvent(
                event_type="OPENED",
                trader_uid=uid,
                trader_nickname=nickname,
                position=snapshot,
                detected_at=int(time.time() * 1000)
            )
            
            console.print(
                f"[bold green]🟢 OPENED[/bold green] {nickname}: {snapshot.side} "
                f"{snapshot.symbol} @ {snapshot.entry_price:.4f} ({snapshot.leverage}x)"
            )
            
            if self.on_position_opened:
                await self.on_position_opened(event)
        
        # Closed positions
        closed_keys = previous_keys - current_keys
        for key in closed_keys:
            snapshot = previous[key]
            event = PositionEvent(
                event_type="CLOSED",
                trader_uid=uid,
                trader_nickname=nickname,
                position=snapshot,
                detected_at=int(time.time() * 1000)
            )
            
            console.print(
                f"[bold red]🔴 CLOSED[/bold red] {nickname}: {snapshot.side} "
                f"{snapshot.symbol}"
            )
            
            if self.on_position_closed:
                await self.on_position_closed(event)
        
        # Modified positions (size change, etc.)
        common_keys = current_keys & previous_keys
        for key in common_keys:
            curr = current_snapshots[key]
            prev = previous[key]
            
            if abs(curr.size - prev.size) > 0.01:  # Size changed
                event = PositionEvent(
                    event_type="MODIFIED",
                    trader_uid=uid,
                    trader_nickname=nickname,
                    position=curr,
                    detected_at=int(time.time() * 1000)
                )
                
                console.print(
                    f"[yellow]🟡 MODIFIED[/yellow] {nickname}: {curr.side} "
                    f"{curr.symbol} size: {prev.size:.4f} → {curr.size:.4f}"
                )
                
                if self.on_position_modified:
                    await self.on_position_modified(event)
    
    async def _monitor_health(self):
        """Tracker health monitoring"""
        while self._running:
            await asyncio.sleep(60)  # Check every minute
            
            # Count active trackers
            active_count = len([t for t in self._tasks if not t.done()])
            
            console.print(
                f"[dim]⏱️  Tracker health: {active_count - 1}/{len(self.tracked_traders)} "
                f"traders active[/dim]"
            )


class SmartPositionCache:
    """
    Akıllı pozisyon cache
    
    - Sık değişmeyen pozisyonları cache'ler
    - Değişen pozisyonları daha sık poll eder
    - Bandwidth ve rate limit optimizasyonu
    """
    
    def __init__(self, default_ttl_sec: float = 10.0):
        self.default_ttl_sec = default_ttl_sec
        self.cache: Dict[str, Dict] = {}  # trader_uid -> {positions, timestamp, ttl}
    
    def get(self, uid: str) -> Optional[List]:
        """Cache'den al"""
        if uid not in self.cache:
            return None
        
        entry = self.cache[uid]
        age = time.time() - entry["timestamp"]
        
        if age > entry["ttl"]:
            return None  # Expired
        
        return entry["positions"]
    
    def set(self, uid: str, positions: List, ttl: Optional[float] = None):
        """Cache'e kaydet"""
        self.cache[uid] = {
            "positions": positions,
            "timestamp": time.time(),
            "ttl": ttl or self.default_ttl_sec
        }
    
    def adjust_ttl(self, uid: str, factor: float):
        """TTL'yi ayarla (hızlı değişen pozisyonlar için kısalt)"""
        if uid in self.cache:
            current_ttl = self.cache[uid]["ttl"]
            new_ttl = max(2.0, min(60.0, current_ttl * factor))
            self.cache[uid]["ttl"] = new_ttl


async def main():
    """Test"""
    
    # Mock fetch callback
    async def mock_fetch(uid: str) -> List[Dict]:
        """Simulate API call"""
        await asyncio.sleep(0.1)
        
        # Simulate some positions
        import random
        if random.random() > 0.7:
            return [
                {
                    "symbol": "BTCUSDT",
                    "side": "LONG",
                    "entryPrice": 65000.0 + random.random() * 100,
                    "amount": 0.1,
                    "leverage": 5
                }
            ]
        else:
            return []
    
    tracker = RealtimePositionTracker(
        fetch_callback=mock_fetch,
        poll_interval_sec=3.0
    )
    
    # Register callback
    async def on_opened(event: PositionEvent):
        console.print(f"[bold]📥 Event handler: Position opened![/bold]")
    
    async def on_closed(event: PositionEvent):
        console.print(f"[bold]📤 Event handler: Position closed![/bold]")
    
    tracker.on_position_opened = on_opened
    tracker.on_position_closed = on_closed
    
    # Register traders
    tracker.register_trader("TRADER1", "TestTrader1")
    tracker.register_trader("TRADER2", "TestTrader2")
    
    # Start tracking
    await tracker.start()
    
    # Run for 30 seconds
    try:
        await asyncio.sleep(30)
    except KeyboardInterrupt:
        pass
    
    await tracker.stop()


if __name__ == "__main__":
    asyncio.run(main())
