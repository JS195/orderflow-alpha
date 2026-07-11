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