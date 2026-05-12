#!/bin/bash
set -euo pipefail

ROOT="/Users/zz/Documents/code/AI/openCli"
cd "$ROOT"

# Reuse the workspace selector: hard filters, 100-point score,
# industry/concept de-correlation, all qualified scores in one file.
# Final buy plans should read the first two rows from a_share_candidate_pool.csv.
python3 scripts/select_a_share_candidates.py "$@"
