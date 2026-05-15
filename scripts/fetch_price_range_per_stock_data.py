#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FETCH_SCRIPT = ROOT / "scripts" / "fetch_eastmoney_stock_data.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按股票清单补抓每只股票的日K、5分钟K、分时文件")
    parser.add_argument("--symbols-csv", required=True, help="股票清单 CSV 路径")
    parser.add_argument("--output-dir", required=True, help="输出目录，内部会创建日K线目录/5分钟K线目录/分时目录")
    parser.add_argument("--daily-limit", type=int, default=260, help="日K条数，默认260")
    parser.add_argument("--five-min-limit", type=int, default=500, help="5分钟K条数，默认500")
    parser.add_argument("--intraday-days", type=int, default=1, help="分时天数，默认1")
    parser.add_argument("--timeout-seconds", type=int, default=45, help="单只股票抓取超时秒数，默认45")
    parser.add_argument("--sleep-seconds", type=float, default=0.05, help="每只股票之间的停顿秒数，默认0.05")
    return parser.parse_args()


def market_prefix(code: str) -> str:
    return "sh" if code.startswith(("5", "6", "9")) else "sz"


def ensure_dirs(base: Path) -> tuple[Path, Path, Path, Path]:
    daily = base / "日K线目录"
    five = base / "5分钟K线目录"
    intra = base / "分时目录"
    tmp = base / "_tmp_fetch"
    for path in (daily, five, intra, tmp):
        path.mkdir(parents=True, exist_ok=True)
    return daily, five, intra, tmp


def all_files_exist(code: str, daily: Path, five: Path, intra: Path) -> bool:
    prefix = market_prefix(code)
    return (
        (daily / f"eastmoney_{prefix}{code}_daily_k.csv").exists()
        and (five / f"eastmoney_{prefix}{code}_5min_k.csv").exists()
        and (intra / f"eastmoney_{prefix}{code}_intraday.csv").exists()
    )


def move_outputs(code: str, daily: Path, five: Path, intra: Path, tmp: Path) -> bool:
    prefix = market_prefix(code)
    mapping = {
        tmp / f"eastmoney_{prefix}{code}_daily_k.csv": daily / f"eastmoney_{prefix}{code}_daily_k.csv",
        tmp / f"eastmoney_{prefix}{code}_5min_k.csv": five / f"eastmoney_{prefix}{code}_5min_k.csv",
        tmp / f"eastmoney_{prefix}{code}_intraday.csv": intra / f"eastmoney_{prefix}{code}_intraday.csv",
    }
    ok = True
    for src, dst in mapping.items():
        if src.exists():
            src.replace(dst)
        else:
            ok = False
    return ok


def main() -> None:
    args = parse_args()
    symbols_csv = Path(args.symbols_csv).resolve()
    output_dir = Path(args.output_dir).resolve()
    daily_dir, five_dir, intra_dir, tmp_dir = ensure_dirs(output_dir)

    with symbols_csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    failures: list[dict[str, str]] = []
    fetched = 0
    missing = 0

    for idx, row in enumerate(rows, 1):
        code = (row.get("代码") or "").zfill(6)
        name = row.get("名称", "")
        if all_files_exist(code, daily_dir, five_dir, intra_dir):
            continue

        missing += 1
        try:
            result = subprocess.run(
                [
                    "python3",
                    str(FETCH_SCRIPT),
                    "--symbol",
                    code,
                    "--daily-limit",
                    str(args.daily_limit),
                    "--five-min-limit",
                    str(args.five_min_limit),
                    "--intraday-days",
                    str(args.intraday_days),
                    "--output-dir",
                    str(tmp_dir),
                ],
                capture_output=True,
                text=True,
                timeout=args.timeout_seconds,
            )
            if result.returncode != 0:
                failures.append({"代码": code, "名称": name, "错误": (result.stderr or result.stdout).strip()[:500]})
            elif move_outputs(code, daily_dir, five_dir, intra_dir, tmp_dir):
                fetched += 1
            else:
                failures.append({"代码": code, "名称": name, "错误": "missing output files after fetch"})
        except subprocess.TimeoutExpired:
            failures.append({"代码": code, "名称": name, "错误": f"timeout > {args.timeout_seconds}s"})

        if missing % 10 == 0:
            print(f"processed_missing={missing} source_index={idx}/{len(rows)} fetched={fetched} failed={len(failures)}", flush=True)
        time.sleep(args.sleep_seconds)

    failed_path = output_dir / "failed_symbols.csv"
    with failed_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["代码", "名称", "错误"])
        writer.writeheader()
        writer.writerows(failures)

    print(
        f"done total_symbols={len(rows)} missing={missing} fetched={fetched} failed={len(failures)} "
        f"daily={len(list(daily_dir.glob('*.csv')))} five={len(list(five_dir.glob('*.csv')))} "
        f"intraday={len(list(intra_dir.glob('*.csv')))} failed_csv={failed_path}"
    )


if __name__ == "__main__":
    main()
