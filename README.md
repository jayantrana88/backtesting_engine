# Algorithmic Backtest Engine

A highly modular, event-driven backtesting framework for Python. Built for modern quantitative traders, this engine prioritizes an intuitive **decorator-based API**, realistic execution simulation, and **institutional-grade reporting** through TradingView-style interactive HTML dashboards.

---

## ✨ Key Features

- **Decorator-Based Strategy API**: Write clean, declarative strategies without wrestling with rigid class inheritance. Just tag your methods with `@Indicator`, `@BuyCondition`, or `@TrailingStop`.
- **Event-Driven Realism**: Simulates execution bar-by-bar to realistically handle slippage, brokerage fees, and intra-bar conflict resolution (e.g., when Stop-Loss and Take-Profit are hit on the same candle).
- **Interactive HTML Reports**: Generates a self-contained, TradingView-style interactive HTML chart (using Plotly) that you can pan and zoom. No more static Matplotlib images.
- **Institutional Metrics**: Automatically calculates 30+ performance metrics including Calmar Ratio, Omega Ratio, Sortino Ratio, and Statistical Significance (t-Stats & p-Values).
- **Fractional Shares & Crypto Support**: Toggle `allow_fractional_shares` in the config to seamlessly switch between traditional equities and cryptocurrency markets.
- **Robust Data Handling**: Out-of-the-box support for local CSV files (with auto-header detection) and the Zerodha Kite API.

---

## 🚀 Quick Start

### 1. Installation

Clone the repository and install the requirements:

```bash
git clone https://github.com/yourusername/jay_backtest_engine.git
cd jay_backtest_engine
python -m venv venv
# On Windows: venv\Scripts\activate
# On Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the Sample Backtest

The engine comes with a synthetic `sample_data.csv` out of the box. Simply run:

```bash
python main.py
```

Check your terminal for the detailed performance report, and open the generated `results.html` in your web browser to view the interactive chart and metrics dashboard.

---

## 🧠 Writing a Strategy

Strategies are built by inheriting from the base `Strategy` class and using decorators from `core.decorators`. 

Here is an example of a complete 20/50 Simple Moving Average Crossover strategy:

```python
from core.strategy import Strategy
from core.decorators import Indicator, BuyCondition, SellCondition, StopLoss, PositionSize

class SMACrossover(Strategy):
    
    @Indicator
    def sma_fast(self):
        return self.data['close'].rolling(20).mean()

    @Indicator
    def sma_slow(self):
        return self.data['close'].rolling(50).mean()

    @BuyCondition
    def enter_long(self):
        fast = self.indicators['sma_fast']
        slow = self.indicators['sma_slow']
        # Buy when fast crosses above slow
        return (fast.iloc[-1] > slow.iloc[-1]) and (fast.iloc[-2] <= slow.iloc[-2])

    @SellCondition
    def exit_long(self):
        fast = self.indicators['sma_fast']
        slow = self.indicators['sma_slow']
        # Sell when fast crosses below slow
        return (fast.iloc[-1] < slow.iloc[-1]) and (fast.iloc[-2] >= slow.iloc[-2])

    @StopLoss
    def risk_management(self):
        # Place a 2% stop loss on the entry price
        return self.current_price * 0.98

    @PositionSize
    def size_trade(self):
        # Risk exactly $5,000 per trade
        return 5000 / self.current_price
```

---

## ⚙️ Configuration (`config.json`)

Control the entire simulation environment without touching your code. 

```json
{
    "data": {
        "source": "csv",
        "csv_file_path": "data\\sample_data.csv",
        "timeframe": "2h"
    },
    "portfolio": {
        "initial_cash": 100000,
        "max_active_positions": 1
    },
    "risk_management": {
        "position_sizing_pct_of_equity": 25,
        "overall_stoploss_amount": 5000
    },
    "simulation": {
        "brokerage_fee_pct": 0.01,
        "slippage_pct": 0.01,
        "allow_fractional_shares": true
    }
}
```

---

## 🏗️ Architecture Overview

The system is separated into three distinct modules to ensure modularity and scalability:

```plaintext
+-----------+      +----------------+      +-----------------+
|           |      |                |      |                 |
| main.py   +------> data_loader.py +------>  backtest.py    |
| (User     |      | (Fetches &     |      |  (Core Engine)  |
|  Entry)   |      |  Prepares Data)|      |                 |
|           |      |                |      |                 |
+-----+-----+      +-------+--------+      +--------+--------+
      |                    ^                        |
      |                    |                        |
+-----v-----+      +-------+--------+      +--------v--------+
|           |      |                |      |                 |
| config.json      |  zerodha_data  |      |   strategy.py   |
|           |      |  csv_data      |      |   (User Logic)  |
|           |      |                |      |   decorator.py  |
+-----------+      +----------------+      +-----------------+
                                                  |
                                          +-------v-------+
                                          |               |
                                          |    plot.py    |
                                          | (Interactive  |
                                          |   HTML View)  |
                                          +---------------+
```

## 📜 License
This project is open-source and available under the MIT License.
