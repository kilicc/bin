#!/usr/bin/env python3
"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 WEB DASHBOARD - LIVE TRADING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

5000 USDT Capital | Real-time Binance Futures Prices | <1s Updates

RUN:
    streamlit run web_dashboard.py
    
ACCESS:
    http://localhost:8501
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

# Page config
st.set_page_config(
    page_title="Live Trading Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .big-metric {
        font-size: 2.5rem !important;
        font-weight: bold;
    }
    .profit {
        color: #00ff00;
    }
    .loss {
        color: #ff0000;
    }
    .stMetric {
        background-color: #1e1e1e;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #333;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_binance_client():
    """Initialize Binance client"""
    return BinanceFuturesClient()


class TradingDashboard:
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
                    'entry_time': time.time()
                }
            ]
        
        if 'price_history' not in st.session_state:
            st.session_state.price_history = {'BTCUSDT': []}
        
        if 'pnl_history' not in st.session_state:
            st.session_state.pnl_history = []
        
        if 'last_update' not in st.session_state:
            st.session_state.last_update = time.time()
    
    def fetch_live_prices(self):
        """Fetch live prices from Binance"""
        for pos in st.session_state.positions:
            try:
                # Get real-time price from Binance
                ticker = self.client.klines_history(
                    pos['symbol'], 
                    '1m', 
                    limit=1
                )
                
                if ticker and len(ticker) > 0:
                    # Get close price from latest candle
                    pos['current_price'] = float(ticker[-1][4])  # Close price
                    
                    # Calculate PnL
                    if pos['side'] == 'LONG':
                        pos['pnl'] = (pos['current_price'] - pos['entry_price']) * pos['size']
                    else:  # SHORT
                        pos['pnl'] = (pos['entry_price'] - pos['current_price']) * pos['size']
                    
                    pos['pnl_pct'] = (pos['pnl'] / (pos['entry_price'] * pos['size'])) * 100
                    
                    # Store price history
                    if pos['symbol'] not in st.session_state.price_history:
                        st.session_state.price_history[pos['symbol']] = []
                    
                    st.session_state.price_history[pos['symbol']].append({
                        'time': datetime.now(),
                        'price': pos['current_price']
                    })
                    
                    # Keep last 100 points
                    if len(st.session_state.price_history[pos['symbol']]) > 100:
                        st.session_state.price_history[pos['symbol']].pop(0)
                    
            except Exception as e:
                st.error(f"Error fetching price for {pos['symbol']}: {e}")
        
        # Update total PnL
        total_pnl = sum(p['pnl'] for p in st.session_state.positions)
        st.session_state.pnl_history.append({
            'time': datetime.now(),
            'pnl': total_pnl
        })
        
        # Keep last 100 points
        if len(st.session_state.pnl_history) > 100:
            st.session_state.pnl_history.pop(0)
        
        st.session_state.last_update = time.time()
    
    def render_header(self):
        """Render dashboard header"""
        st.title("📊 Live Trading Dashboard")
        
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            st.markdown(f"### 💰 Capital: ${self.capital:,.2f} USDT")
        
        with col2:
            elapsed = time.time() - st.session_state.positions[0]['entry_time']
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            st.metric("⏱️ Runtime", f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        
        with col3:
            last_update_ago = time.time() - st.session_state.last_update
            st.metric("🔄 Last Update", f"{last_update_ago:.1f}s ago")
    
    def render_metrics(self):
        """Render key metrics"""
        total_pnl = sum(p['pnl'] for p in st.session_state.positions)
        total_pnl_pct = (total_pnl / self.starting_capital) * 100
        current_capital = self.starting_capital + total_pnl
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "💵 Total PnL",
                f"${total_pnl:+,.2f}",
                f"{total_pnl_pct:+.2f}%",
                delta_color="normal"
            )
        
        with col2:
            st.metric(
                "💰 Current Capital",
                f"${current_capital:,.2f}",
                f"${total_pnl:+,.2f}"
            )
        
        with col3:
            st.metric(
                "📈 Open Positions",
                len(st.session_state.positions),
                delta_color="off"
            )
        
        with col4:
            avg_pnl_pct = sum(p['pnl_pct'] for p in st.session_state.positions) / len(st.session_state.positions)
            st.metric(
                "📊 Avg Position PnL",
                f"{avg_pnl_pct:+.2f}%",
                delta_color="normal"
            )
    
    def render_positions_table(self):
        """Render positions table"""
        st.subheader("📋 Open Positions")
        
        if st.session_state.positions:
            # Create DataFrame
            df = pd.DataFrame([
                {
                    'Symbol': p['symbol'],
                    'Side': p['side'],
                    'Entry': f"${p['entry_price']:,.2f}",
                    'Current': f"${p['current_price']:,.2f}",
                    'Size': f"{p['size']:.4f}",
                    'Leverage': f"{p['leverage']}x",
                    'PnL': f"${p['pnl']:+,.2f}",
                    'PnL %': f"{p['pnl_pct']:+.2f}%"
                }
                for p in st.session_state.positions
            ])
            
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No open positions")
    
    def render_price_chart(self, symbol: str):
        """Render price chart"""
        if symbol in st.session_state.price_history and st.session_state.price_history[symbol]:
            data = st.session_state.price_history[symbol]
            
            fig = go.Figure()
            
            # Price line
            fig.add_trace(go.Scatter(
                x=[d['time'] for d in data],
                y=[d['price'] for d in data],
                mode='lines',
                name='Price',
                line=dict(color='#00ff00', width=2)
            ))
            
            # Entry price line (for BTCUSDT)
            position = next((p for p in st.session_state.positions if p['symbol'] == symbol), None)
            if position:
                fig.add_hline(
                    y=position['entry_price'],
                    line_dash="dash",
                    line_color="yellow",
                    annotation_text=f"Entry: ${position['entry_price']:,.2f}"
                )
            
            fig.update_layout(
                title=f"{symbol} Live Price",
                xaxis_title="Time",
                yaxis_title="Price (USDT)",
                template="plotly_dark",
                height=400,
                showlegend=True
            )
            
            st.plotly_chart(fig, use_container_width=True)
    
    def render_pnl_chart(self):
        """Render PnL chart"""
        if st.session_state.pnl_history:
            data = st.session_state.pnl_history
            
            fig = go.Figure()
            
            # PnL line
            fig.add_trace(go.Scatter(
                x=[d['time'] for d in data],
                y=[d['pnl'] for d in data],
                mode='lines',
                name='PnL',
                line=dict(color='#00ff00' if data[-1]['pnl'] >= 0 else '#ff0000', width=3),
                fill='tozeroy'
            ))
            
            # Zero line
            fig.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.5)
            
            fig.update_layout(
                title="Total PnL Over Time",
                xaxis_title="Time",
                yaxis_title="PnL (USDT)",
                template="plotly_dark",
                height=400
            )
            
            st.plotly_chart(fig, use_container_width=True)
    
    def run(self):
        """Main dashboard"""
        # Fetch latest prices
        self.fetch_live_prices()
        
        # Render components
        self.render_header()
        
        st.divider()
        
        self.render_metrics()
        
        st.divider()
        
        # Two columns: Positions table + Charts
        col1, col2 = st.columns([1, 1])
        
        with col1:
            self.render_positions_table()
        
        with col2:
            # Price chart for BTCUSDT
            self.render_price_chart('BTCUSDT')
        
        # PnL chart (full width)
        self.render_pnl_chart()
        
        # Auto-refresh info
        st.sidebar.header("⚙️ Settings")
        st.sidebar.info(
            "🔄 **Auto-refresh:** Every 1 second\n\n"
            "📡 **Data source:** Binance Futures API\n\n"
            "💰 **Capital:** $5,000 USDT"
        )
        
        # Auto-refresh every 1 second
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    dashboard = TradingDashboard()
    dashboard.run()
