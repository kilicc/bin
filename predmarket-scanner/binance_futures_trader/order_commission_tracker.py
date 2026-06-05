"""
Order-specific commission fetcher
Her order için gerçek commission'ı Binance API'den çeker
"""

from typing import Optional, Dict, TYPE_CHECKING
import time

if TYPE_CHECKING:
    from binance_futures_trader.client import BinanceFuturesClient

def get_order_commission_from_trades(client: 'BinanceFuturesClient', symbol: str, order_id: int) -> Dict[str, any]:
    """
    Belirli bir order'ın gerçek commission bilgisini trades'den çek
    
    Returns:
        {
            'total_commission': float,  # Total commission in USDT
            'commission_asset': str,     # Usually 'USDT'
            'trades_count': int,         # Number of trades for this order
            'success': bool
        }
    """
    try:
        # Get trades for this order
        trades = client.user_trades(symbol.replace('USDT', ''), order_id=order_id, limit=50)
        
        if not trades:
            return {
                'total_commission': 0.0,
                'commission_asset': 'USDT',
                'trades_count': 0,
                'success': False,
                'error': 'No trades found for order'
            }
        
        total_commission = 0.0
        commission_asset = 'USDT'
        
        for trade in trades:
            try:
                commission = abs(float(trade.get('commission', 0)))
                asset = str(trade.get('commissionAsset', 'USDT'))
                
                # Convert to USDT if needed (usually already USDT in futures)
                if asset == 'USDT':
                    total_commission += commission
                else:
                    # For non-USDT assets, might need conversion (rare in futures)
                    print(f"  ⚠️  Non-USDT commission asset: {asset}")
                    total_commission += commission  # Assume 1:1 for now
                    
                commission_asset = asset
            except Exception as e:
                print(f"  ⚠️  Error parsing trade commission: {e}")
                continue
        
        return {
            'total_commission': round(total_commission, 6),
            'commission_asset': commission_asset,
            'trades_count': len(trades),
            'success': True
        }
        
    except Exception as e:
        print(f"  ❌ Failed to fetch order commission: {e}")
        return {
            'total_commission': 0.0,
            'commission_asset': 'USDT',
            'trades_count': 0,
            'success': False,
            'error': str(e)
        }

def wait_and_fetch_order_commission(
    client: 'BinanceFuturesClient', 
    symbol: str, 
    order_id: int,
    max_retries: int = 5,
    retry_delay: float = 0.5
) -> Dict[str, any]:
    """
    Order commission'ını al, gerekirse retry yap
    Trades'in settlement'ı için kısa bir süre bekle
    
    Args:
        max_retries: Max retry count
        retry_delay: Delay between retries (seconds)
    """
    for attempt in range(max_retries):
        result = get_order_commission_from_trades(client, symbol, order_id)
        
        if result['success'] and result['trades_count'] > 0:
            print(f"  ✅ Order {order_id} commission: ${result['total_commission']:.4f} (from {result['trades_count']} trades)")
            return result
        
        if attempt < max_retries - 1:
            print(f"  ⏳ Waiting for order settlement... (attempt {attempt+1}/{max_retries})")
            time.sleep(retry_delay)
    
    # Final attempt failed
    print(f"  ❌ Could not fetch commission for order {order_id} after {max_retries} attempts")
    return result
