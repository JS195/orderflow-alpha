"""Top-level package for orderflow-alpha."""

from importlib.metadata import version as _version, PackageNotFoundError as _PackageNotFoundError
from .get_data import (
    download_zip_in_memory,
    futures_agg_trades,
    get_bookDepth,
    get_mark_price_klines,
    get_oi,
    get_premium_index_klines,
    spot_agg_trades,
)
from .visualisation import (
    build_order_flow_chart,
    create_ohlcv_figure,
)

__author__ = """Joshua Smith"""
__email__ = "josh.smith195@outlook.com"

try:
    __version__ = _version("orderflow-alpha")
except _PackageNotFoundError:
    __version__ = "unknown"

# Explicitly declare the clean public interface for the quant package
__all__ = [
    "download_zip_in_memory",
    "get_oi",
    "get_bookDepth",
    "get_premium_index_klines",
    "get_mark_price_klines",
    "futures_agg_trades",
    "spot_agg_trades",
    "build_order_flow_chart",
    "create_ohlcv_figure",
    "add_candlestick",
    "add_delta_bars",
    "add_line",
]