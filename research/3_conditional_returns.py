"""Conditional forward-return analysis for each signal.

For each signal, compute the SPX forward 3/6/12-month return distribution
conditional on signal-zone membership (extreme-low / mid / extreme-high) vs
the full sample baseline.

Output: data/conditional.csv with per-signal × horizon × zone statistics, plus
bootstrap p-values for the zone-vs-baseline mean difference.

This is the core analytical deliverable. The question we're answering is:

  "When signal X is in zone Z, does the SPX return distribution shift in a
  statistically meaningful way?"

Bootstrap p-value: probability of observing a mean shift as large or larger
under random reassignment of zone labels. < 0.05 = real signal at 95% conf.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

HORIZONS = [3, 6, 12]
EXTREME_LOW_PCT = 0.10
EXTREME_HIGH_PCT = 0.90
MIN_HISTORY_MONTHS = 60
BOOTSTRAP_ITER = 2000
RNG = np.random.default_rng(20260527)


def load_spx_monthly() -> pd.Series:
    df = pd.read_csv(RAW / "GSPC.csv", parse_dates=["date"])
    s = df.set_index("date")["value"].astype(float).sort_index()
    s = s.resample("ME").last().dropna()
    s.name = "spx"
    return s


def load_signals_wide() -> pd.DataFrame:
    long = pd.read_csv(DATA / "signals.csv", parse_dates=["date"])
    wide = long.pivot(index="date", columns="signal", values="value")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def expanding_percentile(s: pd.Series, min_history: int = MIN_HISTORY_MONTHS) -> pd.Series:
    """Each observation's historical percentile using only past data (no look-ahead)."""
    return s.expanding(min_history).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def compute_forward_returns(spx: pd.Series, horizon_months: int) -> pd.Series:
    return spx.shift(-horizon_months) / spx - 1


def stats_of(returns: pd.Series) -> dict:
    r = returns.dropna()
    if r.empty:
        return {"n": 0, "mean": np.nan, "median": np.nan, "p10": np.nan, "p90": np.nan,
                "hit_rate": np.nan, "stddev": np.nan}
    return {
        "n": int(len(r)),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "p10": float(r.quantile(0.10)),
        "p90": float(r.quantile(0.90)),
        "hit_rate": float((r > 0).mean()),
        "stddev": float(r.std(ddof=1)),
    }


def bootstrap_pvalue(
    in_zone_returns: pd.Series, full_returns: pd.Series, n_iter: int = BOOTSTRAP_ITER
) -> float:
    """Two-sided permutation test for difference in means.

    Under the null (no zone effect), the in-zone label is randomly assigned.
    We compare the observed mean-diff to the distribution of mean-diffs under
    random reassignment. p-value = fraction at least as extreme.
    """
    in_zone = in_zone_returns.dropna().values
    full = full_returns.dropna().values
    if len(in_zone) < 5 or len(full) < 30:
        return float("nan")

    out_zone = np.setdiff1d(full, in_zone, assume_unique=False)
    pool = np.concatenate([in_zone, out_zone])
    observed_diff = in_zone.mean() - pool.mean()

    n_in = len(in_zone)
    diffs = np.empty(n_iter)
    for i in range(n_iter):
        idx = RNG.choice(len(pool), n_in, replace=False)
        sample_mean = pool[idx].mean()
        diffs[i] = sample_mean - pool.mean()

    p = float((np.abs(diffs) >= abs(observed_diff)).mean())
    return p


def analyze_signal(name: str, signal_series: pd.Series, spx: pd.Series) -> list[dict]:
    """For one signal, compute conditional stats across all horizons × zones."""
    pct = expanding_percentile(signal_series)
    # Align everything to monthly index
    aligned = pd.DataFrame({
        "signal_value": signal_series,
        "signal_pct": pct,
    }).join(pd.DataFrame({"spx": spx}), how="inner")

    rows = []
    for h in HORIZONS:
        fwd = compute_forward_returns(spx, h)
        df = aligned.join(fwd.rename("fwd"), how="left")
        df = df.dropna(subset=["signal_pct", "fwd"])
        if df.empty:
            continue

        full_stats = stats_of(df["fwd"])
        low_mask = df["signal_pct"] <= EXTREME_LOW_PCT
        high_mask = df["signal_pct"] >= EXTREME_HIGH_PCT
        mid_mask = ~low_mask & ~high_mask

        for zone, mask in [("LOW", low_mask), ("MID", mid_mask), ("HIGH", high_mask)]:
            zone_returns = df.loc[mask, "fwd"]
            stats = stats_of(zone_returns)
            stats["signal"] = name
            stats["horizon_months"] = h
            stats["zone"] = zone
            stats["full_sample_mean"] = full_stats["mean"]
            stats["full_sample_n"] = full_stats["n"]
            stats["mean_diff_vs_full"] = (
                stats["mean"] - full_stats["mean"] if not np.isnan(stats["mean"]) else np.nan
            )
            if zone in ("LOW", "HIGH"):
                stats["bootstrap_p"] = bootstrap_pvalue(zone_returns, df["fwd"])
            else:
                stats["bootstrap_p"] = np.nan
            rows.append(stats)
    return rows


def fmt_pct(x: float, dp: int = 1) -> str:
    return "n/a" if pd.isna(x) else f"{x * 100:+.{dp}f}%"


def main() -> int:
    print("Loading SPX and signals...")
    spx = load_spx_monthly()
    sig_wide = load_signals_wide()
    print(f"  SPX:     {spx.index.min().date()} -> {spx.index.max().date()} ({len(spx)} months)")
    print(f"  Signals: {list(sig_wide.columns)}")

    all_rows: list[dict] = []
    for sig_name in sig_wide.columns:
        s = sig_wide[sig_name].dropna()
        print(f"\nAnalyzing {sig_name} ({len(s)} months)...")
        rows = analyze_signal(sig_name, s, spx)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    df = df[
        ["signal", "horizon_months", "zone", "n", "mean", "median", "p10", "p90",
         "hit_rate", "stddev", "full_sample_mean", "full_sample_n",
         "mean_diff_vs_full", "bootstrap_p"]
    ]
    out_path = DATA / "conditional.csv"
    df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path} ({len(df)} rows)")

    # Pretty-print the 12-month horizon, which is the cleanest signal
    print("\n" + "=" * 95)
    print("Conditional 12-month SPX forward returns by signal × zone")
    print("=" * 95)
    sub = df[df["horizon_months"] == 12].copy()
    print(
        f"{'Signal':<14} {'Zone':<5} {'N':>5}  "
        f"{'Mean':>9}  {'Median':>9}  {'p10':>9}  {'p90':>9}  "
        f"{'Hit':>6}  {'vs_full':>9}  {'p-val':>7}"
    )
    print("-" * 95)
    for _, r in sub.iterrows():
        pval = "" if pd.isna(r["bootstrap_p"]) else f"{r['bootstrap_p']:.3f}"
        flag = "  *" if not pd.isna(r["bootstrap_p"]) and r["bootstrap_p"] < 0.05 else ""
        print(
            f"{r['signal']:<14} {r['zone']:<5} {r['n']:>5}  "
            f"{fmt_pct(r['mean']):>9}  {fmt_pct(r['median']):>9}  "
            f"{fmt_pct(r['p10']):>9}  {fmt_pct(r['p90']):>9}  "
            f"{fmt_pct(r['hit_rate'], 0):>6}  "
            f"{fmt_pct(r['mean_diff_vs_full']):>9}  {pval:>7}{flag}"
        )
    print("\n* = statistically significant zone-vs-full mean difference at p < 0.05")
    return 0


if __name__ == "__main__":
    sys.exit(main())
