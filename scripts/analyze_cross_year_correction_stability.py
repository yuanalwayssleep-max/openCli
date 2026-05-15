#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from train_5d_return_model import DEFAULT_OUTPUT_DIR


DEFAULT_DATE_RANGES = "20250701_20251210,20260202_20260415,20260316_20260507"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="跨年份分析市场风险修正规则稳定性")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="skill输出目录")
    parser.add_argument("--date-ranges", default=DEFAULT_DATE_RANGES, help="10_个股预测结果_市场风险修正文件后缀，逗号分隔")
    return parser.parse_args()


def pct(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:.2%}"


def batch_name(date_range: str) -> str:
    start = date_range.split("_", 1)[0]
    if start.startswith("2025"):
        return "2025验证集"
    if start.startswith("2026"):
        return "2026验证集"
    return f"{start[:4]}验证集"


def load_frames(output_dir: Path, date_ranges: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for item in date_ranges:
        path = output_dir / f"10_个股预测结果_市场风险修正_{item}.csv"
        if not path.exists():
            raise FileNotFoundError(f"缺少修正明细文件: {path}")
        frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"代码": str})
        frame["测试区间"] = item
        frame["测试批次"] = batch_name(item)
        frame["锚点年份"] = pd.to_datetime(frame["锚点日期"]).dt.year.astype(str)
        frames.append(frame)
    df = pd.concat(frames, ignore_index=True)
    df["是否噪声样本"] = df["是否噪声样本"].astype(bool)
    df["是否发生修正"] = df["是否发生修正"].astype(int)
    df["原始预测是否准确"] = df["原始预测是否准确"].astype(int)
    df["修正后预测是否准确"] = df["修正后预测是否准确"].astype(int)
    df["修正效果"] = df["修正后预测是否准确"] - df["原始预测是否准确"]
    df["原始错判为上涨"] = ((df["原始预测涨跌"] == "上涨") & (df["实际涨跌"] == "下跌")).astype(int)
    df["修正后错判为上涨"] = ((df["修正后预测涨跌"] == "上涨") & (df["实际涨跌"] == "下跌")).astype(int)
    df["原始错判为下跌"] = ((df["原始预测涨跌"] == "下跌") & (df["实际涨跌"] == "上涨")).astype(int)
    df["修正后错判为下跌"] = ((df["修正后预测涨跌"] == "下跌") & (df["实际涨跌"] == "上涨")).astype(int)
    return df


def summarize(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    denoised = df.loc[~df["是否噪声样本"]]
    base = (
        df.groupby(group_cols, dropna=False)
        .agg(
            日期数=("锚点日期", "nunique"),
            股票预测数=("代码", "count"),
            噪声样本数=("是否噪声样本", "sum"),
            发生修正数=("是否发生修正", "sum"),
            原始正确数=("原始预测是否准确", "sum"),
            修正后正确数=("修正后预测是否准确", "sum"),
            修正净增正确数=("修正效果", "sum"),
            原始错判为上涨数=("原始错判为上涨", "sum"),
            修正后错判为上涨数=("修正后错判为上涨", "sum"),
            原始错判为下跌数=("原始错判为下跌", "sum"),
            修正后错判为下跌数=("修正后错判为下跌", "sum"),
            平均预测上涨概率=("预测上涨概率", "mean"),
            平均实际5日涨跌幅=("5日后的实际涨跌幅", "mean"),
        )
        .reset_index()
    )
    denoised_base = (
        denoised.groupby(group_cols, dropna=False)
        .agg(
            降噪后股票预测数=("代码", "count"),
            降噪后发生修正数=("是否发生修正", "sum"),
            降噪后原始正确数=("原始预测是否准确", "sum"),
            降噪后修正后正确数=("修正后预测是否准确", "sum"),
            降噪后修正净增正确数=("修正效果", "sum"),
        )
        .reset_index()
    )
    result = base.merge(denoised_base, on=group_cols, how="left")
    for col in ["降噪后股票预测数", "降噪后发生修正数", "降噪后原始正确数", "降噪后修正后正确数", "降噪后修正净增正确数"]:
        result[col] = result[col].fillna(0).astype(int)

    result["原始准确率"] = result["原始正确数"] / result["股票预测数"]
    result["修正后准确率"] = result["修正后正确数"] / result["股票预测数"]
    result["准确率变化百分点"] = (result["修正后准确率"] - result["原始准确率"]) * 100
    result["降噪后原始准确率"] = result["降噪后原始正确数"] / result["降噪后股票预测数"].replace(0, pd.NA)
    result["降噪后修正后准确率"] = result["降噪后修正后正确数"] / result["降噪后股票预测数"].replace(0, pd.NA)
    result["降噪后准确率变化百分点"] = (result["降噪后修正后准确率"] - result["降噪后原始准确率"]) * 100
    result["修正覆盖率"] = result["发生修正数"] / result["股票预测数"]
    result["降噪后修正覆盖率"] = result["降噪后发生修正数"] / result["降噪后股票预测数"].replace(0, pd.NA)

    pct_cols = [
        "原始准确率",
        "修正后准确率",
        "降噪后原始准确率",
        "降噪后修正后准确率",
        "修正覆盖率",
        "降噪后修正覆盖率",
        "平均预测上涨概率",
        "平均实际5日涨跌幅",
    ]
    for col in pct_cols:
        result[col] = result[col].map(pct)
    for col in ["准确率变化百分点", "降噪后准确率变化百分点"]:
        result[col] = result[col].round(2)
    return result


def make_rule_advice(rule_year: pd.DataFrame) -> pd.DataFrame:
    changed = rule_year.loc[rule_year["发生修正数"] > 0].copy()
    if changed.empty:
        return pd.DataFrame(columns=["修正原因", "建议动作", "原因"])

    pivot = changed.pivot_table(
        index="修正原因",
        columns="锚点年份",
        values=["降噪后发生修正数", "降噪后修正净增正确数", "降噪后准确率变化百分点"],
        aggfunc="sum",
        fill_value=0,
    )
    rows: list[dict[str, str]] = []
    for reason in pivot.index:
        per_year = changed.loc[changed["修正原因"] == reason].set_index("锚点年份")
        years = sorted(per_year.index.astype(str).tolist())
        has_2025 = "2025" in years
        has_2026 = "2026" in years
        gains = per_year["降噪后修正净增正确数"].astype(float)
        counts = per_year["降噪后发生修正数"].astype(float)
        weak_years = [year for year, gain in gains.items() if gain < 0]
        tiny_years = [year for year, count in counts.items() if count < 20]

        if weak_years:
            action = "暂停或加条件"
            reason_text = f"{','.join(weak_years)} 降噪后净增正确数为负"
        elif has_2025 and has_2026 and counts.min() >= 20 and gains.min() > 0:
            action = "保留"
            reason_text = "跨年份都有样本且降噪后净增正确数为正"
        elif not has_2025 and has_2026:
            action = "保守保留，需补2025覆盖"
            reason_text = "只在2026触发，缺少2025稳定性证据"
        elif has_2025 and not has_2026:
            action = "观察"
            reason_text = "只在2025触发，缺少2026稳定性证据"
        elif tiny_years:
            action = "观察"
            reason_text = f"{','.join(tiny_years)} 降噪后触发样本少于20"
        else:
            action = "保守保留"
            reason_text = "未发现负增益，但覆盖或年份证据不足"
        rows.append({"修正原因": reason, "建议动作": action, "原因": reason_text})
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    date_ranges = [item.strip() for item in args.date_ranges.split(",") if item.strip()]
    df = load_frames(output_dir, date_ranges)

    suffix = "_".join(date_ranges)
    by_year = summarize(df, ["锚点年份"])
    by_year_state = summarize(df, ["锚点年份", "实际市场状态"])
    by_year_risk = summarize(df, ["锚点年份", "市场风险标签"])
    by_rule_year = summarize(df, ["修正原因", "锚点年份"])
    by_rule_state = summarize(df, ["修正原因", "锚点年份", "实际市场状态"])
    by_date = summarize(df, ["锚点日期", "锚点年份", "实际市场状态", "市场风险标签"])
    advice = make_rule_advice(by_rule_year)

    paths = {
        "by_year": output_dir / f"12_跨年份总体准确率_{suffix}.csv",
        "by_year_state": output_dir / f"12_跨年份按市场状态准确率_{suffix}.csv",
        "by_year_risk": output_dir / f"12_跨年份按市场风险标签准确率_{suffix}.csv",
        "by_rule_year": output_dir / f"12_跨年份按修正原因稳定性_{suffix}.csv",
        "by_rule_state": output_dir / f"12_跨年份按修正原因和市场状态_{suffix}.csv",
        "by_date": output_dir / f"12_跨年份按日期准确率_{suffix}.csv",
        "advice": output_dir / f"12_修正规则投用建议_{suffix}.csv",
    }
    by_year.to_csv(paths["by_year"], index=False, encoding="utf-8-sig")
    by_year_state.to_csv(paths["by_year_state"], index=False, encoding="utf-8-sig")
    by_year_risk.to_csv(paths["by_year_risk"], index=False, encoding="utf-8-sig")
    by_rule_year.to_csv(paths["by_rule_year"], index=False, encoding="utf-8-sig")
    by_rule_state.to_csv(paths["by_rule_state"], index=False, encoding="utf-8-sig")
    by_date.to_csv(paths["by_date"], index=False, encoding="utf-8-sig")
    advice.to_csv(paths["advice"], index=False, encoding="utf-8-sig")

    print("跨年份总体准确率")
    print(by_year.to_string(index=False))
    print("\n修正规则投用建议")
    print(advice.to_string(index=False))
    print("\n输出文件")
    for path in paths.values():
        print(path)


if __name__ == "__main__":
    main()
