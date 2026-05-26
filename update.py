"""Macro Regime Monitor — daily dashboard update.

Fetches fresh data, computes the 5 production signals (+ MCAP_M2 tombstone),
generates charts, and updates README in place. Designed to run on a daily
GitHub Actions cron.

Run locally:
    python update.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from monitor import signals as sig_mod
from monitor import plots
from monitor import render

ROOT = Path(__file__).resolve().parent
CHARTS = ROOT / "charts"
DATA = ROOT / "data"
HISTORY = DATA / "history"
README = ROOT / "README.md"


def fetch_spx_monthly() -> pd.Series:
    """Get SPX monthly for chart overlays."""
    return sig_mod._to_month_end(sig_mod._fetch_yahoo("^GSPC"), how="last").rename("spx")


def build_conditional_table(signals: dict[str, sig_mod.Signal], snap: dict) -> list[dict]:
    """Build rows for the historical effects bar chart."""
    rows = []
    triggered_names = {n for n, _ in (
        snap["triggered_durable_bear"] + snap["triggered_durable_bull"]
        + snap["triggered_mostly_bear"] + snap["triggered_mostly_bull"]
    )}
    cat_order = {"leverage": 0, "leadership": 1, "valuation": 2, "liquidity": 3}
    for name, sig in signals.items():
        if name == "MCAP_M2":
            continue
        for zone, eff, n in [
            ("LOW", sig.effect_low_pp, sig.n_low),
            ("HIGH", sig.effect_high_pp, sig.n_high),
        ]:
            if eff is None:
                continue
            tier = sig.tier_low if zone == "LOW" else sig.tier_high
            triggered_now = (name in triggered_names) and (sig.zone == zone)
            rows.append({
                "label": f"{sig.short_name} - {zone}",
                "effect_pp": eff,
                "n": n,
                "tier": tier,
                "triggered": triggered_now,
                "category_sort": cat_order.get(sig.category, 9),
            })
    return rows


def save_snapshot(snap: dict) -> None:
    DATA.mkdir(exist_ok=True)
    HISTORY.mkdir(exist_ok=True)
    payload = {k: v for k, v in snap.items() if k != "rows"}
    # rows -> JSON-friendly form (strip pandas types)
    payload["rows"] = [
        {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in r.items()}
        for r in snap["rows"]
    ]
    # Stringify the tuple lists
    for k in ("triggered_durable_bear", "triggered_durable_bull",
              "triggered_mostly_bear", "triggered_mostly_bull"):
        payload[k] = [{"name": n, "effect_pp": e} for n, e in payload[k]]

    (DATA / "latest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    (HISTORY / f"{stamp}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    CHARTS.mkdir(exist_ok=True)

    print("Building signals...")
    signals = sig_mod.build_all()

    print("\nFetching SPX monthly...")
    spx = fetch_spx_monthly()

    print("Computing snapshot...")
    snap = sig_mod.snapshot(signals)
    print(f"  Net effect: {snap['net_effect_pp']:+.2f} pp")
    print(f"  Durable triggered (bear/bull): {len(snap['triggered_durable_bear'])}/{len(snap['triggered_durable_bull'])}")
    print(f"  Mostly triggered (bear/bull):  {len(snap['triggered_mostly_bear'])}/{len(snap['triggered_mostly_bull'])}")

    print("\nRendering charts...")
    p1 = plots.plot_overview(signals, spx, CHARTS / "overview.png")
    print(f"  wrote {p1}")
    cond_rows = build_conditional_table(signals, snap)
    p2 = plots.plot_conditional_returns(cond_rows, full_sample_mean_pct=10.0,
                                         out_path=CHARTS / "conditional_returns.png")
    print(f"  wrote {p2}")

    print("\nUpdating README + saving snapshot...")
    render.render_readme(README, snap, signals)
    save_snapshot(snap)

    print("\nCurrent state (production signals):")
    for r in snap["rows"]:
        print(
            f"  {r['name']:<14} val={r['current_value']:>9.3f}  "
            f"pct={r['current_percentile']*100:>5.1f}%  "
            f"zone={r['zone']:<4}  tier={r['tier']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
