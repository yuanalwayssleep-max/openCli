# 尾盘选股法资源索引

这个 skill 目前只保留一套规则：`尾盘选股法`

## 规则文件

- [tail-selection-rules.csv](tail-selection-rules.csv)

适合处理的问题：

- 尾盘能不能选这只
- 这只适不适合隔夜
- 次日有没有冲高卖预期
- 今天尾盘该不该进

## 数据文件

默认市场快照：

- `/Users/zz/Documents/code/AI/openCli/outputs/eastmoney_hs_bj_a_shares.csv`

市场刷新脚本：

- `/Users/zz/Documents/code/AI/openCli/scripts/fetch_eastmoney_a_shares.py`

## 批量筛票入口

- `/Users/zz/.codex/skills/a-share-stock-selection/scripts/run_practice_selector.sh`

说明：

- 这个脚本只是复用工作区现有的候选筛选器
- 如果用户明确要求“按尾盘法严格筛”，回答时必须仍以 `tail-selection-rules.csv` 为准做解释

