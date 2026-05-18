# openCli

This repository currently contains two lines of work:

1. OpenCLI usage / automation notes.
2. A-share machine-learning and trading-practice experiments.

The current priority is the A-share workflow: daily K-line data, 5-trading-day direction/return modeling, market-risk correction, signal filtering, and a small-account trading discipline framework.

## Repository Layout

- `OpenCLI的AI使用说明.md` - Notes for AI agents using OpenCLI capabilities.
- `TODO清单.md` - Existing OpenCLI / dp58 automation todo list.
- `data/` - Input snapshots and the `10w炒股专项` trading-practice materials.
- `outputs/` - Raw or intermediate market-data outputs, including daily K-line directories.
- `scripts/` - Python scripts for fetching data, building samples, training models, corrections, and analysis.
- `skills/a-share-kline-return-modeling/` - Agent skill and outputs for A-share 5-day return/direction modeling.
- `skills/a-share-stock-selection/` - Agent skill and references for late-session A-share stock selection.

## Python Setup

Create a virtual environment, then install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The scripts expect Python 3 and use `numpy`, `pandas`, `scikit-learn`, and several A-share data packages.

## Main A-Share Workflows

### 1. Generate or inspect 5-day direction predictions

Single anchor date:

```bash
python3 scripts/train_5d_direction_model.py --as-of-date 2026-04-24 --feature-set core
```

Batch run:

```bash
python3 scripts/run_5d_direction_batch.py --start-date 2026-04-01 --end-date 2026-04-30 --feature-set core
```

Optional correction and signal layer:

```bash
python3 scripts/run_5d_direction_batch.py \
  --start-date 2026-04-01 \
  --end-date 2026-04-30 \
  --feature-set core \
  --run-correction \
  --run-signal
```

### 2. Train or run 5-day return model

```bash
python3 scripts/train_5d_return_model.py --as-of-date 2026-05-13
```

Rolling backtest:

```bash
python3 scripts/train_5d_return_model.py --rolling-backtest --anchor-end-date 2026-05-06
```

### 3. A-share late-session selection

The late-session stock-selection process is documented in:

```text
skills/a-share-stock-selection/SKILL.md
```

It is a stricter trading workflow for late-session overnight candidates and next-day sell plans. Treat it as a trading-discipline layer, not as a replacement for model validation.

## Current Data Notes

- `skills/a-share-kline-return-modeling/outputs/00_5日涨跌方向预测样本明细.csv` contains the current main modeling sample table.
- `skills/a-share-kline-return-modeling/outputs/00_5日方向模型特征表.csv` contains the current feature table.
- `outputs/daily_k_30_40_20260513/日K线目录/` contains the current daily K-line input directory used by default scripts.
- `data/a股快照_20260515.csv` appears incomplete compared with earlier snapshots and should be refreshed before being used for decision-making.

## Caution

This project is for research and trading-discipline support. Model outputs are probabilistic and can fail badly in regime shifts. Do not treat any prediction or candidate list as financial advice or a guaranteed signal.
