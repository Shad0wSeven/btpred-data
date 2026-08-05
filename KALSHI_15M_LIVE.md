# Live Kalshi BTC 15-minute data

The `KXBTC15M` recorder discovers the currently active BTC 15-minute market,
then stores one snapshot per second and every observed public execution. Each
snapshot includes the contract's BRTI-derived floor strike, expiry time,
Kalshi YES bid/ask, and up to 100 levels on each side of the binary order book.

```sh
python scripts/capture_kalshi_15m.py --seconds 3600
```

Continuous three-hour collection and publishing is installed with:

```sh
scripts/install_kalshi_15m_launch_agent.sh
```

This runs separately from the BTC perp/BRTI collector. Join contract snapshots
to the one-second BRTI anchors using their local receive timestamps; join
subsecond estimated BRTI values to raw 15-minute executions using their source
event timestamps.
