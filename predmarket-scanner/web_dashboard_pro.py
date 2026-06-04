#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💎 PROFESSIONAL TRADING DASHBOARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Professional Grade | Real-time Data | TradingView Style

RUN:
    streamlit run web_dashboard_pro.py --server.port 8504
"""

import streamlit as st
import time
from datetime import datetime, timedelta
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from binance_futures_trader.client import BinanceFuturesClient
from dotenv import load_dotenv
import os
import numpy as np

load_dotenv()

st.set_page_config(
    page_title="Pro Trading Dashboard",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Professional CSS
st.markdown("""
<style>
    /* Base theme */
    .stApp {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
    }
    
    .block-container {
        padding-top: 2rem;
        max-width: 100%;
    }
    
    /* Hide streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Custom fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Glassmorphism cards */
    .glass-card {
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        border-radius: 20px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 24px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        transition: all 0.3s ease;
    }
    
    .glass-card:hover {
        background: rgba(255, 255, 255, 0.08);
        border-color: rgba(99, 102, 241, 0.5);
        box-shadow: 0 8px 32px rgba(99, 102, 241, 0.2);
        transform: translateY(-2px);
    }
    
    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.1) 0%, rgba(139, 92, 246, 0.1) 100%);
        backdrop-filter: blur(10px);
        border-radius: 16px;
        border: 1px solid rgba(99, 102, 241, 0.2);
        padding: 20px;
        text-align: center;
        transition: all 0.3s ease;
    }
    
    .metric-card:hover {
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.2) 0%, rgba(139, 92, 246, 0.2) 100%);
        transform: scale(1.02);
        box-shadow: 0 8px 24px rgba(99, 102, 241, 0.3);
    }
    
    .metric-value {
        font-size: 2.5rem;
        font-weight: 800;
        margin: 8px 0;
        background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    
    .metric-label {
        font-size: 0.9rem;
        color: rgba(255, 255, 255, 0.6);
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
    }
    
    /* Profit/Loss colors */
    .profit {
        color: #10b981 !important;
        text-shadow: 0 0 10px rgba(16, 185, 129, 0.5);
    }
    
    .loss {
        color: #ef4444 !important;
        text-shadow: 0 0 10px rgba(239, 68, 68, 0.5);
    }
    
    /* Position cards */
    .position-card {
        background: linear-gradient(135deg, rgba(30, 30, 46, 0.8) 0%, rgba(40, 40, 56, 0.8) 100%);
        backdrop-filter: blur(10px);
        border-radius: 16px;
        border-left: 4px solid #6366f1;
        padding: 20px;
        margin: 12px 0;
        transition: all 0.3s ease;
    }
    
    .position-card:hover {
        background: linear-gradient(135deg, rgba(40, 40, 56, 0.9) 0%, rgba(50, 50, 66, 0.9) 100%);
        border-left-width: 6px;
        transform: translateX(4px);
        box-shadow: 0 8px 24px rgba(99, 102, 241, 0.3);
    }
    
    .position-long {
        border-left-color: #10b981 !important;
    }
    
    .position-short {
        border-left-color: #ef4444 !important;
    }
    
    /* Live indicator */
    .live-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        background: #10b981;
        border-radius: 50%;
        margin-right: 8px;
        animation: pulse 2s ease-in-out infinite;
        box-shadow: 0 0 15px rgba(16, 185, 129, 0.8);
    }
    
    @keyframes pulse {
        0%, 100% { 
            opacity: 1;
            transform: scale(1);
        }
        50% { 
            opacity: 0.6;
            transform: scale(1.1);
        }
    }
    
    /* Flash animation */
    @keyframes flash-glow {
        0%, 100% { 
            box-shadow: 0 0 20px rgba(251, 191, 36, 0.6);
            border-color: rgba(251, 191, 36, 0.8);
        }
        50% { 
            box-shadow: 0 0 40px rgba(251, 191, 36, 1);
            border-color: rgba(251, 191, 36, 1);
        }
    }
    
    .flash {
        animation: flash-glow 0.6s ease-in-out;
    }
    
    /* Signal badge */
    .signal-badge {
        display: inline-block;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        margin: 4px;
        backdrop-filter: blur(10px);
        transition: all 0.3s ease;
    }
    
    .signal-long {
        background: rgba(16, 185, 129, 0.2);
        border: 1px solid rgba(16, 185, 129, 0.5);
        color: #10b981;
    }
    
    .signal-short {
        background: rgba(239, 68, 68, 0.2);
        border: 1px solid rgba(239, 68, 68, 0.5);
        color: #ef4444;
    }
    
    .signal-badge:hover {
        transform: scale(1.05);
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
    }
    
    /* Header gradient text */
    .gradient-text {
        background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 50%, #f472b6 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 800;
    }
    
    /* Scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(255, 255, 255, 0.05);
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
        border-radius: 4px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(135deg, #8b5cf6 0%, #a78bfa 100%);
    }
    
    /* Remove streamlit padding */
    .element-container {
        margin-bottom: 0.5rem !important;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_client():
    return BinanceFuturesClient()


class ProTradingDashboard:
    def __init__(self):
        self.client = get_client()
        self.capital = 5000.0
        self.starting_capital = 5000.0
        
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
            st.session_state.watchlist = ['ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'XRPUSDT']
        
        if 'flash' not in st.session_state:
            st.session_state.flash = False
        
        if 'last_update' not in st.session_state:
            st.session_state.last_update = time.time()
        
        if 'update_count' not in st.session_state:
            st.session_state.update_count = 0
    
    def fetch_price(self, symbol: str) -> float:
        """Fetch price from Binance"""
        try:
            klines = self.client.klines_history(symbol, '1m', days=1)
            if klines and len(klines) > 0:
                return float(klines[-1][4])
        except:
            pass
        return 0.0
    
    def update_data(self):
        """Update all data"""
        updated = False
        
        # Update positions
        for pos in st.session_state.positions:
            new_price = self.fetch_price(pos['symbol'])
            
            if new_price > 0:
                if abs(new_price - pos['current_price']) > 0.01:
                    updated = True
                
                pos['current_price'] = new_price
                
                if pos['side'] == 'LONG':
                    pos['pnl'] = (pos['current_price'] - pos['entry_price']) * pos['size']
                else:
                    pos['pnl'] = (pos['entry_price'] - pos['current_price']) * pos['size']
                
                pos['pnl_pct'] = (pos['pnl'] / (pos['entry_price'] * pos['size'])) * 100
                
                if pos['symbol'] not in st.session_state.price_history:
                    st.session_state.price_history[pos['symbol']] = []
                
                st.session_state.price_history[pos['symbol']].append({
                    'time': datetime.now(),
                    'price': pos['current_price'],
                    'pnl': pos['pnl']
                })
                
                if len(st.session_state.price_history[pos['symbol']]) > 100:
                    st.session_state.price_history[pos['symbol']].pop(0)
        
        # Scan for signals
        for symbol in st.session_state.watchlist:
            try:
                price = self.fetch_price(symbol)
                if price > 0:
                    if symbol not in st.session_state.price_history:
                        st.session_state.price_history[symbol] = []
                    
                    # Check for momentum signal
                    if len(st.session_state.price_history[symbol]) > 10:
                        old_price = st.session_state.price_history[symbol][-10]['price']
                        change = ((price - old_price) / old_price) * 100
                        
                        if abs(change) > 0.8:  # Strong signal threshold
                            signal_type = "LONG" if change > 0 else "SHORT"
                            st.session_state.signals.append({
                                'symbol': symbol,
                                'type': signal_type,
                                'price': price,
                                'change': change,
                                'strength': min(abs(change) * 10, 100),
                                'time': datetime.now()
                            })
                            
                            # Keep last 20 signals
                            if len(st.session_state.signals) > 20:
                                st.session_state.signals.pop(0)
                    
                    st.session_state.price_history[symbol].append({
                        'time': datetime.now(),
                        'price': price
                    })
                    
                    if len(st.session_state.price_history[symbol]) > 100:
                        st.session_state.price_history[symbol].pop(0)
            except:
                pass
        
        st.session_state.flash = updated
        st.session_state.last_update = time.time()
        st.session_state.update_count += 1
    
    def render_header(self):
        """Professional header"""
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.markdown(
                f'<h1 style="margin:0; padding:0;">'
                f'<span class="live-dot"></span>'
                f'<span class="gradient-text">Professional Trading Dashboard</span>'
                f'</h1>',
                unsafe_allow_html=True
            )
        
        with col2:
            update_ago = time.time() - st.session_state.last_update
            st.markdown(
                f'<div style="text-align:right; padding:10px 0;">'
                f'<div style="color: rgba(255,255,255,0.5); font-size:0.85rem;">Last Update</div>'
                f'<div style="color: #10b981; font-size:1.2rem; font-weight:700;">{update_ago:.1f}s ago</div>'
                f'</div>',
                unsafe_allow_html=True
            )
    
    def render_metrics(self):
        """Big metrics cards"""
        total_pnl = sum(p['pnl'] for p in st.session_state.positions)
        total_pnl_pct = (total_pnl / self.starting_capital) * 100
        current_capital = self.starting_capital + total_pnl
        
        col1, col2, col3, col4, col5 = st.columns(5)
        
        pnl_class = "profit" if total_pnl >= 0 else "loss"
        pnl_icon = "📈" if total_pnl >= 0 else "📉"
        
        with col1:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-label">💰 Capital</div>'
                f'<div class="metric-value">${current_capital:,.0f}</div>'
                f'<div style="color: rgba(255,255,255,0.5); font-size:0.9rem;">USDT</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        
        with col2:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-label">{pnl_icon} Total PnL</div>'
                f'<div class="metric-value {pnl_class}">${total_pnl:+,.2f}</div>'
                f'<div class="{pnl_class}" style="font-size:1.2rem; font-weight:700;">{total_pnl_pct:+.2f}%</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        
        with col3:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-label">📊 Positions</div>'
                f'<div class="metric-value">{len(st.session_state.positions)}</div>'
                f'<div style="color: rgba(255,255,255,0.5); font-size:0.9rem;">Open</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        
        with col4:
            signal_count = len([s for s in st.session_state.signals if (datetime.now() - s['time']).seconds < 60])
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-label">🔔 Signals</div>'
                f'<div class="metric-value">{signal_count}</div>'
                f'<div style="color: rgba(255,255,255,0.5); font-size:0.9rem;">Last 1m</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        
        with col5:
            st.markdown(
                f'<div class="metric-card">'
                f'<div class="metric-label">🔄 Updates</div>'
                f'<div class="metric-value">{st.session_state.update_count}</div>'
                f'<div style="color: rgba(255,255,255,0.5); font-size:0.9rem;">Total</div>'
                f'</div>',
                unsafe_allow_html=True
            )
    
    def render_positions(self):
        """Professional position cards with charts"""
        st.markdown('<h2 class="gradient-text">📈 Active Positions</h2>', unsafe_allow_html=True)
        
        for pos in st.session_state.positions:
            col1, col2 = st.columns([2, 3])
            
            pnl_class = "profit" if pos['pnl'] >= 0 else "loss"
            side_class = "position-long" if pos['side'] == "LONG" else "position-short"
            flash_class = "flash" if st.session_state.flash else ""
            
            with col1:
                duration = time.time() - pos['entry_time']
                duration_str = f"{int(duration//3600)}h {int((duration%3600)//60)}m"
                
                st.markdown(
                    f'<div class="position-card {side_class} {flash_class}">'
                    f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">'
                    f'<div><h2 style="margin:0; color:#fff;">{pos["symbol"]}</h2></div>'
                    f'<div><span class="signal-badge signal-{"long" if pos["side"]=="LONG" else "short"}">{pos["side"]}</span></div>'
                    f'</div>'
                    f'<div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin:16px 0;">'
                    f'<div><div style="color:rgba(255,255,255,0.5); font-size:0.85rem;">Entry Price</div><div style="color:#fff; font-size:1.2rem; font-weight:700;">${pos["entry_price"]:,.2f}</div></div>'
                    f'<div><div style="color:rgba(255,255,255,0.5); font-size:0.85rem;">Current Price</div><div style="color:#fbbf24; font-size:1.2rem; font-weight:700;">${pos["current_price"]:,.2f}</div></div>'
                    f'<div><div style="color:rgba(255,255,255,0.5); font-size:0.85rem;">Size</div><div style="color:#fff; font-size:1.2rem; font-weight:700;">{pos["size"]} BTC</div></div>'
                    f'<div><div style="color:rgba(255,255,255,0.5); font-size:0.85rem;">Leverage</div><div style="color:#fff; font-size:1.2rem; font-weight:700;">{pos["leverage"]}x</div></div>'
                    f'</div>'
                    f'<div style="padding:16px 0; border-top:1px solid rgba(255,255,255,0.1);">'
                    f'<div style="display:flex; justify-content:space-between; align-items:center;">'
                    f'<div><div style="color:rgba(255,255,255,0.5); font-size:0.85rem;">PnL</div><div class="{pnl_class}" style="font-size:2rem; font-weight:800;">${pos["pnl"]:+,.2f}</div></div>'
                    f'<div class="{pnl_class}" style="font-size:1.8rem; font-weight:700;">{pos["pnl_pct"]:+.2f}%</div>'
                    f'</div>'
                    f'</div>'
                    f'<div style="color:rgba(255,255,255,0.4); font-size:0.85rem; margin-top:12px;">Duration: {duration_str}</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
            
            with col2:
                if pos['symbol'] in st.session_state.price_history and st.session_state.price_history[pos['symbol']]:
                    data = st.session_state.price_history[pos['symbol']][-50:]
                    
                    fig = go.Figure()
                    
                    # Price line
                    fig.add_trace(go.Scatter(
                        x=[d['time'] for d in data],
                        y=[d['price'] for d in data],
                        mode='lines',
                        line=dict(
                            color='#10b981' if pos['pnl'] >= 0 else '#ef4444',
                            width=3
                        ),
                        fill='tozeroy',
                        fillcolor='rgba(16, 185, 129, 0.1)' if pos['pnl'] >= 0 else 'rgba(239, 68, 68, 0.1)',
                        name='Price'
                    ))
                    
                    # Entry line
                    fig.add_hline(
                        y=pos['entry_price'],
                        line_dash="dash",
                        line_color="#fbbf24",
                        line_width=2,
                        annotation_text=f"Entry ${pos['entry_price']:,.2f}",
                        annotation_position="right"
                    )
                    
                    fig.update_layout(
                        height=250,
                        margin=dict(l=0, r=0, t=10, b=0),
                        xaxis=dict(
                            showgrid=False,
                            showticklabels=False,
                            zeroline=False
                        ),
                        yaxis=dict(
                            showgrid=True,
                            gridcolor='rgba(255,255,255,0.05)',
                            side='right',
                            tickfont=dict(color='rgba(255,255,255,0.6)')
                        ),
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        showlegend=False,
                        hovermode='x unified'
                    )
                    
                    st.plotly_chart(fig, use_container_width=True, key=f"chart_{pos['symbol']}")
    
    def render_signals(self):
        """Signal panel"""
        st.markdown('<h2 class="gradient-text">🔔 Live Signals</h2>', unsafe_allow_html=True)
        
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        
        if st.session_state.signals:
            recent_signals = sorted(st.session_state.signals, key=lambda x: x['time'], reverse=True)[:8]
            
            for sig in recent_signals:
                age = (datetime.now() - sig['time']).seconds
                if age < 120:  # Show signals less than 2 min old
                    st.markdown(
                        f'<div style="display:flex; justify-content:space-between; align-items:center; padding:12px; margin:8px 0; background:rgba(255,255,255,0.03); border-radius:12px;">'
                        f'<div><span style="font-weight:700; font-size:1.1rem; color:#fff;">{sig["symbol"]}</span> <span class="signal-badge signal-{"long" if sig["type"]=="LONG" else "short"}">{sig["type"]}</span></div>'
                        f'<div style="color:#fbbf24; font-weight:700;">${sig["price"]:,.2f}</div>'
                        f'<div class="{"profit" if sig["change"] >= 0 else "loss"}" style="font-weight:700;">{sig["change"]:+.2f}%</div>'
                        f'<div style="color:rgba(255,255,255,0.4); font-size:0.85rem;">{age}s ago</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
        else:
            st.info("🔍 Scanning markets for signals...")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    def run(self):
        """Main loop"""
        self.update_data()
        
        self.render_header()
        st.markdown("<br>", unsafe_allow_html=True)
        
        self.render_metrics()
        st.markdown("<br>", unsafe_allow_html=True)
        
        col1, col2 = st.columns([7, 3])
        
        with col1:
            self.render_positions()
        
        with col2:
            self.render_signals()
        
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    dashboard = ProTradingDashboard()
    dashboard.run()
