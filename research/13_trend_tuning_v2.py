"""V4.5 — finer trend tuning with derived series and corrected scoring.

Lessons from V4.4 tuning:
  - M2 level barely moves; use M2 12m growth instead.
  - DGS10/DXY levels are too noisy; use 6m change / 3m %change derived series.
  - Scoring was wrong — if direction was ALREADY in expected direction at the
    inflection date, that's a SUCCESS (lag = 0), not a missed event.

Corrected scoring:
  - "in correct direction" within [anchor-3m, anchor+3m] window = good detection
  - lag = month offset from anchor when direction first matches expected
    (negative = detected before event, positive = after)
  - clamp lag to [0, +inf) for scoring (early detection doesn't help if too early)
  - missed = no match within [anchor-6m, anchor+18m]: heavy penalty

Score = -|lag| - flip_count * 0.4
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

# Expected flip DIRECTION at each event for each variable
EXPECTED_DIR = {
    ("WALCL", "2020-03"): +1,        ("WALCL", "2022-01"): -1,
    ("NETLIQ", "2020-03"): +1,       ("NETLIQ", "2022-01"): -1,
    ("M2_GROWTH", "2020-03"): +1,    ("M2_GROWTH", "2022-01"): -1,
    ("DGS10_6M_CHG", "2020-03"): -1, ("DGS10_6M_CHG", "2022-01"): +1,
    ("DXY_3M_CHG", "2020-03"): -1,   ("DXY_3M_CHG", "2022-01"): +1,
}

FLIP_PENALTY = 0.4
WINDOW_BEFORE = 3   # months before event we accept "early detection"
WINDOW_AFTER = 18   # months after event we accept "late detection"


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
    upper = mid + mult * atr
    lower = mid - mult * atr
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

        # Detection window
        win_start = event_date - pd.DateOffset(months=WINDOW_BEFORE)
        win_end = event_date + pd.DateOffset(months=WINDOW_AFTER)
        window = df[(df.index >= win_start) & (df.index <= win_end)]

        # Find first row in window with correct direction
        correct = window[window["direction"] == expected]
        if correct.empty:
            lags.append(WINDOW_AFTER + 5)  # missed event
        else:
            first_correct = correct.index[0]
            lag = max(0.0, (first_correct - event_date).days / 30.44)
            lags.append(lag)

    avg_lag = float(np.mean(lags)) if lags else WINDOW_AFTER + 5
    score = -avg_lag - flip_count * FLIP_PENALTY
    return {
        "period": period, "mult": mult, "smoothing": smoothing,
        "flip_count": flip_count, "avg_lag": avg_lag,
        "lag_2020": lags[0] if len(lags) > 0 else None,
        "lag_2022": lags[1] if len(lags) > 1 else None,
        "score": score,
    }


def main() -> int:
    print("Loading raw + computing derived series...")
    walcl_raw = to_month(load_raw("WALCL")) / 1_000_000
    wtregen = to_month(load_raw("WTREGEN")) / 1_000_000
    rrp = to_month(load_raw("RRPONTSYD")) / 1_000
    netliq = (walcl_raw - wtregen - rrp).dropna()
    netliq.name = "NETLIQ"

    m2 = load_raw("M2SL")
    m2.index = m2.index.to_period("M").to_timestamp("M")
    m2 = m2.sort_index()
    m2_growth = (m2.pct_change(12) * 100).dropna()

    dgs10 = to_month(load_raw("DGS10"))
    dgs10_6m_chg = (dgs10 - dgs10.shift(6)).dropna() * 100   # bps

    dxy = to_month(load_raw("DX-Y.NYB"), "last")
    dxy_3m_chg = (dxy.pct_change(3) * 100).dropna()

    variables = {
        "WALCL": walcl_raw,
        "NETLIQ": netliq,
        "M2_GROWTH": m2_growth,
        "DGS10_6M_CHG": dgs10_6m_chg,
        "DXY_3M_CHG": dxy_3m_chg,
    }

    print("\nVariable ranges:")
    for n, s in variables.items():
        print(f"  {n:<14} {s.index.min().date()} -> {s.index.max().date()}  N={len(s)}")

    periods = [5, 7, 10, 12, 15, 18, 24, 30]
    mults = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
    smoothings = ["raw", "ma3", "ma6"]
    print(f"\nGrid: {len(periods)*len(mults)*len(smoothings)} combos per variable, "
          f"{len(variables)} variables = {len(periods)*len(mults)*len(smoothings)*len(variables)} evals")

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

        print(f"\n{'='*90}")
        print(f"{vname} — top 8 (by score)")
        print('='*90)
        print(f"{'Period':>7} {'Mult':>5} {'Smooth':>7} | {'Flips':>5} | "
              f"{'Lag2020':>8} {'Lag2022':>8} {'AvgLag':>7} | {'Score':>7}")
        print("-" * 80)
        for _, r in df.head(8).iterrows():
            print(f"{int(r['period']):>7} {r['mult']:>5.1f} {r['smoothing']:>7} | "
                  f"{int(r['flip_count']):>5} | "
                  f"{r['lag_2020']:>7.1f}m {r['lag_2022']:>7.1f}m "
                  f"{r['avg_lag']:>6.1f}m | {r['score']:>+6.2f}")

    combined = pd.concat({k: v for k, v in all_results.items()}, names=["variable"]).reset_index()
    combined.to_csv(DATA / "trend_tuning_v2_grid.csv", index=False)

    print("\n" + "=" * 90)
    print("BEST PARAMS PER VARIABLE")
    print("=" * 90)
    print(f"{'Variable':<14} {'Period':>7} {'Mult':>5} {'Smooth':>7} | "
          f"{'Flips':>5} {'Lag2020':>8} {'Lag2022':>8}")
    print("-" * 80)
    for vname, df in all_results.items():
        best = df.iloc[0]
        print(f"{vname:<14} {int(best['period']):>7} {best['mult']:>5.1f} {best['smoothing']:>7} | "
              f"{int(best['flip_count']):>5} "
              f"{best['lag_2020']:>7.1f}m {best['lag_2022']:>7.1f}m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
