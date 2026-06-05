"""
Pozisyon Analiz ve Filtreleme
==============================
Trader pozisyonlarını analiz edip mantıklı olanları seçer.

Analiz kriterleri:
- Teknik göstergeler (RSI, EMA, BB, Volume)
- Market conditions (trend, volatility)
- Risk/reward ratio
- Correlation with our signals
"""
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from rich.console import Console

from .ta_indicators import rsi, ema, bollinger_bands, atr
from .client import BinanceFuturesClient

console = Console()


@dataclass
class PositionAnalysis:
    """Pozisyon analiz sonucu"""
    should_mirror: bool
    confidence: float  # 0-1
    reason: str
    
    # Teknik göstergeler
    rsi_value: float
    trend_alignment: bool  # EMA trend ile uyumlu mu
    volatility: float  # ATR
    volume_surge: bool  # Volume artışı var mı
    
    # Risk metrics
    suggested_tp_pct: float
    suggested_sl_pct: float
    suggested_stake_mult: float  # 1.0 = normal, 0.5 = half, 1.5 = 1.5x


class PositionAnalyzer:
    """
    Trader pozisyonlarını analiz eder ve aynalama kararı verir
    """
    
    def __init__(
        self,
        client: BinanceFuturesClient,
        min_confidence: float = 0.6,
        rsi_range: Tuple[float, float] = (30, 70),  # Healthy RSI range
        min_volume_ratio: float = 1.2,  # Min 20% volume artışı
        require_trend_alignment: bool = True
    ):
        self.client = client
        self.min_confidence = min_confidence
        self.rsi_range = rsi_range
        self.min_volume_ratio = min_volume_ratio
        self.require_trend_alignment = require_trend_alignment
    
    async def analyze_position(
        self,
        symbol: str,
        side: str,  # LONG or SHORT
        trader_entry_price: float,
        trader_leverage: int,
        interval: str = "15m",
        lookback: int = 100
    ) -> PositionAnalysis:
        """
        Bir pozisyonu analiz et
        
        Returns:
            PositionAnalysis nesnesi
        """
        console.print(f"\n[cyan]📊 Analyzing {side} {symbol} @ {trader_entry_price:.4f}...[/cyan]")
        
        # Fetch klines
        try:
            klines = await self.client.klines(
                symbol=symbol,
                interval=interval,
                limit=lookback
            )
        except Exception as e:
            console.print(f"[red]❌ Error fetching klines: {e}[/red]")
            return self._rejected_analysis(f"Data fetch error: {e}")
        
        if len(klines) < lookback:
            return self._rejected_analysis(f"Insufficient data ({len(klines)} bars)")
        
        # Extract OHLCV
        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        
        current_price = closes[-1]
        
        # Technical indicators
        rsi_vals = rsi(closes, period=14)
        ema21 = ema(closes, period=21)
        ema50 = ema(closes, period=50)
        bb_upper, bb_mid, bb_lower = bollinger_bands(closes, period=20, std_dev=2.0)
        atr_vals = atr(highs, lows, closes, period=14)
        
        current_rsi = rsi_vals[-1] if rsi_vals else 50.0
        current_ema21 = ema21[-1] if ema21 else current_price
        current_ema50 = ema50[-1] if ema50 else current_price
        current_atr = atr_vals[-1] if atr_vals else 0.01
        
        # Volume analysis
        avg_volume = sum(volumes[-20:]) / 20
        current_volume = volumes[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        volume_surge = volume_ratio >= self.min_volume_ratio
        
        # Trend alignment
        trend_up = current_ema21 > current_ema50
        trend_alignment = (side == "LONG" and trend_up) or (side == "SHORT" and not trend_up)
        
        # RSI check
        rsi_ok = self.rsi_range[0] <= current_rsi <= self.rsi_range[1]
        
        # Distance from BBands
        bb_position = (current_price - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1]) if bb_upper[-1] != bb_lower[-1] else 0.5
        
        # Score calculation
        confidence = 0.0
        reasons = []
        
        # RSI scoring (30%)
        if rsi_ok:
            confidence += 0.30
            reasons.append(f"RSI healthy ({current_rsi:.1f})")
        else:
            if side == "LONG" and current_rsi < self.rsi_range[0]:
                confidence += 0.15  # Oversold for LONG is okay
                reasons.append(f"RSI oversold ({current_rsi:.1f}) - acceptable for LONG")
            elif side == "SHORT" and current_rsi > self.rsi_range[1]:
                confidence += 0.15  # Overbought for SHORT is okay
                reasons.append(f"RSI overbought ({current_rsi:.1f}) - acceptable for SHORT")
            else:
                reasons.append(f"❌ RSI unfavorable ({current_rsi:.1f})")
        
        # Trend alignment (30%)
        if trend_alignment:
            confidence += 0.30
            reasons.append(f"✓ Trend aligned ({side} with EMA trend)")
        else:
            if not self.require_trend_alignment:
                confidence += 0.10  # Partial credit
                reasons.append(f"⚠ Trend not aligned but allowed")
            else:
                reasons.append(f"❌ Trend misaligned ({side} against EMA trend)")
        
        # Volume (20%)
        if volume_surge:
            confidence += 0.20
            reasons.append(f"✓ Volume surge ({volume_ratio:.1f}x)")
        else:
            confidence += 0.05
            reasons.append(f"⚠ Low volume ({volume_ratio:.1f}x)")
        
        # BB Position (20%)
        if side == "LONG" and bb_position < 0.3:
            confidence += 0.20
            reasons.append(f"✓ Near lower BB (good for LONG)")
        elif side == "SHORT" and bb_position > 0.7:
            confidence += 0.20
            reasons.append(f"✓ Near upper BB (good for SHORT)")
        elif 0.3 <= bb_position <= 0.7:
            confidence += 0.10
            reasons.append(f"⚠ Mid BB range")
        else:
            reasons.append(f"❌ BB position unfavorable")
        
        # Dynamic TP/SL calculation based on ATR
        atr_pct = (current_atr / current_price) * 100
        
        # TP: 2-3x ATR
        suggested_tp_pct = atr_pct * 2.5
        
        # SL: 1-1.5x ATR
        suggested_sl_pct = atr_pct * 1.2
        
        # Stake multiplier based on confidence
        if confidence >= 0.8:
            suggested_stake_mult = 1.3  # High confidence = larger position
        elif confidence >= 0.6:
            suggested_stake_mult = 1.0  # Normal position
        else:
            suggested_stake_mult = 0.5  # Low confidence = smaller position
        
        # Decision
        should_mirror = confidence >= self.min_confidence
        
        reason_text = " | ".join(reasons)
        
        result = PositionAnalysis(
            should_mirror=should_mirror,
            confidence=confidence,
            reason=reason_text,
            rsi_value=current_rsi,
            trend_alignment=trend_alignment,
            volatility=atr_pct,
            volume_surge=volume_surge,
            suggested_tp_pct=suggested_tp_pct,
            suggested_sl_pct=suggested_sl_pct,
            suggested_stake_mult=suggested_stake_mult
        )
        
        if should_mirror:
            console.print(
                f"[green]✓ MIRROR[/green] Confidence: {confidence:.1%} | {reason_text}"
            )
            console.print(
                f"[dim]  Suggested: TP={suggested_tp_pct:.2f}%, SL={suggested_sl_pct:.2f}%, "
                f"Stake={suggested_stake_mult:.1f}x[/dim]"
            )
        else:
            console.print(
                f"[red]✗ REJECT[/red] Confidence: {confidence:.1%} | {reason_text}"
            )
        
        return result
    
    def _rejected_analysis(self, reason: str) -> PositionAnalysis:
        """Return a rejected analysis"""
        return PositionAnalysis(
            should_mirror=False,
            confidence=0.0,
            reason=f"❌ {reason}",
            rsi_value=50.0,
            trend_alignment=False,
            volatility=0.0,
            volume_surge=False,
            suggested_tp_pct=2.0,
            suggested_sl_pct=1.0,
            suggested_stake_mult=1.0
        )


class MultiPositionFilter:
    """
    Çoklu pozisyon filtresi
    
    - Correlation check (aynı yöne çok fazla pozisyon açılmasın)
    - Exposure limits (total risk kontrolü)
    - Diversification (farklı coinler)
    """
    
    def __init__(
        self,
        max_same_direction: int = 3,  # Max aynı yöne pozisyon
        max_correlated: int = 2,  # Max korelasyonlu coin pozisyonu
        max_total_exposure_pct: float = 50.0  # Total sermayenin max %50'si
    ):
        self.max_same_direction = max_same_direction
        self.max_correlated = max_correlated
        self.max_total_exposure_pct = max_total_exposure_pct
        
        # Coin groups (highly correlated)
        self.coin_groups = {
            "BTC_GROUP": ["BTC", "BTCUSDT", "BTCUSD"],
            "ETH_GROUP": ["ETH", "ETHUSDT", "ETHUSD"],
            "LAYER1": ["SOL", "AVAX", "NEAR", "SUI", "APT"],
            "DEFI": ["UNI", "AAVE", "MKR", "LINK"],
            "MEME": ["DOGE", "SHIB", "PEPE", "WIF"]
        }
    
    def check_position_allowed(
        self,
        new_symbol: str,
        new_side: str,
        existing_positions: List[Dict]
    ) -> Tuple[bool, str]:
        """
        Yeni pozisyon açılabilir mi kontrol et
        
        Returns:
            (allowed, reason)
        """
        # Count same direction
        same_direction = [p for p in existing_positions if p["side"] == new_side]
        if len(same_direction) >= self.max_same_direction:
            return False, f"Max {self.max_same_direction} {new_side} positions already open"
        
        # Check correlation
        new_group = self._get_coin_group(new_symbol)
        if new_group:
            correlated_count = sum(
                1 for p in existing_positions
                if self._get_coin_group(p["symbol"]) == new_group
            )
            if correlated_count >= self.max_correlated:
                return False, f"Max {self.max_correlated} {new_group} positions already open"
        
        # Check total exposure
        total_exposure_usd = sum(p.get("size_usd", 0) for p in existing_positions)
        # This would need access to total capital, simplified for now
        
        return True, "✓ Position allowed"
    
    def _get_coin_group(self, symbol: str) -> Optional[str]:
        """Get coin group for correlation check"""
        symbol_upper = symbol.upper().replace("USDT", "").replace("USD", "")
        
        for group_name, coins in self.coin_groups.items():
            if any(coin in symbol_upper for coin in coins):
                return group_name
        
        return None


async def main():
    """Test"""
    from dotenv import load_dotenv
    import os
    
    load_dotenv()
    
    client = BinanceFuturesClient(
        api_key=os.getenv("BINANCE_FUTURES_TESTNET_API_KEY", ""),
        api_secret=os.getenv("BINANCE_FUTURES_TESTNET_API_SECRET", ""),
        testnet=True
    )
    
    analyzer = PositionAnalyzer(
        client=client,
        min_confidence=0.6
    )
    
    # Test analysis
    result = await analyzer.analyze_position(
        symbol="BTCUSDT",
        side="LONG",
        trader_entry_price=65000.0,
        trader_leverage=5
    )
    
    console.print(f"\n[bold]Result: {'MIRROR' if result.should_mirror else 'REJECT'}[/bold]")
    console.print(f"Confidence: {result.confidence:.1%}")
    console.print(f"Reason: {result.reason}")


if __name__ == "__main__":
    asyncio.run(main())
