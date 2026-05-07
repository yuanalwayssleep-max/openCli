#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "outputs"
DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_RETRIES = 3
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
INTRADAY_URL = "https://push2.eastmoney.com/api/qt/stock/trends2/get"
UT = "fa5fd1943c7b386f172d6893dbfba10b"

DAILY_FIELDS = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
FIVE_MIN_FIELDS = ["时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
INTRADAY_FIELDS = ["时间", "最新价", "均价", "最高", "最低", "成交量", "成交额", "最新价_格式化"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取东方财富单只股票的日K、5分钟K、分时数据")
    parser.add_argument("--symbol", required=True, help="股票代码，支持 600111 / sh600111 / sz000001 / bj430047")
    parser.add_argument("--daily-limit", type=int, default=500, help="日K条数，默认 500")
    parser.add_argument("--five-min-limit", type=int, default=500, help="5分钟K条数，默认 500")
    parser.add_argument("--intraday-days", type=int, default=1, help="分时天数，默认 1")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR), help="输出目录，默认 outputs")
    return parser.parse_args()


def normalize_symbol(symbol: str) -> tuple[str, str]:
    value = symbol.strip().lower()
    if value.startswith(("sh", "sz", "bj")):
        market_prefix = value[:2]
        code = value[2:]
    else:
        code = value
        if code.startswith(("5", "6", "9")):
            market_prefix = "sh"
        elif code.startswith(("0", "2", "3")):
            market_prefix = "sz"
        elif code.startswith(("4", "8")):
            market_prefix = "bj"
        else:
            raise ValueError(f"无法从代码推断市场前缀: {symbol}")

    if not code.isdigit():
        raise ValueError(f"股票代码必须为数字: {symbol}")
    return market_prefix, code


def to_secid(symbol: str) -> tuple[str, str]:
    market_prefix, code = normalize_symbol(symbol)
    market_id = "1" if market_prefix == "sh" else "0"
    return f"{market_id}.{code}", f"{market_prefix}{code}"


def get_json(url: str, params: dict[str, str | int]) -> dict:
    full_url = f"{url}?{urlencode(params)}"
    last_error: Exception | None = None
    for _ in range(MAX_RETRIES):
        try:
            result = subprocess.run(
                ["opencli", "browser", "open", full_url],
                check=True,
                capture_output=True,
                text=True,
            )
            if "Navigated to:" not in result.stdout:
                raise RuntimeError(f"browser open failed for {full_url}: {result.stdout}")

            time.sleep(1)
            html_result = subprocess.run(
                ["opencli", "browser", "get", "html"],
                check=True,
                capture_output=True,
                text=True,
            )
            match = re.search(r"<pre>(.*?)</pre>", html_result.stdout, re.S)
            if not match:
                raise RuntimeError(f"failed to extract json body from {full_url}")
            return json.loads(match.group(1))
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"request failed for {full_url}: {last_error}")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fetch_daily_k(secid: str, limit: int) -> list[dict[str, str]]:
    data = get_json(
        KLINE_URL,
        {
            "secid": secid,
            "klt": "101",
            "fqt": "1",
            "lmt": str(limit),
            "end": "20500101",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": UT,
        },
    )["data"]
    rows: list[dict[str, str]] = []
    for line in data["klines"]:
        parts = line.split(",")
        rows.append(
            {
                "日期": parts[0],
                "开盘": parts[1],
                "收盘": parts[2],
                "最高": parts[3],
                "最低": parts[4],
                "成交量": parts[5],
                "成交额": parts[6],
                "振幅": parts[7],
                "涨跌幅": parts[8],
                "涨跌额": parts[9],
                "换手率": parts[10],
            }
        )
    return rows


def fetch_5m_k(secid: str, limit: int) -> list[dict[str, str]]:
    data = get_json(
        KLINE_URL,
        {
            "secid": secid,
            "klt": "5",
            "fqt": "1",
            "lmt": str(limit),
            "end": "20500101",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": UT,
        },
    )["data"]
    rows: list[dict[str, str]] = []
    for line in data["klines"]:
        parts = line.split(",")
        rows.append(
            {
                "时间": parts[0],
                "开盘": parts[1],
                "收盘": parts[2],
                "最高": parts[3],
                "最低": parts[4],
                "成交量": parts[5],
                "成交额": parts[6],
                "振幅": parts[7],
                "涨跌幅": parts[8],
                "涨跌额": parts[9],
                "换手率": parts[10],
            }
        )
    return rows


def fetch_intraday(secid: str, days: int) -> list[dict[str, str]]:
    data = get_json(
        INTRADAY_URL,
        {
            "secid": secid,
            "ndays": str(days),
            "iscr": "0",
            "iscca": "0",
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ut": UT,
        },
    )["data"]
    rows: list[dict[str, str]] = []
    for line in data["trends"]:
        parts = line.split(",")
        rows.append(
            {
                "时间": parts[0],
                "最新价": parts[1],
                "均价": parts[2],
                "最高": parts[3],
                "最低": parts[4],
                "成交量": parts[5],
                "成交额": parts[6],
                "最新价_格式化": parts[7],
            }
        )
    return rows


def main() -> None:
    args = parse_args()
    secid, symbol_slug = to_secid(args.symbol)
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    daily_rows = fetch_daily_k(secid, args.daily_limit)
    k5_rows = fetch_5m_k(secid, args.five_min_limit)
    intraday_rows = fetch_intraday(secid, args.intraday_days)

    daily_path = out_dir / f"eastmoney_{symbol_slug}_daily_k.csv"
    five_min_path = out_dir / f"eastmoney_{symbol_slug}_5min_k.csv"
    intraday_path = out_dir / f"eastmoney_{symbol_slug}_intraday.csv"

    write_csv(daily_path, DAILY_FIELDS, daily_rows)
    write_csv(five_min_path, FIVE_MIN_FIELDS, k5_rows)
    write_csv(intraday_path, INTRADAY_FIELDS, intraday_rows)

    print(
        f"saved symbol={symbol_slug} daily_k={len(daily_rows)} 5min_k={len(k5_rows)} "
        f"intraday={len(intraday_rows)} to {out_dir}"
    )


if __name__ == "__main__":
    main()
