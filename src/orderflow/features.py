import numpy as np
import pandas as pd

from .get_data import binance, okx, bybit, coinbase

SOURCES = {
    "binance": binance,
    "okx": okx,
    "bybit": bybit,
    "coinbase": coinbase,
}


# Preprocessing helpers
def _ohlc(df, timeframe):
    return df.resample(timeframe).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )


def _open_interest(df, timeframe):
    s = df["sum_open_interest"].resample(timeframe).last()
    full_index = pd.date_range(s.index.min().floor("D"), s.index.max(), freq=timeframe)
    return s.reindex(full_index).interpolate("time", limit_direction="both")


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
        "fetch": "get_mark_price_klines",
        "preprocess": _ohlc,
        "panel": {"type": "candlestick", "title": "Price",
                  "name": "Price", "y_title": "Price (USDT)"},
    },
    "oi": {
        "fetch": "get_oi",
        "preprocess": _open_interest,
        "panel": {"type": "line", "title": "Open Interest", "column": "sum_open_interest",
                  "name": "Open Interest", "color": "purple", "y_title": "OI"},
    },
    "funding": {
        "fetch": "get_premium_index_klines",
        "preprocess": _funding,
        "warmup": "8h",
        "panel": {"type": "delta_bars", "title": "Funding Rate", "column": "funding_rate_annualized",
                  "name": "Funding", "color": "orange", "y_title": "Rate"},
    },
    "fut_cvd": {
        "fetch": "futures_agg_trades",
        "preprocess": _futures_cvd,
        "panel": {"type": "delta_bars", "title": "Futures CVD", "column": "fut_cumulative_volume_delta",
                  "name": "Futures Delta", "y_title": "Delta"},
    },
    "spot_cvd": {
        "fetch": "spot_agg_trades",
        "preprocess": _spot_cvd,
        "panel": {"type": "delta_bars", "title": "Spot CVD", "column": "spot_cumulative_volume_delta",
                  "name": "Spot Delta", "y_title": "Delta"},
    },
}


def default_layout(features):
    panels = [dict(FEATURES[f]["panel"]) for f in features if f in FEATURES]
    panels.sort(key=lambda p: 0 if p["type"] == "candlestick" else 1)
    return panels


def build_dataset(symbol, start, end, timeframe="5min", features=None, source="binance"):
    if source not in SOURCES:
        raise ValueError(f"Unknown source {source!r}; choose one of {list(SOURCES)}")
    data_module = SOURCES[source]

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

    streams = {name: getattr(data_module, FEATURES[name]["fetch"]) for name in features}
    raw = data_module.fetch(streams, symbol, dates)

    empty = [name for name in features if raw[name].empty]
    if empty:
        raise ValueError(
            f"No data returned for {empty} from source={source!r}, symbol={symbol!r}, "
            f"window={start.date()}..{end.date()}. Check that symbol is in the format this "
            f"source expects (e.g. Binance wants 'BTCUSDT', OKX wants 'BTC-USDT-SWAP')."
        )

    columns = [FEATURES[name]["preprocess"](raw[name], timeframe) for name in features]
    df = pd.concat(columns, axis=1).loc[start.floor(timeframe):end]

    # We anchor the CVD at 0. This is not ideal but we can't endlessly go back. We care more about the shape and what its doing anyways.
    for col in [c for c in df.columns if "cumulative_volume_delta" in c]:
        df[col] = df[col] - df[col].dropna().iloc[0]

    df.attrs["features"] = features
    df.attrs["layout"] = default_layout(features)
    return df
