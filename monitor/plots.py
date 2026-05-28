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
from .composite import CompositeState, EXTREME_LOW_PCT, EXTREME_HIGH_PCT, DECILE_STATS, DRAWDOWN_STATS
from .trend import TrendState, supertrend, apply_smoothing, VARIABLES as TREND_VARS
from .predictive import PredictiveSignal, SPX_PEAKS_HIST, SPX_TROUGHS_HIST

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


def plot_liquidity_trends(states: dict, spx: pd.Series, out_path: Path) -> Path:
    """Multi-panel chart: SPX reference on top + SuperTrend per macro variable below.

    Designed so the reader can visually trace each liquidity inflection across
    to its SPX consequence: 2008 GFC, 2020 COVID easing, 2022 QT, etc.
    """
    items = [(name, st) for name, st in states.items() if not pd.isna(st.current_value)]
    n = len(items)
    if n == 0:
        return out_path

    start_date = pd.Timestamp("2005-01-01")

    # Total panels: SPX + each macro variable
    n_panels = n + 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(12, 1.7 * n_panels), sharex=True,
                              gridspec_kw={"height_ratios": [2.0] + [1.0] * n})
    fig.patch.set_facecolor(BG)

    # ---- Top panel: SPX log scale ----
    ax_spx = axes[0]
    spx_clip = spx[spx.index >= start_date]
    ax_spx.plot(spx_clip.index, spx_clip.values, color=ACCENT, linewidth=1.4)
    ax_spx.set_yscale("log")
    ax_spx.set_ylabel("SPX (log)", color=ACCENT, fontsize=10)
    _style_ax(ax_spx)

    # Mark major flip events from each variable on the SPX panel for visual alignment
    flip_dates_release = set()
    flip_dates_tighten = set()
    for name, st in items:
        cfg = TREND_VARS.get(name, {})
        sm = apply_smoothing(st.series.dropna(), cfg.get("smoothing", "raw"))
        st_df = supertrend(sm, period=cfg.get("st_period", 5), mult=cfg.get("st_mult", 5.0))
        st_df = st_df[st_df.index >= start_date]
        flips = st_df[st_df["flip"]]
        for fd, row in flips.iterrows():
            is_release_flip = ((row["direction"] == 1 and st.higher_means_release) or
                                (row["direction"] == -1 and not st.higher_means_release))
            if is_release_flip:
                flip_dates_release.add(fd)
            else:
                flip_dates_tighten.add(fd)
    for fd in flip_dates_release:
        ax_spx.axvline(fd, color=BULL, alpha=0.15, linewidth=1.2)
    for fd in flip_dates_tighten:
        ax_spx.axvline(fd, color=BEAR, alpha=0.15, linewidth=1.2)

    ax_spx.set_title("Liquidity Trend Panel — macro variables vs. SPX (visual alignment)",
                      color=FG, fontsize=13, fontweight="bold", pad=12, loc="left")

    # ---- Variable panels ----
    for ax, (name, st) in zip(axes[1:], items):
        cfg = TREND_VARS.get(name, {})
        sm = apply_smoothing(st.series.dropna(), cfg.get("smoothing", "raw"))
        st_df = supertrend(sm, period=cfg.get("st_period", 5), mult=cfg.get("st_mult", 5.0))
        st_df = st_df[st_df.index >= start_date]
        if st_df.empty:
            continue

        # Shade direction regions
        for i in range(1, len(st_df)):
            d = st_df["direction"].iloc[i]
            if d == 0:
                continue
            is_release = (d == 1 and st.higher_means_release) or (d == -1 and not st.higher_means_release)
            color = BAND_BG_LOW if is_release else BAND_BG
            ax.axvspan(st_df.index[i - 1], st_df.index[i], color=color, zorder=0)

        ax.plot(st_df.index, st_df["value"], color=FG, linewidth=1.3)

        flips = st_df[st_df["flip"]]
        for flip_date, row in flips.iterrows():
            is_release_flip = ((row["direction"] == 1 and st.higher_means_release) or
                                (row["direction"] == -1 and not st.higher_means_release))
            marker_color = BULL if is_release_flip else BEAR
            ax.scatter([flip_date], [row["value"]], color=marker_color,
                        s=35, zorder=5, edgecolors=FG, linewidths=0.8)

        impl_color = BULL if st.liquidity_implication == "release" else BEAR if st.liquidity_implication == "tighten" else NEUTRAL
        age_str = f" · {st.months_since_flip:.0f}m" if st.months_since_flip and st.months_since_flip < 200 else ""
        label = f"{'↑' if st.direction == 1 else '↓' if st.direction == -1 else '—'} {st.liquidity_implication}{age_str}"
        ax.text(0.99, 0.5, label, transform=ax.transAxes,
                color=impl_color, fontsize=9, ha="right", va="center",
                fontweight="bold",
                bbox=dict(facecolor=BG, edgecolor=impl_color, alpha=0.85, pad=4))

        ax.set_ylabel(name, color=FG, fontsize=9)
        _style_ax(ax)

    axes[-1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.99, 0.005,
              f"Green vlines = liquidity-release flips  ·  Red vlines = tightening flips  ·  Updated {stamp}",
              ha="right", va="bottom", color=FG, fontsize=8, alpha=0.7)

    plt.tight_layout()
    fig.savefig(out_path, dpi=170, facecolor=BG)
    plt.close(fig)
    return out_path


def plot_predictive_signals(signals: dict, spx: pd.Series, out_path: Path) -> Path:
    """SPX + 5 validated leading signals with direction shading.

    Each signal's direction series is shaded (red=warning / green=setup) on
    its own panel. SPX top panel has historical peaks/troughs marked.
    """
    items = list(signals.items())
    n = len(items)
    if n == 0:
        return out_path

    fig, axes = plt.subplots(n + 1, 1, figsize=(12, 1.5 * (n + 1)), sharex=True,
                              gridspec_kw={"height_ratios": [2.0] + [1.0] * n})
    fig.patch.set_facecolor(BG)
    start_date = pd.Timestamp("2000-01-01")

    # Top panel: SPX
    ax_spx = axes[0]
    spx_clip = spx[spx.index >= start_date]
    ax_spx.plot(spx_clip.index, spx_clip.values, color=ACCENT, linewidth=1.4)
    ax_spx.set_yscale("log")
    ax_spx.set_ylabel("SPX (log)", color=ACCENT, fontsize=10)
    _style_ax(ax_spx)

    # Mark historical peaks/troughs on SPX
    for label, d in SPX_PEAKS_HIST.items():
        ax_spx.axvline(d, color=BEAR, alpha=0.5, linewidth=1.0, linestyle="--")
        ax_spx.text(d, ax_spx.get_ylim()[1] * 0.96, label.split("_")[1] if "_" in label else label,
                     color=BEAR, fontsize=7, ha="center", va="top", rotation=0, alpha=0.85)
    for label, d in SPX_TROUGHS_HIST.items():
        ax_spx.axvline(d, color=BULL, alpha=0.5, linewidth=1.0, linestyle="--")

    ax_spx.set_title("Predictive Leading Signals — validated 6-9 month lead time on SPX peaks/troughs",
                      color=FG, fontsize=13, fontweight="bold", pad=12, loc="left")

    # Signal panels
    for ax, (name, sig) in zip(axes[1:], items):
        # Plot underlying series
        s = sig.series.dropna()
        s = s[s.index >= start_date]
        if s.empty:
            continue
        ax.plot(s.index, s.values, color=FG, linewidth=1.1)

        # Direction shading
        d_series = sig.direction_series.dropna()
        d_series = d_series[d_series.index >= start_date]
        for i in range(1, len(d_series)):
            dval = d_series.iloc[i]
            if dval == +1:
                ax.axvspan(d_series.index[i - 1], d_series.index[i], color=BAND_BG, zorder=0)
            elif dval == -1:
                ax.axvspan(d_series.index[i - 1], d_series.index[i], color=BAND_BG_LOW, zorder=0)

        # Current state label
        if sig.current_direction == +1:
            color = BEAR
            label = f"⚠ WARNING · lead {sig.peak_avg_lead_m:+.0f}m"
        elif sig.current_direction == -1:
            color = BULL
            label = f"✓ SETUP · trough lead {sig.trough_avg_lead_m:+.0f}m"
        else:
            color = NEUTRAL
            label = "— neutral"
        ax.text(0.99, 0.5, label, transform=ax.transAxes,
                color=color, fontsize=9, ha="right", va="center",
                fontweight="bold",
                bbox=dict(facecolor=BG, edgecolor=color, alpha=0.85, pad=4))

        ax.set_ylabel(name.replace("_TREND", "").replace("_RS_6M", " RS6m").replace("_BLOWOFF", "_blow"),
                      color=FG, fontsize=8)
        _style_ax(ax)

    axes[-1].xaxis.set_major_locator(mdates.YearLocator(3))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.99, 0.005,
              f"Dashed red lines = historical SPX peaks  ·  Dashed green = troughs  ·  Updated {stamp}",
              ha="right", va="bottom", color=FG, fontsize=8, alpha=0.7)

    plt.tight_layout()
    fig.savefig(out_path, dpi=170, facecolor=BG)
    plt.close(fig)
    return out_path


def plot_drawdown_asymmetry(out_path: Path) -> Path:
    """Two-panel chart: probability of large drawdown by zone, and CVaR10."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    fig.patch.set_facecolor(BG)

    # Filter to LOW/MID/HIGH (skip FULL baseline reference)
    rows = [r for r in DRAWDOWN_STATS if r[0] != "FULL"]
    full = next(r for r in DRAWDOWN_STATS if r[0] == "FULL")

    labels = [r[0] for r in rows]
    p20 = [r[5] for r in rows]
    p30 = [r[6] for r in rows]

    # Left panel: probability of large drawdown
    x = np.arange(len(labels))
    width = 0.38
    bars1 = ax1.bar(x - width / 2, p20, width, color=BEAR, alpha=0.55, label="P(drawdown ≤ -20%)")
    bars2 = ax1.bar(x + width / 2, p30, width, color=BEAR, alpha=1.0, label="P(drawdown ≤ -30%)")

    ax1.axhline(full[5], color=FG, linestyle="--", linewidth=0.8, alpha=0.6,
                 label=f"Full-sample baseline (P≤-20% = {full[5]:.0f}%)")
    for bars in (bars1, bars2):
        for b in bars:
            h = b.get_height()
            ax1.text(b.get_x() + b.get_width() / 2, h + 1.5,
                      f"{h:.0f}%", ha="center", va="bottom",
                      color=FG, fontsize=9, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, color=FG)
    ax1.set_ylabel("Probability (%)", color=FG, fontsize=10)
    ax1.set_title("Probability of large drawdown in next 24 months",
                   color=FG, fontsize=11, fontweight="bold", pad=10, loc="left")
    leg = ax1.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, loc="upper left", fontsize=8)
    for txt in leg.get_texts():
        txt.set_color(FG)
    ax1.set_ylim(0, max(p30) + 20)
    _style_ax(ax1)

    # Right panel: CVaR10 — average of worst 10% fwd outcomes
    cvar = [r[7] for r in rows]
    colors = [BULL if c >= 0 else BEAR if c <= -20 else NEUTRAL for c in cvar]
    bars = ax2.bar(labels, cvar, color=colors, edgecolor=GRID)
    ax2.axhline(full[7], color=FG, linestyle="--", linewidth=0.8, alpha=0.6,
                 label=f"Full-sample CVaR10 = {full[7]:+.1f}%")
    ax2.axhline(0, color=FG, linewidth=0.6)
    for b, c in zip(bars, cvar):
        offset = 1.5 if c >= 0 else -1.5
        va = "bottom" if c >= 0 else "top"
        ax2.text(b.get_x() + b.get_width() / 2, c + offset,
                  f"{c:+.1f}%", ha="center", va=va, color=FG, fontsize=9, fontweight="bold")
    ax2.set_ylabel("Average return in worst-10% scenarios (%)", color=FG, fontsize=10)
    ax2.set_title("Tail-risk view (CVaR10) — what the worst 10% looked like",
                   color=FG, fontsize=11, fontweight="bold", pad=10, loc="left")
    leg = ax2.legend(facecolor=BG, edgecolor=GRID, labelcolor=FG, loc="upper right", fontsize=8)
    for txt in leg.get_texts():
        txt.set_color(FG)
    _style_ax(ax2)

    fig.suptitle("Composite cycle indicator — drawdown asymmetry by zone",
                  color=FG, fontsize=13, fontweight="bold", y=1.02)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fig.text(0.99, -0.02, f"Source: research/9_drawdown.py  ·  Updated {stamp}",
              ha="right", va="bottom", color=FG, fontsize=8, alpha=0.7)

    plt.tight_layout()
    fig.savefig(out_path, dpi=170, facecolor=BG, bbox_inches="tight")
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
