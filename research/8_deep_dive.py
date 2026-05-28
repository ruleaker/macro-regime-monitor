"""V3 deep dive — test derived signals and cross-asset relationships that the
shallow per-signal stability test of script 7 didn't surface.

Hypotheses to test:

  H1. Real yield = 10Y - 10Y breakeven inflation expectations. Extreme real
      yields squeeze equity multiples regardless of nominal level. Test 12m fwd
      SPX returns at top/bottom decile of real yield.

  H2. Credit-rates spread = HY OAS - 10Y. Captures credit cycle stress
      relative to risk-free rate. Real bear markets see this spread blow out.
      (Note: HY OAS history only since 2023 on FRED public CSV — limited)

  H3. Yield curve at 24-month and 36-month forward horizons. The classic
      thesis is that an inverted curve leads recession by 18-24 months, so the
      12m horizon may miss the actual downturn. Test 24/36m fwd.

  H4. Cross-asset: when DXY is in extreme HIGH zone, how does Gold behave?
      How about SPX? Maps "capital flows" — does money go to USD vs gold
      during stress regimes?

  H5. Joint extremes: when MARGIN_M2 HIGH (durable bear signal) AND DXY HIGH
      AND yield curve LOW (inverted) all fire together, what happens to fwd
      returns?

The goal is to find signals that DO carry information once we look at the
right metric, horizon, or combination.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = ROOT / "data" / "raw"

MIN_HISTORY_MONTHS = 60
BOOTSTRAP_ITER = 2000
RNG = np.random.default_rng(20260528)


def load_raw(name: str) -> pd.Series:
    df = pd.read_csv(RAW / f"{name}.csv", parse_dates=["date"])
    return df.set_index("date")["value"].astype(float).sort_index()


def to_month_end(s: pd.Series, how: str = "last") -> pd.Series:
    if how == "last":
        return s.sort_index().resample("ME").last().dropna()
    return s.sort_index().resample("ME").mean().dropna()


def expanding_percentile(s: pd.Series) -> pd.Series:
    return s.dropna().expanding(MIN_HISTORY_MONTHS).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def bootstrap_p(zone: np.ndarray, pool: np.ndarray) -> float:
    if len(zone) < 5 or len(pool) < 30:
        return float("nan")
    obs = zone.mean() - pool.mean()
    diffs = np.empty(BOOTSTRAP_ITER)
    for i in range(BOOTSTRAP_ITER):
        idx = RNG.choice(len(pool), len(zone), replace=False)
        diffs[i] = pool[idx].mean() - pool.mean()
    return float((np.abs(diffs) >= abs(obs)).mean())


def cond_stats(signal: pd.Series, target: pd.Series, horizon: int,
                low_cut: float = 0.10, high_cut: float = 0.90) -> dict:
    """Conditional fwd target return stats at extreme percentiles of signal."""
    fwd = target.shift(-horizon) / target - 1
    pct = expanding_percentile(signal)
    df = pd.DataFrame({"pct": pct, "fwd": fwd}).dropna()
    if df.empty:
        return {"horizon": horizon, "n_total": 0}
    full = df["fwd"]
    out = {"horizon": horizon, "n_total": len(df), "full_mean_pp": float(full.mean() * 100)}

    for label, mask in [("LOW", df["pct"] <= low_cut), ("HIGH", df["pct"] >= high_cut)]:
        zone = df.loc[mask, "fwd"].values
        if len(zone) < 5:
            out[f"{label}_n"] = len(zone)
            out[f"{label}_mean_pp"] = float("nan")
            out[f"{label}_effect_pp"] = float("nan")
            out[f"{label}_p"] = float("nan")
        else:
            out[f"{label}_n"] = len(zone)
            out[f"{label}_mean_pp"] = float(zone.mean() * 100)
            out[f"{label}_effect_pp"] = float((zone.mean() - full.mean()) * 100)
            out[f"{label}_p"] = bootstrap_p(zone, full.values)
    return out


def print_cond(name: str, stats: dict):
    h = stats["horizon"]
    full = stats.get("full_mean_pp", float("nan"))
    print(f"\n{name} ({h}m horizon, baseline {full:+.2f}%):")
    for zone in ("LOW", "HIGH"):
        n = stats.get(f"{zone}_n", 0)
        m = stats.get(f"{zone}_mean_pp")
        eff = stats.get(f"{zone}_effect_pp")
        p = stats.get(f"{zone}_p")
        if pd.isna(m):
            print(f"  {zone}: N={n} (insufficient)")
        else:
            sig = " *" if (not pd.isna(p) and p < 0.05) else ""
            print(f"  {zone}: N={n:>3}  mean={m:+5.1f}%  effect={eff:+5.1f}pp  p={p:.3f}{sig}")


def main() -> int:
    print("Loading raw series...")
    spx_d = load_raw("GSPC")
    spx_m = to_month_end(spx_d, "last")
    gold_d = load_raw("GC=F")
    gold_m = to_month_end(gold_d, "last")
    dxy_d = load_raw("DX-Y.NYB")
    dxy_m = to_month_end(dxy_d, "last")
    y10_d = load_raw("DGS10")
    y10_m = to_month_end(y10_d, "mean")
    y3m_d = load_raw("DGS3MO")
    y3m_m = to_month_end(y3m_d, "mean")
    breakeven_d = load_raw("T10YIE")
    breakeven_m = to_month_end(breakeven_d, "mean")
    hyoas_d = load_raw("BAMLH0A0HYM2")
    hyoas_m = to_month_end(hyoas_d, "mean")

    # ===================================================================
    # H1: Real yield = 10Y - 10Y breakeven
    # ===================================================================
    print("\n" + "=" * 80)
    print("H1: Real yield (10Y - 10Y breakeven inflation)")
    print("=" * 80)
    aligned = pd.concat({"y10": y10_m, "be": breakeven_m}, axis=1).dropna()
    real_yield = aligned["y10"] - aligned["be"]
    real_yield.name = "REAL_YIELD"
    print(f"Real yield series: {real_yield.index.min().date()} -> {real_yield.index.max().date()}  N={len(real_yield)}")
    print(f"Current: {real_yield.iloc[-1]:+.2f}%")

    # Real yield only has data from 2003. Use quintile (20/80) for more N
    for h in [12, 24]:
        print_cond(f"  REAL_YIELD (quintile 20/80)",
                    cond_stats(real_yield, spx_m, horizon=h, low_cut=0.20, high_cut=0.80))

    # ===================================================================
    # H2: Credit-rates spread = HY OAS - 10Y
    # ===================================================================
    print("\n" + "=" * 80)
    print("H2: Credit-rates spread (HY OAS - 10Y)")
    print("=" * 80)
    aligned = pd.concat({"hy": hyoas_m, "y10": y10_m}, axis=1).dropna()
    credit_spread = aligned["hy"] - aligned["y10"]
    credit_spread.name = "CREDIT_RATES"
    print(f"Series: {credit_spread.index.min().date()} -> {credit_spread.index.max().date()}  N={len(credit_spread)}")
    print("Note: HY OAS history is only 3 years via FRED CSV — this test is exploratory")
    print_cond(f"  CREDIT_RATES (quintile)",
                cond_stats(credit_spread, spx_m, horizon=12, low_cut=0.20, high_cut=0.80))

    # ===================================================================
    # H3: Yield curve at multi-horizon (12 / 24 / 36 month)
    # ===================================================================
    print("\n" + "=" * 80)
    print("H3: Yield curve (10Y - 3M) at multiple horizons")
    print("=" * 80)
    aligned = pd.concat({"y10": y10_m, "y3m": y3m_m}, axis=1).dropna()
    yc = (aligned["y10"] - aligned["y3m"]) * 100  # bps
    yc.name = "YIELD_CURVE"
    print(f"Series: {yc.index.min().date()} -> {yc.index.max().date()}  N={len(yc)}")
    print(f"Current: {yc.iloc[-1]:+.0f} bps")
    for h in [12, 18, 24, 36]:
        print_cond(f"  YIELD_CURVE (decile)",
                    cond_stats(yc, spx_m, horizon=h, low_cut=0.10, high_cut=0.90))

    # ===================================================================
    # H4: Cross-asset — when DXY is extreme, what does Gold do?
    # ===================================================================
    print("\n" + "=" * 80)
    print("H4: Cross-asset — DXY extreme conditional on GOLD and SPX 12m fwd")
    print("=" * 80)
    print(f"DXY series:  {dxy_m.index.min().date()} -> {dxy_m.index.max().date()}  N={len(dxy_m)}")
    print(f"Gold series: {gold_m.index.min().date()} -> {gold_m.index.max().date()}  N={len(gold_m)}")

    print("\n  Target = GOLD 12m fwd return:")
    print_cond(f"  DXY_LEVEL (decile)",
                cond_stats(dxy_m, gold_m, horizon=12, low_cut=0.10, high_cut=0.90))
    print("\n  Target = SPX 12m fwd return (for comparison):")
    print_cond(f"  DXY_LEVEL (decile)",
                cond_stats(dxy_m, spx_m, horizon=12, low_cut=0.10, high_cut=0.90))
    print("\n  Target = GOLD 12m fwd, signal = DXY 3m % change (rapid USD moves):")
    print_cond(f"  DXY_3M_CHG (decile)",
                cond_stats(dxy_m.pct_change(3) * 100, gold_m, horizon=12, low_cut=0.10, high_cut=0.90))

    # ===================================================================
    # H5: Joint extremes (MARGIN_M2 HIGH ∧ DXY HIGH ∧ YIELD_CURVE LOW)
    # ===================================================================
    print("\n" + "=" * 80)
    print("H5: Joint extremes — multiple bearish signals firing together")
    print("=" * 80)

    long = pd.read_csv(DATA / "signals.csv", parse_dates=["date"])
    sig_wide = long.pivot(index="date", columns="signal", values="value").sort_index()

    # Build pct for each of the joint-extreme components
    pct_margin = expanding_percentile(sig_wide["MARGIN_M2"].dropna())
    pct_dxy = expanding_percentile(dxy_m)
    pct_yc = expanding_percentile(yc)

    fwd_12 = spx_m.shift(-12) / spx_m - 1
    grid = pd.concat({
        "fwd_12": fwd_12,
        "margin_pct": pct_margin,
        "dxy_pct": pct_dxy,
        "yc_pct": pct_yc,
    }, axis=1).dropna()

    full_mean = grid["fwd_12"].mean()
    print(f"Joint sample baseline 12m fwd: {full_mean*100:+.2f}%  N={len(grid)}")

    # Test combinations
    tests = [
        ("MARGIN_M2 HIGH",   (grid["margin_pct"] >= 0.80)),
        ("DXY HIGH",          (grid["dxy_pct"] >= 0.80)),
        ("YC LOW (inverted)", (grid["yc_pct"] <= 0.20)),
        ("MARGIN_M2 HIGH ∧ DXY HIGH",                  (grid["margin_pct"] >= 0.80) & (grid["dxy_pct"] >= 0.80)),
        ("MARGIN_M2 HIGH ∧ YC LOW",                     (grid["margin_pct"] >= 0.80) & (grid["yc_pct"] <= 0.20)),
        ("DXY HIGH ∧ YC LOW",                            (grid["dxy_pct"] >= 0.80) & (grid["yc_pct"] <= 0.20)),
        ("MARGIN_M2 HIGH ∧ DXY HIGH ∧ YC LOW",          (grid["margin_pct"] >= 0.80) & (grid["dxy_pct"] >= 0.80) & (grid["yc_pct"] <= 0.20)),
    ]
    print(f"\n{'Condition':<45} {'N':>4}  {'Mean':>8}  {'Effect':>8}  {'Hit':>5}")
    print("-" * 80)
    for label, mask in tests:
        sub = grid.loc[mask, "fwd_12"]
        if len(sub) < 3:
            print(f"{label:<45} {len(sub):>4}  (insufficient)")
            continue
        mean = sub.mean()
        eff = (mean - full_mean) * 100
        hit = (sub > 0).mean()
        print(f"{label:<45} {len(sub):>4}  {mean*100:+6.2f}%  {eff:+6.1f}pp  {hit*100:>4.0f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
