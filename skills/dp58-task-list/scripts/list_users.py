#!/usr/bin/env python3
"""GET /v2/user-info/list?size=<size>

中文说明：获取负责人或用户候选列表，可按关键词在本地过滤。
"""

import argparse
import json

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dp58-system-api" / "scripts"))
from _dp58_opencli import add_common_args, call_api, main_error, print_json


def main() -> None:
    parser = argparse.ArgumentParser(description="List user candidates.")
    parser.add_argument("--size", type=int, default=20, help="Candidate count. Default: 20.")
    parser.add_argument("--keyword", help="Filter by chinese_name, oa_name, or raw user record text.")
    add_common_args(parser)
    args = parser.parse_args()
    data = call_api("GET", f"/v2/user-info/list?size={args.size}", no_open=args.no_open)
    if args.keyword and isinstance(data.get("data"), list):
        # 接口本身不按关键词过滤，这里保留响应外壳，只过滤 data 列表方便查负责人 ID。
        keyword = args.keyword
        data["data"] = [
            item
            for item in data["data"]
            if keyword in item.get("chinese_name", "")
            or keyword in item.get("oa_name", "")
            or keyword in json.dumps(item, ensure_ascii=False)
        ]
    print_json(data, compact=args.compact)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        main_error(error)
