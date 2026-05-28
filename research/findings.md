# Research log — macro-regime-monitor

This file is the running log of what we tested, what worked, what failed.

## Hypothesis under test

> When liquidity, valuation, or internal-leadership signals reach historical
> extremes, the forward distribution of SPX returns shifts in a statistically
> meaningful and **decade-stable** way.

The key word is *decade-stable*. Anything that fires only in one regime is
narrative, not signal.

## Method

- Monthly data, expanding-window percentile for each signal (no look-ahead).
- Extreme zone = top decile or bottom decile (≥90% or ≤10% historical percentile).
- Forward horizon: 12-month SPX total return.
- Significance: 2-sided permutation test, 2000 iterations, p-value vs null of no zone effect.
- Stability: per-decade effect size (zone_mean − decade_baseline) in 1990s / 2000s / 2010s / 2020s.

## Findings (as of 2026-05-27)

### Tier 1 — durable across decades

These show consistent sign in 3+ decades with non-trivial magnitude.

- **RUT_SPX_RS LOW** (small caps lagging large caps by 3m RS): `+12pp, +7pp, +5pp, +0pp` across 1990s/2000s/2010s/2020s. 12m forward SPX return is higher than the decade baseline when small caps lag. **Direction is durable**, magnitude fading. Conventional reading: small caps lag at the *start* of a rally — they're a leading indicator of the prior bottom, not a sell signal for the top.

- **SOX_SPX_RS HIGH** (semis leading large caps by 3m RS): `+7pp, +8pp, +7pp` in 1990s/2000s/2020s. Forward SPX returns are reliably *better* when semis are leading. Semis are the canonical risk-on barometer; this confirms the conventional wisdom across decades.

### Tier 2 — mostly directional but with limited decade coverage

- **MARGIN_M2 HIGH** (margin debt ≥90th pct vs M2): `−16pp, −11pp` in 2000s/2010s. Only 7 total observations across 2 decades, but both decades agree on direction. Real warning but small N.

- **MARGIN_M2 LOW**: `+19pp, +8pp` in 2000s/2020s. Buying after deleveraging works — durable in the limited evidence.

- **SOX_SPX_RS LOW** (semis crashing relative to SPX): `−10pp, −8pp` in 2000s/2020s. Real bear signal when semis roll over hard, but N=9 total.

### Tier 3 — regime-dependent (DO NOT use unconditionally)

- **NDX_SPX_RS LOW**: 1990s `+2pp` (did *not* work), 2000s `−9pp` (worked), 2020s `−5pp` (small N). The often-cited "NDX rolling over = warning" finding is a dot-com era artifact. Pre-2000, tech weakness did not predict bad SPX. This signal lives only in the post-dot-com world. Cannot be applied to other regimes.

- **NDX_SPX_RS HIGH**: `−2.7pp, +3.1pp, +20.5pp` across 1990s/2000s/2020s. Direction inconsistent.

- **RUT_SPX_RS HIGH** (small caps blowing off): negative effect in 1990s/2000s/2010s, but **flipped to +6.4pp in 2020s**. Either signal has died or the 2020s cycle isn't complete yet.

- **M2_GROWTH LOW**: `−6.7pp, −3.8pp, +4.9pp, +4.4pp`. Effect flipped sign between 1990s and 2010s. The mean-reversion thesis (slow M2 growth = good fwd return) only holds post-2010.

### Tier 4 — weak / one-time

- **MCAP_M2 HIGH** (Market Cap / M2 ≥90th pct): full-sample p-value of 0.001 with +5pp effect is **driven entirely by the 2000s** decade (`−16.7pp` from the dot-com unwind). 1990s shows no effect, 2020s shows no effect. The "Buffett indicator at extreme" narrative is largely a single-era story.

  **This is important**: the user's original strategy thesis (MCap/M2 extreme = bad equity returns) fails the stability test. The signal is real in one decade only. We're currently in the 2020s, where the same signal has shown ~zero effect.

- **MCAP_M2 LOW**: N=3 total observations, all from one window. Not testable.

### Tier 5 — insufficient data

- **NET_LIQUIDITY** (Fed BS − TGA − RRP): only post-2003 data, effectively one full decade (2010s) of pre-COVID baseline. Cross-decade test not yet possible. Worth tracking but cannot make stability claims yet.

- **M2_GROWTH HIGH**: only one decade had observations in the extreme high zone.

## Current state (as of 2026-04 data)

Signals currently in extreme zones:

| Signal | Percentile | Zone | Tier | Implied direction |
|---|---|---|---|---|
| MCAP_M2 | 100% | HIGH | Tier 4 (WEAK) | "Sell" narrative but signal is dot-com-only |
| MARGIN_M2 | 99% | HIGH | Tier 2 | Bearish, modest evidence |
| SOX_SPX_RS | 99% | HIGH | Tier 1 | **Bullish, durable** |
| NDX_SPX_RS | 93% | HIGH | Tier 3 (regime-dependent) | Inconclusive |

**Honest read**: of the four currently extreme signals, only one is Tier 1 durable (SOX leadership), and it points *bullish*. One is Tier 2 modest-evidence bearish (margin debt). The two most-cited "sell" signals (MCap/M2 + NDX rolling over) failed the stability test.

This is not a clean call. It is a mixed-evidence regime where the most reliable signals lean bullish and the bearish signals are either weak in N or regime-dependent.

## What to ship in the dashboard

- Tier 1 + Tier 2 signals get foreground placement with current values, percentiles, and conditional return tables.
- Tier 3 signals shown as "context" with explicit regime-dependent caveat.
- Tier 4 (MCAP_M2) shown with a tombstone — "popular narrative, failed stability test, current state shown for reference only".
- Tier 5 shown as "tracking" with a note that we need more data to draw conclusions.

This is the honest version. We're not selling a strategy. We're showing what the data actually says about extreme-state forward returns.

## v2 — composite cycle indicator (2026-05-28)

Combined the 4 leadership / leverage signals (MARGIN_M2, NDX_SPX_RS, SOX_SPX_RS, RUT_SPX_RS) into a weighted composite, sign-aligned so that higher composite = more top-warning. Reporting-lag tolerant via 3-month forward fill on individual components, with proportional reweighting when components drop out.

**Validation results** (12-month forward SPX return, 1990-2026, N=355):

| Composite decile | N | Mean | Hit rate | vs. baseline |
|---|---:|---:|---:|---:|
| 0-10% (extreme low) | 14 | **+31.6%** | **100%** | +22.0pp |
| 10-30% | 52 | +17.3% | 85% | +7.6pp |
| 30-50% | 71 | +10.0% | 83% | +0.3pp |
| 50-70% | 85 | +10.4% | 84% | +0.7pp |
| 70-90% | 109 | +6.7% | 73% | -2.9pp |
| 90-100% (extreme high) | 24 | **-10.1%** | **29%** | -19.7pp |

Bootstrap p-value for both extreme deciles vs. full sample: **p<0.001**.

**Per-decade stability of the composite extremes**:
- 1990s: extremes rare (bull market dominated), small effects
- 2000s: huge effects in both directions (top -18.1pp, bot +48.7pp from one observation)
- 2010s: minimal extreme observations (markets compressed)
- 2020s: top -1.2pp, bot +19.1pp — consistent direction with smaller magnitude

**Why this works when individual signals don't always**: the composite captures the *coincidence* of multiple stretched readings. Any single signal can be regime-dependent or have small N at its extreme, but when 3 of 4 components agree (e.g., extreme leverage + leadership rolling over), the historical base rate of bad forward returns is robust.

**What the composite is honest about**:
- Mid range (30-70%) is genuinely inconclusive. Don't trade off a 50th-percentile reading.
- The bottom-decile N=14 is small. Every single one was followed by positive 12m return historically, but base rates can change.
- The composite is for swing-scale auxiliary judgment, not a short-term timing tool.

## Open questions

1. **Quintile thresholds vs decile**: should we test top-20% / bottom-20% to get more samples in extreme zones, particularly for the MARGIN_M2 and SOX_SPX_RS signals that have small N?

2. **Joint extremes**: when multiple Tier-1/Tier-2 signals fire in the same direction, does the effect compound? The answer changes the composite-score weighting.

3. **Sector overlay**: durable signals are mostly leadership-based. Add XLF / XLE / XLY leadership next pass.

4. **HY OAS**: FRED restricted history to 3 years. Need a long-history alternative source (Moody's? St. Louis Fed FRED API key? Macrotrends scrape?).

5. **Walk-forward simulation**: instead of full-sample percentiles, recompute monthly using only data available at that time, and see if any tier-1 signals had drawdowns when the data was point-in-time.
