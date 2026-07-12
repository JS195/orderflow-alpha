import requests
import pandas as pd
from datetime import timedelta
import time
from concurrent.futures import ThreadPoolExecutor

from . import _coinalyze

BASE_URL = "https://www.okx.com"


def fetch(streams: dict, symbol: str, dates: list, max_workers: int = 4) -> dict:
    """Matches the Binance signature. Lower default max_workers than Binance's
    32 - OKX's public endpoints are rate-limited around 20 req/2s."""
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


def _base_ccy(symbol: str) -> str:
    """'BTC-USDT-SWAP' / 'BTC-USDT' -> 'BTC', for the ccy-keyed rubik stat endpoints."""
    return symbol.split("-")[0]


def _coinalyze_symbol(symbol: str) -> str:
    """'BTC-USDT-SWAP' -> 'BTCUSDT_PERP.3' - Coinalyze's own code for an OKX
    perpetual (exchange suffix '.3'), confirmed against /v1/future-markets
    for BTC; assumed to generalize the same way for other USDT perpetuals."""
    return symbol.replace("-SWAP", "").replace("-", "") + "_PERP.3"


def _get_json(url: str, params: dict, max_retries: int = 6) -> dict:
    """GET with backoff on 429s - OKX's public endpoints cap around 20 req/2s
    and an unhandled 429 used to kill the whole fetch."""
    for attempt in range(max_retries):
        resp = requests.get(url, params=params)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp.json()
        wait = float(resp.headers.get("Retry-After", 0)) or 0.5 * (attempt + 1)
        time.sleep(wait)
    resp.raise_for_status()
    return resp.json()


def _paginate(url: str, params: dict, start_ts: int, end_ts: int, ts_of) -> list:
    """Pages an OKX v5 list endpoint backward via its "after" cursor, seeded at
    end_ts so pagination starts inside the requested day instead of walking
    back from the live head of the feed - for an old date that's the
    difference between ~15 requests and hundreds."""
    params = {**params, "after": str(end_ts)}
    rows = []
    while True:
        data = _get_json(url, params).get("data") or []
        if not data:
            break
        rows += [r for r in data if start_ts <= ts_of(r) < end_ts]
        oldest = ts_of(data[-1])
        if oldest <= start_ts:
            break
        params["after"] = str(oldest)
        time.sleep(0.12)
    return rows


def _fetch_okx_candles(endpoint: str, inst_id: str, date: str, bar: str = "1m") -> pd.DataFrame:
    start_ts, end_ts = _day_bounds_ms(date)
    rows = _paginate(f"{BASE_URL}{endpoint}", {"instId": inst_id, "bar": bar, "limit": "100"},
                      start_ts, end_ts, lambda r: int(r[0]))
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = ["open_time", "open", "high", "low", "close", "volume"]
    df["open_time"] = pd.to_numeric(df["open_time"])
    df = df.set_index("open_time").sort_index()
    # Naive UTC index, matching binance.py / bybit.py.
    df.index = pd.to_datetime(df.index, unit="ms")
    return df.astype(float)


# OKX's rubik/stat endpoints only retain 5-min granularity for a short
# rolling window (~2 days), falling back to coarser 1H/1D beyond that.
# Used for SPOT only (see _taker_volume) - CONTRACTS/futures OI and
# taker-volume come from Coinalyze exclusively instead (see get_oi): OKX's
# futures endpoints are USD notional while Coinalyze is coins-denominated,
# and blending the two with a price conversion left a visible discontinuity
# right at the boundary, so it's simpler to just not mix them.
_RUBIK_COVERAGE_THRESHOLD = 0.8
_RUBIK_COARSE_PERIODS = (("1H", 3_600_000), ("1D", 86_400_000))


def _rubik_stat(url: str, base_params: dict, start_ts: int, end_ts: int) -> list:
    params = {**base_params, "period": "5m", "begin": start_ts, "end": end_ts}
    data = _get_json(url, params).get("data") or []
    return sorted(data, key=lambda row: int(row[0]))


def _rubik_stat_coarse(url: str, base_params: dict, start_ts: int, end_ts: int) -> list:
    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    span_ms = max(0, min(end_ts, now_ms) - start_ts)
    by_ts = {}
    for period, bucket_ms in _RUBIK_COARSE_PERIODS:
        params = {**base_params, "period": period, "begin": start_ts, "end": end_ts}
        for row in _get_json(url, params).get("data") or []:
            by_ts.setdefault(int(row[0]), row)
        if len(by_ts) >= _RUBIK_COVERAGE_THRESHOLD * max(1, span_ms // bucket_ms):
            break
    return [by_ts[ts] for ts in sorted(by_ts)]


def _rubik_rows_to_df(rows: list, columns: list) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["open_time", *columns])
    df["open_time"] = pd.to_numeric(df["open_time"])
    df = df.set_index("open_time").sort_index()
    df.index = pd.to_datetime(df.index, unit="ms")
    return df.astype(float)


def _needs_supplement(df: pd.DataFrame, start_ts: int, end_ts: int) -> bool:
    """True if native 5m coverage falls short of a full grid for the elapsed
    portion of the window - i.e. it's worth falling back to the coarser
    1H/1D tiers."""
    now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    span_ms = max(0, min(end_ts, now_ms) - start_ts)
    expected = max(1, span_ms // 300_000)
    return len(df) < _RUBIK_COVERAGE_THRESHOLD * expected


def _taker_volume(symbol: str, date: str, inst_type: str) -> pd.DataFrame:
    """Buy/sell taker volume. SPOT comes from OKX's own rubik stats (the raw
    trade tape has no time-range params, so this pre-aggregated split is the
    practical source), falling back to the coarser 1H/1D tiers once native
    5m runs out. CONTRACTS (futures) comes from Coinalyze instead - see
    get_oi for why."""
    start_ts, end_ts = _day_bounds_ms(date)

    if inst_type == "CONTRACTS":
        df = _coinalyze.get_taker_volume(_coinalyze_symbol(symbol), start_ts // 1000, end_ts // 1000)
    else:
        url = f"{BASE_URL}/api/v5/rubik/stat/taker-volume"
        base_params = {"ccy": _base_ccy(symbol), "instType": inst_type}
        cols = ["sell_volume", "buy_volume"]
        df = _rubik_rows_to_df(_rubik_stat(url, base_params, start_ts, end_ts), cols)
        if _needs_supplement(df, start_ts, end_ts):
            coarse = _rubik_rows_to_df(_rubik_stat_coarse(url, base_params, start_ts, end_ts), cols)
            if not coarse.empty:
                df = df.combine_first(coarse) if not df.empty else coarse

    if df.empty:
        return df
    df["volume_delta"] = df["buy_volume"] - df["sell_volume"]
    return df


def get_mark_price_klines(symbol: str, date: str) -> pd.DataFrame:
    """Mark price candles. Expects a swap instId, e.g. 'BTC-USDT-SWAP'."""
    return _fetch_okx_candles("/api/v5/market/history-mark-price-candles", symbol, date)


def get_premium_index_klines(symbol: str, date: str) -> pd.DataFrame:
    """The actual mark-vs-index premium (fractional, e.g. -0.00043) - not the
    index price - since features._funding averages and clamps `close` as if
    it were already the premium, the same shape as Binance's premiumIndexKlines."""
    start_ts, end_ts = _day_bounds_ms(date)
    rows = _paginate(f"{BASE_URL}/api/v5/public/premium-history", {"instId": symbol, "limit": "100"},
                      start_ts, end_ts, lambda r: int(r["ts"]))
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_numeric(df["ts"])
    df = df.set_index("ts").sort_index()
    df.index = pd.to_datetime(df.index, unit="ms")
    df["close"] = df["premium"].astype(float)

    # Premium snapshots land irregularly (~30-90s apart) - put them on a
    # clean 1-min grid to match the evenly-spaced klines features._funding expects.
    return df[["close"]].resample("1min").last().ffill()


def futures_agg_trades(symbol: str, date: str) -> pd.DataFrame:
    """Taker buy/sell delta for Perpetual Swaps ('BTC-USDT-SWAP')."""
    df = _taker_volume(symbol, date, "CONTRACTS")
    if not df.empty:
        df["fut_cumulative_volume_delta"] = df["volume_delta"].cumsum()
    return df


def spot_agg_trades(symbol: str, date: str) -> pd.DataFrame:
    """Taker buy/sell delta for Spot markets ('BTC-USDT')."""
    df = _taker_volume(symbol, date, "SPOT")
    if not df.empty:
        df["spot_cumulative_volume_delta"] = df["volume_delta"].cumsum()
    return df


def get_oi(symbol: str, date: str) -> pd.DataFrame:
    """Historical open interest, in coins (base asset, e.g. BTC). Sourced
    entirely from Coinalyze - OKX's own native endpoint is USD notional, so
    blending native with the Coinalyze supplement meant a unit conversion
    and a visible seam right at that boundary. Same approach as
    hyperliquid.py, which has no native OI source at all. Requires a free
    COINALYZE_API_KEY environment variable; returns empty if unset."""
    start_ts, end_ts = _day_bounds_ms(date)
    return _coinalyze.get_oi(_coinalyze_symbol(symbol), start_ts // 1000, end_ts // 1000)
