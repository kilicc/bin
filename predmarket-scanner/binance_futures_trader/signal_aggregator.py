"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 MULTI-SOURCE SIGNAL AGGREGATOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Birden fazla signal kaynağından veri toplar ve birleştirir:
1. Telegram signals (via webhook/API)
2. TradingView alerts
3. 3Commas/Cornix signals
4. StockAPI Telegram parser

Manuel UID gerekmeden otomatik trading signals!
"""

import asyncio
import json
import time
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import httpx
from rich.console import Console

console = Console()


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    LONG = "LONG"
    SHORT = "SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"


class SignalSource(Enum):
    TELEGRAM = "telegram"
    TRADINGVIEW = "tradingview"
    COPYGRAM = "copygram"
    COMMAS_3 = "3commas"
    CORNIX = "cornix"
    STOCKAPI = "stockapi"
    CUSTOM = "custom"


@dataclass
class TradingSignal:
    """Unified trading signal format"""
    source: str  # Signal kaynağı
    signal_type: str  # BUY, SELL, LONG, SHORT
    symbol: str  # BTCUSDT, etc
    entry_price: Optional[float] = None
    take_profit: Optional[List[float]] = None
    stop_loss: Optional[float] = None
    leverage: Optional[int] = None
    quantity: Optional[float] = None
    confidence: Optional[float] = None  # 0-100
    timestamp: int = 0
    raw_data: Optional[Dict] = None


class TelegramSignalParser:
    """Telegram mesajlarını parse et"""
    
    @staticmethod
    def parse_message(text: str) -> Optional[TradingSignal]:
        """
        Telegram signal formatını parse et
        
        Örnek:
        🚀 LONG #BTCUSDT
        Entry: 76500
        TP: 77000, 77500, 78000
        SL: 75500
        Leverage: 10x
        """
        try:
            lines = text.strip().split('\n')
            signal_data = {}
            
            # İlk satırdan signal type ve symbol
            first_line = lines[0].upper()
            if 'LONG' in first_line or '🟢' in first_line:
                signal_data['type'] = 'LONG'
            elif 'SHORT' in first_line or '🔴' in first_line:
                signal_data['type'] = 'SHORT'
            else:
                return None
            
            # Symbol bul
            for word in first_line.split():
                if 'USDT' in word or 'BTC' in word:
                    signal_data['symbol'] = word.replace('#', '').strip()
                    break
            
            # Entry, TP, SL parse et
            for line in lines[1:]:
                line = line.strip().lower()
                if 'entry' in line:
                    price = line.split(':')[1].strip()
                    signal_data['entry'] = float(price.replace(',', ''))
                elif 'tp' in line or 'take profit' in line:
                    prices = line.split(':')[1].strip()
                    signal_data['tp'] = [float(p.strip()) for p in prices.split(',')]
                elif 'sl' in line or 'stop loss' in line:
                    price = line.split(':')[1].strip()
                    signal_data['sl'] = float(price.replace(',', ''))
                elif 'leverage' in line:
                    lev = line.split(':')[1].strip().replace('x', '')
                    signal_data['leverage'] = int(lev)
            
            if 'symbol' in signal_data and 'type' in signal_data:
                return TradingSignal(
                    source=SignalSource.TELEGRAM.value,
                    signal_type=signal_data['type'],
                    symbol=signal_data['symbol'],
                    entry_price=signal_data.get('entry'),
                    take_profit=signal_data.get('tp'),
                    stop_loss=signal_data.get('sl'),
                    leverage=signal_data.get('leverage'),
                    timestamp=int(time.time() * 1000)
                )
        
        except Exception as e:
            console.print(f"[yellow]⚠️  Telegram parse error: {e}[/yellow]")
        
        return None


class StockAPIConnector:
    """StockAPI Telegram signals connector"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.stockapis.com/v1"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def get_telegram_signals(self) -> List[TradingSignal]:
        """StockAPI'den Telegram signals çek"""
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            url = f"{self.base_url}/telegram/signals"
            
            response = await self.client.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                signals = []
                
                for item in data.get('signals', []):
                    signal = TradingSignal(
                        source=SignalSource.STOCKAPI.value,
                        signal_type=item.get('type', 'BUY'),
                        symbol=item.get('symbol', ''),
                        entry_price=item.get('entry_price'),
                        take_profit=item.get('take_profit', []),
                        stop_loss=item.get('stop_loss'),
                        confidence=item.get('confidence'),
                        timestamp=item.get('timestamp', int(time.time() * 1000)),
                        raw_data=item
                    )
                    signals.append(signal)
                
                return signals
        
        except Exception as e:
            console.print(f"[yellow]⚠️  StockAPI error: {e}[/yellow]")
        
        return []
    
    async def close(self):
        await self.client.aclose()


class SignalAggregator:
    """Multi-source signal aggregator"""
    
    def __init__(self):
        self.signals: List[TradingSignal] = []
        self.stockapi = None
    
    def configure_stockapi(self, api_key: str):
        """StockAPI konfigürasyonu"""
        self.stockapi = StockAPIConnector(api_key)
    
    async def fetch_all_signals(self) -> List[TradingSignal]:
        """Tüm kaynaklardan signal topla"""
        all_signals = []
        
        # StockAPI
        if self.stockapi:
            signals = await self.stockapi.get_telegram_signals()
            all_signals.extend(signals)
        
        # TODO: Diğer kaynaklar eklenebilir
        # - 3Commas webhook
        # - Cornix API
        # - Custom Telegram bot
        
        return all_signals
    
    def filter_signals(
        self,
        signals: List[TradingSignal],
        min_confidence: float = 70.0,
        allowed_symbols: Optional[List[str]] = None
    ) -> List[TradingSignal]:
        """Signalleri filtrele"""
        filtered = []
        
        for signal in signals:
            # Confidence check
            if signal.confidence and signal.confidence < min_confidence:
                continue
            
            # Symbol check
            if allowed_symbols and signal.symbol not in allowed_symbols:
                continue
            
            filtered.append(signal)
        
        return filtered
    
    async def close(self):
        """Cleanup"""
        if self.stockapi:
            await self.stockapi.close()


# Örnek kullanım
async def demo():
    """Demo kullanım"""
    from rich.table import Table
    
    aggregator = SignalAggregator()
    
    # StockAPI configure (opsiyonel)
    # aggregator.configure_stockapi("your_api_key")
    
    console.print("[bold cyan]🎯 Signal Aggregator Demo[/bold cyan]\n")
    
    # Telegram mesaj parse örneği
    telegram_message = """
🚀 LONG #BTCUSDT
Entry: 76500
TP: 77000, 77500, 78000
SL: 75500
Leverage: 10x
"""
    
    parser = TelegramSignalParser()
    signal = parser.parse_message(telegram_message)
    
    if signal:
        table = Table(title="Parsed Signal", show_header=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Source", signal.source)
        table.add_row("Type", signal.signal_type)
        table.add_row("Symbol", signal.symbol)
        table.add_row("Entry", str(signal.entry_price))
        table.add_row("TP", str(signal.take_profit))
        table.add_row("SL", str(signal.stop_loss))
        table.add_row("Leverage", str(signal.leverage))
        
        console.print(table)
    
    await aggregator.close()


if __name__ == "__main__":
    asyncio.run(demo())
