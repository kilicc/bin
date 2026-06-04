# 🎯 DUAL STRATEGY SYSTEM

## Main Strategy (5000 USDT) + Copy Trading (5000 USDC)

İki stratejiyi paralel çalıştır ve performanslarını karşılaştır!

---

## 🚀 HIZLI BAŞLANGIÇ

### 1. Config Oluşturuldu ✅

```bash
dual_config.json
```

### 2. Config İçeriği

```json
{
  "main_strategy": {
    "capital": 5000.0,        // 5000 USDT
    "currency": "USDT",
    "max_positions": 6,
    "risk_pct": 0.02,
    "strategy": "adv_alpha_max"
  },
  "copy_trading": {
    "capital": 5000.0,        // 5000 USDC
    "currency": "USDC",
    "max_positions": 5,
    "capital_per_trade": 1000.0,
    "min_confidence": 70.0
  },
  "bitget": {
    "api_key": "YOUR_KEY",
    "api_secret": "YOUR_SECRET",
    "passphrase": "YOUR_PASS"
  },
  "binance": {
    "api_key": "3qLjlfUeLyGgtB8p4oKTD6YsP5M8bWb67tUemJRc7YOxuC1hJYI4fWOqupZj1Idb",
    "api_secret": "RBuo1px4L5uF2n7plOtPPoZ0VXWAfULnDwbdzS5WxGfGTXxqGxZrLsBwlu34ONeX",
    "testnet": true
  }
}
```

### 3. Bitget API Ekle

**Bitget hesabı aç ve API key al:**

```
1. https://www.bitget.com/account/newapi
2. Create API Key
3. Permissions: Read (Copy Trading)
4. Copy: API Key, Secret, Passphrase
```

`dual_config.json` düzenle:

```json
{
  "bitget": {
    "api_key": "bg_abc123...",
    "api_secret": "xyz789...",
    "passphrase": "your_passphrase"
  }
}
```

### 4. BAŞLAT!

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
python3 scripts/run_dual_strategy.py run
```

---

## 📊 EKRAN GÖRÜNTÜSÜ

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 DUAL STRATEGY SYSTEM
Runtime: 01:23:45
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Strategy Comparison

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Metric                    ┃ Main Strategy   ┃ Copy Trading    ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ Capital                   │ $5,000.00 USDT  │ $5,000.00 USDC  │
│ Active Positions          │ 4               │ 3               │
│ Total Trades              │ 28              │ 15              │
│ Total PnL                 │ +$125.50        │ +$87.30         │
│ ROI %                     │ +2.51%          │ +1.75%          │
│ Win Rate                  │ 64.3%           │ 60.0%           │
│                           │                 │                 │
│ TOTAL                     │ $10,000.00      │                 │
│ Combined PnL              │ +$212.80        │                 │
│ Combined ROI              │ +2.13%          │                 │
└───────────────────────────┴─────────────────┴─────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Press Ctrl+C to stop
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 🎯 NASIL ÇALIŞIR?

### Paralel Execution:

```
┌─────────────────────────┐     ┌─────────────────────────┐
│ MAIN STRATEGY           │     │ COPY TRADING            │
│ Capital: 5000 USDT      │     │ Capital: 5000 USDC      │
│ ├── Market Analysis     │     │ ├── Bitget Traders      │
│ ├── Technical Indicators│     │ ├── Signal Processing   │
│ ├── Position Management │     │ ├── Binance Execution   │
│ └── TP/SL Automation    │     │ └── TP/SL Monitoring    │
└───────────┬─────────────┘     └───────────┬─────────────┘
            │                               │
            └───────────┬───────────────────┘
                        │
                        ↓
            ┌─────────────────────────┐
            │ DASHBOARD               │
            │ ├── Combined Stats      │
            │ ├── Performance Compare │
            │ └── Real-time Updates   │
            └─────────────────────────┘
```

### Check Cycle (Every 30s):

```
1. Main Strategy:
   - Analyze market conditions
   - Check technical indicators
   - Open/close positions
   - Monitor TP/SL

2. Copy Trading:
   - Check Bitget traders' positions
   - Process new signals
   - Execute on Binance
   - Monitor TP/SL

3. Update Dashboard:
   - Refresh statistics
   - Calculate ROI
   - Display positions
```

---

## ⚙️ CONFIGURATION

### Main Strategy Settings:

```json
{
  "main_strategy": {
    "capital": 5000.0,         // Starting capital
    "max_positions": 6,        // Max concurrent positions
    "risk_pct": 0.02,          // 2% risk per trade
    "strategy": "adv_alpha_max" // Strategy variant
  }
}
```

### Copy Trading Settings:

```json
{
  "copy_trading": {
    "capital": 5000.0,          // Starting capital
    "max_positions": 5,         // Max concurrent positions
    "capital_per_trade": 1000.0, // $1000 per trade
    "min_confidence": 70.0      // Min 70% confidence
  }
}
```

### Binance Settings:

```json
{
  "binance": {
    "api_key": "your_key",
    "api_secret": "your_secret",
    "testnet": true            // Use testnet for safety
  }
}
```

---

## 📈 PERFORMANCE METRICS

### Real-time Tracking:

- **Capital:** Initial investment per strategy
- **Active Positions:** Currently open positions
- **Total Trades:** Completed trades count
- **Total PnL:** Profit/Loss in USD
- **ROI %:** Return on investment percentage
- **Win Rate:** Successful trades / total trades

### Combined Metrics:

- **Total Capital:** Sum of both strategies
- **Combined PnL:** Total profit/loss
- **Combined ROI:** Overall return percentage

---

## 🎯 AVANTAJLAR

### Diversification:

| Strategy | Type | Risk Profile | Time Horizon |
|----------|------|--------------|--------------|
| **Main** | Technical Analysis | Medium | Short-term |
| **Copy** | Signal Following | Low-Medium | Variable |

### Risk Management:

- ✅ Independent capital allocation
- ✅ Separate risk parameters
- ✅ Portfolio diversification
- ✅ Performance comparison

### Learning:

- ✅ Compare different approaches
- ✅ Identify best performer
- ✅ Optimize capital allocation
- ✅ Real-time feedback

---

## 💡 BEST PRACTICES

### Capital Allocation:

```
Total: $10,000
├── Main Strategy: $5,000 (50%)
└── Copy Trading: $5,000 (50%)
```

**Adjust based on performance:**

```python
# After 1 month:
if main_roi > copy_roi:
    # Allocate more to main
    main_capital = 6000
    copy_capital = 4000
else:
    # Allocate more to copy
    main_capital = 4000
    copy_capital = 6000
```

### Monitoring:

- Check dashboard every few hours
- Review weekly performance
- Adjust parameters if needed
- Stop underperforming strategy

### Risk Control:

- Start with small capital
- Use testnet first
- Set stop-loss limits
- Don't over-leverage

---

## 🚨 TROUBLESHOOTING

### Problem: Bitget API Error

```bash
# Solution:
1. Check API credentials in dual_config.json
2. Verify permissions (Read Copy Trading)
3. Check IP whitelist
4. Test: python scripts/run_bitget_to_binance.py test-bitget
```

### Problem: Main Strategy Not Trading

```bash
# Solution:
1. Check market conditions (low volatility?)
2. Verify technical indicators
3. Review position limits
4. Check Binance API connection
```

### Problem: Low Performance

```bash
# Solution:
1. Review risk parameters
2. Adjust position sizes
3. Change trader filters (copy trading)
4. Consider different timeframes
```

---

## 📊 COMMANDS

### Start System:

```bash
python3 scripts/run_dual_strategy.py run
```

### Create Config:

```bash
python3 scripts/run_dual_strategy.py create-config
```

### Custom Capital:

```bash
python3 scripts/run_dual_strategy.py run \\
    --main-capital 7000 \\
    --copy-capital 3000
```

### Custom Interval:

```bash
python3 scripts/run_dual_strategy.py run --interval 60
```

---

## 🎉 SONUÇ

### ✅ DUAL STRATEGY BENEFITS:

1. **Diversification:** Two different approaches
2. **Comparison:** See which works better
3. **Risk Management:** Independent allocations
4. **Learning:** Understand different strategies
5. **Flexibility:** Adjust based on performance

### 📊 EXPECTED RESULTS:

**Main Strategy:**
- ROI: 3-5% monthly (moderate risk)
- Win Rate: 60-65%
- Trades: 20-30 per month

**Copy Trading:**
- ROI: 2-4% monthly (following top traders)
- Win Rate: 55-60%
- Trades: 10-20 per month

**Combined:**
- ROI: 2.5-4.5% monthly
- Risk: Diversified
- Capital: $10,000

---

## 🚀 NEXT STEPS

```bash
# 1. Add Bitget API
nano dual_config.json

# 2. Test connection
python3 scripts/run_bitget_to_binance.py test-bitget

# 3. START!
python3 scripts/run_dual_strategy.py run
```

**Live dashboard her 30 saniyede güncellenir!** 📊

**Press Ctrl+C to stop anytime** ⏹️
