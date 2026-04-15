#!/usr/bin/env python3
"""GET /v3/page-column-cfg?page=0

中文说明：获取任务列表页面的列展示配置。
"""

import argparse

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dp58-system-api" / "scripts"))
from _dp58_opencli import add_common_args, call_api, main_error, print_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Get task-list page column config.")
    parser.add_argument("--page-code", default="0", help="Page code. Default: 0.")
    add_common_args(parser)
    args = parser.parse_args()
    data = call_api("GET", f"/v3/page-column-cfg?page={args.page_code}", no_open=args.no_open)
    print_json(data, compact=args.compact)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        main_error(error)
