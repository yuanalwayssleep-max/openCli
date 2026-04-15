#!/usr/bin/env python3
"""POST /v2/task-info/get-list-page

中文说明：查询当前机构上下文下的任务列表，不负责切换机构。
"""

import argparse

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dp58-system-api" / "scripts"))
# 复用系统接口 skill 的 OpenCLI helper，避免在页面探查 skill 中复制公共能力。
from _dp58_opencli import add_common_args, call_api, main_error, print_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Query dp task list page.")
    parser.add_argument("--owner-id", type=int, help="Owner user id. Defaults to current user id.")
    parser.add_argument("--name", help="Task name keyword.")
    parser.add_argument("--page", type=int, default=1, help="Page number. Default: 1.")
    parser.add_argument("--size", type=int, default=10, help="Page size. Default: 10.")
    parser.add_argument("--has-sub-product", action="store_true", help="Include sub accounting units.")
    add_common_args(parser)
    args = parser.parse_args()

    req = {"has_sub_product": args.has_sub_product}
    if args.owner_id is not None:
        req["owner_id"] = args.owner_id
    else:
        # 默认使用当前登录用户作为负责人，脚本不硬编码个人 ID。
        current_user = call_api("GET", "/v2/user-info/get-current-user", no_open=args.no_open)
        user_id = current_user.get("data", {}).get("id")
        if user_id:
            req["owner_id"] = user_id
    if args.name:
        req["name"] = args.name

    body = {
        "page": {"current": args.page, "size": args.size, "orders": []},
        "req": req,
    }
    data = call_api("POST", "/v2/task-info/get-list-page", body=body, no_open=True)
    print_json(data, compact=args.compact)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        main_error(error)
