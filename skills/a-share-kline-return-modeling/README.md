# A-share K-line Return Modeling

This module builds and evaluates A-share daily K-line models for 5-trading-day direction and return prediction.

The current goal is not to predict every stock perfectly. The practical goal is to maintain a reproducible pipeline that can:

- build historically valid samples without future leakage
- generate per-stock 5-day direction / return predictions
- evaluate daily and market-regime accuracy
- apply market-risk correction rules
- filter low-coverage, higher-confidence trading signals

## Scope

This module focuses on daily K-line modeling and signal research. Portfolio construction, position sizing, and execution discipline should be handled as a later layer.

## Main Inputs

- `outputs/daily_k_30_40_20260513/日K线目录/` - default daily K-line input directory used by current scripts.
- `outputs/daily_k_30_40_20260513/symbols_30_40_20260513_剔除创业板科创.csv` - default stock metadata file.
- `skills/a-share-kline-return-modeling/outputs/00_5日涨跌方向预测样本明细.csv` - main direction sample table.
- `skills/a-share-kline-return-modeling/outputs/00_5日方向模型特征表.csv` - main feature table.
- `skills/a-share-kline-return-modeling/outputs/00_A股日K基础行情与5日后标签表.csv` - base daily K-line table with 5-day labels.

## Main Scripts

Run from the repository root.

Single-date direction prediction:

```bash
.venv/bin/python scripts/train_5d_direction_model.py --as-of-date 2026-04-24 --feature-set core
```

Batch direction prediction:

```bash
.venv/bin/python scripts/run_5d_direction_batch.py --start-date 2026-04-01 --end-date 2026-04-30 --feature-set core
```

Batch prediction with risk correction and signal layer:

```bash
.venv/bin/python scripts/run_5d_direction_batch.py \
  --start-date 2026-04-01 \
  --end-date 2026-04-30 \
  --feature-set core \
  --run-correction \
  --run-signal
```

Single-date return prediction:

```bash
.venv/bin/python scripts/train_5d_return_model.py --as-of-date 2026-05-13
```

Rolling return backtest:

```bash
.venv/bin/python scripts/train_5d_return_model.py --rolling-backtest --anchor-end-date 2026-05-06
```

Generate the current recommended daily candidate pool from a corrected detail file:

```bash
.venv/bin/python scripts/apply_signal_decision_layer.py \
  --detail-csv skills/a-share-kline-return-modeling/outputs/10_个股预测结果_市场风险修正_<suffix>_<start>_<end>.csv \
  --output-prefix skills/a-share-kline-return-modeling/outputs/18_<suffix>_confidence_top5 \
  --decision-policy v18_confidence_topn \
  --daily-max-signals 5
```

Use `v17_confidence` when you want a broader research signal pool instead of a daily Top5 candidate list.

## Current Modeling Direction

Current notes in `SKILL.md` indicate the project has moved from full-stock direction accuracy toward low-coverage higher-confidence signals:

- full-stock prediction remains the scoring base
- market environment and risk tags explain when the stock model fails
- `v15` market-risk correction aims to reduce unstable direction mistakes
- `v17_confidence` is the broader research signal pool
- `v18_confidence_topn --daily-max-signals 5` is the current recommended daily candidate-pool口径

## Output Files

Output naming is documented in `references/output-file-guide.md`.

Do not treat all files in `outputs/` as equal. The `00_` files are core inputs, while many numbered files are historical experiments. Before using an output for decisions, check its suffix, date range, feature set, and correction policy.

## Practical Caution

This module supports research and disciplined decision-making only. A model hit rate is not a trading system by itself. Always separate:

- prediction accuracy
- signal coverage
- expected return
- drawdown / risk control
- portfolio concentration
