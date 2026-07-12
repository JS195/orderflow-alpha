# orderflow-alpha

An active research project focused on extracting predictive alpha signals from cryptocurrency market microstructure using machine learning.

This repository is Phase 1: a data engineering pipeline that pulls order-flow data from five exchanges (Binance, OKX, Bybit, Coinbase, Hyperliquid) and turns it into clean, time-aligned features - price, open interest, funding, and cumulative volume delta. Any subset of exchanges can be aggregated together in one call.

Phase 1 has so far eliminated data-wrangling friction so that Phase 2 (feature engineering, model training, and signal extraction) can run on a synchronised, arbitrary timeframe historical dataset.

Phase 3 will be sizing and risk.

## Project Roadmap & Status

### Phase 1: Data Pipeline (Complete)
- **Multi-exchange, aggregatable:** `source` is an `{exchange: symbol}` dict - one entry pulls a single exchange, several get summed together (e.g. `{"binance": "BTCUSDT", "bybit": "BTCUSDT"}`), same as an "aggregate" view on velo.xyz.
- **Concurrent ingestion:** each exchange module fetches its own days/streams in parallel.
- **Feature reconstruction:**
  - **CVD (Spot + Futures):** a continuous series across arbitrary time windows, no arbitrary per-day resets.
  - **Predicted Funding Rate:** smoothed from the premium index (TWAP over the funding window) rather than shown as delayed settlement steps.
  - **Index Realignment:** every stream lands on one shared time index.

| Source | Feature | Limitation | Verified |
| :--- | :--- | :--- | :--- |
| Binance | all | none | static archive, full history since inception |
| OKX | oi, fut_cvd | sourced entirely from Coinalyze (set `COINALYZE_API_KEY`), not OKX's own endpoint - OKX reports these in USD, everyone else in coins, and blending the two left a visible seam at the boundary. Retention follows Coinalyze's tiers: ~7-8 days/5min, ~85 days/1hour, indefinite/daily | tested this session, incl. no-key error path |
| OKX | spot_cvd | 5-min only ~2 days back, degrading to daily beyond ~4 days - no Coinalyze fallback (its OKX spot symbol mapping isn't verified) | tested this session |
| OKX | ohlc, funding | none | full history |
| Bybit | fut_cvd/spot_cvd | none in depth - public trade dumps exist back to Jan 2025 at least. Just a speed cost (full-day tick-tape download per day) | verified |
| Coinbase | spot_cvd | Coinbase's own ticker endpoint never matched velo.xyz even after correcting its maker-side field to taker side - root cause never found, so this sources from Coinalyze instead. History depth follows Coinalyze's tiers, shorter than Coinbase's own ~1 year | Coinalyze's own classification checked out via the tick rule; full velo comparison still pending |
| Hyperliquid | ohlc | capped at ~5000 candles/interval - ~17 days at 5-min, ~208 days at 1-hour, 13+ years at daily | verified live |
| Hyperliquid | funding | none - tested 800+ days back | verified |
| Hyperliquid | oi, fut_cvd | no history in Hyperliquid's own API at all (live snapshot only) - sourced from Coinalyze | confirmed against official SDK source |

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

Optional: for OKX `oi`/`fut_cvd`, Hyperliquid `oi`/`fut_cvd`, and Coinbase `spot_cvd`, get a free key at https://coinalyze.net/account/api-key/ and set it as `COINALYZE_API_KEY` in your environment. Everything else works without it. If running through a Jupyter kernel in VS Code, make sure VS Code is actually configured to pass environment variables through to the kernel — a var exported in your shell isn't automatically visible there otherwise.

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