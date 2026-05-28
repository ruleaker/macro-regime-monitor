"""V5.3 — STRICT forward test of supposedly-predictive signals.

User correctly called out that the previous lead-lag analysis had lookback
bias: I gave it the historical SPX peak dates and asked 'did the signal show
warning in a window around each peak'. That's not a real prediction test —
the dates were hand-picked.

The honest test: for each signal flip to warning direction, ask:

  Did SPX actually have a meaningful drawdown in the next 6/12/18 months?

Then compute:
  - PRECISION: of all warning flips, how many were followed by drawdown
                (i.e. how often is the signal 'right when it cries wolf')
  - RECALL: of all actual SPX drawdowns, how many were preceded by warning
            (i.e. how often does the signal catch real events)
  - BASE RATE: how often does SPX have drawdown anyway (null model)

A signal is genuinely predictive ONLY if precision > base rate by a
meaningful margin AND recall is high. Otherwise it's noise.

Drawdown definition: SPX's forward-N-month minimum return is below -X%.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

DRAWDOWN_THRESHOLD = -0.10        # -10% drawdown counts as a "real event"
RECOVERY_BUFFER = 6               # months — collapse multiple events into one if within
LOOKAHEAD_MONTHS_LIST = [6, 12, 18]


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


def find_warning_flips(direction_series: pd.Series, expected_dir: int) -> list[pd.Timestamp]:
    """Return list of dates where direction changed to expected_dir."""
    d = direction_series.dropna()
    diff = d.diff()
    flips = d[(diff != 0) & (d == expected_dir)]
    return list(flips.index)


def spx_drawdown_events(spx_monthly: pd.Series, threshold: float = DRAWDOWN_THRESHOLD,
                          buffer: int = RECOVERY_BUFFER) -> list[pd.Timestamp]:
    """Find all dates where SPX subsequently had a drawdown >= |threshold|.

    Returns the PEAK date (start of drawdown), not the trough.
    Collapses multiple events within `buffer` months.
    """
    s = spx_monthly.dropna()
    arr = s.values
    n = len(arr)
    peaks: list[pd.Timestamp] = []
    last_peak_idx = -100

    for i in range(n):
        # Look forward to find the lowest SPX in next 24 months
        end = min(i + 24, n)
        window = arr[i:end]
        if len(window) < 6:
            continue
        # Was there a >=threshold drawdown from arr[i]?
        worst = window.min()
        if (worst / arr[i] - 1) <= threshold:
            # This is a peak if no recent peak within buffer
            if i - last_peak_idx > buffer:
                peaks.append(s.index[i])
                last_peak_idx = i
    return peaks


def did_drawdown_follow(spx: pd.Series, flip_date: pd.Timestamp,
                          lookahead_m: int, threshold: float = DRAWDOWN_THRESHOLD) -> bool:
    """Does SPX have a >=threshold drawdown in the next lookahead_m months?"""
    end_date = flip_date + pd.DateOffset(months=lookahead_m)
    fwd = spx[(spx.index >= flip_date) & (spx.index <= end_date)]
    if len(fwd) < 3:
        return False
    fwd_min = fwd.min()
    fwd_min_return = fwd_min / spx.loc[flip_date] - 1 if flip_date in spx.index else \
                      fwd_min / spx.iloc[spx.index.get_indexer([flip_date], method="bfill")[0]] - 1
    return fwd_min_return <= threshold


def evaluate_signal(name: str, direction_series: pd.Series, spx: pd.Series,
                     expected_dir: int = +1, lookahead_m: int = 12) -> dict:
    """Run strict forward test:
       PRECISION = fraction of warning flips followed by drawdown
       RECALL = fraction of real peaks preceded by warning within lookahead window
       BASE RATE = fraction of all months where drawdown follows
    """
    flips = find_warning_flips(direction_series, expected_dir)
    flips = [f for f in flips if f >= pd.Timestamp("1999-01-01")]   # post-1999 sample

    # Precision: of all flips, how many had drawdown follow?
    if flips:
        precision_hits = sum(1 for f in flips if did_drawdown_follow(spx, f, lookahead_m))
        precision = precision_hits / len(flips)
    else:
        precision = float("nan")
        precision_hits = 0

    # Recall: of all real drawdown peaks, how many had signal in warning within last `lookahead_m`?
    real_peaks = spx_drawdown_events(spx)
    real_peaks = [p for p in real_peaks if p >= pd.Timestamp("1999-01-01")]

    recall_hits = 0
    for peak in real_peaks:
        window_start = peak - pd.DateOffset(months=lookahead_m)
        # Check if direction was in warning state at ANY point in lookahead window before peak
        # NOTE: this still has the same lookback bias problem. To be truly fair:
        # check if there was a flip to warning in that window.
        flips_in_window = [f for f in flips if window_start <= f <= peak]
        if flips_in_window:
            recall_hits += 1
    recall = recall_hits / len(real_peaks) if real_peaks else float("nan")

    # Base rate: fraction of months where drawdown follows
    all_months = direction_series.dropna().index
    all_months = [m for m in all_months if m >= pd.Timestamp("1999-01-01") and
                    m + pd.DateOffset(months=lookahead_m) <= direction_series.index[-1]]
    base_hits = sum(1 for m in all_months if did_drawdown_follow(spx, m, lookahead_m))
    base_rate = base_hits / len(all_months) if all_months else float("nan")

    # Lift = precision / base_rate (>1 = signal adds value)
    lift = precision / base_rate if base_rate > 0 else float("nan")

    return {
        "signal": name,
        "lookahead_m": lookahead_m,
        "n_flips_to_warning": len(flips),
        "n_real_peaks": len(real_peaks),
        "precision": precision,
        "recall": recall,
        "base_rate": base_rate,
        "lift": lift,
        "precision_hits": precision_hits,
        "recall_hits": recall_hits,
    }


def main() -> int:
    print("Loading...")
    spx = to_month(load_raw("GSPC"), "last")
    print(f"  SPX monthly: {spx.index.min().date()} -> {spx.index.max().date()}  N={len(spx)}")

    # First identify real drawdown events (peaks)
    real_peaks = spx_drawdown_events(spx)
    real_peaks = [p for p in real_peaks if p >= pd.Timestamp("1999-01-01")]
    print(f"\n  Real SPX drawdown peaks (≥10% drawdown follows within 24m), post-1999:")
    for p in real_peaks:
        end = min(spx.index.get_indexer([p])[0] + 24, len(spx))
        window = spx.iloc[spx.index.get_indexer([p])[0]:end]
        dd = (window.min() / window.iloc[0] - 1) * 100
        print(f"    {p.strftime('%Y-%m')}  forward drawdown {dd:+.1f}%")
    print(f"  Total real peaks: {len(real_peaks)}")

    # Build candidate signals
    m2 = load_raw("M2SL")
    m2.index = m2.index.to_period("M").to_timestamp("M")
    m2 = m2.sort_index()
    dgs10 = to_month(load_raw("DGS10"))
    dgs3mo = to_month(load_raw("DGS3MO"))
    dxy = to_month(load_raw("DX-Y.NYB"), "last")
    ndx = to_month(load_raw("NDX"), "last")
    sox = to_month(load_raw("SOX"), "last")
    rut = to_month(load_raw("RUT"), "last")

    candidates = {}

    # YC trend (YC DOWN = warning, so invert from raw SuperTrend direction)
    yc = (dgs10 - dgs3mo).dropna()
    candidates["YC_TREND"] = -supertrend(yc, 12, 3.0)["direction"]

    # NDX/SPX 6m RS (DOWN = warning, invert)
    ndx_rs_6m = ((ndx / spx).pct_change(6) * 100).dropna()
    candidates["NDX_RS_6M_TREND"] = -supertrend(ndx_rs_6m, 10, 3.0)["direction"]

    # SOX/SPX 6m RS
    sox_rs_6m = ((sox / spx).pct_change(6) * 100).dropna()
    candidates["SOX_RS_6M_TREND"] = -supertrend(sox_rs_6m, 10, 3.0)["direction"]

    # DXY trend (UP = warning, no invert)
    dxy_6m = (dxy.pct_change(6) * 100).dropna()
    candidates["DXY_TREND"] = supertrend(dxy_6m, 10, 3.0)["direction"]

    # RUT/SPX blow-off (zone signal: HIGH = warning)
    rut_rs_3m = ((rut / spx).pct_change(3) * 100).dropna()
    pct_rut = rut_rs_3m.expanding(60).apply(lambda x: float((x.iloc[-1] >= x).mean()), raw=False)
    d_rut = pd.Series(0, index=pct_rut.index, dtype=int)
    d_rut[pct_rut >= 0.80] = +1
    d_rut[pct_rut <= 0.20] = -1
    candidates["RUT_RS_BLOWOFF"] = d_rut

    # Run strict test at multiple lookahead horizons
    print("\n" + "=" * 110)
    print(f"STRICT FORWARD TEST — drawdown threshold {DRAWDOWN_THRESHOLD*100:.0f}%, post-1999")
    print("=" * 110)

    for h in LOOKAHEAD_MONTHS_LIST:
        print(f"\nLookahead horizon: {h} months")
        print(f"{'Signal':<22} {'Flips':>6} {'Precision':>10} {'Recall':>9} {'Base':>7} {'Lift':>6} {'P/R verdict':<30}")
        print("-" * 100)
        for name, direction in candidates.items():
            r = evaluate_signal(name, direction.dropna(), spx, expected_dir=+1, lookahead_m=h)
            prec = f"{r['precision']*100:.0f}%" if not pd.isna(r['precision']) else "n/a"
            rec = f"{r['recall']*100:.0f}%" if not pd.isna(r['recall']) else "n/a"
            base = f"{r['base_rate']*100:.0f}%" if not pd.isna(r['base_rate']) else "n/a"
            lift = f"{r['lift']:.2f}x" if not pd.isna(r['lift']) else "n/a"
            # Verdict
            if pd.isna(r['precision']) or pd.isna(r['lift']):
                verdict = "insufficient data"
            elif r['lift'] >= 1.5 and r['recall'] >= 0.50:
                verdict = "PREDICTIVE ★"
            elif r['lift'] >= 1.2:
                verdict = "weak signal"
            elif r['lift'] >= 0.9:
                verdict = "no edge (~base rate)"
            else:
                verdict = "WORSE than random"
            print(f"{name:<22} {r['n_flips_to_warning']:>6} {prec:>10} {rec:>9} {base:>7} {lift:>6} {verdict:<30}")

    print("\nReading:")
    print("  PRECISION = of all warning flips, fraction followed by ≥10% SPX drawdown")
    print("  RECALL    = of all real SPX drawdown events, fraction preceded by warning flip")
    print("  BASE RATE = fraction of all months that have ≥10% drawdown within window (null)")
    print("  LIFT      = precision / base rate (>1 = signal adds value)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
