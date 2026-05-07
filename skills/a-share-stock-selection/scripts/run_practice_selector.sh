#!/bin/bash
set -euo pipefail

ROOT="/Users/zz/Documents/code/AI/openCli"
cd "$ROOT"

# Reuse the workspace candidate selector as a quick pre-filter,
# then explain the result with the tail-session rule table.
python3 scripts/select_a_share_candidates.py "$@"
