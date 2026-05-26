"""Cross-decade stability test for each signal's conditional-return effect.

For each (signal, zone), split observations by the decade in which the
zone observation occurred, and report:

  - decade-by-decade zone mean forward 12m return
  - decade-by-decade FULL-sample mean (from the same decade) as baseline
  - the decade effect (zone - baseline)
  - sample size per decade

Then classify each (signal, zone) as:

  - DURABLE: effect has consistent sign in at least 3 of the available decades,
            AND magnitude is meaningful (>2 pp) in the majority of those decades
  - REGIME-DEPENDENT: signal works in some decades, fails in others
  - INSUFFICIENT: <3 observations or only 1 decade of data
  - DEAD: effect inconsistent or wrong sign in recent decades

This is the harshest test. Many published 'macro signals' fail it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

HORIZON = 12  # focus on 12-month forward returns
EXTREME_LOW_PCT = 0.10
EXTREME_HIGH_PCT = 0.90
MIN_HISTORY_MONTHS = 60
DECADES = [
    (1960, "1960s"), (1970, "1970s"), (1980, "1980s"), (1990, "1990s"),
    (2000, "2000s"), (2010, "2010s"), (2020, "2020s"),
]


def load_spx_monthly() -> pd.Series:
    df = pd.read_csv(RAW / "GSPC.csv", parse_dates=["date"])
    s = df.set_index("date")["value"].astype(float).sort_index()
    s = s.resample("ME").last().dropna()
    s.name = "spx"
    return s


def load_signals_wide() -> pd.DataFrame:
    long = pd.read_csv(DATA / "signals.csv", parse_dates=["date"])
    return long.pivot(index="date", columns="signal", values="value").sort_index()


def expanding_percentile(s: pd.Series) -> pd.Series:
    return s.expanding(MIN_HISTORY_MONTHS).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def decade_of(ts: pd.Timestamp) -> str:
    d = ts.year - (ts.year % 10)
    return f"{d}s"


def per_decade_table(name: str, signal: pd.Series, spx: pd.Series) -> pd.DataFrame:
    pct = expanding_percentile(signal)
    fwd = spx.shift(-HORIZON) / spx - 1
    df = pd.DataFrame({
        "signal": signal,
        "pct": pct,
        "fwd": fwd,
    }).dropna(subset=["pct", "fwd"])
    df["decade"] = df.index.to_series().apply(decade_of)

    rows = []
    for _, decade_label in DECADES:
        sub = df[df["decade"] == decade_label]
        if sub.empty:
            continue
        full = sub["fwd"].mean()
        for zone_label, mask in [
            ("LOW", sub["pct"] <= EXTREME_LOW_PCT),
            ("HIGH", sub["pct"] >= EXTREME_HIGH_PCT),
        ]:
            zone_sub = sub[mask]
            rows.append({
                "signal": name,
                "zone": zone_label,
                "decade": decade_label,
                "n_decade_total": int(len(sub)),
                "n_zone": int(len(zone_sub)),
                "zone_mean": float(zone_sub["fwd"].mean()) if not zone_sub.empty else np.nan,
                "decade_baseline": float(full),
                "effect_pp": float((zone_sub["fwd"].mean() - full) * 100) if not zone_sub.empty else np.nan,
            })
    return pd.DataFrame(rows)


def classify(rows: pd.DataFrame) -> str:
    """Per (signal, zone) classifier. Operates on the decade-level rows."""
    valid = rows.dropna(subset=["effect_pp"])
    if valid.empty:
        return "INSUFFICIENT"
    if len(valid) == 1:
        return "INSUFFICIENT (one decade only)"

    pos = (valid["effect_pp"] > 2).sum()
    neg = (valid["effect_pp"] < -2).sum()
    total = len(valid)

    if pos >= 3 and neg == 0:
        return "DURABLE+"
    if neg >= 3 and pos == 0:
        return "DURABLE-"
    if pos >= total - 1 and neg == 0:
        return "MOSTLY+"
    if neg >= total - 1 and pos == 0:
        return "MOSTLY-"
    if (pos > 0 and neg > 0):
        return "REGIME-DEPENDENT"
    return "WEAK"


def main() -> int:
    print("Loading...")
    spx = load_spx_monthly()
    sig_wide = load_signals_wide()

    all_rows: list[pd.DataFrame] = []
    for sig_name in sig_wide.columns:
        s = sig_wide[sig_name].dropna()
        t = per_decade_table(sig_name, s, spx)
        all_rows.append(t)

    table = pd.concat(all_rows, ignore_index=True)
    table.to_csv(DATA / "stability.csv", index=False)

    # Classifier summary
    print("\n" + "=" * 90)
    print(f"Cross-decade stability of signal × zone effects (12m forward SPX return)")
    print("=" * 90)
    classifier_rows = []
    for (sig, zone), group in table.groupby(["signal", "zone"]):
        n_total = int(group["n_zone"].sum())
        classification = classify(group)
        classifier_rows.append({
            "signal": sig, "zone": zone, "total_zone_n": n_total,
            "n_decades_with_zone": int((group["n_zone"] > 0).sum()),
            "classification": classification,
        })
    cdf = pd.DataFrame(classifier_rows)
    cdf = cdf.sort_values(["classification", "signal", "zone"])

    print(
        f"{'Signal':<14} {'Zone':<5} {'TotalN':>7} {'#Dec':>5}  {'Classification':<22}"
    )
    print("-" * 60)
    for _, r in cdf.iterrows():
        print(
            f"{r['signal']:<14} {r['zone']:<5} {r['total_zone_n']:>7} "
            f"{r['n_decades_with_zone']:>5}  {r['classification']:<22}"
        )

    # Detailed per-signal × zone × decade tables for the durable ones
    print("\n" + "=" * 90)
    print("Per-decade effect breakdown (effect = zone_mean - decade_baseline, in pp)")
    print("=" * 90)
    for (sig, zone), group in table.groupby(["signal", "zone"]):
        # Skip decades with no observations of this zone
        relevant = group[group["n_zone"] > 0].sort_values("decade")
        if len(relevant) < 2:
            continue
        print(f"\n{sig} / {zone}:")
        for _, r in relevant.iterrows():
            zm = "n/a" if pd.isna(r["zone_mean"]) else f"{r['zone_mean']*100:+5.1f}%"
            bm = f"{r['decade_baseline']*100:+5.1f}%"
            eff = "n/a" if pd.isna(r["effect_pp"]) else f"{r['effect_pp']:+5.1f}pp"
            print(
                f"  {r['decade']:<8} N={r['n_zone']:>3}  "
                f"zone_mean={zm:>6}  baseline={bm:>6}  effect={eff:>7}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
