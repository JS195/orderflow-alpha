# orderflow-alpha

An active research project focused on extracting predictive alpha signals from cryptocurrency market microstructure using machine learning.

This repository contains Phase 1 of the project: a high-performance data engineering pipeline designed to pull raw Binance data and transform it into clean, time-aligned features (price, open interest, funding, and cumulative volume delta).

Phase 1 has so far eliminated data-wrangling friction so that Phase 2 (feature engineering, model training, and signal extraction) can run on a synchronised, arbitrary timeframe historical dataset.

Phase 3 will be sizing and risk.

## Project Roadmap & Status

### Phase 1: Data Pipeline (Complete)
- **Concurrent Ingestion:** Pulls daily data directly from Binance's public archive (`data.binance.vision`)—klines, mark price, premium index, and open-interest metrics—alongside settled funding from the REST API. Requests run concurrently to eliminate serial bottlenecks.
- **Feature Reconstruction:** Computes advanced structural features required for predictive modeling:
  - **CVD (Spot + Futures):** Reconstructed as a continuous series across arbitrary time windows without arbitrary per-day resets.
  - **Predicted Funding Rate:** Reconstructed as a smooth, high-resolution time-weighted average price (TWAP) derived from the 1m premium index, mirroring continuous line aggregators rather than delayed 8-hour settled steps.
  - **Index Realignment:** Data streams align on one time index.

| Source | Feature | Limitation | Verified |
| :--- | :--- | :--- | :--- |
| Binance | all | none | static archive, full history since inception |
| OKX | oi, fut_cvd, spot_cvd | 5-min data only ~2 days back, 1H only ~3-4 days, degrades to daily beyond that | tested repeatedly this session |
| OKX | ohlc, funding | none | bar-based candles, full history |
| Bybit | fut_cvd/spot_cvd | none in depth — verified public trade dumps exist back to Jan 2025 (likely further). Only a speed cost (full-day tick-tape CSV download per day) | just verified |
| Coinbase | spot_cvd | none in depth — verified 1 year back still works. Only a speed cost (100 trades/page cap) | just verified |
| Hyperliquid | ohlc | capped at ~5000 most recent candles per interval — ~17 days at 5-min, but ~208 days at 1-hour, ~13+ years at daily | just verified live (boundary is between 15-20 days at 5m; 60 days back works fine at 1h) |
| Hyperliquid | funding | none — tested 800+ days back, still works | just verified |
| Hyperliquid | oi | not available at all historically — only a live current snapshot exists via the free public API | confirmed against official SDK source |
| Hyperliquid | fut_cvd | not available at all historically — no market-wide historical trades endpoint exists free; only live-only recentTrades and per-user fills | confirmed against official SDK source |

### Phase 2: ML & Signal Research (In Progress / Next Step)
- ML to exploit order-flow imbalances, funding discrepancies, and multi-venue CVD regimes.

### Phase 3: Sizing, risk, testing.

---

## Quick start
To use the feature gathering part:

This is not on PyPI yet. Clone and install editable:

```bash
pip install -e .
```

Then see script.ipynb in notebooks for usage examples.

---

## Current available features

| feature    | what you get                        |
|------------|-------------------------------------|
| `ohlc`     | price candles (mark price)          |
| `oi`       | open interest                       |
| `funding`  | smooth predicted funding rate       |
| `fut_cvd`  | futures cumulative volume delta     |
| `spot_cvd` | spot cumulative volume delta        |

## A couple of notes / caveats

- All timestamps are **UTC**. If a chart looks shifted by an hour vs. another site, it's almost certainly that site rendering in your local timezone.
- CVD's are anchored to 0 at the left edge of your window. Its the shape and direction that matters and these are correct. The absolute level will depend on where you start accumulating.
- The smooth funding rate is a reconstruction from premium. Matches the funding rate on velo.xyz.

## Status

Early and evolving — APIs may shift around as the analysis side takes shape. Currently a research/personal project. See `LICENSE` for terms.