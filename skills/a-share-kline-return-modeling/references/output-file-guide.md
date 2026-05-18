# Output File Guide

The current output directory is intentionally left flat for compatibility with existing scripts. Use filename prefixes to understand file roles.

## Prefixes

- `00_` - Core input tables and sample/feature bases.
- `03_` - Per-stock direction prediction results for anchor dates.
- `04_` - Daily direction accuracy statistics paired with `03_` outputs.
- `06_` - Market direction model or related baseline outputs.
- `07_` - Market-state signal evaluation outputs.
- `08_` - Adaptive threshold or correction-rule evaluation outputs.
- `09_` - Stock prediction results joined with market environment tags and grouped statistics.
- `10_` - Market-risk-corrected stock prediction results and correction comparisons.
- `11_` - Cleaned samples, feature tables, or data-quality labels.
- `12_` - Cross-year or stability analysis outputs.
- `13_` - Additional correction audit / policy experiment outputs.
- `14_` - Signal decision layer outputs, currently associated with `v16` style low-coverage signals.
- `15_` - Later signal or policy experiment outputs.
- `16_` - Later signal or policy experiment outputs.
- `17_` - Daily quota / portfolio-candidate style signal outputs.

## Recommended Reading Order

For a date range experiment, inspect files in this order:

1. `03_...csv` - raw per-stock predictions.
2. `04_...csv` - daily accuracy summary.
3. `10_...csv` - market-risk correction result, if correction was run.
4. `14_...csv` or later signal files - actual low-coverage signal layer.
5. Grouped/statistical summaries for market environment or risk tags.

## Temporary Outputs

Smoke-test files should include `smoke` in the filename and be moved to:

```text
outputs/archive/smoke_YYYYMMDD/
```

Do not use smoke files as model-quality evidence.

## Current Compatibility Rule

Do not move existing formal CSV files out of `outputs/` until scripts are updated to accept subdirectories. Many scripts use hardcoded or default paths that point directly to this flat directory.
