#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚀 REAL-TIME TRADING DASHBOARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FastAPI + WebSocket + Real Binance Futures API
Saniyede bir güncellenen gerçek veriler

RUN:
    python trading_dashboard.py
    
ACCESS:
    http://localhost:8000
"""

from __future__ import annotations
import asyncio
import json
import math
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# Load env and set testnet mode BEFORE importing client
load_dotenv(override=True)
os.environ['BN_FUT_MODE'] = 'testnet'
os.environ['BINANCE_FUTURES_TESTNET'] = '1'

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from binance_futures_trader.client import BinanceFuturesClient
import time

# Global state
client = BinanceFuturesClient()
CAPITAL = 5000.0
STARTING_CAPITAL = 5000.0
position_id_counter = 1

# Position state
positions = []

price_history = {}
signals = []
watchlist = ['ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'XRPUSDT']
update_count = 0


def fetch_price(symbol: str) -> float:
    """Fetch real-time price from Binance"""
    try:
        # Extract coin from symbol (BTCUSDT -> BTC)
        coin = symbol.replace('USDT', '')
        price = client.mark_price(coin)
        if price:
            return float(price)
    except Exception as e:
        print(f"❌ Error fetching {symbol}: {e}")
    return 0.0


def open_position(symbol: str, side: str, size: float = None, leverage: int = 1):
    """Open a new position"""
    global positions, position_id_counter, CAPITAL
    
    try:
        entry_price = fetch_price(symbol)
        if entry_price <= 0:
            print(f"❌ Could not fetch price for {symbol}")
            return None
        
        # Calculate size if not provided
        if size is None:
            position_value = CAPITAL * 0.1  # 10% of capital per trade
            size = position_value / entry_price
        
        position = {
            'id': position_id_counter,
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'current_price': entry_price,
            'size': size,
            'leverage': leverage,
            'pnl': 0.0,
            'pnl_pct': 0.0,
            'entry_time': time.time()
        }
        
        positions.append(position)
        position_id_counter += 1
        
        print(f"✅ Opened {side} position: {symbol} @ ${entry_price:.2f} | Size: {size:.4f}")
        return position
        
    except Exception as e:
        print(f"❌ Error opening position: {e}")
        return None


def close_position(position_id: int):
    """Close a position by ID"""
    global positions, CAPITAL
    
    for i, pos in enumerate(positions):
        if pos['id'] == position_id:
            exit_price = pos['current_price']
            pnl = pos['pnl']
            CAPITAL += pnl
            
            print(f"✅ Closed position #{position_id}: {pos['symbol']} | PnL: ${pnl:.2f}")
            positions.pop(i)
            return True
    
    return False


def update_data():
    """Update all positions and scan signals"""
    global positions, price_history, signals, update_count
    
    # Update positions
    for pos in positions:
        new_price = fetch_price(pos['symbol'])
        
        if new_price > 0:
            pos['current_price'] = new_price
            
            if pos['side'] == 'LONG':
                pos['pnl'] = (pos['current_price'] - pos['entry_price']) * pos['size']
            else:
                pos['pnl'] = (pos['entry_price'] - pos['current_price']) * pos['size']
            
            pos['pnl_pct'] = (pos['pnl'] / (pos['entry_price'] * pos['size'])) * 100
            
            if pos['symbol'] not in price_history:
                price_history[pos['symbol']] = []
            
            price_history[pos['symbol']].append({
                'time': datetime.utcnow().isoformat(),
                'price': pos['current_price']
            })
            
            if len(price_history[pos['symbol']]) > 100:
                price_history[pos['symbol']].pop(0)
    
    # Scan for signals
    for symbol in watchlist:
        try:
            price = fetch_price(symbol)
            if price > 0:
                if symbol not in price_history:
                    price_history[symbol] = []
                
                # Check momentum
                if len(price_history[symbol]) > 10:
                    old_price = price_history[symbol][-10]['price']
                    change = ((price - old_price) / old_price) * 100
                    
                    if abs(change) > 0.5:
                        signals.append({
                            'symbol': symbol,
                            'type': 'LONG' if change > 0 else 'SHORT',
                            'price': price,
                            'change': change,
                            'time': datetime.utcnow().isoformat()
                        })
                        
                        if len(signals) > 20:
                            signals.pop(0)
                
                price_history[symbol].append({
                    'time': datetime.utcnow().isoformat(),
                    'price': price
                })
                
                if len(price_history[symbol]) > 100:
                    price_history[symbol].pop(0)
        except:
            pass
    
    update_count += 1


def get_snapshot() -> dict[str, Any]:
    """Get current dashboard snapshot"""
    total_pnl = sum(p['pnl'] for p in positions)
    current_capital = STARTING_CAPITAL + total_pnl
    
    return {
        'ts': datetime.utcnow().isoformat() + 'Z',
        'mode': 'LIVE',
        'capital': current_capital,
        'starting_capital': STARTING_CAPITAL,
        'total_pnl': total_pnl,
        'total_pnl_pct': (total_pnl / STARTING_CAPITAL) * 100,
        'positions': positions,
        'signals': signals[-10:],
        'watchlist': {sym: price_history.get(sym, [])[-1] if price_history.get(sym) else None for sym in watchlist},
        'update_count': update_count,
        'price_history': {k: v[-30:] for k, v in price_history.items()}  # Last 30 points
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
    """Background task to update data every second"""
    # Open initial demo position
    await asyncio.sleep(2)
    if len(positions) == 0:
        open_position('BTCUSDT', 'LONG')
    
    while True:
        try:
            update_data()
            snapshot = get_snapshot()
            await ws_manager.broadcast(snapshot)
        except Exception as e:
            print(f"Update error: {e}")
        await asyncio.sleep(1)  # Update every 1 second


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background task
    task = asyncio.create_task(update_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def get_html():
    return HTMLResponse(HTML_TEMPLATE)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        # Send initial snapshot
        await websocket.send_text(json.dumps(get_snapshot()))
        # Keep connection alive
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trading Dashboard - LIVE</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{--bg:#0a0e27;--card:rgba(26,31,58,0.8);--border:rgba(99,102,241,0.3);--text:#e8eef7;--muted:#8b9cb3;--profit:#10b981;--loss:#ef4444;--warning:#fbbf24;--primary:#6366f1}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#0a0e27 0%,#1a1f3a 100%);color:var(--text);min-height:100vh;overflow-x:hidden}
header{padding:24px;background:var(--card);backdrop-filter:blur(10px);border-bottom:2px solid var(--border);display:flex;align-items:center;gap:16px}
.live-dot{width:12px;height:12px;background:var(--profit);border-radius:50%;animation:pulse 2s infinite;box-shadow:0 0 10px var(--profit)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
h1{font-size:28px;font-weight:800;background:linear-gradient(135deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.status{margin-left:auto;font-size:14px;color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;padding:24px;max-width:1400px;margin:0 auto}
.metric{background:var(--card);backdrop-filter:blur(10px);border:1px solid var(--border);border-radius:16px;padding:20px;transition:all 0.3s}
.metric:hover{transform:translateY(-4px);box-shadow:0 8px 24px rgba(99,102,241,0.3)}
.metric-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}
.metric-value{font-size:32px;font-weight:800;margin:8px 0}
.profit{color:var(--profit)}
.loss{color:var(--loss)}
.warning{color:var(--warning)}
main{max-width:1400px;margin:0 auto;padding:0 24px 40px}
.grid{display:grid;grid-template-columns:2fr 1fr;gap:24px;margin-bottom:24px}
.panel{background:var(--card);backdrop-filter:blur(10px);border:1px solid var(--border);border-radius:16px;padding:24px}
.panel-title{font-size:18px;font-weight:700;margin-bottom:20px;display:flex;align-items:center;gap:8px}
.position-card{background:rgba(255,255,255,0.03);border-radius:12px;border-left:4px solid var(--primary);padding:20px;margin-bottom:16px}
.position-long{border-left-color:var(--profit)}
.position-short{border-left-color:var(--loss)}
.pos-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.pos-symbol{font-size:24px;font-weight:700}
.pos-badge{padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600}
.badge-long{background:rgba(16,185,129,0.2);color:var(--profit)}
.badge-short{background:rgba(239,68,68,0.2);color:var(--loss)}
.pos-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin:16px 0}
.pos-item{font-size:14px}
.pos-label{color:var(--muted);margin-bottom:4px}
.pos-value{font-size:18px;font-weight:700}
.pos-pnl{padding:16px 0;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.signal-item{background:rgba(255,255,255,0.03);border-radius:8px;padding:12px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}
.signal-symbol{font-weight:700;font-size:16px}
#chart{height:300px;margin-top:16px}
</style>
</head>
<body>
<header>
  <div class="live-dot"></div>
  <h1>Real-Time Trading Dashboard</h1>
  <div class="status">
    <span id="ws-status">Connecting...</span> | 
    <span id="update-time">--</span>
  </div>
</header>

<div class="metrics">
  <div class="metric">
    <div class="metric-label">💰 Capital</div>
    <div class="metric-value" id="capital">$5,000</div>
  </div>
  <div class="metric">
    <div class="metric-label">📈 Total PnL</div>
    <div class="metric-value" id="pnl">$0.00</div>
  </div>
  <div class="metric">
    <div class="metric-label">📊 Positions</div>
    <div class="metric-value" id="positions">0</div>
  </div>
  <div class="metric">
    <div class="metric-label">🔔 Signals</div>
    <div class="metric-value" id="signals">0</div>
  </div>
  <div class="metric">
    <div class="metric-label">🔄 Updates</div>
    <div class="metric-value" id="updates">0</div>
  </div>
</div>

<main>
  <div class="grid">
    <div class="panel">
      <div class="panel-title">📈 Active Positions</div>
      <div id="positions-container"></div>
      <div id="chart"></div>
    </div>
    
    <div class="panel">
      <div class="panel-title">🔔 Live Signals</div>
      <div id="signals-container"></div>
    </div>
  </div>
</main>

<script>
let ws = null;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  
  ws.onopen = () => {
    document.getElementById('ws-status').textContent = 'Connected';
    document.getElementById('ws-status').style.color = '#10b981';
  };
  
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    render(data);
  };
  
  ws.onclose = () => {
    document.getElementById('ws-status').textContent = 'Disconnected';
    document.getElementById('ws-status').style.color = '#ef4444';
    setTimeout(connect, 2000);
  };
}

function render(data) {
  // Update metrics
  document.getElementById('capital').textContent = `$${data.capital.toFixed(2)}`;
  document.getElementById('capital').className = 'metric-value';
  
  const pnlEl = document.getElementById('pnl');
  pnlEl.textContent = `$${data.total_pnl >= 0 ? '+' : ''}${data.total_pnl.toFixed(2)} (${data.total_pnl_pct >= 0 ? '+' : ''}${data.total_pnl_pct.toFixed(2)}%)`;
  pnlEl.className = `metric-value ${data.total_pnl >= 0 ? 'profit' : 'loss'}`;
  
  document.getElementById('positions').textContent = data.positions.length;
  document.getElementById('signals').textContent = data.signals.length;
  document.getElementById('updates').textContent = data.update_count;
  document.getElementById('update-time').textContent = new Date().toLocaleTimeString();
  
  // Render positions
  const posContainer = document.getElementById('positions-container');
  posContainer.innerHTML = data.positions.map(pos => {
    const pnlClass = pos.pnl >= 0 ? 'profit' : 'loss';
    const sideClass = pos.side === 'LONG' ? 'position-long' : 'position-short';
    const badgeClass = pos.side === 'LONG' ? 'badge-long' : 'badge-short';
    
    return `
      <div class="position-card ${sideClass}">
        <div class="pos-header">
          <div class="pos-symbol">${pos.symbol}</div>
          <div class="pos-badge ${badgeClass}">${pos.side}</div>
        </div>
        <div class="pos-grid">
          <div class="pos-item">
            <div class="pos-label">Entry Price</div>
            <div class="pos-value">$${pos.entry_price.toFixed(2)}</div>
          </div>
          <div class="pos-item">
            <div class="pos-label">Current Price</div>
            <div class="pos-value warning">$${pos.current_price.toFixed(2)}</div>
          </div>
          <div class="pos-item">
            <div class="pos-label">Size</div>
            <div class="pos-value">${pos.size} BTC</div>
          </div>
          <div class="pos-item">
            <div class="pos-label">Leverage</div>
            <div class="pos-value">${pos.leverage}x</div>
          </div>
        </div>
        <div class="pos-pnl">
          <div>
            <div style="font-size:12px;color:var(--muted)">PnL</div>
            <div style="font-size:28px;font-weight:800" class="${pnlClass}">$${pos.pnl >= 0 ? '+' : ''}${pos.pnl.toFixed(2)}</div>
          </div>
          <div style="font-size:24px;font-weight:700" class="${pnlClass}">${pos.pnl_pct >= 0 ? '+' : ''}${pos.pnl_pct.toFixed(2)}%</div>
        </div>
      </div>
    `;
  }).join('');
  
  // Render signals
  const sigContainer = document.getElementById('signals-container');
  if (data.signals.length === 0) {
    sigContainer.innerHTML = '<div style="text-align:center;padding:40px;color:var(--muted)">🔍 Scanning for signals...</div>';
  } else {
    sigContainer.innerHTML = data.signals.slice().reverse().map(sig => {
      const changeClass = sig.change >= 0 ? 'profit' : 'loss';
      const badgeClass = sig.type === 'LONG' ? 'badge-long' : 'badge-short';
      
      return `
        <div class="signal-item">
          <div>
            <span class="signal-symbol">${sig.symbol}</span>
            <span class="pos-badge ${badgeClass}">${sig.type}</span>
          </div>
          <div>
            <span style="color:var(--warning);font-weight:700">$${sig.price.toFixed(2)}</span>
            <span class="${changeClass}" style="margin-left:12px;font-weight:700">${sig.change >= 0 ? '+' : ''}${sig.change.toFixed(2)}%</span>
          </div>
        </div>
      `;
    }).join('');
  }
  
  // Update chart
  if (data.price_history.BTCUSDT && data.price_history.BTCUSDT.length > 0) {
    const btcHistory = data.price_history.BTCUSDT;
    const times = btcHistory.map(d => d.time);
    const prices = btcHistory.map(d => d.price);
    
    const trace = {
      x: times,
      y: prices,
      type: 'scatter',
      mode: 'lines',
      line: {color: '#10b981', width: 3},
      fill: 'tozeroy',
      fillcolor: 'rgba(16,185,129,0.1)'
    };
    
    const layout = {
      height: 300,
      margin: {l: 50, r: 20, t: 20, b: 40},
      plot_bgcolor: 'rgba(0,0,0,0)',
      paper_bgcolor: 'rgba(0,0,0,0)',
      font: {color: '#e8eef7'},
      xaxis: {showgrid: false, showticklabels: false},
      yaxis: {showgrid: true, gridcolor: 'rgba(255,255,255,0.1)', side: 'right'}
    };
    
    Plotly.newPlot('chart', [trace], layout, {displayModeBar: false});
  }
}

connect();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Real-Time Trading Dashboard...")
    print("📡 Access: http://localhost:9000")
    print("✨ Live updates every 1 second")
    uvicorn.run(app, host="0.0.0.0", port=9000)
