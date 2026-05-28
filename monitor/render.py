"""Render the README with auto-updated tables and headline state.

Supports English and Chinese (zh-CN) variants. The auto-updated markers are
identical across both files; only the surrounding static prose differs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .signals import Signal
from .composite import CompositeState
from .trend import TrendState
from .predictive import PredictiveSignal


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


def composite_block_en(state: CompositeState) -> str:
    arrow = (
        "**↓ BOTTOM-LEANING**" if state.zone == "EXTREME_LOW" else
        "**↑ TOP-LEANING**" if state.zone == "EXTREME_HIGH" else
        "**~ MID**"
    )
    lines = [
        f"Composite value: `{state.current_value:+.3f}`  ·  "
        f"Composite percentile: `{state.current_percentile*100:.0f}%`  ·  "
        f"Zone: **{state.zone}** ({arrow})",
        "",
        f"_{state.zone_label}_",
        "",
        f"Built from {state.n_components} components: " + ", ".join(state.components_used) + ".",
    ]
    return "\n".join(lines)


def predictive_block_en(signals: dict, score: dict) -> str:
    regime_label = {
        "PEAK_WARNING": "**🔴 PEAK WARNING** — historical pre-peak pattern present",
        "TROUGH_SETUP": "**🟢 TROUGH SETUP / no peak warning** — leading signals constructive",
        "MIXED": "**⚪ MIXED** — no clear leading-signal pattern",
    }
    lines = [
        f"**Warning count: {score['warning_count']}/{score['n_total']} signals in warning direction**",
        "",
        regime_label.get(score["regime"], "—"),
        "",
        "| Signal | Direction | Peak detection | Peak lead | Trough detection | Trough lead |",
        "|---|:-:|:-:|:-:|:-:|:-:|",
    ]
    for name, s in signals.items():
        dir_str = "🔴 WARNING" if s.current_direction == 1 else "🟢 SETUP" if s.current_direction == -1 else "⚪ neutral"
        lines.append(
            f"| {s.short_name} | {dir_str} | "
            f"{s.peak_detection_rate} | {s.peak_avg_lead_m:+.1f}m | "
            f"{s.trough_detection_rate} | {s.trough_avg_lead_m:+.1f}m |"
        )
    return "\n".join(lines)


def predictive_block_zh(signals: dict, score: dict) -> str:
    regime_label = {
        "PEAK_WARNING": "**🔴 PEAK WARNING** — 历史 SPX 顶部前 leading 信号配置",
        "TROUGH_SETUP": "**🟢 TROUGH SETUP / 无 peak warning** — leading 信号偏多",
        "MIXED": "**⚪ 混合** — leading 信号没有清晰方向",
    }
    zh_name = {
        "YC_TREND": "收益率曲线趋势 (10Y−3M)",
        "NDX_RS_6M_TREND": "纳指 vs 标普 6月相对强度趋势",
        "SOX_RS_6M_TREND": "费城半导体 vs 标普 6月相对强度",
        "DXY_TREND": "DXY 6月变化趋势",
        "RUT_RS_BLOWOFF": "Russell 2000 blow-off 探测器",
    }
    lines = [
        f"**Warning 计数: {score['warning_count']}/{score['n_total']} 信号在警告方向**",
        "",
        regime_label.get(score["regime"], "—"),
        "",
        "| 信号 | 当前方向 | Peak 检测率 | Peak 提前量 | Trough 检测率 | Trough 提前量 |",
        "|---|:-:|:-:|:-:|:-:|:-:|",
    ]
    for name, s in signals.items():
        dir_str = "🔴 警告" if s.current_direction == 1 else "🟢 setup" if s.current_direction == -1 else "⚪ 中性"
        display_name = zh_name.get(name, s.short_name)
        lines.append(
            f"| {display_name} | {dir_str} | "
            f"{s.peak_detection_rate} | {s.peak_avg_lead_m:+.1f}m | "
            f"{s.trough_detection_rate} | {s.trough_avg_lead_m:+.1f}m |"
        )
    return "\n".join(lines)


def trend_block_en(states: dict, score: dict) -> str:
    direction_arrow = {1: "↑ UP", -1: "↓ DOWN", 0: "— flat"}
    impl_emoji = {"release": "🟢 RELEASE", "tighten": "🔴 TIGHTEN", "neutral": "⚪ neutral"}
    lines = []
    bias = (
        "**leans LIQUIDITY RELEASE**" if score["score"] >= 2 else
        "**leans LIQUIDITY TIGHTEN**" if score["score"] <= -2 else
        "**MIXED / no consensus**"
    )
    lines.append(f"**Liquidity flow score: `{score['score']:+d}/{score['n_total']}` — {bias}**")
    lines.append(f"  · {score['release_count']} variables in release direction, "
                  f"{score['tighten_count']} in tightening, {score['neutral_count']} neutral")
    lines.append("")
    lines.append("| Variable | Direction | Current | Last flip | Age | Implication |")
    lines.append("|---|:-:|---:|:-:|---:|:-:|")
    for name, s in states.items():
        dir_str = direction_arrow.get(s.direction, "—")
        flip_str = s.last_flip_date.strftime("%Y-%m") if s.last_flip_date is not None else "stable"
        age_str = f"{s.months_since_flip:.1f}m" if s.months_since_flip is not None else "—"
        impl_str = impl_emoji.get(s.liquidity_implication, "—")
        val_str = f"{s.current_value:.3f}" if abs(s.current_value) < 1000 else f"{s.current_value:,.0f}"
        lines.append(f"| {s.short_name} ({name}) | {dir_str} | {val_str} | {flip_str} | {age_str} | {impl_str} |")
    return "\n".join(lines)


def trend_block_zh(states: dict, score: dict) -> str:
    direction_arrow = {1: "↑ 上行", -1: "↓ 下行", 0: "— 持平"}
    impl_emoji = {"release": "🟢 放水", "tighten": "🔴 紧缩", "neutral": "⚪ 中性"}
    name_zh = {
        "WALCL": "美联储资产负债表",
        "NETLIQ": "Net Liquidity (Fed BS − TGA − RRP)",
        "M2_LEVEL": "M2 货币供应量",
        "DGS10": "10年期国债收益率",
        "DXY": "美元指数 DXY",
    }
    lines = []
    bias = (
        "**偏向流动性放水**" if score["score"] >= 2 else
        "**偏向流动性紧缩**" if score["score"] <= -2 else
        "**MIXED / 信号不明确**"
    )
    lines.append(f"**流动性流向分数: `{score['score']:+d}/{score['n_total']}` — {bias}**")
    lines.append(f"  · {score['release_count']} 个变量指向放水, "
                  f"{score['tighten_count']} 个紧缩, {score['neutral_count']} 中性")
    lines.append("")
    lines.append("| 变量 | 方向 | 当前值 | 上次拐点 | 趋势年龄 | 含义 |")
    lines.append("|---|:-:|---:|:-:|---:|:-:|")
    for name, s in states.items():
        dir_str = direction_arrow.get(s.direction, "—")
        flip_str = s.last_flip_date.strftime("%Y-%m") if s.last_flip_date is not None else "稳定"
        age_str = f"{s.months_since_flip:.1f}m" if s.months_since_flip is not None else "—"
        impl_str = impl_emoji.get(s.liquidity_implication, "—")
        val_str = f"{s.current_value:.3f}" if abs(s.current_value) < 1000 else f"{s.current_value:,.0f}"
        display_name = name_zh.get(name, s.short_name)
        lines.append(f"| {display_name} | {dir_str} | {val_str} | {flip_str} | {age_str} | {impl_str} |")
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


def composite_block_zh(state: CompositeState) -> str:
    arrow = (
        "**↓ 偏底部**" if state.zone == "EXTREME_LOW" else
        "**↑ 偏顶部**" if state.zone == "EXTREME_HIGH" else
        "**~ 中性**"
    )
    lines = [
        f"复合指标当前值: `{state.current_value:+.3f}`  ·  "
        f"复合指标百分位: `{state.current_percentile*100:.0f}%`  ·  "
        f"区间: **{state.zone}** ({arrow})",
        "",
        f"_{state.zone_label_zh}_",
        "",
        f"由 {state.n_components} 个组件构成：" + "、".join(state.components_used) + "。",
    ]
    return "\n".join(lines)


def stamp_text_zh(snap: dict) -> str:
    return f"_最后更新：**{snap['captured_utc']}**  ·  数据源：FRED · Yahoo Finance · FINRA_"


# --- Marker replacement --------------------------------------------------

def replace_marker(text: str, marker: str, new_content: str) -> str:
    pattern = rf"<!-- BEGIN:{marker} -->.*?<!-- END:{marker} -->"
    replacement = f"<!-- BEGIN:{marker} -->\n{new_content}\n<!-- END:{marker} -->"
    return re.sub(pattern, replacement, text, flags=re.DOTALL)


def render_readme(
    readme_path: Path,
    snap: dict,
    signals: dict[str, Signal],
    composite_state: CompositeState | None = None,
    trend_states: dict | None = None,
    trend_score: dict | None = None,
    pred_signals: dict | None = None,
    pred_score: dict | None = None,
    lang: str = "en",
) -> None:
    text = readme_path.read_text(encoding="utf-8")
    if lang == "zh":
        text = replace_marker(text, "STAMP", stamp_text_zh(snap))
        text = replace_marker(text, "HEADLINE", headline_zh(snap))
        text = replace_marker(text, "SIGNAL_TABLE", signal_table_zh(snap, signals))
        if composite_state is not None:
            text = replace_marker(text, "COMPOSITE", composite_block_zh(composite_state))
        if trend_states is not None and trend_score is not None:
            text = replace_marker(text, "TREND_PANEL", trend_block_zh(trend_states, trend_score))
        if pred_signals is not None and pred_score is not None:
            text = replace_marker(text, "PREDICTIVE", predictive_block_zh(pred_signals, pred_score))
    else:
        text = replace_marker(text, "STAMP", stamp_text_en(snap))
        text = replace_marker(text, "HEADLINE", headline_en(snap))
        text = replace_marker(text, "SIGNAL_TABLE", signal_table_en(snap, signals))
        if composite_state is not None:
            text = replace_marker(text, "COMPOSITE", composite_block_en(composite_state))
        if trend_states is not None and trend_score is not None:
            text = replace_marker(text, "TREND_PANEL", trend_block_en(trend_states, trend_score))
        if pred_signals is not None and pred_score is not None:
            text = replace_marker(text, "PREDICTIVE", predictive_block_en(pred_signals, pred_score))
    readme_path.write_text(text, encoding="utf-8")
