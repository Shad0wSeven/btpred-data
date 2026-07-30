# Kalshi KXBTC15M tick data

Kalshi's public Trade API exposes one record per execution with a market ticker,
microsecond timestamp, price, size, and taker direction. These are event ticks:
multiple trades may occur in one second, and quiet seconds have no raw trade.
They are not historical order-book quote updates.

The `kalshi_ticks/` directory contains two representations for BTC 15-minute
Up/Down markets:

- `KXBTC15M-trades-YYYY-MM-DD.csv.gz`: every raw public trade returned by
  `GET /markets/trades`, preserving its original timestamp and trade ID.
- `KXBTC15M-1s-YYYY-MM-DD.csv.gz`: a dense second-by-second panel for every
  contract. Seconds without a trade have zero count and volume; the most recent
  trade price is forward-filled within that contract only.
- `KXBTC15M-markets-*.csv.gz`: contract metadata, settlement result, strikes,
  open/close times, volume, and open interest.
- `manifest.json`: coverage, row counts, file sizes, and SHA-256 digests.

The one-second table includes per-second OHLC/VWAP, executed contracts, separate
yes/no taker volume, seconds to settlement, and the official market result. The
raw tape should be used whenever exact event ordering matters.

The initial repository snapshot covers three complete UTC days, July 27 through
July 29, 2026:

- 288 complete 15-minute contracts;
- 6,054,392 raw execution ticks;
- 259,200 dense one-second rows (exactly 900 per contract);
- approximately 190 MB compressed.

Reproduce it with:

```sh
python scripts/download_kalshi_ticks.py \
  --start 2026-07-27 \
  --end 2026-07-30
```

The end date is exclusive and dates are UTC.

## Limitation

Kalshi's historical public API provides executions and one-minute candles, not
historical order-book deltas. Real-time ticker, trade, and order-book streams
are available over WebSocket, but the WebSocket connection requires a Kalshi
API key. Credentials must never be committed to this public repository.
