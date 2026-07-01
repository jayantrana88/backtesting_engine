import pandas as pd
from .decorators import (
    Indicator, BuyCondition, SellCondition, ShortCondition, CoverCondition,
    StopLoss, TakeProfit, TrailingStop, MarketFilter, PositionSize,
    WarmupPeriod, TradingSession, OnCandleOpen, OnCandleClose,
    OnEntry, OnExit, OnStopLossHit, OnTakeProfitHit
)

class Strategy:
    """
    The base class for all trading strategies.

    Users should inherit from this class and define their strategy's logic
    by implementing methods and decorating them with the appropriate decorators
    from `core.decorators`.

    The backtesting engine will automatically discover and execute these
    decorated methods.
    """
    def __init__(self, data: pd.DataFrame, config: dict):
        """
        Initializes the Strategy instance.

        This method is called by the backtesting engine. It sets up the
        initial state, including data and configuration, and prepares the
        indicators.

        Args:
            data (pd.DataFrame): The historical market data for the backtest.
            config (dict): The configuration dictionary for the backtest.
        """
        self.data = data
        self.config = config
        self.index = 0
        self._init_indicators()

    def _init_indicators(self):
        """
        Initializes and calculates all decorated indicators.

        This method iterates through all methods decorated with @Indicator,
        executes them, and attaches their results (the indicator Series)
        as attributes to the strategy instance.
        
        For example, a method `def rsi(self)` decorated with `@Indicator`
        will result in `self.rsi` being available throughout the strategy.
        """
        print("Initializing indicators...")
        for indicator_decorator in Indicator.indicators:
            indicator_name = indicator_decorator.func_name
            print(f"  - Calculating '{indicator_name}'...")
            
            # Call the decorated method (e.g., rsi()) on this instance
            indicator_series = indicator_decorator(self)
            
            # Attach the resulting Series to self, e.g., self.rsi = pd.Series(...)
            setattr(self, indicator_name, indicator_series)
            
            # Also, merge it into the main dataframe for easy access and plotting
            if isinstance(indicator_series, pd.Series):
                self.data[indicator_name] = indicator_series

    def _set_current_bar_index(self, index: int):
        """
        Sets the current bar index for evaluation.
        Called by the backtesting engine on each iteration of the event loop.
        """
        self.index = index

    # --- Properties for easy access to current bar data ---

    @property
    def open(self) -> float:
        return self.data['open'].iloc[self.index]

    @property
    def high(self) -> float:
        return self.data['high'].iloc[self.index]

    @property
    def low(self) -> float:
        return self.data['low'].iloc[self.index]

    @property
    def close(self) -> float:
        return self.data['close'].iloc[self.index]

    @property
    def volume(self) -> float:
        return self.data['volume'].iloc[self.index]

    @property
    def timestamp(self):
        return self.data['timestamp'].iloc[self.index]

    @classmethod
    def purge_decorators(cls):
        """
        Clears all decorator lists.
        
        This is crucial for running multiple backtests in the same session
        to prevent strategies from interfering with each other.
        """
        Indicator.indicators.clear()
        BuyCondition.buy_conditions.clear()
        SellCondition.sell_conditions.clear()
        ShortCondition.short_conditions.clear()
        CoverCondition.cover_conditions.clear()
        StopLoss.stop_losses.clear()
        TakeProfit.take_profits.clear()
        TrailingStop.trailing_stops.clear()
        MarketFilter.market_filters.clear()
        PositionSize.position_sizes.clear()
        WarmupPeriod.warmup_periods.clear()
        TradingSession.trading_sessions.clear()
        OnCandleOpen.on_candle_opens.clear()
        OnCandleClose.on_candle_closes.clear()
        OnEntry.on_entries.clear()
        OnExit.on_exits.clear()
        OnStopLossHit.on_stop_loss_hits.clear()
        OnTakeProfitHit.on_take_profit_hits.clear()
        print("All decorator lists have been purged.")