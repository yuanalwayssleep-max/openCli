#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DAILY_DIR = ROOT / "outputs" / "daily_k_30_40_20260513" / "日K线目录"
DEFAULT_META_CSV = ROOT / "outputs" / "daily_k_30_40_20260513" / "symbols_30_40_20260513_剔除创业板科创.csv"
DEFAULT_OUTPUT_DIR = ROOT / "skills" / "a-share-kline-return-modeling" / "outputs"
HOLD_DAYS = 5
RETURN_TOLERANCE = 0.05
DAILY_DIRECTION_TARGET = 0.75


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基于历史日K预测未来5个交易日收益率")
    parser.add_argument("--daily-dir", default=str(DEFAULT_DAILY_DIR), help="日K目录")
    parser.add_argument("--meta-csv", default=str(DEFAULT_META_CSV), help="股票元数据CSV")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--exclude-beijing", action="store_true", help="剔除北交所")
    parser.add_argument("--min-history", type=int, default=60, help="单只股票最少历史天数")
    parser.add_argument("--min-train-samples", type=int, default=200, help="单个锚点日最少训练样本数")
    parser.add_argument("--model-iterations", type=int, default=80, help="单次模型训练迭代轮数")
    parser.add_argument(
        "--as-of-date",
        default="",
        help="指定锚点日期，格式 YYYY-MM-DD；只输出该锚点日全部股票预测",
    )
    parser.add_argument(
        "--rolling-backtest",
        action="store_true",
        help="滚动锚点回测，输出每只股票预测结果和每天预测准确率统计",
    )
    parser.add_argument(
        "--anchor-start-date",
        default="",
        help="滚动回测锚点开始日期，格式 YYYY-MM-DD；为空则从可训练的最早日期开始",
    )
    parser.add_argument(
        "--anchor-end-date",
        default="",
        help="滚动回测锚点截止日期，格式 YYYY-MM-DD；例如 2026-05-06 表示只预测到该日",
    )
    return parser.parse_args()


def safe_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return np.nan


def load_meta(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {row["代码"]: row for row in csv.DictReader(f)}


def compute_streak(series: pd.Series) -> pd.Series:
    streak = []
    current = 0
    prev_sign = 0
    for value in series.fillna(0):
        sign = 1 if value > 0 else -1 if value < 0 else 0
        if sign == 0:
            current = 0
        elif sign == prev_sign:
            current += sign
        else:
            current = sign
        streak.append(current)
        prev_sign = sign
    return pd.Series(streak, index=series.index)


def rolling_pct_rank(series: pd.Series, window: int) -> pd.Series:
    """当前值在过去window个交易日中的分位，只使用当前及历史数据。"""

    return series.rolling(window, min_periods=max(5, window // 2)).apply(
        lambda values: pd.Series(values).rank(pct=True).iloc[-1],
        raw=False,
    )


def enrich_one_stock(df: pd.DataFrame, code: str, meta: dict[str, str]) -> pd.DataFrame:
    df = df.copy()
    df["代码"] = code
    df["名称"] = meta.get("名称", "")
    df["行业"] = meta.get("行业", "")
    df["板块"] = meta.get("板块", "")
    df["交易所"] = meta.get("交易所", "")
    df["日期"] = pd.to_datetime(df["日期"])

    numeric_cols = ["开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].map(safe_float)

    df = (
        df.dropna(subset=["开盘", "收盘", "最高", "最低", "成交量", "成交额"])
        .sort_values("日期")
        .reset_index(drop=True)
    )

    close = df["收盘"]
    open_ = df["开盘"]
    high = df["最高"]
    low = df["最低"]
    vol = df["成交量"]
    amount = df["成交额"]
    ret = close.pct_change()
    prev_close = close.shift(1)

    for n in [1, 3, 5, 10, 20]:
        df[f"ret_{n}"] = close.pct_change(n)
    for n in [5, 10, 20, 30, 60]:
        ma = close.rolling(n).mean()
        df[f"ma_{n}"] = ma
        df[f"close_ma_ratio_{n}"] = close / ma - 1

    df["ma5_ma10_gap"] = df["ma_5"] / df["ma_10"] - 1
    df["ma10_ma20_gap"] = df["ma_10"] / df["ma_20"] - 1

    for n in [5, 10, 20]:
        df[f"vol_ratio_{n}"] = vol / vol.rolling(n).mean()
        df[f"amount_ratio_{n}"] = amount / amount.rolling(n).mean()
        df[f"volatility_{n}"] = ret.rolling(n).std()
        df[f"amp_mean_{n}"] = df["振幅"].rolling(n).mean()
        df[f"up_volume_expand_count_{n}"] = ((ret > 0) & (vol > vol.shift(1))).rolling(n).sum()
        df[f"down_volume_expand_count_{n}"] = ((ret < 0) & (vol > vol.shift(1))).rolling(n).sum()
        df[f"up_volume_shrink_count_{n}"] = ((ret > 0) & (vol < vol.shift(1))).rolling(n).sum()
        df[f"down_volume_shrink_count_{n}"] = ((ret < 0) & (vol < vol.shift(1))).rolling(n).sum()

    df["vol_change_1"] = vol.pct_change()
    df["amount_change_1"] = amount.pct_change()
    df["open_to_close_pct"] = open_ / close.replace(0, np.nan) - 1
    df["high_to_close_pct"] = high / close.replace(0, np.nan) - 1
    df["low_to_close_pct"] = low / close.replace(0, np.nan) - 1
    df["volume_hist_rank_20"] = rolling_pct_rank(vol, 20)
    df["amount_hist_rank_20"] = rolling_pct_rank(amount, 20)
    df["turnover_bias_20"] = df["换手率"] / df["换手率"].rolling(20).mean().replace(0, np.nan) - 1
    df["price_volume_same_direction"] = np.where(ret * df["vol_change_1"] > 0, 1.0, 0.0)
    df["price_up_volume_expand"] = np.where((ret > 0) & (df["vol_change_1"] > 0), 1.0, 0.0)
    df["price_up_volume_shrink"] = np.where((ret > 0) & (df["vol_change_1"] < 0), 1.0, 0.0)
    df["price_down_volume_expand"] = np.where((ret < 0) & (df["vol_change_1"] > 0), 1.0, 0.0)
    df["price_down_volume_shrink"] = np.where((ret < 0) & (df["vol_change_1"] < 0), 1.0, 0.0)
    df["vol_ma5_ma20_gap"] = vol.rolling(5).mean() / vol.rolling(20).mean() - 1
    df["amount_ma5_ma20_gap"] = amount.rolling(5).mean() / amount.rolling(20).mean() - 1
    df["ret_5_vol_ratio_5"] = df["ret_5"] * df["vol_ratio_5"]
    df["ret_5_amount_ratio_5"] = df["ret_5"] * df["amount_ratio_5"]
    df["price_volume_divergence"] = np.select(
        [
            (df["ret_5"] > 0.03) & (df["vol_ma5_ma20_gap"] < -0.10),
            (df["ret_5"] < -0.03) & (df["vol_ma5_ma20_gap"] > 0.10),
        ],
        [-1.0, 1.0],
        default=0.0,
    )

    df["body_pct"] = (close - open_) / open_.replace(0, np.nan)
    df["upper_shadow_pct"] = (high - np.maximum(close, open_)) / open_.replace(0, np.nan)
    df["lower_shadow_pct"] = (np.minimum(close, open_) - low) / open_.replace(0, np.nan)
    day_range = (high - low).replace(0, np.nan)
    df["open_gap_pct"] = open_ / prev_close.replace(0, np.nan) - 1
    df["intraday_return_pct"] = close / open_.replace(0, np.nan) - 1
    df["high_prev_close_pct"] = high / prev_close.replace(0, np.nan) - 1
    df["low_prev_close_pct"] = low / prev_close.replace(0, np.nan) - 1
    df["close_position_in_day"] = (close - low) / day_range
    df["close_to_high_pct"] = close / high.replace(0, np.nan) - 1
    df["close_to_low_pct"] = close / low.replace(0, np.nan) - 1
    df["upper_shadow_range_ratio"] = (high - np.maximum(close, open_)) / day_range
    df["lower_shadow_range_ratio"] = (np.minimum(close, open_) - low) / day_range
    df["body_range_ratio"] = (close - open_).abs() / day_range
    df["weak_close_with_upper_shadow"] = np.where(
        (df["close_position_in_day"] < 0.45) & (df["upper_shadow_range_ratio"] > 0.35),
        1.0,
        0.0,
    )
    df["gap_up_weak_close"] = np.where(
        (df["open_gap_pct"] > 0.01) & (df["intraday_return_pct"] < -0.005),
        1.0,
        0.0,
    )
    df["green_days_5"] = (close > open_).rolling(5).sum()
    df["red_days_5"] = (close < open_).rolling(5).sum()
    df["ret_streak"] = compute_streak(ret)

    for n in [10, 20, 30, 60]:
        rolling_high = high.rolling(n).max()
        rolling_low = low.rolling(n).min()
        denom = (rolling_high - rolling_low).replace(0, np.nan)
        df[f"dist_high_{n}"] = close / rolling_high - 1
        df[f"dist_low_{n}"] = close / rolling_low - 1
        df[f"range_pos_{n}"] = (close - rolling_low) / denom

    df["ret_5_rank_20"] = rolling_pct_rank(df["ret_5"], 20)
    df["volatility_10_rank_20"] = rolling_pct_rank(df["volatility_10"], 20)

    df["breakout_10"] = (close >= high.shift(1).rolling(10).max()).astype(float)
    df["breakout_20"] = (close >= high.shift(1).rolling(20).max()).astype(float)
    df["drawdown_20"] = close / close.rolling(20).max() - 1
    df["near_20d_high_weak_close"] = np.where(
        (df["range_pos_20"] > 0.8) & (df["close_position_in_day"] < 0.5),
        1.0,
        0.0,
    )
    df["overheat_5d"] = np.where(
        (df["ret_5"] > 0.08) & (df["range_pos_20"] > 0.75),
        1.0,
        0.0,
    )
    df["volume_expand_weak_close"] = np.where(
        (df["vol_ratio_5"] > 1.4) & (df["close_position_in_day"] < 0.45),
        1.0,
        0.0,
    )
    df["price_up_volume_down_5d"] = np.where(
        (df["ret_5"] > 0.03) & (df["vol_ma5_ma20_gap"] < -0.1),
        1.0,
        0.0,
    )
    df["high_position_upper_shadow"] = df["range_pos_20"] * df["upper_shadow_range_ratio"]
    df["overheat_volume_expand"] = df["ret_5"] * df["vol_ratio_5"] * df["range_pos_20"]

    df["future_close_5"] = close.shift(-HOLD_DAYS)
    df["future_date_5"] = df["日期"].shift(-HOLD_DAYS)
    df["target_5d"] = df["future_close_5"] / close - 1
    df["label_up_5d"] = (df["target_5d"] > 0).astype(float)
    known_target = df["target_5d"].shift(HOLD_DAYS)
    known_up = df["label_up_5d"].shift(HOLD_DAYS)
    for n in [5, 10, 20, 60]:
        df[f"known_5d_up_rate_{n}"] = known_up.rolling(n).mean()
        df[f"known_5d_avg_return_{n}"] = known_target.rolling(n).mean()
        df[f"known_5d_return_volatility_{n}"] = known_target.rolling(n).std()
    df["known_last_5d_return"] = known_target
    df["known_last_5d_up"] = known_up
    return df


def load_all_samples(
    daily_dir: Path,
    meta_map: dict[str, dict[str, str]],
    exclude_beijing: bool,
    min_history: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for fp in sorted(daily_dir.glob("*_daily_k.csv")):
        code = fp.name.split("_")[0]
        meta = meta_map.get(code)
        if not meta:
            continue
        if exclude_beijing and (code.startswith(("4", "8", "9")) or meta.get("交易所") == "北交所"):
            continue
        if "ST" in meta.get("名称", "").upper():
            continue
        df = pd.read_csv(fp, encoding="utf-8-sig")
        if len(df) < min_history:
            continue
        frames.append(enrich_one_stock(df, code, meta))
    if not frames:
        raise RuntimeError("未加载到可用样本")

    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.sort_values(["日期", "代码"]).reset_index(drop=True)

    # 默认剔除今天未收盘或未确认的最新交易日，避免把未完成K线带入训练和验证。
    max_date = pd.to_datetime(all_df["日期"]).max()
    today_local = pd.Timestamp(date.today())
    if pd.notna(max_date) and max_date.normalize() >= today_local.normalize():
        all_df = all_df[all_df["日期"] < max_date].copy()

    return all_df.reset_index(drop=True)


def add_cross_sectional_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rank_cols = [
        "收盘",
        "成交额",
        "成交量",
        "涨跌幅",
        "振幅",
        "换手率",
        "ret_5",
        "ret_20",
        "vol_ratio_5",
        "amount_ratio_5",
        "range_pos_20",
        "upper_shadow_range_ratio",
        "close_position_in_day",
        "close_ma_ratio_5",
        "known_5d_up_rate_20",
        "known_5d_avg_return_20",
        "known_last_5d_return",
    ]
    for col in rank_cols:
        if col in out.columns:
            out[f"{col}_pct_rank"] = out.groupby("日期")[col].rank(pct=True)
    return out


def add_market_and_industry_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    daily_market = out.groupby("日期").agg(
        全市场平均涨跌幅=("涨跌幅", "mean"),
        全市场上涨比例=("涨跌幅", lambda s: float((s > 0).mean())),
        全市场平均成交额=("成交额", "mean"),
        全市场平均换手率=("换手率", "mean"),
        全市场平均振幅=("振幅", "mean"),
    )
    out = out.merge(daily_market, left_on="日期", right_index=True, how="left")

    industry_daily = out.groupby(["日期", "行业"]).agg(
        行业平均涨跌幅=("涨跌幅", "mean"),
        行业上涨比例=("涨跌幅", lambda s: float((s > 0).mean())),
        行业平均成交额=("成交额", "mean"),
        行业平均换手率=("换手率", "mean"),
        行业股票数=("代码", "count"),
    )
    out = out.merge(industry_daily, left_on=["日期", "行业"], right_index=True, how="left")
    out["行业涨跌幅_pct_rank"] = out.groupby("日期")["行业平均涨跌幅"].rank(pct=True)
    out["行业上涨比例_pct_rank"] = out.groupby("日期")["行业上涨比例"].rank(pct=True)
    out["行业成交额_pct_rank"] = out.groupby("日期")["行业平均成交额"].rank(pct=True)
    out["个股强于行业"] = out["涨跌幅"] - out["行业平均涨跌幅"]
    out["个股成交额强于行业"] = out["成交额"] / out["行业平均成交额"].replace(0, np.nan) - 1
    return out


def _add_rank_bucket(out: pd.DataFrame, rank_col: str, bucket_col: str, bucket_count: int = 5) -> None:
    if rank_col not in out.columns:
        return
    rank = pd.to_numeric(out[rank_col], errors="coerce")
    bucket = np.ceil(rank * bucket_count).clip(1, bucket_count)
    out[bucket_col] = bucket.astype("Int64")


def _merge_historical_group_stats(
    out: pd.DataFrame,
    group_col: str,
    prefix: str,
) -> pd.DataFrame:
    if group_col not in out.columns:
        return out

    stats = (
        out.dropna(subset=[group_col])
        .groupby(["日期", group_col], dropna=False)
        .agg(
            当日分组上涨数=("label_up_5d", "sum"),
            当日分组样本数=("label_up_5d", "count"),
            当日分组收益和=("target_5d", "sum"),
        )
        .reset_index()
        .sort_values([group_col, "日期"])
    )
    grouped = stats.groupby(group_col, dropna=False)
    stats["历史分组上涨数"] = grouped["当日分组上涨数"].cumsum() - stats["当日分组上涨数"]
    stats["历史分组样本数"] = grouped["当日分组样本数"].cumsum() - stats["当日分组样本数"]
    stats["历史分组收益和"] = grouped["当日分组收益和"].cumsum() - stats["当日分组收益和"]
    stats[f"{prefix}历史5日上涨率"] = stats["历史分组上涨数"] / stats["历史分组样本数"].replace(0, np.nan)
    stats[f"{prefix}历史5日平均收益"] = stats["历史分组收益和"] / stats["历史分组样本数"].replace(0, np.nan)
    stats[f"{prefix}历史样本数"] = stats["历史分组样本数"]

    keep_cols = ["日期", group_col, f"{prefix}历史5日上涨率", f"{prefix}历史5日平均收益", f"{prefix}历史样本数"]
    return out.merge(stats[keep_cols], on=["日期", group_col], how="left")


def add_peer_history_features(df: pd.DataFrame) -> pd.DataFrame:
    """增加同类历史5日表现特征。

    每行只使用该日期之前的同分组历史统计，不使用当天自身的未来5日结果。
    分组依据来自锚点日已知的横截面分位或行业字段。
    """
    out = df.copy()
    out["日期"] = pd.to_datetime(out["日期"], errors="coerce")

    bucket_specs = [
        ("收盘_pct_rank", "价格分位档"),
        ("成交额_pct_rank", "成交额分位档"),
        ("成交量_pct_rank", "成交量分位档"),
        ("换手率_pct_rank", "换手率分位档"),
        ("涨跌幅_pct_rank", "当日涨跌幅分位档"),
        ("ret_5_pct_rank", "近5日涨幅分位档"),
        ("ret_20_pct_rank", "近20日涨幅分位档"),
        ("vol_ratio_5_pct_rank", "5日量比分位档"),
        ("amount_ratio_5_pct_rank", "5日金额比分位档"),
        ("振幅_pct_rank", "振幅分位档"),
        ("range_pos_20_pct_rank", "20日位置分位档"),
        ("upper_shadow_range_ratio_pct_rank", "上影线分位档"),
    ]
    for rank_col, bucket_col in bucket_specs:
        _add_rank_bucket(out, rank_col, bucket_col)

    group_specs = [
        ("价格分位档", "同价格档"),
        ("成交额分位档", "同成交额档"),
        ("成交量分位档", "同成交量档"),
        ("换手率分位档", "同换手率档"),
        ("当日涨跌幅分位档", "同当日涨跌幅档"),
        ("近5日涨幅分位档", "同近5日涨幅档"),
        ("近20日涨幅分位档", "同近20日涨幅档"),
        ("5日量比分位档", "同5日量比档"),
        ("5日金额比分位档", "同5日金额比档"),
        ("振幅分位档", "同振幅档"),
        ("20日位置分位档", "同20日位置档"),
        ("上影线分位档", "同上影线档"),
        ("行业", "同行业"),
    ]
    for group_col, prefix in group_specs:
        out = _merge_historical_group_stats(out, group_col, prefix)

    return out


def build_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = {
        "日期",
        "代码",
        "名称",
        "行业",
        "板块",
        "交易所",
        "future_close_5",
        "future_date_5",
        "target_5d",
        "label_up_5d",
    }
    return [col for col in df.columns if col not in excluded and pd.api.types.is_numeric_dtype(df[col])]


def prepare_xy(df: pd.DataFrame, feature_cols: list[str], target_col: str) -> tuple[pd.DataFrame, pd.Series]:
    clean = df.dropna(subset=feature_cols + [target_col]).copy()
    X = clean[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y = clean[target_col]
    return X, y


def balanced_binary_weights(y: pd.Series) -> np.ndarray:
    counts = y.value_counts()
    if len(counts) < 2:
        return np.ones(len(y))
    total = len(y)
    return y.map({label: total / (2 * count) for label, count in counts.items()}).to_numpy()


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

    _, clf_model = build_models(model_iterations)
    clf_model.fit(X_core, y_core, sample_weight=balanced_binary_weights(y_core))
    valid_clean["prob"] = clf_model.predict_proba(X_valid)[:, 1]
    valid_clean["actual"] = y_valid.to_numpy()

    best_threshold = 0.5
    best_daily_accuracy = -1.0
    for threshold in np.arange(0.35, 0.651, 0.01):
        valid_clean["pred"] = (valid_clean["prob"] >= threshold).astype(int)
        daily_accuracy = valid_clean.groupby("日期").apply(lambda g: (g["pred"] == g["actual"]).mean()).mean()
        if pd.notna(daily_accuracy) and daily_accuracy > best_daily_accuracy:
            best_daily_accuracy = float(daily_accuracy)
            best_threshold = float(threshold)
    return best_threshold


def build_models(model_iterations: int) -> tuple[HistGradientBoostingRegressor, HistGradientBoostingClassifier]:
    reg_model = HistGradientBoostingRegressor(
        learning_rate=0.05,
        max_depth=6,
        max_iter=model_iterations,
        min_samples_leaf=20,
        l2_regularization=0.1,
        random_state=42,
    )
    clf_model = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_depth=6,
        max_iter=model_iterations,
        min_samples_leaf=20,
        l2_regularization=0.1,
        random_state=42,
    )
    return reg_model, clf_model


def run_anchor_once(
    full_df: pd.DataFrame,
    as_of_date: pd.Timestamp,
    min_train_samples: int,
    model_iterations: int,
    confidence_threshold: float,
    min_signal_abs_return: float,
) -> tuple[pd.DataFrame, int]:
    train_df = full_df[
        (full_df["日期"] < as_of_date)
        & full_df["target_5d"].notna()
        & (full_df["future_date_5"] <= as_of_date)
    ].copy()
    if len(train_df) < min_train_samples:
        raise RuntimeError(f"锚点日 {as_of_date.strftime('%Y-%m-%d')} 训练样本不足: {len(train_df)}")

    feature_cols = build_feature_columns(train_df)
    X_train, y_train_reg = prepare_xy(train_df, feature_cols, "target_5d")
    _, y_train_clf = prepare_xy(train_df, feature_cols, "label_up_5d")

    reg_model, clf_model = build_models(model_iterations)
    reg_model.fit(X_train, y_train_reg)
    clf_model.fit(X_train, y_train_clf)

    anchor_df = full_df[full_df["日期"] == as_of_date].copy()
    if anchor_df.empty:
        raise RuntimeError(f"未找到锚点日期 {as_of_date.strftime('%Y-%m-%d')} 的样本")

    X_anchor = anchor_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    anchor_df["预测5日收益率"] = reg_model.predict(X_anchor)
    anchor_df["预测上涨概率"] = clf_model.predict_proba(X_anchor)[:, 1]
    anchor_df["方向置信度"] = np.maximum(anchor_df["预测上涨概率"], 1 - anchor_df["预测上涨概率"])
    anchor_df["预测涨跌"] = np.where(anchor_df["预测上涨概率"] >= 0.5, "上涨", "下跌")
    anchor_df["是否高置信预测"] = np.where(
        (anchor_df["方向置信度"] >= confidence_threshold)
        & (anchor_df["预测5日收益率"].abs() >= min_signal_abs_return),
        1,
        0,
    )
    anchor_df["实际5日收益率"] = anchor_df["target_5d"]
    anchor_df["实际涨跌"] = np.where(
        anchor_df["实际5日收益率"].notna(),
        np.where(anchor_df["实际5日收益率"] > 0, "上涨", "下跌"),
        "",
    )
    anchor_df["涨跌预测是否准确"] = np.where(
        anchor_df["实际5日收益率"].notna(),
        np.where((anchor_df["预测涨跌"] == anchor_df["实际涨跌"]), 1, 0),
        np.nan,
    )
    anchor_df["涨跌幅度差值"] = np.where(
        anchor_df["实际5日收益率"].notna(),
        np.abs(anchor_df["预测5日收益率"] - anchor_df["实际5日收益率"]),
        np.nan,
    )
    anchor_df["涨跌幅度预测是否准确"] = np.where(
        anchor_df["涨跌幅度差值"].notna(),
        np.where(anchor_df["涨跌幅度差值"] <= RETURN_TOLERANCE, 1, 0),
        np.nan,
    )
    anchor_df["综合评分"] = anchor_df["预测5日收益率"] * 100
    anchor_df["未来卖出日期"] = anchor_df["future_date_5"]
    anchor_df["锚点日期"] = as_of_date
    anchor_df["训练样本数"] = len(X_train)

    ordered = [
        "锚点日期",
        "训练样本数",
        "日期",
        "代码",
        "名称",
        "行业",
        "收盘",
        "预测5日收益率",
        "预测上涨概率",
        "方向置信度",
        "预测涨跌",
        "是否高置信预测",
        "实际5日收益率",
        "实际涨跌",
        "涨跌预测是否准确",
        "涨跌幅度差值",
        "涨跌幅度预测是否准确",
        "综合评分",
        "未来卖出日期",
    ]
    anchor_df = anchor_df[ordered].sort_values(["综合评分", "代码"], ascending=[False, True]).reset_index(drop=True)
    return anchor_df, len(X_train)


def summarize_daily_accuracy(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for anchor_date, group in predictions.groupby("锚点日期", sort=True):
        actual_group = group[group["实际5日收益率"].notna()].copy()
        direction_acc = actual_group["涨跌预测是否准确"].mean() if not actual_group.empty else np.nan
        magnitude_acc = actual_group["涨跌幅度预测是否准确"].mean() if not actual_group.empty else np.nan
        signal_group = actual_group[actual_group["是否高置信预测"] == 1].copy()
        signal_direction_acc = signal_group["涨跌预测是否准确"].mean() if not signal_group.empty else np.nan
        signal_magnitude_acc = signal_group["涨跌幅度预测是否准确"].mean() if not signal_group.empty else np.nan
        rows.append(
            {
                "锚点日期": pd.to_datetime(anchor_date).strftime("%Y-%m-%d"),
                "训练样本数": int(group["训练样本数"].iloc[0]),
                "股票数量": int(len(group)),
                "有实际结果股票数": int(len(actual_group)),
                "全量涨跌预测准确率": "" if pd.isna(direction_acc) else f"{direction_acc:.2%}",
                "全量涨跌幅度预测准确率": "" if pd.isna(magnitude_acc) else f"{magnitude_acc:.2%}",
                "高置信预测股票数": int(len(signal_group)),
                "高置信涨跌预测准确率": "" if pd.isna(signal_direction_acc) else f"{signal_direction_acc:.2%}",
                "高置信涨跌幅度预测准确率": "" if pd.isna(signal_magnitude_acc) else f"{signal_magnitude_acc:.2%}",
            }
        )
    return pd.DataFrame(rows)


def save_prediction_outputs(predictions: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_anchor = pd.to_datetime(predictions["锚点日期"], errors="coerce").max()
    if pd.isna(latest_anchor):
        date_tag = pd.Timestamp.today().strftime("%Y%m%d")
    else:
        date_tag = latest_anchor.strftime("%Y%m%d")

    per_stock_path = output_dir / f"01_每只股票预测结果_{date_tag}.csv"
    daily_stats_path = output_dir / f"02_每天预测准确率统计_{date_tag}.csv"

    out = predictions.copy()
    for col in ["锚点日期", "日期", "未来卖出日期"]:
        out[col] = pd.to_datetime(out[col], errors="coerce").dt.strftime("%Y-%m-%d")

    out.to_csv(per_stock_path, index=False, encoding="utf-8-sig")
    summarize_daily_accuracy(predictions).to_csv(daily_stats_path, index=False, encoding="utf-8-sig")


def rolling_backtest(
    full_df: pd.DataFrame,
    min_train_samples: int,
    model_iterations: int,
    confidence_threshold: float,
    min_signal_abs_return: float,
    anchor_start_date: pd.Timestamp | None = None,
    anchor_end_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    anchor_dates = sorted(pd.to_datetime(full_df["日期"]).dropna().unique())
    frames: list[pd.DataFrame] = []
    for anchor_date in anchor_dates:
        anchor_ts = pd.to_datetime(anchor_date)
        if anchor_start_date is not None and anchor_ts < anchor_start_date:
            continue
        if anchor_end_date is not None and anchor_ts > anchor_end_date:
            continue
        eligible = full_df[
            (full_df["日期"] < anchor_ts)
            & full_df["target_5d"].notna()
            & (full_df["future_date_5"] <= anchor_ts)
        ]
        if len(eligible) < min_train_samples:
            continue
        try:
            print(f"running anchor {anchor_ts.strftime('%Y-%m-%d')} train_samples={len(eligible)}", flush=True)
            anchor_df, _ = run_anchor_once(
                full_df,
                anchor_ts,
                min_train_samples,
                model_iterations,
                confidence_threshold,
                min_signal_abs_return,
            )
        except Exception:
            continue
        frames.append(anchor_df)
    if not frames:
        raise RuntimeError("未生成任何滚动回测结果，请检查样本量或最小训练样本设置")
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    args = parse_args()
    daily_dir = Path(args.daily_dir).resolve()
    meta_csv = Path(args.meta_csv).resolve()
    output_dir = Path(args.output_dir).resolve()

    meta_map = load_meta(meta_csv)
    full_df = load_all_samples(daily_dir, meta_map, args.exclude_beijing, args.min_history)
    full_df = add_cross_sectional_features(full_df)
    full_df = add_market_and_industry_features(full_df)
    full_df["日期"] = pd.to_datetime(full_df["日期"])

    if args.as_of_date:
        as_of_date = pd.to_datetime(args.as_of_date)
        anchor_df, train_size = run_anchor_once(
            full_df,
            as_of_date,
            args.min_train_samples,
            args.model_iterations,
            args.confidence_threshold,
            args.min_signal_abs_return,
        )
        save_prediction_outputs(anchor_df, output_dir)
        print(f"锚点日期: {as_of_date.strftime('%Y-%m-%d')}")
        print(f"训练样本数: {train_size}")
        date_tag = as_of_date.strftime("%Y%m%d")
        print(f"已输出: {output_dir / f'01_每只股票预测结果_{date_tag}.csv'}")
        print(f"已输出: {output_dir / f'02_每天预测准确率统计_{date_tag}.csv'}")
        return

    # 默认走滚动锚点回测，产出全量每只股票预测结果 + 每天预测准确率统计。
    anchor_start = pd.to_datetime(args.anchor_start_date) if args.anchor_start_date else None
    anchor_end = pd.to_datetime(args.anchor_end_date) if args.anchor_end_date else None
    predictions = rolling_backtest(
        full_df,
        args.min_train_samples,
        args.model_iterations,
        args.confidence_threshold,
        args.min_signal_abs_return,
        anchor_start,
        anchor_end,
    )
    save_prediction_outputs(predictions, output_dir)
    latest_anchor = pd.to_datetime(predictions["锚点日期"], errors="coerce").max()
    date_tag = latest_anchor.strftime("%Y%m%d")
    print(f"已输出: {output_dir / f'01_每只股票预测结果_{date_tag}.csv'}")
    print(f"已输出: {output_dir / f'02_每天预测准确率统计_{date_tag}.csv'}")
    print(f"预测记录数: {len(predictions)}")


if __name__ == "__main__":
    main()
