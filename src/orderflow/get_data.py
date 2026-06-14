import requests
import zipfile
import io
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional

BASE_URL = "https://data.binance.vision"

def download_zip_in_memory(url: str) -> pd.DataFrame:
    resp = requests.get(url)
    resp.raise_for_status()
    zip_bytes = io.BytesIO(resp.content)
    
    with zipfile.ZipFile(zip_bytes) as z:
        csv_name = [f for f in z.namelist() if f.endswith('.csv')][0]
        with z.open(csv_name) as f:
            df = pd.read_csv(f, parse_dates=False)
    
    return df


def get_oi(symbol: str, date: str) -> pd.DataFrame:
    url = f"https://data.binance.vision/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{date}.zip"
    df = download_zip_in_memory(url)
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
    df = df.set_index('open_time')
    df.index = pd.to_datetime(df.index, unit='ms')
    return df

def get_mark_price_klines(symbol: str, date: str, interval: str = "1m") -> pd.DataFrame:
    url = f"https://data.binance.vision/data/futures/um/daily/markPriceKlines/{symbol}/{interval}/{symbol}-{interval}-{date}.zip"
    df = download_zip_in_memory(url)
    df = df.set_index('open_time')
    df.index = pd.to_datetime(df.index, unit='ms')
    return df 

def futures_agg_trades(symbol: str, date: str) -> pd.DataFrame:
    url = f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/5m/{symbol}-5m-{date}.zip"
    df = download_zip_in_memory(url)
    df['buy_volume']  = df['taker_buy_volume']
    df['sell_volume'] = df['volume'] - df["taker_buy_volume"]
    df['volume_delta'] = df['buy_volume'] - df['sell_volume']
    df['fut_cumulative_volume_delta'] = df['volume_delta'].cumsum()
    df = df.set_index('open_time')
    df.index = pd.to_datetime(df.index, unit='ms')
    return df

def spot_agg_trades(symbol, date):
    url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/5m/{symbol}-5m-{date}.zip"
    df = download_zip_in_memory(url)
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
    df['buy_volume']  = df['taker_buy_base_asset_volume']
    df['sell_volume'] = df['volume'] - df["taker_buy_base_asset_volume"]
    df['volume_delta'] = df['buy_volume'] - df['sell_volume']
    df['spot_cumulative_volume_delta'] = df['volume_delta'].cumsum()
    df = df.set_index('open_time')
    df.index = pd.to_datetime(df.index, unit='us')
    return df


