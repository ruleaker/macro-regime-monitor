"""Build the 7 candidate signals as monthly time series.

Reads raw CSVs from data/raw/, produces data/signals.csv (long format) and
data/signals_summary.csv (per-signal current state + extreme thresholds).

All series are resampled to month-end. Signals are forward-fill-free past
their first valid observation. Z-score / percentile computations use expanding
windows so no look-ahead bias enters subsequent analysis.

Signal definitions
------------------
1. MCAP_M2:        Wilshire 5000 close / M2SL (level ratio).
2. M2_GROWTH:      M2SL year-over-year percent change.
3. NET_LIQUIDITY:  Fed BS - TGA - RRP, all normalized to trillions.
4. MARGIN_M2:      FINRA Customer Margin Debt / M2SL.
5. NDX_SPX_RS:     3-month percent change in NDX/SPX ratio.
6. SOX_SPX_RS:     3-month percent change in SOX/SPX ratio.
7. RUT_SPX_RS:     3-month percent change in RUT/SPX ratio.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"

EXTREME_LOW_PCT = 0.10   # bottom decile
EXTREME_HIGH_PCT = 0.90  # top decile
MIN_HISTORY_MONTHS = 60  # need 5 years before computing percentile


@dataclass
class Signal:
    name: str
    category: str
    description: str
    series: pd.Series   # monthly, index=date, value=signal level

    @property
    def latest_date(self) -> pd.Timestamp:
        return self.series.dropna().index[-1]

    @property
    def current_value(self) -> float:
        return float(self.series.dropna().iloc[-1])

    @property
    def percentile_series(self) -> pd.Series:
        """Expanding-window historical percentile of each observation."""
        s = self.series.dropna()
        out = s.expanding(MIN_HISTORY_MONTHS).apply(
            lambda x: float((x.iloc[-1] >= x).mean()), raw=False
        )
        return out

    @property
    def current_percentile(self) -> float:
        return float(self.percentile_series.dropna().iloc[-1])

    @property
    def in_extreme_low(self) -> bool:
        return self.current_percentile <= EXTREME_LOW_PCT

    @property
    def in_extreme_high(self) -> bool:
        return self.current_percentile >= EXTREME_HIGH_PCT


def load_raw(name: str, value_col: str = "value") -> pd.Series:
    df = pd.read_csv(RAW / f"{name}.csv", parse_dates=["date"])
    s = df.set_index("date")[value_col].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s


def to_month_end(s: pd.Series, how: str = "last") -> pd.Series:
    s = s.sort_index()
    if how == "last":
        return s.resample("ME").last().dropna()
    if how == "mean":
        return s.resample("ME").mean().dropna()
    raise ValueError(how)


def m2_align(m2: pd.Series) -> pd.Series:
    """M2SL is dated to the first of each month on FRED. Move to month-end."""
    s = m2.copy()
    s.index = s.index.to_period("M").to_timestamp("M")
    return s.sort_index()


# Signal builders ---------------------------------------------------------

def build_mcap_m2(wilshire: pd.Series, m2: pd.Series) -> Signal:
    w_m = to_month_end(wilshire, "last")
    m2_m = m2_align(m2)
    df = pd.concat({"w": w_m, "m2": m2_m}, axis=1).dropna()
    s = df["w"] / df["m2"]
    s.name = "MCAP_M2"
    return Signal(
        name="MCAP_M2",
        category="valuation_liquidity",
        description="Wilshire 5000 / M2 - market cap to money supply ratio (Buffett indicator variant)",
        series=s,
    )


def build_m2_growth(m2: pd.Series) -> Signal:
    m2_m = m2_align(m2)
    s = m2_m.pct_change(12) * 100  # YoY % change
    s = s.dropna()
    s.name = "M2_GROWTH"
    return Signal(
        name="M2_GROWTH",
        category="liquidity_flow",
        description="M2 year-over-year growth rate (%)",
        series=s,
    )


def build_net_liquidity(walcl: pd.Series, tga: pd.Series, rrp: pd.Series) -> Signal:
    # FRED units: WALCL = Millions of USD, WTREGEN = Millions of USD, RRPONTSYD = Billions of USD
    walcl_m = to_month_end(walcl, "last") / 1_000_000  # M -> T
    tga_m = to_month_end(tga, "last") / 1_000_000      # M -> T
    rrp_m = to_month_end(rrp, "last") / 1_000          # B -> T
    df = pd.concat({"w": walcl_m, "t": tga_m, "r": rrp_m}, axis=1).dropna()
    s = df["w"] - df["t"] - df["r"]
    s.name = "NET_LIQUIDITY"
    return Signal(
        name="NET_LIQUIDITY",
        category="liquidity_stock",
        description="Net Liquidity (Fed BS - TGA - RRP), trillions USD",
        series=s,
    )


def build_margin_m2(margin: pd.Series, m2: pd.Series) -> Signal:
    # Margin debt in millions, M2 in billions. Normalize: margin / (m2 * 1000) -> dimensionless ratio.
    m_m = to_month_end(margin, "last")
    m2_m = m2_align(m2)
    df = pd.concat({"margin": m_m, "m2": m2_m}, axis=1).dropna()
    s = df["margin"] / (df["m2"] * 1000)
    s.name = "MARGIN_M2"
    return Signal(
        name="MARGIN_M2",
        category="speculative_leverage",
        description="FINRA margin debt / M2 - speculative leverage relative to liquidity",
        series=s,
    )


def build_relative_strength(a: pd.Series, b: pd.Series, name: str, label_a: str, label_b: str) -> Signal:
    a_m = to_month_end(a, "last")
    b_m = to_month_end(b, "last")
    df = pd.concat({"a": a_m, "b": b_m}, axis=1).dropna()
    ratio = df["a"] / df["b"]
    rs = ratio.pct_change(3) * 100  # 3-month rate of change
    rs = rs.dropna()
    rs.name = name
    return Signal(
        name=name,
        category="internal_leadership",
        description=f"{label_a}/{label_b} 3-month rate of change (%) - leadership rotation",
        series=rs,
    )


# Reporting ---------------------------------------------------------------

def signal_summary_row(sig: Signal) -> dict:
    pct = sig.percentile_series.dropna()
    return {
        "signal": sig.name,
        "category": sig.category,
        "description": sig.description,
        "start": sig.series.index.min().strftime("%Y-%m"),
        "end": sig.latest_date.strftime("%Y-%m"),
        "months": int(len(sig.series)),
        "current_value": float(sig.current_value),
        "current_percentile": float(sig.current_percentile) if not pct.empty else float("nan"),
        "in_extreme_low": bool(sig.in_extreme_low),
        "in_extreme_high": bool(sig.in_extreme_high),
    }


def main() -> int:
    print("Loading raw series...")
    m2 = load_raw("M2SL")
    walcl = load_raw("WALCL")
    tga = load_raw("WTREGEN")
    rrp = load_raw("RRPONTSYD")
    wilshire = load_raw("W5000")
    margin = load_raw("FINRA_MARGIN_DEBT")
    gspc = load_raw("GSPC")
    ndx = load_raw("NDX")
    sox = load_raw("SOX")
    rut = load_raw("RUT")

    print("\nBuilding signals...")
    signals = [
        build_mcap_m2(wilshire, m2),
        build_m2_growth(m2),
        build_net_liquidity(walcl, tga, rrp),
        build_margin_m2(margin, m2),
        build_relative_strength(ndx, gspc, "NDX_SPX_RS", "NDX", "SPX"),
        build_relative_strength(sox, gspc, "SOX_SPX_RS", "SOX", "SPX"),
        build_relative_strength(rut, gspc, "RUT_SPX_RS", "RUT", "SPX"),
    ]

    # Persist long-format signals.csv (date, signal, value)
    rows = []
    for sig in signals:
        for date, val in sig.series.items():
            rows.append({"date": date, "signal": sig.name, "value": float(val)})
    long_df = pd.DataFrame(rows).sort_values(["signal", "date"])
    long_df.to_csv(OUT / "signals.csv", index=False)
    print(f"\nWrote {OUT / 'signals.csv'} ({len(long_df):,} rows across {len(signals)} signals)")

    # Persist per-signal summary
    summary = pd.DataFrame([signal_summary_row(s) for s in signals])
    summary.to_csv(OUT / "signals_summary.csv", index=False)

    # Pretty-print summary
    print("\nCurrent state of each signal:")
    print("-" * 100)
    fmt = "{name:<14} {start:<8} {end:<8} {n:>5}  curr={cv:>10}  pct={pct:>5}  zone={zone}"
    for _, r in summary.iterrows():
        zone = "LOW" if r["in_extreme_low"] else "HIGH" if r["in_extreme_high"] else "mid"
        pct_str = f"{r['current_percentile']:.0%}" if not pd.isna(r["current_percentile"]) else "n/a"
        cv = f"{r['current_value']:.3f}"
        print(
            fmt.format(
                name=r["signal"], start=r["start"], end=r["end"], n=r["months"],
                cv=cv, pct=pct_str, zone=zone,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
