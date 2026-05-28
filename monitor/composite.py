"""Composite cycle indicator for the production dashboard.

Combines validated signals into a single 'top warning vs bottom setup' score.
Designed as a medium-term (swing) auxiliary indicator — extremes are real,
mid-range is honestly inconclusive.

See research/6_composite.py for the construction details and validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .signals import Signal

MIN_HISTORY_MONTHS = 60

# Components: (signal_name, weight, invert_sign)
# invert_sign=True means "higher signal = LESS dangerous" so we flip
COMPONENTS = [
    ("MARGIN_M2",  1.0, False),
    ("NDX_SPX_RS", 0.6, True),
    ("SOX_SPX_RS", 0.6, True),
    ("RUT_SPX_RS", 0.4, False),
]

EXTREME_LOW_PCT = 0.10
EXTREME_HIGH_PCT = 0.90

# Historical conditional stats from research/6_composite.py
# (Hard-coded because the validation set is stable across runs of the same code)
DECILE_STATS = [
    # (decile_label, n, mean_pct, hit_rate, vs_full_pp)
    ("0-10%",   14, 31.6, 100, +22.0),
    ("10-30%",  52, 17.3,  85,  +7.6),
    ("30-50%",  71, 10.0,  83,  +0.3),
    ("50-70%",  85, 10.4,  84,  +0.7),
    ("70-90%", 109,  6.7,  73,  -2.9),
    ("90-100%", 24,-10.1,  29, -19.7),
]


@dataclass
class CompositeState:
    series: pd.Series           # full historical composite values
    percentile_series: pd.Series  # historical percentile of composite values
    current_value: float
    current_percentile: float
    zone: str                   # 'EXTREME_LOW' | 'LOW' | 'MID' | 'HIGH' | 'EXTREME_HIGH'
    n_components: int           # how many of the 4 components contributed this month
    components_used: list[str]

    @property
    def zone_label(self) -> str:
        return {
            "EXTREME_LOW": "EXTREME LOW (setup / bottom-leaning)",
            "LOW": "LOW (leaning setup)",
            "MID": "MID (inconclusive)",
            "HIGH": "HIGH (leaning warning)",
            "EXTREME_HIGH": "EXTREME HIGH (warning / top-leaning)",
        }[self.zone]

    @property
    def zone_label_zh(self) -> str:
        return {
            "EXTREME_LOW": "极低区（底部 setup / 抄底辅助）",
            "LOW": "偏低区（倾向 setup）",
            "MID": "中性区（信号不明确）",
            "HIGH": "偏高区（倾向警告）",
            "EXTREME_HIGH": "极高区（顶部警告 / 逃顶辅助）",
        }[self.zone]


def expanding_percentile(s: pd.Series) -> pd.Series:
    s = s.dropna()
    return s.expanding(MIN_HISTORY_MONTHS).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def build_composite_series(signals_dict: dict[str, Signal]) -> CompositeState:
    """Compute the composite series from production signals."""
    aligned: dict[str, pd.Series] = {}
    weight_by_name: dict[str, float] = {}
    invert_by_name: dict[str, bool] = {}

    for name, weight, invert in COMPONENTS:
        if name not in signals_dict:
            continue
        sig = signals_dict[name]
        pct = expanding_percentile(sig.series)
        aligned[name] = pct
        weight_by_name[name] = weight
        invert_by_name[name] = invert

    if not aligned:
        raise RuntimeError("No composite components available")

    # Common monthly index across all components
    full_idx = sorted(set().union(*(s.index for s in aligned.values())))
    full_idx = pd.DatetimeIndex(full_idx)

    centered_cols: dict[str, pd.Series] = {}
    for name, pct in aligned.items():
        # Tolerate up to 3 months of reporting lag
        reindexed = pct.reindex(full_idx).ffill(limit=3)
        c = (reindexed - 0.5) * 2.0
        if invert_by_name[name]:
            c = -c
        centered_cols[name] = c

    combined = pd.DataFrame(centered_cols)
    weight_arr = np.array([weight_by_name[c] for c in combined.columns])
    mask = combined.notna().to_numpy().astype(float)
    weighted_vals = combined.fillna(0).to_numpy() * weight_arr
    weight_sum_row = (mask * weight_arr).sum(axis=1)
    composite_vals = np.where(
        weight_sum_row > 0,
        weighted_vals.sum(axis=1) / weight_sum_row,
        np.nan,
    )
    composite = pd.Series(composite_vals, index=combined.index, name="COMPOSITE").dropna()

    # Compute percentile rank over composite's own history
    pct_series = expanding_percentile(composite)
    current_val = float(composite.iloc[-1])
    current_pct_series = pct_series.dropna()
    current_pct = float(current_pct_series.iloc[-1]) if not current_pct_series.empty else float("nan")

    # Zone classification
    if np.isnan(current_pct):
        zone = "MID"
    elif current_pct <= EXTREME_LOW_PCT:
        zone = "EXTREME_LOW"
    elif current_pct <= 0.30:
        zone = "LOW"
    elif current_pct <= 0.70:
        zone = "MID"
    elif current_pct <= EXTREME_HIGH_PCT:
        zone = "HIGH"
    else:
        zone = "EXTREME_HIGH"

    # Which components had data in the latest month
    latest = combined.iloc[-1]
    used = [name for name in combined.columns if not pd.isna(latest[name])]

    return CompositeState(
        series=composite,
        percentile_series=pct_series,
        current_value=current_val,
        current_percentile=current_pct,
        zone=zone,
        n_components=len(used),
        components_used=used,
    )
