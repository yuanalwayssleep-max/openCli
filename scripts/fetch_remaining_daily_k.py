#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import time
from datetime import date
from pathlib import Path

import baostock as bs
import pandas as pd
import tushare as ts

try:
    import akshare as ak
except Exception:
    ak = None


DAILY_FIELDS = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
START_DATE_TEXT = "2025-01-01"
START_DATE_COMPACT = "20250101"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="补抓缺失的日K线文件，支持 baostock / tushare / akshare")
    parser.add_argument("--symbols-csv", required=True, help="股票清单 CSV")
    parser.add_argument("--output-dir", required=True, help="日K线目录")
    parser.add_argument("--provider", default="baostock", choices=["baostock", "tushare", "akshare", "eastmoney-curl"], help="数据源")
    parser.add_argument("--token", default=os.environ.get("TUSHARE_TOKEN", ""), help="Tushare Pro token")
    parser.add_argument("--batch-size", type=int, default=10, help="Tushare 每批股票数，默认 10")
    parser.add_argument("--limit", type=int, default=260, help="每只股票最多保留多少根日K，默认 260")
    parser.add_argument("--retries", type=int, default=3, help="失败重试次数，默认 3")
    parser.add_argument("--sleep-seconds", type=float, default=0.2, help="成功后的停顿秒数")
    parser.add_argument("--retry-sleep-seconds", type=float, default=0.8, help="失败重试前停顿秒数")
    return parser.parse_args()


def safe_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[\\\\/:*?"<>|]+', "_", value.strip())
    return value or "未命名"


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def market_suffix(code: str) -> str:
    if code.startswith(("4", "8")) or code.startswith("92"):
        return ".BJ"
    if code.startswith(("5", "6", "9")):
        return ".SH"
    if code.startswith(("0", "2", "3")):
        return ".SZ"
    raise ValueError(f"无法识别市场: {code}")


def market_prefix(code: str) -> str:
    return market_suffix(code)[1:].lower()


def to_ts_code(code: str) -> str:
    return f"{code}{market_suffix(code)}"


def to_bs_code(code: str) -> str:
    return f"{market_prefix(code)}.{code}"


def eastmoney_market_code(code: str) -> str:
    if code.startswith("6"):
        return "1"
    return "0"


def output_path(output_dir: Path, code: str, name: str) -> Path:
    return output_dir / f"{code}_{sanitize_filename(name)}_daily_k.csv"


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DAILY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_rows_from_tushare(df: pd.DataFrame, limit: int) -> list[dict[str, str]]:
    if df.empty:
        return []
    df = df.sort_values("trade_date").tail(limit).copy()
    rows: list[dict[str, str]] = []
    prev_close = None
    for _, item in df.iterrows():
        trade_date = str(item["trade_date"])
        open_ = safe_float(item["open"])
        close = safe_float(item["close"])
        high = safe_float(item["high"])
        low = safe_float(item["low"])
        pre_close = safe_float(item["pre_close"])
        vol = safe_float(item["vol"]) * 100
        amount = safe_float(item["amount"]) * 1000
        pct_chg = safe_float(item["pct_chg"])
        change = safe_float(item["change"])
        base_close = prev_close if prev_close else pre_close
        amplitude = ((high - low) / base_close * 100) if base_close else 0.0
        rows.append(
            {
                "日期": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}",
                "开盘": f"{open_:.4f}",
                "收盘": f"{close:.4f}",
                "最高": f"{high:.4f}",
                "最低": f"{low:.4f}",
                "成交量": f"{vol:.0f}",
                "成交额": f"{amount:.0f}",
                "振幅": f"{amplitude:.2f}",
                "涨跌幅": f"{pct_chg:.4f}",
                "涨跌额": f"{change:.4f}",
                "换手率": "",
            }
        )
        prev_close = close
    return rows


def build_rows_from_akshare(df: pd.DataFrame, limit: int) -> list[dict[str, str]]:
    if df.empty:
        return []
    df = df.sort_values("日期").tail(limit).copy()
    rows: list[dict[str, str]] = []
    for _, item in df.iterrows():
        rows.append(
            {
                "日期": str(item["日期"]),
                "开盘": f"{safe_float(item['开盘']):.4f}",
                "收盘": f"{safe_float(item['收盘']):.4f}",
                "最高": f"{safe_float(item['最高']):.4f}",
                "最低": f"{safe_float(item['最低']):.4f}",
                "成交量": f"{safe_float(item['成交量']):.0f}",
                "成交额": f"{safe_float(item['成交额']):.0f}",
                "振幅": f"{safe_float(item.get('振幅', 0)):.2f}",
                "涨跌幅": f"{safe_float(item.get('涨跌幅', 0)):.4f}",
                "涨跌额": f"{safe_float(item.get('涨跌额', 0)):.4f}",
                "换手率": f"{safe_float(item.get('换手率', 0)):.4f}" if item.get("换手率", "") != "" else "",
            }
        )
    return rows


def build_rows_from_baostock(raw_rows: list[list[str]], limit: int) -> list[dict[str, str]]:
    raw_rows = raw_rows[-limit:]
    rows: list[dict[str, str]] = []
    prev_close = None
    for item in raw_rows:
        trade_date, open_, close, high, low, volume, amount, turn, pct_chg = item
        high_f = safe_float(high)
        low_f = safe_float(low)
        close_f = safe_float(close)
        amplitude = ((high_f - low_f) / prev_close * 100) if prev_close else 0.0
        change = close_f - prev_close if prev_close else 0.0
        rows.append(
            {
                "日期": trade_date,
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


def build_rows_from_eastmoney_klines(klines: list[str], limit: int) -> list[dict[str, str]]:
    selected = klines[-limit:]
    rows: list[dict[str, str]] = []
    for item in selected:
        parts = item.split(",")
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


def chunked(items: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def fetch_one_baostock(code: str, limit: int) -> list[dict[str, str]]:
    rs = bs.query_history_k_data_plus(
        to_bs_code(code),
        "date,open,close,high,low,volume,amount,turn,pctChg",
        start_date=START_DATE_TEXT,
        end_date=date.today().isoformat(),
        frequency="d",
        adjustflag="2",
    )
    if rs.error_code != "0":
        raise RuntimeError(f"{rs.error_code} {rs.error_msg}")
    raw_rows: list[list[str]] = []
    while rs.next():
        raw_rows.append(rs.get_row_data())
    rows = build_rows_from_baostock(raw_rows, limit)
    if not rows:
        raise RuntimeError("empty daily rows")
    return rows


def run_baostock(pending_rows: list[dict[str, str]], output_dir: Path, args: argparse.Namespace, skipped: int) -> tuple[int, list[dict[str, str]]]:
    login_result = bs.login()
    if login_result.error_code != "0":
        raise RuntimeError(f"baostock login failed: {login_result.error_code} {login_result.error_msg}")
    fetched = 0
    failures: list[dict[str, str]] = []
    try:
        for idx, item in enumerate(pending_rows, 1):
            code = item["代码"]
            name = item["名称"]
            last_error = ""
            success = False
            for _ in range(args.retries):
                try:
                    rows = fetch_one_baostock(code, args.limit)
                    write_csv(output_path(output_dir, code, name), rows)
                    fetched += 1
                    success = True
                    break
                except Exception as exc:
                    last_error = str(exc)
                    try:
                        bs.logout()
                    except Exception:
                        pass
                    time.sleep(args.retry_sleep_seconds)
                    relogin = bs.login()
                    if relogin.error_code != "0":
                        last_error = f"baostock relogin failed: {relogin.error_code} {relogin.error_msg}"
            if not success:
                failures.append({"代码": code, "名称": name, "错误": last_error[:500]})
            if idx % 10 == 0:
                print(f"progress {idx}/{len(pending_rows)} fetched={fetched} skipped={skipped} failed={len(failures)}", flush=True)
            time.sleep(args.sleep_seconds)
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    return fetched, failures


def run_tushare(pending_rows: list[dict[str, str]], output_dir: Path, args: argparse.Namespace, skipped: int) -> tuple[int, list[dict[str, str]]]:
    if not args.token:
        raise RuntimeError("缺少 Tushare Pro token")
    ts.set_token(args.token)
    pro = ts.pro_api()
    fetched = 0
    failures: list[dict[str, str]] = []
    batches = chunked(pending_rows, args.batch_size)
    for batch_index, batch in enumerate(batches, 1):
        batch_df = None
        last_error = ""
        ts_codes = ",".join(to_ts_code(item["代码"]) for item in batch)
        for _ in range(args.retries):
            try:
                batch_df = pro.daily(ts_code=ts_codes, start_date=START_DATE_COMPACT, end_date=date.today().strftime("%Y%m%d"))
                break
            except Exception as exc:
                last_error = str(exc)
                time.sleep(args.retry_sleep_seconds)
        if batch_df is None:
            for item in batch:
                failures.append({"代码": item["代码"], "名称": item["名称"], "错误": last_error[:500]})
            print(f"batch {batch_index}/{len(batches)} failed size={len(batch)} fetched={fetched} skipped={skipped} failed={len(failures)}", flush=True)
            continue
        for item in batch:
            code = item["代码"]
            name = item["名称"]
            one_df = batch_df[batch_df["ts_code"] == to_ts_code(code)].copy() if not batch_df.empty else pd.DataFrame()
            rows = build_rows_from_tushare(one_df, args.limit)
            if rows:
                write_csv(output_path(output_dir, code, name), rows)
                fetched += 1
            else:
                failures.append({"代码": code, "名称": name, "错误": "empty daily rows"})
        print(f"batch {batch_index}/{len(batches)} done size={len(batch)} fetched={fetched} skipped={skipped} failed={len(failures)}", flush=True)
        time.sleep(args.sleep_seconds)
    return fetched, failures


def run_akshare(pending_rows: list[dict[str, str]], output_dir: Path, args: argparse.Namespace, skipped: int) -> tuple[int, list[dict[str, str]]]:
    if ak is None:
        raise RuntimeError("akshare 未安装")
    fetched = 0
    failures: list[dict[str, str]] = []
    end_date = date.today().strftime("%Y%m%d")
    for idx, item in enumerate(pending_rows, 1):
        code = item["代码"]
        name = item["名称"]
        last_error = ""
        success = False
        for _ in range(args.retries):
            try:
                df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=START_DATE_COMPACT, end_date=end_date, adjust="qfq")
                rows = build_rows_from_akshare(df, args.limit)
                if not rows:
                    raise RuntimeError("empty daily rows")
                write_csv(output_path(output_dir, code, name), rows)
                fetched += 1
                success = True
                break
            except Exception as exc:
                last_error = str(exc)
                time.sleep(args.retry_sleep_seconds)
        if not success:
            failures.append({"代码": code, "名称": name, "错误": last_error[:500]})
        if idx % 10 == 0:
            print(f"progress {idx}/{len(pending_rows)} fetched={fetched} skipped={skipped} failed={len(failures)}", flush=True)
        time.sleep(args.sleep_seconds)
    return fetched, failures


def fetch_one_eastmoney_curl(code: str, limit: int) -> list[dict[str, str]]:
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116"
        f"&ut=7eea3edcaed734bea9cbfc24409ed989"
        f"&klt=101&fqt=1&secid={eastmoney_market_code(code)}.{code}"
        f"&beg={START_DATE_COMPACT}&end={date.today().strftime('%Y%m%d')}"
    )
    cmd = [
        "curl",
        "-L",
        "--max-time",
        "20",
        "--retry",
        "2",
        "--retry-delay",
        "1",
        "-A",
        "Mozilla/5.0",
        "-H",
        "Referer: https://quote.eastmoney.com/",
        "-sS",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or f"curl exit {result.returncode}").strip())
    data_json = json.loads(result.stdout)
    data = data_json.get("data")
    if not data or not data.get("klines"):
        raise RuntimeError("empty daily rows")
    return build_rows_from_eastmoney_klines(data["klines"], limit)


def run_eastmoney_curl(pending_rows: list[dict[str, str]], output_dir: Path, args: argparse.Namespace, skipped: int) -> tuple[int, list[dict[str, str]]]:
    fetched = 0
    failures: list[dict[str, str]] = []
    for idx, item in enumerate(pending_rows, 1):
        code = item["代码"]
        name = item["名称"]
        last_error = ""
        success = False
        for _ in range(args.retries):
            try:
                rows = fetch_one_eastmoney_curl(code, args.limit)
                write_csv(output_path(output_dir, code, name), rows)
                fetched += 1
                success = True
                break
            except Exception as exc:
                last_error = str(exc)
                time.sleep(args.retry_sleep_seconds)
        if not success:
            failures.append({"代码": code, "名称": name, "错误": last_error[:500]})
        if idx % 10 == 0:
            print(f"progress {idx}/{len(pending_rows)} fetched={fetched} skipped={skipped} failed={len(failures)}", flush=True)
        time.sleep(args.sleep_seconds)
    return fetched, failures


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = load_rows(Path(args.symbols_csv).resolve())
    pending_rows: list[dict[str, str]] = []
    skipped = 0
    for row in all_rows:
        code = (row.get("代码") or "").strip().zfill(6)
        name = (row.get("名称") or "").strip()
        if not code:
            continue
        if output_path(output_dir, code, name).exists() and output_path(output_dir, code, name).stat().st_size > 64:
            skipped += 1
            continue
        pending_rows.append({"代码": code, "名称": name})

    if args.provider == "baostock":
        fetched, failures = run_baostock(pending_rows, output_dir, args, skipped)
    elif args.provider == "tushare":
        fetched, failures = run_tushare(pending_rows, output_dir, args, skipped)
    elif args.provider == "akshare":
        fetched, failures = run_akshare(pending_rows, output_dir, args, skipped)
    else:
        fetched, failures = run_eastmoney_curl(pending_rows, output_dir, args, skipped)

    failed_path = output_dir.parent / "failed_symbols_日K线.csv"
    with failed_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["代码", "名称", "错误"])
        writer.writeheader()
        writer.writerows(failures)

    print(
        f"done provider={args.provider} total={len(all_rows)} pending={len(pending_rows)} fetched={fetched} skipped={skipped} "
        f"failed={len(failures)} daily_files={len(list(output_dir.glob('*.csv')))} failed_csv={failed_path}"
    )


if __name__ == "__main__":
    main()
