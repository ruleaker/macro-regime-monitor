"""V5 — lead/lag analysis to find signals that truly LEAD SPX inflections.

Honest evaluation: a signal "predicts" SPX moves only if its direction change
historically precedes SPX peaks/troughs by a meaningful lead time.

Method:
  1. Define historical SPX peaks + troughs (drawdown > 15%).
  2. For each candidate signal, build its direction (SuperTrend or pct-rank zone).
  3. For each SPX inflection, find the signal's most recent direction change
     within [-12m, +3m] of the event.
  4. Lead time = signal_change_date - spx_inflection_date (negative = leads).
  5. Score signal by: average lead time + consistency (low std of lead times).

Candidates: yield curve inversion, margin debt zone, NDX/SOX/RUT RS trend,
DXY trend, real yield, etc. — many more than the trend panel currently uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

# Historical SPX major peaks (followed by >=15% drawdown) and troughs
SPX_PEAKS = {
    "2000-03_dotcom_peak":   pd.Timestamp("2000-03-31"),
    "2007-10_gfc_peak":      pd.Timestamp("2007-10-31"),
    "2018-09_taper_peak":    pd.Timestamp("2018-09-30"),
    "2020-02_covid_peak":    pd.Timestamp("2020-02-29"),
    "2022-01_qt_peak":       pd.Timestamp("2022-01-31"),
}
SPX_TROUGHS = {
    "2002-10_dotcom_low":    pd.Timestamp("2002-10-31"),
    "2009-03_gfc_low":       pd.Timestamp("2009-03-31"),
    "2018-12_taper_low":     pd.Timestamp("2018-12-31"),
    "2020-03_covid_low":     pd.Timestamp("2020-03-31"),
    "2022-10_qt_low":        pd.Timestamp("2022-10-31"),
}


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


def expanding_percentile(s: pd.Series, min_history: int = 60) -> pd.Series:
    return s.dropna().expanding(min_history).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def zone_signal(series: pd.Series, high_threshold: float = 0.80,
                 low_threshold: float = 0.20) -> pd.Series:
    """Map signal to discrete bear (+1 at HIGH) / neutral (0) / bull (-1 at LOW) labels."""
    pct = expanding_percentile(series)
    out = pd.Series(0, index=pct.index)
    out[pct >= high_threshold] = +1
    out[pct <= low_threshold] = -1
    return out


def find_lead_time(signal_direction: pd.Series, event_date: pd.Timestamp,
                    expected_direction: int, search_before: int = 12,
                    search_after: int = 3) -> tuple[float | None, pd.Timestamp | None]:
    """Find the signal's most recent flip TO expected direction within window.
    Returns (lead_months, flip_date). lead_months negative = leads, positive = lags.
    """
    win_start = event_date - pd.DateOffset(months=search_before)
    win_end = event_date + pd.DateOffset(months=search_after)
    window = signal_direction[(signal_direction.index >= win_start) &
                                (signal_direction.index <= win_end)]
    if window.empty:
        return None, None

    # Find flips (direction change) in window
    diff = window.diff()
    flips_to_expected = window[(diff != 0) & (window == expected_direction)]
    if flips_to_expected.empty:
        return None, None

    # Most recent flip BEFORE event (most useful)
    before_event = flips_to_expected[flips_to_expected.index <= event_date]
    if not before_event.empty:
        flip_date = before_event.index[-1]
    else:
        flip_date = flips_to_expected.index[0]

    lead_months = (flip_date - event_date).days / 30.44
    return lead_months, flip_date


def analyze_signal(name: str, direction_series: pd.Series,
                    peaks: dict, troughs: dict) -> dict:
    """For each peak event, expected dir = +1 (bear/warning).
    For each trough event, expected dir = -1 (bull/setup).
    """
    peak_leads = []
    trough_leads = []
    for event_key, event_date in peaks.items():
        lead, _ = find_lead_time(direction_series, event_date, +1)
        if lead is not None:
            peak_leads.append(lead)
    for event_key, event_date in troughs.items():
        lead, _ = find_lead_time(direction_series, event_date, -1)
        if lead is not None:
            trough_leads.append(lead)

    return {
        "name": name,
        "n_peaks_detected": len(peak_leads),
        "n_peaks_total": len(peaks),
        "n_troughs_detected": len(trough_leads),
        "n_troughs_total": len(troughs),
        "peak_avg_lead": float(np.mean(peak_leads)) if peak_leads else None,
        "peak_std_lead": float(np.std(peak_leads)) if peak_leads else None,
        "trough_avg_lead": float(np.mean(trough_leads)) if trough_leads else None,
        "trough_std_lead": float(np.std(trough_leads)) if trough_leads else None,
        "peak_leads": peak_leads,
        "trough_leads": trough_leads,
    }


def main() -> int:
    print("Loading...")
    spx = to_month(load_raw("GSPC"), "last")
    m2 = load_raw("M2SL")
    m2.index = m2.index.to_period("M").to_timestamp("M")
    m2 = m2.sort_index()
    margin = pd.read_csv(DATA / "FINRA_MARGIN_DEBT.csv", parse_dates=["date"]).set_index("date")["value"]
    margin = margin.astype(float).sort_index()
    walcl = to_month(load_raw("WALCL")) / 1_000_000
    wtregen = to_month(load_raw("WTREGEN")) / 1_000_000
    rrp = to_month(load_raw("RRPONTSYD")) / 1_000
    netliq = (walcl - wtregen - rrp).dropna()
    dgs10 = to_month(load_raw("DGS10"))
    dgs3mo = to_month(load_raw("DGS3MO"))
    dxy = to_month(load_raw("DX-Y.NYB"), "last")
    ndx = to_month(load_raw("NDX"), "last")
    sox = to_month(load_raw("SOX"), "last")
    rut = to_month(load_raw("RUT"), "last")
    spx_m = to_month(load_raw("GSPC"), "last")

    # Build candidate signals
    candidates = {}

    # MARGIN_DEBT_M2_ZONE: high=warning, low=setup
    m2_m = m2.copy()
    margin_m2 = (margin.reindex(margin.index.union(m2_m.index)).ffill() / m2_m * 1000).dropna()
    candidates["MARGIN_M2_ZONE"] = zone_signal(margin_m2)

    # YIELD_CURVE_INVERSION: when YC < 0
    yc = (dgs10 - dgs3mo).dropna()
    yc_inv = (yc < 0).astype(int).replace({0: -1, 1: +1})  # +1 when inverted (warning)
    candidates["YIELD_CURVE_INV"] = yc_inv

    # YIELD_CURVE_TREND (SuperTrend)
    yc_st = supertrend(yc, period=12, mult=3.0)["direction"]
    candidates["YC_TREND"] = -yc_st  # invert because YC going DOWN = warning

    # NDX/SPX 6m RS trend
    ndx_rs_6m = ((ndx / spx_m).pct_change(6) * 100).dropna()
    ndx_st = supertrend(ndx_rs_6m, period=10, mult=3.0)["direction"]
    candidates["NDX_RS_6M_TREND"] = -ndx_st  # NDX RS DOWN = warning

    # SOX/SPX 6m RS trend
    sox_rs_6m = ((sox / spx_m).pct_change(6) * 100).dropna()
    sox_st = supertrend(sox_rs_6m, period=10, mult=3.0)["direction"]
    candidates["SOX_RS_6M_TREND"] = -sox_st

    # RUT/SPX zone (HIGH = blow-off warning)
    rut_rs_3m = ((rut / spx_m).pct_change(3) * 100).dropna()
    candidates["RUT_RS_BLOWOFF"] = zone_signal(rut_rs_3m, high_threshold=0.80, low_threshold=0.20)

    # DXY 6m %change trend (UP = USD strength = warning)
    dxy_6m_chg = (dxy.pct_change(6) * 100).dropna()
    dxy_st = supertrend(dxy_6m_chg, period=10, mult=3.0)["direction"]
    candidates["DXY_TREND"] = dxy_st  # UP = warning (no invert)

    # 10Y yield 12m change trend (UP = tightening = warning)
    dgs10_12m_chg = ((dgs10 - dgs10.shift(12)) * 100).dropna()
    dgs10_st = supertrend(dgs10_12m_chg, period=10, mult=3.0)["direction"]
    candidates["DGS10_TREND"] = dgs10_st

    # NETLIQ trend (DOWN = warning)
    netliq_st = supertrend(netliq, period=5, mult=5.0)["direction"]
    candidates["NETLIQ_TREND"] = -netliq_st

    # WALCL trend
    walcl_st = supertrend(walcl, period=5, mult=5.0)["direction"]
    candidates["WALCL_TREND"] = -walcl_st

    print(f"\n{len(candidates)} candidate signals to analyze")
    print(f"{len(SPX_PEAKS)} SPX peaks + {len(SPX_TROUGHS)} troughs to test against")

    # Analyze each
    results = []
    for name, direction in candidates.items():
        r = analyze_signal(name, direction.dropna(), SPX_PEAKS, SPX_TROUGHS)
        results.append(r)

    # Rank by detection rate + lead time (negative = leads is good)
    print("\n" + "=" * 105)
    print("SIGNAL LEAD/LAG vs SPX peaks (warning direction +1) & troughs (setup direction -1)")
    print("=" * 105)
    print(f"{'Signal':<22} | {'P-det':>5} {'P-avg-lead':>11} {'P-std':>7} | "
          f"{'T-det':>5} {'T-avg-lead':>11} {'T-std':>7}")
    print("-" * 100)
    # Sort by peak detection rate + average lead (more negative = leads more)
    def score(r):
        ratio_p = (r["n_peaks_detected"] / r["n_peaks_total"]) if r["n_peaks_total"] else 0
        ratio_t = (r["n_troughs_detected"] / r["n_troughs_total"]) if r["n_troughs_total"] else 0
        lead_p = r["peak_avg_lead"] if r["peak_avg_lead"] is not None else 100
        return -ratio_p - ratio_t + lead_p * 0.05
    for r in sorted(results, key=score):
        p_det = f"{r['n_peaks_detected']}/{r['n_peaks_total']}"
        t_det = f"{r['n_troughs_detected']}/{r['n_troughs_total']}"
        p_lead = f"{r['peak_avg_lead']:+5.1f}m" if r['peak_avg_lead'] is not None else "n/a"
        p_std = f"{r['peak_std_lead']:>5.1f}" if r['peak_std_lead'] is not None else "n/a"
        t_lead = f"{r['trough_avg_lead']:+5.1f}m" if r['trough_avg_lead'] is not None else "n/a"
        t_std = f"{r['trough_std_lead']:>5.1f}" if r['trough_std_lead'] is not None else "n/a"
        print(f"{r['name']:<22} | {p_det:>5} {p_lead:>10} {p_std:>7} | {t_det:>5} {t_lead:>10} {t_std:>7}")

    print("\nP-avg-lead = average month-offset from SPX peak (negative = signal flipped BEFORE peak)")
    print("T-avg-lead = average month-offset from SPX trough (negative = signal flipped BEFORE trough)")

    # Per-event detail for top 3 by detection rate
    print("\n" + "=" * 105)
    print("PER-EVENT DETAIL — best leading signals")
    print("=" * 105)
    top = sorted(results, key=lambda r: -(r["n_peaks_detected"] + r["n_troughs_detected"]))[:5]
    for r in top:
        print(f"\n{r['name']}:")
        print(f"  Peak leads (months from SPX peak; negative = led):")
        for (event, _), lead in zip(SPX_PEAKS.items(), r['peak_leads']):
            print(f"    {event}: {lead:+5.1f}m")
        print(f"  Trough leads:")
        for (event, _), lead in zip(SPX_TROUGHS.items(), r['trough_leads']):
            print(f"    {event}: {lead:+5.1f}m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
