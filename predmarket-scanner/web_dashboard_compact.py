#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 COMPACT DASHBOARD - LIVE TRADING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

5000 USDT | Binance Futures | Real-time | Signal Scanner

RUN:
    streamlit run web_dashboard_compact.py --server.port 8503
"""

import streamlit as st
import time
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
from binance_futures_trader.client import BinanceFuturesClient
from dotenv import load_dotenv
import os

load_dotenv()

st.set_page_config(
    page_title="Trading Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Compact CSS
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    h1 { font-size: 1.5rem !important; margin-bottom: 0.5rem !important; }
    h2 { font-size: 1.2rem !important; margin-bottom: 0.5rem !important; }
    h3 { font-size: 1rem !important; margin-bottom: 0.3rem !important; }
    
    @keyframes flash { 
        0%, 100% { border-color: #ffeb3b; box-shadow: 0 0 10px #ffeb3b; }
        50% { border-color: #ffc107; box-shadow: 0 0 20px #ffc107; }
    }
    
    .flash { animation: flash 0.5s ease-in-out; border: 2px solid #ffeb3b !important; }
    .metric-sm { padding: 8px; border-radius: 8px; background: #1e1e1e; border: 1px solid #333; margin: 5px 0; }
    .profit { color: #00ff88 !important; }
    .loss { color: #ff4444 !important; }
    .signal-new { background: rgba(255,235,59,0.1); border-left: 3px solid #ffeb3b; padding: 8px; margin: 5px 0; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_client():
    return BinanceFuturesClient()


class CompactDashboard:
    def __init__(self):
        self.client = get_client()
        self.capital = 5000.0
        self.starting_capital = 5000.0
        
        # Init state
        if 'positions' not in st.session_state:
            st.session_state.positions = [{
                'symbol': 'BTCUSDT',
                'side': 'LONG',
                'entry_price': 76500.0,
                'current_price': 76500.0,
                'size': 0.065,
                'leverage': 1,
                'pnl': 0.0,
                'pnl_pct': 0.0,
                'entry_time': time.time()
            }]
        
        if 'price_history' not in st.session_state:
            st.session_state.price_history = {}
        
        if 'signals' not in st.session_state:
            st.session_state.signals = []
        
        if 'watchlist' not in st.session_state:
            # Watchlist for signal scanning
            st.session_state.watchlist = ['ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT']
        
        if 'flash' not in st.session_state:
            st.session_state.flash = False
        
        if 'last_update' not in st.session_state:
            st.session_state.last_update = time.time()
    
    def fetch_price(self, symbol: str) -> float:
        """Fetch single price (fixed method)"""
        try:
            # Use klines_history without limit parameter
            klines = self.client.klines_history(symbol, '1m')
            if klines and len(klines) > 0:
                return float(klines[-1][4])  # Close price
        except Exception as e:
            st.error(f"Error fetching {symbol}: {e}")
        return 0.0
    
    def update_positions(self):
        """Update position prices"""
        updated = False
        
        for pos in st.session_state.positions:
            new_price = self.fetch_price(pos['symbol'])
            
            if new_price > 0 and new_price != pos['current_price']:
                updated = True
                pos['current_price'] = new_price
                
                # Calculate PnL
                if pos['side'] == 'LONG':
                    pos['pnl'] = (pos['current_price'] - pos['entry_price']) * pos['size']
                else:
                    pos['pnl'] = (pos['entry_price'] - pos['current_price']) * pos['size']
                
                pos['pnl_pct'] = (pos['pnl'] / (pos['entry_price'] * pos['size'])) * 100
                
                # Store history
                if pos['symbol'] not in st.session_state.price_history:
                    st.session_state.price_history[pos['symbol']] = []
                
                st.session_state.price_history[pos['symbol']].append({
                    'time': datetime.now(),
                    'price': pos['current_price']
                })
                
                # Keep last 100
                if len(st.session_state.price_history[pos['symbol']]) > 100:
                    st.session_state.price_history[pos['symbol']].pop(0)
        
        st.session_state.flash = updated
        st.session_state.last_update = time.time()
    
    def scan_signals(self):
        """Scan watchlist for signals"""
        # Simple momentum signal: price change > 1%
        new_signals = []
        
        for symbol in st.session_state.watchlist:
            try:
                price = self.fetch_price(symbol)
                
                if price > 0:
                    # Check if we have previous price
                    if symbol in st.session_state.price_history and len(st.session_state.price_history[symbol]) > 5:
                        old_price = st.session_state.price_history[symbol][-5]['price']
                        change_pct = ((price - old_price) / old_price) * 100
                        
                        if abs(change_pct) > 0.5:  # Signal if >0.5% move
                            signal_type = "🟢 LONG" if change_pct > 0 else "🔴 SHORT"
                            new_signals.append({
                                'symbol': symbol,
                                'type': signal_type,
                                'price': price,
                                'change': change_pct,
                                'time': datetime.now()
                            })
                    
                    # Update watchlist history
                    if symbol not in st.session_state.price_history:
                        st.session_state.price_history[symbol] = []
                    
                    st.session_state.price_history[symbol].append({
                        'time': datetime.now(),
                        'price': price
                    })
                    
                    if len(st.session_state.price_history[symbol]) > 100:
                        st.session_state.price_history[symbol].pop(0)
                        
            except:
                pass
        
        # Add new signals (keep last 10)
        if new_signals:
            st.session_state.signals.extend(new_signals)
            st.session_state.signals = st.session_state.signals[-10:]
    
    def render_header(self):
        """Compact header"""
        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
        
        with col1:
            st.markdown("### 📊 Live Trading")
        
        with col2:
            total_pnl = sum(p['pnl'] for p in st.session_state.positions)
            pnl_color = "profit" if total_pnl >= 0 else "loss"
            st.markdown(f'<div class="metric-sm"><small>PnL</small><br><span class="{pnl_color}" style="font-size:1.3rem; font-weight:bold;">${total_pnl:+.2f}</span></div>', unsafe_allow_html=True)
        
        with col3:
            current_capital = self.starting_capital + sum(p['pnl'] for p in st.session_state.positions)
            st.markdown(f'<div class="metric-sm"><small>Capital</small><br><span style="font-size:1.3rem; font-weight:bold; color:#ffeb3b;">${current_capital:,.0f}</span></div>', unsafe_allow_html=True)
        
        with col4:
            last_update_ago = time.time() - st.session_state.last_update
            st.markdown(f'<div class="metric-sm"><small>Update</small><br><span style="font-size:1.3rem; font-weight:bold; color:#00ff88;">{last_update_ago:.1f}s</span></div>', unsafe_allow_html=True)
    
    def render_positions(self):
        """Compact positions with charts"""
        st.markdown("### 📈 Open Positions")
        
        for pos in st.session_state.positions:
            col1, col2 = st.columns([2, 3])
            
            pnl_color = "profit" if pos['pnl'] >= 0 else "loss"
            flash_class = "flash" if st.session_state.flash else ""
            
            with col1:
                st.markdown(
                    f'<div class="metric-sm {flash_class}">'
                    f'<div style="font-size:1.3rem; font-weight:bold;">{pos["symbol"]} <span style="color: {"#00ff88" if pos["side"]=="LONG" else "#ff4444"};">{pos["side"]}</span></div>'
                    f'<div style="margin:5px 0;">Entry: <b>${pos["entry_price"]:,.2f}</b> | Current: <b style="color:#ffeb3b;">${pos["current_price"]:,.2f}</b></div>'
                    f'<div>Size: {pos["size"]} BTC | Leverage: {pos["leverage"]}x</div>'
                    f'<div class="{pnl_color}" style="font-size:1.5rem; font-weight:bold; margin-top:8px;">${pos["pnl"]:+.2f} ({pos["pnl_pct"]:+.2f}%)</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
            
            with col2:
                # Compact chart
                if pos['symbol'] in st.session_state.price_history and st.session_state.price_history[pos['symbol']]:
                    data = st.session_state.price_history[pos['symbol']][-30:]  # Last 30 points
                    
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=[d['time'] for d in data],
                        y=[d['price'] for d in data],
                        mode='lines',
                        line=dict(color='#00ff88' if pos['pnl'] >= 0 else '#ff4444', width=2),
                        fill='tozeroy'
                    ))
                    
                    fig.add_hline(y=pos['entry_price'], line_dash="dash", line_color="yellow", line_width=1)
                    
                    fig.update_layout(
                        height=150,
                        margin=dict(l=0, r=0, t=0, b=0),
                        xaxis=dict(showgrid=False, showticklabels=False),
                        yaxis=dict(showgrid=True, gridcolor='#333', side='right'),
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        showlegend=False
                    )
                    
                    st.plotly_chart(fig, use_container_width=True, key=f"chart_{pos['symbol']}")
    
    def render_signals(self):
        """Render signal scanner"""
        st.markdown("### 🔍 Signal Scanner")
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            st.markdown("**Watchlist:**")
            for symbol in st.session_state.watchlist:
                if symbol in st.session_state.price_history and st.session_state.price_history[symbol]:
                    price = st.session_state.price_history[symbol][-1]['price']
                    
                    # Calculate change
                    if len(st.session_state.price_history[symbol]) > 5:
                        old_price = st.session_state.price_history[symbol][-5]['price']
                        change = ((price - old_price) / old_price) * 100
                        color = "profit" if change >= 0 else "loss"
                        st.markdown(f'<div class="metric-sm"><b>{symbol}</b> ${price:,.2f} <span class="{color}">({change:+.2f}%)</span></div>', unsafe_allow_html=True)
        
        with col2:
            st.markdown("**Recent Signals:**")
            
            if st.session_state.signals:
                for sig in reversed(st.session_state.signals[-5:]):  # Last 5 signals
                    st.markdown(
                        f'<div class="signal-new">'
                        f'<b>{sig["type"]}</b> {sig["symbol"]} @ ${sig["price"]:,.2f} '
                        f'<span class="{"profit" if sig["change"] >= 0 else "loss"}">({sig["change"]:+.2f}%)</span>'
                        f'<small style="color:#888;"> | {sig["time"].strftime("%H:%M:%S")}</small>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
            else:
                st.info("Scanning for signals...")
    
    def run(self):
        """Main loop"""
        # Update data
        self.update_positions()
        self.scan_signals()
        
        # Render
        self.render_header()
        st.divider()
        
        col1, col2 = st.columns([3, 2])
        
        with col1:
            self.render_positions()
        
        with col2:
            self.render_signals()
        
        # Auto-refresh
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    dashboard = CompactDashboard()
    dashboard.run()
