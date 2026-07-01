from pandas import Series

class Indicator:

    # Class variable to store all decorated methods (indicators)
    indicators = []
    
    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        # Add this function to our list of indicators
        Indicator.indicators.append(self)

    def __call__(self, instance, *args, **kwargs) -> Series:
        # instance will be 'self' from the class method
        return self.func(instance, *args, **kwargs)

class BuyCondition:

    # Class variable to store all decorated methods (buy conditions)
    buy_conditions = []
    
    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        BuyCondition.buy_conditions.append(self)

    def __call__(self, instance, *args, **kwargs) -> bool:
        return self.func(instance, *args, **kwargs)

class SellCondition:

    # Class variable to store all decorated methods (sell conditions)
    sell_conditions = []
    
    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        SellCondition.sell_conditions.append(self)

    def __call__(self, instance, *args, **kwargs) -> bool:
        return self.func(instance, *args, **kwargs)
    
class StopLoss:

    # Class variable to store all decorated methods (stop loss)
    stop_losses = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        StopLoss.stop_losses.append(self)

    def __call__(self, instance, *args, **kwargs) -> float:
        return self.func(instance, *args, **kwargs)
    
    def purge(self):
        StopLoss.stop_losses = []
         
class TakeProfit:

    # Class variable to store all decorated methods (take profit)
    take_profits = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        TakeProfit.take_profits.append(self)

    def __call__(self, instance, *args, **kwargs) -> float:
        return self.func(instance, *args, **kwargs)
    
    def purge(self):
        TakeProfit.take_profits = []

# For custom functions that need to be called on candle open
class OnCandleOpen:

    # Class variable to store all decorated methods (on candle open)
    on_candle_opens = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        OnCandleOpen.on_candle_opens.append(self)

    def __call__(self, instance, *args, **kwargs) -> None:
        return self.func(instance, *args, **kwargs)


# For custom functions that need to be called on candle close
class OnCandleClose:

    # Class variable to store all decorated methods (on candle close)
    on_candle_closes = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        OnCandleClose.on_candle_closes.append(self)

    def __call__(self, instance, *args, **kwargs) -> None:
        return self.func(instance, *args, **kwargs)


# --- Entry/Exit Signals ---

class ShortCondition:

    # Class variable to store all decorated methods (short conditions)
    short_conditions = []
    
    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        ShortCondition.short_conditions.append(self)

    def __call__(self, instance, *args, **kwargs) -> bool:
        return self.func(instance, *args, **kwargs)

class CoverCondition:

    # Class variable to store all decorated methods (cover conditions)
    cover_conditions = []
    
    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        CoverCondition.cover_conditions.append(self)

    def __call__(self, instance, *args, **kwargs) -> bool:
        return self.func(instance, *args, **kwargs)

# --- Risk Management ---

class TrailingStop:

    # Class variable to store all decorated methods (trailing stop)
    trailing_stops = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        TrailingStop.trailing_stops.append(self)

    def __call__(self, instance, *args, **kwargs) -> float:
        return self.func(instance, *args, **kwargs)
    
    def purge(self):
        TrailingStop.trailing_stops = []

# --- Filters, Sizing, and Configuration ---

class MarketFilter:

    # Class variable to store all decorated methods (market filter)
    market_filters = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        MarketFilter.market_filters.append(self)

    def __call__(self, instance, *args, **kwargs) -> bool:
        return self.func(instance, *args, **kwargs)

class PositionSize:

    # Class variable to store all decorated methods (position size)
    position_sizes = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        PositionSize.position_sizes.append(self)

    def __call__(self, instance, *args, **kwargs) -> float:
        return self.func(instance, *args, **kwargs)

class WarmupPeriod:

    # Class variable to store all decorated methods (warmup period)
    warmup_periods = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        WarmupPeriod.warmup_periods.append(self)

    def __call__(self, instance, *args, **kwargs) -> int:
        return self.func(instance, *args, **kwargs)

class TradingSession:

    # Class variable to store all decorated methods (trading session)
    trading_sessions = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        TradingSession.trading_sessions.append(self)

    def __call__(self, instance, *args, **kwargs) -> bool:
        return self.func(instance, *args, **kwargs)

# --- Event Hooks ---

class OnEntry:

    # Class variable to store all decorated methods (on entry)
    on_entries = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        OnEntry.on_entries.append(self)

    def __call__(self, instance, *args, **kwargs) -> None:
        return self.func(instance, *args, **kwargs)

class OnExit:

    # Class variable to store all decorated methods (on exit)
    on_exits = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        OnExit.on_exits.append(self)

    def __call__(self, instance, *args, **kwargs) -> None:
        return self.func(instance, *args, **kwargs)

class OnStopLossHit:

    # Class variable to store all decorated methods (on stop loss hit)
    on_stop_loss_hits = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        OnStopLossHit.on_stop_loss_hits.append(self)

    def __call__(self, instance, *args, **kwargs) -> None:
        return self.func(instance, *args, **kwargs)

class OnTakeProfitHit:

    # Class variable to store all decorated methods (on take profit hit)
    on_take_profit_hits = []

    def __init__(self, func):
        self.func = func
        self.func_name = func.__name__
        self.func_description = func.__doc__
        OnTakeProfitHit.on_take_profit_hits.append(self)

    def __call__(self, instance, *args, **kwargs) -> None:
        return self.func(instance, *args, **kwargs)