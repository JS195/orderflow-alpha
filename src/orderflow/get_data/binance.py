import requests
import zipfile
import io
import pandas as pd
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

def fetch(streams: dict, symbol: str, dates: list, max_workers: int = 32) -> dict:
    tasks = [(name, fn, d) for name, fn in streams.items() for d in dates]
    frames = {name: [] for name in streams}
    
    with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as ex:
        for name, df in ex.map(lambda t: (t[0], t[1](symbol, t[2])), tasks):
            if not df.empty:
                frames[name].append(df)

    result = {}
    for name, dfs in frames.items():
        if dfs:
            result[name] = pd.concat(dfs).sort_index()
        else:
            result[name] = pd.DataFrame()

    return result

def download_zip_in_memory(url: str, header="infer") -> pd.DataFrame:
    resp = requests.get(url)
    if resp.status_code == 404:
        # The public archive occasionally has a one-off missing day (verified
        # live, e.g. 2026-06-29's markPriceKlines while every neighboring day
        # is fine) - same "no data for this day" case as any other source's
        # empty-day convention, not worth failing a whole multi-day fetch over.
        return pd.DataFrame()
    resp.raise_for_status()
    zip_bytes = io.BytesIO(resp.content)

    with zipfile.ZipFile(zip_bytes) as z:
        csv_name = [f for f in z.namelist() if f.endswith('.csv')][0]
        with z.open(csv_name) as f:
            df = pd.read_csv(f, parse_dates=False, header=header)

    return df


def get_oi(symbol: str, date: str) -> pd.DataFrame:
    url = f"https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{date}.zip"
    df = download_zip_in_memory(url)
    if df.empty:
        return df
    df = df.set_index('create_time')
    df.index = pd.to_datetime(df.index)
    return df

def get_bookDepth(symbol, date) -> pd.DataFrame:
    url = f"https://data.binance.vision/data/futures/um/daily/bookDepth/{symbol}/{symbol}-bookDepth-{date}.zip"
    df = download_zip_in_memory(url)
    df = df.set_index('timestamp')
    df.index = pd.to_datetime(df.index)
    return df

def get_premium_index_klines(symbol: str, date: str, interval: str = "1m") -> pd.DataFrame:
    url = f"https://data.binance.vision/data/futures/um/daily/premiumIndexKlines/{symbol}/{interval}/{symbol}-{interval}-{date}.zip"
    df = download_zip_in_memory(url)
    if df.empty:
        return df
    df = df.set_index('open_time')
    df.index = pd.to_datetime(df.index, unit='ms')
    return df

def get_mark_price_klines(symbol: str, date: str, interval: str = "1m") -> pd.DataFrame:
    url = f"https://data.binance.vision/data/futures/um/daily/markPriceKlines/{symbol}/{interval}/{symbol}-{interval}-{date}.zip"
    df = download_zip_in_memory(url)
    if df.empty:
        return df
    df = df.set_index('open_time')
    df.index = pd.to_datetime(df.index, unit='ms')
    return df

def futures_agg_trades(symbol: str, date: str) -> pd.DataFrame:
    url = f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/5m/{symbol}-5m-{date}.zip"
    df = download_zip_in_memory(url)
    if df.empty:
        return df
    df['buy_volume']  = df['taker_buy_volume']
    df['sell_volume'] = df['volume'] - df["taker_buy_volume"]
    df['volume_delta'] = df['buy_volume'] - df['sell_volume']
    df['fut_cumulative_volume_delta'] = df['volume_delta'].cumsum()
    df = df.set_index('open_time')
    df.index = pd.to_datetime(df.index, unit='ms')
    return df

# Leave this incase I come back and want the settled funding rate but tbh this is kind of dead code now
def get_funding_rate(symbol: str, date: str, annualize: bool = True) -> pd.DataFrame:
    start = pd.Timestamp(date, tz="UTC")
    end = start + timedelta(days=1)

    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    params = {
        "symbol": symbol,
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000) - 1,
        "limit": 1000,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    df = pd.DataFrame(data)
    if df.empty:
        cols = ["funding_rate"] + (["funding_rate_annualized"] if annualize else [])
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="fundingTime"))

    # Floor off the millisecond jitter Binance reports so settlements land
    # exactly on the funding boundary (00:00/08:00/16:00) and align with the
    # 5-min grid when joined into the combined dataframe.
    df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms").dt.floor("s")
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df.set_index("fundingTime").sort_index()

    out = df[["fundingRate"]].rename(columns={"fundingRate": "funding_rate"})

    if annualize:
        # Infer the funding interval (8h for most perps, 4h for some) from the
        # spacing between settlements so annualization stays correct per symbol.
        if len(out) > 1:
            interval_hours = out.index.to_series().diff().median().total_seconds() / 3600
        else:
            interval_hours = 8.0
        periods_per_year = (24 / interval_hours) * 365
        out["funding_rate_annualized"] = out["funding_rate"] * periods_per_year

    return out


def spot_agg_trades(symbol, date):
    url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/5m/{symbol}-5m-{date}.zip"
    # Binance spot kline dumps have NO header row, so read positionally and
    # assign names ourselves; otherwise the first candle is eaten as a header.
    df = download_zip_in_memory(url, header=None)
    if df.empty:
        return df
    cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_asset_volume",
        "number_of_trades",
        "taker_buy_base_asset_volume",
        "taker_buy_quote_asset_volume",
        "ignore"
    ]
    df.columns = cols
    # Guard in case Binance later adds a header row: drop any non-numeric open_time.
    df = df[pd.to_numeric(df['open_time'], errors='coerce').notna()].copy()
    df['open_time'] = df['open_time'].astype('int64')
    df['buy_volume']  = df['taker_buy_base_asset_volume']
    df['sell_volume'] = df['volume'] - df["taker_buy_base_asset_volume"]
    df['volume_delta'] = df['buy_volume'] - df['sell_volume']
    df['spot_cumulative_volume_delta'] = df['volume_delta'].cumsum()
    df = df.set_index('open_time')
    df.index = pd.to_datetime(df.index, unit='us')
    return df