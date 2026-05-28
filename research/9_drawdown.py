"""V3 — drawdown analysis by signal regime.

Mean forward return tells half the story. The other half is the *cost of being
wrong* — the maximum drawdown you'd have lived through during the forward
window. For a swing-trade aid that helps you escape tops, the relevant
metric is "what was the worst-case drawdown when this signal was at this
zone historically?"

For each signal × zone, compute:
  - fwd 24-month maximum drawdown (peak-to-trough in forward window)
  - p10 / p50 / p90 of fwd drawdown
  - probability of fwd drawdown >= -10%, -20%, -30%
  - median time-to-trough (months from t to fwd min)
  - median time-to-recover (months from fwd min back to t-level)
  - CVaR @ 10% (average of worst 10% of fwd returns)

Compares conditional distributions to the full-sample baseline so the user
can see the asymmetry — e.g. composite EXTREME HIGH may have higher mean
fwd return than expected, but the worst-case tail is much heavier.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

LOOKAHEAD_MONTHS = 24
MIN_HISTORY_MONTHS = 60


def load_spx_monthly() -> pd.Series:
    df = pd.read_csv(RAW / "GSPC.csv", parse_dates=["date"])
    s = df.set_index("date")["value"].astype(float).sort_index()
    return s.resample("ME").last().dropna().rename("spx")


def load_signals_wide() -> pd.DataFrame:
    long = pd.read_csv(DATA / "signals.csv", parse_dates=["date"])
    return long.pivot(index="date", columns="signal", values="value").sort_index()


def expanding_percentile(s: pd.Series) -> pd.Series:
    return s.dropna().expanding(MIN_HISTORY_MONTHS).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def compute_fwd_metrics(spx: pd.Series, h: int) -> pd.DataFrame:
    """For each month t, compute forward h-month statistics."""
    n = len(spx)
    arr = spx.values
    fwd_max = np.full(n, np.nan)
    fwd_min = np.full(n, np.nan)
    fwd_dd = np.full(n, np.nan)        # peak-to-trough drawdown in fwd window
    fwd_dd_from_t = np.full(n, np.nan)  # drawdown measured from t (not running peak)
    months_to_trough = np.full(n, np.nan)
    months_to_recover = np.full(n, np.nan)
    fwd_h_return = np.full(n, np.nan)

    for i in range(n - 1):
        end = min(i + 1 + h, n)
        window = arr[i + 1:end]
        if len(window) == 0:
            continue
        # Include t in the running-max so we measure "any forward drawdown vs prior peak"
        with_t = np.concatenate([[arr[i]], window])
        cummax = np.maximum.accumulate(with_t)
        running_dd = with_t / cummax - 1.0
        min_dd_idx_in_with_t = running_dd.argmin()
        fwd_max[i] = window.max()
        fwd_min[i] = window.min()
        fwd_dd[i] = running_dd.min()
        # Drawdown from t price specifically (most relevant for "if I bought at t")
        from_t = window / arr[i] - 1.0
        fwd_dd_from_t[i] = from_t.min()
        # Months to trough (in fwd window, since window starts at i+1)
        trough_idx_fwd = from_t.argmin()
        months_to_trough[i] = trough_idx_fwd + 1
        # Months to recover: from trough, how many months until back to arr[i]
        if from_t[trough_idx_fwd] < 0:
            tail = window[trough_idx_fwd:]
            above = np.where(tail >= arr[i])[0]
            if len(above):
                months_to_recover[i] = above[0]
            else:
                months_to_recover[i] = np.nan
        else:
            months_to_recover[i] = 0
        # Plain horizon return at exactly h months
        if end - 1 - i == h:
            fwd_h_return[i] = arr[end - 1] / arr[i] - 1

    df = pd.DataFrame({
        "fwd_dd_from_t": fwd_dd_from_t,    # the most actionable metric
        "fwd_dd_peak_trough": fwd_dd,
        "months_to_trough": months_to_trough,
        "months_to_recover": months_to_recover,
        "fwd_h_return": fwd_h_return,
    }, index=spx.index)
    return df


def conditional_drawdown_stats(signal: pd.Series, fwd_df: pd.DataFrame,
                                 low_cut: float, high_cut: float) -> pd.DataFrame:
    pct = expanding_percentile(signal)
    df = fwd_df.join(pd.DataFrame({"pct": pct}), how="inner").dropna(subset=["pct", "fwd_dd_from_t"])
    if df.empty:
        return pd.DataFrame()

    full = df
    out_rows = []
    for label, mask in [("LOW", df["pct"] <= low_cut),
                          ("MID", (df["pct"] > low_cut) & (df["pct"] < high_cut)),
                          ("HIGH", df["pct"] >= high_cut),
                          ("FULL", pd.Series(True, index=df.index))]:
        sub = df.loc[mask]
        if sub.empty:
            continue
        dd = sub["fwd_dd_from_t"]
        ret = sub["fwd_h_return"].dropna()
        out_rows.append({
            "zone": label,
            "n": len(sub),
            "dd_mean": float(dd.mean() * 100),
            "dd_median": float(dd.median() * 100),
            "dd_p10": float(dd.quantile(0.10) * 100),  # worst 10%
            "dd_p50": float(dd.quantile(0.50) * 100),
            "dd_p90": float(dd.quantile(0.90) * 100),  # best 10% of drawdowns (smallest)
            "p_dd_below_10": float((dd <= -0.10).mean() * 100),
            "p_dd_below_20": float((dd <= -0.20).mean() * 100),
            "p_dd_below_30": float((dd <= -0.30).mean() * 100),
            "median_to_trough_m": float(sub["months_to_trough"].median()),
            "median_to_recover_m": float(sub["months_to_recover"].median()) if sub["months_to_recover"].notna().any() else float("nan"),
            "fwd_h_mean": float(ret.mean() * 100) if not ret.empty else float("nan"),
            "cvar_10": float(ret.quantile(0.10) * 100) if len(ret) > 10 else float("nan"),
        })
    return pd.DataFrame(out_rows)


def load_composite() -> pd.Series:
    path = DATA / "composite.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date")
    return df["composite"]


def print_table(name: str, df: pd.DataFrame):
    print(f"\n{name} — fwd {LOOKAHEAD_MONTHS}m drawdown statistics by zone:")
    print(f"  {'Zone':<5} {'N':>4} | {'Mean DD':>8} {'Med DD':>8} {'p10 DD':>8} | "
          f"{'P(<-10%)':>9} {'P(<-20%)':>9} {'P(<-30%)':>9} | "
          f"{'fwd ret':>9} {'CVaR10':>8}")
    print("  " + "-" * 100)
    for _, r in df.iterrows():
        print(
            f"  {r['zone']:<5} {int(r['n']):>4} | "
            f"{r['dd_mean']:>7.1f}% {r['dd_median']:>7.1f}% {r['dd_p10']:>7.1f}% | "
            f"{r['p_dd_below_10']:>8.0f}% {r['p_dd_below_20']:>8.0f}% {r['p_dd_below_30']:>8.0f}% | "
            f"{r['fwd_h_mean']:>7.1f}% {r['cvar_10']:>7.1f}%"
        )


def main() -> int:
    print("Loading...")
    spx = load_spx_monthly()
    print(f"  SPX: {spx.index.min().date()} -> {spx.index.max().date()}  N={len(spx)}")
    print(f"\nComputing fwd {LOOKAHEAD_MONTHS}-month drawdown metrics for SPX...")
    fwd = compute_fwd_metrics(spx, LOOKAHEAD_MONTHS)
    print(f"  Computed {fwd['fwd_dd_from_t'].notna().sum()} monthly fwd-window records")

    sig = load_signals_wide()
    composite = load_composite()

    all_summary = []

    # Production signals (decile cutoffs)
    for sig_name in ("MARGIN_M2", "NDX_SPX_RS", "SOX_SPX_RS", "RUT_SPX_RS"):
        if sig_name not in sig.columns:
            continue
        df = conditional_drawdown_stats(sig[sig_name], fwd, 0.10, 0.90)
        if not df.empty:
            df.insert(0, "signal", sig_name)
            all_summary.append(df)
            print_table(sig_name, df)

    # Composite
    if not composite.empty:
        df = conditional_drawdown_stats(composite, fwd, 0.10, 0.90)
        if not df.empty:
            df.insert(0, "signal", "COMPOSITE")
            all_summary.append(df)
            print_table("COMPOSITE", df)

    # Yield curve at 36m (just to show the worst-case shape)
    print("\n" + "=" * 90)
    print("BONUS: Yield curve (10Y-3M) at 36-MONTH drawdown horizon")
    print("=" * 90)
    y10_d = pd.read_csv(RAW / "DGS10.csv", parse_dates=["date"]).set_index("date")["value"].sort_index()
    y3m_d = pd.read_csv(RAW / "DGS3MO.csv", parse_dates=["date"]).set_index("date")["value"].sort_index()
    y10_m = y10_d.resample("ME").mean().dropna()
    y3m_m = y3m_d.resample("ME").mean().dropna()
    yc = (y10_m - y3m_m).dropna() * 100
    yc.name = "YIELD_CURVE"
    fwd_36 = compute_fwd_metrics(spx, 36)
    df = conditional_drawdown_stats(yc, fwd_36, 0.10, 0.90)
    if not df.empty:
        df.insert(0, "signal", "YIELD_CURVE_36M")
        all_summary.append(df)
        print_table("YIELD_CURVE (36m horizon)", df)

    # Save all
    if all_summary:
        combined = pd.concat(all_summary, ignore_index=True)
        combined.to_csv(DATA / "drawdown_stats.csv", index=False)
        print(f"\nSaved {len(combined)} rows to data/drawdown_stats.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
