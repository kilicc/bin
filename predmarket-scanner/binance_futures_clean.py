#!/usr/bin/env python3
"""
BINANCE FUTURES CLEAN DASHBOARD - NO DEMO POSITIONS
Port 9003 - Absolutely no demo positions on startup
"""
from __future__ import annotations
import asyncio, json, os, time, random
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from dotenv import load_dotenv

load_dotenv(override=True)
os.environ['BN_FUT_MODE'] = 'testnet'
os.environ['BINANCE_FUTURES_TESTNET'] = '1'

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from binance_futures_trader.client import BinanceFuturesClient
from pathlib import Path

client = BinanceFuturesClient()
STARTING_CAPITAL = 5000.0
position_id_counter = 1

# CLEAN STATE - NO DEMO POSITIONS
positions = []
closed_positions = []
price_history = {}
capital_history = []
signals = []
watchlist = [
    'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'XRPUSDT', 'DOGEUSDT', 'MATICUSDT', 'DOTUSDT',
    'AVAXUSDT', 'LINKUSDT', 'UNIUSDT', 'ATOMUSDT', 'LTCUSDT', 'NEARUSDT', 'AAVEUSDT', 'FILUSDT'
]

def fetch_price(symbol: str) -> tuple[float, float]:
    try:
        start = time.time()
        coin = symbol.replace('USDT', '')
        price = client.mark_price(coin)
        latency = (time.time() - start) * 1000
        if price:
            return float(price), latency
    except Exception as e:
        print(f"❌ {symbol}: {e}")
    return 0.0, 0.0

def get_current_capital() -> float:
    total_pnl = sum(p['unrealized_pnl'] for p in positions)
    realized_pnl = sum(p.get('final_pnl', p.get('pnl_usd', 0)) for p in closed_positions)
    return STARTING_CAPITAL + realized_pnl + total_pnl

def open_position(symbol: str, side: str, size: float = None, leverage: int = 3, edge: float = None, signal_source: str = "AUTO") -> dict | None:
    global positions, position_id_counter
    try:
        entry_price, _ = fetch_price(symbol)
        if entry_price <= 0:
            return None
        
        current_capital = get_current_capital()
        if size is None:
            position_value = current_capital * 0.08 * leverage
            size = position_value / entry_price
        
        entry_fee = size * entry_price * 0.0004
        stake_usd = size * entry_price / leverage
        
        if edge is None:
            edge = random.uniform(0.05, 0.15)
        
        position = {
            'id': position_id_counter,
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'current_price': entry_price,
            'size': size,
            'leverage': leverage,
            'stake_usd': stake_usd,
            'position_value': size * entry_price,
            'unrealized_pnl': 0.0,
            'pnl_pct': 0.0,
            'entry_time': time.time(),
            'entry_time_str': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'tp_target': entry_price * 1.025 if side == 'LONG' else entry_price * 0.975,
            'sl_target': entry_price * 0.985 if side == 'LONG' else entry_price * 1.015,
            'price_history': [entry_price],
            'time_history': [datetime.utcnow().isoformat()],
            'entry_fee': entry_fee,
            'total_fees': entry_fee,
            'edge': edge,
            'signal_source': signal_source,
            'signal_strength': 'Strong' if edge > 0.10 else 'Medium' if edge > 0.07 else 'Weak',
        }
        
        positions.append(position)
        position_id_counter += 1
        print(f"✅ {side} {symbol} @ ${entry_price:.2f} | {leverage}x | Signal: {signal_source}")
        return position
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def close_position(position_id: int, exit_reason: str = 'Manual'):
    global positions, closed_positions
    for i, pos in enumerate(positions):
        if pos['id'] == position_id:
            exit_price = pos['current_price']
            pnl = pos['unrealized_pnl']
            
            exit_fee = pos['size'] * exit_price * 0.0004
            total_fees = pos.get('entry_fee', 0) + exit_fee
            net_pnl = pnl - total_fees
            net_pnl_pct = (net_pnl / pos['stake_usd']) * 100
            tax = max(0, net_pnl * 0.10)
            final_pnl = net_pnl - tax
            
            closed = {
                'id': pos['id'],
                'symbol': pos['symbol'],
                'side': pos['side'],
                'entry_price': pos['entry_price'],
                'exit_price': exit_price,
                'size': pos['size'],
                'leverage': pos['leverage'],
                'stake_usd': pos['stake_usd'],
                'pnl_usd': pnl,
                'pnl_pct': (pnl / pos['stake_usd']) * 100,
                'entry_fee': pos.get('entry_fee', 0),
                'exit_fee': exit_fee,
                'total_fees': total_fees,
                'net_pnl': net_pnl,
                'net_pnl_pct': net_pnl_pct,
                'tax': tax,
                'final_pnl': final_pnl,
                'exit_reason': exit_reason,
                'entry_time': pos['entry_time_str'],
                'exit_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'duration': time.time() - pos['entry_time']
            }
            
            closed_positions.append(closed)
            positions.pop(i)
            print(f"✅ Closed #{position_id}: {pos['symbol']} | ${final_pnl:.2f}")
            return True
    return False

def update_positions():
    total_latency = 0
    count = 0
    for pos in positions:
        new_price, latency = fetch_price(pos['symbol'])
        total_latency += latency
        count += 1
        
        if new_price > 0:
            pos['current_price'] = new_price
            pos['price_history'].append(new_price)
            pos['time_history'].append(datetime.utcnow().isoformat())
            
            if len(pos['price_history']) > 60:
                pos['price_history'].pop(0)
                pos['time_history'].pop(0)
            
            if pos['side'] == 'LONG':
                pos['unrealized_pnl'] = (pos['current_price'] - pos['entry_price']) * pos['size']
            else:
                pos['unrealized_pnl'] = (pos['entry_price'] - pos['current_price']) * pos['size']
            
            pos['pnl_pct'] = (pos['unrealized_pnl'] / pos['stake_usd']) * 100
            
            if pos['side'] == 'LONG':
                if pos['current_price'] >= pos['tp_target']:
                    close_position(pos['id'], 'TP Hit')
                elif pos['current_price'] <= pos['sl_target']:
                    close_position(pos['id'], 'SL Hit')
            else:
                if pos['current_price'] <= pos['tp_target']:
                    close_position(pos['id'], 'TP Hit')
                elif pos['current_price'] >= pos['sl_target']:
                    close_position(pos['id'], 'SL Hit')
    
    return total_latency / count if count > 0 else 0

def scan_signals():
    global signals, price_history
    for symbol in watchlist:
        try:
            price, _ = fetch_price(symbol)
            if price > 0:
                if symbol not in price_history:
                    price_history[symbol] = []
                
                price_history[symbol].append({
                    'time': datetime.utcnow().isoformat(),
                    'price': price
                })
                
                if len(price_history[symbol]) > 60:
                    price_history[symbol].pop(0)
                
                if len(price_history[symbol]) > 10:
                    old_price = price_history[symbol][-10]['price']
                    change = ((price - old_price) / old_price) * 100
                    
                    if abs(change) > 0.12:
                        signal_exists = any(s['symbol'] == symbol and s['type'] == ('LONG' if change > 0 else 'SHORT') for s in signals[-5:])
                        if not signal_exists:
                            signals.append({
                                'symbol': symbol,
                                'type': 'LONG' if change > 0 else 'SHORT',
                                'price': price,
                                'change': change,
                                'time': datetime.utcnow().strftime('%H:%M:%S'),
                                'strength': 'Strong' if abs(change) > 0.5 else 'Medium' if abs(change) > 0.25 else 'Weak'
                            })
                            
                            if len(signals) > 30:
                                signals.pop(0)
        except:
            pass

def update_capital_history():
    current = get_current_capital()
    capital_history.append({
        'time': datetime.utcnow().isoformat(),
        'capital': current
    })
    
    if len(capital_history) > 100:
        capital_history.pop(0)

def get_snapshot() -> dict[str, Any]:
    current_capital = get_current_capital()
    total_unrealized = sum(p['unrealized_pnl'] for p in positions)
    total_realized = sum(p.get('final_pnl', p.get('pnl_usd', 0)) for p in closed_positions)
    total_pnl = total_realized + total_unrealized
    
    win_count = len([p for p in closed_positions if p.get('final_pnl', 0) > 0])
    total_count = len(closed_positions)
    win_rate = (win_count / total_count * 100) if total_count > 0 else 0
    
    total_fees = sum(p.get('total_fees', 0) for p in closed_positions)
    total_taxes = sum(p.get('tax', 0) for p in closed_positions)
    
    total_active_stake = sum(p['stake_usd'] for p in positions)
    total_position_value = sum(p.get('position_value', p['size'] * p['current_price']) for p in positions)
    
    return {
        'ts': datetime.utcnow().isoformat() + 'Z',
        'mode': 'TESTNET' if not client.paper else 'PAPER',
        'wallet': {
            'usdt': current_capital,
            'max_position_usd': STARTING_CAPITAL * 0.1
        },
        'summary': {
            'starting_capital': STARTING_CAPITAL,
            'current_capital': current_capital,
            'total_pnl': total_pnl,
            'total_pnl_pct': (total_pnl / STARTING_CAPITAL) * 100,
            'realized_pnl': total_realized,
            'unrealized_pnl': total_unrealized,
            'open_trades': len(positions),
            'closed_trades': len(closed_positions),
            'win_rate': win_rate,
            'win_count': win_count,
            'total_fees': total_fees,
            'total_taxes': total_taxes,
            'total_active_stake': total_active_stake,
            'total_position_value': total_position_value,
            'available_capital': current_capital - total_active_stake,
        },
        'positions': {
            'open': positions,
            'closed': closed_positions[-40:]
        },
        'signals': signals[-20:],
        'equity': [p['capital'] for p in capital_history],
        'timestamps': [p['time'] for p in capital_history],
        'watchlist_prices': {sym: {'price': price_history.get(sym, [])[-1]['price'] if price_history.get(sym) else 0, 'change': ((price_history.get(sym, [])[-1]['price'] - price_history.get(sym, [])[-10]['price']) / price_history.get(sym, [])[-10]['price'] * 100) if len(price_history.get(sym, [])) > 10 else 0} for sym in watchlist}
    }

class WSManager:
    def __init__(self):
        self.clients: list[WebSocket] = []
    
    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.append(ws)
    
    def disconnect(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)
    
    async def broadcast(self, data: dict):
        if not self.clients:
            return
        txt = json.dumps(data)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(txt)
            except:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

ws_manager = WSManager()

async def update_loop():
    print("🚀 Starting clean - NO DEMO POSITIONS")
    await asyncio.sleep(2)
    
    # NO DEMO POSITIONS - NEVER OPEN ON STARTUP
    # Positions will only open from real signals
    
    update_count = 0
    avg_latency = 0
    
    while True:
        try:
            avg_latency = update_positions()
            
            if update_count % 3 == 0:
                scan_signals()
            
            if update_count % 3 == 0:
                update_capital_history()
            
            snapshot = get_snapshot()
            snapshot['api_latency_ms'] = round(avg_latency, 1)
            await ws_manager.broadcast(snapshot)
            
            update_count += 1
        except Exception as e:
            print(f"❌ {e}")
        
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(update_loop())
    yield

app = FastAPI(title="Binance Futures Clean", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def index():
    template_path = Path(__file__).parent / "elite_pro_template.html"
    if template_path.exists():
        return template_path.read_text()
    return "<h1>Template not found</h1>"

@app.get("/api/live")
async def api_live():
    return get_snapshot()

@app.websocket("/ws")
async def ws_live(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        await ws.send_text(json.dumps(get_snapshot()))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)

if __name__ == "__main__":
    import uvicorn
    print("━" * 80)
    print("🚀 BINANCE FUTURES CLEAN DASHBOARD")
    print("━" * 80)
    print(f"📡 Port: 9004")
    print(f"💰 Capital: ${STARTING_CAPITAL:,.0f}")
    print(f"🚫 NO DEMO POSITIONS - Clean Start")
    print(f"📊 Signal Scanner: {len(watchlist)} coins")
    print("━" * 80)
    uvicorn.run(app, host="0.0.0.0", port=9004)
