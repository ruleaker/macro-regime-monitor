"""V4 — trend / inflection detection on macro variables.

The composite indicator is slow by design — it answers "where are we in the
cycle". For event-driven trades (e.g. Fed pivot, QE start, QT shock) we need
a faster lens that fires soon after the inflection.

This script applies 3 trend-following techniques borrowed from price
technical analysis to monthly macro time series:

  1. SuperTrend (monthly, ATR-equivalent = rolling std of monthly delta)
  2. EMA crossover (fast EMA vs slow EMA)
  3. Donchian breakout (rolling high/low breakout)

Then backtests detection speed at two known regime flips:

  - 2020-03  Fed COVID easing pivot (slashing rates + QE infinity)
  - 2022-01  Fed taper + rate-hike pivot (start of QT cycle)

Tests run on these macro variables:

  WALCL       Fed total assets (weekly -> monthly mean)
  NETLIQ      Fed BS - TGA - RRP (monthly mean, trillions)
  M2_LEVEL    M2 level (monthly)
  DGS10       10Y treasury yield (monthly mean)
  DXY         ICE Dollar Index (monthly close)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

# Inflection windows (we want detection within 1-3 months of these)
INFLECTIONS = {
    "2020-03_covid_easing": {
        "date": pd.Timestamp("2020-03-15"),
        "direction": "down_for_rates_dxy / up_for_walcl_netliq_m2",
        "description": "Fed slashes rates, QE infinity, M2 explodes",
    },
    "2022-01_qt_pivot": {
        "date": pd.Timestamp("2022-01-31"),
        "direction": "up_for_rates_dxy / down_for_walcl_netliq_m2_growth",
        "description": "Fed signals rate hikes + QT begins; M2 growth turns negative",
    },
}


def load_raw(name: str) -> pd.Series:
    df = pd.read_csv(RAW / f"{name}.csv", parse_dates=["date"])
    return df.set_index("date")["value"].astype(float).sort_index()


def to_month(s: pd.Series, how: str = "mean") -> pd.Series:
    if how == "mean":
        return s.sort_index().resample("ME").mean().dropna()
    return s.sort_index().resample("ME").last().dropna()


# --- Trend techniques ---------------------------------------------------

def supertrend(series: pd.Series, period: int = 10, mult: float = 2.0) -> pd.DataFrame:
    """SuperTrend adapted to monthly macro: ATR replaced by rolling std of monthly delta.

    Returns DataFrame with columns:
      - upper, lower: band levels
      - direction:    +1 if uptrend, -1 if downtrend, 0 initial
      - level:        current band serving as support/resistance
      - flip:         True at the month the direction changed
    """
    s = series.dropna().copy()
    delta = s.diff()
    atr = delta.abs().rolling(period).mean()  # equivalent to ATR for monthly
    mid = (s + s.shift(1)) / 2
    upper_basic = mid + mult * atr
    lower_basic = mid - mult * atr

    upper = upper_basic.copy()
    lower = lower_basic.copy()
    direction = pd.Series(0, index=s.index, dtype=int)
    level = pd.Series(np.nan, index=s.index)

    for i in range(1, len(s)):
        if pd.isna(upper.iloc[i]) or pd.isna(lower.iloc[i]):
            continue
        # Smooth bands: only tighten in direction of trend
        if s.iloc[i - 1] <= upper.iloc[i - 1]:
            upper.iloc[i] = min(upper.iloc[i], upper.iloc[i - 1]) if not pd.isna(upper.iloc[i - 1]) else upper.iloc[i]
        if s.iloc[i - 1] >= lower.iloc[i - 1]:
            lower.iloc[i] = max(lower.iloc[i], lower.iloc[i - 1]) if not pd.isna(lower.iloc[i - 1]) else lower.iloc[i]

        if direction.iloc[i - 1] >= 0:
            if s.iloc[i] < lower.iloc[i]:
                direction.iloc[i] = -1
                level.iloc[i] = upper.iloc[i]
            else:
                direction.iloc[i] = 1
                level.iloc[i] = lower.iloc[i]
        else:
            if s.iloc[i] > upper.iloc[i]:
                direction.iloc[i] = 1
                level.iloc[i] = lower.iloc[i]
            else:
                direction.iloc[i] = -1
                level.iloc[i] = upper.iloc[i]

    flip = direction.diff().abs() > 0
    flip.iloc[0] = False
    return pd.DataFrame({
        "value": s,
        "upper": upper,
        "lower": lower,
        "direction": direction,
        "level": level,
        "flip": flip,
    })


def ema_cross(series: pd.Series, fast: int = 3, slow: int = 12) -> pd.DataFrame:
    """Fast/slow EMA crossover. Direction = +1 when fast > slow, else -1."""
    s = series.dropna().copy()
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    direction = (ema_fast > ema_slow).astype(int) * 2 - 1   # {-1, +1}
    flip = direction.diff().abs() > 0
    flip.iloc[0] = False
    return pd.DataFrame({
        "value": s, "ema_fast": ema_fast, "ema_slow": ema_slow,
        "direction": direction, "flip": flip,
    })


def donchian_breakout(series: pd.Series, window: int = 12) -> pd.DataFrame:
    """Donchian channel breakout. Direction = +1 after new high, -1 after new low."""
    s = series.dropna().copy()
    upper = s.rolling(window).max()
    lower = s.rolling(window).min()
    direction = pd.Series(0, index=s.index, dtype=int)
    for i in range(window, len(s)):
        if s.iloc[i] >= upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif s.iloc[i] <= lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
    flip = direction.diff().abs() > 0
    flip.iloc[0] = False
    return pd.DataFrame({
        "value": s, "upper": upper, "lower": lower,
        "direction": direction, "flip": flip,
    })


# --- Backtest infrastructure --------------------------------------------

def first_flip_after(df: pd.DataFrame, anchor: pd.Timestamp, expected_dir: int | None = None) -> pd.Timestamp | None:
    """Find first flip in df at or after anchor, optionally matching expected direction."""
    sub = df.loc[anchor:]
    flips = sub[sub["flip"]]
    if expected_dir is not None:
        flips = flips[flips["direction"] == expected_dir]
    return flips.index[0] if not flips.empty else None


def months_between(d1: pd.Timestamp, d2: pd.Timestamp) -> float:
    if d2 is None or d1 is None:
        return float("nan")
    return (d2 - d1).days / 30.44


def evaluate_technique(name: str, df: pd.DataFrame, var_name: str,
                        events: dict) -> list[dict]:
    rows = []
    for ev_key, ev in events.items():
        # Determine expected direction based on variable + event
        expected = None
        if ev_key.endswith("covid_easing"):
            expected = {
                "WALCL": +1, "NETLIQ": +1, "M2_LEVEL": +1, "M2_GROWTH_YOY": +1,
                "DGS10": -1, "DXY": -1,
            }.get(var_name, None)
        elif ev_key.endswith("qt_pivot"):
            expected = {
                "WALCL": -1, "NETLIQ": -1, "M2_LEVEL": -1, "M2_GROWTH_YOY": -1,
                "DGS10": +1, "DXY": +1,
            }.get(var_name, None)

        flip_date = first_flip_after(df, ev["date"], expected_dir=expected)
        lag_m = months_between(ev["date"], flip_date)
        rows.append({
            "technique": name,
            "variable": var_name,
            "event": ev_key,
            "event_date": ev["date"].strftime("%Y-%m"),
            "expected_dir": expected,
            "detected_date": flip_date.strftime("%Y-%m") if flip_date else "never",
            "lag_months": round(lag_m, 1) if not pd.isna(lag_m) else None,
        })
    return rows


def main() -> int:
    print("Loading macro variables...")
    walcl = to_month(load_raw("WALCL"), "mean") / 1_000_000   # M$ -> T$
    wtregen = to_month(load_raw("WTREGEN"), "mean") / 1_000_000
    rrpontsyd = to_month(load_raw("RRPONTSYD"), "mean") / 1_000
    netliq = (walcl - wtregen - rrpontsyd).dropna()
    netliq.name = "NETLIQ"

    m2 = load_raw("M2SL").copy()
    m2.index = m2.index.to_period("M").to_timestamp("M")
    m2 = m2.sort_index()
    m2_growth = m2.pct_change(12) * 100  # YoY %

    dgs10 = to_month(load_raw("DGS10"), "mean")
    dxy = to_month(load_raw("DX-Y.NYB"), "last")

    variables = {
        "WALCL": walcl,
        "NETLIQ": netliq,
        "M2_LEVEL": m2,
        "M2_GROWTH_YOY": m2_growth.dropna(),
        "DGS10": dgs10,
        "DXY": dxy,
    }

    for vname, series in variables.items():
        print(f"  {vname:<15} {series.index.min().strftime('%Y-%m')} -> "
              f"{series.index.max().strftime('%Y-%m')}  N={len(series)}")

    techniques = {
        "SuperTrend(10, 2.0)": lambda s: supertrend(s, period=10, mult=2.0),
        "EMA(3,12)":           lambda s: ema_cross(s, fast=3, slow=12),
        "EMA(6,24)":           lambda s: ema_cross(s, fast=6, slow=24),
        "Donchian(12)":        lambda s: donchian_breakout(s, window=12),
    }

    all_rows = []
    for vname, series in variables.items():
        print(f"\nApplying techniques to {vname}...")
        for tname, fn in techniques.items():
            try:
                df = fn(series)
                rows = evaluate_technique(tname, df, vname, INFLECTIONS)
                all_rows.extend(rows)
            except Exception as e:
                print(f"  [error] {tname}: {e}")
                continue

    result = pd.DataFrame(all_rows)
    result.to_csv(DATA / "trend_inflection_test.csv", index=False)

    # Print results grouped by event then variable
    for ev_key in INFLECTIONS:
        print("\n" + "=" * 90)
        print(f"Event: {ev_key} ({INFLECTIONS[ev_key]['date'].strftime('%Y-%m-%d')})")
        print(f"   {INFLECTIONS[ev_key]['description']}")
        print("=" * 90)
        sub = result[result["event"] == ev_key].copy()
        print(f"{'Variable':<16} {'Technique':<24} {'Expected':>4}  {'Detected':>9}  {'Lag (m)':>8}")
        print("-" * 80)
        for vname in variables.keys():
            sub_v = sub[sub["variable"] == vname]
            for _, r in sub_v.iterrows():
                lag = f"{r['lag_months']:.1f}" if r["lag_months"] is not None else "n/a"
                exp = "+" if r["expected_dir"] == 1 else "-" if r["expected_dir"] == -1 else "?"
                print(f"{r['variable']:<16} {r['technique']:<24} {exp:>4}  {r['detected_date']:>9}  {lag:>7}m")

    # Summary: which technique was fastest per variable
    print("\n" + "=" * 90)
    print("SUMMARY: Best technique per (variable, event) by detection speed")
    print("=" * 90)
    print(f"{'Variable':<16} {'Event':<28} {'Best Technique':<24} {'Lag (m)':>8}")
    print("-" * 80)
    for vname in variables.keys():
        for ev_key in INFLECTIONS:
            sub = result[(result["variable"] == vname) & (result["event"] == ev_key)]
            sub = sub[sub["lag_months"].notna() & (sub["lag_months"] >= 0)]
            if sub.empty:
                continue
            best = sub.sort_values("lag_months").iloc[0]
            print(f"{vname:<16} {ev_key:<28} {best['technique']:<24} {best['lag_months']:>7.1f}m")

    return 0


if __name__ == "__main__":
    sys.exit(main())
