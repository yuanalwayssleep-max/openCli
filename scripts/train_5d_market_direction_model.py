#!/usr/bin/env python3
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from train_5d_direction_model import DEFAULT_SAMPLE_CSV
from train_5d_return_model import DEFAULT_OUTPUT_DIR, prepare_xy


DEFAULT_MARKET_SAMPLE_CSV = DEFAULT_OUTPUT_DIR / "00_市场5日方向预测样本.csv"
DEFAULT_BASE_CSV = DEFAULT_OUTPUT_DIR / "00_A股日K基础行情与5日后标签表.csv"
DEFAULT_FEATURE_CSV = DEFAULT_OUTPUT_DIR / "00_5日方向模型特征表.csv"

warnings.filterwarnings("ignore", category=PerformanceWarning)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="训练并回测股票池未来5日市场方向模型")
    parser.add_argument("--sample-csv", default=str(DEFAULT_SAMPLE_CSV), help="每只股票5日方向样本明细CSV")
    parser.add_argument("--base-csv", default=str(DEFAULT_BASE_CSV), help="A股日K基础行情与5日后标签表")
    parser.add_argument("--feature-csv", default=str(DEFAULT_FEATURE_CSV), help="5日方向模型特征表")
    parser.add_argument(
        "--data-source",
        choices=["split", "sample"],
        default="split",
        help="市场样本数据源：split=基础表+特征表，sample=旧建模明细表；默认split",
    )
    parser.add_argument("--market-sample-csv", default=str(DEFAULT_MARKET_SAMPLE_CSV), help="市场方向样本输出CSV")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--as-of-date", help="单个锚点日期，格式 YYYY-MM-DD")
    parser.add_argument(
        "--test-dates",
        help="多个锚点日期，逗号分隔；例如 2026-03-16,2026-03-19",
    )
    parser.add_argument("--min-train-days", type=int, default=60, help="最少训练交易日数")
    parser.add_argument("--train-window-days", type=int, default=120, help="最近N个已完成结果交易日训练；0表示全部")
    parser.add_argument("--ensemble-windows", default="60,90,120", help="市场上涨比例回归的多窗口，逗号分隔")
    parser.add_argument("--target-up-ratio", type=float, default=0.50, help="未来5日市场偏涨阈值，默认上涨比例>=50%")
    parser.add_argument("--neutral-low", type=float, default=0.45, help="震荡区间下界，默认0.45")
    parser.add_argument("--neutral-high", type=float, default=0.55, help="震荡区间上界，默认0.55")
    parser.add_argument(
        "--decision-mode",
        choices=["baseline", "regime"],
        default="regime",
        help="市场方向决策模式：baseline=旧二分类融合，regime=上涨比例回归+五档状态；默认regime",
    )
    return parser.parse_args()


def market_state(up_ratio: float) -> str:
    if pd.isna(up_ratio):
        return ""
    if up_ratio >= 0.70:
        return "强上涨"
    if up_ratio >= 0.55:
        return "普涨"
    if up_ratio >= 0.45:
        return "震荡"
    if up_ratio >= 0.30:
        return "普跌"
    return "强下跌"


def load_stock_samples(sample_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(sample_csv, encoding="utf-8-sig", dtype={"代码": str})
    if df.empty:
        raise RuntimeError(f"样本为空: {sample_csv}")
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df["卖出日"] = pd.to_datetime(df["卖出日"], errors="coerce")
    df["5日后的实际涨跌幅"] = pd.to_numeric(df["5日后的实际涨跌幅"], errors="coerce")
    return df


def load_split_samples(base_csv: Path, feature_csv: Path) -> pd.DataFrame:
    base = pd.read_csv(base_csv, encoding="utf-8-sig", dtype={"代码": str})
    if base.empty:
        raise RuntimeError(f"基础表为空: {base_csv}")
    base["代码"] = base["代码"].str.zfill(6)

    if feature_csv.exists():
        feature = pd.read_csv(feature_csv, encoding="utf-8-sig", dtype={"代码": str})
        feature["代码"] = feature["代码"].str.zfill(6)
        feature_cols = [
            col
            for col in feature.columns
            if col in {"日期", "代码"} or col not in base.columns
        ]
        df = base.merge(feature[feature_cols], on=["日期", "代码"], how="left")
    else:
        print(f"未找到特征表，仅使用基础表生成市场样本: {feature_csv}")
        df = base.copy()

    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    df["卖出日"] = pd.to_datetime(df["卖出日"], errors="coerce")
    df["5日后的实际涨跌幅"] = pd.to_numeric(df["5日后的实际涨跌幅"], errors="coerce")
    return df


def make_market_samples(stock_df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "涨跌幅",
        "振幅",
        "换手率",
        "成交量",
        "成交额",
        "ret_1",
        "ret_3",
        "ret_5",
        "ret_10",
        "ret_20",
        "vol_ratio_5",
        "amount_ratio_5",
        "vol_ratio_10",
        "amount_ratio_10",
        "volatility_5",
        "volatility_10",
        "amp_mean_5",
        "amp_mean_10",
        "range_pos_20",
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
        "个股强于沪深300_5日相对强弱",
        "个股强于中证500_5日相对强弱",
        "个股强于中证1000_5日相对强弱",
    ]
    for col in numeric_cols:
        if col in stock_df.columns:
            stock_df[col] = pd.to_numeric(stock_df[col], errors="coerce")

    rows: list[dict[str, object]] = []
    for date, day in stock_df.groupby("日期", sort=True):
        target = day["5日后的实际涨跌幅"]
        pct = pd.to_numeric(day["涨跌幅"], errors="coerce")
        amount = pd.to_numeric(day["成交额"], errors="coerce")
        volume = pd.to_numeric(day["成交量"], errors="coerce")
        row: dict[str, object] = {
            "日期": date,
            "卖出日": day["卖出日"].max(),
            "股票数量": int(day["代码"].nunique()),
            "当日上涨比例": float((pct > 0).mean()),
            "当日下跌比例": float((pct < 0).mean()),
            "当日大涨比例_3pct": float((pct >= 3).mean()),
            "当日大跌比例_3pct": float((pct <= -3).mean()),
            "当日强涨比例_5pct": float((pct >= 5).mean()),
            "当日强跌比例_5pct": float((pct <= -5).mean()),
            "当日接近涨停比例": float((pct >= 9.5).mean()),
            "当日接近跌停比例": float((pct <= -9.5).mean()),
            "当日平均涨跌幅": float(pct.mean()),
            "当日涨跌幅中位数": float(pct.median()),
            "当日涨跌幅标准差": float(pct.std()),
            "当日涨跌幅25分位": float(pct.quantile(0.25)),
            "当日涨跌幅75分位": float(pct.quantile(0.75)),
            "当日涨跌幅偏度": float(pct.skew()),
            "当日涨跌幅极差": float(pct.max() - pct.min()),
            "当日平均振幅": float(day["振幅"].mean()),
            "当日平均换手率": float(day["换手率"].mean()),
            "当日平均成交额": float(amount.mean()),
            "当日成交额中位数": float(amount.median()),
            "当日成交额标准差": float(amount.std()),
            "当日平均成交量": float(volume.mean()),
            "当日成交量中位数": float(volume.median()),
            "未来5日上涨比例": float((target > 0).mean()) if target.notna().any() else np.nan,
            "未来5日平均收益": float(target.mean()) if target.notna().any() else np.nan,
            "未来5日市场方向": "",
        }
        if pd.notna(row["未来5日上涨比例"]):
            row["未来5日市场方向"] = "上涨" if row["未来5日上涨比例"] >= 0.50 else "下跌"
            row["未来5日市场状态"] = market_state(float(row["未来5日上涨比例"]))
        else:
            row["未来5日市场状态"] = ""

        mean_cols = [
            "ret_1",
            "ret_3",
            "ret_5",
            "ret_10",
            "ret_20",
            "vol_ratio_5",
            "amount_ratio_5",
            "vol_ratio_10",
            "amount_ratio_10",
            "volatility_5",
            "volatility_10",
            "amp_mean_5",
            "amp_mean_10",
            "range_pos_20",
            "全市场上涨比例",
            "全市场平均涨跌幅",
            "行业平均涨跌幅",
            "行业上涨比例",
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
        for col in mean_cols:
            if col in day.columns:
                row[f"{col}_均值"] = float(day[col].mean())

        if "行业" in day.columns:
            industry = day.groupby("行业")["涨跌幅"].mean()
            row["上涨行业比例"] = float((industry > 0).mean()) if len(industry) else np.nan
            row["下跌行业比例"] = float((industry < 0).mean()) if len(industry) else np.nan
            row["行业平均涨跌幅中位数"] = float(industry.median()) if len(industry) else np.nan
            row["行业强涨比例_1pct"] = float((industry >= 1).mean()) if len(industry) else np.nan
            row["行业强跌比例_1pct"] = float((industry <= -1).mean()) if len(industry) else np.nan
            row["行业涨跌分化度"] = float(industry.std()) if len(industry) else np.nan

        rows.append(row)

    market = pd.DataFrame(rows).sort_values("日期").reset_index(drop=True)

    for col in ["沪深300_5日涨跌幅_均值", "中证500_5日涨跌幅_均值", "中证1000_5日涨跌幅_均值"]:
        if col not in market.columns:
            market[col] = np.nan
    market["中证1000强于沪深300_5日"] = market["中证1000_5日涨跌幅_均值"] - market["沪深300_5日涨跌幅_均值"]
    market["中证500强于沪深300_5日"] = market["中证500_5日涨跌幅_均值"] - market["沪深300_5日涨跌幅_均值"]
    market["小盘强于中盘_5日"] = market["中证1000_5日涨跌幅_均值"] - market["中证500_5日涨跌幅_均值"]
    market["市场宽度价格背离"] = market["当日上涨比例"] - (market["当日平均涨跌幅"] > 0).astype(float)
    market["涨跌扩散差"] = market["当日大涨比例_3pct"] - market["当日大跌比例_3pct"]
    market["极端涨跌差"] = market["当日强涨比例_5pct"] - market["当日强跌比例_5pct"]

    rolling_base_cols = [
        "当日上涨比例",
        "当日平均涨跌幅",
        "当日平均振幅",
        "当日平均换手率",
        "当日平均成交额",
        "当日平均成交量",
        "当日大涨比例_3pct",
        "当日大跌比例_3pct",
        "当日强涨比例_5pct",
        "当日强跌比例_5pct",
        "当日涨跌幅标准差",
        "涨跌扩散差",
        "极端涨跌差",
        "上涨行业比例",
        "下跌行业比例",
        "行业强涨比例_1pct",
        "行业强跌比例_1pct",
        "行业涨跌分化度",
        "沪深300_5日涨跌幅_均值",
        "中证500_5日涨跌幅_均值",
        "中证1000_5日涨跌幅_均值",
        "中证1000强于沪深300_5日",
        "中证500强于沪深300_5日",
        "小盘强于中盘_5日",
    ]
    for col in rolling_base_cols:
        if col not in market.columns:
            continue
        series = pd.to_numeric(market[col], errors="coerce")
        for window in (3, 5, 10):
            market[f"{col}_近{window}日均值"] = series.rolling(window, min_periods=1).mean()
            market[f"{col}_近{window}日标准差"] = series.rolling(window, min_periods=2).std()
        market[f"{col}_近5日变化"] = series - series.shift(5)
        market[f"{col}_近3日斜率"] = series - series.shift(3)

    down = pd.to_numeric(market["当日上涨比例"], errors="coerce") < 0.35
    market["连续弱势天数"] = (
        down.groupby((down != down.shift()).cumsum()).cumcount() + 1
    ).where(down, 0)
    up = pd.to_numeric(market["当日上涨比例"], errors="coerce") > 0.65
    market["连续强势天数"] = (
        up.groupby((up != up.shift()).cumsum()).cumcount() + 1
    ).where(up, 0)
    avg_return = pd.to_numeric(market["当日平均涨跌幅"], errors="coerce")
    market["连续下跌天数"] = (
        (avg_return < 0).groupby(((avg_return < 0) != (avg_return < 0).shift()).cumsum()).cumcount() + 1
    ).where(avg_return < 0, 0)
    market["连续上涨天数"] = (
        (avg_return > 0).groupby(((avg_return > 0) != (avg_return > 0).shift()).cumsum()).cumcount() + 1
    ).where(avg_return > 0, 0)

    for window in (5, 10, 20):
        market[f"当日上涨比例_近{window}日最高"] = market["当日上涨比例"].rolling(window, min_periods=1).max()
        market[f"当日上涨比例_近{window}日最低"] = market["当日上涨比例"].rolling(window, min_periods=1).min()
        market[f"当日上涨比例_近{window}日位置"] = (
            (market["当日上涨比例"] - market[f"当日上涨比例_近{window}日最低"])
            / (market[f"当日上涨比例_近{window}日最高"] - market[f"当日上涨比例_近{window}日最低"] + 1e-9)
        )
        market[f"当日平均涨跌幅_近{window}日最高"] = market["当日平均涨跌幅"].rolling(window, min_periods=1).max()
        market[f"当日平均涨跌幅_近{window}日最低"] = market["当日平均涨跌幅"].rolling(window, min_periods=1).min()
        market[f"当日平均涨跌幅_近{window}日位置"] = (
            (market["当日平均涨跌幅"] - market[f"当日平均涨跌幅_近{window}日最低"])
            / (market[f"当日平均涨跌幅_近{window}日最高"] - market[f"当日平均涨跌幅_近{window}日最低"] + 1e-9)
        )

    market["恐慌释放特征"] = (
        (market["当日上涨比例"] < 0.30).astype(int)
        + (market["当日大跌比例_3pct"] > 0.35).astype(int)
        + (market["当日平均成交额_近5日变化"] > 0).astype(int)
        + (market["连续弱势天数"] >= 1).astype(int)
    )
    market["过热回落风险特征"] = (
        (market["当日上涨比例"] > 0.65).astype(int)
        + (market["当日平均涨跌幅_近5日均值"] > 0.5).astype(int)
        + (market["连续强势天数"] >= 1).astype(int)
        + (market["中证1000强于沪深300_5日"] > 0.02).astype(int)
    )
    market["弱势延续风险特征"] = (
        (market["当日上涨比例_近5日均值"] < 0.40).astype(int)
        + (market["当日平均涨跌幅_近5日均值"] < -0.30).astype(int)
        + (market["中证500_5日涨跌幅_均值"] < -0.02).astype(int)
        + (market["中证1000_5日涨跌幅_均值"] < -0.02).astype(int)
    )
    market["未来5日市场上涨标签"] = (
        pd.to_numeric(market["未来5日上涨比例"], errors="coerce") >= 0.50
    ).astype(float)
    return market


def build_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = {
        "日期",
        "卖出日",
        "未来5日上涨比例",
        "未来5日平均收益",
        "未来5日市场方向",
        "未来5日市场状态",
        "未来5日市场上涨标签",
    }
    return [
        col
        for col in df.columns
        if col not in excluded and pd.api.types.is_numeric_dtype(df[col])
    ]


def apply_train_window(train_df: pd.DataFrame, train_window_days: int) -> pd.DataFrame:
    if train_window_days <= 0:
        return train_df
    return train_df.sort_values("日期").tail(train_window_days).copy()


def parse_ensemble_windows(value: str) -> list[int]:
    windows = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not windows:
        raise ValueError("--ensemble-windows不能为空")
    return windows


def train_regressor(train_df: pd.DataFrame, feature_cols: list[str]) -> HistGradientBoostingRegressor:
    X_train, y_train = prepare_xy(train_df, feature_cols, "未来5日上涨比例")
    reg = HistGradientBoostingRegressor(
        learning_rate=0.04,
        max_iter=100,
        max_depth=3,
        min_samples_leaf=8,
        l2_regularization=0.2,
        random_state=42,
    )
    reg.fit(X_train, y_train)
    return reg


def safe_binary_probability(
    train_df: pd.DataFrame,
    anchor_df: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
) -> float:
    y = train_df[label_col].astype(int)
    if y.nunique() < 2:
        return float(y.mean())
    X_train, y_train = prepare_xy(train_df, feature_cols, label_col)
    X_anchor = anchor_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    clf = HistGradientBoostingClassifier(
        learning_rate=0.04,
        max_iter=80,
        max_depth=3,
        min_samples_leaf=8,
        l2_regularization=0.2,
        random_state=42,
    )
    clf.fit(X_train, y_train)
    return float(clf.predict_proba(X_anchor)[:, 1][0])


def predict_market_regime(
    train_df: pd.DataFrame,
    anchor_df: pd.DataFrame,
    feature_cols: list[str],
    ensemble_windows: list[int],
    neutral_low: float,
    neutral_high: float,
    min_train_days: int,
) -> dict[str, float | str]:
    X_anchor = anchor_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    reg_predictions: list[float] = []
    for window in ensemble_windows:
        window_df = apply_train_window(train_df, window)
        reg = train_regressor(window_df, feature_cols)
        reg_predictions.append(float(np.clip(reg.predict(X_anchor)[0], 0.0, 1.0)))

    train_for_cls = train_df.copy()
    train_for_cls["强上涨标签"] = (train_for_cls["未来5日上涨比例"] >= 0.70).astype(int)
    train_for_cls["强下跌标签"] = (train_for_cls["未来5日上涨比例"] < 0.30).astype(int)
    opportunity_prob = safe_binary_probability(train_for_cls, anchor_df, feature_cols, "强上涨标签")
    risk_prob = safe_binary_probability(train_for_cls, anchor_df, feature_cols, "强下跌标签")

    reg_ratio = float(np.mean(reg_predictions))
    adjusted_ratio = float(np.clip(reg_ratio + 0.04 * opportunity_prob - 0.04 * risk_prob, 0.0, 1.0))
    state = market_state(adjusted_ratio)
    direction = "上涨" if adjusted_ratio >= 0.50 else "下跌"
    if neutral_low <= adjusted_ratio < neutral_high:
        direction = "震荡"

    return {
        "预测未来5日上涨比例": reg_ratio,
        "机会模型强上涨概率": opportunity_prob,
        "风险模型强下跌概率": risk_prob,
        "融合预测上涨比例": adjusted_ratio,
        "预测市场状态": state,
        "预测市场方向": direction,
    }


def predict_one(
    market_df: pd.DataFrame,
    as_of_date: pd.Timestamp,
    feature_cols: list[str],
    min_train_days: int,
    train_window_days: int,
    target_up_ratio: float,
    decision_mode: str,
    ensemble_windows: list[int],
    neutral_low: float,
    neutral_high: float,
) -> dict[str, object]:
    train_df = market_df[
        (market_df["日期"] < as_of_date)
        & (market_df["卖出日"] <= as_of_date)
        & market_df["未来5日上涨比例"].notna()
    ].copy()
    train_df = apply_train_window(train_df, train_window_days)
    if len(train_df) < min_train_days:
        raise RuntimeError(f"{as_of_date.strftime('%Y-%m-%d')} 市场模型训练天数不足: {len(train_df)}")

    anchor_df = market_df[market_df["日期"] == as_of_date].copy()
    if anchor_df.empty:
        raise RuntimeError(f"未找到锚点日期: {as_of_date.strftime('%Y-%m-%d')}")

    train_df["market_label"] = (
        pd.to_numeric(train_df["未来5日上涨比例"], errors="coerce") >= target_up_ratio
    ).astype(int)
    if decision_mode == "baseline":
        X_train, y_train = prepare_xy(train_df, feature_cols, "market_label")
        X_anchor = anchor_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        clf = HistGradientBoostingClassifier(
            learning_rate=0.04,
            max_iter=80,
            max_depth=3,
            min_samples_leaf=8,
            l2_regularization=0.2,
            random_state=42,
        )
        clf.fit(X_train, y_train)

        reg = train_regressor(train_df, feature_cols)
        pred_prob = float(clf.predict_proba(X_anchor)[:, 1][0])
        pred_up_ratio = float(np.clip(reg.predict(X_anchor)[0], 0.0, 1.0))
        similar_up_ratio = predict_similar_market_up_ratio(train_df, anchor_df)
        blended_up_ratio = 0.60 * pred_up_ratio + 0.40 * similar_up_ratio
        pred_direction = "上涨" if blended_up_ratio >= target_up_ratio else "下跌"
        pred_state = market_state(blended_up_ratio)
        opportunity_prob = np.nan
        risk_prob = np.nan
    else:
        regime = predict_market_regime(
            train_df,
            anchor_df,
            feature_cols,
            ensemble_windows,
            neutral_low,
            neutral_high,
            min_train_days,
        )
        pred_prob = np.nan
        pred_up_ratio = float(regime["预测未来5日上涨比例"])
        similar_up_ratio = np.nan
        blended_up_ratio = float(regime["融合预测上涨比例"])
        pred_direction = str(regime["预测市场方向"])
        pred_state = str(regime["预测市场状态"])
        opportunity_prob = float(regime["机会模型强上涨概率"])
        risk_prob = float(regime["风险模型强下跌概率"])

    actual_value = anchor_df["未来5日上涨比例"].iloc[0]
    actual_up_ratio = float(actual_value) if pd.notna(actual_value) else np.nan
    actual_state = anchor_df["未来5日市场状态"].iloc[0]
    actual_direction = "上涨" if actual_up_ratio >= target_up_ratio else ("下跌" if pd.notna(actual_up_ratio) else "")
    eval_pred_direction = "上涨" if blended_up_ratio >= target_up_ratio else "下跌"
    is_correct = int(eval_pred_direction == actual_direction) if actual_direction else np.nan
    sell_date = anchor_df["卖出日"].iloc[0]
    sell_date_text = pd.to_datetime(sell_date).strftime("%Y-%m-%d") if pd.notna(sell_date) else ""
    return {
        "锚点日期": as_of_date.strftime("%Y-%m-%d"),
        "训练天数": int(len(train_df)),
        "特征数量": int(len(feature_cols)),
        "股票数量": int(anchor_df["股票数量"].iloc[0]),
        "决策模式": decision_mode,
        "预测市场上涨概率": pred_prob,
        "预测未来5日上涨比例": pred_up_ratio,
        "相似市场预测上涨比例": similar_up_ratio,
        "机会模型强上涨概率": opportunity_prob,
        "风险模型强下跌概率": risk_prob,
        "融合预测上涨比例": blended_up_ratio,
        "预测市场方向": pred_direction,
        "预测市场状态": pred_state,
        "实际未来5日上涨比例": actual_up_ratio,
        "实际市场方向": actual_direction,
        "实际市场状态": actual_state,
        "市场方向预测是否准确": is_correct,
        "未来卖出日期": sell_date_text,
    }


SIMILAR_FEATURE_COLUMNS = [
    "当日上涨比例",
    "当日平均涨跌幅",
    "当日涨跌幅中位数",
    "ret_3_均值",
    "ret_5_均值",
    "ret_10_均值",
    "沪深300_5日涨跌幅_均值",
    "中证500_5日涨跌幅_均值",
    "中证1000_5日涨跌幅_均值",
    "当日上涨比例_近3日均值",
    "当日上涨比例_近5日均值",
    "当日平均涨跌幅_近3日均值",
    "当日平均涨跌幅_近5日均值",
    "上涨行业比例",
    "上涨行业比例_近5日均值",
    "连续弱势天数",
]


def predict_similar_market_up_ratio(train_df: pd.DataFrame, anchor_df: pd.DataFrame, top_n: int = 12) -> float:
    cols = [col for col in SIMILAR_FEATURE_COLUMNS if col in train_df.columns and col in anchor_df.columns]
    if not cols:
        return float(pd.to_numeric(train_df["未来5日上涨比例"], errors="coerce").mean())

    train_x = train_df[cols].replace([np.inf, -np.inf], np.nan).astype(float)
    anchor_x = anchor_df[cols].replace([np.inf, -np.inf], np.nan).astype(float)
    median = train_x.median()
    train_x = train_x.fillna(median)
    anchor_x = anchor_x.fillna(median)
    std = train_x.std().replace(0, 1.0).fillna(1.0)
    distance = ((train_x - anchor_x.iloc[0]).abs() / std).sum(axis=1)
    similar = train_df.assign(_distance=distance).sort_values("_distance").head(top_n)
    return float(pd.to_numeric(similar["未来5日上涨比例"], errors="coerce").mean())


def parse_dates(args: argparse.Namespace) -> list[pd.Timestamp]:
    dates: list[str] = []
    if args.as_of_date:
        dates.append(args.as_of_date)
    if args.test_dates:
        dates.extend([item.strip() for item in args.test_dates.split(",") if item.strip()])
    if not dates:
        raise SystemExit("必须提供 --as-of-date 或 --test-dates")
    return [pd.to_datetime(item) for item in dates]


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.data_source == "split":
        stock_df = load_split_samples(Path(args.base_csv).resolve(), Path(args.feature_csv).resolve())
    else:
        stock_df = load_stock_samples(Path(args.sample_csv).resolve())
    market_df = make_market_samples(stock_df)
    market_sample_csv = Path(args.market_sample_csv).resolve()
    market_sample_csv.parent.mkdir(parents=True, exist_ok=True)
    market_out = market_df.copy()
    for col in ["日期", "卖出日"]:
        market_out[col] = pd.to_datetime(market_out[col], errors="coerce").dt.strftime("%Y-%m-%d")
    market_out.to_csv(market_sample_csv, index=False, encoding="utf-8-sig")

    feature_cols = build_feature_columns(market_df)
    ensemble_windows = parse_ensemble_windows(args.ensemble_windows)
    rows = [
        predict_one(
            market_df,
            as_of_date,
            feature_cols,
            args.min_train_days,
            args.train_window_days,
            args.target_up_ratio,
            args.decision_mode,
            ensemble_windows,
            args.neutral_low,
            args.neutral_high,
        )
        for as_of_date in parse_dates(args)
    ]
    result = pd.DataFrame(rows)
    for col in [
        "预测市场上涨概率",
        "预测未来5日上涨比例",
        "相似市场预测上涨比例",
        "机会模型强上涨概率",
        "风险模型强下跌概率",
        "融合预测上涨比例",
        "实际未来5日上涨比例",
    ]:
        result[col] = result[col].map(lambda value: "" if pd.isna(value) else f"{value:.2%}")

    start_tag = rows[0]["锚点日期"].replace("-", "")
    end_tag = rows[-1]["锚点日期"].replace("-", "")
    if len(rows) == 1:
        result_path = output_dir / f"06_市场5日方向预测结果_{start_tag}.csv"
    else:
        result_path = output_dir / f"06_市场5日方向预测结果汇总_{start_tag}_{end_tag}.csv"
    result.to_csv(result_path, index=False, encoding="utf-8-sig")

    judged_rows = [row for row in rows if pd.notna(row["市场方向预测是否准确"])]
    accuracy = (
        sum(row["市场方向预测是否准确"] for row in judged_rows) / len(judged_rows)
        if judged_rows
        else np.nan
    )
    stats = pd.DataFrame(
        [
            {
                "测试日期数": len(rows),
                "可判卷日期数": len(judged_rows),
                "预测正确日期数": int(sum(row["市场方向预测是否准确"] for row in judged_rows)) if judged_rows else 0,
                "市场方向预测准确率": "" if pd.isna(accuracy) else f"{accuracy:.2%}",
                "平均训练天数": round(float(np.mean([row["训练天数"] for row in rows])), 2),
                "特征数量": int(len(feature_cols)),
            }
        ]
    )
    stats_path = output_dir / f"06_市场5日方向预测准确率统计_{start_tag}_{end_tag}.csv"
    stats.to_csv(stats_path, index=False, encoding="utf-8-sig")

    print(f"市场样本: {market_sample_csv}")
    print(f"预测结果: {result_path}")
    print(f"准确率统计: {stats_path}")
    print(result.to_string(index=False))
    print(stats.to_string(index=False))


if __name__ == "__main__":
    main()
