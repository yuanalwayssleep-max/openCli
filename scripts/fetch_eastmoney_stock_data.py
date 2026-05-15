#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import baostock as bs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "outputs"
DEFAULT_OUT_DIR.mkdir(parents=True, exist_ok=True)

DAILY_FIELDS = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
FIVE_MIN_FIELDS = ["时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
INTRADAY_FIELDS = ["时间", "最新价", "均价", "最高", "最低", "成交量", "成交额", "最新价_格式化"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="使用免费 Python 接口抓取单只股票的日K、5分钟K、分时兼容数据")
    parser.add_argument("--symbol", required=True, help="股票代码，支持 600111 / sh600111 / sz000001 / bj430047")
    parser.add_argument("--daily-limit", type=int, default=500, help="日K条数，默认 500")
    parser.add_argument("--five-min-limit", type=int, default=500, help="5分钟K条数，默认 500")
    parser.add_argument("--intraday-days", type=int, default=1, help="分时天数，默认 1；当前使用5分钟K生成兼容分时")
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


def to_symbol_slug(symbol: str) -> tuple[str, str]:
    market_prefix, code = normalize_symbol(symbol)
    return f"{market_prefix}.{code}", f"{market_prefix}{code}"


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def safe_float(value: str) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def login_baostock() -> None:
    result = bs.login()
    if result.error_code != "0":
        raise RuntimeError(f"baostock login failed: {result.error_code} {result.error_msg}")


def logout_baostock() -> None:
    try:
        bs.logout()
    except Exception:
        pass


def fetch_daily_k(bs_symbol: str, limit: int) -> list[dict[str, str]]:
    rs = bs.query_history_k_data_plus(
        bs_symbol,
        "date,open,close,high,low,volume,amount,turn,pctChg",
        start_date="1990-01-01",
        end_date="2099-12-31",
        frequency="d",
        adjustflag="2",
    )
    if rs.error_code != "0":
        raise RuntimeError(f"baostock daily query failed: {rs.error_code} {rs.error_msg}")

    raw_rows: list[list[str]] = []
    while rs.next():
        raw_rows.append(rs.get_row_data())
    raw_rows = raw_rows[-limit:]

    rows: list[dict[str, str]] = []
    prev_close = None
    for item in raw_rows:
        date, open_, close, high, low, volume, amount, turn, pct_chg = item
        high_f = safe_float(high)
        low_f = safe_float(low)
        open_f = safe_float(open_)
        close_f = safe_float(close)
        amplitude = ((high_f - low_f) / prev_close * 100) if prev_close else 0.0
        change = close_f - prev_close if prev_close else 0.0
        rows.append(
            {
                "日期": date,
                "开盘": open_,
                "收盘": close,
                "最高": high,
                "最低": low,
                "成交量": volume,
                "成交额": amount,
                "振幅": f"{amplitude:.2f}",
                "涨跌幅": pct_chg or "0",
                "涨跌额": f"{change:.2f}",
                "换手率": turn or "0",
            }
        )
        prev_close = close_f
    return rows


def fetch_5m_k(bs_symbol: str, limit: int) -> list[dict[str, str]]:
    rs = bs.query_history_k_data_plus(
        bs_symbol,
        "date,time,open,close,high,low,volume,amount",
        start_date="2025-01-01",
        end_date="2099-12-31",
        frequency="5",
        adjustflag="2",
    )
    if rs.error_code != "0":
        raise RuntimeError(f"baostock 5min query failed: {rs.error_code} {rs.error_msg}")

    raw_rows: list[list[str]] = []
    while rs.next():
        raw_rows.append(rs.get_row_data())
    raw_rows = raw_rows[-limit:]

    rows: list[dict[str, str]] = []
    prev_close = None
    for item in raw_rows:
        date, time_code, open_, close, high, low, volume, amount = item
        ts = f"{date} {time_code[8:10]}:{time_code[10:12]}"
        high_f = safe_float(high)
        low_f = safe_float(low)
        close_f = safe_float(close)
        amplitude = ((high_f - low_f) / prev_close * 100) if prev_close else 0.0
        pct_chg = ((close_f / prev_close - 1) * 100) if prev_close else 0.0
        change = close_f - prev_close if prev_close else 0.0
        rows.append(
            {
                "时间": ts,
                "开盘": open_,
                "收盘": close,
                "最高": high,
                "最低": low,
                "成交量": volume,
                "成交额": amount,
                "振幅": f"{amplitude:.2f}",
                "涨跌幅": f"{pct_chg:.2f}",
                "涨跌额": f"{change:.2f}",
                "换手率": "0",
            }
        )
        prev_close = close_f
    return rows


def build_intraday_from_5m(rows_5m: list[dict[str, str]], intraday_days: int) -> list[dict[str, str]]:
    if not rows_5m:
        return []
    selected = rows_5m[-48 * intraday_days :]
    intraday_rows: list[dict[str, str]] = []
    cumulative_amount = 0.0
    cumulative_volume = 0.0
    for row in selected:
        amount = safe_float(row["成交额"])
        volume = safe_float(row["成交量"])
        close = safe_float(row["收盘"])
        cumulative_amount += amount
        cumulative_volume += volume
        avg_price = (cumulative_amount / cumulative_volume) if cumulative_volume else close
        intraday_rows.append(
            {
                "时间": row["时间"],
                "最新价": row["收盘"],
                "均价": f"{avg_price:.3f}",
                "最高": row["最高"],
                "最低": row["最低"],
                "成交量": row["成交量"],
                "成交额": row["成交额"],
                "最新价_格式化": row["收盘"],
            }
        )
    return intraday_rows


def main() -> None:
    args = parse_args()
    bs_symbol, symbol_slug = to_symbol_slug(args.symbol)
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    login_baostock()
    try:
        daily_rows = fetch_daily_k(bs_symbol, args.daily_limit)
        k5_rows = fetch_5m_k(bs_symbol, args.five_min_limit)
        intraday_rows = build_intraday_from_5m(k5_rows, args.intraday_days)
    finally:
        logout_baostock()

    daily_path = out_dir / f"eastmoney_{symbol_slug}_daily_k.csv"
    five_min_path = out_dir / f"eastmoney_{symbol_slug}_5min_k.csv"
    intraday_path = out_dir / f"eastmoney_{symbol_slug}_intraday.csv"

    write_csv(daily_path, DAILY_FIELDS, daily_rows)
    write_csv(five_min_path, FIVE_MIN_FIELDS, k5_rows)
    write_csv(intraday_path, INTRADAY_FIELDS, intraday_rows)

    print(
        f"saved symbol={symbol_slug} daily_k={len(daily_rows)} 5min_k={len(k5_rows)} "
        f"intraday={len(intraday_rows)} provider=baostock to {out_dir}"
    )


if __name__ == "__main__":
    main()
