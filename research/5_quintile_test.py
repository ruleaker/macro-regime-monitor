"""Re-run conditional return + stability with quintile (top/bottom 20%) thresholds.

Goal: see if loosening the extreme cutoff from decile (10%) to quintile (20%)
gives enough samples to confirm Tier 2 signals as decade-durable, without
washing out the effect.

Outputs a side-by-side comparison vs the decile results.
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
MIN_HISTORY_MONTHS = 60
BOOTSTRAP_ITER = 2000
RNG = np.random.default_rng(20260527)

THRESHOLDS = {
    "decile":   (0.10, 0.90),
    "quintile": (0.20, 0.80),
}


def load_spx_monthly() -> pd.Series:
    df = pd.read_csv(RAW / "GSPC.csv", parse_dates=["date"])
    s = df.set_index("date")["value"].astype(float).sort_index()
    return s.resample("ME").last().dropna().rename("spx")


def load_signals_wide() -> pd.DataFrame:
    long = pd.read_csv(DATA / "signals.csv", parse_dates=["date"])
    return long.pivot(index="date", columns="signal", values="value").sort_index()


def expanding_percentile(s: pd.Series) -> pd.Series:
    return s.expanding(MIN_HISTORY_MONTHS).apply(
        lambda x: float((x.iloc[-1] >= x).mean()), raw=False
    )


def bootstrap_pvalue(in_zone: np.ndarray, pool: np.ndarray, n_iter: int = BOOTSTRAP_ITER) -> float:
    if len(in_zone) < 5 or len(pool) < 30:
        return float("nan")
    observed_diff = in_zone.mean() - pool.mean()
    n_in = len(in_zone)
    diffs = np.empty(n_iter)
    for i in range(n_iter):
        idx = RNG.choice(len(pool), n_in, replace=False)
        diffs[i] = pool[idx].mean() - pool.mean()
    return float((np.abs(diffs) >= abs(observed_diff)).mean())


def decade_of(ts: pd.Timestamp) -> str:
    d = ts.year - (ts.year % 10)
    return f"{d}s"


def analyze(spx: pd.Series, signals: pd.DataFrame, low_cut: float, high_cut: float) -> pd.DataFrame:
    fwd = spx.shift(-HORIZON) / spx - 1
    rows = []
    for sig_name in signals.columns:
        s = signals[sig_name].dropna()
        pct = expanding_percentile(s)
        df = pd.DataFrame({"pct": pct}).join(fwd.rename("fwd"), how="inner").dropna()
        if df.empty:
            continue
        full = df["fwd"]
        for zone, mask in [
            ("LOW", df["pct"] <= low_cut),
            ("HIGH", df["pct"] >= high_cut),
        ]:
            zone_vals = df.loc[mask, "fwd"].values
            n = len(zone_vals)
            mean = float(zone_vals.mean()) if n > 0 else np.nan
            p = bootstrap_pvalue(zone_vals, full.values) if n >= 5 else float("nan")
            # decade-level
            decade_effects = {}
            df_with_decade = df.copy()
            df_with_decade["decade"] = df.index.to_series().apply(decade_of)
            for decade_label, dec_sub in df_with_decade.groupby("decade"):
                decade_baseline = dec_sub["fwd"].mean()
                dec_zone = dec_sub.loc[
                    (dec_sub["pct"] <= low_cut) if zone == "LOW"
                    else (dec_sub["pct"] >= high_cut),
                    "fwd"
                ]
                if len(dec_zone) == 0:
                    continue
                decade_effects[decade_label] = {
                    "n": len(dec_zone),
                    "effect_pp": (dec_zone.mean() - decade_baseline) * 100,
                }
            # Classify durability: count decades with consistent-direction effect ≥ 2pp magnitude
            same_sign_count = 0
            opposite_sign_count = 0
            target_sign = np.sign(mean - full.mean()) if not np.isnan(mean) else 0
            for dec, info in decade_effects.items():
                eff = info["effect_pp"]
                if abs(eff) < 2:
                    continue
                if np.sign(eff) == target_sign:
                    same_sign_count += 1
                else:
                    opposite_sign_count += 1
            n_decades = len(decade_effects)
            rows.append({
                "signal": sig_name, "zone": zone,
                "n": n,
                "mean_pp": mean * 100 if not np.isnan(mean) else np.nan,
                "full_mean_pp": full.mean() * 100,
                "effect_pp": (mean - full.mean()) * 100 if not np.isnan(mean) else np.nan,
                "p_value": p,
                "n_decades_observed": n_decades,
                "n_decades_same_sign": same_sign_count,
                "n_decades_opposite": opposite_sign_count,
                "decade_detail": "; ".join(
                    f"{d}:N={info['n']},eff={info['effect_pp']:+.1f}pp"
                    for d, info in sorted(decade_effects.items())
                ),
            })
    return pd.DataFrame(rows)


def classify(row: pd.Series) -> str:
    if np.isnan(row["mean_pp"]) or row["n"] < 5:
        return "INSUFFICIENT"
    if row["n_decades_observed"] < 2:
        return "INSUFFICIENT (one decade)"
    same = row["n_decades_same_sign"]
    opp = row["n_decades_opposite"]
    total_directional = same + opp
    if total_directional == 0:
        return "WEAK (no decade ≥2pp)"
    if same >= 3 and opp == 0:
        return "DURABLE"
    if same >= 2 and opp == 0 and row["n_decades_observed"] <= 3:
        return "MOSTLY"
    if same > opp and opp == 0:
        return "MOSTLY"
    if same > opp:
        return "REGIME-DEPENDENT (lean)"
    if opp > same:
        return "FAILED"
    return "REGIME-DEPENDENT"


def main() -> int:
    spx = load_spx_monthly()
    signals = load_signals_wide()

    results = {}
    for label, (low, high) in THRESHOLDS.items():
        print(f"\nRunning {label} (low<={low}, high>={high})...")
        df = analyze(spx, signals, low, high)
        df["class"] = df.apply(classify, axis=1)
        df["threshold"] = label
        results[label] = df

    # Combine for side-by-side comparison
    combined = pd.concat([results["decile"], results["quintile"]], ignore_index=True)
    combined.to_csv(DATA / "threshold_comparison.csv", index=False)

    # Print side-by-side
    print("\n" + "=" * 110)
    print("Side-by-side: decile (10%) vs quintile (20%) extreme cutoffs")
    print("=" * 110)
    print(f"{'Signal':<14} {'Zone':<5} | "
          f"{'DEC N':>5} {'DEC eff':>8} {'DEC p':>6} {'DEC class':<22} | "
          f"{'QUI N':>5} {'QUI eff':>8} {'QUI p':>6} {'QUI class':<22}")
    print("-" * 110)
    for sig in signals.columns:
        for zone in ["LOW", "HIGH"]:
            dec = results["decile"][(results["decile"]["signal"] == sig) & (results["decile"]["zone"] == zone)]
            qui = results["quintile"][(results["quintile"]["signal"] == sig) & (results["quintile"]["zone"] == zone)]
            if dec.empty or qui.empty:
                continue
            d = dec.iloc[0]
            q = qui.iloc[0]
            d_p = f"{d['p_value']:.3f}" if not pd.isna(d["p_value"]) else "n/a"
            q_p = f"{q['p_value']:.3f}" if not pd.isna(q["p_value"]) else "n/a"
            d_eff = f"{d['effect_pp']:+.1f}pp" if not pd.isna(d["effect_pp"]) else "n/a"
            q_eff = f"{q['effect_pp']:+.1f}pp" if not pd.isna(q["effect_pp"]) else "n/a"
            print(
                f"{sig:<14} {zone:<5} | "
                f"{d['n']:>5} {d_eff:>8} {d_p:>6} {d['class']:<22} | "
                f"{q['n']:>5} {q_eff:>8} {q_p:>6} {q['class']:<22}"
            )

    # Promotion check: which signals upgraded from quintile?
    print("\n" + "=" * 110)
    print("Promotion check: signals whose tier improves when using quintile")
    print("=" * 110)
    for sig in signals.columns:
        for zone in ["LOW", "HIGH"]:
            dec = results["decile"][(results["decile"]["signal"] == sig) & (results["decile"]["zone"] == zone)]
            qui = results["quintile"][(results["quintile"]["signal"] == sig) & (results["quintile"]["zone"] == zone)]
            if dec.empty or qui.empty:
                continue
            d, q = dec.iloc[0], qui.iloc[0]
            if d["class"] != q["class"]:
                arrow = "->"
                print(f"  {sig:<14} {zone:<5}: {d['class']:<22} {arrow} {q['class']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
