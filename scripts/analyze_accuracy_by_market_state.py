#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from train_5d_return_model import DEFAULT_OUTPUT_DIR


DEFAULT_DATES = "20260316_20260507"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按市场状态分层统计个股5日方向预测准确率")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="skill输出目录")
    parser.add_argument("--date-range", default=DEFAULT_DATES, help="10_个股预测结果_市场风险修正文件的日期后缀")
    return parser.parse_args()


def pct(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:.2%}"


def classify_error(row: pd.Series) -> str:
    if row["修正后预测是否准确"] == 1:
        return "预测正确"
    if row["修正后预测涨跌"] == "上涨" and row["实际涨跌"] == "下跌":
        return "错判为上涨"
    if row["修正后预测涨跌"] == "下跌" and row["实际涨跌"] == "上涨":
        return "错判为下跌"
    return "其他错误"


def summarize(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    denoised = df.loc[~df["是否噪声样本"]].copy()
    base = (
        df.groupby(group_cols, dropna=False)
        .agg(
            日期数=("锚点日期", "nunique"),
            股票预测数=("代码", "count"),
            原始正确数=("原始预测是否准确", "sum"),
            修正后正确数=("修正后预测是否准确", "sum"),
            预测上涨数=("修正后预测涨跌", lambda s: (s == "上涨").sum()),
            预测下跌数=("修正后预测涨跌", lambda s: (s == "下跌").sum()),
            实际上涨数=("实际涨跌", lambda s: (s == "上涨").sum()),
            实际下跌数=("实际涨跌", lambda s: (s == "下跌").sum()),
            噪声样本数=("是否噪声样本", "sum"),
            平均未来5日上涨比例=("市场未来5日上涨比例", "mean"),
            平均预测上涨概率=("预测上涨概率", "mean"),
        )
        .reset_index()
    )
    denoised_base = (
        denoised.groupby(group_cols, dropna=False)
        .agg(
            降噪后股票预测数=("代码", "count"),
            降噪后原始正确数=("原始预测是否准确", "sum"),
            降噪后修正正确数=("修正后预测是否准确", "sum"),
        )
        .reset_index()
    )
    result = base.merge(denoised_base, on=group_cols, how="left")
    for col in ["降噪后股票预测数", "降噪后原始正确数", "降噪后修正正确数"]:
        result[col] = result[col].fillna(0).astype(int)

    result["原始准确率"] = result["原始正确数"] / result["股票预测数"]
    result["修正后准确率"] = result["修正后正确数"] / result["股票预测数"]
    result["降噪后原始准确率"] = result["降噪后原始正确数"] / result["降噪后股票预测数"].replace(0, pd.NA)
    result["降噪后修正准确率"] = result["降噪后修正正确数"] / result["降噪后股票预测数"].replace(0, pd.NA)
    result["预测上涨占比"] = result["预测上涨数"] / result["股票预测数"]
    result["实际上涨占比"] = result["实际上涨数"] / result["股票预测数"]

    pct_cols = [
        "原始准确率",
        "修正后准确率",
        "降噪后原始准确率",
        "降噪后修正准确率",
        "预测上涨占比",
        "实际上涨占比",
        "平均未来5日上涨比例",
        "平均预测上涨概率",
    ]
    for col in pct_cols:
        result[col] = result[col].map(pct)
    return result


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    detail_path = output_dir / f"10_个股预测结果_市场风险修正_{args.date_range}.csv"
    if not detail_path.exists():
        raise FileNotFoundError(f"缺少修正明细文件: {detail_path}")

    df = pd.read_csv(detail_path, encoding="utf-8-sig", dtype={"代码": str})
    df["是否噪声样本"] = df["是否噪声样本"].astype(bool)
    df["错误类型"] = df.apply(classify_error, axis=1)

    state_summary = summarize(df, ["实际市场状态"])
    state_date_summary = summarize(df, ["实际市场状态", "锚点日期", "市场风险标签"])
    error_summary = (
        df.groupby(["实际市场状态", "错误类型"], dropna=False)
        .agg(
            股票数=("代码", "count"),
            降噪后股票数=("是否噪声样本", lambda s: (~s).sum()),
            平均预测上涨概率=("预测上涨概率", "mean"),
            平均实际5日涨跌幅=("5日后的实际涨跌幅", "mean"),
        )
        .reset_index()
    )
    error_summary["平均预测上涨概率"] = error_summary["平均预测上涨概率"].map(pct)
    error_summary["平均实际5日涨跌幅"] = error_summary["平均实际5日涨跌幅"].map(pct)

    state_summary_path = output_dir / f"11_按市场状态分层预测准确率_{args.date_range}.csv"
    state_date_path = output_dir / f"11_按市场状态和日期预测准确率_{args.date_range}.csv"
    error_path = output_dir / f"11_按市场状态错误类型统计_{args.date_range}.csv"

    state_summary.to_csv(state_summary_path, index=False, encoding="utf-8-sig")
    state_date_summary.to_csv(state_date_path, index=False, encoding="utf-8-sig")
    error_summary.to_csv(error_path, index=False, encoding="utf-8-sig")

    print(f"按市场状态汇总: {state_summary_path}")
    print(state_summary.to_string(index=False))
    print(f"按市场状态+日期: {state_date_path}")
    print(f"按市场状态错误类型: {error_path}")
    print(error_summary.to_string(index=False))


if __name__ == "__main__":
    main()
