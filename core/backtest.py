"""
backtest.py — Core Backtesting Engine

This module drives the entire simulation. It consumes the decorator-based
strategy API defined in decorators.py and strategy.py, iterates through
historical data bar-by-bar, simulates order execution with realistic
fill logic (slippage, fees, gap handling), and produces a performance report.

Architecture:
    Order       — data class representing a single order
    Position    — data class representing an open position
    Broker      — simulates order fills against candle data
    Portfolio   — tracks cash, positions, equity curve, trade records
    run_backtest()      — the main event loop orchestrator
    generate_report()   — computes performance metrics from results
"""

import math
import numpy as np
import pandas as pd
from datetime import datetime

from .decorators import (
    Indicator, BuyCondition, SellCondition, ShortCondition, CoverCondition,
    StopLoss, TakeProfit, TrailingStop, MarketFilter, PositionSize,
    WarmupPeriod, TradingSession, OnCandleOpen, OnCandleClose,
    OnEntry, OnExit, OnStopLossHit, OnTakeProfitHit
)


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class Order:
    """
    Represents a single order in the simulation.

    An order starts as 'pending' and transitions to 'filled' or 'cancelled'.
    The Broker processes pending orders against incoming candle data to
    determine if and when they should fill.

    Attributes:
        order_type (str): 'market', 'limit', or 'stop'.
        side (str): 'buy', 'sell', 'short', or 'cover'.
        quantity (int): Number of shares/units to trade.
        price (float | None): Target price for limit/stop orders. None for market.
        timestamp: When the order was placed.
        status (str): 'pending', 'filled', or 'cancelled'.
        raw_fill_price (float | None): Fill price before slippage.
        fill_price (float | None): Actual execution price after slippage.
        fill_timestamp: When the order was filled.
        trigger (str): What caused this order — e.g. 'buy_signal', 'stop_loss',
                       'take_profit', 'sell_signal', 'trailing_stop', 'force_close'.
        position_id (int | None): Links exit orders to their parent position.
    """

    _id_counter = 0

    def __init__(self, order_type: str, side: str, quantity: float,
                 price: float = None, timestamp=None, trigger: str = "",
                 position_id: int = None):
        Order._id_counter += 1
        self.id = Order._id_counter
        self.order_type = order_type
        self.side = side
        self.quantity = quantity
        self.price = price
        self.timestamp = timestamp
        self.status = "pending"
        self.raw_fill_price = None
        self.fill_price = None
        self.fill_timestamp = None
        self.trigger = trigger
        self.position_id = position_id

    def __repr__(self):
        return (f"Order(id={self.id}, {self.order_type} {self.side} "
                f"qty={self.quantity}, price={self.price}, "
                f"status={self.status}, trigger={self.trigger})")


class Position:
    """
    Represents an open position in the portfolio.

    Tracks entry details, current SL/TP levels, and the high/low watermark
    since entry (used for trailing stop calculations).

    Attributes:
        side (str): 'long' or 'short'.
        entry_price (float): The fill price at which the position was opened.
        quantity (int): Number of shares held.
        entry_time: Timestamp of entry.
        stop_loss (float | None): Current stop-loss price level.
        take_profit (float | None): Current take-profit price level.
        highest_price (float): Highest price seen since entry (for trailing SL on longs).
        lowest_price (float): Lowest price seen since entry (for trailing SL on shorts).
        fees_paid (float): Total brokerage fees paid for this position so far.
    """

    _id_counter = 0

    def __init__(self, side: str, entry_price: float, quantity: float,
                 entry_time=None, fees: float = 0.0):
        Position._id_counter += 1
        self.id = Position._id_counter
        self.side = side
        self.entry_price = entry_price
        self.quantity = quantity
        self.entry_time = entry_time
        self.stop_loss = None
        self.take_profit = None
        self.highest_price = entry_price
        self.lowest_price = entry_price
        self.fees_paid = fees

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculates unrealized P&L at the given price (excluding fees)."""
        if self.side == "long":
            return (current_price - self.entry_price) * self.quantity
        else:  # short
            return (self.entry_price - current_price) * self.quantity

    def update_watermarks(self, high: float, low: float):
        """Updates the high/low watermarks with the current candle's data."""
        if high > self.highest_price:
            self.highest_price = high
        if low < self.lowest_price:
            self.lowest_price = low

    def __repr__(self):
        return (f"Position(id={self.id}, {self.side} @ {self.entry_price:.2f}, "
                f"qty={self.quantity}, SL={self.stop_loss}, TP={self.take_profit})")


# ═══════════════════════════════════════════════════════════════════════════
# BROKER — Order Execution Simulation
# ═══════════════════════════════════════════════════════════════════════════

class Broker:
    """
    Simulates order execution against historical candle data.

    Manages the lifecycle of orders: placement, fill logic, slippage
    application, and fee calculation. Handles the ambiguity of intra-bar
    events (e.g., when both SL and TP could trigger on the same candle)
    using open-priority resolution.

    Args:
        slippage_pct (float): Slippage percentage applied to fills (e.g. 0.01 = 1%).
        brokerage_fee_pct (float): Brokerage fee as a percentage of trade value.
    """

    def __init__(self, slippage_pct: float = 0.0, brokerage_fee_pct: float = 0.0):
        self.slippage_pct = slippage_pct
        self.brokerage_fee_pct = brokerage_fee_pct
        self.pending_orders: list[Order] = []
        self.filled_orders: list[Order] = []
        self.cancelled_orders: list[Order] = []

    def place_order(self, order: Order):
        """Adds an order to the pending queue."""
        self.pending_orders.append(order)

    def cancel_orders_for_position(self, position_id: int):
        """
        Cancels all pending orders linked to a given position.

        This is called when a position is closed (e.g., SL hit) to ensure
        the orphaned TP order (or vice versa) doesn't linger.
        """
        remaining = []
        for order in self.pending_orders:
            if order.position_id == position_id:
                order.status = "cancelled"
                self.cancelled_orders.append(order)
            else:
                remaining.append(order)
        self.pending_orders = remaining

    def process_pending_orders(self, candle: pd.Series) -> list[Order]:
        """
        Processes all pending orders against the current candle.

        For each pending order, determines if the candle's price action
        would trigger a fill. Market orders fill at the candle's open.
        Limit and stop orders are checked against the candle's OHLC range.

        Args:
            candle: A pandas Series with 'open', 'high', 'low', 'close', 'timestamp'.

        Returns:
            A list of orders that were filled on this candle.
        """
        newly_filled = []
        still_pending = []

        for order in self.pending_orders:
            fill_price = self._try_fill(order, candle)

            if fill_price is not None:
                # Store raw price and apply slippage
                order.raw_fill_price = fill_price
                order.fill_price = self._apply_slippage(fill_price, order.side)
                order.fill_timestamp = candle['timestamp']
                order.status = "filled"
                self.filled_orders.append(order)
                newly_filled.append(order)
            else:
                still_pending.append(order)

        self.pending_orders = still_pending
        return newly_filled

    def _try_fill(self, order: Order, candle: pd.Series) -> float | None:
        """
        Attempts to fill an order against the given candle.

        Returns the raw fill price (before slippage) if the order can be
        filled, or None if it cannot.

        Fill Logic:
            Market: Always fills at the candle's open.
            Limit Buy:  Fills if low <= limit_price. Price = min(open, limit).
            Limit Sell: Fills if high >= limit_price. Price = max(open, limit).
            Stop Sell (long SL): Fills if low <= stop_price.
                                 Price = min(open, stop) — gap-through hurts.
            Stop Buy (short SL): Fills if high >= stop_price.
                                 Price = max(open, stop) — gap-through hurts.
        """
        o, h, l = candle['open'], candle['high'], candle['low']

        if order.order_type == "market":
            return o

        elif order.order_type == "limit":
            if order.side in ("buy", "cover"):
                # Limit buy: want to buy at limit_price or lower
                if l <= order.price:
                    # If open is already at or below limit, fill at open (gap-through, favorable)
                    return min(o, order.price)
            elif order.side in ("sell", "short"):
                # Limit sell: want to sell at limit_price or higher
                if h >= order.price:
                    return max(o, order.price)

        elif order.order_type == "stop":
            if order.side in ("sell", "cover_stop"):
                # Stop sell (long SL): triggers when price drops to stop level
                if l <= order.price:
                    # If open gaps below stop, fill at open (gap-through, unfavorable)
                    return min(o, order.price)
            elif order.side in ("buy", "short_stop"):
                # Stop buy (short SL / cover): triggers when price rises to stop level
                if h >= order.price:
                    return max(o, order.price)

        return None

    def _apply_slippage(self, price: float, side: str) -> float:
        """
        Applies slippage to a fill price. Slippage always works against
        the trader: buys get slightly worse (higher), sells get slightly
        worse (lower).
        """
        if side in ("buy", "cover", "short_stop"):
            return price * (1 + self.slippage_pct)
        else:  # sell, short, cover_stop
            return price * (1 - self.slippage_pct)

    def calculate_fees(self, fill_price: float, quantity: int) -> float:
        """Calculates brokerage fees for a fill."""
        return abs(fill_price * quantity * self.brokerage_fee_pct)


# ═══════════════════════════════════════════════════════════════════════════
# PORTFOLIO — Cash, Position, and Equity Management
# ═══════════════════════════════════════════════════════════════════════════

class Portfolio:
    """
    Tracks the full accounting state of the backtest.

    Manages cash, open positions, closed trade records, and the equity
    curve. Enforces position limits and handles position sizing.

    Args:
        initial_cash (float): Starting capital.
        max_active_positions (int): Maximum concurrent open positions.
        position_sizing_pct (float): Default % of equity per position (e.g. 25 = 25%).
        overall_stoploss_amount (float): Session-level circuit breaker — cumulative
            realized loss threshold. Once breached, no new positions are opened.
        takeprofit_amount (float): Default take-profit amount from config (per-trade).
    """

    def __init__(self, initial_cash: float, max_active_positions: int = 1,
                 position_sizing_pct: float = 100.0,
                 overall_stoploss_amount: float = 0.0,
                 takeprofit_amount: float = 0.0,
                 allow_fractional_shares: bool = False):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.max_active_positions = max_active_positions
        self.position_sizing_pct = position_sizing_pct
        self.overall_stoploss_amount = overall_stoploss_amount
        self.takeprofit_amount = takeprofit_amount
        self.allow_fractional_shares = allow_fractional_shares

        self.positions: list[Position] = []
        self.closed_trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.cumulative_realized_loss = 0.0  # tracks session-level losses
        self.total_slippage_cost = 0.0       # tracks total slippage across all trades
        self.total_commission_paid = 0.0     # tracks total brokerage fees

    def can_open_position(self) -> bool:
        """
        Checks whether a new position can be opened.

        Returns False if:
            - Already at max_active_positions limit.
            - The session-level circuit breaker has been tripped.
        """
        if len(self.positions) >= self.max_active_positions:
            return False

        # Circuit breaker: if cumulative losses exceed the threshold, halt trading
        if (self.overall_stoploss_amount > 0 and
                self.cumulative_realized_loss >= self.overall_stoploss_amount):
            return False

        return True

    def calculate_position_size(self, price: float) -> float:
        """
        Calculates the number of shares to buy based on a percentage of
        current total equity.

        Uses the default position_sizing_pct from config. This can be
        overridden by the @PositionSize decorator in the strategy.

        Returns:
            float: Number of shares. Returns 0 if price
                 is zero or equity is insufficient.
        """
        if price <= 0:
            return 0.0
        equity = self.get_total_equity(price)
        allocated_capital = equity * (self.position_sizing_pct / 100.0)
        quantity = allocated_capital / price
        
        if not self.allow_fractional_shares:
            quantity = float(int(quantity))
            
        return max(quantity, 0.0)

    def open_position(self, side: str, fill_price: float, quantity: float,
                      timestamp, fees: float,
                      slippage_cost: float = 0.0) -> Position:
        """
        Opens a new position and deducts the cost from cash.

        Args:
            side: 'long' or 'short'.
            fill_price: The fill price after slippage.
            quantity: Number of shares.
            timestamp: When the fill occurred.
            fees: Brokerage fees for this entry.
            slippage_cost: The cost of slippage on this fill.

        Returns:
            The newly created Position object.
        """
        cost = fill_price * quantity
        self.cash -= (cost + fees)
        self.total_slippage_cost += slippage_cost
        self.total_commission_paid += fees

        position = Position(
            side=side,
            entry_price=fill_price,
            quantity=quantity,
            entry_time=timestamp,
            fees=fees
        )
        self.positions.append(position)
        return position

    def close_position(self, position: Position, fill_price: float,
                       timestamp, fees: float, reason: str,
                       slippage_cost: float = 0.0) -> dict:
        """
        Closes a position, credits cash, and records the completed trade.

        Args:
            position: The Position object to close.
            fill_price: The exit fill price after slippage.
            timestamp: When the exit fill occurred.
            fees: Brokerage fees for this exit.
            reason: Why the position was closed (e.g. 'sell_signal',
                    'stop_loss', 'take_profit', 'force_close').
            slippage_cost: The cost of slippage on this exit fill.

        Returns:
            A dict representing the completed trade record.
        """
        # Calculate proceeds
        proceeds = fill_price * position.quantity
        if position.side == "long":
            self.cash += proceeds - fees
        else:  # short: we originally received cash on entry, now we buy back
            # For shorts: profit = (entry - exit) * qty
            # Cash change: we add back the original cost and subtract the buyback cost
            self.cash += (position.entry_price * position.quantity) + \
                         (position.entry_price - fill_price) * position.quantity - fees

        # Track costs
        self.total_slippage_cost += slippage_cost
        self.total_commission_paid += fees

        # Calculate P&L
        total_fees = position.fees_paid + fees
        if position.side == "long":
            gross_pnl = (fill_price - position.entry_price) * position.quantity
        else:
            gross_pnl = (position.entry_price - fill_price) * position.quantity
        net_pnl = gross_pnl - total_fees

        # Track cumulative losses for circuit breaker
        if net_pnl < 0:
            self.cumulative_realized_loss += abs(net_pnl)

        # Build trade record
        trade = {
            "position_id": position.id,
            "side": position.side,
            "entry_price": position.entry_price,
            "exit_price": fill_price,
            "quantity": position.quantity,
            "entry_time": position.entry_time,
            "exit_time": timestamp,
            "gross_pnl": gross_pnl,
            "fees": total_fees,
            "slippage_cost": slippage_cost,
            "net_pnl": net_pnl,
            "exit_reason": reason,
        }
        self.closed_trades.append(trade)

        # Remove from active positions
        self.positions = [p for p in self.positions if p.id != position.id]

        return trade

    def get_total_equity(self, current_price: float) -> float:
        """
        Calculates total portfolio equity: cash + market value of all
        open positions at the given price.
        """
        positions_value = sum(
            p.entry_price * p.quantity + p.unrealized_pnl(current_price)
            for p in self.positions
        )
        return self.cash + positions_value

    def update_equity(self, timestamp, current_price: float):
        """Snapshots total equity for the equity curve."""
        equity = self.get_total_equity(current_price)
        self.equity_curve.append({
            "timestamp": timestamp,
            "equity": equity,
        })


# ═══════════════════════════════════════════════════════════════════════════
# THE EVENT LOOP — run_backtest()
# ═══════════════════════════════════════════════════════════════════════════

def run_backtest(strategy_class, data: pd.DataFrame, config: dict) -> dict:
    """
    Runs a full backtest simulation.

    This is the main orchestrator. It:
        1. Instantiates the user's strategy (which calculates indicators).
        2. Initializes the Broker and Portfolio from config.
        3. Iterates through each candle in the data, executing the 7-phase
           event loop on each bar.
        4. Force-closes any remaining positions at the end.
        5. Generates and returns a performance report.

    Args:
        strategy_class: The user's Strategy subclass (the class itself, not an instance).
        data (pd.DataFrame): Historical OHLCV data with a 'timestamp' column.
        config (dict): The full config dictionary (as loaded from config.json).

    Returns:
        A dict containing:
            'metrics':      Performance metrics (dict).
            'equity_curve': List of {timestamp, equity} snapshots.
            'trades':       List of completed trade records.
            'data':         The DataFrame with indicators attached.
    """

    # ── Setup ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("BACKTEST ENGINE — Starting Simulation")
    print("=" * 60)

    # Extract config sections
    portfolio_config = config.get("portfolio", {})
    risk_config = config.get("risk_management", {})
    sim_config = config.get("simulation", {})

    # Reset static ID counters for clean runs
    Order._id_counter = 0
    Position._id_counter = 0

    # Initialize the strategy (this triggers indicator calculation)
    strategy = strategy_class(data, config)

    # Initialize Broker
    broker = Broker(
        slippage_pct=sim_config.get("slippage_pct", 0.0),
        brokerage_fee_pct=sim_config.get("brokerage_fee_pct", 0.0)
    )

    # Initialize Portfolio
    portfolio = Portfolio(
        initial_cash=portfolio_config.get("initial_cash", 100000),
        max_active_positions=portfolio_config.get("max_active_positions", 1),
        position_sizing_pct=risk_config.get("position_sizing_pct_of_equity", 100.0),
        overall_stoploss_amount=risk_config.get("overall_stoploss_amount", 0.0),
        takeprofit_amount=risk_config.get("takeprofit_amount", 0.0),
        allow_fractional_shares=sim_config.get("allow_fractional_shares", False)
    )

    # Determine warmup period
    warmup = 0
    for wp_decorator in WarmupPeriod.warmup_periods:
        val = wp_decorator(strategy)
        if val is not None and val > warmup:
            warmup = val
    print(f"Warmup period: {warmup} bars")

    total_bars = len(data)
    print(f"Total bars: {total_bars} | Tradeable bars: {total_bars - warmup}")
    print("-" * 60)

    # ── Main Event Loop ──────────────────────────────────────────────────

    for i in range(total_bars):
        candle = data.iloc[i]
        strategy._set_current_bar_index(i)

        # ── Phase 1: Process Pending Orders ──────────────────────────
        # Orders placed on the previous bar get filled here (next bar's open).
        filled_orders = broker.process_pending_orders(candle)

        for order in filled_orders:
            fees = broker.calculate_fees(order.fill_price, order.quantity)
            slip_cost = abs(order.fill_price - order.raw_fill_price) * order.quantity if order.raw_fill_price else 0.0

            if order.trigger in ("buy_signal", "short_signal"):
                # ── Entry Fill ──
                pos_side = "long" if order.side == "buy" else "short"
                position = portfolio.open_position(
                    side=pos_side,
                    fill_price=order.fill_price,
                    quantity=order.quantity,
                    timestamp=order.fill_timestamp,
                    fees=fees,
                    slippage_cost=slip_cost
                )

                # Set initial SL/TP from config defaults
                _set_initial_sl_tp(position, strategy, risk_config)

                # Fire @OnEntry hooks
                for hook in OnEntry.on_entries:
                    hook(strategy)

            else:
                # ── Exit Fill ──
                # Find the position this order belongs to
                target_position = None
                for p in portfolio.positions:
                    if p.id == order.position_id:
                        target_position = p
                        break

                if target_position is not None:
                    # Close the position
                    trade = portfolio.close_position(
                        position=target_position,
                        fill_price=order.fill_price,
                        timestamp=order.fill_timestamp,
                        fees=fees,
                        reason=order.trigger,
                        slippage_cost=slip_cost
                    )

                    # Cancel any remaining orders linked to this position
                    broker.cancel_orders_for_position(target_position.id)

                    # Fire the appropriate event hooks
                    for hook in OnExit.on_exits:
                        hook(strategy)

                    if order.trigger == "stop_loss" or order.trigger == "trailing_stop":
                        for hook in OnStopLossHit.on_stop_loss_hits:
                            hook(strategy)
                    elif order.trigger == "take_profit":
                        for hook in OnTakeProfitHit.on_take_profit_hits:
                            hook(strategy)

        # Skip signal evaluation during warmup, but still process fills above
        if i < warmup:
            portfolio.update_equity(candle['timestamp'], candle['close'])
            continue

        # ── Phase 2: Fire @OnCandleOpen hooks ────────────────────────
        for hook in OnCandleOpen.on_candle_opens:
            hook(strategy)

        # ── Phase 3: Check Filters ───────────────────────────────────
        market_ok = all(
            f(strategy) for f in MarketFilter.market_filters
        ) if MarketFilter.market_filters else True

        session_ok = all(
            s(strategy) for s in TradingSession.trading_sessions
        ) if TradingSession.trading_sessions else True

        filters_pass = market_ok and session_ok

        # ── Phase 4: Manage Existing Positions ───────────────────────
        # Update watermarks and SL/TP levels, check for exit signals.
        positions_to_check = list(portfolio.positions)  # copy to avoid mutation during iteration

        for position in positions_to_check:
            # Update high/low watermarks for trailing stop
            position.update_watermarks(candle['high'], candle['low'])

            # Recalculate trailing stop if decorators are defined
            if TrailingStop.trailing_stops:
                for ts_decorator in TrailingStop.trailing_stops:
                    new_trailing_sl = ts_decorator(strategy)
                    if new_trailing_sl is not None:
                        if position.side == "long":
                            # Trailing SL can only move UP for longs
                            if position.stop_loss is None or new_trailing_sl > position.stop_loss:
                                position.stop_loss = new_trailing_sl
                        else:
                            # Trailing SL can only move DOWN for shorts
                            if position.stop_loss is None or new_trailing_sl < position.stop_loss:
                                position.stop_loss = new_trailing_sl

            # Recalculate dynamic SL from @StopLoss decorators (non-trailing)
            elif StopLoss.stop_losses:
                for sl_decorator in StopLoss.stop_losses:
                    new_sl = sl_decorator(strategy)
                    if new_sl is not None:
                        position.stop_loss = new_sl

            # Recalculate dynamic TP from @TakeProfit decorators
            if TakeProfit.take_profits:
                for tp_decorator in TakeProfit.take_profits:
                    new_tp = tp_decorator(strategy)
                    if new_tp is not None:
                        position.take_profit = new_tp

            # ── Check for SL/TP hits on current candle ──
            # Use open-priority: whichever level is closer to the open triggers first
            sl_hit = False
            tp_hit = False

            if position.stop_loss is not None:
                if position.side == "long" and candle['low'] <= position.stop_loss:
                    sl_hit = True
                elif position.side == "short" and candle['high'] >= position.stop_loss:
                    sl_hit = True

            if position.take_profit is not None:
                if position.side == "long" and candle['high'] >= position.take_profit:
                    tp_hit = True
                elif position.side == "short" and candle['low'] <= position.take_profit:
                    tp_hit = True

            if sl_hit and tp_hit:
                # Both triggered — use open-priority: whichever is closer to open fires first
                sl_dist = abs(candle['open'] - position.stop_loss)
                tp_dist = abs(candle['open'] - position.take_profit)
                if sl_dist <= tp_dist:
                    tp_hit = False  # SL wins
                else:
                    sl_hit = False  # TP wins

            if sl_hit:
                # Determine fill price for the stop
                if position.side == "long":
                    fill_raw = min(candle['open'], position.stop_loss)
                else:
                    fill_raw = max(candle['open'], position.stop_loss)

                exit_side = "sell" if position.side == "long" else "cover"
                trigger = "trailing_stop" if TrailingStop.trailing_stops else "stop_loss"
                fill_price = broker._apply_slippage(fill_raw, exit_side)
                fees = broker.calculate_fees(fill_price, position.quantity)

                portfolio.close_position(position, fill_price,
                                         candle['timestamp'], fees, trigger)
                broker.cancel_orders_for_position(position.id)

                for hook in OnExit.on_exits:
                    hook(strategy)
                for hook in OnStopLossHit.on_stop_loss_hits:
                    hook(strategy)

            elif tp_hit:
                if position.side == "long":
                    fill_raw = max(candle['open'], position.take_profit)
                else:
                    fill_raw = min(candle['open'], position.take_profit)

                exit_side = "sell" if position.side == "long" else "cover"
                fill_price = broker._apply_slippage(fill_raw, exit_side)
                fees = broker.calculate_fees(fill_price, position.quantity)

                portfolio.close_position(position, fill_price,
                                         candle['timestamp'], fees, "take_profit")
                broker.cancel_orders_for_position(position.id)

                for hook in OnExit.on_exits:
                    hook(strategy)
                for hook in OnTakeProfitHit.on_take_profit_hits:
                    hook(strategy)

            else:
                # Position is still open — check for sell/cover signal conditions
                if position.side == "long" and SellCondition.sell_conditions:
                    if all(sc(strategy) for sc in SellCondition.sell_conditions):
                        order = Order(
                            order_type="market",
                            side="sell",
                            quantity=position.quantity,
                            timestamp=candle['timestamp'],
                            trigger="sell_signal",
                            position_id=position.id
                        )
                        broker.place_order(order)

                elif position.side == "short" and CoverCondition.cover_conditions:
                    if all(cc(strategy) for cc in CoverCondition.cover_conditions):
                        order = Order(
                            order_type="market",
                            side="cover",
                            quantity=position.quantity,
                            timestamp=candle['timestamp'],
                            trigger="cover_signal",
                            position_id=position.id
                        )
                        broker.place_order(order)

        # ── Phase 5: Check Entry Signals ─────────────────────────────
        if filters_pass and portfolio.can_open_position():

            # Check @BuyCondition — AND logic: all must agree
            if BuyCondition.buy_conditions:
                buy_signal = all(
                    bc(strategy) for bc in BuyCondition.buy_conditions
                )
            else:
                buy_signal = False

            if buy_signal:
                # Determine position size
                quantity = _get_position_size(strategy, portfolio, candle['close'])
                if quantity > 0:
                    order = Order(
                        order_type="market",
                        side="buy",
                        quantity=quantity,
                        timestamp=candle['timestamp'],
                        trigger="buy_signal"
                    )
                    broker.place_order(order)

            # Check @ShortCondition — AND logic: all must agree
            if ShortCondition.short_conditions and portfolio.can_open_position():
                short_signal = all(
                    sc(strategy) for sc in ShortCondition.short_conditions
                )

                if short_signal:
                    quantity = _get_position_size(strategy, portfolio, candle['close'])
                    if quantity > 0:
                        order = Order(
                            order_type="market",
                            side="short",
                            quantity=quantity,
                            timestamp=candle['timestamp'],
                            trigger="short_signal"
                        )
                        broker.place_order(order)

        # ── Phase 6: Fire @OnCandleClose hooks ───────────────────────
        for hook in OnCandleClose.on_candle_closes:
            hook(strategy)

        # ── Phase 7: Update Equity Curve ─────────────────────────────
        portfolio.update_equity(candle['timestamp'], candle['close'])

    # ── Post-Loop: Force-Close Remaining Positions ───────────────────
    if portfolio.positions:
        last_candle = data.iloc[-1]
        print(f"\nForce-closing {len(portfolio.positions)} remaining position(s) "
              f"at last candle's close ({last_candle['close']:.2f})...")

        for position in list(portfolio.positions):
            exit_side = "sell" if position.side == "long" else "cover"
            fill_price = broker._apply_slippage(last_candle['close'], exit_side)
            fees = broker.calculate_fees(fill_price, position.quantity)
            portfolio.close_position(position, fill_price,
                                     last_candle['timestamp'], fees, "force_close")

    # ── Generate Report ──────────────────────────────────────────────
    report = generate_report(portfolio, data)

    # Attach data and trade details for plotting
    report["equity_curve"] = portfolio.equity_curve
    report["trades"] = portfolio.closed_trades
    report["data"] = strategy.data  # DataFrame with indicators merged in

    print("\n" + "=" * 60)
    print("BACKTEST ENGINE — Simulation Complete")
    print("=" * 60)
    _print_report(report["metrics"])

    return report


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _set_initial_sl_tp(position: Position, strategy, risk_config: dict):
    """
    Sets the initial stop-loss and take-profit levels on a newly opened position.

    Priority:
        1. @StopLoss / @TakeProfit decorators (dynamic, strategy-defined).
        2. Config-level defaults (overall_stoploss_amount is session-level,
           takeprofit_amount is per-trade).
    """
    # Try decorator-defined SL
    if StopLoss.stop_losses:
        for sl_decorator in StopLoss.stop_losses:
            sl_value = sl_decorator(strategy)
            if sl_value is not None:
                position.stop_loss = sl_value

    # Try decorator-defined TP
    if TakeProfit.take_profits:
        for tp_decorator in TakeProfit.take_profits:
            tp_value = tp_decorator(strategy)
            if tp_value is not None:
                position.take_profit = tp_value

    # Fallback: config-level takeprofit_amount (treated as absolute price distance)
    if position.take_profit is None and risk_config.get("takeprofit_amount", 0) > 0:
        tp_amount = risk_config["takeprofit_amount"]
        if position.side == "long":
            position.take_profit = position.entry_price + tp_amount
        else:
            position.take_profit = position.entry_price - tp_amount


def _get_position_size(strategy, portfolio: Portfolio, current_price: float) -> float:
    """
    Determines the position size for a new trade.

    Checks if the user defined a @PositionSize decorator; if so, uses that.
    Otherwise falls back to the Portfolio's default calculation.
    """
    if PositionSize.position_sizes:
        # Use the first defined @PositionSize decorator
        custom_qty = PositionSize.position_sizes[0](strategy)
        if custom_qty is not None and custom_qty > 0:
            return custom_qty if portfolio.allow_fractional_shares else float(int(custom_qty))

    return portfolio.calculate_position_size(current_price)


# ═══════════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def generate_report(portfolio: Portfolio, data: pd.DataFrame) -> dict:
    """
    Computes comprehensive performance metrics from the portfolio's
    closed trades, equity curve, and original price data.

    Metric categories:
        - Trade Duration: start, end, duration
        - Return: total return %, CAGR %, alpha
        - Risk: max drawdown, drawdown duration, volatility, downside dev, calmar
        - Risk-Adjusted: sharpe, sortino, omega
        - Trade-Level: win rate, profit factor, expectancy, streaks, etc.
        - Statistical Validity: t-stat, p-value, significance
        - Cost & Execution: commission, slippage, return after costs

    Args:
        portfolio: The Portfolio object after the backtest has completed.
        data: The original OHLCV DataFrame (used for buy-and-hold benchmark).

    Returns:
        A dict with a 'metrics' key containing all computed statistics.
    """
    trades = portfolio.closed_trades
    equity_curve = portfolio.equity_curve
    metrics = {}

    # ── Trade Duration ───────────────────────────────────────────────
    if equity_curve:
        metrics["start"] = equity_curve[0]["timestamp"]
        metrics["end"] = equity_curve[-1]["timestamp"]
        try:
            start_dt = pd.Timestamp(metrics["start"])
            end_dt = pd.Timestamp(metrics["end"])
            metrics["duration"] = str(end_dt - start_dt)
            duration_days = (end_dt - start_dt).total_seconds() / 86400
        except Exception:
            metrics["duration"] = "N/A"
            duration_days = 0
    else:
        metrics["start"] = "N/A"
        metrics["end"] = "N/A"
        metrics["duration"] = "N/A"
        duration_days = 0

    # ── Return ───────────────────────────────────────────────────────
    initial = portfolio.initial_cash
    final = portfolio.cash  # all positions closed at this point
    metrics["initial_capital"] = initial
    metrics["final_equity"] = final

    total_return_pct = ((final - initial) / initial) * 100 if initial != 0 else 0.0
    metrics["total_return_pct"] = total_return_pct

    # CAGR — Compound Annual Growth Rate
    duration_years = duration_days / 365.25 if duration_days > 0 else 0
    if duration_years > 0 and initial > 0 and final > 0:
        metrics["cagr_pct"] = ((final / initial) ** (1 / duration_years) - 1) * 100
    else:
        metrics["cagr_pct"] = 0.0

    # Alpha — strategy CAGR minus buy-and-hold CAGR on the same symbol
    if len(data) >= 2 and duration_years > 0:
        bh_start = data['close'].iloc[0]
        bh_end = data['close'].iloc[-1]
        if bh_start > 0 and bh_end > 0:
            bh_cagr = ((bh_end / bh_start) ** (1 / duration_years) - 1) * 100
        else:
            bh_cagr = 0.0
        metrics["alpha_pct"] = metrics["cagr_pct"] - bh_cagr
    else:
        metrics["alpha_pct"] = 0.0

    # ── Risk ─────────────────────────────────────────────────────────
    if len(equity_curve) > 1:
        equities = np.array([e["equity"] for e in equity_curve])
        timestamps = [e["timestamp"] for e in equity_curve]
        returns = np.diff(equities) / equities[:-1]

        # Max Drawdown % and Max Drawdown Duration
        peak = equities[0]
        max_dd_pct = 0.0
        dd_start_idx = 0
        max_dd_duration = pd.Timedelta(0)
        current_dd_start_idx = 0

        for idx, eq in enumerate(equities):
            if eq > peak:
                peak = eq
                current_dd_start_idx = idx  # new peak, reset drawdown start
            dd_pct = ((peak - eq) / peak) * 100 if peak != 0 else 0.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            # Track drawdown duration (time between current peak and recovery)
            if dd_pct > 0:
                try:
                    dd_dur = (pd.Timestamp(timestamps[idx])
                              - pd.Timestamp(timestamps[current_dd_start_idx]))
                    if dd_dur > max_dd_duration:
                        max_dd_duration = dd_dur
                except Exception:
                    pass

        metrics["max_drawdown_pct"] = max_dd_pct
        metrics["max_drawdown_duration"] = str(max_dd_duration) if max_dd_duration > pd.Timedelta(0) else "N/A"

        # Volatility % (Annualised) — std of returns × sqrt(252)
        std_ret = np.std(returns, ddof=1) if len(returns) > 1 else 0.0
        metrics["volatility_pct"] = std_ret * math.sqrt(252) * 100

        # Downside Deviation %
        downside_returns = returns[returns < 0]
        downside_std = np.std(downside_returns, ddof=1) if len(downside_returns) > 1 else 0.0
        metrics["downside_deviation_pct"] = downside_std * math.sqrt(252) * 100

        # Calmar Ratio — CAGR / Max Drawdown %
        metrics["calmar_ratio"] = (
            metrics["cagr_pct"] / metrics["max_drawdown_pct"]
            if metrics["max_drawdown_pct"] != 0 else 0.0
        )

        # ── Risk-Adjusted ────────────────────────────────────────────
        mean_ret = np.mean(returns)
        annualization = math.sqrt(252)

        # Sharpe Ratio
        metrics["sharpe_ratio"] = (
            (mean_ret / std_ret) * annualization if std_ret != 0 else 0.0
        )

        # Sortino Ratio
        metrics["sortino_ratio"] = (
            (mean_ret / downside_std) * annualization if downside_std != 0 else 0.0
        )

        # Omega Ratio — sum of gains / sum of losses (threshold = 0)
        gains = returns[returns > 0]
        losses_arr = returns[returns < 0]
        sum_gains = np.sum(gains) if len(gains) > 0 else 0.0
        sum_losses = abs(np.sum(losses_arr)) if len(losses_arr) > 0 else 0.0
        metrics["omega_ratio"] = (
            (sum_gains / sum_losses) if sum_losses != 0 else float('inf')
        )
    else:
        metrics["max_drawdown_pct"] = 0.0
        metrics["max_drawdown_duration"] = "N/A"
        metrics["volatility_pct"] = 0.0
        metrics["downside_deviation_pct"] = 0.0
        metrics["calmar_ratio"] = 0.0
        metrics["sharpe_ratio"] = 0.0
        metrics["sortino_ratio"] = 0.0
        metrics["omega_ratio"] = 0.0

    # ── Trade-Level ──────────────────────────────────────────────────
    metrics["total_trades"] = len(trades)

    if trades:
        pnls = [t["net_pnl"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        n_wins = len(wins)
        n_losses = len(losses)
        n_total = len(trades)

        metrics["win_rate_pct"] = (n_wins / n_total) * 100
        metrics["loss_rate_pct"] = (n_losses / n_total) * 100
        metrics["avg_win"] = float(np.mean(wins)) if wins else 0.0
        metrics["avg_loss"] = float(np.mean(losses)) if losses else 0.0

        # Win/Loss Ratio — avg win magnitude / avg loss magnitude
        avg_loss_abs = abs(metrics["avg_loss"]) if metrics["avg_loss"] != 0 else 0.0
        metrics["win_loss_ratio"] = (
            metrics["avg_win"] / avg_loss_abs if avg_loss_abs != 0 else float('inf')
        )

        # Profit Factor — gross profits / gross losses
        gross_profit = sum(wins) if wins else 0.0
        gross_loss_abs = abs(sum(losses)) if losses else 0.0
        metrics["profit_factor"] = (
            gross_profit / gross_loss_abs if gross_loss_abs != 0 else float('inf')
        )

        # Expectancy — (win_rate × avg_win) + (loss_rate × avg_loss)
        # Note: avg_loss is already negative, so this naturally subtracts
        win_rate = n_wins / n_total
        loss_rate = n_losses / n_total
        metrics["expectancy"] = (win_rate * metrics["avg_win"]) + (loss_rate * metrics["avg_loss"])

        metrics["largest_win"] = max(wins) if wins else 0.0
        metrics["largest_loss"] = min(losses) if losses else 0.0

        # Average Holding Period
        durations = []
        for t in trades:
            if t["entry_time"] is not None and t["exit_time"] is not None:
                try:
                    durations.append(
                        pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])
                    )
                except Exception:
                    pass
        if durations:
            avg_duration = sum(durations, pd.Timedelta(0)) / len(durations)
            metrics["avg_holding_period"] = str(avg_duration)
        else:
            metrics["avg_holding_period"] = "N/A"

        # Streaks
        win_streak, lose_streak = 0, 0
        max_win_streak, max_lose_streak = 0, 0
        for pnl in pnls:
            if pnl > 0:
                win_streak += 1
                lose_streak = 0
            else:
                lose_streak += 1
                win_streak = 0
            max_win_streak = max(max_win_streak, win_streak)
            max_lose_streak = max(max_lose_streak, lose_streak)

        metrics["max_consecutive_wins"] = max_win_streak
        metrics["max_consecutive_losses"] = max_lose_streak

        # ── Statistical Validity ─────────────────────────────────────
        pnls_arr = np.array(pnls)
        n = len(pnls_arr)
        mean_pnl = np.mean(pnls_arr)
        std_pnl = np.std(pnls_arr, ddof=1) if n > 1 else 0.0

        if std_pnl > 0 and n > 1:
            t_stat = mean_pnl / (std_pnl / math.sqrt(n))
            metrics["t_statistic"] = t_stat

            # Compute p-value: try scipy first, fall back to manual approx
            try:
                from scipy import stats as scipy_stats
                # Two-tailed t-test: is mean PnL significantly different from 0?
                _, p_val = scipy_stats.ttest_1samp(pnls_arr, 0)
                metrics["p_value"] = p_val
            except ImportError:
                # Manual approximation using the normal distribution for large n
                # For n >= 30 the t-distribution ≈ normal
                p_val = 2 * (1 - _normal_cdf(abs(t_stat)))
                metrics["p_value"] = p_val

            metrics["statistically_significant"] = metrics["p_value"] < 0.05
        else:
            metrics["t_statistic"] = 0.0
            metrics["p_value"] = 1.0
            metrics["statistically_significant"] = False

    else:
        # No trades — fill all trade-level metrics with defaults
        metrics["win_rate_pct"] = 0.0
        metrics["loss_rate_pct"] = 0.0
        metrics["avg_win"] = 0.0
        metrics["avg_loss"] = 0.0
        metrics["win_loss_ratio"] = 0.0
        metrics["profit_factor"] = 0.0
        metrics["expectancy"] = 0.0
        metrics["largest_win"] = 0.0
        metrics["largest_loss"] = 0.0
        metrics["avg_holding_period"] = "N/A"
        metrics["max_consecutive_wins"] = 0
        metrics["max_consecutive_losses"] = 0
        metrics["t_statistic"] = 0.0
        metrics["p_value"] = 1.0
        metrics["statistically_significant"] = False

    # ── Cost & Execution ─────────────────────────────────────────────
    metrics["total_commission_paid"] = portfolio.total_commission_paid
    metrics["total_slippage_cost"] = portfolio.total_slippage_cost

    total_costs = metrics["total_commission_paid"] + metrics["total_slippage_cost"]
    net_profit = final - initial
    gross_return = net_profit + total_costs  # what return would have been without costs

    metrics["return_after_costs"] = net_profit
    metrics["cost_as_pct_of_gross_return"] = (
        (total_costs / gross_return) * 100
        if gross_return != 0 else 0.0
    )

    return {"metrics": metrics}


def _normal_cdf(x: float) -> float:
    """
    Approximation of the standard normal CDF using the error function.
    Used as a fallback when scipy is not installed.
    """
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _print_report(metrics: dict):
    """Prints a formatted, grouped performance report to the console."""
    W = 65  # total width

    def _header(title: str):
        print(f"\n  ┌{'─' * (W - 4)}┐")
        print(f"  │ {title:<{W - 5}}│")
        print(f"  ├{'─' * (W - 4)}┤")

    def _row(label: str, value, fmt=""):
        if fmt == "₹":
            val_str = f"₹{value:>12,.2f}"
        elif fmt == "%":
            val_str = f"{value:>11.2f}%"
        elif fmt == "ratio":
            val_str = f"{value:>12.2f}"
        elif fmt == "int":
            val_str = f"{value:>12}"
        elif fmt == "bool":
            val_str = f"{'  ✓ Yes' if value else '  ✗ No':>12}"
        else:
            val_str = f"{str(value):>12}"
        print(f"  │  {label:<30} {val_str:<{W - 36}}│")

    def _footer():
        print(f"  └{'─' * (W - 4)}┘")

    print("\n" + "═" * W)
    print("  PERFORMANCE REPORT")
    print("═" * W)

    # ── Trade Duration ──
    _header("TRADE DURATION")
    _row("Start", metrics.get("start", "N/A"))
    _row("End", metrics.get("end", "N/A"))
    _row("Duration", metrics.get("duration", "N/A"))
    _footer()

    # ── Return ──
    _header("RETURN")
    _row("Total Return", metrics.get("total_return_pct", 0), "%")
    _row("CAGR", metrics.get("cagr_pct", 0), "%")
    _row("Alpha", metrics.get("alpha_pct", 0), "%")
    _footer()

    # ── Risk ──
    _header("RISK")
    _row("Max Drawdown", metrics.get("max_drawdown_pct", 0), "%")
    _row("Max Drawdown Duration", metrics.get("max_drawdown_duration", "N/A"))
    _row("Volatility (Annualised)", metrics.get("volatility_pct", 0), "%")
    _row("Downside Deviation", metrics.get("downside_deviation_pct", 0), "%")
    _row("Calmar Ratio", metrics.get("calmar_ratio", 0), "ratio")
    _footer()

    # ── Risk-Adjusted ──
    _header("RISK-ADJUSTED")
    _row("Sharpe Ratio", metrics.get("sharpe_ratio", 0), "ratio")
    _row("Sortino Ratio", metrics.get("sortino_ratio", 0), "ratio")
    _row("Omega Ratio", metrics.get("omega_ratio", 0), "ratio")
    _footer()

    # ── Trade-Level ──
    _header("TRADE-LEVEL")
    _row("Total Trades", metrics.get("total_trades", 0), "int")
    _row("Win Rate", metrics.get("win_rate_pct", 0), "%")
    _row("Loss Rate", metrics.get("loss_rate_pct", 0), "%")
    _row("Average Win", metrics.get("avg_win", 0), "₹")
    _row("Average Loss", metrics.get("avg_loss", 0), "₹")
    _row("Win/Loss Ratio", metrics.get("win_loss_ratio", 0), "ratio")
    _row("Profit Factor", metrics.get("profit_factor", 0), "ratio")
    _row("Expectancy", metrics.get("expectancy", 0), "₹")
    _row("Largest Win", metrics.get("largest_win", 0), "₹")
    _row("Largest Loss", metrics.get("largest_loss", 0), "₹")
    _row("Average Holding Period", metrics.get("avg_holding_period", "N/A"))
    _row("Max Consecutive Wins", metrics.get("max_consecutive_wins", 0), "int")
    _row("Max Consecutive Losses", metrics.get("max_consecutive_losses", 0), "int")
    _footer()

    # ── Statistical Validity ──
    _header("STATISTICAL VALIDITY")
    _row("t-Statistic", metrics.get("t_statistic", 0), "ratio")
    _row("p-Value", metrics.get("p_value", 1.0), "ratio")
    _row("Statistically Significant", metrics.get("statistically_significant", False), "bool")
    _footer()

    # ── Cost & Execution ──
    _header("COST & EXECUTION")
    _row("Total Commission Paid", metrics.get("total_commission_paid", 0), "₹")
    _row("Total Slippage Cost", metrics.get("total_slippage_cost", 0), "₹")
    _row("Return After Costs", metrics.get("return_after_costs", 0), "₹")
    _row("Cost as % of Gross Return", metrics.get("cost_as_pct_of_gross_return", 0), "%")
    _footer()

    print("═" * W)
