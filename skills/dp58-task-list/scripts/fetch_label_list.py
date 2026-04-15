#!/usr/bin/env python3
"""GET /v2/task-info/fetch-label-list?orgId=<org_id>

中文说明：获取指定机构下的全部任务标签候选。
"""

import argparse

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dp58-system-api" / "scripts"))
from _dp58_opencli import add_common_args, call_api, main_error, print_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch task labels.")
    parser.add_argument("--org-id", required=True, help="Org id, for example 33.")
    add_common_args(parser)
    args = parser.parse_args()
    data = call_api("GET", f"/v2/task-info/fetch-label-list?orgId={args.org_id}", no_open=args.no_open)
    print_json(data, compact=args.compact)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        main_error(error)
