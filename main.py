"""
main.py — User Entry Point for the Backtesting Engine

This is the primary script the user runs. It orchestrates the full pipeline:
    1. Loads market data (CSV or Zerodha) via the DataLoader.
    2. Defines a trading strategy using the decorator-based API.
    3. Runs the backtest simulation.
    4. Generates an interactive HTML chart with trade markers and indicators.

Usage:
    1. Edit config.json to set your data source, symbol, timeframe, and risk params.
    2. Define your strategy below (or replace the example with your own).
    3. Run:  python main.py

The example strategy below is a simple SMA crossover to demonstrate
how the decorator system works. Replace it with your own logic.
"""

import json
import sys

from data.data_loader import DataLoader
from core.strategy import Strategy
from core.decorators import (
    Indicator, BuyCondition, SellCondition,
    StopLoss, WarmupPeriod, OnEntry, OnExit
)
from core.backtest import run_backtest
from core.plot import plot_results


# ═══════════════════════════════════════════════════════════════════════════
# STRATEGY DEFINITION
# ═══════════════════════════════════════════════════════════════════════════
# Define your strategy by subclassing Strategy and using decorators.
# Each decorated method is automatically discovered by the backtesting engine.
#
# Available decorators:
#   @Indicator          — computes a pd.Series (e.g., SMA, RSI)
#   @BuyCondition       — returns True when a long entry signal fires
#   @SellCondition      — returns True when a long exit signal fires
#   @ShortCondition     — returns True when a short entry signal fires
#   @CoverCondition     — returns True when a short cover signal fires
#   @StopLoss           — returns the current stop-loss price level
#   @TakeProfit         — returns the current take-profit price level
#   @TrailingStop       — returns the trailing stop-loss level
#   @MarketFilter       — returns True if the market is tradeable
#   @PositionSize       — returns the number of shares to trade
#   @WarmupPeriod       — returns the number of bars to skip before trading
#   @TradingSession     — returns True if within trading hours
#   @OnCandleOpen       — hook called at each candle open
#   @OnCandleClose      — hook called at each candle close
#   @OnEntry            — hook called when a position is opened
#   @OnExit             — hook called when a position is closed
#   @OnStopLossHit      — hook called when a stop-loss is triggered
#   @OnTakeProfitHit    — hook called when a take-profit is triggered
# ═══════════════════════════════════════════════════════════════════════════


class SMACrossover(Strategy):
    """
    Example Strategy: Simple Moving Average Crossover

    Buys when the fast SMA crosses above the slow SMA.
    Sells when the fast SMA crosses below the slow SMA.

    This is the "hello world" of quantitative strategies — simple,
    demonstrative, and easy to understand. Replace this with your own
    strategy logic.
    """

    # --- Indicators ---

    @Indicator
    def sma_fast(self):
        """Fast SMA (20-period)."""
        return self.data['close'].rolling(window=20).mean()

    @Indicator
    def sma_slow(self):
        """Slow SMA (50-period)."""
        return self.data['close'].rolling(window=50).mean()

    # --- Warmup Period ---

    @WarmupPeriod
    def warmup(self):
        """Skip the first 50 bars so that both SMAs are fully formed."""
        return 50

    # --- Entry Conditions ---

    @BuyCondition
    def sma_crossover_buy(self):
        """Buy when fast SMA crosses above slow SMA."""
        if self.index < 1:
            return False
        fast_now = self.sma_fast.iloc[self.index]
        fast_prev = self.sma_fast.iloc[self.index - 1]
        slow_now = self.sma_slow.iloc[self.index]
        slow_prev = self.sma_slow.iloc[self.index - 1]
        # Crossover: fast was below slow, now fast is above slow
        res = fast_prev <= slow_prev and fast_now > slow_now
        if res:
            print(f"BUY SIGNAL at index {self.index}")
        return res

    # --- Exit Conditions ---

    @SellCondition
    def sma_crossover_sell(self):
        """Sell when fast SMA crosses below slow SMA."""
        if self.index < 1:
            return False
        fast_now = self.sma_fast.iloc[self.index]
        fast_prev = self.sma_fast.iloc[self.index - 1]
        slow_now = self.sma_slow.iloc[self.index]
        slow_prev = self.sma_slow.iloc[self.index - 1]
        # Crossunder: fast was above slow, now fast is below slow
        return fast_prev >= slow_prev and fast_now < slow_now

    # --- Risk Management ---

    @StopLoss
    def fixed_stop_loss(self):
        """Set stop-loss 2% below the current close price."""
        return self.close * 0.98

    # --- Event Hooks (optional, for logging/debugging) ---

    @OnEntry
    def log_entry(self):
        """Print a message when a position is opened."""
        print(f"    >> ENTRY at bar {self.index} | "
              f"Close: {self.close:.2f} | Time: {self.timestamp}")

    @OnExit
    def log_exit(self):
        """Print a message when a position is closed."""
        print(f"    << EXIT  at bar {self.index} | "
              f"Close: {self.close:.2f} | Time: {self.timestamp}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """
    Orchestrates the full backtesting pipeline:
        1. Load config and data
        2. Run backtest with the defined strategy
        3. Generate interactive chart
    """

    # ── Step 1: Load Data ────────────────────────────────────────────
    print("=" * 60)
    print("STEP 1: Loading Data")
    print("=" * 60)

    loader = DataLoader(config_path="config.json")
    data = loader.get_data()

    if data is None or data.empty:
        print("\nERROR: No data loaded. Check your config.json settings:")
        print("  - For CSV: ensure 'csv_file_path' points to a valid file.")
        print("  - For Zerodha: ensure credentials.env is configured.")
        sys.exit(1)

    print(f"\nData loaded successfully:")
    print(f"  Rows:      {len(data)}")
    print(f"  Columns:   {list(data.columns)}")
    print(f"  Date range: {data['timestamp'].iloc[0]} → {data['timestamp'].iloc[-1]}")

    # ── Step 2: Run Backtest ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("STEP 2: Running Backtest")
    print("=" * 60)

    config = loader.config  # full config dict from config.json

    report = run_backtest(
        strategy_class=SMACrossover,
        data=data,
        config=config,
    )

    # ── Step 3: Generate Interactive Chart ───────────────────────────
    print("\n" + "=" * 60)
    print("STEP 3: Generating Interactive Chart")
    print("=" * 60)

    output_file = "results.html"
    plot_results(report, output_path=output_file)

    print(f"\n{'=' * 60}")
    print(f"  DONE! Open '{output_file}' in your browser to review results.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
