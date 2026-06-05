#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 ADVANCED WEB DASHBOARD - LIVE TRADING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

5000 USDT | Binance Futures Demo | Real-time Data | <1s Updates

RUN:
    streamlit run web_dashboard_advanced.py --server.port 8501
    
ACCESS:
    http://localhost:8501
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

# Page config
st.set_page_config(
    page_title="Advanced Trading Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS with flash effect
st.markdown("""
<style>
    /* Dark theme */
    .stApp {
        background-color: #0e1117;
    }
    
    /* Flash animation for updates */
    @keyframes flash-border {
        0% { border-color: #ffeb3b; box-shadow: 0 0 20px #ffeb3b; }
        50% { border-color: #ffc107; box-shadow: 0 0 30px #ffc107; }
        100% { border-color: #ffeb3b; box-shadow: 0 0 20px #ffeb3b; }
    }
    
    .flash-update {
        animation: flash-border 0.5s ease-in-out;
        border: 2px solid #ffeb3b !important;
        border-radius: 10px;
        padding: 10px;
    }
    
    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, #1e1e1e 0%, #2a2a2a 100%);
        padding: 20px;
        border-radius: 15px;
        border: 2px solid #333;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        margin: 10px 0;
    }
    
    .metric-card:hover {
        border-color: #ffeb3b;
        box-shadow: 0 0 15px rgba(255,235,59,0.3);
        transition: all 0.3s ease;
    }
    
    /* Big numbers */
    .big-number {
        font-size: 3rem !important;
        font-weight: bold;
        margin: 0;
        line-height: 1;
    }
    
    .profit {
        color: #00ff88 !important;
    }
    
    .loss {
        color: #ff4444 !important;
    }
    
    /* Position status */
    .position-long {
        background: linear-gradient(90deg, rgba(0,255,136,0.1) 0%, transparent 100%);
        border-left: 4px solid #00ff88;
    }
    
    .position-short {
        background: linear-gradient(90deg, rgba(255,68,68,0.1) 0%, transparent 100%);
        border-left: 4px solid #ff4444;
    }
    
    /* Status indicators */
    .status-live {
        display: inline-block;
        width: 12px;
        height: 12px;
        background: #00ff88;
        border-radius: 50%;
        animation: pulse 2s infinite;
        margin-right: 8px;
    }
    
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    
    /* Scrollbar */
    ::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }
    
    ::-webkit-scrollbar-track {
        background: #1e1e1e;
    }
    
    ::-webkit-scrollbar-thumb {
        background: #ffeb3b;
        border-radius: 5px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: #ffc107;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_binance_client():
    """Initialize Binance client"""
    return BinanceFuturesClient()


class AdvancedTradingDashboard:
    def __init__(self):
        self.client = get_binance_client()
        self.capital = 5000.0
        self.starting_capital = 5000.0
        
        # Initialize session state
        if 'positions' not in st.session_state:
            st.session_state.positions = [
                {
                    'symbol': 'BTCUSDT',
                    'side': 'LONG',
                    'entry_price': 76500.0,
                    'current_price': 76500.0,
                    'size': 0.065,
                    'leverage': 1,
                    'pnl': 0.0,
                    'pnl_pct': 0.0,
                    'entry_time': time.time(),
                    'open_duration': 0
                }
            ]
        
        if 'price_history' not in st.session_state:
            st.session_state.price_history = {}
        
        if 'pnl_history' not in st.session_state:
            st.session_state.pnl_history = []
        
        if 'capital_history' not in st.session_state:
            st.session_state.capital_history = []
        
        if 'last_update' not in st.session_state:
            st.session_state.last_update = time.time()
        
        if 'update_count' not in st.session_state:
            st.session_state.update_count = 0
        
        if 'flash_update' not in st.session_state:
            st.session_state.flash_update = False
        
        if 'trades_history' not in st.session_state:
            st.session_state.trades_history = []
    
    def fetch_live_prices(self):
        """Fetch live prices from Binance"""
        updated = False
        
        for pos in st.session_state.positions:
            try:
                # Get real-time price from Binance
                ticker = self.client.klines_history(
                    pos['symbol'], 
                    '1m', 
                    limit=1
                )
                
                if ticker and len(ticker) > 0:
                    new_price = float(ticker[-1][4])  # Close price
                    
                    if new_price != pos['current_price']:
                        updated = True
                        pos['current_price'] = new_price
                    
                    # Calculate PnL
                    if pos['side'] == 'LONG':
                        pos['pnl'] = (pos['current_price'] - pos['entry_price']) * pos['size']
                    else:  # SHORT
                        pos['pnl'] = (pos['entry_price'] - pos['current_price']) * pos['size']
                    
                    pos['pnl_pct'] = (pos['pnl'] / (pos['entry_price'] * pos['size'])) * 100
                    
                    # Update open duration
                    pos['open_duration'] = time.time() - pos['entry_time']
                    
                    # Store price history
                    if pos['symbol'] not in st.session_state.price_history:
                        st.session_state.price_history[pos['symbol']] = []
                    
                    st.session_state.price_history[pos['symbol']].append({
                        'time': datetime.now(),
                        'price': pos['current_price'],
                        'pnl': pos['pnl']
                    })
                    
                    # Keep last 200 points (for smoother charts)
                    if len(st.session_state.price_history[pos['symbol']]) > 200:
                        st.session_state.price_history[pos['symbol']].pop(0)
                    
            except Exception as e:
                st.error(f"❌ Error fetching {pos['symbol']}: {e}")
        
        # Update total PnL and capital
        total_pnl = sum(p['pnl'] for p in st.session_state.positions)
        current_capital = self.starting_capital + total_pnl
        
        st.session_state.pnl_history.append({
            'time': datetime.now(),
            'pnl': total_pnl
        })
        
        st.session_state.capital_history.append({
            'time': datetime.now(),
            'capital': current_capital
        })
        
        # Keep last 200 points
        if len(st.session_state.pnl_history) > 200:
            st.session_state.pnl_history.pop(0)
        if len(st.session_state.capital_history) > 200:
            st.session_state.capital_history.pop(0)
        
        st.session_state.last_update = time.time()
        st.session_state.update_count += 1
        st.session_state.flash_update = updated
    
    def render_header(self):
        """Render header with live status"""
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            st.markdown(
                f'<div style="font-size: 2.5rem; font-weight: bold;">'
                f'<span class="status-live"></span>'
                f'📊 Live Trading Dashboard'
                f'</div>',
                unsafe_allow_html=True
            )
        
        with col2:
            elapsed = time.time() - st.session_state.positions[0]['entry_time']
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            st.markdown(
                f'<div style="text-align: center; padding: 10px;">'
                f'<div style="color: #888; font-size: 0.9rem;">Runtime</div>'
                f'<div style="font-size: 1.5rem; font-weight: bold; color: #ffeb3b;">'
                f'{hours:02d}:{minutes:02d}:{seconds:02d}'
                f'</div></div>',
                unsafe_allow_html=True
            )
        
        with col3:
            last_update_ago = time.time() - st.session_state.last_update
            st.markdown(
                f'<div style="text-align: center; padding: 10px;">'
                f'<div style="color: #888; font-size: 0.9rem;">Last Update</div>'
                f'<div style="font-size: 1.5rem; font-weight: bold; color: #00ff88;">'
                f'{last_update_ago:.1f}s'
                f'</div></div>',
                unsafe_allow_html=True
            )
    
    def render_key_metrics(self):
        """Render key metrics with big numbers"""
        total_pnl = sum(p['pnl'] for p in st.session_state.positions)
        total_pnl_pct = (total_pnl / self.starting_capital) * 100
        current_capital = self.starting_capital + total_pnl
        
        col1, col2, col3, col4 = st.columns(4)
        
        pnl_color = "profit" if total_pnl >= 0 else "loss"
        
        with col1:
            st.markdown(
                f'<div class="metric-card">'
                f'<div style="color: #888; font-size: 0.9rem; margin-bottom: 10px;">💰 Current Capital</div>'
                f'<div class="big-number">${current_capital:,.2f}</div>'
                f'<div style="color: #888; font-size: 0.8rem; margin-top: 5px;">USDT</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        
        with col2:
            st.markdown(
                f'<div class="metric-card">'
                f'<div style="color: #888; font-size: 0.9rem; margin-bottom: 10px;">💵 Total PnL</div>'
                f'<div class="big-number {pnl_color}">${total_pnl:+,.2f}</div>'
                f'<div class="{pnl_color}" style="font-size: 1.2rem; margin-top: 5px;">{total_pnl_pct:+.2f}%</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        
        with col3:
            open_pos = len(st.session_state.positions)
            closed_trades = len(st.session_state.trades_history)
            st.markdown(
                f'<div class="metric-card">'
                f'<div style="color: #888; font-size: 0.9rem; margin-bottom: 10px;">📈 Positions</div>'
                f'<div class="big-number" style="color: #00ff88;">{open_pos}</div>'
                f'<div style="color: #888; font-size: 0.8rem; margin-top: 5px;">Open | {closed_trades} Closed</div>'
                f'</div>',
                unsafe_allow_html=True
            )
        
        with col4:
            updates = st.session_state.update_count
            st.markdown(
                f'<div class="metric-card">'
                f'<div style="color: #888; font-size: 0.9rem; margin-bottom: 10px;">🔄 Updates</div>'
                f'<div class="big-number" style="color: #ffeb3b;">{updates}</div>'
                f'<div style="color: #888; font-size: 0.8rem; margin-top: 5px;">Data Points</div>'
                f'</div>',
                unsafe_allow_html=True
            )
    
    def render_positions_detailed(self):
        """Render detailed positions with visual indicators"""
        st.subheader("📋 Open Positions")
        
        for pos in st.session_state.positions:
            side_class = "position-long" if pos['side'] == "LONG" else "position-short"
            pnl_color = "profit" if pos['pnl'] >= 0 else "loss"
            
            # Duration
            duration = pos['open_duration']
            duration_str = f"{int(duration//3600)}h {int((duration%3600)//60)}m {int(duration%60)}s"
            
            # Price change
            price_change = ((pos['current_price'] - pos['entry_price']) / pos['entry_price']) * 100
            
            col1, col2 = st.columns([3, 2])
            
            with col1:
                st.markdown(
                    f'<div class="metric-card {side_class}" style="margin: 10px 0;">'
                    f'<div style="display: flex; justify-content: space-between; align-items: center;">'
                    f'<div>'
                    f'<div style="font-size: 1.8rem; font-weight: bold;">{pos["symbol"]}</div>'
                    f'<div style="color: #888; font-size: 0.9rem;">Side: <span style="color: {"#00ff88" if pos["side"]=="LONG" else "#ff4444"}; font-weight: bold;">{pos["side"]}</span> | Leverage: {pos["leverage"]}x | Size: {pos["size"]} BTC</div>'
                    f'</div>'
                    f'<div style="text-align: right;">'
                    f'<div class="{pnl_color}" style="font-size: 2rem; font-weight: bold;">${pos["pnl"]:+,.2f}</div>'
                    f'<div class="{pnl_color}" style="font-size: 1.2rem;">{pos["pnl_pct"]:+.2f}%</div>'
                    f'</div>'
                    f'</div>'
                    f'<div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #333;">'
                    f'<div style="display: flex; justify-content: space-between;">'
                    f'<div><span style="color: #888;">Entry:</span> <span style="color: #fff; font-weight: bold;">${pos["entry_price"]:,.2f}</span></div>'
                    f'<div><span style="color: #888;">Current:</span> <span style="color: #ffeb3b; font-weight: bold;">${pos["current_price"]:,.2f}</span></div>'
                    f'<div><span style="color: #888;">Change:</span> <span class="{pnl_color}">{price_change:+.2f}%</span></div>'
                    f'<div><span style="color: #888;">Duration:</span> <span style="color: #fff;">{duration_str}</span></div>'
                    f'</div>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
            
            with col2:
                # Mini chart for this position
                if pos['symbol'] in st.session_state.price_history and st.session_state.price_history[pos['symbol']]:
                    data = st.session_state.price_history[pos['symbol']][-50:]  # Last 50 points
                    
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=[d['time'] for d in data],
                        y=[d['price'] for d in data],
                        mode='lines',
                        line=dict(color='#00ff88' if pos['pnl'] >= 0 else '#ff4444', width=2),
                        fill='tozeroy',
                        fillcolor='rgba(0,255,136,0.1)' if pos['pnl'] >= 0 else 'rgba(255,68,68,0.1)'
                    ))
                    
                    fig.add_hline(y=pos['entry_price'], line_dash="dash", line_color="yellow", line_width=1)
                    
                    fig.update_layout(
                        height=150,
                        margin=dict(l=0, r=0, t=10, b=0),
                        xaxis=dict(showgrid=False, showticklabels=False),
                        yaxis=dict(showgrid=True, gridcolor='#333'),
                        plot_bgcolor='rgba(0,0,0,0)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        showlegend=False
                    )
                    
                    st.plotly_chart(fig, use_container_width=True, key=f"mini_{pos['symbol']}")
    
    def render_main_charts(self):
        """Render main charts with flash effect"""
        # Create subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=('📈 BTC Price (Live)', '💰 Capital Over Time', '📊 PnL History', '🔥 Price Heatmap'),
            specs=[[{"secondary_y": False}, {"secondary_y": False}],
                   [{"secondary_y": False}, {"type": "indicator"}]],
            vertical_spacing=0.15,
            horizontal_spacing=0.1
        )
        
        # Chart 1: BTC Price with volume-like bars
        if 'BTCUSDT' in st.session_state.price_history and st.session_state.price_history['BTCUSDT']:
            data = st.session_state.price_history['BTCUSDT']
            
            fig.add_trace(
                go.Scatter(
                    x=[d['time'] for d in data],
                    y=[d['price'] for d in data],
                    mode='lines',
                    name='Price',
                    line=dict(color='#00ff88', width=3),
                    fill='tozeroy',
                    fillcolor='rgba(0,255,136,0.1)'
                ),
                row=1, col=1
            )
            
            # Entry line
            entry = st.session_state.positions[0]['entry_price']
            fig.add_hline(y=entry, line_dash="dash", line_color="yellow", row=1, col=1)
        
        # Chart 2: Capital
        if st.session_state.capital_history:
            data = st.session_state.capital_history
            colors = ['#00ff88' if d['capital'] >= self.starting_capital else '#ff4444' for d in data]
            
            fig.add_trace(
                go.Scatter(
                    x=[d['time'] for d in data],
                    y=[d['capital'] for d in data],
                    mode='lines',
                    name='Capital',
                    line=dict(color='#ffeb3b', width=3),
                    fill='tozeroy',
                    fillcolor='rgba(255,235,59,0.1)'
                ),
                row=1, col=2
            )
            
            fig.add_hline(y=self.starting_capital, line_dash="dash", line_color="white", row=1, col=2)
        
        # Chart 3: PnL
        if st.session_state.pnl_history:
            data = st.session_state.pnl_history
            colors = ['#00ff88' if d['pnl'] >= 0 else '#ff4444' for d in data]
            
            fig.add_trace(
                go.Bar(
                    x=[d['time'] for d in data],
                    y=[d['pnl'] for d in data],
                    name='PnL',
                    marker_color=colors
                ),
                row=2, col=1
            )
            
            fig.add_hline(y=0, line_dash="dash", line_color="white", row=2, col=1)
        
        # Chart 4: Current PnL Gauge
        total_pnl = sum(p['pnl'] for p in st.session_state.positions)
        total_pnl_pct = (total_pnl / self.starting_capital) * 100
        
        fig.add_trace(
            go.Indicator(
                mode="gauge+number+delta",
                value=total_pnl,
                delta={'reference': 0, 'increasing': {'color': "#00ff88"}, 'decreasing': {'color': "#ff4444"}},
                gauge={
                    'axis': {'range': [-500, 500]},
                    'bar': {'color': "#00ff88" if total_pnl >= 0 else "#ff4444"},
                    'steps': [
                        {'range': [-500, 0], 'color': "rgba(255,68,68,0.2)"},
                        {'range': [0, 500], 'color': "rgba(0,255,136,0.2)"}
                    ],
                    'threshold': {
                        'line': {'color': "yellow", 'width': 4},
                        'thickness': 0.75,
                        'value': 0
                    }
                },
                number={'prefix': "$", 'suffix': f" ({total_pnl_pct:+.1f}%)"},
                title={'text': "Current PnL"}
            ),
            row=2, col=2
        )
        
        # Update layout
        fig.update_layout(
            height=800,
            showlegend=False,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(color='white'),
            margin=dict(l=50, r=50, t=80, b=50)
        )
        
        # Flash effect container
        flash_class = "flash-update" if st.session_state.flash_update else ""
        st.markdown(f'<div class="{flash_class}">', unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Reset flash
        st.session_state.flash_update = False
    
    def render_sidebar(self):
        """Render sidebar with controls and info"""
        st.sidebar.header("⚙️ Dashboard Settings")
        
        st.sidebar.markdown("---")
        
        st.sidebar.subheader("📊 Strategy Info")
        st.sidebar.info(
            f"**Strategy:** Main Portfolio\n\n"
            f"**Capital:** ${self.capital:,.2f} USDT\n\n"
            f"**Exchange:** Binance Futures (Demo)\n\n"
            f"**Update Rate:** <1 second\n\n"
            f"**Status:** 🟢 LIVE"
        )
        
        st.sidebar.markdown("---")
        
        st.sidebar.subheader("🎯 Performance")
        total_pnl = sum(p['pnl'] for p in st.session_state.positions)
        total_pnl_pct = (total_pnl / self.starting_capital) * 100
        
        st.sidebar.metric("Total PnL", f"${total_pnl:+,.2f}", f"{total_pnl_pct:+.2f}%")
        st.sidebar.metric("Updates", st.session_state.update_count)
        
        st.sidebar.markdown("---")
        
        if st.sidebar.button("🔄 Force Refresh"):
            st.rerun()
    
    def run(self):
        """Main dashboard loop"""
        # Fetch latest data
        self.fetch_live_prices()
        
        # Render components
        self.render_header()
        st.divider()
        
        self.render_key_metrics()
        st.divider()
        
        self.render_positions_detailed()
        st.divider()
        
        self.render_main_charts()
        
        # Sidebar
        self.render_sidebar()
        
        # Auto-refresh every 1 second
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    dashboard = AdvancedTradingDashboard()
    dashboard.run()
