import plotly.graph_objects as go
from plotly.subplots import make_subplots

# TradingView light theme (Pine Script built-in colours)
TV_BG = "#FFFBF5"
TV_GRID = "#E0E3EB"
TV_TEXT = "#131722"
TV_CANDLE_UP = "#2196F3"  # color.blue
TV_CANDLE_DOWN = "#F23645"  # color.red


def create_ohlcv_figure(n_rows=4, row_heights=None, subplot_titles=None, height=900, title_text=""):
    """
    Initialise a multi-panel Plotly figure with shared x-axis.

    Returns the figure object ready for traces to be added.
    """
    row_heights = row_heights or [0.4, 0.2, 0.2, 0.2]
    subplot_titles = subplot_titles or ("Price", "Open Interest", "Fut Cum Vol Delta", "Spot Cum Vol Delta")

    specs = [[{"type": "candlestick"}]] + [[{"type": "xy"}]] * (n_rows - 1)

    fig = make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
        specs=specs,
    )

    fig.update_layout(
        height=height,
        title_text=title_text,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_rangeslider_visible=False,
        plot_bgcolor=TV_BG,
        paper_bgcolor=TV_BG,
        font_color=TV_TEXT,
    )
    fig.update_xaxes(gridcolor=TV_GRID, zerolinecolor=TV_GRID)
    fig.update_yaxes(gridcolor=TV_GRID, zerolinecolor=TV_GRID)

    return fig


def add_candlestick(fig, df, row=1, name="Price"):
    """Add an OHLC candlestick trace to the figure."""
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=name,
            increasing_line_color=TV_CANDLE_UP,
            increasing_fillcolor=TV_CANDLE_UP,
            decreasing_line_color=TV_CANDLE_DOWN,
            decreasing_fillcolor=TV_CANDLE_DOWN,
        ),
        row=row,
        col=1,
    )
    fig.update_xaxes(showticklabels=False, row=row, col=1)
    fig.update_yaxes(title_text="Price (USDT)", row=row, col=1)


def add_line(fig, df, column, row, name, color="purple", width=2, y_title=""):
    """Add a simple line trace to the specified panel."""
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df[column],
            name=name,
            line=dict(color=color, width=width),
        ),
        row=row,
        col=1,
    )
    fig.update_xaxes(showticklabels=False, row=row, col=1)
    if y_title:
        fig.update_yaxes(title_text=y_title, row=row, col=1)


def add_delta_bars(fig, df, column, row, name, y_title=""):
    """
    Add a bar trace coloured green/red based on positive/negative values.
    Intended for cumulative volume delta panels.
    """
    colors = df[column].apply(lambda x: "green" if x > 0 else "red")
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df[column],
            name=name,
            marker_color=colors,
        ),
        row=row,
        col=1,
    )
    if y_title:
        fig.update_yaxes(title_text=y_title, row=row, col=1)


def build_order_flow_chart(df, date, symbol="BTCUSDT", timeframe="5min"):
    """
    Top-level convenience function: forward-fills the dataframe and
    builds the complete 4-panel order-flow chart.

    Parameters
    ----------
    df      : pd.DataFrame  – combined OHLCV + OI + delta dataframe
    date    : str           – date label used in the chart title
    symbol  : str
    timeframe : str

    Returns
    -------
    fig : plotly.graph_objects.Figure
    """
    df = df.ffill()

    fig = create_ohlcv_figure(
        title_text=f"{symbol} Order Flow - {timeframe} | {date}",
    )

    add_candlestick(fig, df, row=1)
    add_line(
        fig, df,
        column="sum_open_interest",
        row=2,
        name="Open Interest Coins",
        color="purple",
        y_title="Open Interest Coins",
    )
    add_delta_bars(
        fig, df,
        column="spot_cumulative_volume_delta",
        row=3,
        name="Spot Vol Delta (Buy - Sell)",
        y_title="Spot Volume Coins Delta",
    )
    add_delta_bars(
        fig, df,
        column="8h_avg",
        row=4,
        name="Futures Vol Delta (Buy - Sell)",
        y_title="Futures Volume Coins Delta",
    )

    return fig
