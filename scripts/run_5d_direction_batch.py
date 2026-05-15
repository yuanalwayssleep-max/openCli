#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from train_5d_return_model import DEFAULT_OUTPUT_DIR
from train_5d_direction_model import DEFAULT_SAMPLE_CSV


@dataclass(frozen=True)
class JobResult:
    date_tag: str
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="并发批量运行A股5日方向预测")
    parser.add_argument("--sample-csv", default=str(DEFAULT_SAMPLE_CSV), help="5日方向预测样本明细CSV")
    parser.add_argument("--train-quality-csv", default="", help="训练样本质量标记CSV")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--dates", default="", help="锚点日期，逗号分隔，支持YYYY-MM-DD或YYYYMMDD")
    parser.add_argument("--months", default="", help="锚点月份，逗号分隔，如2025-08,2025-09")
    parser.add_argument("--start-date", default="", help="开始日期，YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="结束日期，YYYY-MM-DD")
    parser.add_argument("--feature-set", default="core", choices=["all", "core", "core_v14", "stock_only", "relative_core"])
    parser.add_argument("--output-suffix", default="", help="03/04预测文件输出后缀")
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1), help="并发进程数，默认最多4个")
    parser.add_argument("--model-iterations", type=int, default=80)
    parser.add_argument("--model-mode", choices=["ensemble", "single"], default="ensemble")
    parser.add_argument("--train-window-dates", type=int, default=40)
    parser.add_argument("--ensemble-window-weights", default="40:0.45,60:0.35,90:0.20")
    parser.add_argument("--sample-weight-mode", choices=["balanced", "recent_balanced", "none"], default="recent_balanced")
    parser.add_argument("--train-target-margin", type=float, default=0.005)
    parser.add_argument("--threshold-mode", choices=["regime", "validation"], default="regime")
    parser.add_argument("--direction-threshold", type=float, default=-1.0)
    parser.add_argument("--min-history", type=int, default=60)
    parser.add_argument("--min-train-samples", type=int, default=200)
    parser.add_argument("--exclude-beijing", action="store_true")
    parser.add_argument("--run-correction", action="store_true", help="预测完成后运行市场风险修正")
    parser.add_argument("--run-signal", action="store_true", help="修正完成后运行信号决策层；会自动启用--run-correction")
    parser.add_argument("--correction-output-suffix", default="", help="10修正文件输出后缀；默认沿用--output-suffix")
    parser.add_argument("--correction-policy", choices=["full", "high_confidence", "v15"], default="v15")
    parser.add_argument("--label-csv", default="00_5日涨跌方向预测样本明细.csv")
    parser.add_argument("--feature-csv", default="00_5日方向模型特征表.csv")
    return parser.parse_args()


def normalize_date_tag(value: str) -> str:
    return pd.to_datetime(value).strftime("%Y%m%d")


def normalize_date_text(value: str) -> str:
    return pd.to_datetime(value).strftime("%Y-%m-%d")


def load_available_dates(sample_csv: Path) -> list[pd.Timestamp]:
    df = pd.read_csv(sample_csv, encoding="utf-8-sig", usecols=["日期"])
    dates = pd.to_datetime(df["日期"], errors="coerce").dropna().drop_duplicates()
    return sorted(dates)


def resolve_dates(args: argparse.Namespace) -> list[str]:
    explicit_dates = [item.strip() for item in args.dates.split(",") if item.strip()]
    if explicit_dates:
        return sorted({normalize_date_tag(item) for item in explicit_dates})

    sample_csv = Path(args.sample_csv).resolve()
    dates = load_available_dates(sample_csv)
    if args.months:
        months = {item.strip() for item in args.months.split(",") if item.strip()}
        selected = [dt for dt in dates if dt.strftime("%Y-%m") in months]
    elif args.start_date and args.end_date:
        start = pd.to_datetime(args.start_date)
        end = pd.to_datetime(args.end_date)
        selected = [dt for dt in dates if start <= dt <= end]
    else:
        raise SystemExit("请提供 --dates、--months 或 --start-date/--end-date")

    if not selected:
        raise SystemExit("没有匹配到可预测日期，请检查样本表日期覆盖范围")
    return [dt.strftime("%Y%m%d") for dt in selected]


def build_train_command(args: argparse.Namespace, date_tag: str) -> list[str]:
    cmd = [
        sys.executable,
        "scripts/train_5d_direction_model.py",
        "--sample-csv",
        str(Path(args.sample_csv).resolve()),
        "--output-dir",
        str(Path(args.output_dir).resolve()),
        "--output-suffix",
        args.output_suffix,
        "--as-of-date",
        normalize_date_text(date_tag),
        "--feature-set",
        args.feature_set,
        "--model-iterations",
        str(args.model_iterations),
        "--model-mode",
        args.model_mode,
        "--train-window-dates",
        str(args.train_window_dates),
        "--ensemble-window-weights",
        args.ensemble_window_weights,
        "--sample-weight-mode",
        args.sample_weight_mode,
        "--train-target-margin",
        str(args.train_target_margin),
        "--threshold-mode",
        args.threshold_mode,
        "--direction-threshold",
        str(args.direction_threshold),
        "--min-history",
        str(args.min_history),
        "--min-train-samples",
        str(args.min_train_samples),
    ]
    if args.train_quality_csv:
        cmd.extend(["--train-quality-csv", str(Path(args.train_quality_csv).resolve())])
    if args.exclude_beijing:
        cmd.append("--exclude-beijing")
    return cmd


def run_one_date(args: argparse.Namespace, date_tag: str) -> JobResult:
    proc = subprocess.run(
        build_train_command(args, date_tag),
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )
    return JobResult(
        date_tag=date_tag,
        ok=proc.returncode == 0,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def run_batch_predictions(args: argparse.Namespace, dates: list[str]) -> list[JobResult]:
    max_workers = max(1, min(args.workers, len(dates)))
    results: list[JobResult] = []
    print(f"并发预测日期数: {len(dates)}, workers={max_workers}, feature_set={args.feature_set}")
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(run_one_date, args, date_tag): date_tag for date_tag in dates}
        for future in concurrent.futures.as_completed(future_map):
            date_tag = future_map[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = JobResult(date_tag=date_tag, ok=False, returncode=-1, stdout="", stderr=str(exc))
            results.append(result)
            status = "完成" if result.ok else "失败"
            print(f"[{status}] {date_tag}")
            if not result.ok:
                tail = (result.stderr or result.stdout).strip().splitlines()[-8:]
                print("\n".join(tail))
    return sorted(results, key=lambda item: item.date_tag)


def run_post_steps(args: argparse.Namespace, dates: list[str]) -> None:
    if not (args.run_correction or args.run_signal):
        return

    output_dir = Path(args.output_dir).resolve()
    correction_suffix = args.correction_output_suffix or args.output_suffix
    dates_arg = ",".join(dates)
    correction_cmd = [
        sys.executable,
        "scripts/apply_market_risk_correction.py",
        "--output-dir",
        str(output_dir),
        "--dates",
        dates_arg,
        "--prediction-suffix",
        args.output_suffix,
        "--output-suffix",
        correction_suffix,
        "--correction-policy",
        args.correction_policy,
        "--label-csv",
        args.label_csv,
        "--feature-csv",
        args.feature_csv,
    ]
    print("开始市场风险修正...")
    subprocess.run(correction_cmd, cwd=Path(__file__).resolve().parents[1], check=True)

    if not args.run_signal:
        return

    detail_csv = output_dir / f"10_个股预测结果_市场风险修正{correction_suffix}_{dates[0]}_{dates[-1]}.csv"
    output_prefix = output_dir / f"14{correction_suffix}_信号决策"
    signal_cmd = [
        sys.executable,
        "scripts/apply_signal_decision_layer.py",
        "--detail-csv",
        str(detail_csv),
        "--output-prefix",
        str(output_prefix),
    ]
    print("开始信号决策层...")
    subprocess.run(signal_cmd, cwd=Path(__file__).resolve().parents[1], check=True)


def main() -> None:
    args = parse_args()
    dates = resolve_dates(args)
    results = run_batch_predictions(args, dates)
    failed = [item for item in results if not item.ok]
    if failed:
        print(f"失败日期数: {len(failed)} / {len(results)}")
        raise SystemExit(1)
    run_post_steps(args, dates)
    print(f"全部完成: {len(results)} 个日期")


if __name__ == "__main__":
    main()
