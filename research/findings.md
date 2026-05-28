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

## v3 — DXY/10Y/Yield Curve deep dive + drawdown analysis (2026-05-28)

Initial premise was to add DXY and 10Y treasury level signals to the composite. Quintile-threshold stability tests killed both as standalone signals (DXY level failed cross-decade stability — dot-com era artifact again; 10Y change was too noisy). User pushed back, asking for deeper exploration. The deeper dive revealed:

### Multi-horizon validation

Yield curve (10Y-3M) finally surfaces at the **36-month horizon**, not 12-month:

| Horizon | YC LOW effect | p-value |
|---|---:|---:|
| 12m | +0.2pp | 0.911 (no signal) |
| 24m | -4.5pp | 0.049 (weak) |
| 36m | **-17.5pp** | **<0.001** ★ |

The classic "inverted yield curve precedes recession" thesis is real, but the 12-month forward horizon misses it. Recessions hit ~18-24 months after inversion, and the worst SPX drawdown follows in the 24-36 month window. We had filtered yield curve out of the dashboard based on a too-short horizon. Lesson: signal validity depends on the horizon you test at.

### Decile rerun salvaged one signal

`Y10_3M_CHG LOW` (rates dropping fast) at decile threshold became DURABLE: **+8.2pp, p<0.001**, with 4 of 5 decades positive (most recently +24pp in 2020s). Interpretation: rapid yield drops = central-bank easing / crisis response → strong 12m fwd SPX rebounds. Promoted to candidate composite component.

### Cross-asset asymmetry (H4)

When DXY is in extreme zones, SPX and Gold behave very differently:

| DXY zone | 12m fwd SPX | 12m fwd Gold |
|---|---:|---:|
| LOW (weak USD) | -7.6pp (p<0.001) | +5.2pp (p=0.013) |
| HIGH (strong USD) | -21.2pp (p<0.001) | +6.9pp (p=0.089) |

**Both DXY extremes are bad for SPX** (symmetric stress) **but good for Gold** (avoid-USD refuge). This is the "where does money go" answer the user asked for — when DXY regime is extreme, gold absorbs the safe-haven flow.

### Joint extremes (H5)

Combining signals yields a sharper bear regime indicator:

- `MARGIN_M2 HIGH` alone: -13.2pp, 54% hit (N=56)
- `MARGIN_M2 HIGH ∧ YC LOW`: **-14.1pp, 27% hit (N=11)** — when over-leveraged AND curve inverted, bear odds spike

### Drawdown asymmetry is the real story

When we shift from "mean fwd return" to "fwd 24-month maximum drawdown distribution", the composite extremes show their teeth:

| Zone | N | Mean DD | Median DD | P(DD ≤ -20%) | P(DD ≤ -30%) | CVaR10 |
|---|---:|---:|---:|---:|---:|---:|
| LOW (0-10%) | 14 | **+1.9%** | +1.7% | **0%** | **0%** | **+8.4%** |
| MID | 324 | -7.8% | -3.5% | 14% | 7% | -13.6% |
| HIGH (90-100%) | 28 | **-23.9%** | **-30.8%** | **64%** | **50%** | **-37.1%** |

This is the dashboard's real value. The asymmetry between zones is starker on the drawdown axis than on the mean-return axis. Avoiding the EXTREME HIGH zone has historically been the single biggest swing-trade edge.

Single-signal drawdown highlights:
- `SOX_SPX_RS LOW` (semis crashing): N=9, mean DD -24.9%, P(DD ≤ -30%) = 44%. Strongest single bear signal by drawdown depth.
- `NDX_SPX_RS LOW` (tech rolling over): mean DD -17.1%, P(DD ≤ -20%) = 46%. Confirms tech weakness is a real risk signal.
- `MARGIN_M2 HIGH`: median DD only -4.9% (small) but p10 DD = -50% — wide dispersion. Sometimes continues (1999, 2021), sometimes catastrophic (2000, 2008).

## v3.7 — A/B composite expansion: REVERTED (2026-05-28)

User question: "Did the new factors (DXY/10Y) actually make the composite more accurate? I see no change in red/green zones."

Honest answer: **They did not improve the composite. The composite was reverted to V2.**

### The A/B test

Built 4 candidate composites and tested fwd 12m return + 24m drawdown stats:

| Candidate | Y10 sign | Asym (pp) | HIGH mean | HIGH P(DD≤-30%) | Current pct |
|---|---|---:|---:|---:|---:|
| V2 (4 components) | n/a | +43.0 | -8.9% | 50% | 37.8% |
| V3a-wrongsign (Y10 invert=True) | ❌ backwards | +47.6 | -12.6% | 57% | 22.3% |
| V3a-correct (Y10 invert=False) | ✅ aligned | +25.5 | **+6.7%** | 12% | 57.6% |
| V3b (Y10 + DXY 3m chg) | ✅ | +25.2 | +6.7% | 12% | 65.0% |
| V3c (+ DXY level) | n/a | +22.3 | +8.8% | 0% | 48.0% |

### What happened

My initial "V3a improves the composite" finding was wrong. The improvement only existed when Y10_3M_CHG was sign-inverted (invert=True), which is *semantically backwards* — it makes high signal value (rapid rate rise = stress) reduce composite, when it should increase it. With the correct sign:

1. HIGH composite zone mean fwd return goes from -8.9% (V2) to +6.7% (V3a-correct). The signal disappears.
2. P(DD ≤ -30%) in HIGH zone drops from 50% to 12%. Big loss of tail-risk warning power.
3. Asymmetry drops from +43pp to +25pp.

### Why adding Y10 hurts

Y10_3M_CHG LOW (rapid rate drops) and MARGIN_M2 LOW (post-deleveraging) are highly correlated in crisis aftermath. They both fire in the same windows (2002-2003, 2009-2010, 2020-2021). Adding Y10 amplifies what MARGIN_M2 already captures rather than adding information.

Similarly, DXY_LEVEL is regime-dependent (dot-com era artifact, same trap as MCAP_M2). DXY_3M_CHG has direction stability but weak magnitude.

### The discipline lesson

A composite is not "more validated signals = better composite". Component diversification matters more than component count. The A/B test was the right gate — without it we would have shipped a worse indicator and labeled it "improved".

The Y10_3M_CHG LOW signal is still **real** at the standalone level (DURABLE +8.2pp at decile, p<0.001). But it just doesn't add information to the existing composite.

### What stays from V3 research

Even though the composite didn't change, the V3 research delivered real findings:

- Yield curve at 36-month horizon is DURABLE (-17.5pp, p<0.001). Classic recession lead at the right horizon.
- Cross-asset asymmetry: DXY extremes hurt SPX both directions, but help Gold (safe-haven flows).
- Joint extremes: MARGIN_M2 HIGH ∧ YC LOW (N=11) — 27% hit rate, much worse than MARGIN alone.
- Drawdown asymmetry: composite HIGH zone has 50% probability of -30% drawdown vs 0% for LOW zone. The composite's real value is on the *risk* axis, not the *return* axis.

These are documented but not in the composite. They live as watch-list signals and analytical context.

## v4 — Liquidity Trend Panel (2026-05-28)

User asked: can we detect 2022 liquidity tightening early? 2020-21 liquidity release quickly? Should this be a separate panel rather than fold into the composite?

The answer is yes to both. Composite is slow by design (percentile-based, designed for cycle-position). Trend detection on macro variables is a different lens — faster, inflection-oriented.

### Backtest at 2020-03 (Fed COVID easing) and 2022-01 (QT pivot)

Three techniques tested: SuperTrend(10, 2.0), EMA crossover (3/12 and 6/24), Donchian breakout(12). Results per variable, best detection lag:

| Variable | 2020-03 easing detection | 2022-01 tightening detection |
|---|---:|---:|
| **NETLIQ** | 0.5m (EMA 6/24) | **0.9m (SuperTrend)** |
| WALCL | 0.5m (EMA 6/24) | 9.0m (SuperTrend) |
| M2_LEVEL | 46.6m (slow, monotonic) | 9.0m (SuperTrend) |
| M2_GROWTH_YOY | 45.5m | 46.0m |
| DGS10 | 16.5m | 26.9m |
| DXY | 4.5m (EMA 3/12) | 19.9m (EMA 3/12) |

**Net Liquidity is the most sensitive inflection detector** — both 2020 and 2022 caught within 1 month. WALCL is fast in easing (Fed announces) but slow in tightening (passive runoff). M2 GROWTH lags way too much.

### Why SuperTrend works on monthly macro

Classic SuperTrend uses ATR-based bands above and below price. For monthly macro, we substitute ATR with the rolling mean of absolute month-over-month delta (10-period). The bands tighten when in trend and only flip when price crosses the OPPOSITE band — making the signal sticky but responsive at true inflections.

### Production design

- Variables: WALCL, NETLIQ, M2_LEVEL, DGS10, DXY (5 total)
- Single technique: SuperTrend(10, 2.0) — easier to read than 4 different techniques per variable
- Liquidity flow score = (# in release direction) − (# in tightening direction). Range −5 to +5.
- Score ≥ +2 = leaning release; ≤ −2 = leaning tightening; otherwise mixed.

### Current state (2026-05)

Score +3/5 — leans liquidity release:
- WALCL: UP, just flipped 2 months ago (Fed BS expanding again)
- NETLIQ: UP, stable
- M2: UP, trend established 26 months
- DGS10: UP just 1 month — RATES RISING TIGHTENING (the dissenting signal)
- DXY: DOWN, 14 months of USD weakening = release

Net read: 4-vs-1 lean toward release, but DGS10 recently flipping up + WALCL fresh up = "Fed loosening while market reprices growth/inflation expectations". A regime to watch.

## Open questions

1. **Quintile thresholds vs decile**: should we test top-20% / bottom-20% to get more samples in extreme zones, particularly for the MARGIN_M2 and SOX_SPX_RS signals that have small N?

2. **Joint extremes**: when multiple Tier-1/Tier-2 signals fire in the same direction, does the effect compound? The answer changes the composite-score weighting.

3. **Sector overlay**: durable signals are mostly leadership-based. Add XLF / XLE / XLY leadership next pass.

4. **HY OAS**: FRED restricted history to 3 years. Need a long-history alternative source (Moody's? St. Louis Fed FRED API key? Macrotrends scrape?).

5. **Walk-forward simulation**: instead of full-sample percentiles, recompute monthly using only data available at that time, and see if any tier-1 signals had drawdowns when the data was point-in-time.
