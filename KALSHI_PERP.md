# Kalshi BTC perpetual and BRTI capture

Kalshi's public Perps REST API exposes the `KXBTCPERP` market without API
credentials. Its `reference_price` is the CF Benchmarks BRTI scaled by the
contract size. `KXBTCPERP` represents 0.0001 BTC, so a reference price of
`6.2945` corresponds to a BRTI value of `62,945 USD`.

Run a one-hour capture with:

```sh
python scripts/capture_kalshi_perp.py --seconds 3600
```

The gzip JSON Lines output contains:

- one `snapshot` record per second with Kalshi's timestamped BRTI reference
  price, perp bid/ask and last trade, settlement and liquidation marks, and up
  to 100 order-book levels per side;
- every public perp execution observed during the capture, retaining its trade
  ID, timestamp, size, price, and taker side;
- locally derived unscaled USD prices and the perp/reference premium.

The reference price is direct published BRTI data, not an EMA estimate. The
perp mid and settlement mark remain separate fields so their basis to BRTI can
be modeled without contaminating the target.

Public endpoints used:

```text
GET /trade-api/v2/margin/markets/KXBTCPERP
GET /trade-api/v2/margin/markets/KXBTCPERP/orderbook
GET /trade-api/v2/margin/trades?ticker=KXBTCPERP
```

The public REST market snapshot is polled at one second because BRTI is
published once per second. Trades retain their finer source timestamps. Kalshi
also offers a separate authenticated margin WebSocket for every book delta;
that can be added when a read-only Kalshi key is available.

## Subsecond BRTI estimate

The data includes the official one-second BRTI anchors and finer-time perp
trades. Create a causal event-time estimate between anchors with:

```sh
python scripts/estimate_subsecond_brti.py kalshi_perp/KXBTCPERP-....jsonl.gz
```

The estimator smooths the perp microprice with a 250 ms EMA, estimates the
perp-to-BRTI basis with a 30-second EMA using only observed one-second anchors,
and writes one inferred BRTI row for every perp trade or book snapshot. The
output must be used as `brti_estimated`, not as official BRTI.

## Continuous publishing

On macOS, install the three-hour capture and GitHub publishing service:

```sh
scripts/install_kalshi_perp_launch_agent.sh
```

It uses a dedicated checkout under
`~/Library/Application Support/btpred-kalshi-perp/`, so captures and automated
Git operations do not modify an interactive working tree. Inspect it with:

```sh
launchctl print gui/$UID/com.btpred.kalshiperp
tail -f "$HOME/Library/Application Support/btpred-kalshi-perp/runtime/capture.log"
tail -f "$HOME/Library/Application Support/btpred-kalshi-perp/runtime/capture.error.log"
```
