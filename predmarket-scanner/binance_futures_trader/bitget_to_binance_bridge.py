"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌉 BITGET → BINANCE BRIDGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bitget'ten signal al, Binance Futures'da execute et!

FLOW:
1. Bitget API → Best traders keşfet
2. Trader positions'ı monitor et
3. Yeni signal gelince → Binance'de order aç
4. Position management (TP/SL, close)
"""

import asyncio
import time
from typing import Dict, List
from dataclasses import dataclass
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from binance_futures_trader.bitget_signal_source import BitgetSignalAggregator, BitgetTrader
from binance_futures_trader.client import BinanceFuturesClient

console = Console()


@dataclass
class ActivePosition:
    """Binance'de açık pozisyon"""
    symbol: str
    side: str
    entry_price: float
    size: float
    leverage: int
    open_time: float
    source_trader_id: str
    source_trader_name: str
    binance_order_id: str = ""
    
    def pnl_pct(self, current_price: float) -> float:
        """PnL percentage"""
        if self.side == 'BUY':
            return ((current_price - self.entry_price) / self.entry_price) * 100
        else:
            return ((self.entry_price - current_price) / self.entry_price) * 100


class BitgetToBinanceBridge:
    """
    Bitget signals → Binance execution bridge
    """
    
    def __init__(
        self,
        # Bitget credentials
        bitget_api_key: str,
        bitget_api_secret: str,
        bitget_passphrase: str,
        # Binance credentials
        binance_api_key: str = "",
        binance_api_secret: str = "",
        binance_testnet: bool = True,
        # Trading params
        capital_per_trade: float = 100.0,  # USDT
        max_positions: int = 5,
        min_signal_confidence: float = 70.0
    ):
        # Bitget signal source
        self.bitget = BitgetSignalAggregator(
            bitget_api_key=bitget_api_key,
            bitget_api_secret=bitget_api_secret,
            bitget_passphrase=bitget_passphrase
        )
        
        # Binance execution client
        self.binance = BinanceFuturesClient()
        
        # Trading parameters
        self.capital_per_trade = capital_per_trade
        self.max_positions = max_positions
        self.min_signal_confidence = min_signal_confidence
        
        # Active positions
        self.active_positions: Dict[str, ActivePosition] = {}
        
        # Stats
        self.stats = {
            'signals_received': 0,
            'signals_executed': 0,
            'signals_rejected': 0,
            'positions_opened': 0,
            'positions_closed': 0,
            'total_pnl': 0.0
        }
    
    def discover_traders(
        self,
        top_n: int = 10,
        min_roi: float = 15.0,
        min_win_rate: float = 60.0
    ) -> List[BitgetTrader]:
        """
        Bitget'ten en iyi trader'ları bul
        """
        console.print(Panel.fit(
            "[bold cyan]🔍 DISCOVERING BITGET TRADERS[/bold cyan]\n"
            f"Looking for top {top_n} traders...",
            border_style="cyan"
        ))
        
        traders = self.bitget.discover_best_traders(
            top_n=top_n,
            min_roi=min_roi,
            min_win_rate=min_win_rate
        )
        
        if traders:
            console.print(f"\n[green]✅ Found {len(traders)} high-quality traders![/green]")
        else:
            console.print("\n[red]❌ No traders found matching criteria[/red]")
        
        return traders
    
    def process_signal(self, signal: Dict) -> bool:
        """
        Signal'i işle ve Binance'de execute et
        
        Args:
            signal: Bitget'ten gelen signal
        
        Returns:
            True if executed, False if rejected
        """
        self.stats['signals_received'] += 1
        
        symbol = signal['symbol']
        side = signal['side']
        entry_price = signal['entry_price']
        confidence = signal.get('confidence', 70.0)
        trader_id = signal['trader_id']
        trader_name = signal.get('trader_name', 'Unknown')
        
        console.print(f"\n[bold]📡 NEW SIGNAL:[/bold]")
        console.print(f"  Trader: {trader_name}")
        console.print(f"  Symbol: {symbol}")
        console.print(f"  Side: {side}")
        console.print(f"  Entry: ${entry_price:,.2f}")
        console.print(f"  Confidence: {confidence:.1f}%")
        
        # Checks
        
        # 1. Already have position?
        if symbol in self.active_positions:
            console.print(f"[yellow]⚠️  REJECTED: Already have position in {symbol}[/yellow]")
            self.stats['signals_rejected'] += 1
            return False
        
        # 2. Max positions reached?
        if len(self.active_positions) >= self.max_positions:
            console.print(f"[yellow]⚠️  REJECTED: Max positions ({self.max_positions}) reached[/yellow]")
            self.stats['signals_rejected'] += 1
            return False
        
        # 3. Confidence too low?
        if confidence < self.min_signal_confidence:
            console.print(f"[yellow]⚠️  REJECTED: Low confidence ({confidence:.1f}% < {self.min_signal_confidence}%)[/yellow]")
            self.stats['signals_rejected'] += 1
            return False
        
        # Execute on Binance
        try:
            # Calculate position size
            current_price = self.binance.mark_price(symbol.replace('USDT', ''))
            if not current_price:
                current_price = entry_price
            
            leverage = signal.get('leverage', 3)
            size_usd = self.capital_per_trade * leverage
            size = size_usd / current_price
            
            # Round to Binance rules
            coin = symbol.replace('USDT', '')
            size = self.binance.round_qty(coin, size)
            
            console.print(f"\n[cyan]🔄 Executing on Binance...[/cyan]")
            console.print(f"  Size: {size} {coin} (${size_usd:,.2f})")
            console.print(f"  Leverage: {leverage}x")
            
            # Set leverage
            self.binance.set_leverage(coin, leverage)
            
            # Place order (market order for fast execution)
            order_result = self.binance.place_order(
                coin=coin,
                side=side,  # BUY or SELL
                size=size,
                order_type='MARKET'
            )
            
            if order_result and not self.binance.paper:
                console.print(f"[bold green]✅ Order placed on Binance![/bold green]")
                console.print(f"  Order ID: {order_result.get('orderId', 'N/A')}")
            else:
                console.print(f"[bold green]✅ Order simulated (paper trading)[/bold green]")
            
            # Track position
            position = ActivePosition(
                symbol=symbol,
                side=side,
                entry_price=current_price,
                size=size,
                leverage=leverage,
                open_time=time.time(),
                source_trader_id=trader_id,
                source_trader_name=trader_name,
                binance_order_id=str(order_result.get('orderId', '')) if order_result else ''
            )
            
            self.active_positions[symbol] = position
            
            self.stats['signals_executed'] += 1
            self.stats['positions_opened'] += 1
            
            return True
        
        except Exception as e:
            console.print(f"[red]❌ Execution failed: {e}[/red]")
            self.stats['signals_rejected'] += 1
            return False
    
    def monitor_positions(self):
        """
        Açık pozisyonları monitor et
        """
        if not self.active_positions:
            return
        
        console.print(f"\n[cyan]📊 Monitoring {len(self.active_positions)} position(s)[/cyan]")
        
        table = Table(show_header=True)
        table.add_column("Symbol", style="cyan")
        table.add_column("Side", style="yellow")
        table.add_column("Entry", style="white")
        table.add_column("Current", style="white")
        table.add_column("PnL %", style="green")
        table.add_column("Trader", style="blue")
        
        for symbol, pos in list(self.active_positions.items()):
            # Get current price
            coin = symbol.replace('USDT', '')
            current_price = self.binance.mark_price(coin)
            
            if not current_price:
                continue
            
            pnl_pct = pos.pnl_pct(current_price)
            pnl_style = "green" if pnl_pct > 0 else "red"
            
            table.add_row(
                symbol,
                pos.side,
                f"${pos.entry_price:,.2f}",
                f"${current_price:,.2f}",
                f"[{pnl_style}]{pnl_pct:+.2f}%[/{pnl_style}]",
                pos.source_trader_name[:15]
            )
            
            # Auto close logic (simple example)
            # TP: +5%, SL: -3%
            if pnl_pct >= 5.0:
                console.print(f"[bold green]🎯 TP HIT: Closing {symbol} at +{pnl_pct:.2f}%[/bold green]")
                self._close_position(symbol, current_price, "TP")
            elif pnl_pct <= -3.0:
                console.print(f"[bold red]🛑 SL HIT: Closing {symbol} at {pnl_pct:.2f}%[/bold red]")
                self._close_position(symbol, current_price, "SL")
        
        console.print(table)
    
    def _close_position(self, symbol: str, exit_price: float, reason: str):
        """
        Pozisyonu kapat
        """
        if symbol not in self.active_positions:
            return
        
        pos = self.active_positions[symbol]
        
        # Calculate PnL
        pnl_pct = pos.pnl_pct(exit_price)
        pnl_usd = (pos.size * exit_price * pnl_pct / 100) * pos.leverage
        
        # Close on Binance
        coin = symbol.replace('USDT', '')
        close_side = 'SELL' if pos.side == 'BUY' else 'BUY'
        
        try:
            self.binance.place_order(
                coin=coin,
                side=close_side,
                size=pos.size,
                order_type='MARKET'
            )
            
            console.print(f"[green]✅ Position closed: {symbol}[/green]")
            console.print(f"  Reason: {reason}")
            console.print(f"  PnL: {pnl_pct:+.2f}% (${pnl_usd:+,.2f})")
        
        except Exception as e:
            console.print(f"[red]❌ Failed to close {symbol}: {e}[/red]")
        
        # Remove from active
        del self.active_positions[symbol]
        
        # Update stats
        self.stats['positions_closed'] += 1
        self.stats['total_pnl'] += pnl_usd
    
    def display_stats(self):
        """Display statistics"""
        table = Table(title="📊 Trading Statistics", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Signals Received", str(self.stats['signals_received']))
        table.add_row("Signals Executed", str(self.stats['signals_executed']))
        table.add_row("Signals Rejected", str(self.stats['signals_rejected']))
        table.add_row("Positions Opened", str(self.stats['positions_opened']))
        table.add_row("Positions Closed", str(self.stats['positions_closed']))
        table.add_row("Total PnL", f"${self.stats['total_pnl']:+,.2f}")
        
        console.print(table)
    
    async def run_continuous(self, check_interval: int = 30):
        """
        Sürekli monitoring
        
        Args:
            check_interval: Check interval in seconds
        """
        console.print(Panel.fit(
            "[bold green]🚀 BITGET → BINANCE BRIDGE STARTED[/bold green]\n"
            f"Check interval: {check_interval}s\n"
            f"Max positions: {self.max_positions}\n"
            f"Capital per trade: ${self.capital_per_trade}",
            border_style="green"
        ))
        
        iteration = 0
        
        try:
            while True:
                iteration += 1
                console.print(f"\n[bold]━━━ Iteration {iteration} ━━━[/bold]")
                
                # Check for new signals from Bitget
                signals = self.bitget.get_new_signals()
                
                if signals:
                    console.print(f"[bold cyan]📡 {len(signals)} new signal(s) detected![/bold cyan]")
                    
                    for signal in signals:
                        self.process_signal(signal)
                
                # Monitor active positions
                if self.active_positions:
                    self.monitor_positions()
                
                # Stats
                if iteration % 10 == 0:
                    self.display_stats()
                
                # Wait
                await asyncio.sleep(check_interval)
        
        except KeyboardInterrupt:
            console.print("\n[yellow]⚠️  Shutting down...[/yellow]")
        
        finally:
            # Cleanup
            self.bitget.close()
            self.binance.close()
            
            console.print("\n[bold]━━━ FINAL STATS ━━━[/bold]")
            self.display_stats()
    
    def close(self):
        """Cleanup"""
        self.bitget.close()
        self.binance.close()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main():
    """Demo"""
    
    # Credentials (user should replace)
    BITGET_API_KEY = "your_bitget_api_key"
    BITGET_API_SECRET = "your_bitget_secret"
    BITGET_PASSPHRASE = "your_passphrase"
    
    BINANCE_API_KEY = "your_binance_key"
    BINANCE_API_SECRET = "your_binance_secret"
    
    # Create bridge
    bridge = BitgetToBinanceBridge(
        bitget_api_key=BITGET_API_KEY,
        bitget_api_secret=BITGET_API_SECRET,
        bitget_passphrase=BITGET_PASSPHRASE,
        binance_api_key=BINANCE_API_KEY,
        binance_api_secret=BINANCE_API_SECRET,
        binance_testnet=True,  # Use testnet for safety
        capital_per_trade=100.0,  # $100 per trade
        max_positions=5,
        min_signal_confidence=70.0
    )
    
    # Discover best traders
    bridge.discover_traders(
        top_n=10,
        min_roi=15.0,
        min_win_rate=60.0
    )
    
    # Run continuous monitoring
    await bridge.run_continuous(check_interval=30)


if __name__ == "__main__":
    asyncio.run(main())
