"""
plot.py — Interactive Backtest Visualization

Generates a single, self-contained interactive HTML file from backtest results.
Built on Plotly, the chart supports zoom, pan, hover, and range selection
for detailed inspection of trades, indicators, and portfolio performance.

Layout:
    Row 1 (main):   Candlestick chart + price-level indicator overlays + trade markers
    Row 2:          Volume bars
    Row 3:          Equity curve
    Rows 4+:        One subplot per non-overlay indicator (e.g. RSI, MACD)
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots


# Standard OHLCV columns — anything else in the DataFrame is an indicator
_OHLCV_COLS = {"open", "high", "low", "close", "volume", "timestamp"}

# Palette for indicator lines — cycles through these
_INDICATOR_COLORS = [
    "#FF6D00", "#2979FF", "#00E676", "#D500F9",
    "#FFD600", "#00B8D4", "#FF1744", "#76FF03",
    "#F50057", "#651FFF", "#00BFA5", "#FFAB00",
]


def plot_results(report: dict, output_path: str = "results.html"):
    """
    Generates an interactive HTML chart from backtest results.

    Args:
        report (dict): The full report dict returned by run_backtest().
            Expected keys:
                'data'          — pd.DataFrame with OHLCV + indicator columns
                'trades'        — list of trade record dicts
                'equity_curve'  — list of {timestamp, equity} dicts
                'metrics'       — dict of performance metrics
        output_path (str): Where to save the HTML file. Defaults to 'results.html'.
    """
    data = report["data"]
    trades = report.get("trades", [])
    equity_curve = report.get("equity_curve", [])
    metrics = report.get("metrics", {})

    # --- Identify Indicators ---
    indicator_cols = [
        col for col in data.columns if col.lower() not in _OHLCV_COLS
    ]

    # Classify indicators: overlay (price-scale) vs subplot (different scale)
    overlay_indicators = []
    subplot_indicators = []

    if indicator_cols and len(data) > 0:
        price_median = data["close"].median()
        for col in indicator_cols:
            col_data = data[col].dropna()
            if len(col_data) == 0:
                continue
            indicator_median = col_data.median()
            # Heuristic: if the indicator's median is within a factor of
            # the price, it's a price-level overlay (e.g., SMA, EMA, Bollinger).
            # Otherwise it goes in its own subplot (e.g., RSI, MACD).
            if price_median > 0 and 0.1 * price_median <= indicator_median <= 10 * price_median:
                overlay_indicators.append(col)
            else:
                subplot_indicators.append(col)

    # --- Determine Layout ---
    # Fixed rows: candlestick (1), volume (2), equity curve (3)
    # Dynamic rows: one per subplot indicator
    n_fixed_rows = 3
    n_subplot_indicators = len(subplot_indicators)
    total_rows = n_fixed_rows + n_subplot_indicators

    # Row height ratios
    # Main chart gets the most space, volume and equity get less, subplots get equal small shares
    row_heights = [0.55, 0.10, 0.15]  # candlestick, volume, equity
    if n_subplot_indicators > 0:
        subplot_height = 0.20 / n_subplot_indicators
        row_heights.extend([subplot_height] * n_subplot_indicators)

    # Normalize to sum to 1
    total_h = sum(row_heights)
    row_heights = [h / total_h for h in row_heights]

    # Build subplot titles
    subplot_titles = ["", "Volume", "Equity Curve"]
    subplot_titles.extend([col.upper() for col in subplot_indicators])

    fig = make_subplots(
        rows=total_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    # ═══════════════════════════════════════════════════════════════════
    # ROW 1: Candlestick Chart
    # ═══════════════════════════════════════════════════════════════════
    fig.add_trace(
        go.Candlestick(
            x=data["timestamp"],
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            name="Price",
            increasing_line_color="#26A69A",
            decreasing_line_color="#EF5350",
            increasing_fillcolor="#26A69A",
            decreasing_fillcolor="#EF5350",
            showlegend=True,
        ),
        row=1, col=1,
    )

    # --- Overlay Indicators on Price Chart ---
    for i, col in enumerate(overlay_indicators):
        color = _INDICATOR_COLORS[i % len(_INDICATOR_COLORS)]
        fig.add_trace(
            go.Scatter(
                x=data["timestamp"],
                y=data[col],
                mode="lines",
                name=col.upper(),
                line=dict(color=color, width=1.2),
                opacity=0.85,
            ),
            row=1, col=1,
        )

    # --- Trade Entry/Exit Markers ---
    if trades:
        _add_trade_markers(fig, trades, row=1, col=1)

    # ═══════════════════════════════════════════════════════════════════
    # ROW 2: Volume Bars
    # ═══════════════════════════════════════════════════════════════════
    # Color volume bars based on candle direction
    colors = [
        "#26A69A" if c >= o else "#EF5350"
        for o, c in zip(data["open"], data["close"])
    ]
    fig.add_trace(
        go.Bar(
            x=data["timestamp"],
            y=data["volume"],
            marker_color=colors,
            name="Volume",
            showlegend=False,
            opacity=0.6,
        ),
        row=2, col=1,
    )

    # ═══════════════════════════════════════════════════════════════════
    # ROW 3: Equity Curve
    # ═══════════════════════════════════════════════════════════════════
    if equity_curve:
        eq_timestamps = [e["timestamp"] for e in equity_curve]
        eq_values = [e["equity"] for e in equity_curve]

        fig.add_trace(
            go.Scatter(
                x=eq_timestamps,
                y=eq_values,
                mode="lines",
                name="Equity",
                line=dict(color="#42A5F5", width=1.5),
                fill="tozeroy",
                fillcolor="rgba(66, 165, 245, 0.08)",
            ),
            row=3, col=1,
        )

    # ═══════════════════════════════════════════════════════════════════
    # ROWS 4+: Subplot Indicators (RSI, MACD, etc.)
    # ═══════════════════════════════════════════════════════════════════
    for i, col in enumerate(subplot_indicators):
        row_idx = n_fixed_rows + i + 1
        color = _INDICATOR_COLORS[(len(overlay_indicators) + i) % len(_INDICATOR_COLORS)]
        fig.add_trace(
            go.Scatter(
                x=data["timestamp"],
                y=data[col],
                mode="lines",
                name=col.upper(),
                line=dict(color=color, width=1.2),
            ),
            row=row_idx, col=1,
        )

        # Add common reference lines for known oscillator types
        col_lower = col.lower()
        if "rsi" in col_lower:
            _add_hline(fig, row_idx, 70, "#EF5350", "dot", "Overbought")
            _add_hline(fig, row_idx, 30, "#26A69A", "dot", "Oversold")
        elif "stoch" in col_lower:
            _add_hline(fig, row_idx, 80, "#EF5350", "dot", "Overbought")
            _add_hline(fig, row_idx, 20, "#26A69A", "dot", "Oversold")

    # ═══════════════════════════════════════════════════════════════════
    # Layout & Styling
    # ═══════════════════════════════════════════════════════════════════
    symbol = metrics.get("symbol", "")
    total_return = metrics.get("total_return_pct", 0)
    total_trades = metrics.get("total_trades", 0)
    win_rate = metrics.get("win_rate_pct", 0)
    sharpe = metrics.get("sharpe_ratio", 0)

    title_text = (
        f"<b>Backtest Results</b>"
        f"{'  —  ' + symbol if symbol else ''}"
        f"  |  Return: {total_return:+.2f}%"
        f"  |  Trades: {total_trades}"
        f"  |  Win Rate: {win_rate:.1f}%"
        f"  |  Sharpe: {sharpe:.2f}"
    )

    fig.update_layout(
        title=dict(text=title_text, x=0.01, font=dict(size=14)),
        template="plotly_dark",
        height=250 + (total_rows * 150),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
            font=dict(size=10),
        ),
        hovermode="x unified",
        dragmode="pan",
        xaxis_rangeslider_visible=False,
        margin=dict(l=60, r=30, t=80, b=40),
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#16213e",
        font=dict(color="#e0e0e0", family="Segoe UI, sans-serif"),
    )

    # Style all x-axes and y-axes
    for i in range(1, total_rows + 1):
        xaxis_key = f"xaxis{i}" if i > 1 else "xaxis"
        yaxis_key = f"yaxis{i}" if i > 1 else "yaxis"

        fig.update_layout(**{
            xaxis_key: dict(
                gridcolor="rgba(255,255,255,0.05)",
                showgrid=True,
                zeroline=False,
            ),
            yaxis_key: dict(
                gridcolor="rgba(255,255,255,0.05)",
                showgrid=True,
                zeroline=False,
                side="right",
            ),
        })

    # Add range selector buttons to the bottom x-axis
    bottom_xaxis = f"xaxis{total_rows}"
    fig.update_layout(**{
        bottom_xaxis: dict(
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1D", step="day", stepmode="backward"),
                    dict(count=5, label="5D", step="day", stepmode="backward"),
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(step="all", label="All"),
                ],
                bgcolor="#0f3460",
                activecolor="#533483",
                font=dict(color="#e0e0e0"),
            ),
            type="date",
        ),
    })

    # ═══════════════════════════════════════════════════════════════════
    # Write to HTML
    # ═══════════════════════════════════════════════════════════════════
    chart_html = fig.to_html(
        include_plotlyjs=True,
        full_html=False,
        config={
            "scrollZoom": True,
            "displayModeBar": True,
            "modeBarButtonsToAdd": ["drawline", "eraseshape"],
        },
    )

    metrics_html = _generate_metrics_html(metrics)

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Backtest Results</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #1a1a2e;
                color: #e0e0e0;
                margin: 0;
                padding: 20px;
            }}
            .container {{
                max-width: 1400px;
                margin: 0 auto;
            }}
            .metrics-container {{
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                margin-top: 20px;
                margin-bottom: 30px;
            }}
            .metric-card {{
                background-color: #16213e;
                border-radius: 8px;
                padding: 15px;
                flex: 1;
                min-width: 280px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            }}
            .metric-card h3 {{
                margin-top: 0;
                color: #42A5F5;
                border-bottom: 1px solid #0f3460;
                padding-bottom: 10px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }}
            td {{
                padding: 6px 0;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }}
            td:last-child {{
                text-align: right;
                font-weight: bold;
                color: #ffffff;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            {chart_html}
            {metrics_html}
        </div>
    </body>
    </html>
    """

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"\nInteractive chart saved to: {output_path}")


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _add_trade_markers(fig, trades: list, row: int, col: int):
    """
    Adds entry and exit markers for each trade on the candlestick chart.
    Draws connecting lines between entry and exit of each trade.
    Color-codes by P&L: green for winners, red for losers.
    """
    # Separate entries and exits
    entry_times, entry_prices, entry_hovers, entry_colors, entry_symbols = [], [], [], [], []
    exit_times, exit_prices, exit_hovers, exit_colors, exit_symbols = [], [], [], [], []

    for t in trades:
        is_winner = t["net_pnl"] > 0
        pnl_color = "#26A69A" if is_winner else "#EF5350"
        pnl_sign = "+" if t["net_pnl"] >= 0 else ""

        # Entry marker
        entry_times.append(t["entry_time"])
        entry_prices.append(t["entry_price"])
        entry_colors.append(pnl_color)

        if t["side"] == "long":
            entry_symbols.append("triangle-up")
            entry_label = "BUY"
        else:
            entry_symbols.append("triangle-down")
            entry_label = "SHORT"

        entry_hovers.append(
            f"<b>{entry_label}</b><br>"
            f"Price: ₹{t['entry_price']:,.2f}<br>"
            f"Qty: {t['quantity']}<br>"
            f"Time: {t['entry_time']}"
        )

        # Exit marker
        exit_times.append(t["exit_time"])
        exit_prices.append(t["exit_price"])
        exit_colors.append(pnl_color)

        if t["side"] == "long":
            exit_symbols.append("triangle-down")
            exit_label = "SELL"
        else:
            exit_symbols.append("triangle-up")
            exit_label = "COVER"

        exit_hovers.append(
            f"<b>{exit_label}</b> ({t['exit_reason']})<br>"
            f"Price: ₹{t['exit_price']:,.2f}<br>"
            f"Qty: {t['quantity']}<br>"
            f"P&L: {pnl_sign}₹{t['net_pnl']:,.2f}<br>"
            f"Time: {t['exit_time']}"
        )

        # Draw a line connecting entry to exit
        fig.add_trace(
            go.Scatter(
                x=[t["entry_time"], t["exit_time"]],
                y=[t["entry_price"], t["exit_price"]],
                mode="lines",
                line=dict(
                    color=pnl_color,
                    width=1,
                    dash="dot",
                ),
                opacity=0.4,
                showlegend=False,
                hoverinfo="skip",
            ),
            row=row, col=col,
        )

    # Entry markers (single scatter for all entries)
    fig.add_trace(
        go.Scatter(
            x=entry_times,
            y=entry_prices,
            mode="markers",
            name="Entry",
            marker=dict(
                symbol=entry_symbols,
                size=12,
                color=entry_colors,
                line=dict(width=1, color="#ffffff"),
            ),
            text=entry_hovers,
            hovertemplate="%{text}<extra></extra>",
        ),
        row=row, col=col,
    )

    # Exit markers (single scatter for all exits)
    fig.add_trace(
        go.Scatter(
            x=exit_times,
            y=exit_prices,
            mode="markers",
            name="Exit",
            marker=dict(
                symbol=exit_symbols,
                size=10,
                color=exit_colors,
                line=dict(width=1, color="#ffffff"),
            ),
            text=exit_hovers,
            hovertemplate="%{text}<extra></extra>",
        ),
        row=row, col=col,
    )


def _add_hline(fig, row: int, y_value: float, color: str,
               dash: str = "dot", label: str = ""):
    """Adds a horizontal reference line to a specific subplot row."""
    fig.add_hline(
        y=y_value,
        line_dash=dash,
        line_color=color,
        line_width=0.8,
        opacity=0.5,
        annotation_text=label,
        annotation_position="top left",
        annotation_font_size=9,
        annotation_font_color=color,
        row=row, col=1,
    )

def _generate_metrics_html(metrics: dict) -> str:
    """Generates an HTML dashboard for the backtest metrics."""
    def _format_val(val, is_pct=False, is_currency=False):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return "N/A"
        if isinstance(val, (int, float)):
            if is_pct:
                return f"{val:.2f}%"
            elif is_currency:
                return f"₹{val:,.2f}"
            elif isinstance(val, float):
                return f"{val:.2f}"
        return str(val)

    groups = {
        "Return": [
            ("Total Return", metrics.get("total_return_pct"), True, False),
            ("CAGR", metrics.get("cagr_pct"), True, False),
            ("Alpha", metrics.get("alpha_pct"), True, False),
        ],
        "Risk": [
            ("Max Drawdown", metrics.get("max_drawdown_pct"), True, False),
            ("Max DD Duration", metrics.get("max_drawdown_duration"), False, False),
            ("Volatility (Ann.)", metrics.get("volatility_annualized_pct"), True, False),
            ("Downside Dev.", metrics.get("downside_deviation_pct"), True, False),
            ("Calmar Ratio", metrics.get("calmar_ratio"), False, False),
        ],
        "Risk-Adjusted": [
            ("Sharpe Ratio", metrics.get("sharpe_ratio"), False, False),
            ("Sortino Ratio", metrics.get("sortino_ratio"), False, False),
            ("Omega Ratio", metrics.get("omega_ratio"), False, False),
        ],
        "Trade-Level": [
            ("Total Trades", metrics.get("total_trades"), False, False),
            ("Win Rate", metrics.get("win_rate_pct"), True, False),
            ("Loss Rate", metrics.get("loss_rate_pct"), True, False),
            ("Average Win", metrics.get("average_win"), False, True),
            ("Average Loss", metrics.get("average_loss"), False, True),
            ("Win/Loss Ratio", metrics.get("win_loss_ratio"), False, False),
            ("Profit Factor", metrics.get("profit_factor"), False, False),
            ("Expectancy", metrics.get("expectancy"), False, True),
            ("Largest Win", metrics.get("largest_win"), False, True),
            ("Largest Loss", metrics.get("largest_loss"), False, True),
            ("Average Holding Period", metrics.get("average_holding_period"), False, False),
            ("Max Consecutive Wins", metrics.get("max_consecutive_wins"), False, False),
            ("Max Consecutive Losses", metrics.get("max_consecutive_losses"), False, False),
        ],
        "Cost & Execution": [
            ("Total Commission", metrics.get("total_commission_paid"), False, True),
            ("Total Slippage", metrics.get("total_slippage_cost"), False, True),
            ("Return After Costs", metrics.get("return_after_costs"), False, True),
            ("Cost % of Gross", metrics.get("cost_as_pct_of_gross_return"), True, False),
        ]
    }

    html = '<div class="metrics-container">'
    for group_name, items in groups.items():
        html += f'<div class="metric-card"><h3>{group_name}</h3><table>'
        for label, val, is_pct, is_currency in items:
            formatted_val = _format_val(val, is_pct, is_currency)
            # Color coding for negative vs positive where applicable
            color_style = ""
            neutral_labels = {"Total Trades", "Max DD Duration", "Average Holding Period", "Win/Loss Ratio", "Profit Factor"}
            bad_if_positive_labels = {"Max Drawdown", "Loss Rate", "Total Commission", "Total Slippage", "Max Consecutive Losses", "Downside Dev.", "Volatility (Ann.)"}
            
            if isinstance(val, (int, float)) and label not in neutral_labels:
                if val < 0:
                    color_style = "color: #EF5350;" # Red
                elif val > 0:
                    if label in bad_if_positive_labels or "Loss" in label:
                        color_style = "color: #EF5350;" # Red for bad things that are positive numbers
                    else:
                        color_style = "color: #26A69A;" # Green for good things
                    
            html += f'<tr><td>{label}</td><td style="{color_style}">{formatted_val}</td></tr>'
        html += '</table></div>'
    html += '</div>'
    
    return html
