"""V4.4 — tune SuperTrend parameters per macro variable for clean macro
inflection detection.

The original SuperTrend(10, 2.0) on raw monthly data was too noisy.
Goal: parameters that give FEW false positives during steady-state periods,
but still flip within 1-3 months of true regime inflections (2020-03 easing,
2022-01 QT).

Grid:
  period:    10, 15, 20, 24    (ATR lookback in months)
  mult:      2.0, 2.5, 3.0, 4.0 (band width multiplier)
  smoothing: raw, 3m MA, 6m MA  (smooth input before SuperTrend)

Score for each (variable, params):
  score = -(detection_lag_2020 + detection_lag_2022) / 2 - flip_count * penalty
where penalty = 0.5 (each false-positive flip costs 0.5 months of lag tolerance)

The combo with highest score wins.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

INFLECTIONS = {
    "2020-03": pd.Timestamp("2020-03-15"),
    "2022-01": pd.Timestamp("2022-01-31"),
}

# Expected flip direction per (variable, event)
EXPECTED_DIR = {
    ("WALCL", "2020-03"): +1,    ("WALCL", "2022-01"): -1,
    ("NETLIQ", "2020-03"): +1,   ("NETLIQ", "2022-01"): -1,
    ("M2_LEVEL", "2020-03"): +1, ("M2_LEVEL", "2022-01"): -1,
    ("DGS10", "2020-03"): -1,    ("DGS10", "2022-01"): +1,
    ("DXY", "2020-03"): -1,      ("DXY", "2022-01"): +1,
}

FLIP_PENALTY = 0.4   # months of lag tolerance per false-positive flip


def load_raw(name: str) -> pd.Series:
    df = pd.read_csv(RAW / f"{name}.csv", parse_dates=["date"])
    return df.set_index("date")["value"].astype(float).sort_index()


def to_month(s: pd.Series, how: str = "mean") -> pd.Series:
    if how == "mean":
        return s.sort_index().resample("ME").mean().dropna()
    return s.sort_index().resample("ME").last().dropna()


def supertrend(series: pd.Series, period: int, mult: float) -> pd.DataFrame:
    s = series.dropna().copy()
    delta = s.diff()
    atr = delta.abs().rolling(period).mean()
    mid = (s + s.shift(1)) / 2
    upper_basic = mid + mult * atr
    lower_basic = mid - mult * atr
    upper = upper_basic.copy()
    lower = lower_basic.copy()
    direction = pd.Series(0, index=s.index, dtype=int)

    for i in range(1, len(s)):
        if pd.isna(upper.iloc[i]) or pd.isna(lower.iloc[i]):
            continue
        if s.iloc[i - 1] <= upper.iloc[i - 1] and not pd.isna(upper.iloc[i - 1]):
            upper.iloc[i] = min(upper.iloc[i], upper.iloc[i - 1])
        if s.iloc[i - 1] >= lower.iloc[i - 1] and not pd.isna(lower.iloc[i - 1]):
            lower.iloc[i] = max(lower.iloc[i], lower.iloc[i - 1])
        if direction.iloc[i - 1] >= 0:
            direction.iloc[i] = -1 if s.iloc[i] < lower.iloc[i] else 1
        else:
            direction.iloc[i] = 1 if s.iloc[i] > upper.iloc[i] else -1

    flip = direction.diff().abs() > 0
    flip.iloc[0] = False
    return pd.DataFrame({"value": s, "direction": direction, "flip": flip})


def evaluate(series: pd.Series, var_name: str, period: int, mult: float,
              smoothing: str) -> dict:
    if smoothing == "ma3":
        s_in = series.rolling(3).mean().dropna()
    elif smoothing == "ma6":
        s_in = series.rolling(6).mean().dropna()
    else:
        s_in = series.copy()

    df = supertrend(s_in, period, mult)
    df_post_2005 = df[df.index >= pd.Timestamp("2005-01-01")]
    flip_count = int(df_post_2005["flip"].sum())

    lags = []
    for event_key, event_date in INFLECTIONS.items():
        expected = EXPECTED_DIR.get((var_name, event_key))
        if expected is None:
            continue
        sub = df[df.index >= event_date]
        match = sub[sub["flip"] & (sub["direction"] == expected)]
        if match.empty:
            lags.append(60.0)  # penalty for missed event
        else:
            lag = (match.index[0] - event_date).days / 30.44
            lags.append(min(lag, 60.0))

    avg_lag = float(np.mean(lags)) if lags else 60.0
    score = -avg_lag - flip_count * FLIP_PENALTY
    return {
        "period": period, "mult": mult, "smoothing": smoothing,
        "flip_count": flip_count, "avg_lag": avg_lag,
        "lag_2020": lags[0] if len(lags) > 0 else None,
        "lag_2022": lags[1] if len(lags) > 1 else None,
        "score": score,
    }


def main() -> int:
    print("Loading...")
    walcl = to_month(load_raw("WALCL")) / 1_000_000
    wtregen = to_month(load_raw("WTREGEN")) / 1_000_000
    rrp = to_month(load_raw("RRPONTSYD")) / 1_000
    netliq = (walcl - wtregen - rrp).dropna()
    netliq.name = "NETLIQ"
    m2 = load_raw("M2SL")
    m2.index = m2.index.to_period("M").to_timestamp("M")
    m2 = m2.sort_index()
    dgs10 = to_month(load_raw("DGS10"))
    dxy = to_month(load_raw("DX-Y.NYB"), "last")

    variables = {
        "WALCL": walcl, "NETLIQ": netliq, "M2_LEVEL": m2, "DGS10": dgs10, "DXY": dxy,
    }

    # Param grid
    periods = [10, 15, 20, 24]
    mults = [2.0, 2.5, 3.0, 4.0]
    smoothings = ["raw", "ma3", "ma6"]

    print(f"\nGrid: {len(periods)*len(mults)*len(smoothings)} combos per variable, "
          f"{len(variables)} variables")

    all_results = {}
    for vname, series in variables.items():
        rows = []
        for p in periods:
            for m in mults:
                for sm in smoothings:
                    r = evaluate(series, vname, p, m, sm)
                    rows.append(r)
        df = pd.DataFrame(rows).sort_values("score", ascending=False)
        all_results[vname] = df

        print(f"\n{'='*80}")
        print(f"{vname} — top 5 parameter combos (by score)")
        print('='*80)
        print(f"{'Period':>7} {'Mult':>5} {'Smooth':>7} | {'Flips':>5} | "
              f"{'Lag2020':>8} {'Lag2022':>8} {'AvgLag':>7} | {'Score':>7}")
        print("-" * 75)
        for _, r in df.head(5).iterrows():
            print(f"{int(r['period']):>7} {r['mult']:>5.1f} {r['smoothing']:>7} | "
                  f"{int(r['flip_count']):>5} | "
                  f"{r['lag_2020']:>7.1f}m {r['lag_2022']:>7.1f}m "
                  f"{r['avg_lag']:>6.1f}m | {r['score']:>+6.2f}")

    # Combined export
    combined = pd.concat({k: v for k, v in all_results.items()}, names=["variable"]).reset_index()
    combined.to_csv(DATA / "trend_tuning_grid.csv", index=False)

    # Best per variable
    print("\n" + "=" * 80)
    print("BEST PARAMS PER VARIABLE")
    print("=" * 80)
    print(f"{'Variable':<10} {'Period':>7} {'Mult':>5} {'Smooth':>7} | "
          f"{'Flips':>5} {'Lag2020':>8} {'Lag2022':>8}")
    print("-" * 70)
    for vname, df in all_results.items():
        best = df.iloc[0]
        print(f"{vname:<10} {int(best['period']):>7} {best['mult']:>5.1f} {best['smoothing']:>7} | "
              f"{int(best['flip_count']):>5} "
              f"{best['lag_2020']:>7.1f}m {best['lag_2022']:>7.1f}m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
