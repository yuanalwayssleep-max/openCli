#!/usr/bin/env python3
"""GET /api/org-manage/org/get-user-org-list

中文说明：获取当前用户可访问的机构列表。
"""

import argparse

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dp58-system-api" / "scripts"))
from _dp58_opencli import add_common_args, call_api, main_error, print_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Get current user's org list.")
    add_common_args(parser)
    args = parser.parse_args()
    data = call_api("GET", "/api/org-manage/org/get-user-org-list", no_open=args.no_open)
    print_json(data, compact=args.compact)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        main_error(error)
