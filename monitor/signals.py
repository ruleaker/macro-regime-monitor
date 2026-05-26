"""Signal definitions for the production dashboard.

Each signal carries explicit metadata about which durability tier it earned
in the research phase (see research/findings.md). The dashboard surfaces
this in the UI so the reader knows the evidence strength behind any current
extreme reading.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import requests
import yfinance as yf

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=1960-01-01"
FINRA_MARGIN_URL = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"

MIN_HISTORY_MONTHS = 60
QUINTILE_LOW = 0.20
QUINTILE_HIGH = 0.80


# --- Tier metadata, taken from research/findings.md ----------------------

TIER_LABEL = {
    "DURABLE": "Durable (consistent direction across 3+ decades)",
    "MOSTLY": "Mostly directional (2+ decades agree, <3 of 3+pp magnitude)",
    "TOMBSTONE": "Failed stability test — kept for reference only",
}


@dataclass
class Signal:
    name: str
    short_name: str               # display name
    description: str
    category: str                  # 'leverage' | 'leadership' | 'valuation' | 'liquidity'
    series: pd.Series              # monthly time series (date index, value)
    tier_low: str                  # 'DURABLE' | 'MOSTLY' | 'TOMBSTONE' | 'INSUFFICIENT'
    tier_high: str
    effect_low_pp: float | None    # historical zone-vs-full effect in pp, 12m horizon (quintile findings)
    effect_high_pp: float | None
    n_low: int                     # historical sample size in LOW zone (quintile)
    n_high: int                    # historical sample size in HIGH zone (quintile)
    higher_is_riskier: bool        # for the UI: which zone is "warning" direction

    @property
    def latest_date(self) -> pd.Timestamp:
        return self.series.dropna().index[-1]

    @property
    def current_value(self) -> float:
        return float(self.series.dropna().iloc[-1])

    @property
    def percentile_series(self) -> pd.Series:
        return self.series.dropna().expanding(MIN_HISTORY_MONTHS).apply(
            lambda x: float((x.iloc[-1] >= x).mean()), raw=False
        )

    @property
    def current_percentile(self) -> float:
        p = self.percentile_series.dropna()
        return float(p.iloc[-1]) if not p.empty else float("nan")

    @property
    def zone(self) -> str:
        p = self.current_percentile
        if np.isnan(p):
            return "n/a"
        if p <= QUINTILE_LOW:
            return "LOW"
        if p >= QUINTILE_HIGH:
            return "HIGH"
        return "MID"

    @property
    def in_extreme(self) -> bool:
        return self.zone in ("LOW", "HIGH")

    @property
    def current_tier(self) -> str:
        return self.tier_low if self.zone == "LOW" else self.tier_high if self.zone == "HIGH" else "—"

    @property
    def current_effect_pp(self) -> float | None:
        if self.zone == "LOW":
            return self.effect_low_pp
        if self.zone == "HIGH":
            return self.effect_high_pp
        return None


# --- Data fetch helpers --------------------------------------------------

def _fetch_fred(series_id: str) -> pd.Series:
    r = requests.get(FRED_CSV.format(series=series_id), timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), parse_dates=["observation_date"], na_values=".")
    df = df.rename(columns={"observation_date": "date", series_id: "value"})
    df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
    s = df.set_index("date")["value"].astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s


def _fetch_yahoo(ticker: str, start: str = "1985-01-01") -> pd.Series:
    raw = yf.download(ticker, start=start, progress=False, auto_adjust=False, threads=False)
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    s = close.dropna().astype(float)
    s.index = pd.to_datetime(s.index)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


_FINRA_CACHE = Path(__file__).resolve().parents[1] / "data" / "FINRA_MARGIN_DEBT.csv"


def _fetch_finra_margin() -> pd.Series:
    """FINRA Customer Margin Balances. Brittle source — caches to disk on success
    and falls back to cached CSV if the FINRA URL is unavailable."""
    try:
        df = pd.read_excel(FINRA_MARGIN_URL, sheet_name="Customer Margin Balances")
        debit_col = next(c for c in df.columns if "Debit Balances" in c)
        out = df[["Year-Month", debit_col]].copy()
        out["date"] = pd.PeriodIndex(out["Year-Month"].astype(str), freq="M").to_timestamp("M")
        out["value"] = pd.to_numeric(out[debit_col], errors="coerce")
        out = out.dropna(subset=["date", "value"]).sort_values("date")
        s = out.set_index("date")["value"].astype(float)
        # Cache for resilience
        _FINRA_CACHE.parent.mkdir(exist_ok=True)
        s.reset_index().to_csv(_FINRA_CACHE, index=False)
        return s
    except Exception as e:
        msg = str(e).splitlines()[0][:100]
        print(f"  [warn] FINRA fetch failed ({msg}); falling back to cached CSV")
        if not _FINRA_CACHE.exists():
            raise RuntimeError("FINRA fetch failed and no cache available")
        df = pd.read_csv(_FINRA_CACHE, parse_dates=["date"])
        return df.set_index("date")["value"].astype(float).sort_index()


def _to_month_end(s: pd.Series, how: str = "last") -> pd.Series:
    s = s.sort_index()
    if how == "last":
        return s.resample("ME").last().dropna()
    if how == "mean":
        return s.resample("ME").mean().dropna()
    raise ValueError(how)


def _m2_to_month_end(m2: pd.Series) -> pd.Series:
    s = m2.copy()
    s.index = s.index.to_period("M").to_timestamp("M")
    return s.sort_index()


# --- Signal builders -----------------------------------------------------

def build_all() -> dict[str, Signal]:
    """Fetch raw data + build all production signals. Returns dict keyed by name."""
    print("Fetching M2 (FRED M2SL)...")
    m2 = _fetch_fred("M2SL")
    print("Fetching FINRA margin debt...")
    margin = _fetch_finra_margin()
    print("Fetching SPX (Yahoo ^GSPC)...")
    gspc = _fetch_yahoo("^GSPC")
    print("Fetching NDX (Yahoo ^NDX)...")
    ndx = _fetch_yahoo("^NDX")
    print("Fetching SOX (Yahoo ^SOX)...")
    sox = _fetch_yahoo("^SOX")
    print("Fetching Wilshire 5000 (Yahoo ^W5000)...")
    wilshire = _fetch_yahoo("^W5000")

    signals: dict[str, Signal] = {}

    # MARGIN_M2 — Tier 1 DURABLE bear at HIGH, Tier 2 MOSTLY bull at LOW
    m2_me = _m2_to_month_end(m2)
    margin_me = _to_month_end(margin)
    df = pd.concat({"m": margin_me, "m2": m2_me}, axis=1).dropna()
    margin_m2 = df["m"] / (df["m2"] * 1000)
    signals["MARGIN_M2"] = Signal(
        name="MARGIN_M2",
        short_name="Margin debt / M2",
        description="FINRA customer margin debit balances divided by M2 money supply — speculative leverage relative to liquidity.",
        category="leverage",
        series=margin_m2,
        tier_low="MOSTLY",
        tier_high="DURABLE",
        effect_low_pp=+7.6,
        effect_high_pp=-13.2,
        n_low=41,
        n_high=56,
        higher_is_riskier=True,
    )

    # NDX_SPX_RS — Tier 2 MOSTLY bull at HIGH, Tier 3 at LOW (regime-dependent)
    ndx_me = _to_month_end(ndx)
    gspc_me = _to_month_end(gspc)
    df = pd.concat({"a": ndx_me, "b": gspc_me}, axis=1).dropna()
    ndx_rs = (df["a"] / df["b"]).pct_change(3) * 100
    signals["NDX_SPX_RS"] = Signal(
        name="NDX_SPX_RS",
        short_name="NDX vs SPX 3m RS",
        description="3-month rate-of-change in NDX/SPX ratio — tech leadership over large caps.",
        category="leadership",
        series=ndx_rs.dropna(),
        tier_low="REGIME-DEP",
        tier_high="MOSTLY",
        effect_low_pp=-8.3,
        effect_high_pp=+4.8,
        n_low=67,
        n_high=77,
        higher_is_riskier=False,
    )

    # SOX_SPX_RS — Tier 2 MOSTLY bull at HIGH, Tier 2 MOSTLY bear at LOW
    sox_me = _to_month_end(sox)
    df = pd.concat({"a": sox_me, "b": gspc_me}, axis=1).dropna()
    sox_rs = (df["a"] / df["b"]).pct_change(3) * 100
    signals["SOX_SPX_RS"] = Signal(
        name="SOX_SPX_RS",
        short_name="SOX vs SPX 3m RS",
        description="3-month rate-of-change in PHLX Semiconductor / SPX ratio — semis are the canonical risk-on barometer.",
        category="leadership",
        series=sox_rs.dropna(),
        tier_low="MOSTLY",
        tier_high="MOSTLY",
        effect_low_pp=-5.5,
        effect_high_pp=+4.2,
        n_low=33,
        n_high=41,
        higher_is_riskier=False,
    )

    # MCAP_M2 — TOMBSTONE: failed stability test, shown for reference
    wilshire_me = _to_month_end(wilshire)
    df = pd.concat({"w": wilshire_me, "m2": m2_me}, axis=1).dropna()
    mcap_m2 = df["w"] / df["m2"]
    signals["MCAP_M2"] = Signal(
        name="MCAP_M2",
        short_name="Market cap / M2 (Buffett indicator variant)",
        description="Wilshire 5000 divided by M2 money supply. Popular narrative; failed cross-decade stability test (signal driven entirely by 2000s dot-com unwind).",
        category="valuation",
        series=mcap_m2,
        tier_low="INSUFFICIENT",
        tier_high="TOMBSTONE",
        effect_low_pp=None,
        effect_high_pp=None,
        n_low=9,
        n_high=140,
        higher_is_riskier=True,
    )

    return signals


# --- Snapshot helpers ----------------------------------------------------

def snapshot(signals: dict[str, Signal]) -> dict:
    captured = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []
    net_effect = 0.0
    triggered_durable_bear = []
    triggered_durable_bull = []
    triggered_mostly_bear = []
    triggered_mostly_bull = []

    for name, sig in signals.items():
        if name == "MCAP_M2":
            # Tombstone — record value but do not contribute to composite
            rows.append({
                "name": name,
                "short_name": sig.short_name,
                "current_value": sig.current_value,
                "current_percentile": sig.current_percentile,
                "zone": sig.zone,
                "tier": "TOMBSTONE",
                "effect_pp": None,
                "latest_date": sig.latest_date.strftime("%Y-%m"),
            })
            continue

        eff = sig.current_effect_pp
        tier = sig.current_tier
        rows.append({
            "name": name,
            "short_name": sig.short_name,
            "current_value": sig.current_value,
            "current_percentile": sig.current_percentile,
            "zone": sig.zone,
            "tier": tier,
            "effect_pp": eff,
            "latest_date": sig.latest_date.strftime("%Y-%m"),
        })

        if eff is None:
            continue
        net_effect += eff
        if tier == "DURABLE":
            (triggered_durable_bear if eff < 0 else triggered_durable_bull).append((name, eff))
        elif tier == "MOSTLY":
            (triggered_mostly_bear if eff < 0 else triggered_mostly_bull).append((name, eff))

    return {
        "captured_utc": captured,
        "rows": rows,
        "net_effect_pp": round(net_effect, 2),
        "triggered_durable_bear": triggered_durable_bear,
        "triggered_durable_bull": triggered_durable_bull,
        "triggered_mostly_bear": triggered_mostly_bear,
        "triggered_mostly_bull": triggered_mostly_bull,
    }
