import plotly.graph_objects as go
from plotly.subplots import make_subplots

# TradingView theme constants remains identical...
BG = "#FFFBF5"
GRID = "#E0E3EB"
TEXT = "#131722"
CANDLE_UP = "#2196F3"
CANDLE_DOWN = "#F23645"


def create_ohlcv_figure(n_rows, row_heights=None, subplot_titles=None, height=900, title_text=""):
    """Initialise a multi-panel Plotly figure with dynamic structural rows."""
    if row_heights is None:
        if n_rows == 1:
            row_heights = [1.0]
        else:
            rem_height = 0.6 / (n_rows - 1)
            row_heights = [0.4] + [rem_height] * (n_rows - 1)

    specs = [[{"type": "candlestick"}]] + [[{"type": "xy"}]] * (n_rows - 1)

    fig = make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
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
        plot_bgcolor=BG,
        paper_bgcolor=BG,
        font_color=TEXT,
    )

    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, showticklabels=False)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)

    fig.update_xaxes(showticklabels=True, row=n_rows, col=1)

    return fig

TRACE_MAPPING = {
    "candlestick": lambda fig, df, cfg, row: fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
            name=cfg.get("name", "Price"),
            increasing_line_color=CANDLE_UP, increasing_fillcolor=CANDLE_UP,
            decreasing_line_color=CANDLE_DOWN, decreasing_fillcolor=CANDLE_DOWN
        ), row=row, col=1
    ),
    "line": lambda fig, df, cfg, row: fig.add_trace(
        go.Scatter(
            x=df.index, y=df[cfg["column"]], name=cfg["name"],
            line=dict(color=cfg.get("color", "purple"), width=cfg.get("width", 2))
        ), row=row, col=1
    ),
    "delta_bars": lambda fig, df, cfg, row: fig.add_trace(
        go.Bar(
            x=df.index, y=df[cfg["column"]], name=cfg["name"],
            marker_color=df[cfg["column"]].apply(lambda x: "green" if x > 0 else "red")
        ), row=row, col=1
    )
}


def build_order_flow_chart(df, symbol="BTCUSDT", timeframe="5min", height=900):
    config = df.attrs.get("layout")
    df = df.ffill()

    titles = [panel["title"] for panel in config]
    
    fig = create_ohlcv_figure(
        n_rows=len(config),
        subplot_titles=titles,
        title_text=f"{symbol} Order Flow - {timeframe} | {df.index[0]} -> {df.index[-1]}",
        height=height
    )

    for idx, panel in enumerate(config, start=1):
        trace_type = panel["type"]
        if trace_type in TRACE_MAPPING:
            TRACE_MAPPING[trace_type](fig, df, panel, idx)
            if "y_title" in panel:
                fig.update_yaxes(title_text=panel["y_title"], row=idx, col=1)
        else:
            raise ValueError(f"Unsupported trace configuration type encountered: {trace_type}")

    return fig