"""Render the README with auto-updated tables and headline state.

Supports English and Chinese (zh-CN) variants. The auto-updated markers are
identical across both files; only the surrounding static prose differs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .signals import Signal


def _pp(x: float, dp: int = 1) -> str:
    return "n/a" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:+.{dp}f}pp"


def _zone_emoji(zone: str, higher_is_riskier: bool) -> str:
    if zone == "HIGH":
        return "[BEAR]" if higher_is_riskier else "[BULL]"
    if zone == "LOW":
        return "[BULL]" if higher_is_riskier else "[BEAR]"
    return "[mid]"


# --- English copy --------------------------------------------------------

def headline_en(snap: dict) -> str:
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
    return "\n".join([
        f"**Net 12-month historical effect from currently-triggered signals: `{_pp(net)}` — {lean}.**",
        "",
        f"- Durable (Tier 1) signals triggered: **{n_dur_bear} bearish, {n_dur_bull} bullish**",
        f"- Mostly-directional (Tier 2) signals triggered: **{n_mostly_bear} bearish, {n_mostly_bull} bullish**",
    ])


def signal_table_en(snap: dict, signals: dict[str, Signal]) -> str:
    lines = [
        "| Signal | Current value | Percentile | Zone | Tier | Effect (12m fwd SPX) |",
        "|---|---:|---:|:-:|:-:|---:|",
    ]
    def sort_key(r: dict) -> tuple:
        tier_rank = {"DURABLE": 0, "MOSTLY": 1, "REGIME-DEP": 2, "TOMBSTONE": 3, "—": 4}.get(r["tier"], 5)
        return (tier_rank, -abs(r["effect_pp"] or 0))
    for r in sorted(snap["rows"], key=sort_key):
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


def stamp_text_en(snap: dict) -> str:
    return f"_Last updated: **{snap['captured_utc']}**  ·  Data: FRED · Yahoo Finance · FINRA_"


# --- Chinese copy --------------------------------------------------------

# Map English short_name to Chinese description for the table
ZH_SHORT_NAME = {
    "Margin debt / M2": "保证金债务 / M2",
    "NDX vs SPX 3m RS": "纳指 vs 标普 3月相对强度",
    "SOX vs SPX 3m RS": "费城半导体 vs 标普 3月相对强度",
    "Market cap / M2 (Buffett indicator variant)": "总市值 / M2（巴菲特指标变体）",
}


def _zone_zh(zone: str) -> str:
    return {"HIGH": "高", "LOW": "低", "MID": "中", "n/a": "n/a"}.get(zone, zone)


def _zone_marker_zh(zone: str, higher_is_riskier: bool) -> str:
    if zone == "HIGH":
        return "[偏空]" if higher_is_riskier else "[偏多]"
    if zone == "LOW":
        return "[偏多]" if higher_is_riskier else "[偏空]"
    return "[中性]"


def headline_zh(snap: dict) -> str:
    net = snap["net_effect_pp"]
    n_dur_bear = len(snap["triggered_durable_bear"])
    n_dur_bull = len(snap["triggered_durable_bull"])
    n_mostly_bear = len(snap["triggered_mostly_bear"])
    n_mostly_bull = len(snap["triggered_mostly_bull"])
    lean = (
        "偏空" if net <= -3 else
        "偏多" if net >= 3 else
        "近似中性"
    )
    return "\n".join([
        f"**当前触发信号的历史 12 月 SPX 净影响：`{_pp(net)}` — {lean}。**",
        "",
        f"- Tier 1（持久型）触发数：**空 {n_dur_bear} 个，多 {n_dur_bull} 个**",
        f"- Tier 2（多数同向）触发数：**空 {n_mostly_bear} 个，多 {n_mostly_bull} 个**",
    ])


def signal_table_zh(snap: dict, signals: dict[str, Signal]) -> str:
    lines = [
        "| 信号 | 当前值 | 百分位 | 区间 | 等级 | 影响（12月前瞻 SPX） |",
        "|---|---:|---:|:-:|:-:|---:|",
    ]
    def sort_key(r: dict) -> tuple:
        tier_rank = {"DURABLE": 0, "MOSTLY": 1, "REGIME-DEP": 2, "TOMBSTONE": 3, "—": 4}.get(r["tier"], 5)
        return (tier_rank, -abs(r["effect_pp"] or 0))
    for r in sorted(snap["rows"], key=sort_key):
        sig = signals[r["name"]]
        zone_str = _zone_zh(r["zone"])
        zone_marker = _zone_marker_zh(r["zone"], sig.higher_is_riskier)
        effect = "—" if r["effect_pp"] is None else _pp(r["effect_pp"])
        if r["tier"] == "TOMBSTONE":
            effect = "*未通过稳定性测试*"
        tier_display = r["tier"] if r["tier"] != "—" else "—"
        pct_display = "n/a" if pd.isna(r["current_percentile"]) else f"{r['current_percentile']*100:.0f}%"
        val_display = f"{r['current_value']:.3f}"
        zh_name = ZH_SHORT_NAME.get(sig.short_name, sig.short_name)
        lines.append(
            f"| {zh_name} | {val_display} | {pct_display} | "
            f"{zone_str} {zone_marker} | {tier_display} | {effect} |"
        )
    return "\n".join(lines)


def stamp_text_zh(snap: dict) -> str:
    return f"_最后更新：**{snap['captured_utc']}**  ·  数据源：FRED · Yahoo Finance · FINRA_"


# --- Marker replacement --------------------------------------------------

def replace_marker(text: str, marker: str, new_content: str) -> str:
    pattern = rf"<!-- BEGIN:{marker} -->.*?<!-- END:{marker} -->"
    replacement = f"<!-- BEGIN:{marker} -->\n{new_content}\n<!-- END:{marker} -->"
    return re.sub(pattern, replacement, text, flags=re.DOTALL)


def render_readme(readme_path: Path, snap: dict, signals: dict[str, Signal], lang: str = "en") -> None:
    text = readme_path.read_text(encoding="utf-8")
    if lang == "zh":
        text = replace_marker(text, "STAMP", stamp_text_zh(snap))
        text = replace_marker(text, "HEADLINE", headline_zh(snap))
        text = replace_marker(text, "SIGNAL_TABLE", signal_table_zh(snap, signals))
    else:
        text = replace_marker(text, "STAMP", stamp_text_en(snap))
        text = replace_marker(text, "HEADLINE", headline_en(snap))
        text = replace_marker(text, "SIGNAL_TABLE", signal_table_en(snap, signals))
    readme_path.write_text(text, encoding="utf-8")
