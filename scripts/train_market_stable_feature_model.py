#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

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
    parser = argparse.ArgumentParser(description="稳定特征池市场5日方向模型")
    parser.add_argument("--market-sample-csv", default=str(DEFAULT_MARKET_SAMPLE_CSV), help="市场5日方向预测样本")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--test-dates", default=DEFAULT_TEST_DATES, help="测试日期，逗号分隔")
    parser.add_argument("--min-train-days", type=int, default=80, help="最少训练日期数")
    parser.add_argument("--feature-top-n", type=int, default=30, help="每个锚点日最多保留的稳定特征数")
    parser.add_argument("--target-up-ratio", type=float, default=0.50, help="方向判定阈值")
    parser.add_argument("--neutral-low", type=float, default=0.45, help="训练时弱化震荡样本下界")
    parser.add_argument("--neutral-high", type=float, default=0.55, help="训练时弱化震荡样本上界")
    parser.add_argument("--windows", default="60,90,120", help="稳定性评估窗口，逗号分隔")
    return parser.parse_args()


def load_market_samples(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df["卖出日"] = pd.to_datetime(df["卖出日"], errors="coerce")
    df["未来5日上涨比例"] = pd.to_numeric(df["未来5日上涨比例"], errors="coerce")
    return df.sort_values("日期").reset_index(drop=True)


def parse_dates(value: str) -> list[pd.Timestamp]:
    return [pd.to_datetime(item.strip()) for item in value.split(",") if item.strip()]


def parse_windows(value: str) -> list[int]:
    windows = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not windows:
        raise ValueError("--windows不能为空")
    return windows


def completed_train(market_df: pd.DataFrame, as_of_date: pd.Timestamp) -> pd.DataFrame:
    return market_df[
        (market_df["日期"] < as_of_date)
        & (market_df["卖出日"] <= as_of_date)
        & market_df["未来5日上涨比例"].notna()
    ].copy()


def select_stable_features(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    windows: list[int],
    top_n: int,
) -> tuple[list[str], pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for feature in feature_cols:
        signs: list[float] = []
        abs_corrs: list[float] = []
        for window in windows:
            part = train_df.tail(window)
            values = pd.to_numeric(part[feature], errors="coerce").replace([np.inf, -np.inf], np.nan)
            target = pd.to_numeric(part["未来5日上涨比例"], errors="coerce")
            if values.nunique(dropna=True) < 5:
                continue
            corr = values.corr(target, method="spearman")
            if pd.isna(corr) or corr == 0:
                continue
            signs.append(float(np.sign(corr)))
            abs_corrs.append(abs(float(corr)))
        if len(abs_corrs) < 2:
            continue
        positive = sum(1 for sign in signs if sign > 0)
        negative = sum(1 for sign in signs if sign < 0)
        consistency = max(positive, negative) / len(signs)
        if consistency < 0.67:
            continue
        rows.append(
            {
                "特征": feature,
                "平均相关性绝对值": float(np.mean(abs_corrs)),
                "最低相关性绝对值": float(np.min(abs_corrs)),
                "方向一致率": consistency,
                "窗口数": len(abs_corrs),
                "相关方向": "正相关" if positive >= negative else "负相关",
            }
        )
    scored = pd.DataFrame(rows)
    if scored.empty:
        return [], scored
    scored = scored.sort_values(
        ["方向一致率", "平均相关性绝对值", "最低相关性绝对值"],
        ascending=False,
    ).reset_index(drop=True)
    return scored.head(top_n)["特征"].tolist(), scored


def fit_predict_one_window(
    train_df: pd.DataFrame,
    anchor_df: pd.DataFrame,
    features: list[str],
    neutral_low: float,
    neutral_high: float,
    target_up_ratio: float,
) -> tuple[float, float, int]:
    strong = train_df[
        (train_df["未来5日上涨比例"] <= neutral_low)
        | (train_df["未来5日上涨比例"] >= neutral_high)
    ].copy()
    fit_df = strong if len(strong) >= 50 and strong["未来5日上涨比例"].ge(target_up_ratio).nunique() > 1 else train_df
    fit_df["方向标签"] = (fit_df["未来5日上涨比例"] >= target_up_ratio).astype(int)

    X = fit_df[features].replace([np.inf, -np.inf], np.nan)
    y = fit_df["方向标签"].astype(int)
    clf = make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        LogisticRegression(max_iter=2000, class_weight="balanced", C=0.5, random_state=42),
    )
    clf.fit(X, y)

    reg = make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        Ridge(alpha=3.0),
    )
    reg.fit(X, fit_df["未来5日上涨比例"].astype(float))

    X_anchor = anchor_df[features].replace([np.inf, -np.inf], np.nan)
    prob = float(clf.predict_proba(X_anchor)[:, 1][0])
    ratio = float(np.clip(reg.predict(X_anchor)[0], 0.0, 1.0))
    return prob, ratio, len(fit_df)


def predict_one(
    market_df: pd.DataFrame,
    as_of_date: pd.Timestamp,
    feature_cols: list[str],
    windows: list[int],
    top_n: int,
    min_train_days: int,
    neutral_low: float,
    neutral_high: float,
    target_up_ratio: float,
) -> tuple[dict[str, object], pd.DataFrame]:
    train_df = completed_train(market_df, as_of_date)
    if len(train_df) < min_train_days:
        raise RuntimeError(f"{as_of_date.strftime('%Y-%m-%d')} 训练日期不足: {len(train_df)}")
    anchor_df = market_df[market_df["日期"] == as_of_date].copy()
    if anchor_df.empty:
        raise RuntimeError(f"未找到锚点日期: {as_of_date.strftime('%Y-%m-%d')}")

    features, feature_score = select_stable_features(train_df, feature_cols, windows, top_n)
    if not features:
        raise RuntimeError(f"{as_of_date.strftime('%Y-%m-%d')} 未筛出稳定特征")

    probs: list[float] = []
    ratios: list[float] = []
    train_sizes: list[int] = []
    for window in windows:
        window_df = train_df.tail(window).copy()
        prob, ratio, train_size = fit_predict_one_window(
            window_df,
            anchor_df,
            features,
            neutral_low,
            neutral_high,
            target_up_ratio,
        )
        probs.append(prob)
        ratios.append(ratio)
        train_sizes.append(train_size)

    pred_prob = float(np.mean(probs))
    pred_ratio = float(np.mean(ratios))
    blended_ratio = float(np.clip(0.55 * pred_ratio + 0.45 * pred_prob, 0.0, 1.0))
    pred_direction = "上涨" if blended_ratio >= target_up_ratio else "下跌"
    pred_state = market_state(blended_ratio)

    actual_ratio_value = anchor_df["未来5日上涨比例"].iloc[0]
    actual_ratio = float(actual_ratio_value) if pd.notna(actual_ratio_value) else np.nan
    actual_direction = "上涨" if actual_ratio >= target_up_ratio else ("下跌" if pd.notna(actual_ratio) else "")
    is_correct = int(pred_direction == actual_direction) if actual_direction else np.nan

    row = {
        "锚点日期": as_of_date.strftime("%Y-%m-%d"),
        "训练日期数": len(train_df),
        "模型实际训练日期数": int(np.mean(train_sizes)),
        "稳定特征数": len(features),
        "稳定特征Top10": "|".join(features[:10]),
        "预测上涨概率": pred_prob,
        "预测未来5日上涨比例": pred_ratio,
        "融合预测上涨比例": blended_ratio,
        "预测市场方向": pred_direction,
        "预测市场状态": pred_state,
        "实际未来5日上涨比例": actual_ratio,
        "实际市场方向": actual_direction,
        "实际市场状态": market_state(actual_ratio),
        "市场方向预测是否准确": is_correct,
    }
    feature_score.insert(0, "锚点日期", as_of_date.strftime("%Y-%m-%d"))
    return row, feature_score


def main() -> None:
    args = parse_args()
    market_df = load_market_samples(Path(args.market_sample_csv).resolve())
    feature_cols = build_feature_columns(market_df)
    windows = parse_windows(args.windows)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    feature_frames: list[pd.DataFrame] = []
    for as_of_date in parse_dates(args.test_dates):
        row, feature_score = predict_one(
            market_df,
            as_of_date,
            feature_cols,
            windows,
            args.feature_top_n,
            args.min_train_days,
            args.neutral_low,
            args.neutral_high,
            args.target_up_ratio,
        )
        rows.append(row)
        feature_frames.append(feature_score)

    result = pd.DataFrame(rows)
    judged = result[result["市场方向预测是否准确"].notna()]
    stats = pd.DataFrame(
        [
            {
                "测试日期数": len(result),
                "可判卷日期数": len(judged),
                "预测正确日期数": int(judged["市场方向预测是否准确"].sum()),
                "稳定特征模型准确率": f"{judged['市场方向预测是否准确'].mean():.2%}" if len(judged) else "",
                "平均稳定特征数": round(float(result["稳定特征数"].mean()), 2),
            }
        ]
    )
    feature_all = pd.concat(feature_frames, ignore_index=True)
    feature_summary = (
        feature_all.groupby("特征", as_index=False)
        .agg(
            入选次数=("特征", "size"),
            平均相关性绝对值=("平均相关性绝对值", "mean"),
            平均方向一致率=("方向一致率", "mean"),
        )
        .sort_values(["入选次数", "平均相关性绝对值"], ascending=False)
        .reset_index(drop=True)
    )

    for col in ["预测上涨概率", "预测未来5日上涨比例", "融合预测上涨比例", "实际未来5日上涨比例"]:
        result[col] = result[col].map(lambda value: "" if pd.isna(value) else f"{value:.2%}")

    start_tag = result["锚点日期"].iloc[0].replace("-", "")
    end_tag = result["锚点日期"].iloc[-1].replace("-", "")
    result_path = output_dir / f"08_市场稳定特征模型预测结果_{start_tag}_{end_tag}.csv"
    stats_path = output_dir / f"08_市场稳定特征模型准确率统计_{start_tag}_{end_tag}.csv"
    feature_path = output_dir / f"08_市场稳定特征入选汇总_{start_tag}_{end_tag}.csv"
    result.to_csv(result_path, index=False, encoding="utf-8-sig")
    stats.to_csv(stats_path, index=False, encoding="utf-8-sig")
    feature_summary.to_csv(feature_path, index=False, encoding="utf-8-sig")

    print(f"稳定特征模型预测结果: {result_path}")
    print(f"稳定特征模型准确率统计: {stats_path}")
    print(f"稳定特征入选汇总: {feature_path}")
    print(result.to_string(index=False))
    print(stats.to_string(index=False))
    print(feature_summary.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
