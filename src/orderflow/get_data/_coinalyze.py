"""Shared Coinalyze fallback for open interest and taker buy/sell volume.

Not a registered `source` in features.SOURCES - this is a supplementary data
source other get_data modules pull from to extend their own history, not
something you'd select on its own (Coinalyze doesn't have candles/funding,
so it can't stand in for a whole exchange).

Why this exists: OKX's own OI/taker-volume endpoints only retain ~2 days at
5-min resolution, degrading to daily beyond ~4 days (see okx.py). Hyperliquid
has no historical OI or market-wide trades endpoint at all, free or
otherwise. Coinalyze (api.coinalyze.net) aggregates both exchanges' OI and
buy/sell volume with its own retention tiers - verified live: ~7-8 days at
5min, ~85 days at 1hour, indefinite at daily. For OKX this extends the
useful high-resolution window; for Hyperliquid it's the only source of this
data at all.

Requires a free Coinalyze account (https://coinalyze.net/account/api-key/,
no credit card) - set the key as the COINALYZE_API_KEY environment variable.
Never commit an actual key to this file or anywhere else in the repo.
"""

import requests
import pandas as pd
import os
import time

BASE_URL = "https://api.coinalyze.net/v1"

# Coinalyze's own retention per interval, verified live against real data
# (not documented anywhere) - same idea as okx.py's _RUBIK_PERIODS: try
# finest first, only fall back to a coarser period for whatever gap it
# doesn't cover, so a 10-day-old date still gets full 5-min resolution for
# whichever portion of it was within Coinalyze's 5-min window.
_PERIODS = (("5min", 300), ("1hour", 3600), ("daily", 86400))
_COVERAGE_THRESHOLD = 0.8


def _api_key() -> str:
    try:
        return os.environ["COINALYZE_API_KEY"]
    except KeyError:
        raise RuntimeError(
            "COINALYZE_API_KEY is not set. Get a free key at "
            "https://coinalyze.net/account/api-key/ and set it as an "
            "environment variable before calling this."
        ) from None


def has_api_key() -> bool:
    """Callers (okx.py, hyperliquid.py) check this before reaching for a
    Coinalyze supplement, so an unset key degrades to 'no supplement' rather
    than raising mid-request - Coinalyze is optional/supplementary, not a
    hard dependency of any get_data module."""
    return bool(os.environ.get("COINALYZE_API_KEY"))


def _get(endpoint: str, params: dict, max_retries: int = 6) -> list:
    """GET with backoff on 429s - free tier is 40 requests/min."""
    headers = {"api_key": _api_key()}
    for attempt in range(max_retries):
        resp = requests.get(f"{BASE_URL}/{endpoint}", headers=headers, params=params)
        if resp.status_code != 429:
            resp.raise_for_status()
            data = resp.json()
            return data[0]["history"] if data else []
        time.sleep(float(resp.headers.get("Retry-After", 0)) or 1.5 * (attempt + 1))
    resp.raise_for_status()
    return []


def _history(endpoint: str, symbol: str, start_ts: int, end_ts: int) -> list:
    now_ts = int(pd.Timestamp.now(tz="UTC").timestamp())
    span = max(0, min(end_ts, now_ts) - start_ts)

    by_ts = {}
    for interval, bucket_s in _PERIODS:
        rows = _get(endpoint, {"symbols": symbol, "interval": interval, "from": start_ts, "to": end_ts})
        for row in rows:
            by_ts.setdefault(row["t"], row)
        expected = max(1, span // bucket_s)
        if len(by_ts) >= _COVERAGE_THRESHOLD * expected:
            break

    return [by_ts[t] for t in sorted(by_ts)]


def get_oi(symbol: str, start_ts: int, end_ts: int) -> pd.DataFrame:
    """Open interest. `symbol` is Coinalyze's own code, e.g. 'BTCUSDT_PERP.3'
    (OKX) or 'BTC.H' (Hyperliquid) - see /v1/future-markets for the mapping
    from an exchange's native symbol."""
    if not has_api_key():
        return pd.DataFrame()
    rows = _history("open-interest-history", symbol, start_ts, end_ts)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["t"], unit="s")
    df = df.sort_index()
    # OI history is shaped like an OHLC candle (open/high/low/close of the
    # OI level within each bucket) - close is the OI level at bucket end,
    # matching what a single point-in-time OI reading represents elsewhere.
    df["sum_open_interest"] = df["c"].astype(float)
    return df[["sum_open_interest"]]


def get_taker_volume(symbol: str, start_ts: int, end_ts: int) -> pd.DataFrame:
    """Buy/sell taker volume, from the ohlcv-history endpoint's `bv`
    (buy volume) and `v` (total volume) fields - sell volume is v - bv."""
    if not has_api_key():
        return pd.DataFrame()
    rows = _history("ohlcv-history", symbol, start_ts, end_ts)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["t"], unit="s")
    df = df.sort_index()
    df["buy_volume"] = df["bv"].astype(float)
    df["sell_volume"] = (df["v"].astype(float) - df["bv"].astype(float))
    df["volume_delta"] = df["buy_volume"] - df["sell_volume"]
    return df[["buy_volume", "sell_volume", "volume_delta"]]
