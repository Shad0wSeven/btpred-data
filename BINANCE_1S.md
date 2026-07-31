# Dense Binance BTCFDUSD one-second bars

`spot_1s/` contains Binance's native one-second BTCFDUSD spot klines from
January 1 through July 29, 2026. These are not minute bars expanded or
interpolated into seconds.

The verified snapshot contains:

- 18,144,000 consecutive one-second rows;
- zero missing or duplicate seconds;
- 13,188,795 explicit zero-trade rows;
- 102,832,722 underlying trades summarized by the bars;
- 35 source archives totaling 270,442,396 compressed bytes.

Every UTC second has exactly one row, including seconds with no trades. A
zero-trade row carries the unchanged market price with zero volume and a zero
trade count. Each row has the standard Binance kline fields:

1. open time in microseconds;
2. open, high, low, and close;
3. base volume;
4. close time in microseconds;
5. quote volume;
6. trade count;
7. taker-buy base and quote volume;
8. ignore.

The six complete months from January through June use monthly ZIP archives.
July 1 through July 29 use daily archives because the July monthly archive is
not yet complete. Every archive remains byte-for-byte identical to Binance,
is verified against Binance's published SHA-256 checksum, and is stored with
Git LFS.

Reproduce and validate the dataset:

```sh
python scripts/download_binance_1s.py
```

The downloader rejects an archive unless it has the expected UTC endpoints,
one row per second, no gaps, no duplicate timestamps, twelve columns per row,
a valid ZIP CRC, and the official Binance SHA-256 digest.

Use `spot_1s/manifest.json` for exact coverage, row counts, no-trade seconds,
trade totals, source URLs, byte sizes, and per-file checksums.
