"""Render the README with auto-updated tables and headline state."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .signals import Signal


def _pct(x: float, dp: int = 1) -> str:
    return "n/a" if pd.isna(x) or x is None else f"{x * 100:+.{dp}f}%"


def _pp(x: float, dp: int = 1) -> str:
    return "n/a" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:+.{dp}f}pp"


def _zone_emoji(zone: str, higher_is_riskier: bool) -> str:
    if zone == "HIGH":
        return "[BEAR]" if higher_is_riskier else "[BULL]"
    if zone == "LOW":
        return "[BULL]" if higher_is_riskier else "[BEAR]"
    return "[mid]"


def headline(snap: dict) -> str:
    net = snap["net_effect_pp"]
    n_dur_bear = len(snap["triggered_durable_bear"])
    n_dur_bull = len(snap["triggered_durable_bull"])
    n_mostly_bear = len(snap["triggered_mostly_bear"])
    n_mostly_bull = len(snap["triggered_mostly_bull"])

    lean = (
        "leans BEARISH" if net <= -3 else
        "leans BULLISH" if net >= 3 else
        "is approximately NEUTRAL"
    )

    parts = [
        f"**Net 12-month historical effect from currently-triggered signals: `{_pp(net)}` — {lean}.**",
        "",
        f"- Durable (Tier 1) signals triggered: **{n_dur_bear} bearish, {n_dur_bull} bullish**",
        f"- Mostly-directional (Tier 2) signals triggered: **{n_mostly_bear} bearish, {n_mostly_bull} bullish**",
    ]
    return "\n".join(parts)


def signal_table(snap: dict, signals: dict[str, Signal]) -> str:
    lines = [
        "| Signal | Current value | Percentile | Zone | Tier | Effect (12m fwd SPX) |",
        "|---|---:|---:|:-:|:-:|---:|",
    ]
    # Sort: tier severity, then percentile
    def sort_key(r: dict) -> tuple:
        tier_rank = {"DURABLE": 0, "MOSTLY": 1, "REGIME-DEP": 2, "TOMBSTONE": 3, "—": 4}.get(r["tier"], 5)
        return (tier_rank, -abs(r["effect_pp"] or 0))

    rows_sorted = sorted(snap["rows"], key=sort_key)
    for r in rows_sorted:
        sig = signals[r["name"]]
        zone_marker = _zone_emoji(r["zone"], sig.higher_is_riskier)
        effect = "—" if r["effect_pp"] is None else _pp(r["effect_pp"])
        if r["tier"] == "TOMBSTONE":
            effect = "*failed stability test*"
        tier_display = r["tier"] if r["tier"] != "—" else "—"
        pct_display = "n/a" if pd.isna(r["current_percentile"]) else f"{r['current_percentile']*100:.0f}%"
        val_display = f"{r['current_value']:.3f}"
        lines.append(
            f"| {sig.short_name} | {val_display} | {pct_display} | "
            f"{r['zone']} {zone_marker} | {tier_display} | {effect} |"
        )
    return "\n".join(lines)


def stamp_text(snap: dict) -> str:
    return f"_Last updated: **{snap['captured_utc']}**  ·  Data: FRED · Yahoo Finance · FINRA_"


def replace_marker(text: str, marker: str, new_content: str) -> str:
    pattern = rf"<!-- BEGIN:{marker} -->.*?<!-- END:{marker} -->"
    replacement = f"<!-- BEGIN:{marker} -->\n{new_content}\n<!-- END:{marker} -->"
    return re.sub(pattern, replacement, text, flags=re.DOTALL)


def render_readme(readme_path: Path, snap: dict, signals: dict[str, Signal]) -> None:
    text = readme_path.read_text(encoding="utf-8")
    text = replace_marker(text, "STAMP", stamp_text(snap))
    text = replace_marker(text, "HEADLINE", headline(snap))
    text = replace_marker(text, "SIGNAL_TABLE", signal_table(snap, signals))
    readme_path.write_text(text, encoding="utf-8")
