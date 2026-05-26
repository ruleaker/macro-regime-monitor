"""Fetch all candidate signals' raw data and cache to data/raw/.

Run once a day at most. Subsequent research scripts read from the cached CSVs.

Data sources, all free:
  - FRED via pandas-datareader (M2SL, WILL5000PRFC, BAMLH0A0HYM2, WALCL, WTREGEN, RRPONTSYD, SP500)
  - Yahoo via yfinance (^GSPC, ^NDX, ^SOX, ^RUT, ^DJI) for daily index data
  - FINRA Customer Margin Balances (xlsx)

Margin debt from FINRA is the only awkward one — published with a lag and the
URL changes occasionally. Wrapped in try/except so the rest still runs.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=1960-01-01"
FINRA_MARGIN_URL = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"

FRED_SERIES = {
    "M2SL": "M2 Money Stock (monthly, billions)",
    "WALCL": "Fed Total Assets (weekly, millions)",
    "WTREGEN": "Treasury General Account (weekly, millions)",
    "RRPONTSYD": "Overnight Reverse Repo (daily, billions)",
    "BAMLH0A0HYM2": "HY OAS - ICE BofA US HY Index Option-Adjusted Spread (daily)",
}

YAHOO_TICKERS = {
    "^GSPC": "S&P 500 (long history, primary)",
    "^NDX": "Nasdaq-100",
    "^SOX": "PHLX Semiconductor Index",
    "^RUT": "Russell 2000",
    "^DJI": "Dow Jones Industrial Average",
    "^W5000": "Wilshire 5000 (Yahoo, since FRED retired WILL5000PRFC)",
}


def fetch_fred(series_id: str) -> pd.DataFrame:
    r = requests.get(FRED_CSV.format(series=series_id), timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), parse_dates=["observation_date"], na_values=".")
    df = df.rename(columns={"observation_date": "date", series_id: "value"})
    df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
    df["value"] = df["value"].astype(float)
    return df


def fetch_yahoo(ticker: str, start: str = "1985-01-01") -> pd.DataFrame:
    """Yahoo close prices via yfinance. Falls back gracefully if blocked."""
    import yfinance as yf

    raw = yf.download(ticker, start=start, progress=False, auto_adjust=False, threads=False)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "value"])
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    s = close.dropna()
    out = pd.DataFrame({"date": s.index, "value": s.values.astype(float)})
    return out


def fetch_finra_margin() -> pd.DataFrame:
    """FINRA Customer Margin Balances. Monthly. Brittle URL."""
    df = pd.read_excel(FINRA_MARGIN_URL, sheet_name="Customer Margin Balances")
    debit_cols = [c for c in df.columns if "Debit Balances" in c]
    if not debit_cols:
        raise RuntimeError(f"No debit-balance column found; got {list(df.columns)}")
    debit_col = debit_cols[0]
    out = df[["Year-Month", debit_col]].copy()
    out = out.rename(columns={debit_col: "value"})
    out["date"] = pd.PeriodIndex(out["Year-Month"].astype(str), freq="M").to_timestamp("M")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out = out.dropna(subset=["date", "value"]).sort_values("date")
    return out[["date", "value"]].reset_index(drop=True)


def save(name: str, df: pd.DataFrame) -> None:
    path = RAW / f"{name}.csv"
    df.to_csv(path, index=False)
    if df.empty:
        print(f"  [FAIL]{name}: EMPTY")
        return
    first = df["date"].min().date()
    last = df["date"].max().date()
    print(f"  [OK]{name}: {len(df):>5} rows  {first} → {last}")


def main() -> int:
    print("FRED series:")
    fred_failed: list[str] = []
    for sid, desc in FRED_SERIES.items():
        try:
            df = fetch_fred(sid)
            save(sid, df)
        except Exception as e:
            msg = str(e).splitlines()[0][:120]
            print(f"  [FAIL]{sid}: {msg}")
            fred_failed.append(sid)

    print("\nYahoo tickers:")
    yahoo_failed: list[str] = []
    for tkr, desc in YAHOO_TICKERS.items():
        try:
            df = fetch_yahoo(tkr)
            # Strip caret for filename
            name = tkr.lstrip("^")
            save(name, df)
        except Exception as e:
            msg = str(e).splitlines()[0][:120]
            print(f"  [FAIL]{tkr}: {msg}")
            yahoo_failed.append(tkr)

    print("\nFINRA margin debt:")
    try:
        df = fetch_finra_margin()
        save("FINRA_MARGIN_DEBT", df)
    except Exception as e:
        msg = str(e).splitlines()[0][:200]
        print(f"  [FAIL]FINRA margin: {msg}")
        print("    (FINRA URL is brittle; we'll bootstrap from the existing macro CSV if present)")

    if fred_failed or yahoo_failed:
        print(f"\nFailed FRED: {fred_failed}")
        print(f"Failed Yahoo: {yahoo_failed}")
        print("(Re-run the script in a few minutes — these are transient network issues most of the time.)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
