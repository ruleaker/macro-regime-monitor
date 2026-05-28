"""V3 expansion — add DXY (broad USD strength) and 10Y treasury signals.

For each new signal, runs the full validation flow:
  1. Conditional 12m fwd SPX return per zone (top/bottom 20% quintile cutoff)
  2. Bootstrap p-value vs full sample
  3. Per-decade stability check

Outputs new signals to data/signals.csv (appended) and prints a tier
classification verdict so the user can decide what gets promoted to the
production composite.

Signal candidates added in V3:

  DXY_LEVEL       DXY index level (Yahoo ^DXY ticker) percentile rank
  DXY_3M_CHG      3-month % change in DXY level
  Y10_3M_CHG      3-month change in 10Y Treasury yield (basis points)
  YIELD_CURVE     10Y minus 3M Treasury yield spread (basis points)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

HORIZON = 12
QUINTILE_LOW = 0.10   # tightened to decile for this rerun
QUINTILE_HIGH = 0.90
MIN_HISTORY_MONTHS = 60
BOOTSTRAP_ITER = 2000
RNG = np.random.default_rng(20260528)


def load_raw(name: str) -> pd.Series:
    df = pd.read_csv(RAW / f"{name}.csv", parse_dates=["date"])
    return df.set_index("date")["value"].astype(float).sort_index()


def to_month_end(s: pd.Series, how: str = "last") -> pd.Series:
    s = s.sort_index()
    if how == "last":
        return s.resample("ME").last().dropna()
    return s.resample("ME").mean().dropna()


def expanding_percentile(s: pd.Series) -> pd.Series:
    return s.dropna().expanding(MIN_HISTORY_MONTHS).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def bootstrap_pvalue(zone: np.ndarray, pool: np.ndarray, n_iter: int = BOOTSTRAP_ITER) -> float:
    if len(zone) < 5 or len(pool) < 30:
        return float("nan")
    obs = zone.mean() - pool.mean()
    n = len(zone)
    diffs = np.empty(n_iter)
    for i in range(n_iter):
        idx = RNG.choice(len(pool), n, replace=False)
        diffs[i] = pool[idx].mean() - pool.mean()
    return float((np.abs(diffs) >= abs(obs)).mean())


def analyze_signal(name: str, signal: pd.Series, spx: pd.Series) -> dict:
    """Full analysis: zone stats + p-value + decade stability."""
    fwd = spx.shift(-HORIZON) / spx - 1
    pct = expanding_percentile(signal)
    df = pd.DataFrame({"pct": pct, "fwd": fwd}).dropna()
    if df.empty:
        return {"name": name, "verdict": "INSUFFICIENT"}

    full = df["fwd"]
    full_mean = full.mean()

    out = {"name": name, "start": signal.dropna().index.min().strftime("%Y-%m"),
           "end": signal.dropna().index.max().strftime("%Y-%m"),
           "n_obs": len(signal.dropna()),
           "full_mean_pp": float(full_mean * 100)}

    for label, mask in [("LOW", df["pct"] <= QUINTILE_LOW),
                          ("HIGH", df["pct"] >= QUINTILE_HIGH)]:
        zone = df.loc[mask, "fwd"].values
        if len(zone) < 5:
            out[f"{label}_n"] = len(zone)
            out[f"{label}_mean"] = float("nan")
            out[f"{label}_effect_pp"] = float("nan")
            out[f"{label}_p"] = float("nan")
            continue
        out[f"{label}_n"] = len(zone)
        out[f"{label}_mean"] = float(zone.mean() * 100)
        out[f"{label}_effect_pp"] = float((zone.mean() - full_mean) * 100)
        out[f"{label}_p"] = bootstrap_pvalue(zone, full.values)
        # Per-decade
        df_d = df.copy()
        df_d["decade"] = df_d.index.to_series().apply(lambda x: f"{x.year - (x.year % 10)}s")
        per_decade = []
        for decade, sub in df_d.groupby("decade"):
            sub_mask = (sub["pct"] <= QUINTILE_LOW) if label == "LOW" else (sub["pct"] >= QUINTILE_HIGH)
            sub_zone = sub.loc[sub_mask, "fwd"]
            if len(sub_zone) >= 2:
                eff = (sub_zone.mean() - sub["fwd"].mean()) * 100
                per_decade.append((decade, len(sub_zone), eff))
        out[f"{label}_decades"] = per_decade

    # Classify: DURABLE / MOSTLY / REGIME-DEP / FAILED
    for label in ("LOW", "HIGH"):
        decades = out.get(f"{label}_decades", [])
        if not decades or pd.isna(out.get(f"{label}_effect_pp")):
            out[f"{label}_verdict"] = "INSUFFICIENT"
            continue
        target_sign = np.sign(out[f"{label}_effect_pp"])
        same = sum(1 for _, n, e in decades if np.sign(e) == target_sign and abs(e) >= 2)
        opp = sum(1 for _, n, e in decades if np.sign(e) != target_sign and abs(e) >= 2)
        n_decades = len(decades)
        if same >= 3 and opp == 0:
            out[f"{label}_verdict"] = "DURABLE"
        elif same >= 2 and opp == 0:
            out[f"{label}_verdict"] = "MOSTLY"
        elif same > opp:
            out[f"{label}_verdict"] = "REGIME-DEP (lean)"
        elif opp > same:
            out[f"{label}_verdict"] = "FAILED"
        else:
            out[f"{label}_verdict"] = "WEAK"
    return out


def main() -> int:
    print("Loading...")
    spx_d = load_raw("GSPC")
    spx_m = to_month_end(spx_d)

    # DXY from Yahoo (longer history than DTWEXBGS)
    dxy_d = load_raw("DX-Y.NYB")
    dxy_m = to_month_end(dxy_d)

    # 10Y treasury
    y10_d = load_raw("DGS10")
    y10_m = to_month_end(y10_d, how="mean")  # monthly mean smooths daily noise

    # 3M treasury
    y3m_d = load_raw("DGS3MO")
    y3m_m = to_month_end(y3m_d, how="mean")

    # Signal definitions
    signals_to_test = {}

    # DXY level — percentile is the signal (high = strong USD)
    signals_to_test["DXY_LEVEL"] = dxy_m

    # DXY 3-month %change — captures pace of USD move
    signals_to_test["DXY_3M_CHG"] = dxy_m.pct_change(3) * 100

    # 10Y yield 3-month change (in bps)
    signals_to_test["Y10_3M_CHG"] = (y10_m - y10_m.shift(3)) * 100  # %pts -> bps

    # Yield curve (10Y - 3M) in bps
    aligned = pd.concat({"y10": y10_m, "y3m": y3m_m}, axis=1).dropna()
    signals_to_test["YIELD_CURVE"] = (aligned["y10"] - aligned["y3m"]) * 100  # %pts -> bps

    print(f"\n{'Signal':<14} {'Start':>8} -> {'End':>8} {'N':>5}")
    for name, s in signals_to_test.items():
        s_clean = s.dropna()
        print(f"{name:<14} {s_clean.index.min().strftime('%Y-%m'):>8} -> {s_clean.index.max().strftime('%Y-%m'):>8} {len(s_clean):>5}")

    results = []
    for name, s in signals_to_test.items():
        print(f"\nAnalyzing {name}...")
        r = analyze_signal(name, s, spx_m)
        results.append(r)

    # Print analysis table
    print("\n" + "=" * 110)
    print(f"V3 new signals — 12m fwd SPX conditional analysis (quintile cutoffs)")
    print("=" * 110)
    print(f"{'Signal':<14} {'Zone':<5} {'N':>4}  {'Mean':>8}  {'Effect':>9}  {'p-val':>6}  {'Verdict':<22}")
    print("-" * 90)
    for r in results:
        for zone in ("LOW", "HIGH"):
            n = r.get(f"{zone}_n", 0)
            mean = r.get(f"{zone}_mean")
            eff = r.get(f"{zone}_effect_pp")
            p = r.get(f"{zone}_p")
            verdict = r.get(f"{zone}_verdict", "INSUFFICIENT")
            if mean is None or (isinstance(mean, float) and pd.isna(mean)):
                print(f"{r['name']:<14} {zone:<5} {n:>4}  {'n/a':>8}  {'n/a':>9}  {'n/a':>6}  {verdict:<22}")
            else:
                mean_s = f"{mean:+5.1f}%"
                eff_s = f"{eff:+5.1f}pp"
                p_s = f"{p:.3f}" if not pd.isna(p) else "n/a"
                flag = " *" if (not pd.isna(p) and p < 0.05) else ""
                print(f"{r['name']:<14} {zone:<5} {n:>4}  {mean_s:>8}  {eff_s:>9}  {p_s:>6}  {verdict:<22}{flag}")

    # Detailed per-decade table for each signal × zone
    print("\n" + "=" * 110)
    print("Per-decade effect detail")
    print("=" * 110)
    for r in results:
        for zone in ("LOW", "HIGH"):
            decades = r.get(f"{zone}_decades", [])
            if not decades:
                continue
            print(f"\n{r['name']} / {zone}:")
            for decade, n, eff in decades:
                print(f"  {decade:<7}  N={n:>3}   effect={eff:+5.1f}pp")

    # Save new signals to signals.csv (appended)
    long_df = pd.read_csv(DATA / "signals.csv", parse_dates=["date"])
    existing_names = set(long_df["signal"].unique())
    new_rows = []
    for name, s in signals_to_test.items():
        if name in existing_names:
            continue
        s_clean = s.dropna()
        for date, val in s_clean.items():
            new_rows.append({"date": date, "signal": name, "value": float(val)})
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        combined = pd.concat([long_df, new_df], ignore_index=True).sort_values(["signal", "date"])
        combined.to_csv(DATA / "signals.csv", index=False)
        print(f"\nAppended {len(new_rows)} rows to signals.csv ({len(signals_to_test)} new signals)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
