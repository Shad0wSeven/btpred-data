# Binance BTC/FDUSD and BTC options data

Downloaded from the public [Binance data archive](https://data.binance.vision/).
All files remain compressed ZIP archives exactly as provided by Binance; each ZIP contains one CSV file.

## Spot (`spot/`)

`BTCFDUSD-1m-2026-04.zip` through `BTCFDUSD-1m-2026-06.zip` contain one-minute BTC/FDUSD spot candlesticks for April, May, and June 2026.  The CSV fields are Binance kline fields: open time, open, high, low, close, volume, close time, quote volume, trade count, taker-buy base volume, taker-buy quote volume, and ignore.

## Options (`options/`)

Historical BTC options data is provided for 2023-07-01 through 2023-09-30:

- `BTCUSDT-EOHSummary-*.zip`: BTC options end-of-hour summaries (one file per date).
- `BTCBVOLUSDT-BVOLIndex-*.zip`: BTC Binance Volatility Index observations (one file per date).

The EOH archive does not contain 2023-09-08 through 2023-09-18 or 2023-09-25, so there are 80 EOH files rather than 92. The BVOL index series is complete (92 files).

Source paths:

- `data/spot/monthly/klines/BTCFDUSD/1m/`
- `data/option/daily/EOHSummary/BTCUSDT/`
- `data/option/daily/BVOLIndex/BTCBVOLUSDT/`

To inspect a file without extracting it permanently:

```sh
unzip -p spot/BTCFDUSD-1m-2026-06.zip | head
unzip -p options/BTCUSDT-EOHSummary-2023-07-01.zip | head
```
