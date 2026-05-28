"""Composite cycle indicator — combines validated signals into a single
'top warning vs bottom setup' score for medium-term (swing) positioning.

Construction
------------
For each component signal:
  1. Compute expanding-window percentile rank (no look-ahead).
  2. Center to [-1, +1]: `(percentile - 0.5) * 2`.
  3. Sign-align so that +1 means "more dangerous / top-leaning":
       - MARGIN_M2:   higher = danger    → keep sign
       - NDX_SPX_RS:  higher = LESS danger (bullish continuation) → invert sign
       - SOX_SPX_RS:  higher = LESS danger → invert sign
       - RUT_SPX_RS:  higher = danger (small-cap blow-off, late cycle) → keep sign
  4. Weight by tier confidence (DURABLE=1.0, MOSTLY=0.6, REGIME-DEP=0.4).
  5. Composite = weighted average, range roughly [-1, +1].

Validation
----------
For each composite-percentile decile, compute 12m fwd SPX return distribution
and compare to full-sample baseline. Bootstrap p-value for the top/bottom decile
to confirm extremes carry real predictive shift.

This is the medium-term "swing" auxiliary indicator the user asked for —
not a precise trigger, but a relative-position read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

MIN_HISTORY_MONTHS = 60
BOOTSTRAP_ITER = 2000
HORIZON = 12
RNG = np.random.default_rng(20260528)

# Component definitions: (name, weight, invert_sign)
# invert_sign=True means "higher signal value = LESS dangerous" so we flip
COMPONENTS = [
    ("MARGIN_M2",  1.0, False),   # DURABLE bearish-when-high (keep)
    ("NDX_SPX_RS", 0.6, True),    # MOSTLY bullish-when-high (invert: high RS = less danger)
    ("SOX_SPX_RS", 0.6, True),    # MOSTLY bullish-when-high (invert)
    ("RUT_SPX_RS", 0.4, False),   # higher RS = small caps blowing off = late cycle (keep)
]


def load_spx_monthly() -> pd.Series:
    df = pd.read_csv(RAW / "GSPC.csv", parse_dates=["date"])
    s = df.set_index("date")["value"].astype(float).sort_index()
    return s.resample("ME").last().dropna().rename("spx")


def load_signals_wide() -> pd.DataFrame:
    long = pd.read_csv(DATA / "signals.csv", parse_dates=["date"])
    return long.pivot(index="date", columns="signal", values="value").sort_index()


def expanding_percentile(s: pd.Series) -> pd.Series:
    return s.expanding(MIN_HISTORY_MONTHS).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def build_composite(signals: pd.DataFrame) -> pd.Series:
    """Compute the composite cycle indicator as a monthly series.

    Components are forward-filled up to 3 months to handle reporting lags
    (e.g., FINRA margin debt is published with a ~3-week lag, so the most
    recent month's value is often missing for the first 2-3 weeks of the
    following month). Beyond 3 months of staleness, that component drops out
    and the composite is re-weighted across remaining components.
    """
    aligned = {}
    weight_by_name = {}
    for name, weight, invert in COMPONENTS:
        if name not in signals.columns:
            print(f"  [warn] component {name} missing from signals; skipping")
            continue
        s = signals[name]                            # may have NaN at recent months
        pct = expanding_percentile(s.dropna())
        # Reindex to the full monthly grid of all components combined later
        aligned[name] = pct
        weight_by_name[name] = weight

    # Build full monthly grid from all components
    full_idx = sorted(set().union(*[s.index for s in aligned.values()]))
    full_idx = pd.DatetimeIndex(full_idx)

    centered = {}
    for name, pct in aligned.items():
        invert = next(inv for n, _, inv in COMPONENTS if n == name)
        # Forward-fill up to 3 months for reporting-lag tolerance
        reindexed = pct.reindex(full_idx).ffill(limit=3)
        c = (reindexed - 0.5) * 2.0
        if invert:
            c = -c
        centered[name] = c

    combined = pd.DataFrame(centered)
    # Weighted average across components present each month; reweight by available weights
    weight_arr = np.array([weight_by_name[c] for c in combined.columns])
    mask = combined.notna().to_numpy().astype(float)         # 1 if present, 0 if NaN
    weighted_vals = combined.fillna(0).to_numpy() * weight_arr
    sum_weights_row = mask * weight_arr
    sum_weights_row = sum_weights_row.sum(axis=1)
    # Avoid div by zero
    composite_vals = np.where(sum_weights_row > 0,
                              weighted_vals.sum(axis=1) / sum_weights_row,
                              np.nan)
    composite = pd.Series(composite_vals, index=combined.index, name="COMPOSITE")
    return composite.dropna()


def conditional_stats(composite: pd.Series, spx: pd.Series) -> pd.DataFrame:
    """For each composite decile, compute conditional 12m fwd SPX return stats."""
    fwd = spx.shift(-HORIZON) / spx - 1
    pct = expanding_percentile(composite)
    df = pd.DataFrame({"composite": composite, "pct": pct, "fwd": fwd}).dropna()

    rows = []
    deciles = [(0, 0.10, "0-10% (extreme low / setup)"),
               (0.10, 0.30, "10-30% (low / leaning setup)"),
               (0.30, 0.50, "30-50% (mid-low)"),
               (0.50, 0.70, "50-70% (mid-high)"),
               (0.70, 0.90, "70-90% (high / leaning warning)"),
               (0.90, 1.00, "90-100% (extreme high / warning)")]

    full_mean = df["fwd"].mean()
    full_std = df["fwd"].std(ddof=1)
    full_n = len(df)

    for lo, hi, label in deciles:
        sub = df[(df["pct"] > lo) & (df["pct"] <= hi)] if lo > 0 else df[df["pct"] <= hi]
        if sub.empty:
            continue
        rows.append({
            "decile": label,
            "n": len(sub),
            "mean": float(sub["fwd"].mean()),
            "median": float(sub["fwd"].median()),
            "p10": float(sub["fwd"].quantile(0.10)),
            "p90": float(sub["fwd"].quantile(0.90)),
            "hit_rate": float((sub["fwd"] > 0).mean()),
            "vs_full_pp": float((sub["fwd"].mean() - full_mean) * 100),
        })

    return pd.DataFrame(rows), full_mean, full_std, full_n


def bootstrap_pvalue(zone: np.ndarray, pool: np.ndarray, n_iter: int = BOOTSTRAP_ITER) -> float:
    if len(zone) < 5 or len(pool) < 30:
        return float("nan")
    obs = zone.mean() - pool.mean()
    n_z = len(zone)
    diffs = np.empty(n_iter)
    for i in range(n_iter):
        idx = RNG.choice(len(pool), n_z, replace=False)
        diffs[i] = pool[idx].mean() - pool.mean()
    return float((np.abs(diffs) >= abs(obs)).mean())


def extremes_pvalues(composite: pd.Series, spx: pd.Series) -> dict:
    fwd = spx.shift(-HORIZON) / spx - 1
    pct = expanding_percentile(composite)
    df = pd.DataFrame({"pct": pct, "fwd": fwd}).dropna()
    pool = df["fwd"].values
    top = df.loc[df["pct"] >= 0.90, "fwd"].values
    bot = df.loc[df["pct"] <= 0.10, "fwd"].values
    return {
        "top_decile_n": len(top),
        "top_decile_mean": float(top.mean()) if len(top) > 0 else float("nan"),
        "top_decile_p": bootstrap_pvalue(top, pool),
        "bot_decile_n": len(bot),
        "bot_decile_mean": float(bot.mean()) if len(bot) > 0 else float("nan"),
        "bot_decile_p": bootstrap_pvalue(bot, pool),
    }


def stability_by_decade(composite: pd.Series, spx: pd.Series) -> pd.DataFrame:
    """Per-decade conditional stats for top/bottom deciles."""
    fwd = spx.shift(-HORIZON) / spx - 1
    pct = expanding_percentile(composite)
    df = pd.DataFrame({"pct": pct, "fwd": fwd}).dropna()
    df["decade"] = df.index.to_series().apply(lambda x: f"{x.year - (x.year % 10)}s")
    rows = []
    for decade_label, sub in df.groupby("decade"):
        base = sub["fwd"].mean()
        top = sub.loc[sub["pct"] >= 0.90, "fwd"]
        bot = sub.loc[sub["pct"] <= 0.10, "fwd"]
        rows.append({
            "decade": decade_label,
            "n_decade": len(sub),
            "baseline_pct": float(base * 100),
            "top_n": len(top),
            "top_effect_pp": float((top.mean() - base) * 100) if len(top) > 0 else np.nan,
            "bot_n": len(bot),
            "bot_effect_pp": float((bot.mean() - base) * 100) if len(bot) > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def main() -> int:
    print("Loading SPX and signals...")
    spx = load_spx_monthly()
    signals = load_signals_wide()

    print("\nBuilding composite from components:")
    for name, w, inv in COMPONENTS:
        print(f"  - {name} (weight={w}, invert_sign={inv})")
    composite = build_composite(signals)
    print(f"\nComposite series: {composite.index.min().date()} -> {composite.index.max().date()} ({len(composite)} months)")
    print(f"Current value: {composite.iloc[-1]:+.3f}")
    pct_now = expanding_percentile(composite).dropna()
    if len(pct_now):
        print(f"Current percentile: {pct_now.iloc[-1]*100:.1f}%")
    composite.to_frame("composite").to_csv(DATA / "composite.csv", index_label="date")

    print("\n" + "=" * 80)
    print("Composite decile conditional 12m fwd SPX returns")
    print("=" * 80)
    stats, full_mean, full_std, full_n = conditional_stats(composite, spx)
    print(f"Full sample baseline: mean={full_mean*100:+.2f}%  std={full_std*100:.2f}%  N={full_n}")
    print()
    print(f"{'Decile':<35} {'N':>4}  {'Mean':>9}  {'Median':>9}  {'p10':>9}  {'p90':>9}  {'Hit':>5}  {'vs_full':>8}")
    print("-" * 100)
    for _, r in stats.iterrows():
        print(
            f"{r['decile']:<35} {r['n']:>4}  "
            f"{r['mean']*100:+8.2f}%  {r['median']*100:+8.2f}%  "
            f"{r['p10']*100:+8.2f}%  {r['p90']*100:+8.2f}%  "
            f"{r['hit_rate']*100:>4.0f}%  {r['vs_full_pp']:+7.1f}pp"
        )
    stats.to_csv(DATA / "composite_deciles.csv", index=False)

    print("\nBootstrap p-values for top/bottom decile extreme:")
    p = extremes_pvalues(composite, spx)
    print(f"  Top decile    (composite >= 0.90 pct): N={p['top_decile_n']}, "
          f"mean={p['top_decile_mean']*100:+.2f}%, p={p['top_decile_p']:.3f}")
    print(f"  Bottom decile (composite <= 0.10 pct): N={p['bot_decile_n']}, "
          f"mean={p['bot_decile_mean']*100:+.2f}%, p={p['bot_decile_p']:.3f}")

    print("\nPer-decade stability:")
    print("-" * 80)
    decade_stats = stability_by_decade(composite, spx)
    print(f"{'Decade':<8} {'N':>5} {'Base':>7}  {'TopN':>5} {'TopEff':>9}  {'BotN':>5} {'BotEff':>9}")
    for _, r in decade_stats.iterrows():
        top_eff = f"{r['top_effect_pp']:+6.1f}pp" if not pd.isna(r['top_effect_pp']) else "    n/a"
        bot_eff = f"{r['bot_effect_pp']:+6.1f}pp" if not pd.isna(r['bot_effect_pp']) else "    n/a"
        print(
            f"{r['decade']:<8} {int(r['n_decade']):>5} "
            f"{r['baseline_pct']:>5.1f}%  "
            f"{int(r['top_n']):>5} {top_eff:>9}  "
            f"{int(r['bot_n']):>5} {bot_eff:>9}"
        )
    decade_stats.to_csv(DATA / "composite_stability.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
