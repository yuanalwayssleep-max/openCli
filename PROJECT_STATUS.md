# PROJECT_STATUS

Last organized: 2026-05-16

## Current Priority

Build a reproducible A-share machine-learning workflow for:

- 5-trading-day direction prediction
- 5-trading-day return prediction
- market environment / risk correction
- low-coverage high-confidence signal filtering
- eventual personal portfolio construction and disciplined execution

## What Already Exists

- Core scripts for sample construction, model training, batch prediction, market-risk correction, and signal decisions in `scripts/`.
- A-share modeling skill documentation in `skills/a-share-kline-return-modeling/SKILL.md`.
- Late-session stock-selection and next-day selling rules in `skills/a-share-stock-selection/SKILL.md`.
- Existing model sample and feature tables under `skills/a-share-kline-return-modeling/outputs/`.
- A 10w trading-practice framework under `data/10w炒股专项/`.

## Current Local Audit

Observed on 2026-05-16:

- Repository clone path: `/Users/cocoon/.openclaw/workspace/openCli`
- Approx repository size: `760M`
- Approx modeling output size: `646M`
- Main sample table: `56457` rows, `77` columns
- Main feature table: `56457` rows, `67` columns
- Base K-line label table: `56457` rows, `21` columns
- Daily K-line directory currently has about `236` files, so it is not a full-market daily K universe.
- Python dependencies were not installed in the active environment during audit.

## Known Issues

1. No root-level `README.md` existed before this cleanup.
2. No dependency manifest existed before this cleanup.
3. `data/a股快照_20260515.csv` has only about `228` rows, while earlier snapshots have about `5500+` rows. Treat it as incomplete until refreshed.
4. Some documentation still focuses on OpenCLI / dp58 automation and does not reflect the current A-share priority.
5. Large generated CSV outputs are tracked in the repository; consider whether future generated outputs should be archived separately or ignored.

## Recommended Next Steps

1. Create a virtual environment and install `requirements.txt`.
2. Run a small smoke test on one historical anchor date, for example:

```bash
python3 scripts/train_5d_direction_model.py --as-of-date 2026-04-24 --feature-set core
```

3. If the smoke test passes, run a tiny batch window with correction and signal layers.
4. Refresh or replace incomplete `20260515` snapshot data before using recent snapshots for any trading decision.
5. Decide whether the project root should focus on A-share modeling, OpenCLI automation, or split into clearer subprojects.
