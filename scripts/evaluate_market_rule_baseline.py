#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from train_5d_market_direction_model import (
    DEFAULT_MARKET_SAMPLE_CSV,
    build_feature_columns,
    market_state,
)
from train_5d_return_model import DEFAULT_OUTPUT_DIR


DEFAULT_TEST_DATES = ",".join(
    [
        "2026-03-16",
        "2026-03-19",
        "2026-03-24",
        "2026-03-27",
        "2026-04-01",
        "2026-04-07",
        "2026-04-10",
        "2026-04-15",
        "2026-04-20",
        "2026-04-24",
        "2026-04-27",
        "2026-04-28",
        "2026-04-29",
        "2026-04-30",
        "2026-05-06",
        "2026-05-07",
    ]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="评估市场方向特征有效性和滚动规则基线")
    parser.add_argument("--market-sample-csv", default=str(DEFAULT_MARKET_SAMPLE_CSV), help="市场5日方向预测样本")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--test-dates", default=DEFAULT_TEST_DATES, help="测试日期，逗号分隔")
    parser.add_argument("--validation-days", type=int, default=40, help="每个锚点日前用于选规则的最近已完成日期数")
    parser.add_argument("--min-train-days", type=int, default=80, help="每个锚点日最少已完成训练日期数")
    parser.add_argument("--target-up-ratio", type=float, default=0.50, help="方向判定阈值")
    return parser.parse_args()


def load_market_samples(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df["卖出日"] = pd.to_datetime(df["卖出日"], errors="coerce")
    df["未来5日上涨比例"] = pd.to_numeric(df["未来5日上涨比例"], errors="coerce")
    return df.sort_values("日期").reset_index(drop=True)


def split_train_validation(
    market_df: pd.DataFrame,
    as_of_date: pd.Timestamp,
    validation_days: int,
    min_train_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_df = market_df[
        (market_df["日期"] < as_of_date)
        & (market_df["卖出日"] <= as_of_date)
        & market_df["未来5日上涨比例"].notna()
    ].copy()
    if len(train_df) < min_train_days:
        raise RuntimeError(f"{as_of_date.strftime('%Y-%m-%d')} 训练日期不足: {len(train_df)}")
    validation_df = train_df.tail(validation_days).copy()
    return train_df, validation_df


def predict_by_rule(value: float, threshold: float, direction: str) -> str:
    if pd.isna(value):
        return "下跌"
    if direction == "high_up":
        return "上涨" if value >= threshold else "下跌"
    return "上涨" if value <= threshold else "下跌"


def evaluate_rule(validation_df: pd.DataFrame, feature: str, threshold: float, direction: str, target_up_ratio: float) -> float:
    values = pd.to_numeric(validation_df[feature], errors="coerce")
    pred = values.map(lambda value: predict_by_rule(value, threshold, direction))
    actual = np.where(validation_df["未来5日上涨比例"] >= target_up_ratio, "上涨", "下跌")
    return float((pred.to_numpy() == actual).mean())


def select_best_rule(
    validation_df: pd.DataFrame,
    feature_cols: list[str],
    target_up_ratio: float,
) -> dict[str, object]:
    best: dict[str, object] = {
        "规则特征": "",
        "规则方向": "",
        "规则阈值": np.nan,
        "验证准确率": -1.0,
    }
    for feature in feature_cols:
        values = pd.to_numeric(validation_df[feature], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if values.nunique() < 5:
            continue
        thresholds = values.quantile([0.15, 0.25, 0.35, 0.50, 0.65, 0.75, 0.85]).dropna().unique()
        for threshold in thresholds:
            for direction in ("high_up", "low_up"):
                accuracy = evaluate_rule(validation_df, feature, float(threshold), direction, target_up_ratio)
                if accuracy > float(best["验证准确率"]):
                    best = {
                        "规则特征": feature,
                        "规则方向": direction,
                        "规则阈值": float(threshold),
                        "验证准确率": accuracy,
                    }
    return best


def feature_effectiveness(train_df: pd.DataFrame, feature_cols: list[str], as_of_date: pd.Timestamp) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    target = pd.to_numeric(train_df["未来5日上涨比例"], errors="coerce")
    label = (target >= 0.50).astype(float)
    for feature in feature_cols:
        values = pd.to_numeric(train_df[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)
        if values.nunique(dropna=True) < 5:
            continue
        corr_ratio = values.corr(target, method="spearman")
        corr_label = values.corr(label, method="spearman")
        rows.append(
            {
                "锚点日期": as_of_date.strftime("%Y-%m-%d"),
                "特征": feature,
                "与未来5日上涨比例相关性": corr_ratio,
                "与市场上涨标签相关性": corr_label,
                "相关性绝对值": max(abs(corr_ratio) if pd.notna(corr_ratio) else 0, abs(corr_label) if pd.notna(corr_label) else 0),
            }
        )
    return pd.DataFrame(rows)


def parse_dates(value: str) -> list[pd.Timestamp]:
    return [pd.to_datetime(item.strip()) for item in value.split(",") if item.strip()]


def main() -> None:
    args = parse_args()
    market_df = load_market_samples(Path(args.market_sample_csv).resolve())
    feature_cols = build_feature_columns(market_df)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    prediction_rows: list[dict[str, object]] = []
    feature_frames: list[pd.DataFrame] = []

    for as_of_date in parse_dates(args.test_dates):
        train_df, validation_df = split_train_validation(
            market_df,
            as_of_date,
            args.validation_days,
            args.min_train_days,
        )
        feature_frames.append(feature_effectiveness(train_df, feature_cols, as_of_date))
        rule = select_best_rule(validation_df, feature_cols, args.target_up_ratio)

        anchor = market_df[market_df["日期"] == as_of_date].copy()
        if anchor.empty:
            raise RuntimeError(f"未找到锚点日期: {as_of_date.strftime('%Y-%m-%d')}")
        value = float(pd.to_numeric(anchor[rule["规则特征"]], errors="coerce").iloc[0])
        pred_direction = predict_by_rule(value, float(rule["规则阈值"]), str(rule["规则方向"]))
        actual_ratio = float(anchor["未来5日上涨比例"].iloc[0]) if pd.notna(anchor["未来5日上涨比例"].iloc[0]) else np.nan
        actual_direction = "上涨" if actual_ratio >= args.target_up_ratio else ("下跌" if pd.notna(actual_ratio) else "")
        prediction_rows.append(
            {
                "锚点日期": as_of_date.strftime("%Y-%m-%d"),
                "训练日期数": len(train_df),
                "验证日期数": len(validation_df),
                "规则特征": rule["规则特征"],
                "规则方向": "高值看涨" if rule["规则方向"] == "high_up" else "低值看涨",
                "规则阈值": rule["规则阈值"],
                "锚点特征值": value,
                "历史验证准确率": rule["验证准确率"],
                "预测市场方向": pred_direction,
                "实际未来5日上涨比例": actual_ratio,
                "实际市场方向": actual_direction,
                "实际市场状态": market_state(actual_ratio),
                "市场方向预测是否准确": int(pred_direction == actual_direction) if actual_direction else np.nan,
            }
        )

    predictions = pd.DataFrame(prediction_rows)
    judged = predictions[predictions["市场方向预测是否准确"].notna()]
    stats = pd.DataFrame(
        [
            {
                "测试日期数": len(predictions),
                "可判卷日期数": len(judged),
                "预测正确日期数": int(judged["市场方向预测是否准确"].sum()),
                "规则基线准确率": f"{judged['市场方向预测是否准确'].mean():.2%}" if len(judged) else "",
                "平均历史验证准确率": f"{predictions['历史验证准确率'].mean():.2%}",
            }
        ]
    )

    feature_eval = pd.concat(feature_frames, ignore_index=True)
    feature_summary = (
        feature_eval.groupby("特征", as_index=False)
        .agg(
            平均相关性绝对值=("相关性绝对值", "mean"),
            最高相关性绝对值=("相关性绝对值", "max"),
            平均收益比例相关性=("与未来5日上涨比例相关性", "mean"),
            平均方向标签相关性=("与市场上涨标签相关性", "mean"),
        )
        .sort_values(["平均相关性绝对值", "最高相关性绝对值"], ascending=False)
        .reset_index(drop=True)
    )

    start_tag = predictions["锚点日期"].iloc[0].replace("-", "")
    end_tag = predictions["锚点日期"].iloc[-1].replace("-", "")
    pred_path = output_dir / f"07_市场方向规则基线预测结果_{start_tag}_{end_tag}.csv"
    stats_path = output_dir / f"07_市场方向规则基线准确率统计_{start_tag}_{end_tag}.csv"
    feature_path = output_dir / f"07_市场方向特征有效性汇总_{start_tag}_{end_tag}.csv"
    predictions.to_csv(pred_path, index=False, encoding="utf-8-sig")
    stats.to_csv(stats_path, index=False, encoding="utf-8-sig")
    feature_summary.to_csv(feature_path, index=False, encoding="utf-8-sig")

    print(f"规则基线预测结果: {pred_path}")
    print(f"规则基线准确率统计: {stats_path}")
    print(f"特征有效性汇总: {feature_path}")
    print(predictions.to_string(index=False))
    print(stats.to_string(index=False))
    print(feature_summary.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
