import requests
import pandas as pd
from datetime import timedelta
import time
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "https://api.bybit.com"


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
    return int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000) - 1


def _get_json(url: str, params: dict, max_retries: int = 6) -> dict:
    """GET with backoff on 429s."""
    for attempt in range(max_retries):
        resp = requests.get(url, params=params)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp.json()
        wait = float(resp.headers.get("Retry-After", 0)) or 0.5 * (attempt + 1)
        time.sleep(wait)
    resp.raise_for_status()
    return resp.json()


def _paginate(endpoint: str, params: dict, start_ts: int, end_ts: int, ts_of,
              start_key: str = "start", end_key: str = "end") -> list:
    """Bybit's v5 market endpoints page newest-first with no "after" cursor,
    only a start/end window - so walk `end` backward a page at a time until
    the oldest row in a page reaches start_ts. The window param names differ
    per endpoint (klines use start/end, open-interest uses startTime/endTime)
    - get the name wrong and Bybit silently ignores the window and just
    returns its latest page every time, which never converges."""
    url = f"{BASE_URL}/v5/market/{endpoint}"
    rows = []
    current_end = end_ts
    while current_end > start_ts:
        page = {**params, start_key: start_ts, end_key: current_end}
        res = _get_json(url, page)
        data = res["result"]["list"] if res.get("retCode") == 0 else []
        if not data:
            break
        rows += data
        oldest = ts_of(data[-1])
        if oldest <= start_ts:
            break
        current_end = oldest - 1
        time.sleep(0.1)
    return rows


def _klines(symbol: str, date: str, endpoint: str, interval: str = "1") -> pd.DataFrame:
    start_ts, end_ts = _day_bounds_ms(date)
    rows = _paginate(endpoint, {"category": "linear", "symbol": symbol, "interval": interval, "limit": 1000},
                      start_ts, end_ts, lambda r: int(r[0]))
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close"])
    df["open_time"] = pd.to_numeric(df["open_time"])
    df = df.set_index("open_time").sort_index()
    df.index = pd.to_datetime(df.index, unit="ms")
    return df.astype(float)


def get_mark_price_klines(symbol: str, date: str, interval: str = "1") -> pd.DataFrame:
    """Mark price candles. Bybit's linear perpetual symbol format, e.g. 'BTCUSDT'."""
    return _klines(symbol, date, "mark-price-kline", interval)


def get_premium_index_klines(symbol: str, date: str, interval: str = "1") -> pd.DataFrame:
    """Actual mark-vs-index premium (fractional, e.g. -0.00033) - already the
    shape features._funding expects for `close`, not an index price to convert."""
    return _klines(symbol, date, "premium-index-price-kline", interval)


def get_oi(symbol: str, date: str, interval: str = "5min") -> pd.DataFrame:
    start_ts, end_ts = _day_bounds_ms(date)
    rows = _paginate("open-interest", {"category": "linear", "symbol": symbol, "intervalTime": interval, "limit": 200},
                      start_ts, end_ts, lambda r: int(r["timestamp"]), start_key="startTime", end_key="endTime")
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_numeric(df["timestamp"])
    df = df.set_index("timestamp").sort_index()
    df.index = pd.to_datetime(df.index, unit="ms")
    df["sum_open_interest"] = df["openInterest"].astype(float)
    return df[["sum_open_interest"]]


# Bybit's kline endpoints don't split taker buy/sell, so CVD comes from the
# public daily tick-tape dump instead. Linear and spot are separate archives
# with different filenames, size columns and timestamp units - not just a
# different URL prefix, so each needs its own reader, not one guesser.
_TRADE_ARCHIVES = {
    "linear": ("https://public.bybit.com/trading/{s}/{s}{d}.csv.gz", "size", "s"),
    "spot": ("https://public.bybit.com/spot/{s}/{s}_{d}.csv.gz", "volume", "ms"),
}


def _taker_volume(symbol: str, date: str, category: str) -> pd.DataFrame:
    """The linear tape is a full day of tick-by-tick trades for a liquid pair
    (tens of millions of rows) - parsing only the 3 columns we actually use
    (instead of the other 8: symbol, tickDirection, trdMatchID, grossValue,
    homeNotional, foreignNotional, RPI) skips most of pandas' per-column
    allocation and type-conversion work on top of the unavoidable download."""
    url_fmt, size_col, unit = _TRADE_ARCHIVES[category]
    cols = ["timestamp", "side", size_col]
    try:
        df = pd.read_csv(url_fmt.format(s=symbol, d=date), compression="gzip", usecols=cols,
                          dtype={"timestamp": "float64", "side": "str", size_col: "float64"})
    except Exception:
        return pd.DataFrame()

    side = df["side"].str.lower()
    size = df[size_col].astype(float)

    # Building straight from these Series with index=ts would align by the
    # rows' original integer labels vs. ts's datetime *values*, which never
    # match - every row silently becomes NaN and resample().sum() turns that
    # into a false all-zero result. Attach ts positionally instead.
    out = pd.DataFrame({"buy_volume": (side == "buy") * size, "sell_volume": (side == "sell") * size})
    out.index = pd.to_datetime(df["timestamp"].astype(float), unit=unit).values
    out = out.sort_index().resample("5min").sum()
    out["volume_delta"] = out["buy_volume"] - out["sell_volume"]
    return out


def futures_agg_trades(symbol: str, date: str) -> pd.DataFrame:
    """Taker buy/sell delta for USDT perpetuals ('BTCUSDT', category=linear)."""
    df = _taker_volume(symbol, date, "linear")
    if not df.empty:
        df["fut_cumulative_volume_delta"] = df["volume_delta"].cumsum()
    return df


def spot_agg_trades(symbol: str, date: str) -> pd.DataFrame:
    """Taker buy/sell delta for Spot markets ('BTCUSDT')."""
    df = _taker_volume(symbol, date, "spot")
    if not df.empty:
        df["spot_cumulative_volume_delta"] = df["volume_delta"].cumsum()
    return df


def get_bookDepth(symbol, date):
    """Bybit doesn't provide free historical order-book depth."""
    return pd.DataFrame()
