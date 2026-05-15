#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from train_5d_return_model import (
    DEFAULT_DAILY_DIR,
    DEFAULT_META_CSV,
    DEFAULT_OUTPUT_DIR,
    balanced_binary_weights,
    prepare_xy,
)
from sklearn.ensemble import HistGradientBoostingClassifier

DEFAULT_SAMPLE_CSV = DEFAULT_OUTPUT_DIR / "00_5日涨跌方向预测样本明细.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只预测未来5个交易日涨跌方向")
    parser.add_argument("--sample-csv", default=str(DEFAULT_SAMPLE_CSV), help="已合并的5日方向预测样本明细CSV")
    parser.add_argument("--train-quality-csv", default="", help="训练样本质量标记CSV；仅用于过滤历史训练样本，不过滤锚点日预测股票池")
    parser.add_argument("--daily-dir", default=str(DEFAULT_DAILY_DIR), help="日K目录")
    parser.add_argument("--meta-csv", default=str(DEFAULT_META_CSV), help="股票元数据CSV")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--output-suffix", default="", help="输出文件名后缀，例如 _严格清洗")
    parser.add_argument("--as-of-date", required=True, help="锚点日期，格式 YYYY-MM-DD")
    parser.add_argument("--exclude-beijing", action="store_true", help="剔除北交所")
    parser.add_argument("--min-history", type=int, default=60, help="单只股票最少历史天数")
    parser.add_argument("--min-train-samples", type=int, default=200, help="最少训练样本数")
    parser.add_argument("--target-accuracy", type=float, default=0.80, help="每日全股票方向预测目标准确率，默认0.80")
    parser.add_argument(
        "--train-target-margin",
        type=float,
        default=0.005,
        help="训练时剔除绝对5日收益率小于该值的临界样本；默认0.005",
    )
    parser.add_argument("--model-iterations", type=int, default=80, help="分类模型训练迭代轮数")
    parser.add_argument(
        "--model-mode",
        choices=["ensemble", "single"],
        default="ensemble",
        help="模型模式：ensemble=多训练窗口概率融合，single=单训练窗口",
    )
    parser.add_argument("--train-window-dates", type=int, default=40, help="只使用锚点日前最近N个交易日训练；0表示使用全部历史")
    parser.add_argument(
        "--ensemble-window-weights",
        default="40:0.45,60:0.35,90:0.20",
        help="多窗口融合权重，格式如 40:0.45,60:0.35,90:0.20",
    )
    parser.add_argument(
        "--sample-weight-mode",
        choices=["balanced", "recent_balanced", "none"],
        default="recent_balanced",
        help="样本权重：balanced=类别平衡，recent_balanced=类别平衡且近期样本权重更高，none=不加权",
    )
    parser.add_argument(
        "--direction-threshold",
        type=float,
        default=-1.0,
        help="上涨概率阈值；非负数表示固定阈值；负数时按 --threshold-mode 自动计算",
    )
    parser.add_argument(
        "--threshold-mode",
        choices=["regime", "validation"],
        default="regime",
        help="direction-threshold为负数时的阈值模式：regime=市场状态阈值，validation=历史验证集最优阈值",
    )
    parser.add_argument(
        "--feature-set",
        choices=["all", "core", "stock_only", "relative_core"],
        default="core",
        help=(
            "特征集合：core=核心关键特征；stock_only=去掉市场/行业/指数环境；"
            "relative_core=保留相对强弱、去掉市场绝对方向；all=全部数值特征；默认core"
        ),
    )
    return parser.parse_args()


def load_direction_samples(sample_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(sample_csv, encoding="utf-8-sig", dtype={"代码": str})
    if df.empty:
        raise RuntimeError(f"样本明细为空: {sample_csv}")

    df["代码"] = df["代码"].str.zfill(6)
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df["future_date_5"] = pd.to_datetime(df["卖出日"], errors="coerce")
    df["target_5d"] = pd.to_numeric(df["5日后的实际涨跌幅"], errors="coerce")
    df["label_up_5d"] = (df["target_5d"] > 0).astype(float)
    return df


def load_train_quality_filter(path_text: str) -> pd.DataFrame:
    if not path_text:
        return pd.DataFrame()
    quality = pd.read_csv(path_text, encoding="utf-8-sig", dtype={"代码": str})
    quality["代码"] = quality["代码"].str.zfill(6)
    quality["日期"] = pd.to_datetime(quality["日期"], errors="coerce")
    if "是否建议纳入训练" not in quality.columns:
        raise RuntimeError(f"质量标记表缺少字段: 是否建议纳入训练 {path_text}")
    return quality[["日期", "代码", "是否建议纳入训练"]].copy()


def build_direction_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = {
        "日期",
        "代码",
        "名称",
        "行业",
        "板块",
        "交易所",
        "卖出日",
        "5日后收盘",
        "5日后的实际涨跌幅",
        "5日后上涨标签",
        "5日后实际涨跌",
        "future_date_5",
        "target_5d",
        "label_up_5d",
    }
    noisy_suffixes = ("分位档", "历史样本数")
    return [
        col
        for col in df.columns
        if col not in excluded
        and not col.endswith(noisy_suffixes)
        and pd.api.types.is_numeric_dtype(df[col])
    ]


CORE_FEATURE_COLUMNS = [
    "开盘",
    "收盘",
    "最高",
    "最低",
    "成交量",
    "成交额",
    "振幅",
    "涨跌幅",
    "换手率",
    "ret_1",
    "ret_3",
    "ret_5",
    "ret_10",
    "ret_20",
    "close_ma_ratio_5",
    "close_ma_ratio_10",
    "close_ma_ratio_20",
    "vol_ratio_5",
    "amount_ratio_5",
    "vol_ratio_10",
    "amount_ratio_10",
    "vol_change_1",
    "amount_change_1",
    "volatility_5",
    "volatility_10",
    "amp_mean_5",
    "amp_mean_10",
    "body_pct",
    "upper_shadow_pct",
    "lower_shadow_pct",
    "close_position_in_day",
    "range_pos_20",
    "dist_high_20",
    "dist_low_20",
    "全市场平均涨跌幅",
    "全市场上涨比例",
    "行业平均涨跌幅",
    "行业上涨比例",
    "个股强于行业",
    "同行业历史5日上涨率",
    "上证指数_1日涨跌幅",
    "上证指数_5日涨跌幅",
    "沪深300_1日涨跌幅",
    "沪深300_5日涨跌幅",
    "中证500_5日涨跌幅",
    "中证1000_5日涨跌幅",
    "个股强于沪深300_5日相对强弱",
    "个股强于中证500_5日相对强弱",
    "个股强于中证1000_5日相对强弱",
]

MARKET_ABSOLUTE_FEATURE_COLUMNS = {
    "全市场平均涨跌幅",
    "全市场上涨比例",
    "行业平均涨跌幅",
    "行业上涨比例",
    "上证指数_1日涨跌幅",
    "上证指数_5日涨跌幅",
    "沪深300_1日涨跌幅",
    "沪深300_5日涨跌幅",
    "中证500_5日涨跌幅",
    "中证1000_5日涨跌幅",
}

RELATIVE_STRENGTH_FEATURE_COLUMNS = {
    "个股强于行业",
    "同行业历史5日上涨率",
    "个股强于沪深300_5日相对强弱",
    "个股强于中证500_5日相对强弱",
    "个股强于中证1000_5日相对强弱",
}


def build_core_feature_columns(df: pd.DataFrame) -> list[str]:
    return [
        col
        for col in CORE_FEATURE_COLUMNS
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col])
    ]


def build_stock_only_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = MARKET_ABSOLUTE_FEATURE_COLUMNS | RELATIVE_STRENGTH_FEATURE_COLUMNS
    return [
        col
        for col in CORE_FEATURE_COLUMNS
        if col not in excluded and col in df.columns and pd.api.types.is_numeric_dtype(df[col])
    ]


def build_relative_core_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = MARKET_ABSOLUTE_FEATURE_COLUMNS
    return [
        col
        for col in CORE_FEATURE_COLUMNS
        if col not in excluded and col in df.columns and pd.api.types.is_numeric_dtype(df[col])
    ]


def feature_file_tag(feature_set: str) -> str:
    if feature_set in {"core", "stock_only", "relative_core"}:
        return "_核心特征"
    return ""


def direction_label(series: pd.Series) -> np.ndarray:
    return np.where(series > 0, "上涨", "下跌")


def build_direction_model(model_iterations: int) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_depth=6,
        max_iter=model_iterations,
        min_samples_leaf=20,
        l2_regularization=0.1,
        random_state=42,
    )


def parse_window_weights(value: str) -> list[tuple[int, float]]:
    pairs: list[tuple[int, float]] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        window, weight = item.split(":", 1)
        pairs.append((int(window), float(weight)))
    if not pairs:
        raise ValueError("ensemble-window-weights不能为空")
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        raise ValueError("ensemble-window-weights权重和必须大于0")
    return [(window, weight / total_weight) for window, weight in pairs]


def market_regime_threshold(anchor_df: pd.DataFrame, train_window_dates: int = 0, model_mode: str = "single") -> float:
    """根据锚点日已知市场状态调整方向阈值。

    规则只使用锚点日当时已知的行情特征：
    - 近5日整体涨幅越高，越容易出现5日后回落，阈值收紧。
    - 近5日不强且当日市场上涨比例较高时，更偏修复，阈值放松。
    """
    avg_ret_5 = float(pd.to_numeric(anchor_df.get("ret_5"), errors="coerce").mean())
    market_up = float(pd.to_numeric(anchor_df.get("全市场上涨比例"), errors="coerce").mean())

    if pd.isna(avg_ret_5):
        avg_ret_5 = 0.0
    if pd.isna(market_up):
        market_up = 0.5

    if model_mode == "ensemble":
        if avg_ret_5 >= 0.015 and market_up < 0.5:
            return 0.615
        if avg_ret_5 >= 0.015:
            return 0.345
        if avg_ret_5 > 0:
            return 0.335
        if market_up >= 0.5:
            return 0.215
        return 0.28

    if train_window_dates and train_window_dates <= 60:
        if avg_ret_5 >= 0.015 and market_up < 0.5:
            return 0.795
        if avg_ret_5 >= 0.015:
            return 0.47
        if avg_ret_5 > 0:
            return 0.30
        if market_up >= 0.5:
            return 0.235
        return 0.265

    if avg_ret_5 >= 0.03:
        return 0.47
    if avg_ret_5 >= 0.015:
        return 0.485
    if avg_ret_5 > 0:
        return 0.405
    if market_up >= 0.5:
        return 0.34
    return 0.37


def apply_train_window(train_df: pd.DataFrame, train_window_dates: int) -> pd.DataFrame:
    if train_window_dates <= 0:
        return train_df
    unique_dates = sorted(pd.to_datetime(train_df["日期"]).dropna().unique())
    keep_dates = set(unique_dates[-train_window_dates:])
    return train_df[train_df["日期"].isin(keep_dates)].copy()


def apply_target_margin(train_df: pd.DataFrame, margin: float) -> pd.DataFrame:
    if margin <= 0:
        return train_df
    return train_df[train_df["target_5d"].abs() >= margin].copy()


def direction_sample_weights(train_df: pd.DataFrame, y: pd.Series, mode: str) -> np.ndarray | None:
    if mode == "none":
        return None

    base = balanced_binary_weights(y)
    if mode == "balanced":
        return base

    unique_dates = sorted(pd.to_datetime(train_df["日期"]).dropna().unique())
    if len(unique_dates) <= 1:
        return base
    date_rank = {value: idx for idx, value in enumerate(unique_dates)}
    ranks = pd.to_datetime(train_df["日期"]).map(date_rank).to_numpy(dtype=float)
    ranks = (ranks - np.nanmin(ranks)) / (np.nanmax(ranks) - np.nanmin(ranks) + 1e-9)
    recency_weight = 0.5 + 1.5 * ranks
    return base * recency_weight


def train_predict_one_window(
    train_df: pd.DataFrame,
    anchor_df: pd.DataFrame,
    feature_cols: list[str],
    model_iterations: int,
    sample_weight_mode: str,
) -> tuple[np.ndarray, int]:
    X_train, y_train = prepare_xy(train_df, feature_cols, "label_up_5d")
    if len(X_train) == 0:
        raise RuntimeError("训练样本为空")

    clean_train = train_df.dropna(subset=feature_cols + ["label_up_5d"]).copy()
    sample_weight = direction_sample_weights(clean_train, y_train, sample_weight_mode)
    clf_model = build_direction_model(model_iterations)
    if sample_weight is None:
        clf_model.fit(X_train, y_train)
    else:
        clf_model.fit(X_train, y_train, sample_weight=sample_weight)

    X_anchor = anchor_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return clf_model.predict_proba(X_anchor)[:, 1], len(X_train)


def calibrate_direction_threshold(train_df: pd.DataFrame, feature_cols: list[str], model_iterations: int) -> float:
    unique_dates = sorted(pd.to_datetime(train_df["日期"]).dropna().unique())
    if len(unique_dates) < 20:
        return 0.5

    split_at = max(int(len(unique_dates) * 0.8), len(unique_dates) - 25)
    core_dates = set(unique_dates[:split_at])
    valid_dates = set(unique_dates[split_at:])
    core_df = train_df[train_df["日期"].isin(core_dates)].copy()
    valid_df = train_df[train_df["日期"].isin(valid_dates)].copy()
    if len(core_df) < 200 or len(valid_df) < 50:
        return 0.5

    X_core, y_core = prepare_xy(core_df, feature_cols, "label_up_5d")
    valid_clean = valid_df.dropna(subset=feature_cols + ["label_up_5d"]).copy()
    X_valid = valid_clean[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y_valid = valid_clean["label_up_5d"].astype(int)

    clf_model = build_direction_model(model_iterations)
    clf_model.fit(X_core, y_core, sample_weight=balanced_binary_weights(y_core))
    valid_clean["prob"] = clf_model.predict_proba(X_valid)[:, 1]
    valid_clean["actual"] = y_valid.to_numpy()

    best_threshold = 0.5
    best_daily_accuracy = -1.0
    for threshold in np.arange(0.35, 0.651, 0.01):
        valid_clean["pred"] = (valid_clean["prob"] >= threshold).astype(int)
        valid_clean["correct"] = (valid_clean["pred"] == valid_clean["actual"]).astype(float)
        daily_accuracy = valid_clean.groupby("日期")["correct"].mean().mean()
        if pd.notna(daily_accuracy) and daily_accuracy > best_daily_accuracy:
            best_daily_accuracy = float(daily_accuracy)
            best_threshold = float(threshold)
    return best_threshold


def main() -> None:
    args = parse_args()
    as_of_date = pd.to_datetime(args.as_of_date)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    full_df = load_direction_samples(Path(args.sample_csv).resolve())
    quality_filter = load_train_quality_filter(args.train_quality_csv)
    if not quality_filter.empty:
        full_df = full_df.merge(quality_filter, on=["日期", "代码"], how="left")
        full_df["是否建议纳入训练"] = full_df["是否建议纳入训练"].fillna(0).astype(int)
    else:
        full_df["是否建议纳入训练"] = 1

    # 严格真实回测：预测锚点日时，只允许使用当时已经知道5日后结果的历史样本。
    base_train_df = full_df[
        (full_df["日期"] < as_of_date)
        & full_df["target_5d"].notna()
        & (full_df["future_date_5"] <= as_of_date)
        & (full_df["是否建议纳入训练"] == 1)
    ].copy()
    train_df = apply_train_window(base_train_df, args.train_window_dates)

    anchor_df = full_df[full_df["日期"] == as_of_date].copy()
    if anchor_df.empty:
        raise RuntimeError(f"未找到锚点日期: {args.as_of_date}")

    if args.feature_set == "core":
        feature_cols = build_core_feature_columns(base_train_df)
    elif args.feature_set == "stock_only":
        feature_cols = build_stock_only_feature_columns(base_train_df)
    elif args.feature_set == "relative_core":
        feature_cols = build_relative_core_feature_columns(base_train_df)
    else:
        feature_cols = build_direction_feature_columns(base_train_df)
    if not feature_cols:
        raise RuntimeError(f"特征集合为空: {args.feature_set}")
    if args.direction_threshold >= 0:
        threshold = float(args.direction_threshold)
    elif args.threshold_mode == "regime":
        threshold = market_regime_threshold(anchor_df, args.train_window_dates, args.model_mode)
    else:
        threshold = calibrate_direction_threshold(train_df, feature_cols, args.model_iterations)

    if args.model_mode == "ensemble":
        probabilities: list[np.ndarray] = []
        train_sizes: list[int] = []
        for window, weight in parse_window_weights(args.ensemble_window_weights):
            window_train_df = apply_train_window(base_train_df, window)
            window_train_df = apply_target_margin(window_train_df, args.train_target_margin)
            if len(window_train_df) < args.min_train_samples:
                raise RuntimeError(f"{window}日窗口训练样本不足: {len(window_train_df)}")
            prob, train_size = train_predict_one_window(
                window_train_df,
                anchor_df,
                feature_cols,
                args.model_iterations,
                args.sample_weight_mode,
            )
            probabilities.append(prob * weight)
            train_sizes.append(train_size)
        anchor_df["预测上涨概率"] = np.sum(probabilities, axis=0)
        train_sample_size = int(sum(train_sizes))
    else:
        train_df = apply_target_margin(train_df, args.train_target_margin)
        if len(train_df) < args.min_train_samples:
            raise RuntimeError(f"训练样本不足: {len(train_df)}")
        anchor_df["预测上涨概率"], train_sample_size = train_predict_one_window(
            train_df,
            anchor_df,
            feature_cols,
            args.model_iterations,
            args.sample_weight_mode,
        )
    anchor_df["方向阈值"] = threshold
    anchor_df["预测涨跌"] = np.where(anchor_df["预测上涨概率"] >= threshold, "上涨", "下跌")
    anchor_df["实际涨跌"] = direction_label(anchor_df["target_5d"])
    anchor_df["涨跌预测是否准确"] = np.where(anchor_df["预测涨跌"] == anchor_df["实际涨跌"], 1, 0)
    anchor_df["锚点日期"] = as_of_date
    anchor_df["训练样本数"] = train_sample_size
    anchor_df["特征集合"] = args.feature_set
    anchor_df["特征数量"] = len(feature_cols)
    anchor_df["未来卖出日期"] = anchor_df["future_date_5"]

    out_cols = [
        "锚点日期",
        "训练样本数",
        "特征集合",
        "特征数量",
        "日期",
        "代码",
        "名称",
        "行业",
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "振幅",
        "涨跌幅",
        "换手率",
        "预测上涨概率",
        "方向阈值",
        "预测涨跌",
        "实际涨跌",
        "涨跌预测是否准确",
        "未来卖出日期",
    ]
    result = anchor_df[out_cols].sort_values(["预测上涨概率", "代码"], ascending=[False, True]).reset_index(drop=True)
    for col in ["锚点日期", "日期", "未来卖出日期"]:
        result[col] = pd.to_datetime(result[col], errors="coerce").dt.strftime("%Y-%m-%d")

    correct_count = int(result["涨跌预测是否准确"].sum())
    total_count = int(len(result))
    target_count = int(np.ceil(total_count * args.target_accuracy))
    accuracy = correct_count / total_count if total_count else np.nan
    target_pct = f"{args.target_accuracy:.0%}"
    stats = pd.DataFrame(
        [
            {
                "锚点日期": as_of_date.strftime("%Y-%m-%d"),
                "训练样本数": int(train_sample_size),
                "特征集合": args.feature_set,
                "特征数量": len(feature_cols),
                "股票数量": total_count,
                "预测正确数": correct_count,
                f"{target_pct}目标所需准确数": target_count,
                "涨跌预测准确率": f"{accuracy:.2%}",
                f"是否达到{target_pct}目标": int(correct_count >= target_count),
                "预测上涨数": int((result["预测涨跌"] == "上涨").sum()),
                "预测下跌数": int((result["预测涨跌"] == "下跌").sum()),
                "实际上涨数": int((result["实际涨跌"] == "上涨").sum()),
                "实际下跌数": int((result["实际涨跌"] == "下跌").sum()),
            }
        ]
    )

    date_tag = as_of_date.strftime("%Y%m%d")
    feature_tag = feature_file_tag(args.feature_set)
    result_path = output_dir / f"03_每只股票方向预测结果{feature_tag}{args.output_suffix}_{date_tag}.csv"
    stats_path = output_dir / f"04_每天方向预测准确率统计{feature_tag}{args.output_suffix}_{date_tag}.csv"
    result.to_csv(result_path, index=False, encoding="utf-8-sig")
    stats.to_csv(stats_path, index=False, encoding="utf-8-sig")

    print(f"已输出: {result_path}")
    print(f"已输出: {stats_path}")
    print(stats.to_string(index=False))


if __name__ == "__main__":
    main()
