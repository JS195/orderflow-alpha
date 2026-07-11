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
| OKX | oi, fut_cvd | native OKX data only covers ~2 days back at 5-min. Beyond that, goes straight to a free Coinalyze supplement (set `COINALYZE_API_KEY`) for genuine 5-min resolution out to ~7-8 days, ~85 days/1hour, indefinite/daily — deliberately skips OKX's own coarser native 1H/1D tiers in favour of Coinalyze's finer ones. Only degrades to OKX's own 1H/1D as a last resort if no key is set | tested repeatedly this session, incl. no-key fallback and multi-day-old dates confirmed at true 5-min resolution via Coinalyze |
| OKX | spot_cvd | 5-min data only ~2 days back, 1H only ~3-4 days, degrades to daily beyond that — no Coinalyze supplement (its OKX spot symbol mapping isn't verified) | tested repeatedly this session |
| OKX | ohlc, funding | none | bar-based candles, full history |
| Bybit | fut_cvd/spot_cvd | none in depth — verified public trade dumps exist back to Jan 2025 (likely further). Only a speed cost (full-day tick-tape CSV download per day) | just verified |
| Coinbase | spot_cvd | Coinbase's own ticker endpoint never matched velo.xyz's Coinbase-only spot CVD chart, even after correcting its maker-side field to taker side (confirmed correct via docs + tick rule) — root cause of that mismatch was never found, so `spot_cvd` now sources buy/sell volume from a free Coinalyze supplement instead (set `COINALYZE_API_KEY`; empty if unset), same as OKX/Hyperliquid's `oi`/`fut_cvd`. Coinalyze's own classification for this market was independently checked with the tick rule (~63% positive correlation between price direction and volume-delta sign, vs. Coinbase's own ~2x *anti*-correlation) and looks correctly oriented; full velo comparison still pending, and history depth follows Coinalyze's own tiers (~7-8 days/5min, ~85 days/1hour, indefinite/daily) rather than Coinbase's own ~1 year | tick-rule check passed; end-to-end velo comparison not yet done |
| Hyperliquid | ohlc | capped at ~5000 most recent candles per interval — ~17 days at 5-min, but ~208 days at 1-hour, ~13+ years at daily | just verified live (boundary is between 15-20 days at 5m; 60 days back works fine at 1h) |
| Hyperliquid | funding | none — tested 800+ days back, still works | just verified |
| Hyperliquid | oi, fut_cvd | not available from Hyperliquid's own API at all historically — only a live current snapshot exists via the free public API, and no market-wide historical trades endpoint exists free (only live-only recentTrades and per-user fills). Sourced entirely from the free Coinalyze supplement instead (~7-8 days/5min, ~85 days/1hour, indefinite/daily); errors clearly if `COINALYZE_API_KEY` is unset rather than returning empty/garbage data | confirmed against official SDK source; Coinalyze path tested this session, full 5-min resolution confirmed multiple days back |

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

Optional: for extended OKX `oi`/`fut_cvd` history, any Hyperliquid `oi`/`fut_cvd` at all, and Coinbase `spot_cvd`, get a free key at https://coinalyze.net/account/api-key/ and set it as `COINALYZE_API_KEY` in your environment. Everything else works without it. If running through a Jupyter kernel in VS Code, make sure VS Code is actually configured to pass environment variables through to the kernel — a var exported in your shell isn't automatically visible there otherwise.

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