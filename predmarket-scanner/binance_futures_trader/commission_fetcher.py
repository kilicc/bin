"""
Binance API Commission Rate Fetcher
Gerçek fee rates'i Binance API'den alır ve cache'ler
"""

import time
from typing import Optional, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from binance_futures_trader.client import BinanceFuturesClient

# Global cache
_commission_cache: Dict[str, any] = {
    'maker_rate': None,
    'taker_rate': None,
    'last_update': 0,
    'cache_ttl': 3600  # 1 hour
}

def get_commission_rates(client: 'BinanceFuturesClient') -> Dict[str, float]:
    """
    Binance API'den gerçek commission rates'i al
    Cache'li - 1 saatte bir güncellenir
    API başarısız olursa HATA FIRLATIR (default kullanmaz!)
    """
    global _commission_cache
    
    # Check cache
    now = time.time()
    if (_commission_cache['maker_rate'] is not None and 
        _commission_cache['taker_rate'] is not None and
        now - _commission_cache['last_update'] < _commission_cache['cache_ttl']):
        return {
            'maker': _commission_cache['maker_rate'],
            'taker': _commission_cache['taker_rate']
        }
    
    # Fetch from Binance API - MUST succeed!
    try:
        # Try a popular symbol for commission rate
        response = client._get(
            "/fapi/v1/commissionRate",
            params={"symbol": "BTCUSDT"},
            signed=True,
        )
        
        if response and isinstance(response, dict):
            maker_rate = float(response.get('makerCommissionRate', 0.0))
            taker_rate = float(response.get('takerCommissionRate', 0.0))
            
            # Update cache
            _commission_cache['maker_rate'] = maker_rate
            _commission_cache['taker_rate'] = taker_rate
            _commission_cache['last_update'] = now
            
            print(f"  ✓ Binance Commission Rates (API): Maker={maker_rate*100:.4f}% | Taker={taker_rate*100:.4f}%")
            
            return {
                'maker': maker_rate,
                'taker': taker_rate
            }
        else:
            raise ValueError("Invalid API response for commission rates")
            
    except Exception as e:
        print(f"  ❌ Commission rate API FAILED: {e}")
        print(f"  ⚠️  CANNOT calculate fees without real API data!")
        raise RuntimeError(f"Failed to fetch commission rates from Binance API: {e}")

def get_order_actual_commission(client: 'BinanceFuturesClient', symbol: str, order_id: int) -> Optional[float]:
    """
    Gerçek order'dan actual commission'ı al
    """
    try:
        order = client.get_order(symbol, order_id)
        if order and 'commission' in order:
            return float(order['commission'])
    except Exception as e:
        print(f"  ⚠ Order commission fetch error: {e}")
    
    return None

def refresh_commission_cache(client: 'BinanceFuturesClient'):
    """
    Commission cache'i manuel refresh et
    """
    global _commission_cache
    _commission_cache['last_update'] = 0
    return get_commission_rates(client)
