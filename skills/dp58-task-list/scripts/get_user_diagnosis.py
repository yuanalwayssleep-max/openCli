#!/usr/bin/env python3
"""GET /api/asset-govern/task/user-diagnosis

中文说明：获取当前用户任务治理诊断摘要。
"""

import argparse

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dp58-system-api" / "scripts"))
from _dp58_opencli import add_common_args, call_api, main_error, print_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Get task governance diagnosis summary.")
    add_common_args(parser)
    args = parser.parse_args()
    data = call_api("GET", "/api/asset-govern/task/user-diagnosis", no_open=args.no_open)
    print_json(data, compact=args.compact)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        main_error(error)
