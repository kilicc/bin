"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔄 SIGNAL → POSITION CONVERTER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Signal sağlayıcılardan gelen signalleri Binance positions'a çevirir
ve mevcut copy trading sistemine entegre eder.
"""

import asyncio
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from rich.console import Console

from binance_futures_trader.signal_aggregator import (
    SignalAggregator,
    TradingSignal,
    SignalSource,
    SignalType
)
from binance_futures_trader.copy_trader import (
    CopyTradingEngine,
    BinanceLeaderboardAPI
)

console = Console()


@dataclass
class VirtualTrader:
    """
    Signal sağlayıcıyı virtual trader olarak temsil eder
    """
    trader_id: str  # "telegram_signals", "tradingview_bot", etc
    source: str  # Signal source
    performance_score: float = 75.0  # Default confidence
    total_signals: int = 0
    successful_signals: int = 0
    
    def update_performance(self, success: bool):
        """Performance score güncelle"""
        self.total_signals += 1
        if success:
            self.successful_signals += 1
        
        if self.total_signals > 0:
            self.performance_score = (self.successful_signals / self.total_signals) * 100


class SignalToCopyTrading:
    """
    Signal aggregator + Copy trading engine bridge
    """
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True
    ):
        self.signal_aggregator = SignalAggregator()
        self.copy_engine = CopyTradingEngine(
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet
        )
        
        self.virtual_traders: Dict[str, VirtualTrader] = {}
        self.active_positions: Dict[str, Dict] = {}
    
    def add_signal_source(
        self,
        source_id: str,
        source_type: str,
        **config
    ):
        """
        Yeni signal source ekle
        
        Args:
            source_id: Unique ID (ör: "telegram_crypto_vip")
            source_type: "telegram", "tradingview", "stockapi", etc
            **config: Source-specific config (API keys, etc)
        """
        # Virtual trader oluştur
        trader = VirtualTrader(
            trader_id=source_id,
            source=source_type
        )
        self.virtual_traders[source_id] = trader
        
        # Signal aggregator'a configure et
        if source_type == "stockapi":
            api_key = config.get('api_key')
            if api_key:
                self.signal_aggregator.configure_stockapi(api_key)
        
        console.print(f"[green]✅ Signal source added: {source_id} ({source_type})[/green]")
    
    def signal_to_position(self, signal: TradingSignal) -> Dict:
        """
        TradingSignal → CopyTradingEngine position format
        """
        return {
            'symbol': signal.symbol,
            'positionAmt': signal.quantity or 0.0,
            'entryPrice': signal.entry_price or 0.0,
            'markPrice': signal.entry_price or 0.0,
            'unRealizedProfit': 0.0,
            'side': 'LONG' if signal.signal_type in ['BUY', 'LONG'] else 'SHORT',
            'leverage': signal.leverage or 10,
            'positionSide': 'BOTH',
            # Custom fields
            '_signal_source': signal.source,
            '_take_profit': signal.take_profit,
            '_stop_loss': signal.stop_loss,
            '_confidence': signal.confidence or 70.0,
            '_timestamp': signal.timestamp
        }
    
    async def process_signals(self):
        """Signalleri işle ve position aç"""
        
        # 1. Tüm kaynaklardan signal topla
        signals = await self.signal_aggregator.fetch_all_signals()
        
        console.print(f"[cyan]📡 Received {len(signals)} signals[/cyan]")
        
        # 2. Filtrele
        filtered = self.signal_aggregator.filter_signals(
            signals,
            min_confidence=70.0,
            allowed_symbols=['BTCUSDT', 'ETHUSDT', 'BNBUSDT']  # Whitelist
        )
        
        console.print(f"[cyan]✅ Filtered to {len(filtered)} high-quality signals[/cyan]")
        
        # 3. Her signal için
        for signal in filtered:
            await self.execute_signal(signal)
    
    async def execute_signal(self, signal: TradingSignal):
        """Single signal'i execute et"""
        
        try:
            # Virtual trader ID
            trader_id = f"{signal.source}_{signal.symbol}"
            
            # Position format'a çevir
            position = self.signal_to_position(signal)
            
            # Basit analiz
            confidence = signal.confidence or 75.0
            
            console.print(f"\n[bold cyan]📊 Signal Analysis: {signal.symbol}[/bold cyan]")
            console.print(f"  Source: {signal.source}")
            console.print(f"  Type: {signal.signal_type}")
            console.print(f"  Entry: {signal.entry_price}")
            console.print(f"  Confidence: {confidence:.1f}%")
            
            # Eğer signal kabul edilirse
            if confidence >= 70:
                
                # Position aç (şimdilik simüle et)
                # TODO: Gerçek execution
                result = True
                
                if result and confidence >= 70:
                    console.print(f"[bold green]✅ Position opened: {signal.symbol}[/bold green]")
                    
                    # Track et
                    self.active_positions[signal.symbol] = {
                        'signal': signal,
                        'confidence': confidence,
                        'open_time': time.time()
                    }
                else:
                    console.print(f"[yellow]⚠️  Position execution failed[/yellow]")
            
            else:
                console.print(f"[yellow]⚠️  Signal rejected (low confidence or wrong timing)[/yellow]")
        
        except Exception as e:
            console.print(f"[red]❌ Signal execution error: {e}[/red]")
    
    async def run_continuous(self, interval_seconds: int = 60):
        """
        Sürekli signal monitoring
        
        Args:
            interval_seconds: Signal check interval (default 60s)
        """
        console.print(f"[bold cyan]🚀 Signal → Copy Trading Engine Started[/bold cyan]\n")
        console.print(f"  Check interval: {interval_seconds}s")
        console.print(f"  Active sources: {len(self.virtual_traders)}\n")
        
        iteration = 0
        
        while True:
            try:
                iteration += 1
                console.print(f"\n[bold]━━━ Iteration {iteration} ━━━[/bold]")
                
                # Process signals
                await self.process_signals()
                
                # Monitor open positions
                await self.monitor_positions()
                
                # Wait
                await asyncio.sleep(interval_seconds)
            
            except KeyboardInterrupt:
                console.print("\n[yellow]⚠️  Shutting down...[/yellow]")
                break
            
            except Exception as e:
                console.print(f"[red]❌ Error in main loop: {e}[/red]")
                await asyncio.sleep(10)
        
        # Cleanup
        await self.signal_aggregator.close()
    
    async def monitor_positions(self):
        """Açık positionları monitor et ve TP/SL kontrol et"""
        
        if not self.active_positions:
            return
        
        console.print(f"\n[cyan]📈 Monitoring {len(self.active_positions)} positions[/cyan]")
        
        for symbol, data in list(self.active_positions.items()):
            signal = data['signal']
            
            # Mevcut fiyatı çek
            try:
                # Simüle edilmiş fiyat (TODO: gerçek API)
                current_price = signal.entry_price * 1.01 if signal.entry_price else None
                entry_price = signal.entry_price
                
                if not entry_price or not current_price:
                    continue
                
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                
                # TP check
                if signal.take_profit:
                    for tp in signal.take_profit:
                        if current_price >= tp:
                            console.print(f"[green]🎯 TP HIT: {symbol} @ {current_price}[/green]")
                            # Position kapat
                            # await self.copy_engine.close_position(symbol)
                            del self.active_positions[symbol]
                            break
                
                # SL check
                if signal.stop_loss:
                    if current_price <= signal.stop_loss:
                        console.print(f"[red]🛑 SL HIT: {symbol} @ {current_price}[/red]")
                        # Position kapat
                        # await self.copy_engine.close_position(symbol)
                        del self.active_positions[symbol]
                
                console.print(f"  {symbol}: Entry={entry_price:.2f}, Current={current_price:.2f}, PnL={pnl_pct:+.2f}%")
            
            except Exception as e:
                console.print(f"[yellow]⚠️  Monitor error for {symbol}: {e}[/yellow]")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ÖRNEK KULLANIM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main():
    """Demo"""
    
    # Initialize
    bridge = SignalToCopyTrading(
        api_key="YOUR_BINANCE_API_KEY",
        api_secret="YOUR_BINANCE_API_SECRET",
        testnet=True
    )
    
    # Signal sources ekle
    bridge.add_signal_source(
        source_id="telegram_crypto_vip",
        source_type="telegram"
    )
    
    bridge.add_signal_source(
        source_id="tradingview_strategy",
        source_type="tradingview"
    )
    
    # StockAPI (opsiyonel)
    # bridge.add_signal_source(
    #     source_id="stockapi_signals",
    #     source_type="stockapi",
    #     api_key="YOUR_STOCKAPI_KEY"
    # )
    
    # Continuous monitoring başlat
    await bridge.run_continuous(interval_seconds=60)


if __name__ == "__main__":
    asyncio.run(main())
