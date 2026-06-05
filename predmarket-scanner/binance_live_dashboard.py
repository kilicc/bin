#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚀 BINANCE FUTURES — LIVE TRADING DASHBOARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Polymarket paneli tasarımı ile Binance Futures trading

RUN:
    python binance_live_dashboard.py
    
ACCESS:
    http://localhost:9000
"""

from __future__ import annotations
import asyncio
import json
import math
import os
from contextlib import asynccontextmanager
from datetime import datetime
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# GLOBAL STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

client = BinanceFuturesClient()
STARTING_CAPITAL = 5000.0
position_id_counter = 1

# Trading state
positions = []
closed_positions = []
price_history = {}
capital_history = []
signals = []
watchlist = ['ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'XRPUSDT']


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CORE FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fetch_price(symbol: str) -> tuple[float, float]:
    """Fetch real-time price from Binance - returns (price, latency_ms)"""
    try:
        start = time.time()
        coin = symbol.replace('USDT', '')
        price = client.mark_price(coin)
        latency = (time.time() - start) * 1000  # Convert to ms
        if price:
            return float(price), latency
    except Exception as e:
        print(f"❌ Error fetching {symbol}: {e}")
    return 0.0, 0.0


def get_current_capital() -> float:
    """Calculate current capital"""
    total_pnl = sum(p['unrealized_pnl'] for p in positions)
    realized_pnl = sum(p['pnl_usd'] for p in closed_positions)
    return STARTING_CAPITAL + realized_pnl + total_pnl


def open_position(symbol: str, side: str, size: float = None, leverage: int = 1) -> dict | None:
    """Open a new position"""
    global positions, position_id_counter
    
    try:
        entry_price, _ = fetch_price(symbol)
        if entry_price <= 0:
            print(f"❌ Could not fetch price for {symbol}")
            return None
        
        current_capital = get_current_capital()
        if size is None:
            position_value = current_capital * 0.1  # 10% per trade
            size = position_value / entry_price
        
        position = {
            'id': position_id_counter,
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'current_price': entry_price,
            'size': size,
            'leverage': leverage,
            'stake_usd': size * entry_price,
            'unrealized_pnl': 0.0,
            'pnl_pct': 0.0,
            'entry_time': time.time(),
            'entry_time_str': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'tp_target': entry_price * 1.02 if side == 'LONG' else entry_price * 0.98,
            'sl_target': entry_price * 0.98 if side == 'LONG' else entry_price * 1.02,
            'price_history': [entry_price],  # Track price history for chart
            'time_history': [datetime.utcnow().isoformat()],
        }
        
        positions.append(position)
        position_id_counter += 1
        
        print(f"✅ Opened {side} {symbol} @ ${entry_price:.2f} | Size: {size:.4f}")
        return position
        
    except Exception as e:
        print(f"❌ Error opening position: {e}")
        return None


def close_position(position_id: int, exit_reason: str = 'Manual'):
    """Close a position"""
    global positions, closed_positions
    
    for i, pos in enumerate(positions):
        if pos['id'] == position_id:
            exit_price = pos['current_price']
            pnl = pos['unrealized_pnl']
            pnl_pct = pos['pnl_pct']
            
            closed = {
                'id': pos['id'],
                'symbol': pos['symbol'],
                'side': pos['side'],
                'entry_price': pos['entry_price'],
                'exit_price': exit_price,
                'size': pos['size'],
                'stake_usd': pos['stake_usd'],
                'pnl_usd': pnl,
                'pnl_pct': pnl_pct,
                'exit_reason': exit_reason,
                'entry_time': pos['entry_time_str'],
                'exit_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'duration': time.time() - pos['entry_time']
            }
            
            closed_positions.append(closed)
            positions.pop(i)
            
            print(f"✅ Closed position #{position_id}: {pos['symbol']} | PnL: ${pnl:.2f} ({pnl_pct:.2f}%)")
            return True
    
    return False


def update_positions():
    """Update all open positions"""
    total_latency = 0
    count = 0
    
    for pos in positions:
        new_price, latency = fetch_price(pos['symbol'])
        total_latency += latency
        count += 1
        
        if new_price > 0:
            pos['current_price'] = new_price
            
            # Update price history
            pos['price_history'].append(new_price)
            pos['time_history'].append(datetime.utcnow().isoformat())
            
            # Keep last 60 points
            if len(pos['price_history']) > 60:
                pos['price_history'].pop(0)
                pos['time_history'].pop(0)
            
            if pos['side'] == 'LONG':
                pos['unrealized_pnl'] = (pos['current_price'] - pos['entry_price']) * pos['size']
            else:
                pos['unrealized_pnl'] = (pos['entry_price'] - pos['current_price']) * pos['size']
            
            pos['pnl_pct'] = (pos['unrealized_pnl'] / pos['stake_usd']) * 100
            
            # Auto TP/SL
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
    """Scan for trading signals"""
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
                
                # Momentum signal
                if len(price_history[symbol]) > 10:
                    old_price = price_history[symbol][-10]['price']
                    change = ((price - old_price) / old_price) * 100
                    
                    if abs(change) > 0.5:
                        signals.append({
                            'symbol': symbol,
                            'type': 'LONG' if change > 0 else 'SHORT',
                            'price': price,
                            'change': change,
                            'time': datetime.utcnow().strftime('%H:%M:%S')
                        })
                        
                        if len(signals) > 20:
                            signals.pop(0)
        except:
            pass


def update_capital_history():
    """Track capital over time"""
    current = get_current_capital()
    capital_history.append({
        'time': datetime.utcnow().isoformat(),
        'capital': current
    })
    
    if len(capital_history) > 100:
        capital_history.pop(0)


def get_snapshot() -> dict[str, Any]:
    """Get current dashboard snapshot"""
    current_capital = get_current_capital()
    total_unrealized = sum(p['unrealized_pnl'] for p in positions)
    total_realized = sum(p['pnl_usd'] for p in closed_positions)
    total_pnl = total_realized + total_unrealized
    
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
        },
        'positions': {
            'open': positions,
            'closed': closed_positions[-40:]  # Last 40 closed
        },
        'signals': signals[-10:],
        'equity': [p['capital'] for p in capital_history],
        'timestamps': [p['time'] for p in capital_history]
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WEBSOCKET MANAGER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BACKGROUND LOOP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def update_loop():
    """Background task - updates every second"""
    # Open initial position
    await asyncio.sleep(2)
    if len(positions) == 0:
        open_position('BTCUSDT', 'LONG')
    
    update_count = 0
    avg_latency = 0
    
    while True:
        try:
            avg_latency = update_positions()
            
            if update_count % 5 == 0:  # Scan signals every 5 seconds
                scan_signals()
            
            if update_count % 3 == 0:  # Update capital history every 3 seconds
                update_capital_history()
            
            snapshot = get_snapshot()
            snapshot['api_latency_ms'] = round(avg_latency, 1)
            await ws_manager.broadcast(snapshot)
            
            update_count += 1
            
        except Exception as e:
            print(f"❌ Update error: {e}")
        
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(update_loop())
    yield


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FASTAPI APP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

app = FastAPI(title="Binance Futures Live", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_TEMPLATE


@app.get("/api/live")
async def api_live():
    return get_snapshot()


@app.websocket("/ws")
async def ws_live(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        # Send initial snapshot
        await ws.send_text(json.dumps(get_snapshot()))
        # Keep alive
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTML TEMPLATE (Polymarket style adapted for Binance Futures)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Binance Futures — LIVE</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>
:root{--bg:#0f1419;--card:#1a2332;--bdr:#2d3a4f;--text:#e8eef7;--muted:#8b9cb3;--up:#22c55e;--dn:#ef4444;--acc:#f59e0b;--live:#ef4444}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
header{display:flex;align-items:center;gap:16px;padding:16px 24px;border-bottom:1px solid var(--bdr);background:var(--card)}
.badge{background:var(--live);color:#fff;font-size:11px;font-weight:700;padding:4px 10px;border-radius:6px;letter-spacing:.06em}
h1{font-size:18px;font-weight:700}
.sub{font-size:12px;color:var(--muted);margin-left:auto}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;padding:20px 24px}
.kpi{background:var(--card);border:1px solid var(--bdr);border-radius:10px;padding:14px 16px}
.kpi-l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.kpi-v{font-size:22px;font-weight:700;margin-top:4px;font-family:'JetBrains Mono',monospace}
.kpi-v.up{color:var(--up)}.kpi-v.dn{color:var(--dn)}.kpi-v.acc{color:var(--acc)}
main{padding:0 24px 32px;display:grid;gap:20px}
.panel{background:var(--card);border:1px solid var(--bdr);border-radius:12px;overflow:hidden}
.position-card{background:var(--card);border:1px solid var(--bdr);border-radius:12px;padding:16px;margin-bottom:16px;transition:all 0.3s}
.position-card.flash{animation:flashBorder 0.5s ease-in-out;box-shadow:0 0 20px rgba(245,158,11,0.6)}
@keyframes flashBorder{0%{border-color:var(--acc);box-shadow:0 0 20px rgba(245,158,11,0.8)}50%{border-color:var(--acc);box-shadow:0 0 30px rgba(245,158,11,1)}100%{border-color:var(--bdr)}}
.pos-chart{height:200px;margin-top:12px;border-radius:8px;overflow:hidden}
.panel-h{padding:12px 16px;border-bottom:1px solid var(--bdr);font-weight:600;font-size:13px;display:flex;justify-content:space-between;align-items:center}
.api-latency{position:absolute;top:16px;right:24px;background:var(--card);border:1px solid var(--acc);border-radius:8px;padding:8px 12px;font-size:12px;font-weight:600;color:var(--acc);font-family:'JetBrains Mono',monospace}
.rule{font-size:11px;color:var(--acc);font-weight:500}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--bdr)}
th{color:var(--muted);font-weight:500;font-size:10px;text-transform:uppercase}
tr:last-child td{border-bottom:none}
.side-long{color:var(--up);font-weight:700}.side-short{color:var(--dn);font-weight:700}
.pnl-up{color:var(--up)}.pnl-dn{color:var(--dn)}
.empty{padding:32px;text-align:center;color:var(--muted);font-size:13px}
#chart{height:240px}
.ws{font-size:11px;color:var(--muted)}.ws.ok{color:var(--up)}
.mono{font-family:'JetBrains Mono',monospace}
.signal-badge{padding:3px 8px;border-radius:4px;font-size:10px;font-weight:700}
.signal-long{background:rgba(34,197,94,.2);color:var(--up)}
.signal-short{background:rgba(239,68,68,.2);color:var(--dn)}
</style>
</head>
<body>
<div class="api-latency">⚡ <span id="apiLatency">-- ms</span></div>
<header>
  <span class="badge">LIVE</span>
  <h1>Binance Futures — Testnet Trading</h1>
  <span class="sub"><span id="wsLbl" class="ws">bağlanıyor…</span> · <span id="updateTime"></span></span>
</header>

<div class="kpis">
  <div class="kpi"><div class="kpi-l">💰 Capital (USDT)</div><div id="kCapital" class="kpi-v acc">—</div></div>
  <div class="kpi"><div class="kpi-l">📈 Total P&L</div><div id="kPnl" class="kpi-v">—</div></div>
  <div class="kpi"><div class="kpi-l">📊 Unrealized P&L</div><div id="kUnrealized" class="kpi-v">—</div></div>
  <div class="kpi"><div class="kpi-l">✅ Realized P&L</div><div id="kRealized" class="kpi-v">—</div></div>
  <div class="kpi"><div class="kpi-l">🔓 Açık</div><div id="kOpen" class="kpi-v">0</div></div>
  <div class="kpi"><div class="kpi-l">🔒 Kapalı</div><div id="kClosed" class="kpi-v">0</div></div>
</div>

<main>
  <div class="panel">
    <div class="panel-h">
      Equity Curve
      <span id="equityInfo" class="rule">Starting: $5,000</span>
    </div>
    <div id="chart"></div>
  </div>
  
  <div class="panel">
    <div class="panel-h">
      Açık Pozisyonlar
      <span id="openCount">0</span>
    </div>
    <div style="padding:16px" id="positionsGrid"></div>
  </div>
  
  <div class="panel">
    <div class="panel-h">
      Kapalı Pozisyonlar (Son 40)
    </div>
    <div style="overflow-x:auto">
      <table>
        <thead><tr>
          <th>#</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th>
          <th>Stake</th><th>P&L</th><th>%</th><th>Reason</th><th>Time</th>
        </tr></thead>
        <tbody id="closedBody">
          <tr><td colspan="10" class="empty">Henüz kapanış yok</td></tr>
        </tbody>
      </table>
    </div>
  </div>
  
  <div class="panel">
    <div class="panel-h">
      Live Signals
      <span id="signalCount">0</span>
    </div>
    <div style="overflow-x:auto">
      <table>
        <thead><tr>
          <th>Symbol</th><th>Type</th><th>Price</th><th>Change</th><th>Time</th>
        </tr></thead>
        <tbody id="signalsBody">
          <tr><td colspan="5" class="empty">Sinyal bekleniyor...</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</main>

<script>
function fmt(n){if(n==null||isNaN(n))return'—';return Math.abs(n)>=100?n.toFixed(0):n.toFixed(2);}

let lastPrices = {};

function render(data){
  const s=data.summary||{}, w=data.wallet||{}, pos=data.positions||{};
  
  // Update time & API latency
  document.getElementById('updateTime').textContent=new Date().toLocaleTimeString('tr-TR');
  document.getElementById('apiLatency').textContent=(data.api_latency_ms||0).toFixed(1)+' ms';
  
  // KPIs
  document.getElementById('kCapital').textContent='$'+fmt(s.current_capital||0);
  
  const pnl=s.total_pnl||0;
  const pnlEl=document.getElementById('kPnl');
  pnlEl.textContent=(pnl>=0?'+':'')+'$'+fmt(Math.abs(pnl))+' ('+(pnl>=0?'+':'')+fmt(s.total_pnl_pct||0)+'%)';
  pnlEl.className='kpi-v '+(pnl>=0?'up':'dn');
  
  const unrealized=s.unrealized_pnl||0;
  const unEl=document.getElementById('kUnrealized');
  unEl.textContent=(unrealized>=0?'+':'')+'$'+fmt(Math.abs(unrealized));
  unEl.className='kpi-v '+(unrealized>=0?'up':'dn');
  
  const realized=s.realized_pnl||0;
  const realEl=document.getElementById('kRealized');
  realEl.textContent=(realized>=0?'+':'')+'$'+fmt(Math.abs(realized));
  realEl.className='kpi-v '+(realized>=0?'up':'dn');
  
  document.getElementById('kOpen').textContent=String(s.open_trades||0);
  document.getElementById('kClosed').textContent=String(s.closed_trades||0);
  
  // Open positions with live charts
  const opens=pos.open||[];
  document.getElementById('openCount').textContent=String(opens.length);
  const grid=document.getElementById('positionsGrid');
  
  if(!opens.length){
    grid.innerHTML='<div class="empty">Açık pozisyon yok</div>';
  }else{
    grid.innerHTML=opens.map(x=>{
      const pnlCls=x.unrealized_pnl>=0?'pnl-up':'pnl-dn';
      const sideCls=x.side==='LONG'?'side-long':'side-short';
      const cardId='pos-'+x.id;
      const chartId='chart-'+x.id;
      
      // Check if price changed
      const priceChanged = lastPrices[x.id] !== x.current_price;
      lastPrices[x.id] = x.current_price;
      const flashClass = priceChanged ? 'flash' : '';
      
      return `
        <div class="position-card ${flashClass}" id="${cardId}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <div>
              <span class="mono" style="font-size:20px;font-weight:700">${x.symbol}</span>
              <span class="${sideCls}" style="margin-left:12px;font-size:14px">${x.side}</span>
            </div>
            <div style="text-align:right">
              <div class="${pnlCls}" style="font-size:24px;font-weight:700">${x.unrealized_pnl>=0?'+':''}$${fmt(x.unrealized_pnl)}</div>
              <div class="${pnlCls} mono" style="font-size:14px">${x.pnl_pct>=0?'+':''}${fmt(x.pnl_pct)}%</div>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;font-size:12px;margin-bottom:12px">
            <div><span style="color:var(--muted)">Entry:</span> <span class="mono">${fmt(x.entry_price)}</span></div>
            <div><span style="color:var(--muted)">Current:</span> <span class="mono" style="font-weight:700;color:var(--acc)">${fmt(x.current_price)}</span></div>
            <div><span style="color:var(--muted)">TP:</span> <span class="mono" style="color:var(--up)">${fmt(x.tp_target)}</span></div>
            <div><span style="color:var(--muted)">SL:</span> <span class="mono" style="color:var(--dn)">${fmt(x.sl_target)}</span></div>
          </div>
          <div class="pos-chart" id="${chartId}"></div>
        </div>
      `;
    }).join('');
    
    // Render charts for each position
    opens.forEach(x=>{
      const chartId='chart-'+x.id;
      if(x.price_history && x.price_history.length>1){
        const times = x.time_history || [];
        const prices = x.price_history || [];
        
        Plotly.newPlot(chartId,[{
          x:times,
          y:prices,
          type:'scatter',
          mode:'lines+markers',
          line:{color:x.side==='LONG'?'#22c55e':'#ef4444',width:2},
          marker:{size:4},
          fill:'tozeroy',
          fillcolor:x.side==='LONG'?'rgba(34,197,94,0.12)':'rgba(239,68,68,0.12)'
        },{
          x:[times[0],times[times.length-1]],
          y:[x.entry_price,x.entry_price],
          type:'scatter',
          mode:'lines',
          line:{color:'#8b9cb3',width:1,dash:'dash'},
          showlegend:false,
          hoverinfo:'skip'
        }],{
          margin:{l:40,r:20,t:5,b:30},
          paper_bgcolor:'#1a2332',
          plot_bgcolor:'#1a2332',
          font:{color:'#8b9cb3',size:10},
          xaxis:{showgrid:true,gridcolor:'#2d3a4f',showticklabels:false},
          yaxis:{showgrid:true,gridcolor:'#2d3a4f',side:'right',tickprefix:'$'}
        },{responsive:true,displayModeBar:false});
      }
    });
  }
  
  // Closed positions
  const closed=pos.closed||[];
  const cb=document.getElementById('closedBody');
  if(!closed.length){
    cb.innerHTML='<tr><td colspan="10" class="empty">Henüz kapanış yok</td></tr>';
  }else{
    cb.innerHTML=closed.slice().reverse().map(x=>{
      const pnlCls=x.pnl_usd>=0?'pnl-up':'pnl-dn';
      const sideCls=x.side==='LONG'?'side-long':'side-short';
      return `<tr>
        <td class="mono">${x.id}</td>
        <td class="mono">${x.symbol}</td>
        <td class="${sideCls}">${x.side}</td>
        <td class="mono">$${fmt(x.entry_price)}</td>
        <td class="mono">$${fmt(x.exit_price)}</td>
        <td class="mono">$${fmt(x.stake_usd)}</td>
        <td class="${pnlCls} mono">${x.pnl_usd>=0?'+':''}$${fmt(x.pnl_usd)}</td>
        <td class="${pnlCls} mono">${x.pnl_pct>=0?'+':''}${fmt(x.pnl_pct)}%</td>
        <td>${x.exit_reason||'—'}</td>
        <td style="font-size:11px">${(x.exit_time||'').slice(11,19)}</td>
      </tr>`;
    }).join('');
  }
  
  // Signals
  const signals=data.signals||[];
  document.getElementById('signalCount').textContent=String(signals.length);
  const sb=document.getElementById('signalsBody');
  if(!signals.length){
    sb.innerHTML='<tr><td colspan="5" class="empty">Sinyal bekleniyor...</td></tr>';
  }else{
    sb.innerHTML=signals.slice().reverse().map(x=>{
      const changeCls=x.change>=0?'pnl-up':'pnl-dn';
      const badgeCls=x.type==='LONG'?'signal-long':'signal-short';
      return `<tr>
        <td class="mono">${x.symbol}</td>
        <td><span class="signal-badge ${badgeCls}">${x.type}</span></td>
        <td class="mono">$${fmt(x.price)}</td>
        <td class="${changeCls} mono">${x.change>=0?'+':''}${fmt(x.change)}%</td>
        <td>${x.time}</td>
      </tr>`;
    }).join('');
  }
  
  // Equity chart
  const eq=data.equity||[], ts=data.timestamps||[];
  if(eq.length>1){
    Plotly.react('chart',[{
      x:ts,
      y:eq,
      type:'scatter',
      mode:'lines',
      line:{color:'#f59e0b',width:2},
      fill:'tozeroy',
      fillcolor:'rgba(245,158,11,.12)'
    }],{
      margin:{l:52,r:16,t:8,b:32},
      paper_bgcolor:'#1a2332',
      plot_bgcolor:'#1a2332',
      font:{color:'#8b9cb3',size:11},
      xaxis:{gridcolor:'#2d3a4f',showticklabels:false},
      yaxis:{gridcolor:'#2d3a4f',tickprefix:'$',side:'right'}
    },{responsive:true,displayModeBar:false});
  }
}

// WebSocket connection
const ws=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/ws');
ws.onopen=()=>{
  document.getElementById('wsLbl').textContent='canlı';
  document.getElementById('wsLbl').className='ws ok';
};
ws.onclose=()=>{
  document.getElementById('wsLbl').textContent='kopuk';
  document.getElementById('wsLbl').className='ws';
  setTimeout(()=>location.reload(),3000);
};
ws.onmessage=e=>{
  try{render(JSON.parse(e.data));}catch(err){console.error(err);}
};

// Initial load
fetch('/api/live').then(r=>r.json()).then(render).catch(()=>{});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    print("━" * 80)
    print("🚀 BINANCE FUTURES LIVE DASHBOARD")
    print("━" * 80)
    print(f"📡 Access: http://localhost:9001")
    print(f"💰 Starting Capital: ${STARTING_CAPITAL:,.0f} USDT")
    print(f"🔧 Mode: {'TESTNET' if not client.paper else 'PAPER'}")
    print(f"✨ Updates: Every 1 second")
    print("━" * 80)
    uvicorn.run(app, host="0.0.0.0", port=9001)
