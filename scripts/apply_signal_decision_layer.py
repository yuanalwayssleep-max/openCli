#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="在修正后方向预测上增加观望/出手决策层")
    parser.add_argument("--detail-csv", required=True, help="10_个股预测结果_市场风险修正明细CSV")
    parser.add_argument("--output-prefix", required=True, help="输出文件前缀，不含扩展名")
    return parser.parse_args()


def pct(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:.2%}"


def add_decision_layer(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    weak_rebound_uncertain = (
        out["市场风险标签"].eq("弱势延续高")
        & (out["当日上涨比例"] >= 0.70)
        & (out["当日平均涨跌幅"] >= 1.0)
        & (out["上证指数_20日涨跌幅"] < 0)
        & (out["中证500_20日涨跌幅"] < 0)
    )
    weak_down_range_uncertain = (
        out["市场风险标签"].eq("弱势延续高")
        & (out["当日上涨比例"] < 0.25)
        & (out["当日平均涨跌幅"] < -1.0)
        & (out["连续弱势天数"] <= 1)
        & ((out["行业强跌比例_1pct_近5日变化"] < 0) | (out["当日平均涨跌幅_近5日变化"] > 0))
    )

    out["信号动作"] = "出手"
    out["观望原因"] = ""
    out.loc[weak_rebound_uncertain, "信号动作"] = "观望"
    out.loc[weak_rebound_uncertain, "观望原因"] = "弱势趋势强反弹后方向分歧，观望"
    out.loc[weak_down_range_uncertain, "信号动作"] = "观望"
    out.loc[weak_down_range_uncertain, "观望原因"] = "弱势大跌但未继续恶化，方向分歧，观望"
    return out


def summarize(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    tradable = df[df["信号动作"] == "出手"].copy()
    total = (
        df.groupby(group_cols, dropna=False)
        .agg(
            总股票数=("代码", "count"),
            观望数=("信号动作", lambda s: (s == "观望").sum()),
        )
        .reset_index()
    )
    if tradable.empty:
        total["出手数"] = 0
        total["出手准确数"] = 0
        total["出手准确率"] = ""
        total["覆盖率"] = "0.00%"
        return total

    hit = (
        tradable.groupby(group_cols, dropna=False)
        .agg(
            出手数=("代码", "count"),
            出手准确数=("修正后预测是否准确", "sum"),
            出手上涨数=("修正后预测涨跌", lambda s: (s == "上涨").sum()),
            出手下跌数=("修正后预测涨跌", lambda s: (s == "下跌").sum()),
            实际上涨数=("实际涨跌", lambda s: (s == "上涨").sum()),
            实际下跌数=("实际涨跌", lambda s: (s == "下跌").sum()),
        )
        .reset_index()
    )
    out = total.merge(hit, on=group_cols, how="left")
    for col in ["出手数", "出手准确数", "出手上涨数", "出手下跌数", "实际上涨数", "实际下跌数"]:
        out[col] = out[col].fillna(0).astype(int)
    out["覆盖率"] = out.apply(lambda row: pct(row["出手数"] / row["总股票数"]) if row["总股票数"] else "", axis=1)
    out["出手准确率"] = out.apply(lambda row: pct(row["出手准确数"] / row["出手数"]) if row["出手数"] else "", axis=1)
    return out


def main() -> None:
    args = parse_args()
    detail_path = Path(args.detail_csv).resolve()
    output_prefix = Path(args.output_prefix).resolve()
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(detail_path, encoding="utf-8-sig", dtype={"代码": str})
    out = add_decision_layer(df)

    detail_out = output_prefix.with_name(output_prefix.name + "_信号决策明细.csv")
    total_out = output_prefix.with_name(output_prefix.name + "_信号决策总体.csv")
    date_out = output_prefix.with_name(output_prefix.name + "_信号决策按日期.csv")
    reason_out = output_prefix.with_name(output_prefix.name + "_观望原因统计.csv")

    total = pd.DataFrame(
        [
            {
                "总股票数": len(out),
                "出手数": int((out["信号动作"] == "出手").sum()),
                "观望数": int((out["信号动作"] == "观望").sum()),
                "覆盖率": pct((out["信号动作"] == "出手").mean()),
                "修正后全量准确率": pct(out["修正后预测是否准确"].mean()),
                "出手准确率": pct(out.loc[out["信号动作"] == "出手", "修正后预测是否准确"].mean()),
                "观望样本原本准确率": pct(out.loc[out["信号动作"] == "观望", "修正后预测是否准确"].mean()),
            }
        ]
    )
    by_date = summarize(out, ["锚点日期", "实际市场状态", "市场风险标签"])
    reason = summarize(out[out["信号动作"] == "观望"], ["观望原因"])

    out.to_csv(detail_out, index=False, encoding="utf-8-sig")
    total.to_csv(total_out, index=False, encoding="utf-8-sig")
    by_date.to_csv(date_out, index=False, encoding="utf-8-sig")
    reason.to_csv(reason_out, index=False, encoding="utf-8-sig")

    print(f"信号决策总体: {total_out}")
    print(total.to_string(index=False))
    print(f"\n信号决策按日期: {date_out}")
    print(by_date.to_string(index=False))
    print(f"\n观望原因统计: {reason_out}")
    print(reason.to_string(index=False))
    print(f"\n信号决策明细: {detail_out}")


if __name__ == "__main__":
    main()
