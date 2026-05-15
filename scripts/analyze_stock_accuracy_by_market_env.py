#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from train_5d_return_model import DEFAULT_OUTPUT_DIR


DEFAULT_DATES = ",".join(
    [
        "20260316",
        "20260319",
        "20260324",
        "20260327",
        "20260401",
        "20260407",
        "20260410",
        "20260415",
        "20260420",
        "20260424",
        "20260427",
        "20260428",
        "20260429",
        "20260430",
        "20260506",
        "20260507",
    ]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按市场环境统计个股5日方向模型准确率")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="skill输出目录")
    parser.add_argument("--dates", default=DEFAULT_DATES, help="预测结果日期标签，逗号分隔，格式YYYYMMDD")
    return parser.parse_args()


def risk_label(row: pd.Series) -> str:
    flags: list[str] = []
    if row.get("恐慌释放特征", 0) >= 3:
        flags.append("恐慌释放高")
    if row.get("过热回落风险特征", 0) >= 3:
        flags.append("过热回落高")
    if row.get("弱势延续风险特征", 0) >= 3:
        flags.append("弱势延续高")
    return "+".join(flags) if flags else "常规环境"


def summarize(merged: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    stats = (
        merged.groupby(group_cols, dropna=False)
        .agg(
            股票预测数=("代码", "count"),
            预测正确数=("涨跌预测是否准确", "sum"),
            预测上涨数=("预测涨跌", lambda s: (s == "上涨").sum()),
            预测下跌数=("预测涨跌", lambda s: (s == "下跌").sum()),
            实际上涨数=("实际涨跌", lambda s: (s == "上涨").sum()),
            实际下跌数=("实际涨跌", lambda s: (s == "下跌").sum()),
            实际下跌却预测上涨数=("错误类型", lambda s: (s == "实际下跌却预测上涨").sum()),
            实际上涨却预测下跌数=("错误类型", lambda s: (s == "实际上涨却预测下跌").sum()),
        )
        .reset_index()
    )
    stats["个股方向准确率"] = (stats["预测正确数"] / stats["股票预测数"]).map(lambda x: f"{x:.2%}")
    return stats


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    dates = [item.strip() for item in args.dates.split(",") if item.strip()]

    market = pd.read_csv(output_dir / "00_市场5日方向预测样本.csv", encoding="utf-8-sig")
    market_cols = [
        "日期",
        "未来5日上涨比例",
        "未来5日市场方向",
        "未来5日市场状态",
        "恐慌释放特征",
        "过热回落风险特征",
        "弱势延续风险特征",
        "连续弱势天数",
        "连续强势天数",
        "连续下跌天数",
        "连续上涨天数",
        "当日上涨比例",
        "当日平均涨跌幅",
        "上涨行业比例",
        "当日大跌比例_3pct",
        "当日大涨比例_3pct",
    ]
    market = market[[col for col in market_cols if col in market.columns]].rename(
        columns={
            "未来5日上涨比例": "市场未来5日上涨比例",
            "未来5日市场方向": "实际市场方向",
            "未来5日市场状态": "实际市场状态",
        }
    )

    frames: list[pd.DataFrame] = []
    for date_tag in dates:
        path = output_dir / f"03_每只股票方向预测结果_核心特征_{date_tag}.csv"
        if not path.exists():
            raise FileNotFoundError(f"缺少个股预测结果: {path}")
        frames.append(pd.read_csv(path, encoding="utf-8-sig", dtype={"代码": str}))
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.merge(market, left_on="锚点日期", right_on="日期", how="left").drop(columns=["日期_y"], errors="ignore")
    if "日期_x" in merged.columns:
        merged = merged.rename(columns={"日期_x": "日期"})

    merged["市场风险标签"] = merged.apply(risk_label, axis=1)
    merged["错误类型"] = np.where(
        merged["涨跌预测是否准确"] == 1,
        "预测正确",
        np.where(
            (merged["预测涨跌"] == "上涨") & (merged["实际涨跌"] == "下跌"),
            "实际下跌却预测上涨",
            "实际上涨却预测下跌",
        ),
    )

    start_tag = dates[0]
    end_tag = dates[-1]
    detail_path = output_dir / f"09_个股预测结果_附市场环境标签_{start_tag}_{end_tag}.csv"
    state_path = output_dir / f"09_按实际市场状态统计个股预测准确率_{start_tag}_{end_tag}.csv"
    risk_path = output_dir / f"09_按市场风险标签统计个股预测准确率_{start_tag}_{end_tag}.csv"
    date_path = output_dir / f"09_按日期与市场环境统计个股预测准确率_{start_tag}_{end_tag}.csv"

    by_state = summarize(merged, ["实际市场状态"]).sort_values("股票预测数", ascending=False)
    by_risk = summarize(merged, ["市场风险标签"]).sort_values("股票预测数", ascending=False)
    by_date = summarize(merged, ["锚点日期", "实际市场状态", "市场风险标签"]).sort_values("锚点日期")

    merged.to_csv(detail_path, index=False, encoding="utf-8-sig")
    by_state.to_csv(state_path, index=False, encoding="utf-8-sig")
    by_risk.to_csv(risk_path, index=False, encoding="utf-8-sig")
    by_date.to_csv(date_path, index=False, encoding="utf-8-sig")

    print(f"明细: {detail_path}")
    print(f"按实际市场状态: {state_path}")
    print(by_state.to_string(index=False))
    print(f"按市场风险标签: {risk_path}")
    print(by_risk.to_string(index=False))
    print(f"按日期与市场环境: {date_path}")
    print(by_date.to_string(index=False))


if __name__ == "__main__":
    main()
