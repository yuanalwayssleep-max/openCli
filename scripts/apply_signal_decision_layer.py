#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="在修正后方向预测上增加观望/出手决策层")
    parser.add_argument("--detail-csv", required=True, help="10_个股预测结果_市场风险修正明细CSV")
    parser.add_argument("--output-prefix", required=True, help="输出文件前缀，不含扩展名")
    parser.add_argument(
        "--decision-policy",
        choices=["legacy", "v16", "v17_confidence", "v18_confidence_topn", "v17_daily_quota"],
        default="v16",
        help="信号决策策略：legacy=旧观望规则；v16=高置信低覆盖出手层；v17_confidence=概率/修正原因低覆盖出手层；v18_confidence_topn=每日限额版v17；v17_daily_quota=每日低配额出手层",
    )
    parser.add_argument("--daily-min-signals", type=int, default=2, help="v17每日最少出手数")
    parser.add_argument("--daily-max-signals", type=int, default=10, help="v17/v18每日最多出手数")
    return parser.parse_args()


def pct(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:.2%}"


def add_legacy_decision_layer(df: pd.DataFrame) -> pd.DataFrame:
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


def add_v16_decision_layer(df: pd.DataFrame) -> pd.DataFrame:
    """高置信低覆盖出手层。

    v16不追求全股票覆盖，只在跨月回测中胜率更稳定的环境出手。
    规则只使用锚点日已知字段和模型预测概率，不使用未来标签。
    """
    out = df.copy()
    prob = pd.to_numeric(out["预测上涨概率"], errors="coerce")
    confidence = (prob - 0.5).abs()
    breadth = pd.to_numeric(out.get("当日上涨比例"), errors="coerce")
    zz1000_20d_ret = pd.to_numeric(out.get("中证1000_20日涨跌幅"), errors="coerce")
    pred_up = out["修正后预测涨跌"].eq("上涨")

    overheat_up_continuation = (
        pred_up
        & out["市场风险标签"].eq("过热回落高")
        & (confidence >= 0.15)
        & (breadth >= 0.70)
        & (zz1000_20d_ret >= 0.065)
    )
    weak_repair_up = (
        pred_up
        & out["市场风险标签"].eq("弱势延续高")
        & (confidence >= 0.15)
        & (breadth >= 0.35)
    )
    panic_weak_rebound_up = (
        pred_up
        & out["市场风险标签"].eq("恐慌释放高+弱势延续高")
        & (confidence >= 0.15)
    )

    out["信号动作"] = "观望"
    out["观望原因"] = "v16未满足高置信出手条件"
    out["信号规则"] = ""

    out.loc[overheat_up_continuation, "信号动作"] = "出手"
    out.loc[overheat_up_continuation, "观望原因"] = ""
    out.loc[overheat_up_continuation, "信号规则"] = "v16_过热强势延续上涨"

    out.loc[weak_repair_up, "信号动作"] = "出手"
    out.loc[weak_repair_up, "观望原因"] = ""
    out.loc[weak_repair_up, "信号规则"] = "v16_弱势修复上涨"

    out.loc[panic_weak_rebound_up, "信号动作"] = "出手"
    out.loc[panic_weak_rebound_up, "观望原因"] = ""
    out.loc[panic_weak_rebound_up, "信号规则"] = "v16_恐慌弱势反抽上涨"
    return out


def add_v17_confidence_layer(df: pd.DataFrame) -> pd.DataFrame:
    """概率/修正原因低覆盖出手层。

    v16在部分月份过严，容易完全不出手。v17_confidence保留低覆盖原则，
    但增加两类更可解释的出手条件：高上涨概率，以及v15识别出的恐慌洗盘修正。
    """
    out = add_v16_decision_layer(df)
    prob = pd.to_numeric(out["预测上涨概率"], errors="coerce")
    industry_up = pd.to_numeric(out.get("行业上涨比例"), errors="coerce")
    pred_up = out["修正后预测涨跌"].eq("上涨")
    risk_label = out["市场风险标签"].astype(str)
    correction_reason = out.get("修正原因", pd.Series("", index=out.index)).fillna("").astype(str)

    high_prob_up = pred_up & (prob >= 0.70)
    strong_industry_up = (
        pred_up
        & (prob >= 0.62)
        & risk_label.isin(["常规环境", "过热回落高"])
        & (industry_up >= 0.50)
    )
    panic_wash_up = (
        pred_up
        & risk_label.eq("恐慌释放高")
        & correction_reason.str.contains("上升趋势中恐慌洗盘", regex=False)
    )

    out.loc[high_prob_up, "信号动作"] = "出手"
    out.loc[high_prob_up, "观望原因"] = ""
    out.loc[high_prob_up, "信号规则"] = "v17_高概率上涨"

    out.loc[strong_industry_up, "信号动作"] = "出手"
    out.loc[strong_industry_up, "观望原因"] = ""
    out.loc[strong_industry_up, "信号规则"] = "v17_行业共振上涨"

    out.loc[panic_wash_up, "信号动作"] = "出手"
    out.loc[panic_wash_up, "观望原因"] = ""
    out.loc[panic_wash_up, "信号规则"] = "v17_恐慌洗盘修正上涨"
    return out


def add_v18_confidence_topn_layer(df: pd.DataFrame, daily_max: int) -> pd.DataFrame:
    """每日限额版v17。

    先用v17_confidence生成候选，再按规则优先级和上涨概率排序，每天最多保留daily_max个信号。
    """
    if daily_max <= 0:
        raise ValueError("v18要求 daily-max-signals > 0")

    out = add_v17_confidence_layer(df)
    candidates = out[out["信号动作"].eq("出手")].copy()
    out["信号动作"] = "观望"
    out["观望原因"] = "v18未入选每日TopN"

    if candidates.empty:
        out["信号规则"] = ""
        return out

    priority = {
        "v17_高概率上涨": 1,
        "v17_行业共振上涨": 2,
        "v17_恐慌洗盘修正上涨": 3,
        "v16_过热强势延续上涨": 4,
        "v16_弱势修复上涨": 5,
        "v16_恐慌弱势反抽上涨": 6,
    }
    candidates["_规则优先级"] = candidates["信号规则"].map(priority).fillna(99)
    candidates["_预测上涨概率"] = pd.to_numeric(candidates["预测上涨概率"], errors="coerce")
    selected_indices: list[int] = []
    for _, day in candidates.groupby("锚点日期", sort=True):
        selected = day.sort_values(["_规则优先级", "_预测上涨概率"], ascending=[True, False]).head(daily_max)
        selected_indices.extend(list(selected.index))

    out.loc[selected_indices, "信号动作"] = "出手"
    out.loc[selected_indices, "观望原因"] = ""
    out.loc[selected_indices, "信号规则"] = candidates.loc[selected_indices, "信号规则"]
    out.loc[out["信号动作"].eq("观望"), "信号规则"] = ""
    return out


def add_v17_daily_quota_layer(df: pd.DataFrame, daily_min: int, daily_max: int) -> pd.DataFrame:
    """每日低配额出手层。

    先选v16高胜率信号；如果当天不足daily_min，再用全市场最高置信度样本补足。
    """
    if daily_min < 0 or daily_max <= 0 or daily_min > daily_max:
        raise ValueError("v17要求 0 <= daily-min-signals <= daily-max-signals 且 daily-max-signals > 0")

    out = add_v16_decision_layer(df)
    out["_v16信号规则"] = out["信号规则"].astype(str)
    prob = pd.to_numeric(out["预测上涨概率"], errors="coerce")
    out["_信号置信度"] = (prob - 0.5).abs()
    out["信号动作"] = "观望"
    out["观望原因"] = "v17未入选每日出手配额"
    out["信号规则"] = ""

    selected_indices: list[int] = []
    for _, day in out.groupby("锚点日期", sort=True):
        v16_candidates = day[day["_v16信号规则"].str.startswith("v16_")].copy()
        v16_selected = v16_candidates.sort_values(
            ["预测上涨概率", "_信号置信度"],
            ascending=[False, False],
        ).head(daily_max)
        chosen = list(v16_selected.index)

        if len(chosen) < daily_min:
            remaining = day.drop(index=chosen, errors="ignore")
            fill_count = daily_min - len(chosen)
            fillers = remaining.sort_values("_信号置信度", ascending=False).head(fill_count)
            chosen.extend(list(fillers.index))

        selected_indices.extend(chosen)

    out.loc[selected_indices, "信号动作"] = "出手"
    out.loc[selected_indices, "信号规则"] = out.loc[selected_indices, "_v16信号规则"]
    empty_rule = out.loc[selected_indices, "信号规则"].astype(str).eq("")
    filler_indices = out.loc[selected_indices].loc[empty_rule].index
    out.loc[filler_indices, "信号规则"] = "v17_每日最高置信补充"
    out.loc[selected_indices, "观望原因"] = ""
    return out.drop(columns=["_信号置信度", "_v16信号规则"], errors="ignore")


def add_decision_layer(df: pd.DataFrame, policy: str, daily_min: int, daily_max: int) -> pd.DataFrame:
    if policy == "legacy":
        return add_legacy_decision_layer(df)
    if policy == "v16":
        return add_v16_decision_layer(df)
    if policy == "v17_confidence":
        return add_v17_confidence_layer(df)
    if policy == "v18_confidence_topn":
        return add_v18_confidence_topn_layer(df, daily_max)
    if policy == "v17_daily_quota":
        return add_v17_daily_quota_layer(df, daily_min, daily_max)
    raise ValueError(f"未知信号决策策略: {policy}")


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
    out = add_decision_layer(df, args.decision_policy, args.daily_min_signals, args.daily_max_signals)

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
