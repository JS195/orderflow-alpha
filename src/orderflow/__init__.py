"""Top-level package for orderflow-alpha."""

from importlib.metadata import version as _version, PackageNotFoundError as _PackageNotFoundError
from .features import (
    FEATURES,
    build_dataset,
    default_layout,
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
    "build_dataset",
    "default_layout",
    "FEATURES",
    "build_order_flow_chart",
    "create_ohlcv_figure",
]