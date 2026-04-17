#!/usr/bin/env python3
"""Download dp58 tasks owned by Zhuangyuan via direct Python requests.

This script uses a full cookie jar (including HttpOnly cookies) to call:
- GET  /v2/user-info/get-current-user
- GET  /api/org-manage/org/get-user-org-list
- POST /api/user/auth/change-current-org
- POST /v2/task-info/get-list-page

It is intentionally browser-independent at runtime. The only requirement is
that a valid cookie jar has been exported beforehand.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


BASE_URL = "https://dp.58corp.com"
TASK_LIST_PAGE_URL = f"{BASE_URL}/data-develop/task-list"
DEFAULT_COOKIES_JSON = "configs/dp58.cookies.local.json"
DEFAULT_OUTPUT_JSON = "outputs/dp58_zhuangyuan_tasks_all_orgs.json"
DEFAULT_OUTPUT_CSV = "outputs/dp58_zhuangyuan_tasks_all_orgs.csv"
DEFAULT_SUMMARY_JSON = "outputs/dp58_zhuangyuan_tasks_all_orgs_summary.json"
DEFAULT_OWNER_ID = 49926
DEFAULT_OWNER_NAME = "庄园"
DEFAULT_PAGE_SIZE = 5000
DEFAULT_TIMEOUT = 20


class Dp58Error(RuntimeError):
    """Base error for dp58 request failures."""


class AuthError(Dp58Error):
    """Raised when the cookie jar cannot authenticate against dp58."""


@dataclass
class Org:
    org_id: int
    org_name: str
    is_current: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download dp58 tasks owned by Zhuangyuan.")
    parser.add_argument(
        "--cookies-json",
        default=DEFAULT_COOKIES_JSON,
        help=f"Cookie jar JSON file. Default: {DEFAULT_COOKIES_JSON}",
    )
    parser.add_argument(
        "--owner-id",
        type=int,
        default=DEFAULT_OWNER_ID,
        help=f"Owner id to query. Default: {DEFAULT_OWNER_ID}",
    )
    parser.add_argument(
        "--owner-name",
        default=DEFAULT_OWNER_NAME,
        help=f"Owner display name for summary only. Default: {DEFAULT_OWNER_NAME}",
    )
    parser.add_argument(
        "--org-id",
        type=int,
        action="append",
        dest="org_ids",
        help="Restrict export to one or more org ids. Can be repeated.",
    )
    parser.add_argument("--name", help="Optional task name keyword filter.")
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Number of records requested per page, not a total export cap. Default: {DEFAULT_PAGE_SIZE}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional debug cap across all orgs. Default 0 means export everything.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds. Default: {DEFAULT_TIMEOUT}",
    )
    parser.add_argument(
        "--output-json",
        default=DEFAULT_OUTPUT_JSON,
        help=f"Where to write the raw JSON tasks. Default: {DEFAULT_OUTPUT_JSON}",
    )
    parser.add_argument(
        "--output-csv",
        default=DEFAULT_OUTPUT_CSV,
        help=f"Where to write a flattened CSV export. Default: {DEFAULT_OUTPUT_CSV}",
    )
    parser.add_argument(
        "--summary-json",
        default=DEFAULT_SUMMARY_JSON,
        help=f"Where to write summary metadata. Default: {DEFAULT_SUMMARY_JSON}",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Indent for JSON outputs. Use 0 for compact JSON.",
    )
    return parser.parse_args()


def load_cookie_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Cookie file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        cookies = payload.get("cookies", [])
    elif isinstance(payload, list):
        cookies = payload
    else:
        raise Dp58Error("Cookie JSON must be a list or an object with a 'cookies' field.")

    if not isinstance(cookies, list) or not cookies:
        raise Dp58Error("Cookie JSON does not contain any cookies.")
    return cookies


def build_session(cookie_entries: Iterable[dict[str, Any]]) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Origin": BASE_URL,
            "Referer": TASK_LIST_PAGE_URL,
        }
    )

    for cookie in cookie_entries:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue

        kwargs: dict[str, Any] = {}
        if cookie.get("domain"):
            kwargs["domain"] = cookie["domain"]
        if cookie.get("path"):
            kwargs["path"] = cookie["path"]
        if "secure" in cookie:
            kwargs["secure"] = bool(cookie["secure"])
        if cookie.get("expires") is not None:
            kwargs["expires"] = cookie["expires"]
        session.cookies.set(name, str(value), **kwargs)

    return session


def request_json(
    session: requests.Session,
    method: str,
    path: str,
    *,
    timeout: int,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = path if path.startswith("http") else f"{BASE_URL}{path}"
    response = session.request(method=method, url=url, json=body, timeout=timeout)
    content_type = response.headers.get("content-type", "")

    if "text/html" in content_type.lower():
        raise AuthError(f"Received HTML instead of JSON from {path}; cookie jar is likely expired.")

    try:
        data = response.json()
    except ValueError as exc:
        snippet = response.text[:200].replace("\n", " ")
        raise Dp58Error(f"Failed to parse JSON from {path}: {snippet}") from exc

    if response.status_code != 200:
        raise Dp58Error(f"HTTP {response.status_code} from {path}: {json.dumps(data, ensure_ascii=False)}")

    code = data.get("code")
    status = data.get("status")
    if code != 200 or status != "success":
        if "login" in json.dumps(data, ensure_ascii=False).lower():
            raise AuthError(f"Authentication failed for {path}: {json.dumps(data, ensure_ascii=False)}")
        raise Dp58Error(f"Business error from {path}: {json.dumps(data, ensure_ascii=False)}")

    return data


def get_current_user(session: requests.Session, *, timeout: int) -> dict[str, Any]:
    return request_json(session, "GET", "/v2/user-info/get-current-user", timeout=timeout)["data"]


def get_user_orgs(session: requests.Session, *, timeout: int) -> list[Org]:
    payload = request_json(session, "GET", "/api/org-manage/org/get-user-org-list", timeout=timeout)
    orgs = []
    for item in payload.get("data", []):
        org_id = item.get("org_id")
        org_name = item.get("org_name") or ""
        if org_id is None:
            continue
        orgs.append(Org(org_id=int(org_id), org_name=org_name, is_current=item.get("is_current") == 1))
    return orgs


def change_current_org(session: requests.Session, org_id: int, *, timeout: int) -> None:
    request_json(
        session,
        "POST",
        "/api/user/auth/change-current-org",
        timeout=timeout,
        body={"org_id": org_id},
    )


def ensure_current_org(
    session: requests.Session,
    org: Org,
    *,
    timeout: int,
) -> dict[str, Any]:
    """Switch to the requested org and verify the server-side current org."""
    confirmed_user = get_current_user(session, timeout=timeout)
    current_org_id = confirmed_user.get("current_org_id")
    if current_org_id == org.org_id:
        return confirmed_user

    change_current_org(session, org.org_id, timeout=timeout)
    confirmed_user = get_current_user(session, timeout=timeout)
    current_org_id = confirmed_user.get("current_org_id")
    if current_org_id != org.org_id:
        raise Dp58Error(
            f"Failed to switch org context to {org.org_id} ({org.org_name}); "
            f"server still reports current_org_id={current_org_id}"
        )
    return confirmed_user


def fetch_task_page(
    session: requests.Session,
    *,
    owner_id: int,
    page: int,
    page_size: int,
    timeout: int,
    name: str | None = None,
) -> dict[str, Any]:
    req: dict[str, Any] = {
        "owner_id": owner_id,
        "has_sub_product": False,
    }
    if name:
        req["name"] = name

    body = {
        "page": {
            "current": page,
            "size": page_size,
            "orders": [],
        },
        "req": req,
    }
    return request_json(session, "POST", "/v2/task-info/get-list-page", timeout=timeout, body=body)["data"]


def fetch_tasks_for_org(
    session: requests.Session,
    org: Org,
    *,
    owner_id: int,
    page_size: int,
    timeout: int,
    name: str | None = None,
    limit_remaining: int = 0,
) -> list[dict[str, Any]]:
    page = 1
    collected: list[dict[str, Any]] = []

    while True:
        payload = fetch_task_page(
            session,
            owner_id=owner_id,
            page=page,
            page_size=page_size,
            timeout=timeout,
            name=name,
        )
        records = payload.get("records", []) or []
        for item in records:
            row = dict(item)
            row["_org_id"] = org.org_id
            row["_org_name"] = org.org_name
            scheduler_id = row.get("scheduler_id")
            if scheduler_id is not None:
                row["task_detail_url"] = (
                    f"{TASK_LIST_PAGE_URL}/task-detail/{scheduler_id}"
                )
            collected.append(row)
            if limit_remaining > 0 and len(collected) >= limit_remaining:
                return collected

        total = int(payload.get("total") or 0)
        current = int(payload.get("current") or page)
        size = int(payload.get("size") or page_size or 1)
        if not records or current * size >= total:
            break
        page += 1

    return collected


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any, *, indent: int) -> None:
    ensure_parent(path)
    text = json.dumps(payload, ensure_ascii=False, indent=indent or None)
    path.write_text(text + ("\n" if indent else ""), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    fieldnames = [
        "_org_id",
        "_org_name",
        "scheduler_id",
        "job_detail_id",
        "dev_task_id",
        "name",
        "owner_id",
        "owner_chinese_name",
        "owner_oa_name",
        "editor_chinese_name",
        "job_type_name",
        "status",
        "job_state",
        "run_cycle",
        "update_time",
        "create_time",
        "product_full_name",
        "label_names",
        "health_score",
        "job_desc",
        "task_detail_url",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_summary(
    *,
    owner_id: int,
    owner_name: str,
    cookie_file: str,
    current_user: dict[str, Any],
    orgs_scanned: list[Org],
    tasks: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    counts = Counter(row.get("_org_name") or str(row.get("_org_id")) for row in tasks)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "site": "dp58",
        "target_owner": {
            "owner_id": owner_id,
            "owner_name": owner_name,
        },
        "cookie_source": {
            "type": "json",
            "path": cookie_file,
        },
        "current_user": {
            "id": current_user.get("id"),
            "oa_name": current_user.get("oa_name"),
            "chinese_name": current_user.get("chinese_name"),
            "current_org_id": current_user.get("current_org_id"),
            "current_org_name": current_user.get("current_org_name"),
        },
        "query": {
            "name": args.name,
            "page_size": args.page_size,
            "limit": args.limit if args.limit > 0 else None,
            "org_ids": args.org_ids or [],
        },
        "orgs_scanned": [
            {
                "org_id": org.org_id,
                "org_name": org.org_name,
                "is_current": org.is_current,
            }
            for org in orgs_scanned
        ],
        "total_tasks": len(tasks),
        "task_count_by_org": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
        "output_files": {
            "json": args.output_json,
            "csv": args.output_csv,
            "summary_json": args.summary_json,
        },
    }


def filter_orgs(orgs: list[Org], org_ids: list[int] | None) -> list[Org]:
    if not org_ids:
        return orgs
    wanted = set(org_ids)
    filtered = [org for org in orgs if org.org_id in wanted]
    if not filtered:
        raise Dp58Error(f"None of the requested org ids are available: {sorted(wanted)}")
    return filtered


def main() -> None:
    args = parse_args()
    cookie_path = Path(args.cookies_json)
    session = build_session(load_cookie_entries(cookie_path))

    current_user = get_current_user(session, timeout=args.timeout)
    orgs = filter_orgs(get_user_orgs(session, timeout=args.timeout), args.org_ids)

    original_org_id = current_user.get("current_org_id")
    active_org_id = original_org_id
    all_tasks: list[dict[str, Any]] = []

    try:
        for org in orgs:
            if active_org_id != org.org_id:
                current_user = ensure_current_org(session, org, timeout=args.timeout)
                active_org_id = current_user.get("current_org_id")
            else:
                current_user = get_current_user(session, timeout=args.timeout)
                if current_user.get("current_org_id") != org.org_id:
                    raise Dp58Error(
                        f"Org context drift detected before fetch; expected {org.org_id}, "
                        f"got {current_user.get('current_org_id')}"
                    )

            limit_remaining = 0
            if args.limit > 0:
                limit_remaining = max(args.limit - len(all_tasks), 0)
                if limit_remaining == 0:
                    break

            org_tasks = fetch_tasks_for_org(
                session,
                org,
                owner_id=args.owner_id,
                page_size=args.page_size,
                timeout=args.timeout,
                name=args.name,
                limit_remaining=limit_remaining,
            )
            all_tasks.extend(org_tasks)

            print(
                f"[dp58] org {org.org_id} {org.org_name}: fetched {len(org_tasks)} task(s)",
                file=sys.stderr,
            )
    finally:
        if original_org_id is not None:
            try:
                ensure_current_org(
                    session,
                    Org(
                        org_id=int(original_org_id),
                        org_name=str(current_user.get("current_org_name") or original_org_id),
                        is_current=True,
                    ),
                    timeout=args.timeout,
                )
            except Exception as exc:  # pragma: no cover - best effort restore
                print(f"[dp58] failed to restore original org: {exc}", file=sys.stderr)

    summary = build_summary(
        owner_id=args.owner_id,
        owner_name=args.owner_name,
        cookie_file=str(cookie_path),
        current_user=current_user,
        orgs_scanned=orgs,
        tasks=all_tasks,
        args=args,
    )

    write_json(Path(args.output_json), all_tasks, indent=args.indent)
    write_csv(Path(args.output_csv), all_tasks)
    write_json(Path(args.summary_json), summary, indent=args.indent)

    print(
        json.dumps(
            {
                "ok": True,
                "total_tasks": len(all_tasks),
                "output_json": args.output_json,
                "output_csv": args.output_csv,
                "summary_json": args.summary_json,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
