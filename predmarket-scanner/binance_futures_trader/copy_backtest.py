"""
Copy Trading Backtest Engine
=============================
Copy trading stratejisini geçmiş verilerle test eder.

Simülasyon:
- Trader'ların geçmiş pozisyonlarını takip eder
- Pozisyon analizi yapıp mirror kararı verir
- PnL, drawdown, win rate hesaplar
- Performans raporları üretir
"""
import json
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from rich.console import Console
from rich.table import Table

console = Console()


@dataclass
class SimulatedTraderPosition:
    """Simüle edilmiş trader pozisyonu"""
    trader_id: int
    symbol: str
    side: str
    entry_time: int
    entry_price: float
    exit_time: int
    exit_price: float
    size: float
    leverage: int
    pnl_pct: float  # Trader'ın gerçek PnL'si


@dataclass
class MirrorTrade:
    """Bizim aynalanan trade'imiz"""
    trader_id: int
    symbol: str
    side: str
    entry_time: int
    entry_price: float
    exit_time: Optional[int]
    exit_price: Optional[float]
    size_usd: float
    leverage: int
    tp_pct: float
    sl_pct: float
    
    analysis_confidence: float
    analysis_reason: str
    
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None
    is_winner: Optional[bool] = None


@dataclass
class BacktestResult:
    """Backtest sonucu"""
    start_date: str
    end_date: str
    duration_days: int
    
    start_balance: float
    end_balance: float
    total_pnl: float
    total_pnl_pct: float
    
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    
    avg_win: float
    avg_loss: float
    profit_factor: float
    
    max_drawdown: float
    max_drawdown_pct: float
    
    sharpe_ratio: float
    calmar_ratio: float
    
    trades: List[MirrorTrade]


class CopyTradingBacktest:
    """
    Copy trading backtest motoru
    """
    
    def __init__(
        self,
        start_balance: float = 5000.0,
        copy_allocation_pct: float = 30.0,
        max_positions: int = 5,
        min_analysis_confidence: float = 0.6,
        use_dynamic_tpsl: bool = True
    ):
        self.start_balance = start_balance
        self.copy_allocation_pct = copy_allocation_pct
        self.max_positions = max_positions
        self.min_analysis_confidence = min_analysis_confidence
        self.use_dynamic_tpsl = use_dynamic_tpsl
        
        self.copy_capital = start_balance * (copy_allocation_pct / 100.0)
    
    def run_backtest(
        self,
        simulated_positions: List[SimulatedTraderPosition],
        start_date: datetime,
        end_date: datetime
    ) -> BacktestResult:
        """
        Backtest çalıştır
        
        Args:
            simulated_positions: Trader'ların simüle edilmiş pozisyonları
            start_date: Başlangıç tarihi
            end_date: Bitiş tarihi
        
        Returns:
            BacktestResult
        """
        console.print(f"\n[bold cyan]🔄 Running Copy Trading Backtest[/bold cyan]")
        console.print(f"  Period: {start_date.date()} to {end_date.date()}")
        console.print(f"  Copy Capital: ${self.copy_capital:,.2f}")
        console.print(f"  Max Positions: {self.max_positions}")
        console.print(f"  Min Confidence: {self.min_analysis_confidence:.0%}\n")
        
        # Sort positions by entry time
        sorted_positions = sorted(simulated_positions, key=lambda p: p.entry_time)
        
        # Simulation state
        current_balance = self.start_balance
        copy_balance = self.copy_capital
        open_positions: List[MirrorTrade] = []
        closed_trades: List[MirrorTrade] = []
        
        equity_curve = []
        
        # Simulate
        for trader_pos in sorted_positions:
            # Check if we should mirror this position
            should_mirror, analysis = self._analyze_position(trader_pos)
            
            if not should_mirror:
                continue
            
            # Check if we have capacity
            if len(open_positions) >= self.max_positions:
                continue
            
            # Calculate position size
            position_size_usd = self._calculate_position_size(
                copy_balance,
                len(open_positions),
                analysis["stake_mult"]
            )
            
            if position_size_usd < 10.0:  # Min size
                continue
            
            # Open mirror position
            mirror_trade = MirrorTrade(
                trader_id=trader_pos.trader_id,
                symbol=trader_pos.symbol,
                side=trader_pos.side,
                entry_time=trader_pos.entry_time,
                entry_price=trader_pos.entry_price,
                exit_time=None,
                exit_price=None,
                size_usd=position_size_usd,
                leverage=min(trader_pos.leverage, 10),  # Max 10x
                tp_pct=analysis["tp_pct"],
                sl_pct=analysis["sl_pct"],
                analysis_confidence=analysis["confidence"],
                analysis_reason=analysis["reason"]
            )
            
            open_positions.append(mirror_trade)
            copy_balance -= position_size_usd  # Reserve capital
            
            console.print(
                f"[green]OPEN[/green] {trader_pos.symbol} {trader_pos.side} @ "
                f"{trader_pos.entry_price:.2f} | Size: ${position_size_usd:.2f} | "
                f"Conf: {analysis['confidence']:.0%}"
            )
            
            # Check for closes
            # When trader closes, we close too
            for open_pos in list(open_positions):
                if open_pos.trader_id == trader_pos.trader_id and \
                   open_pos.symbol == trader_pos.symbol and \
                   open_pos.exit_time is None:
                    
                    # Close position
                    open_pos.exit_time = trader_pos.exit_time
                    open_pos.exit_price = trader_pos.exit_price
                    
                    # Calculate PnL
                    price_change_pct = (
                        (trader_pos.exit_price - trader_pos.entry_price) / trader_pos.entry_price
                    ) * 100
                    
                    if open_pos.side == "SHORT":
                        price_change_pct = -price_change_pct
                    
                    # Apply TP/SL
                    if price_change_pct >= open_pos.tp_pct:
                        price_change_pct = open_pos.tp_pct  # Hit TP
                    elif price_change_pct <= -open_pos.sl_pct:
                        price_change_pct = -open_pos.sl_pct  # Hit SL
                    
                    pnl_usd = open_pos.size_usd * (price_change_pct / 100) * open_pos.leverage
                    
                    open_pos.pnl_usd = pnl_usd
                    open_pos.pnl_pct = price_change_pct
                    open_pos.is_winner = pnl_usd > 0
                    
                    # Update balance
                    copy_balance += open_pos.size_usd + pnl_usd
                    current_balance += pnl_usd
                    
                    console.print(
                        f"[{'green' if pnl_usd > 0 else 'red'}]CLOSE[/{'green' if pnl_usd > 0 else 'red'}] "
                        f"{open_pos.symbol} {open_pos.side} @ {trader_pos.exit_price:.2f} | "
                        f"PnL: ${pnl_usd:+.2f} ({price_change_pct:+.2f}%)"
                    )
                    
                    closed_trades.append(open_pos)
                    open_positions.remove(open_pos)
                    
                    # Track equity
                    equity_curve.append({
                        "time": trader_pos.exit_time,
                        "balance": current_balance
                    })
        
        # Calculate metrics
        total_pnl = current_balance - self.start_balance
        total_pnl_pct = (total_pnl / self.start_balance) * 100
        
        total_trades = len(closed_trades)
        winning_trades = sum(1 for t in closed_trades if t.is_winner)
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        winners = [t.pnl_usd for t in closed_trades if t.is_winner]
        losers = [t.pnl_usd for t in closed_trades if not t.is_winner]
        
        avg_win = sum(winners) / len(winners) if winners else 0.0
        avg_loss = sum(losers) / len(losers) if losers else 0.0
        
        profit_factor = abs(sum(winners) / sum(losers)) if losers and sum(losers) != 0 else 0.0
        
        # Drawdown
        max_balance = self.start_balance
        max_drawdown = 0.0
        for point in equity_curve:
            balance = point["balance"]
            if balance > max_balance:
                max_balance = balance
            drawdown = max_balance - balance
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        max_drawdown_pct = (max_drawdown / max_balance) * 100 if max_balance > 0 else 0.0
        
        # Sharpe & Calmar (simplified)
        sharpe_ratio = 0.0  # TODO: Calculate with returns volatility
        calmar_ratio = abs(total_pnl_pct / max_drawdown_pct) if max_drawdown_pct > 0 else 0.0
        
        result = BacktestResult(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            duration_days=(end_date - start_date).days,
            start_balance=self.start_balance,
            end_balance=current_balance,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            calmar_ratio=calmar_ratio,
            trades=closed_trades
        )
        
        self._print_results(result)
        
        return result
    
    def _analyze_position(
        self,
        trader_pos: SimulatedTraderPosition
    ) -> tuple[bool, Dict]:
        """
        Pozisyonu analiz et (simulated)
        
        Gerçekte position_analyzer.py kullanılacak,
        burada basit simulasyon yapıyoruz
        """
        # Simulate analysis confidence (60-90%)
        confidence = 0.6 + random.random() * 0.3
        
        # Higher confidence for winning trader positions
        if trader_pos.pnl_pct > 0:
            confidence = min(0.95, confidence + 0.1)
        
        should_mirror = confidence >= self.min_analysis_confidence
        
        # Dynamic TP/SL based on volatility (simulated)
        if self.use_dynamic_tpsl:
            base_tp = 2.5
            base_sl = 1.2
            
            # Adjust based on confidence
            tp_pct = base_tp * (1.0 + (confidence - 0.6) * 0.5)
            sl_pct = base_sl * (1.0 + (0.9 - confidence) * 0.5)
            stake_mult = confidence / 0.6  # Higher confidence = larger stake
        else:
            tp_pct = 2.5
            sl_pct = 1.0
            stake_mult = 1.0
        
        analysis = {
            "confidence": confidence,
            "reason": f"Simulated analysis (conf={confidence:.2f})",
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "stake_mult": stake_mult
        }
        
        return should_mirror, analysis
    
    def _calculate_position_size(
        self,
        available_balance: float,
        open_count: int,
        stake_mult: float
    ) -> float:
        """Pozisyon büyüklüğünü hesapla"""
        # Equal distribution among max positions
        base_size = available_balance / (self.max_positions - open_count)
        
        # Apply multiplier
        size = base_size * stake_mult
        
        # Clamp
        size = max(10.0, min(size, available_balance * 0.3))
        
        return size
    
    def _print_results(self, result: BacktestResult):
        """Sonuçları yazdır"""
        console.print(f"\n[bold cyan]{'═' * 60}[/bold cyan]")
        console.print(f"[bold cyan]Copy Trading Backtest Results[/bold cyan]")
        console.print(f"[bold cyan]{'═' * 60}[/bold cyan]\n")
        
        # Performance
        table = Table(title="Performance Metrics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="bold")
        
        table.add_row("Duration", f"{result.duration_days} days")
        table.add_row("Start Balance", f"${result.start_balance:,.2f}")
        table.add_row("End Balance", f"${result.end_balance:,.2f}")
        table.add_row("Total PnL", f"[{'green' if result.total_pnl > 0 else 'red'}]${result.total_pnl:+,.2f}[/{'green' if result.total_pnl > 0 else 'red'}]")
        table.add_row("Total Return", f"[{'green' if result.total_pnl_pct > 0 else 'red'}]{result.total_pnl_pct:+.2f}%[/{'green' if result.total_pnl_pct > 0 else 'red'}]")
        table.add_row("Max Drawdown", f"[red]{result.max_drawdown_pct:.2f}%[/red]")
        table.add_row("Calmar Ratio", f"{result.calmar_ratio:.2f}")
        
        console.print(table)
        
        # Trade stats
        table2 = Table(title="Trade Statistics")
        table2.add_column("Metric", style="cyan")
        table2.add_column("Value", style="bold")
        
        table2.add_row("Total Trades", str(result.total_trades))
        table2.add_row("Winning Trades", f"[green]{result.winning_trades}[/green]")
        table2.add_row("Losing Trades", f"[red]{result.losing_trades}[/red]")
        table2.add_row("Win Rate", f"{result.win_rate*100:.1f}%")
        table2.add_row("Profit Factor", f"{result.profit_factor:.2f}")
        table2.add_row("Avg Win", f"[green]${result.avg_win:+.2f}[/green]")
        table2.add_row("Avg Loss", f"[red]${result.avg_loss:+.2f}[/red]")
        
        console.print("\n", table2)
    
    def save_result(self, result: BacktestResult, filepath: str):
        """Sonucu kaydet"""
        data = asdict(result)
        
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        
        console.print(f"\n[green]✓ Results saved to: {filepath}[/green]")


def generate_sample_positions(
    num_traders: int = 5,
    num_positions_per_trader: int = 20,
    win_rate: float = 0.65
) -> List[SimulatedTraderPosition]:
    """Generate sample trader positions for testing"""
    positions = []
    
    start_time = int(datetime.now().timestamp() * 1000) - (30 * 24 * 3600 * 1000)  # 30 days ago
    
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT"]
    
    for trader_id in range(num_traders):
        for i in range(num_positions_per_trader):
            symbol = random.choice(symbols)
            side = random.choice(["LONG", "SHORT"])
            
            entry_time = start_time + random.randint(0, 25 * 24 * 3600 * 1000)
            entry_price = random.uniform(50, 70000)
            
            # Simulate win/loss
            is_winner = random.random() < win_rate
            
            if is_winner:
                pnl_pct = random.uniform(1.0, 5.0)
            else:
                pnl_pct = random.uniform(-3.0, -0.5)
            
            exit_price = entry_price * (1 + pnl_pct / 100)
            exit_time = entry_time + random.randint(3600 * 1000, 48 * 3600 * 1000)
            
            pos = SimulatedTraderPosition(
                trader_id=trader_id,
                symbol=symbol,
                side=side,
                entry_time=entry_time,
                entry_price=entry_price,
                exit_time=exit_time,
                exit_price=exit_price,
                size=random.uniform(0.01, 1.0),
                leverage=random.choice([3, 5, 10]),
                pnl_pct=pnl_pct
            )
            
            positions.append(pos)
    
    return positions


def main():
    """Test backtest"""
    console.print("[bold cyan]🧪 Copy Trading Backtest Test[/bold cyan]\n")
    
    # Generate sample data
    positions = generate_sample_positions(
        num_traders=3,
        num_positions_per_trader=30,
        win_rate=0.70
    )
    
    # Run backtest
    backtest = CopyTradingBacktest(
        start_balance=5000.0,
        copy_allocation_pct=30.0,
        max_positions=5,
        min_analysis_confidence=0.6,
        use_dynamic_tpsl=True
    )
    
    start_date = datetime.now() - timedelta(days=30)
    end_date = datetime.now()
    
    result = backtest.run_backtest(positions, start_date, end_date)
    
    # Save
    backtest.save_result(result, "data/copy_trading/backtest_result_sample.json")


if __name__ == "__main__":
    main()
