# A-share K-line Modeling Status

Last organized: 2026-05-16

## Current State

The module can run locally in the project `.venv`.

Verified smoke test:

```bash
.venv/bin/python scripts/train_5d_direction_model.py \
  --as-of-date 2026-04-24 \
  --feature-set core \
  --model-mode single \
  --model-iterations 10 \
  --output-suffix _smoke_20260516
```

Smoke result:

- training samples: 8294
- feature set: core
- feature count: 49
- predicted stocks: 228
- direction accuracy: 64.04%
- predicted up: 228
- predicted down: 0
- 80% target reached: no

This smoke test only proves the local pipeline runs. It should not be used as a strategy-quality result.

## Current Main Artifacts

- `00_5日涨跌方向预测样本明细.csv`
- `00_5日方向模型特征表.csv`
- `00_A股日K基础行情与5日后标签表.csv`
- `00_市场5日方向预测样本.csv`
- `00_核心指数日K.csv`
- `00_核心指数特征.csv`
- `00_股票清单.csv`

## Current Main Policies

- Feature set: `core` is the preferred baseline unless testing a specific experiment.
- Market-risk correction: `v15` is the currently documented stable correction layer.
- Research signal pool: `v17_confidence` is the broader low-coverage signal pool for analysis.
- Recommended candidate pool: `v18_confidence_topn --daily-max-signals 5` is the current default candidate-selection口径.
- Full-stock direction accuracy is not the final trading target; selective high-confidence signals are more important.

## April 2026 Validation Snapshot

Batch tested on `2026-04-01` to `2026-04-30`, feature set `core`, suffix `_formal_20260516_april`.

- Raw direction model: 4774 predictions, 62.82% accuracy.
- `v15` risk correction: 68.01% accuracy, +5.19 percentage points over raw.
- Denoised `v15` accuracy: 73.94%, +6.92 percentage points over denoised raw.
- `v16`: 0 signals; rules were too strict for this month.
- `v17_confidence`: 441 signals, 9.24% coverage, 85.49% signal accuracy.
- `v18_confidence_topn --daily-max-signals 5`: 78 signals, 1.63% coverage, 93.59% signal accuracy.
- `v18_confidence_topn --daily-max-signals 10`: 127 signals, 2.66% coverage, 89.76% signal accuracy.
- `v18_confidence_topn --daily-max-signals 20`: 185 signals, 3.88% coverage, 87.57% signal accuracy.

Current recommendation: use Top5 as the portfolio candidate pool and keep Top10 as an aggressive watchlist.

## Known Issues

1. `outputs/` contains many historical experiment CSVs in one flat directory.
2. Several scripts still assume files live directly under `skills/a-share-kline-return-modeling/outputs/`.
3. The current default daily K-line directory has about 236 files, so it is not a full-market daily K universe.
4. Some large generated outputs are tracked in Git; future output retention policy should be clarified.
5. Smoke outputs should stay archived and not be mixed with formal experiment outputs.

## Recommended Next Steps

1. Validate `v18_confidence_topn --daily-max-signals 5` on more months, especially weak/sideways months.
2. Add a comparison script for `v17_confidence`, `v18_top5`, `v18_top10`, and `v18_top20`.
3. Design the next portfolio layer: daily candidate ranking, max holdings, industry concentration, stop-loss, and 5-day exit rules.
4. Decide an output retention policy before running large new batches.
5. Keep `v16` as historical reference unless future tests justify restoring it.
