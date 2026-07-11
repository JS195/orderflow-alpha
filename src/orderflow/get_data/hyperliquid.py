import requests
import pandas as pd
import time
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

from . import _coinalyze

# Official public "Info" endpoint - a single POST route dispatched by a
# "type" field, not a REST-per-resource API like the other exchanges.
# https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
BASE_URL = "https://api.hyperliquid.xyz/info"

# Features this source can never provide, no matter the symbol/window/API
# key - features.build_dataset skips these silently instead of raising, as
# opposed to a supported feature returning empty for a real reason (bad
# symbol, missing COINALYZE_API_KEY, data outside retention).
UNSUPPORTED = frozenset({"spot_cvd"})


def _post(body: dict, max_retries: int = 6) -> requests.Response:
    """POST with backoff on 429s. Info requests share an aggregated weight
    budget of 1200/min per IP - a single build_dataset call already fires
    several of these concurrently (one per stream per warmup day), enough
    to trip it if anything else on the same IP has been calling the API too."""
    for attempt in range(max_retries):
        resp = requests.post(BASE_URL, json=body)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        time.sleep(float(resp.headers.get("Retry-After", 0)) or 0.5 * (attempt + 1))
    resp.raise_for_status()
    return resp


def fetch(streams: dict, symbol: str, dates: list, max_workers: int = 8) -> dict:
    """Matches the Binance signature."""
    tasks = [(name, fn, d) for name, fn in streams.items() for d in dates]
    frames = {name: [] for name in streams}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as ex:
        for name, df in ex.map(lambda t: (t[0], t[1](symbol, t[2])), tasks):
            if not df.empty:
                frames[name].append(df)

    return {
        name: pd.concat(dfs).sort_index() if dfs else pd.DataFrame()
        for name, dfs in frames.items()
    }


def _day_bounds_ms(date: str) -> tuple[int, int]:
    start = pd.Timestamp(date, tz="UTC")
    return int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000)


def get_mark_price_klines(symbol: str, date: str, interval: str = "5m") -> pd.DataFrame:
    """OHLC candles for a perp, e.g. symbol='BTC' (Hyperliquid coins have no
    quote-currency suffix - not 'BTCUSDT' or 'BTC-USDT-SWAP', just 'BTC').

    POST /info {"type": "candleSnapshot", "req": {coin, interval, startTime,
    endTime}}. This is traded price, not a distinct mark-price series -
    Hyperliquid's public API doesn't expose one separately from candles the
    way the other three exchanges do. A full day at 5m is 289 candles in a
    single request (verified live), no pagination needed.
    """
    start_ts, end_ts = _day_bounds_ms(date)
    resp = _post({
        "type": "candleSnapshot",
        "req": {"coin": symbol, "interval": interval, "startTime": start_ts, "endTime": end_ts},
    })
    candles = resp.json()
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df["open_time"] = pd.to_numeric(df["t"])
    df = df.set_index("open_time").sort_index()
    df.index = pd.to_datetime(df.index, unit="ms")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def get_premium_index_klines(symbol: str, date: str) -> pd.DataFrame:
    """The actual mark-vs-oracle premium (fractional) - not an index price -
    since features._funding averages and clamps `close` as if it were
    already the premium, the same shape as Binance's premiumIndexKlines.

    POST /info {"type": "fundingHistory", "coin", "startTime", "endTime"}
    gives Hyperliquid's real settled premium/funding directly (no need to
    reconstruct it from mark/index candles the way OKX does). Hyperliquid
    only settles/reports this hourly though (not every 8h like the other
    three exchanges, and not every ~30-90s like OKX's own premium ticks) -
    upsampled onto a 1-min grid (same as okx.py) before returning, so
    features._funding's rolling smoother has a real point at every step and
    produces a value at every 5-min output bucket instead of one real point
    per hour and NaN elsewhere. The smoothing still only has 8 genuinely
    distinct inputs per 8h window (each just repeated ~60x), but the
    rolling weighted average blends them into a continuously-evolving line
    rather than a stepped one - and critically, this also means the funding
    column no longer has gaps that null out other exchanges' real values
    when aggregated together in build_dataset (source={...} with multiple
    exchanges just adds the columns).

    Resampled to 1-min (Hyperliquid's own timestamps land a few tens of ms
    past the hour, not exactly on it, so this also snaps them onto a clean
    grid) then reindexed onto the full calendar day before ffilling - each
    day is fetched separately, so ffilling only between this day's own
    first/last update leaves the last ~59 minutes empty (nothing later in
    that same day's own frame to ffill from), which reappears as a gap once
    days are concatenated.
    """
    start_ts, end_ts = _day_bounds_ms(date)
    resp = _post({"type": "fundingHistory", "coin": symbol, "startTime": start_ts, "endTime": end_ts})
    rows = resp.json()
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_numeric(df["time"])
    df = df.set_index("ts").sort_index()
    df.index = pd.to_datetime(df.index, unit="ms")
    df["close"] = df["premium"].astype(float)
    full_day = pd.date_range(pd.Timestamp(date), periods=24 * 60, freq="1min")
    return df[["close"]].resample("1min").last().reindex(full_day).ffill()


def _coinalyze_symbol(symbol: str) -> str:
    """'BTC' -> 'BTC.H' - Coinalyze's own per-exchange symbol suffix for
    Hyperliquid, from /v1/future-markets (symbol_on_exchange='BTC' maps to
    symbol='BTC.H' for exchange code 'H')."""
    return f"{symbol}.H"


def get_oi(symbol: str, date: str) -> pd.DataFrame:
    """Hyperliquid's own public API only exposes *current* OI (a live
    snapshot via metaAndAssetCtxs), not a queryable history, and the only
    official historical source is a paid, requester-pays S3 archive - not
    used here. This comes from Coinalyze (api.coinalyze.net) instead, a free
    third-party aggregator that retains Hyperliquid OI at ~7-8 days/5min,
    ~85 days/1hour, indefinitely/daily (verified live) - see _coinalyze.py.
    Requires a free COINALYZE_API_KEY environment variable; if unset, this
    returns an empty DataFrame (same as any other unsupported feature)."""
    start_ts, end_ts = _day_bounds_ms(date)
    return _coinalyze.get_oi(_coinalyze_symbol(symbol), start_ts // 1000, end_ts // 1000)


def futures_agg_trades(symbol: str, date: str) -> pd.DataFrame:
    """Taker buy/sell delta, from Coinalyze (see get_oi's docstring for why -
    Hyperliquid's own public API has no market-wide historical trades
    endpoint at all, only a single user's fills and live-only recentTrades)."""
    start_ts, end_ts = _day_bounds_ms(date)
    df = _coinalyze.get_taker_volume(_coinalyze_symbol(symbol), start_ts // 1000, end_ts // 1000)
    if not df.empty:
        df["fut_cumulative_volume_delta"] = df["volume_delta"].cumsum()
    return df


def spot_agg_trades(symbol: str, date: str) -> pd.DataFrame:
    """Hyperliquid perps only for this module - no spot CVD."""
    return pd.DataFrame()
