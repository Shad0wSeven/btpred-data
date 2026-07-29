# Granular Binance market data

## What Binance publishes historically

The public spot archive publishes both `trades` and `aggTrades`. The `trades`
files are the more granular choice: each row is an individual fill with trade
ID, price, base quantity, quote quantity, microsecond event time,
`isBuyerMaker`, and `isBestMatch`. The existing `ticks/` archives are
`aggTrades`, which combine fills from the same taker order at the same price.

Binance does not publish historical spot price-level L2 snapshots or diff
messages in the public archive. True spot L2 must be recorded live by joining a
REST depth snapshot to the 100 ms WebSocket diff-depth stream.

USD-M futures do publish a historical dataset named `bookDepth`. Despite the
name, it is not a price-level order book. Each second it reports cumulative
depth and notional at percentage bands around the market:

```text
timestamp,percentage,depth,notional
2026-07-26 00:00:01,-0.20,464.27300000,29840157.15020000
2026-07-26 00:00:01,0.20,551.14300000,35498436.04110000
```

It is useful for spread-side liquidity, order-book imbalance, liquidity shocks,
and volatility-regime features.

## Data included in this repository

- `granular/spot_raw_trades/`: BTCFDUSD individual spot fills for April through
  June 2026 (monthly archives) and July 1 through July 27, 2026 (daily
  archives): 30 ZIPs containing 11,284,968 fills.
- `granular/futures_um_book_depth/`: BTCUSDT USD-M perpetual one-second depth
  curves for July 1 through July 27, 2026: 27 ZIPs containing 932,823 rows.
- `granular/manifest.json`: source URL, byte size, SHA-256 digest, and ZIP member
  name for every archive.

The 57 archives total 172,103,114 compressed bytes. All ZIPs are unchanged from
Binance, verified against Binance's published SHA-256 checksums, and stored with
Git LFS.

Reproduce or verify the download:

```sh
python scripts/download_granular_data.py
```

## Recording true spot L2

Install the one additional dependency and run a capture:

```sh
python -m pip install -r requirements-data.txt
python scripts/capture_spot_l2.py --symbol BTCFDUSD --seconds 3600
```

The recorder writes a gzip-compressed JSON Lines file containing the initial
5,000-level snapshot followed by every 100 ms diff event and a local
nanosecond receive timestamp. It detects sequence gaps and reconnects with a
fresh snapshot. Use `--seconds 0` for a continuous capture.

The output is intentionally ignored by Git until it has been reviewed. Move a
completed capture into a tracked dataset directory before committing it.

### Continuous three-hour publishing

On macOS, install the background recorder:

```sh
scripts/install_l2_launch_agent.sh
```

The LaunchAgent maintains a continuous connection, closes a capture every three
hours, validates the gzip stream, and pushes the completed file to
`granular/spot_l2/`. It uses a dedicated lightweight checkout under
`~/Library/Application Support/btpred-l2/` so it does not interfere with
interactive work in this repository, an isolated Python environment, and a
runtime copy outside macOS's protected Documents directory. The service
reconnects with a fresh snapshot after a WebSocket sequence gap or network
interruption.

Inspect its state and logs:

```sh
launchctl print gui/$UID/com.btpred.l2capture
tail -f "$HOME/Library/Application Support/btpred-l2/runtime/capture.log"
tail -f "$HOME/Library/Application Support/btpred-l2/runtime/capture.error.log"
```

Each capture is stored with Git LFS. At approximately the activity rate observed
in the initial test, expect tens of megabytes per three-hour chunk, although
market activity can make files materially larger. This consumes GitHub LFS
storage and download bandwidth continuously.

## Modeling features

For a 15-minute probability model, align all features strictly before the
prediction timestamp. Useful additions include:

- signed trade flow using `isBuyerMaker`;
- trade count, volume, VWAP, and large-trade share over 1 s to 15 min windows;
- bid/ask depth imbalance at each percentage band;
- changes in total depth and depth slope;
- liquidity-adjusted realized volatility;
- interactions between trade-flow pressure, depth imbalance, and volatility
  regime.

Evaluate with rolling, purged time splits. Report Brier score, log loss, and
calibration by volatility/liquidity regime so that gains are not caused by
look-ahead leakage or one unusually easy month.
