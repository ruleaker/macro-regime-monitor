"""Liquidity Trend Panel — V4.

A separate, faster lens than the composite. The composite tells you 'where
are we in the cycle' (slow percentile-based). This module tells you 'what
is currently trending which way' using technical-analysis tools applied
to monthly macro variables.

Validated on 2020-03 COVID easing and 2022-01 QT pivot (see research/
11_trend_inflection.py). SuperTrend(10, 2.0) detected the NETLIQ inflection
within 1 month at both events.

Variables tracked:
  WALCL    Fed Balance Sheet               (trillions, monthly mean)
  NETLIQ   Fed BS - TGA - RRP              (trillions, monthly mean)
  M2_LEVEL M2 money supply                 (billions, monthly)
  DGS10    10Y Treasury yield              (%, monthly mean)
  DXY      ICE Dollar Index                (level, monthly close)

For each variable, we compute:
  - SuperTrend direction (+1 / -1)
  - Last flip date and months since flip
  - Liquidity implication based on variable's macro role
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import yfinance as yf
import requests
import io

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=1960-01-01"


@dataclass
class TrendState:
    name: str
    short_name: str
    description: str
    direction: int                      # +1 (UP) | -1 (DOWN) | 0 (insufficient data)
    current_value: float
    last_flip_date: pd.Timestamp | None
    months_since_flip: float | None
    upper_band: float
    lower_band: float
    liquidity_implication: str          # 'release' | 'tighten' | 'neutral'
    higher_means_release: bool           # for chart coloring
    series: pd.Series = field(default_factory=pd.Series)
    direction_series: pd.Series = field(default_factory=pd.Series)


VARIABLES = {
    "WALCL": {
        "short_name": "Fed Balance Sheet",
        "description": "Fed total assets - direct measure of QE/QT activity.",
        "higher_means_release": True,
        "fred_id": "WALCL",
        "fred_scale": 1_000_000,        # millions -> trillions
        "month_agg": "mean",
    },
    "NETLIQ": {
        "short_name": "Net Liquidity",
        "description": "Fed BS - TGA - RRP. Most sensitive inflection detector (0.5-0.9m lag at 2020/2022 pivots).",
        "higher_means_release": True,
        "compute": "netliq",
        "month_agg": "mean",
    },
    "M2_LEVEL": {
        "short_name": "M2 Money Supply",
        "description": "Broad money stock. Smoother than NETLIQ but lags QE/QT events.",
        "higher_means_release": True,
        "fred_id": "M2SL",
        "fred_scale": 1,
        "month_agg": "last",
    },
    "DGS10": {
        "short_name": "10Y Treasury Yield",
        "description": "Long-end rates. Rising trend = market pricing tightening / inflation.",
        "higher_means_release": False,
        "fred_id": "DGS10",
        "fred_scale": 1,
        "month_agg": "mean",
    },
    "DXY": {
        "short_name": "US Dollar Index",
        "description": "USD strength. Strengthening DXY = global liquidity absorbed by USD.",
        "higher_means_release": False,
        "yahoo_ticker": "DX-Y.NYB",
        "month_agg": "last",
    },
}

SUPERTREND_PERIOD = 10
SUPERTREND_MULT = 2.0


def _fetch_fred(series: str) -> pd.Series:
    r = requests.get(FRED_CSV.format(series=series), timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), parse_dates=["observation_date"], na_values=".")
    df = df.rename(columns={"observation_date": "date", series: "value"})
    df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
    s = df.set_index("date")["value"].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def _fetch_yahoo(ticker: str, start: str = "1985-01-01") -> pd.Series:
    raw = yf.download(ticker, start=start, progress=False, auto_adjust=False, threads=False)
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    s = close.dropna().astype(float)
    s.index = pd.to_datetime(s.index)
    return s[~s.index.duplicated(keep="last")].sort_index()


def _to_month(s: pd.Series, how: str = "mean") -> pd.Series:
    if how == "mean":
        return s.resample("ME").mean().dropna()
    return s.resample("ME").last().dropna()


def _m2_align(s: pd.Series) -> pd.Series:
    out = s.copy()
    out.index = out.index.to_period("M").to_timestamp("M")
    return out.sort_index()


def supertrend(series: pd.Series, period: int = SUPERTREND_PERIOD,
                mult: float = SUPERTREND_MULT) -> pd.DataFrame:
    """SuperTrend adapted for monthly macro data. Returns DataFrame with
    columns: value, upper, lower, direction (+1/-1), flip (bool)."""
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
    return pd.DataFrame({
        "value": s,
        "upper": upper,
        "lower": lower,
        "direction": direction,
        "flip": flip,
    })


def fetch_all_variables() -> dict[str, pd.Series]:
    """Fetch monthly series for all variables. Returns dict keyed by var name."""
    series_map: dict[str, pd.Series] = {}
    # Direct FRED + Yahoo first
    for vname, cfg in VARIABLES.items():
        if "fred_id" in cfg:
            raw = _fetch_fred(cfg["fred_id"])
            if vname == "M2_LEVEL":
                raw = _m2_align(raw)
            else:
                raw = _to_month(raw, cfg["month_agg"])
            if cfg.get("fred_scale", 1) != 1:
                raw = raw / cfg["fred_scale"]
            series_map[vname] = raw
        elif "yahoo_ticker" in cfg:
            raw = _fetch_yahoo(cfg["yahoo_ticker"])
            series_map[vname] = _to_month(raw, cfg["month_agg"])

    # Composite computations (NETLIQ)
    walcl = series_map.get("WALCL")
    wtregen = _to_month(_fetch_fred("WTREGEN"), "mean") / 1_000_000
    rrp = _to_month(_fetch_fred("RRPONTSYD"), "mean") / 1_000   # billions -> trillions
    if walcl is not None:
        netliq = (walcl - wtregen - rrp).dropna()
        series_map["NETLIQ"] = netliq

    return series_map


def liquidity_implication(direction: int, higher_means_release: bool) -> str:
    if direction == 0:
        return "neutral"
    is_release = (direction == 1 and higher_means_release) or \
                 (direction == -1 and not higher_means_release)
    return "release" if is_release else "tighten"


def build_trend_state(var_name: str, series: pd.Series) -> TrendState:
    cfg = VARIABLES[var_name]
    st = supertrend(series, period=SUPERTREND_PERIOD, mult=SUPERTREND_MULT)
    st = st.dropna(subset=["direction"])
    if st.empty or len(st) < SUPERTREND_PERIOD + 2:
        return TrendState(
            name=var_name, short_name=cfg["short_name"], description=cfg["description"],
            direction=0, current_value=float("nan"),
            last_flip_date=None, months_since_flip=None,
            upper_band=float("nan"), lower_band=float("nan"),
            liquidity_implication="neutral",
            higher_means_release=cfg["higher_means_release"],
        )

    latest = st.iloc[-1]
    dir_int = int(latest["direction"])
    # Last flip
    flips = st[st["flip"]]
    last_flip = flips.index[-1] if not flips.empty else None
    months_since = None
    if last_flip is not None:
        months_since = (latest.name - last_flip).days / 30.44

    return TrendState(
        name=var_name,
        short_name=cfg["short_name"],
        description=cfg["description"],
        direction=dir_int,
        current_value=float(latest["value"]),
        last_flip_date=last_flip,
        months_since_flip=months_since,
        upper_band=float(latest["upper"]),
        lower_band=float(latest["lower"]),
        liquidity_implication=liquidity_implication(dir_int, cfg["higher_means_release"]),
        higher_means_release=cfg["higher_means_release"],
        series=st["value"],
        direction_series=st["direction"],
    )


def build_all_trends() -> dict[str, TrendState]:
    series_map = fetch_all_variables()
    out: dict[str, TrendState] = {}
    for vname in VARIABLES:
        if vname not in series_map:
            continue
        out[vname] = build_trend_state(vname, series_map[vname])
    return out


def liquidity_flow_score(states: dict[str, TrendState]) -> dict:
    """Composite trend score: how many variables point to liquidity release vs tighten.

    Range: -N to +N where N is number of variables.
    """
    release_count = sum(1 for s in states.values() if s.liquidity_implication == "release")
    tighten_count = sum(1 for s in states.values() if s.liquidity_implication == "tighten")
    neutral_count = sum(1 for s in states.values() if s.liquidity_implication == "neutral")
    n_total = release_count + tighten_count + neutral_count
    score = release_count - tighten_count
    return {
        "score": score,
        "release_count": release_count,
        "tighten_count": tighten_count,
        "neutral_count": neutral_count,
        "n_total": n_total,
        "release_vars": [n for n, s in states.items() if s.liquidity_implication == "release"],
        "tighten_vars": [n for n, s in states.items() if s.liquidity_implication == "tighten"],
        "captured_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
