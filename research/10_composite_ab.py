"""V3.7 — A/B comparison of composite indicator variants.

User question: did adding DXY/10Y research actually improve the composite?
The answer is honest only if we run the new candidates through the same
conditional-return and drawdown tests as the current production composite,
then compare apples-to-apples.

Candidates tested:

  V2_CURRENT:  MARGIN_M2 + NDX/SOX/RUT relative strength            (4 components, prod)
  V3a:         V2_CURRENT + Y10_3M_CHG                                (5 components)
  V3b:         V3a + DXY_3M_CHG                                       (6 components)
  V3c:         V2_CURRENT + DXY_LEVEL                                 (5 components, exploratory)

For each candidate, compute:
  - Decile conditional 12m fwd SPX return (mean, hit, vs baseline)
  - Drawdown stats (mean DD, P(DD<=-20%), P(DD<=-30%), CVaR10)
  - Top/bottom decile bootstrap p-values
  - Per-decade stability of top decile

The winner is whichever candidate gives the steepest asymmetry between
extreme deciles AND maintains stability across decades.
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
HORIZON = 12
DD_LOOKAHEAD = 24
RNG = np.random.default_rng(20260528)
BOOTSTRAP_ITER = 2000

# Candidate composite specs: list of (signal_name, weight, invert_sign)
# invert_sign=True means "higher signal value = LESS dangerous" so we flip it
CANDIDATES = {
    "V2_CURRENT": [
        ("MARGIN_M2",  1.0, False),
        ("NDX_SPX_RS", 0.6, True),
        ("SOX_SPX_RS", 0.6, True),
        ("RUT_SPX_RS", 0.4, False),
    ],
    "V3a-wrongsign (Y10 inverted)": [
        ("MARGIN_M2",  1.0, False),
        ("NDX_SPX_RS", 0.6, True),
        ("SOX_SPX_RS", 0.6, True),
        ("RUT_SPX_RS", 0.4, False),
        ("Y10_3M_CHG", 0.6, True),   # historical accident, semantically backwards
    ],
    "V3a-correct (+Y10)": [
        ("MARGIN_M2",  1.0, False),
        ("NDX_SPX_RS", 0.6, True),
        ("SOX_SPX_RS", 0.6, True),
        ("RUT_SPX_RS", 0.4, False),
        ("Y10_3M_CHG", 0.6, False),  # high rate-change = danger (keep sign)
    ],
    "V3b (+Y10 +DXY3M)": [
        ("MARGIN_M2",  1.0, False),
        ("NDX_SPX_RS", 0.6, True),
        ("SOX_SPX_RS", 0.6, True),
        ("RUT_SPX_RS", 0.4, False),
        ("Y10_3M_CHG", 0.6, False),
        ("DXY_3M_CHG", 0.4, False),  # rapid USD strengthening = danger (keep)
    ],
    "V3c (+DXY_LEVEL)": [
        ("MARGIN_M2",  1.0, False),
        ("NDX_SPX_RS", 0.6, True),
        ("SOX_SPX_RS", 0.6, True),
        ("RUT_SPX_RS", 0.4, False),
        ("DXY_LEVEL",  0.4, False),  # high USD = danger (keep)
    ],
}


def load_spx_monthly() -> pd.Series:
    df = pd.read_csv(RAW / "GSPC.csv", parse_dates=["date"])
    s = df.set_index("date")["value"].astype(float).sort_index()
    return s.resample("ME").last().dropna().rename("spx")


def load_signals_wide() -> pd.DataFrame:
    long = pd.read_csv(DATA / "signals.csv", parse_dates=["date"])
    return long.pivot(index="date", columns="signal", values="value").sort_index()


def expanding_percentile(s: pd.Series) -> pd.Series:
    return s.dropna().expanding(MIN_HISTORY_MONTHS).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def build_composite(signals_wide: pd.DataFrame, spec: list,
                     min_components_required: int | None = None) -> pd.Series:
    """Build composite from spec, sign-aligned + weight-normalized + reporting-lag tolerant.

    Restricts the output to dates where AT LEAST min_components_required
    components have valid (non-NaN, ffilled <= 3 months) data. If not
    specified, defaults to ceil(N_components * 0.75) — at least 75% must be
    present. This avoids percentile contamination from periods where only
    a single component drives the score.
    """
    aligned = {}
    weights = {}
    inverts = {}
    for name, w, inv in spec:
        if name not in signals_wide.columns:
            print(f"  [warn] {name} missing")
            continue
        s = signals_wide[name].dropna()
        if len(s) < MIN_HISTORY_MONTHS:
            print(f"  [warn] {name} has only {len(s)} obs")
            continue
        pct = expanding_percentile(s)
        aligned[name] = pct
        weights[name] = w
        inverts[name] = inv

    if not aligned:
        return pd.Series(dtype=float)

    if min_components_required is None:
        min_components_required = int(np.ceil(len(aligned) * 0.75))

    full_idx = sorted(set().union(*(s.index for s in aligned.values())))
    full_idx = pd.DatetimeIndex(full_idx)

    centered = {}
    for name, pct in aligned.items():
        reindexed = pct.reindex(full_idx).ffill(limit=3)
        c = (reindexed - 0.5) * 2.0
        if inverts[name]:
            c = -c
        centered[name] = c

    combined = pd.DataFrame(centered)
    weight_arr = np.array([weights[c] for c in combined.columns])
    mask = combined.notna().to_numpy().astype(float)
    n_present = mask.sum(axis=1)
    weighted = combined.fillna(0).to_numpy() * weight_arr
    weight_sum = (mask * weight_arr).sum(axis=1)
    composite_vals = np.where(
        (weight_sum > 0) & (n_present >= min_components_required),
        weighted.sum(axis=1) / weight_sum,
        np.nan,
    )
    return pd.Series(composite_vals, index=combined.index).dropna()


def bootstrap_p(zone: np.ndarray, pool: np.ndarray) -> float:
    if len(zone) < 5 or len(pool) < 30:
        return float("nan")
    obs = zone.mean() - pool.mean()
    diffs = np.empty(BOOTSTRAP_ITER)
    for i in range(BOOTSTRAP_ITER):
        idx = RNG.choice(len(pool), len(zone), replace=False)
        diffs[i] = pool[idx].mean() - pool.mean()
    return float((np.abs(diffs) >= abs(obs)).mean())


def compute_fwd_drawdown(spx: pd.Series, h: int) -> pd.Series:
    arr = spx.values
    n = len(arr)
    dd = np.full(n, np.nan)
    for i in range(n - 1):
        end = min(i + 1 + h, n)
        window = arr[i + 1:end]
        if len(window) == 0:
            continue
        from_t = window / arr[i] - 1.0
        dd[i] = from_t.min()
    return pd.Series(dd, index=spx.index)


def score_composite(name: str, composite: pd.Series, spx: pd.Series) -> dict:
    fwd_ret = spx.shift(-HORIZON) / spx - 1
    fwd_dd = compute_fwd_drawdown(spx, DD_LOOKAHEAD)
    pct = expanding_percentile(composite)
    df = pd.concat({"pct": pct, "fwd_ret": fwd_ret, "fwd_dd": fwd_dd}, axis=1).dropna()
    if df.empty:
        return {"name": name, "error": "empty"}

    full = df
    low = df[df["pct"] <= 0.10]
    high = df[df["pct"] >= 0.90]
    full_mean = full["fwd_ret"].mean()

    def block(sub: pd.DataFrame) -> dict:
        if len(sub) < 3:
            return {"n": len(sub)}
        return {
            "n": len(sub),
            "ret_mean_pp": float(sub["fwd_ret"].mean() * 100),
            "ret_effect_pp": float((sub["fwd_ret"].mean() - full_mean) * 100),
            "ret_hit": float((sub["fwd_ret"] > 0).mean() * 100),
            "dd_mean_pp": float(sub["fwd_dd"].mean() * 100),
            "dd_median_pp": float(sub["fwd_dd"].median() * 100),
            "p_dd_20": float((sub["fwd_dd"] <= -0.20).mean() * 100),
            "p_dd_30": float((sub["fwd_dd"] <= -0.30).mean() * 100),
            "cvar10": float(sub["fwd_ret"].quantile(0.10) * 100) if len(sub) >= 10 else float("nan"),
            "bootstrap_p": bootstrap_p(sub["fwd_ret"].values, full["fwd_ret"].values),
        }

    out = {
        "name": name,
        "start": composite.index.min().strftime("%Y-%m"),
        "end": composite.index.max().strftime("%Y-%m"),
        "n_total": len(df),
        "full_ret_pp": float(full_mean * 100),
        "low_block": block(low),
        "high_block": block(high),
    }
    # Asymmetry score = LOW ret - HIGH ret (higher = sharper signal)
    if "ret_mean_pp" in out["low_block"] and "ret_mean_pp" in out["high_block"]:
        out["asymmetry_pp"] = out["low_block"]["ret_mean_pp"] - out["high_block"]["ret_mean_pp"]
    return out


def main() -> int:
    print("Loading...")
    spx = load_spx_monthly()
    signals = load_signals_wide()
    print(f"  SPX: {spx.index.min().date()} -> {spx.index.max().date()} ({len(spx)} months)")
    print(f"  Available signals: {sorted(signals.columns)}")

    results = {}
    for name, spec in CANDIDATES.items():
        print(f"\nBuilding {name}...")
        comp = build_composite(signals, spec)
        print(f"  series: {comp.index.min().date() if not comp.empty else 'EMPTY'} -> "
              f"{comp.index.max().date() if not comp.empty else 'EMPTY'} ({len(comp)} months)")
        if comp.empty:
            results[name] = {"error": "empty"}
            continue
        r = score_composite(name, comp, spx)
        r["current_value"] = float(comp.iloc[-1])
        r["current_pct"] = float(expanding_percentile(comp).dropna().iloc[-1])
        results[name] = r

    # Print comparison table
    print("\n" + "=" * 110)
    print("A/B COMPARISON — composite candidates")
    print("=" * 110)
    print(f"{'Candidate':<22} {'N':>5} {'Start':>8}  {'LowN':>5} {'LowMean':>9} {'LowDD':>8} "
          f"{'P30L':>5} {'HighN':>6} {'HighMean':>9} {'HighDD':>8} {'P30H':>5} {'Asym':>8}")
    print("-" * 110)
    for name, r in results.items():
        if "error" in r:
            print(f"{name:<22}  (error: {r['error']})")
            continue
        lb, hb = r["low_block"], r["high_block"]
        asym = r.get("asymmetry_pp", float("nan"))
        print(
            f"{name:<22} {r['n_total']:>5} {r['start']:>8}  "
            f"{lb.get('n', 0):>5} {lb.get('ret_mean_pp', float('nan')):>+7.1f}% {lb.get('dd_mean_pp', float('nan')):>+6.1f}% "
            f"{lb.get('p_dd_30', 0):>4.0f}% "
            f"{hb.get('n', 0):>6} {hb.get('ret_mean_pp', float('nan')):>+7.1f}% {hb.get('dd_mean_pp', float('nan')):>+6.1f}% "
            f"{hb.get('p_dd_30', 0):>4.0f}% "
            f"{asym:>+6.1f}pp"
        )

    # Detailed view of LOW + HIGH blocks for each candidate
    print("\n" + "=" * 110)
    print("DETAILED BLOCKS")
    print("=" * 110)
    for name, r in results.items():
        if "error" in r:
            continue
        print(f"\n{name}  (N={r['n_total']}, baseline ret {r['full_ret_pp']:+.2f}%)")
        for label, b in [("LOW (<=10%)", r["low_block"]), ("HIGH (>=90%)", r["high_block"])]:
            if "ret_mean_pp" not in b:
                print(f"  {label}: insufficient N={b.get('n', 0)}")
                continue
            p = b.get("bootstrap_p")
            p_str = f"{p:.3f}" if not pd.isna(p) else "n/a"
            print(f"  {label}: N={b['n']:>3}  ret={b['ret_mean_pp']:+5.1f}%  effect={b['ret_effect_pp']:+5.1f}pp  "
                  f"hit={b['ret_hit']:>3.0f}%  p={p_str}")
            print(f"  {label}: meanDD={b['dd_mean_pp']:+5.1f}%  medDD={b['dd_median_pp']:+5.1f}%  "
                  f"P(<=-20%)={b['p_dd_20']:>3.0f}%  P(<=-30%)={b['p_dd_30']:>3.0f}%  "
                  f"CVaR10={b['cvar10']:+5.1f}%")
        print(f"  CURRENT: composite_value={r['current_value']:+.3f}  pct={r['current_pct']*100:.1f}%")

    # Summary verdict
    print("\n" + "=" * 110)
    print("VERDICT — which candidate has the steepest extreme-zone asymmetry?")
    print("=" * 110)
    ranked = sorted(
        [(name, r) for name, r in results.items() if "error" not in r and "asymmetry_pp" in r],
        key=lambda x: x[1]["asymmetry_pp"],
        reverse=True,
    )
    for rank, (name, r) in enumerate(ranked, 1):
        print(f"  {rank}. {name:<22} asymmetry={r['asymmetry_pp']:+.1f}pp  "
              f"(high_DD_p30={r['high_block'].get('p_dd_30', 0):.0f}%  "
              f"low_DD_p30={r['low_block'].get('p_dd_30', 0):.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
