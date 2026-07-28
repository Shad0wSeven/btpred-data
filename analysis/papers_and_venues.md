# BTC options research notes and venue choice

## Practical venue choice

**Binance** is the cleanest starting point for this project because its public archive supplies point-in-time hourly BTC option summaries (mark price, mark IV, bid/ask IV, Greeks and open interest), BTC spot bars, and perpetual-futures funding.  Its options are European-style and cash-settled, making Black--Scholes an appropriate *quoting convention* for extracting IV.

**Deribit** is the natural next venue for a more liquid, execution-oriented study. The 2024 study below describes Deribit as dominating BTC-option volume and open interest in its sample. Deribit's public API exposes current option IV fields and historical volatility; its older option-chain snapshots generally require collection or a specialist data vendor for a rigorous point-in-time backtest. This makes Binance archival data preferable for the first reproducible experiment and Deribit preferable for a live collector.

## What the literature suggests measuring

1. [Ariane Chevallier, David I. Harvey & Stefano D. Massacci, *Implied volatility estimation of bitcoin options and the stylized facts of option pricing* (2021)](https://pmc.ncbi.nlm.nih.gov/articles/PMC8418903/) documents a BTC volatility smile and maturity-dependent behavior. It motivates extracting ATM IV, 25-delta risk reversal (put IV minus call IV), and term structure rather than treating one IV as “the” volatility.
2. [Hou, Wang, Chen & Härdle, *Pricing Cryptocurrency Options* (2020)](https://arxiv.org/abs/2009.11007) finds that jump/co-jump dynamics matter for BTC option values. That is a warning against interpreting Black--Scholes as a literal BTC data-generating process; use it to normalize prices into an implied-vol surface.
3. [Chen, Deng & Nie, *Implied volatility slopes and jumps in bitcoin options market* (2024)](https://www.sciencedirect.com/science/article/pii/S0167637724000713) links IV-slope changes to positive and negative jumps after controls for buying pressure. This supports adding spot jump indicators, option-flow/open-interest changes, and funding to a surface-change model.
4. [Atanasova, Miao, Segarra & Willeboordse, *What Do Crypto Options Tell Us?* (2026 working paper)](https://papers.ssrn.com/sol3/Delivery.cfm/6410838.pdf?abstractid=6410838&mirid=1&type=2) focuses on arbitrage-consistent risk-neutral distributions and variance-risk-premium measures, rather than trying to forecast raw returns directly. This is the more ambitious second stage once the surface data are clean.

## Recommended next tests

- **Variance risk premium:** compare 7/30-day ATM implied variance with subsequent realized variance; do not use the later realized window when forming the signal.
- **Skew and crash risk:** regress next-week downside realized volatility or return-jump indicators on 25-delta risk reversal, controlling for current realized vol and funding.
- **Term structure:** test whether near-minus-medium ATM IV predicts the subsequent change in realized vol, not the BTC price level.
- **Perp/options link:** test whether extreme funding and a steep put skew co-occur, then whether the relation reverses after funding resets.

None of these are trading rules until bid/ask, fees, contract multiplier, fill assumptions, and a strictly point-in-time universe are included.
