[English](README.md) · **中文**

# 宏观体制监测仪 (Macro Regime Monitor)

> 追踪一组精选的流动性、估值、市场内部信号相对其历史极端区间的位置。每日通过 GitHub Actions 更新。**不是交易策略，是一份关于"我们现在在哪"的描述性视图。**

<!-- BEGIN:STAMP -->
_最后更新：**2026-05-28 05:41 UTC**  ·  数据源：FRED · Yahoo Finance · FINRA_
<!-- END:STAMP -->

## 当前状态

<!-- BEGIN:HEADLINE -->
**当前触发信号的历史 12 月 SPX 净影响：`-4.2pp` — 偏空。**

- Tier 1（持久型）触发数：**空 1 个，多 0 个**
- Tier 2（多数同向）触发数：**空 0 个，多 2 个**
<!-- END:HEADLINE -->

![信号百分位与极端区间](charts/overview.png)

## 复合周期指标

将通过验证的几个信号加权组合而成，作为中期（波段）辅助判断工具——告诉你"现在在宏观周期相对哪个位置"。复合指标自身历史的 top/bottom decile（前 10% / 后 10%）在历史上对未来 12 个月 SPX 收益分布有统计上显著的偏移；中间区域则诚实地承认信号不明确。

<!-- BEGIN:COMPOSITE -->
复合指标当前值: `-0.001`  ·  复合指标百分位: `38%`  ·  区间: **MID** (**~ 中性**)

_中性区（信号不明确）_

由 4 个组件构成：MARGIN_M2、NDX_SPX_RS、SOX_SPX_RS、RUT_SPX_RS。
<!-- END:COMPOSITE -->

![复合周期指标历史](charts/composite.png)

复合指标各 decile 历史 12 月前瞻 SPX 收益——两个极端 decile 都通过了 bootstrap p<0.001 显著性：

![复合指标 decile 历史前瞻收益](charts/composite_deciles.png)

| 复合指标 decile | N | 12月 fwd SPX 均值 | 胜率 | vs 全样本 |
|---|---:|---:|---:|---:|
| **0-10%（极低 / 底部 setup）** | 14 | **+31.6%** | **100%** | **+22.0pp** |
| 10-30%（偏低） | 52 | +17.3% | 85% | +7.6pp |
| 30-50%（中偏低） | 71 | +10.0% | 83% | +0.3pp |
| 50-70%（中偏高） | 85 | +10.4% | 84% | +0.7pp |
| 70-90%（偏高） | 109 | +6.7% | 73% | -2.9pp |
| **90-100%（极高 / 顶部警告）** | 24 | **-10.1%** | **29%** | **-19.7pp** |

如何使用复合指标：
- **中间区间（30-70%）当作不明确**。不要根据 50 分位的读数下单。
- **极低区（≤10%）历史上是强底部 setup 信号**——N=14 样本不大，但**每一次都被正 12 月收益所跟随**。
- **极高区（≥90%）历史上是顶部警告信号**——胜率 29%，平均前瞻收益 −10%。
- 这是**辅助判断**，不是交易触发器。用它来调整 discretionary 仓位，而不是凭单次读数翻转方向。

## 信号表

<!-- BEGIN:SIGNAL_TABLE -->
| 信号 | 当前值 | 百分位 | 区间 | 等级 | 影响（12月前瞻 SPX） |
|---|---:|---:|:-:|:-:|---:|
| 保证金债务 / M2 | 0.057 | 99% | 高 [偏空] | DURABLE | -13.2pp |
| 纳指 vs 标普 3月相对强度 | 9.843 | 92% | 高 [偏多] | MOSTLY | +4.8pp |
| 费城半导体 vs 标普 3月相对强度 | 43.470 | 99% | 高 [偏多] | MOSTLY | +4.2pp |
| 总市值 / M2（巴菲特指标变体） | 3.160 | 100% | 高 [偏空] | TOMBSTONE | *未通过稳定性测试* |
| Russell 2000 vs SPX 3m RS | 1.463 | 64% | 中 [中性] | — | — |
| 10Y Treasury 3m change | 36.245 | 80% | 中 [中性] | — | — |
<!-- END:SIGNAL_TABLE -->

区间标记表示该信号在该区间时的历史偏向——不是买卖建议。每个信号的局限性和审计追踪见 `research/findings.md`。

## 历史条件影响

每个信号处于其历史前/后 20% 区间时，12 月前瞻 SPX 收益分布相对全样本基线的偏移。当前正触发的区间用白色边框高亮。

![历史条件影响](charts/conditional_returns.png)

## 我们做了什么

本仓库是一个完整研究项目的生产层，研究文档见 `research/findings.md`。研究流程对 14 个信号-区间组合进行了 decade-stratified 子样本检验，配合 bootstrap permutation 显著性测试。只有通过 stability test 的信号才进入 dashboard。

**通过稳定性测试的信号**：

- **MARGIN_M2 HIGH**（保证金债务/M2 处于前 20%）——*DURABLE* 跨 3 个 decade 一致。历史上，杠杆达到此区间预示 12 月 SPX 收益 −13pp。
- **MARGIN_M2 LOW**（保证金债务/M2 处于后 20%）——*MOSTLY directional*（2 个 decade）。去杠杆完毕预示 +8pp。
- **NDX_SPX_RS HIGH**（纳指相对标普 3 月强度处于前 20%）——*MOSTLY directional*（2 个 decade）。科技股领涨延展预示 +5pp。
- **SOX_SPX_RS HIGH**（半导体相对标普 3 月强度处于前 20%）——*MOSTLY directional*（3 个 decade）。半导体领涨预示 +4pp。
- **SOX_SPX_RS LOW**（半导体相对标普走弱）——*MOSTLY directional*（2 个 decade）。半导体崩盘预示 −5.5pp。

**经过测试但被淘汰的信号（保留在文档中以保持透明度）**：

- **MCAP_M2 HIGH**（"巴菲特指标处于极端"）——*未通过稳定性测试*。这个流行的叙事只在 2000s dot-com 时代真实有效。在 1990s 和 2020s 同样的极端读数几乎没有前瞻收益效应。表格中作为 tombstone 保留。
- **NDX_SPX_RS LOW**（"纳指走弱 = 警告"）——*regime-dependent*。在 2000s 有效。在 1990s 无效。只在 post-dot-com regime 内成立。
- **M2_GROWTH LOW**——信号 sign 在 1990s 和 2010s 之间翻转。不可应用。
- **NET_LIQUIDITY**——数据不足。post-2003 只有一个完整 pre-COVID decade 可用。

## 方法论

- 月度分辨率。信号使用 expanding-window percentile（无未来数据偏差）。
- 极端区间定义：quintile 阈值（历史观测的前 20% / 后 20%）。
- 前瞻收益期限：12 个月。条件均值对全样本 baseline 进行假设检验。
- 统计检验：双侧 permutation test，2000 次迭代，对"区间无效应"的零假设计算 p-value。
- Stability 要求：3+ 个 decade 同号且效应 >2pp = DURABLE；2 个 decade = MOSTLY；混合 = REGIME-DEPENDENT（排除）；单 decade = INSUFFICIENT。
- 更新频率：每日 22:00 UTC 通过 GitHub Actions。

## 数据源

- [FRED M2SL](https://fred.stlouisfed.org/series/M2SL) — 美国 M2 货币供应量（月度）。
- [FINRA Customer Margin Balances](https://www.finra.org/rules-guidance/key-topics/margin-accounts) — 保证金借记余额（月度）。
- [Yahoo Finance](https://finance.yahoo.com/) — SPX, NDX, SOX, Wilshire 5000（日度）。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python update.py
```

图表生成在 `charts/`，快照在 `data/latest.json`，README 自动原地更新。

## 这是什么 / 这不是什么

**是**：一份描述性快照，呈现当前宏观与市场内部读数在其历史分布中的位置，以及历史上当每个信号处于相同区间时通常发生了什么。对哪些信号通过 stability test、哪些没通过都保持透明。

**不是**：一个交易策略。研究阶段明确拒绝了"策略作为交付物"的框架——理由见 `research/findings.md`。把这个作为离散判断的一个输入，而不是买/卖触发器。

## 相关项目

- [awesome-macro-liquidity](https://github.com/ruleaker/awesome-macro-liquidity) — 宏观流动性追踪资源清单。
- [awesome-derivatives-data](https://github.com/ruleaker/awesome-derivatives-data) — 加密衍生品数据资源清单。
- [net-liquidity-dashboard](https://github.com/ruleaker/net-liquidity-dashboard) — 每日 Net Liquidity 追踪（更宏观的视角）。

## License

[MIT](LICENSE)
