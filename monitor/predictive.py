"""Predictive Leading Signals Panel — V5.

The Liquidity Trend Panel is a REGIME CLASSIFIER (Fed mostly reacts to markets,
not predicts them). This panel is different — it tracks signals that
historically LED SPX peaks/troughs by 6-9 months on average.

Validated in research/14_lead_lag.py against 5 SPX peaks and 5 troughs:

  YC_TREND          5/5 peaks (-8.4m avg lead) — yield curve trend
  NDX_RS_6M_TREND   5/5 peaks (-8.4m avg lead) — tech leadership 6m
  SOX_RS_6M_TREND   4/5 peaks (-8.3m avg lead) — semis leadership 6m
  DXY_TREND         4/5 peaks (-8.5m avg lead) — USD trend
  RUT_RS_BLOWOFF    3/5 peaks (-6.3m), 5/5 troughs — small caps

A "warning score" tracks how many leading signals are currently in WARNING
direction. Historical pattern: before SPX peaks, ≥3 leading signals were in
warning direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .trend import supertrend, _to_month, _fetch_fred, _fetch_yahoo, _m2_align


# Historical SPX peaks (used for chart annotation only — not for prediction)
SPX_PEAKS_HIST = {
    "2000-03": pd.Timestamp("2000-03-31"),
    "2007-10": pd.Timestamp("2007-10-31"),
    "2018-09": pd.Timestamp("2018-09-30"),
    "2020-02": pd.Timestamp("2020-02-29"),
    "2022-01": pd.Timestamp("2022-01-31"),
}
SPX_TROUGHS_HIST = {
    "2002-10": pd.Timestamp("2002-10-31"),
    "2009-03": pd.Timestamp("2009-03-31"),
    "2018-12": pd.Timestamp("2018-12-31"),
    "2020-03": pd.Timestamp("2020-03-31"),
    "2022-10": pd.Timestamp("2022-10-31"),
}


@dataclass
class PredictiveSignal:
    name: str
    short_name: str
    description: str
    series: pd.Series            # underlying derived series (e.g., NDX/SPX 6m RS)
    direction_series: pd.Series  # +1 (warning) / -1 (setup) / 0
    current_direction: int
    current_value: float
    last_flip_date: pd.Timestamp | None
    months_since_flip: float | None
    peak_detection_rate: str     # e.g., "5/5"
    peak_avg_lead_m: float       # average months of lead at SPX peaks
    trough_detection_rate: str
    trough_avg_lead_m: float


def expanding_percentile(s: pd.Series, min_history: int = 60) -> pd.Series:
    return s.dropna().expanding(min_history).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def st_direction(series: pd.Series, period: int, mult: float,
                  invert: bool = False) -> pd.Series:
    """Compute SuperTrend direction, optionally inverted so +1 = warning."""
    df = supertrend(series.dropna(), period=period, mult=mult)
    d = df["direction"]
    return -d if invert else d


def build_predictive_signals() -> dict[str, PredictiveSignal]:
    """Fetch underlying data + build 5 leading signals with current state."""
    # Fetch
    spx = _to_month(_fetch_yahoo("^GSPC"), "last")
    ndx = _to_month(_fetch_yahoo("^NDX"), "last")
    sox = _to_month(_fetch_yahoo("^SOX"), "last")
    rut = _to_month(_fetch_yahoo("^RUT"), "last")
    dxy = _to_month(_fetch_yahoo("DX-Y.NYB"), "last")
    dgs10 = _to_month(_fetch_fred("DGS10"), "mean")
    dgs3mo = _to_month(_fetch_fred("DGS3MO"), "mean")

    signals: dict[str, PredictiveSignal] = {}

    # 1. YC_TREND — yield curve direction (DOWN = warning)
    yc = (dgs10 - dgs3mo).dropna()
    d_yc = -st_direction(yc, period=12, mult=3.0)  # invert because YC DOWN = warning
    signals["YC_TREND"] = _build_predictive_state(
        "YC_TREND", "Yield curve (10Y−3M) trend",
        "Direction of the 10Y−3M Treasury spread. Steepening = setup, flattening/inverting = warning.",
        yc, d_yc,
        peak_rate="5/5", peak_lead=-8.4, trough_rate="4/5", trough_lead=-9.2,
    )

    # 2. NDX_RS_6M_TREND — NDX/SPX 6m RS direction (DOWN = warning)
    ndx_rs_6m = ((ndx / spx).pct_change(6) * 100).dropna()
    d_ndx = -st_direction(ndx_rs_6m, period=10, mult=3.0)
    signals["NDX_RS_6M_TREND"] = _build_predictive_state(
        "NDX_RS_6M_TREND", "NDX/SPX 6m relative strength trend",
        "Tech leadership 6-month rate-of-change. NDX RS DOWN = warning.",
        ndx_rs_6m, d_ndx,
        peak_rate="5/5", peak_lead=-8.4, trough_rate="4/5", trough_lead=-6.2,
    )

    # 3. SOX_RS_6M_TREND
    sox_rs_6m = ((sox / spx).pct_change(6) * 100).dropna()
    d_sox = -st_direction(sox_rs_6m, period=10, mult=3.0)
    signals["SOX_RS_6M_TREND"] = _build_predictive_state(
        "SOX_RS_6M_TREND", "SOX/SPX 6m relative strength trend",
        "Semiconductor leadership 6m RoC. SOX RS DOWN = warning.",
        sox_rs_6m, d_sox,
        peak_rate="4/5", peak_lead=-8.3, trough_rate="4/5", trough_lead=-7.3,
    )

    # 4. DXY_TREND — DXY 6m %change direction (UP = warning)
    dxy_6m = (dxy.pct_change(6) * 100).dropna()
    d_dxy = st_direction(dxy_6m, period=10, mult=3.0)
    signals["DXY_TREND"] = _build_predictive_state(
        "DXY_TREND", "DXY 6m %change trend",
        "USD strength trend (6m %change). Rising USD trend = warning.",
        dxy_6m, d_dxy,
        peak_rate="4/5", peak_lead=-8.5, trough_rate="5/5", trough_lead=-5.0,
    )

    # 5. RUT_RS_BLOWOFF — Russell 3m RS percentile (HIGH = blow-off warning)
    rut_rs_3m = ((rut / spx).pct_change(3) * 100).dropna()
    pct_rut = expanding_percentile(rut_rs_3m)
    d_rut = pd.Series(0, index=pct_rut.index, dtype=int)
    d_rut[pct_rut >= 0.80] = +1
    d_rut[pct_rut <= 0.20] = -1
    signals["RUT_RS_BLOWOFF"] = _build_predictive_state(
        "RUT_RS_BLOWOFF", "Russell/SPX blow-off detector",
        "Small-cap 3m RS percentile. HIGH = blow-off top warning, LOW = trough setup.",
        rut_rs_3m, d_rut,
        peak_rate="3/5", peak_lead=-6.3, trough_rate="5/5", trough_lead=-3.4,
    )

    return signals


def _build_predictive_state(name, short_name, description, series, direction,
                              peak_rate, peak_lead, trough_rate, trough_lead):
    direction = direction.dropna()
    if direction.empty:
        current_dir = 0
        last_flip = None
        months_since = None
        current_value = float("nan")
    else:
        current_dir = int(direction.iloc[-1])
        current_value = float(series.dropna().iloc[-1])
        diff = direction.diff().abs()
        flips = direction[diff > 0]
        last_flip = flips.index[-1] if not flips.empty else None
        months_since = ((direction.index[-1] - last_flip).days / 30.44
                          if last_flip is not None else None)
    return PredictiveSignal(
        name=name, short_name=short_name, description=description,
        series=series, direction_series=direction,
        current_direction=current_dir, current_value=current_value,
        last_flip_date=last_flip, months_since_flip=months_since,
        peak_detection_rate=peak_rate, peak_avg_lead_m=peak_lead,
        trough_detection_rate=trough_rate, trough_avg_lead_m=trough_lead,
    )


def warning_score(signals: dict[str, PredictiveSignal]) -> dict:
    """Aggregate score: how many leading signals are currently in WARNING vs SETUP direction."""
    warning_count = sum(1 for s in signals.values() if s.current_direction == +1)
    setup_count = sum(1 for s in signals.values() if s.current_direction == -1)
    neutral_count = sum(1 for s in signals.values() if s.current_direction == 0)
    n_total = warning_count + setup_count + neutral_count
    if warning_count >= 3:
        regime = "PEAK_WARNING"
    elif setup_count >= 3:
        regime = "TROUGH_SETUP"
    else:
        regime = "MIXED"
    return {
        "warning_count": warning_count,
        "setup_count": setup_count,
        "neutral_count": neutral_count,
        "n_total": n_total,
        "regime": regime,
        "warning_signals": [n for n, s in signals.items() if s.current_direction == +1],
        "setup_signals": [n for n, s in signals.items() if s.current_direction == -1],
        "captured_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
