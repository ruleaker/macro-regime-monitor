"""Chart rendering for the dashboard.

Two main charts:

  1. overview.png — 5 signals' percentile rank over time, with extreme bands
     (top 20% / bottom 20%) shaded, current value marker, SPX log overlay.

  2. conditional_returns.png — bar chart of historical 12-month forward SPX
     return by signal × zone, with full-sample baseline as a horizontal line.
     Currently-triggered zones are highlighted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .signals import Signal, QUINTILE_LOW, QUINTILE_HIGH
from .composite import CompositeState, EXTREME_LOW_PCT, EXTREME_HIGH_PCT, DECILE_STATS

BG = "#0d1117"
FG = "#e6edf3"
GRID = "#21262d"
ACCENT = "#a371f7"
BEAR = "#f85149"
BULL = "#3fb950"
NEUTRAL = "#58a6ff"
BAND_BG = "#f8514922"  # transparent red for high band
BAND_BG_LOW = "#3fb95022"  # transparent green for low band


def _style_ax(ax: plt.Axes) -> None:
    ax.set_facecolor(BG)
    ax.tick_params(colors=FG, which="both", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(True, color=GRID, linestyle="-", linewidth=0.5, alpha=0.7)


def plot_overview(signals: dict[str, Signal], spx: pd.Series, out_path: Path) -> Path:
    """5-panel chart: each signal's percentile rank over time + SPX overlay."""
    production_signals = {k: v for k, v in signals.items() if k != "MCAP_M2"}
    n = len(production_signals) + 1  # +1 for SPX panel at top
    fig, axes = plt.subplots(n, 1, figsize=(12, 2.0 * n), sharex=True,
                              gridspec_kw={"height_ratios": [1.5] + [1] * (n - 1)})
    fig.patch.set_facecolor(BG)

    # Top: SPX log scale
    ax = axes[0]
    spx_clip = spx[spx.index >= pd.Timestamp("1990-01-01")]
    ax.plot(spx_clip.index, spx_clip.values, color=ACCENT, linewidth=1.4)
    ax.set_yscale("log")
    ax.set_ylabel("SPX (log)", color=ACCENT, fontsize=10)
    ax.set_title("Macro Regime Monitor — signal percentile rank with extreme bands",
                  color=FG, fontsize=13, fontweight="bold", pad=12, loc="left")
    _style_ax(ax)

    # One panel per signal
    for ax_idx, (name, sig) in enumerate(production_signals.items(), start=1):
        ax = axes[ax_idx]
        pct = sig.percentile_series.dropna() * 100
        pct = pct[pct.index >= pd.Timestamp("1990-01-01")]

        # Extreme bands
        ax.axhspan(QUINTILE_HIGH * 100, 100, color=BAND_BG, zorder=0)
        ax.axhspan(0, QUINTILE_LOW * 100, color=BAND_BG_LOW, zorder=0)

        # Line — color by current zone
        zone = sig.zone
        line_color = BEAR if (zone == "HIGH" and sig.higher_is_riskier) or (zone == "LOW" and not sig.higher_is_riskier) else \
                     BULL if zone in ("HIGH", "LOW") else NEUTRAL
        ax.plot(pct.index, pct.values, color=line_color, linewidth=1.4)
        ax.fill_between(pct.index, pct.values, color=line_color, alpha=0.15)

        # Current marker
        if not pct.empty:
            ax.scatter([pct.index[-1]], [pct.iloc[-1]], color=line_color,
                       s=40, zorder=5, edgecolors=FG, linewidths=0.8)

        ax.set_ylim(0, 100)
        ax.set_yticks([0, 20, 50, 80, 100])
        ax.set_ylabel(name, color=FG, fontsize=9)
        _style_ax(ax)

        # Right-side label with current state
        if not pct.empty:
            label = f"{pct.iloc[-1]:.0f}th · {zone}"
            ax.text(0.99, 0.5, label, transform=ax.transAxes,
                    color=line_color, fontsize=10, ha="right", va="center",
                    fontweight="bold",
                    bbox=dict(facecolor=BG, edgecolor=line_color, alpha=0.85, pad=4))

    # X-axis on bottom panel
    axes[-1].xaxis.set_major_locator(mdates.YearLocator(5))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.99, 0.005, f"Updated {stamp}  ·  Bands: top/bottom 20%",
             ha="right", va="bottom", color=FG, fontsize=8, alpha=0.7)

    plt.tight_layout()
    fig.savefig(out_path, dpi=170, facecolor=BG)
    plt.close(fig)
    return out_path


def plot_composite(state: CompositeState, spx: pd.Series, out_path: Path) -> Path:
    """Two-panel chart: SPX log + composite percentile rank with extreme bands."""
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 6.5), sharex=True,
        gridspec_kw={"height_ratios": [1.5, 1.5]},
    )
    fig.patch.set_facecolor(BG)

    pct = state.percentile_series.dropna() * 100
    series = state.series.loc[pct.index]

    spx_clip = spx[spx.index >= series.index.min()]
    ax1.plot(spx_clip.index, spx_clip.values, color=ACCENT, linewidth=1.4)
    ax1.set_yscale("log")
    ax1.set_ylabel("SPX (log)", color=ACCENT, fontsize=10)
    ax1.set_title("Composite Cycle Indicator — extreme deciles historically predict 12m SPX direction",
                  color=FG, fontsize=13, fontweight="bold", pad=12, loc="left")
    _style_ax(ax1)

    # Shade SPX panel for periods where composite is in extreme high (red) or low (green)
    for zone_pct, color in [(pct[pct >= EXTREME_HIGH_PCT * 100], BAND_BG),
                              (pct[pct <= EXTREME_LOW_PCT * 100], BAND_BG_LOW)]:
        if zone_pct.empty:
            continue
        # Draw vertical spans for contiguous regions
        idx = zone_pct.index
        for i, d in enumerate(idx):
            span_color = color.replace("22", "33")
            ax1.axvspan(d - pd.Timedelta(days=15), d + pd.Timedelta(days=15),
                        color=span_color, zorder=0)

    # Bottom: composite percentile
    ax2.axhspan(EXTREME_HIGH_PCT * 100, 100, color=BAND_BG, zorder=0)
    ax2.axhspan(0, EXTREME_LOW_PCT * 100, color=BAND_BG_LOW, zorder=0)
    ax2.axhline(50, color=GRID, linewidth=0.6, linestyle="--", alpha=0.5)

    line_color = (
        BEAR if state.zone == "EXTREME_HIGH" else
        BULL if state.zone == "EXTREME_LOW" else
        NEUTRAL
    )
    ax2.plot(pct.index, pct.values, color=line_color, linewidth=1.5)
    ax2.fill_between(pct.index, 50, pct.values,
                      where=(pct.values >= 50), color=BEAR, alpha=0.10, interpolate=True)
    ax2.fill_between(pct.index, 50, pct.values,
                      where=(pct.values < 50), color=BULL, alpha=0.10, interpolate=True)

    # Current marker + annotation
    ax2.scatter([pct.index[-1]], [pct.iloc[-1]], color=line_color, s=60, zorder=5,
                edgecolors=FG, linewidths=0.9)
    current_label = f"current: {pct.iloc[-1]:.0f}th pct · {state.zone}"
    ax2.text(0.99, 0.92, current_label, transform=ax2.transAxes,
              color=line_color, fontsize=10, ha="right", va="top",
              fontweight="bold",
              bbox=dict(facecolor=BG, edgecolor=line_color, alpha=0.85, pad=4))

    ax2.set_ylim(0, 100)
    ax2.set_yticks([0, 10, 30, 50, 70, 90, 100])
    ax2.set_ylabel("Composite percentile", color=FG, fontsize=10)
    _style_ax(ax2)
    ax2.xaxis.set_major_locator(mdates.YearLocator(5))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.99, 0.005,
             f"Components: {', '.join(state.components_used)}  ·  Updated {stamp}",
             ha="right", va="bottom", color=FG, fontsize=8, alpha=0.7)

    plt.tight_layout()
    fig.savefig(out_path, dpi=170, facecolor=BG)
    plt.close(fig)
    return out_path


def plot_composite_decile_returns(out_path: Path) -> Path:
    """Bar chart of historical 12m SPX forward returns by composite decile."""
    labels = [d[0] for d in DECILE_STATS]
    means = [d[2] for d in DECILE_STATS]
    ns = [d[1] for d in DECILE_STATS]
    hits = [d[3] for d in DECILE_STATS]

    fig, ax = plt.subplots(figsize=(11, 5.5))
    fig.patch.set_facecolor(BG)

    colors = [BULL if m > 12 else BEAR if m < 0 else NEUTRAL for m in means]
    bars = ax.bar(labels, means, color=colors, edgecolor=GRID, alpha=0.9)

    # Annotate each bar with N + hit rate
    for bar, n, hit, m in zip(bars, ns, hits, means):
        y = bar.get_height()
        offset = 1.5 if y >= 0 else -1.5
        va = "bottom" if y >= 0 else "top"
        ax.text(bar.get_x() + bar.get_width() / 2, y + offset,
                f"N={n}\n{hit}% pos",
                color=FG, ha="center", va=va, fontsize=8, alpha=0.9)

    ax.axhline(9.6, color=FG, linewidth=0.8, linestyle="--", alpha=0.6,
                label="Full-sample baseline +9.6%")
    ax.set_ylabel("12-month SPX forward return (%)", color=FG, fontsize=10)
    ax.set_title("Historical 12-month SPX forward returns by composite percentile decile",
                  color=FG, fontsize=12, fontweight="bold", pad=10, loc="left")
    leg = ax.legend(loc="upper right", facecolor=BG, edgecolor=GRID, labelcolor=FG)
    for txt in leg.get_texts():
        txt.set_color(FG)
    _style_ax(ax)
    ax.set_ylim(-25, 45)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.99, 0.005, f"Source: research/6_composite.py  ·  Updated {stamp}",
             ha="right", va="bottom", color=FG, fontsize=8, alpha=0.7)

    plt.tight_layout()
    fig.savefig(out_path, dpi=170, facecolor=BG)
    plt.close(fig)
    return out_path


def plot_conditional_returns(rows: list[dict], full_sample_mean_pct: float, out_path: Path) -> Path:
    """Bar chart of zone-vs-baseline effect for each signal × zone."""
    df = pd.DataFrame(rows)
    # Only plot the production signals with quantified effect
    df = df[df["effect_pp"].notna()]
    df = df.sort_values(["category_sort", "effect_pp"])

    fig, ax = plt.subplots(figsize=(11, 5.5))
    fig.patch.set_facecolor(BG)

    bar_colors = [BEAR if e < 0 else BULL for e in df["effect_pp"]]
    bars = ax.barh(df["label"], df["effect_pp"], color=bar_colors, edgecolor=GRID)

    # Highlight currently-triggered with bold edge
    for bar, triggered in zip(bars, df["triggered"]):
        if triggered:
            bar.set_edgecolor(FG)
            bar.set_linewidth(2.0)

    ax.axvline(0, color=FG, linewidth=0.8)
    _style_ax(ax)
    ax.set_xlabel("12-month SPX forward return effect vs full sample (pp)", color=FG, fontsize=10)
    ax.set_title("Historical conditional effects — currently-triggered zones highlighted with white border",
                  color=FG, fontsize=12, fontweight="bold", pad=10, loc="left")

    # Annotate bars with N. For negative bars, place N just to the right of zero
    # so it doesn't collide with the y-axis label.
    for bar, n in zip(bars, df["n"]):
        x = bar.get_width()
        if x >= 0:
            ax.text(x + 0.4, bar.get_y() + bar.get_height() / 2,
                    f"N={n}", color=FG, va="center", ha="left", fontsize=9, alpha=0.85)
        else:
            ax.text(0.4, bar.get_y() + bar.get_height() / 2,
                    f"N={n}", color=FG, va="center", ha="left", fontsize=9, alpha=0.85)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.99, 0.005, f"Quintile thresholds (top/bottom 20%)  ·  Updated {stamp}",
             ha="right", va="bottom", color=FG, fontsize=8, alpha=0.7)

    plt.tight_layout()
    fig.savefig(out_path, dpi=170, facecolor=BG)
    plt.close(fig)
    return out_path
