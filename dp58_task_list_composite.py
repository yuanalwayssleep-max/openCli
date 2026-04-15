#!/usr/bin/env python3
"""Composite script for querying dp.58corp.com task lists.

This root-level script combines:
- optional current-org switching
- current-user lookup
- POST /v2/task-info/get-list-page
- automatic org restoration

中文说明：复合查询星河任务列表，支持临时切换机构、查询任务、最后恢复原机构。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

SYSTEM_API_SCRIPTS = Path(__file__).resolve().parent / "skills" / "dp58-system-api" / "scripts"
sys.path.insert(0, str(SYSTEM_API_SCRIPTS))

# 优先复用系统接口 skill 的 OpenCLI 调用能力，根目录脚本只负责跨接口编排。
from _dp58_opencli import call_api, print_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query dp task list with optional org switching.")
    parser.add_argument("--owner-id", type=int, help="Owner user id. Defaults to current user id.")
    parser.add_argument("--org-id", type=int, help="Temporarily switch current org before querying.")
    parser.add_argument("--name", help="Task name keyword.")
    parser.add_argument("--page", type=int, default=1, help="Page number. Default: 1.")
    parser.add_argument("--size", type=int, default=10, help="Page size. Default: 10.")
    parser.add_argument("--has-sub-product", action="store_true", help="Include sub accounting units.")
    parser.add_argument("--no-open", action="store_true", help="Do not open task-list page first.")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    original_org_id = None
    if args.org_id is not None:
        current_user = call_api("GET", "/v2/user-info/get-current-user", no_open=args.no_open)
        original_org_id = current_user.get("data", {}).get("current_org_id")
        if original_org_id != args.org_id:
            # 查询指定机构前先切换 current_org_id；列表接口依赖当前机构上下文。
            call_api(
                "POST",
                "/api/user/auth/change-current-org",
                body={"org_id": args.org_id},
                no_open=True,
            )

    req = {"has_sub_product": args.has_sub_product}
    try:
        if args.owner_id is not None:
            req["owner_id"] = args.owner_id
        else:
            # 不传负责人时默认查询当前登录用户，避免在脚本里硬编码个人 ID。
            current_user = call_api("GET", "/v2/user-info/get-current-user", no_open=True)
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
    finally:
        if args.org_id is not None and original_org_id and original_org_id != args.org_id:
            # 无论查询成功或失败都切回原机构，避免污染浏览器里的工作上下文。
            call_api(
                "POST",
                "/api/user/auth/change-current-org",
                body={"org_id": original_org_id},
                no_open=True,
            )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
