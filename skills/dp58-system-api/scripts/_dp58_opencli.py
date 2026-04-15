#!/usr/bin/env python3
"""Shared OpenCLI bridge helpers for dp.58corp.com system API scripts.

中文说明：封装 OpenCLI Browser Bridge 调用，让脚本复用 Chrome 登录态请求星河接口。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any


PAGE_URL = "https://dp.58corp.com/data-develop/task-list"
RESULT_ATTR = "data-dp58-system-api-result"


def run_opencli(args: list[str]) -> str:
    # 统一加载 Node 22 环境，避免非交互 shell 中找不到 opencli。
    quoted = " ".join(_shell_quote(arg) for arg in args)
    cmd = f"source ~/.nvm/nvm.sh && nvm use 22 >/dev/null && opencli {quoted}"
    proc = subprocess.run(
        ["zsh", "-lc", cmd],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = "\n".join(part for part in [proc.stdout, proc.stderr] if part).strip()
        raise RuntimeError(detail or f"opencli exited with {proc.returncode}")
    return proc.stdout.strip()


def _shell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-open", action="store_true", help="Do not open task-list page first.")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON.")


def ensure_page(no_open: bool = False) -> None:
    # Browser Bridge 需要先有目标页面，页面主上下文才带有正确登录态和域名。
    if no_open:
        return
    run_opencli(["browser", "open", PAGE_URL])
    run_opencli(["browser", "wait", "time", "3"])


def call_api(
    method: str,
    path: str,
    body: Any | None = None,
    no_open: bool = False,
    timeout: int = 20,
) -> dict[str, Any]:
    ensure_page(no_open=no_open)
    payload = {"method": method.upper(), "path": path, "body": body}
    # 将请求注入页面主上下文执行，避免手动处理 Cookie、CSRF 或公司内网登录态。
    browser_script = f"""
(async function(payload) {{
  const attr = {json.dumps(RESULT_ATTR)};

  function done(value) {{
    document.documentElement.setAttribute(attr, JSON.stringify(value));
  }}

  async function readJson(res) {{
    const text = await res.text();
    try {{
      return JSON.parse(text);
    }} catch (error) {{
      return {{ status: 'parse_error', code: res.status, raw: text }};
    }}
  }}

  try {{
    const options = {{ credentials: 'include' }};
    if (payload.method !== 'GET') {{
      options.method = payload.method;
      options.headers = {{ 'content-type': 'application/json' }};
      options.body = JSON.stringify(payload.body || {{}});
    }}
    const res = await fetch(payload.path, options);
    const data = await readJson(res);
    done({{ ok: true, http_status: res.status, data }});
  }} catch (error) {{
    done({{ ok: false, error: String(error && error.stack || error) }});
  }}
}})({json.dumps(payload, ensure_ascii=False)});
"""

    eval_script = f"""
(function() {{
  document.documentElement.removeAttribute({json.dumps(RESULT_ATTR)});
  const script = document.createElement('script');
  script.textContent = {json.dumps(browser_script, ensure_ascii=False)};
  document.documentElement.appendChild(script);
  script.remove();
  return JSON.stringify({{ injected: true }});
}})()
"""
    run_opencli(["browser", "eval", eval_script])

    deadline = time.time() + timeout
    read_script = f"document.documentElement.getAttribute({json.dumps(RESULT_ATTR)})"
    # OpenCLI eval 隔离上下文读不到页面 window 变量，因此通过 DOM 属性回传结果。
    while time.time() < deadline:
        raw = run_opencli(["browser", "eval", read_script])
        if raw and raw not in {"null", "undefined"}:
            result = json.loads(raw)
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "API call failed"))
            return result["data"]
        time.sleep(1)

    raise TimeoutError("Timed out waiting for page API result")


def print_json(data: Any, compact: bool = False) -> None:
    if compact:
        print(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def main_error(error: Exception) -> None:
    print(str(error), file=sys.stderr)
    raise SystemExit(1)
