---
name: a-share-stock-selection
description: Use this skill when the user wants to use 尾盘选股法 on A-share stocks, screen next-day candidates from the latest Eastmoney market snapshot, evaluate whether a stock is suitable for 隔夜短线, or produce buy, stop-loss, and next-day sell plans based on late-session price action.
---

# 尾盘选股法

这个 skill 只做一件事：

- 用 `A股尾盘选股法` 选股和解释选股结果

适用场景：

- 用户说“尾盘帮我选股”
- 用户说“找明天冲高卖的票”
- 用户说“按尾盘法筛 2-3 只”
- 用户说“这只票尾盘形态怎么样，明天有戏吗”

## 默认数据源

优先使用：

- `/Users/zz/Documents/code/AI/openCli/outputs/eastmoney_hs_bj_a_shares.csv`

如需刷新，使用：

- `/Users/zz/Documents/code/AI/openCli/scripts/fetch_eastmoney_a_shares.py`

## 标准流程

1. 先确认用户目标：
   - 只是尾盘筛票
   - 还是要给次日卖出计划
   - 还是要判断单只票能不能隔夜
2. 读取最新 A 股全市场快照。
3. 用 [references/tail-selection-rules.csv](references/tail-selection-rules.csv) 做规则判断。
4. 如果用户要批量候选，优先给：
   - 1-3 只核心票
   - 每只的入选理由
   - 风险提醒
   - 次日观察位 / 止损位 / 止盈位
5. 如果用户问单只票，优先回答：
   - 适不适合尾盘法
   - 明天偏强还是偏弱
   - 是否适合隔夜

## 输出要求

- 默认用中文，先说结论，再说依据。
- 区分三种内容：
  - `数据事实`
  - `规则判断`
  - `交易建议`
- 不要把尾盘法说成必胜方法，要明确这是 `概率筛选法`。
- 推荐候选时，默认偏好：
  - 主板
  - 流动性强
  - 振幅适中
  - 尾盘不跳水
  - 不过热

## 必看资源

- 规则总览： [references/rule-index.md](references/rule-index.md)
- 规则清单： [references/tail-selection-rules.csv](references/tail-selection-rules.csv)
- 输出模版： [references/output-template.md](references/output-template.md)
- 运行入口： [scripts/run_practice_selector.sh](scripts/run_practice_selector.sh)

