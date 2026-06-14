"""Feature layer: turn raw get_data.py streams into a chart/analysis-ready frame.

The public entry point is ``build_dataset`` — give it a symbol, a time window, a
timeframe and the list of features you want, and it returns a single tidy
DataFrame on a common index. Each feature also knows how it should be drawn, so
``build_dataset`` attaches a default chart layout (``df.attrs["layout"]``) inferred
from the features you asked for; ``build_order_flow_chart`` picks that up
automatically. Pass an explicit ``config`` to customise.

Add a new queryable feature by adding one entry to ``FEATURES``.
"""

import numpy as np
import pandas as pd

from .get_data import (
    fetch,
    futures_agg_trades,
    get_mark_price_klines,
    get_oi,
    get_premium_index_klines,
    spot_agg_trades,
)


# Preprocessing helpers
def _ohlc(df, timeframe):
    return df.resample(timeframe).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )


def _open_interest(df, timeframe):
    return df["sum_open_interest"].resample(timeframe).last()


def _futures_cvd(df, timeframe):
    # Continuous CVD: per-bar taker delta summed, then a single cumsum (no
    # per-day reset). build_dataset rebases it to 0 at the left edge of the view.
    return (
        df["volume_delta"].resample(timeframe).sum().cumsum()
        .rename("fut_cumulative_volume_delta")
    )


def _spot_cvd(df, timeframe):
    return (
        df["volume_delta"].resample(timeframe).sum().cumsum()
        .rename("spot_cumulative_volume_delta")
    )


def _funding(df, timeframe):
    # Smooth (predicted) funding rate from the 1m premium index, matching the
    # continuous line aggregators like velo.xyz show:
    #   F = P_avg + clamp(I - P_avg, -0.05%, +0.05%)
    # where P_avg is a linear time-weighted premium average over the 8h window.
    I = 0.0001  # 0.01% per 8h interest rate — BTC/ETH; other coins differ
    step = df.index.to_series().diff().median()
    n = int(pd.Timedelta("8h") / step)
    w = np.arange(1, n + 1)
    p_avg = df["close"].rolling(n).apply(lambda x: x @ w / w.sum(), raw=True)
    funding_rate = p_avg + (I - p_avg).clip(-0.0005, 0.0005)
    return (funding_rate * 3 * 365).resample(timeframe).last().rename(
        "funding_rate_annualized"
    )


# feature name -> how to fetch it, preprocess it, and draw it 
# Each "panel" is the default chart spec consumed by build_order_flow_chart.
# Pick any subset of these in build_dataset(..., features=[...]).
# Easily add new features at any point
FEATURES = {
    "ohlc": {
        "fetch": get_mark_price_klines,
        "preprocess": _ohlc,
        "panel": {"type": "candlestick", "title": "Price",
                  "name": "Price", "y_title": "Price (USDT)"},
    },
    "oi": {
        "fetch": get_oi,
        "preprocess": _open_interest,
        "panel": {"type": "line", "title": "Open Interest", "column": "sum_open_interest",
                  "name": "Open Interest", "color": "purple", "y_title": "OI"},
    },
    "funding": {
        "fetch": get_premium_index_klines,
        "preprocess": _funding,
        "warmup": "8h",
        "panel": {"type": "delta_bars", "title": "Funding Rate", "column": "funding_rate_annualized",
                  "name": "Funding", "color": "orange", "y_title": "Rate"},
    },
    "fut_cvd": {
        "fetch": futures_agg_trades,
        "preprocess": _futures_cvd,
        "panel": {"type": "delta_bars", "title": "Futures CVD", "column": "fut_cumulative_volume_delta",
                  "name": "Futures Delta", "y_title": "Delta"},
    },
    "spot_cvd": {
        "fetch": spot_agg_trades,
        "preprocess": _spot_cvd,
        "panel": {"type": "delta_bars", "title": "Spot CVD", "column": "spot_cumulative_volume_delta",
                  "name": "Spot Delta", "y_title": "Delta"},
    },
}


def default_layout(features):
    panels = [dict(FEATURES[f]["panel"]) for f in features if f in FEATURES]
    panels.sort(key=lambda p: 0 if p["type"] == "candlestick" else 1)
    return panels


def build_dataset(symbol, start, end, timeframe="5min", features=None):
    features = list(FEATURES) if features is None else list(features)
    start, end = pd.Timestamp(start), pd.Timestamp(end)

    # Warm-up is per-feature: go back far enough to cover the largest lookback any
    # requested feature declares (e.g. funding's 8h rolling window). Features with
    # no "warmup" need none, so a query without them fetches no extra days.
    # We only execute a lookback if one of the features demands it. This is so we can go back in future perhaps with we need moving averages or something
    lookback = max(
        (pd.Timedelta(FEATURES[name].get("warmup", 0)) for name in features),
        default=pd.Timedelta(0),
    )
    dates = [
        d.strftime("%Y-%m-%d")
        for d in pd.date_range((start - lookback).normalize(), end.normalize(), freq="D")
    ]

    streams = {name: FEATURES[name]["fetch"] for name in features}
    raw = fetch(streams, symbol, dates)

    columns = [FEATURES[name]["preprocess"](raw[name], timeframe) for name in features]
    df = pd.concat(columns, axis=1).loc[start.floor(timeframe):end]

    # We anchor the CVD at 0. This is not ideal but we can't endlessly go back. We care more about the shape and what its doing anyways.
    for col in [c for c in df.columns if "cumulative_volume_delta" in c]:
        df[col] = df[col] - df[col].dropna().iloc[0]

    # Connect data -> chart: stash what was requested and how to draw it.
    df.attrs["features"] = features
    df.attrs["layout"] = default_layout(features)
    return df
