#!/usr/bin/env python3
"""POST /api/user/auth/change-current-org

中文说明：切换星河当前机构上下文，供后续系统接口按指定机构查询。
"""

import argparse

from _dp58_opencli import add_common_args, call_api, main_error, print_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Change current dp org context.")
    parser.add_argument("--org-id", required=True, type=int, help="Target org id, for example 33 or 1095.")
    add_common_args(parser)
    args = parser.parse_args()
    # 机构切换会影响当前浏览器会话，调用方需要自行决定是否切回原机构。
    data = call_api(
        "POST",
        "/api/user/auth/change-current-org",
        body={"org_id": args.org_id},
        no_open=args.no_open,
    )
    print_json(data, compact=args.compact)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        main_error(error)
