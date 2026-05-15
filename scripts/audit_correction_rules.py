#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计5日方向预测修正规则的触发效果")
    parser.add_argument("--detail-csv", required=True, help="10_个股预测结果_市场风险修正明细CSV")
    parser.add_argument("--output-prefix", required=True, help="输出文件前缀，不含扩展名")
    parser.add_argument("--low-accuracy-threshold", type=float, default=0.65, help="修正后准确率低于该值的日期进入诊断")
    return parser.parse_args()


def pct(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:.2%}"


def summarize_group(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    out = (
        df.groupby(group_cols, dropna=False)
        .agg(
            股票数=("代码", "count"),
            发生修正数=("是否发生修正", "sum"),
            原始正确数=("原始预测是否准确", "sum"),
            修正后正确数=("修正后预测是否准确", "sum"),
            原始预测上涨数=("原始预测涨跌", lambda s: (s == "上涨").sum()),
            原始预测下跌数=("原始预测涨跌", lambda s: (s == "下跌").sum()),
            修正后预测上涨数=("修正后预测涨跌", lambda s: (s == "上涨").sum()),
            修正后预测下跌数=("修正后预测涨跌", lambda s: (s == "下跌").sum()),
            实际上涨数=("实际涨跌", lambda s: (s == "上涨").sum()),
            实际下跌数=("实际涨跌", lambda s: (s == "下跌").sum()),
            噪声样本数=("是否噪声样本", "sum"),
        )
        .reset_index()
    )
    out["原始准确率"] = out["原始正确数"] / out["股票数"]
    out["修正后准确率"] = out["修正后正确数"] / out["股票数"]
    out["准确率变化百分点"] = (out["修正后准确率"] - out["原始准确率"]) * 100
    out["修正净增正确数"] = out["修正后正确数"] - out["原始正确数"]
    out["原始实际下跌却预测上涨数"] = 0
    out["修正后实际下跌却预测上涨数"] = 0
    return out


def add_false_up_counts(summary: pd.DataFrame, df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    false_up = (
        df.assign(
            原始实际下跌却预测上涨=((df["原始预测涨跌"] == "上涨") & (df["实际涨跌"] == "下跌")).astype(int),
            修正后实际下跌却预测上涨=((df["修正后预测涨跌"] == "上涨") & (df["实际涨跌"] == "下跌")).astype(int),
        )
        .groupby(group_cols, dropna=False)
        .agg(
            原始实际下跌却预测上涨数=("原始实际下跌却预测上涨", "sum"),
            修正后实际下跌却预测上涨数=("修正后实际下跌却预测上涨", "sum"),
        )
        .reset_index()
    )
    summary = summary.drop(columns=["原始实际下跌却预测上涨数", "修正后实际下跌却预测上涨数"], errors="ignore")
    return summary.merge(false_up, on=group_cols, how="left")


def format_rates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["原始准确率", "修正后准确率"]:
        if col in out.columns:
            out[col] = out[col].map(pct)
    if "准确率变化百分点" in out.columns:
        out["准确率变化百分点"] = out["准确率变化百分点"].round(2)
    return out


def main() -> None:
    args = parse_args()
    detail_path = Path(args.detail_csv).resolve()
    output_prefix = Path(args.output_prefix).resolve()
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(detail_path, encoding="utf-8-sig", dtype={"代码": str})
    required = {
        "代码",
        "锚点日期",
        "修正原因",
        "市场风险标签",
        "原始预测涨跌",
        "修正后预测涨跌",
        "实际涨跌",
        "原始预测是否准确",
        "修正后预测是否准确",
        "是否发生修正",
        "是否噪声样本",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise RuntimeError(f"缺少字段: {missing}")

    rule = summarize_group(df, ["修正原因"])
    rule = add_false_up_counts(rule, df, ["修正原因"])
    rule = rule.sort_values(["修正净增正确数", "发生修正数"], ascending=[False, False]).reset_index(drop=True)

    date_rule = summarize_group(df, ["锚点日期", "实际市场状态", "市场风险标签", "修正原因"])
    date_rule = add_false_up_counts(date_rule, df, ["锚点日期", "实际市场状态", "市场风险标签", "修正原因"])
    date_rule = date_rule.sort_values(["锚点日期", "修正净增正确数"], ascending=[True, False]).reset_index(drop=True)

    by_date = summarize_group(df, ["锚点日期", "实际市场状态", "市场风险标签"])
    by_date = add_false_up_counts(by_date, df, ["锚点日期", "实际市场状态", "市场风险标签"])
    low_dates = by_date.loc[by_date["修正后准确率"] < args.low_accuracy_threshold].copy()
    low_date_keys = set(low_dates["锚点日期"].astype(str))
    low_detail = df.loc[df["锚点日期"].astype(str).isin(low_date_keys)].copy()
    low_reason = summarize_group(low_detail, ["锚点日期", "实际市场状态", "市场风险标签", "修正原因"])
    low_reason = add_false_up_counts(low_reason, low_detail, ["锚点日期", "实际市场状态", "市场风险标签", "修正原因"])
    low_reason = low_reason.sort_values(["锚点日期", "修正净增正确数"], ascending=[True, False]).reset_index(drop=True)

    rule_path = output_prefix.with_name(output_prefix.name + "_规则效果审计.csv")
    date_rule_path = output_prefix.with_name(output_prefix.name + "_按日期规则效果.csv")
    low_path = output_prefix.with_name(output_prefix.name + "_低准确率日期诊断.csv")

    format_rates(rule).to_csv(rule_path, index=False, encoding="utf-8-sig")
    format_rates(date_rule).to_csv(date_rule_path, index=False, encoding="utf-8-sig")
    format_rates(low_reason).to_csv(low_path, index=False, encoding="utf-8-sig")

    print(f"规则效果审计: {rule_path}")
    print(format_rates(rule).to_string(index=False))
    print(f"\n低准确率日期诊断: {low_path}")
    print(format_rates(low_reason).to_string(index=False))
    print(f"\n按日期规则效果: {date_rule_path}")


if __name__ == "__main__":
    main()
