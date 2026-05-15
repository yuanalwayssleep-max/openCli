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
    parser = argparse.ArgumentParser(description="用市场风险标签修正个股5日方向预测")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="skill输出目录")
    parser.add_argument("--dates", default=DEFAULT_DATES, help="预测结果日期标签，逗号分隔，格式YYYYMMDD")
    parser.add_argument("--prediction-suffix", default="", help="读取03预测文件的后缀，例如 _严格清洗")
    parser.add_argument("--output-suffix", default="", help="输出10修正文件的后缀，例如 _严格清洗")
    parser.add_argument(
        "--correction-policy",
        choices=["full", "high_confidence", "v15"],
        default="v15",
        help="修正策略：full=原完整规则；high_confidence=旧高置信修正；v15=跨年稳定版高置信修正",
    )
    parser.add_argument("--label-csv", default="00_5日涨跌方向预测样本明细.csv", help="5日标签样本文件名")
    parser.add_argument("--feature-csv", default="00_5日方向模型特征表.csv", help="5日方向特征文件名")
    parser.add_argument("--overheat-threshold", type=float, default=0.80, help="过热高位延伸环境下保留上涨预测的最低上涨概率")
    parser.add_argument("--noise-threshold", type=float, default=0.02, help="实际5日涨跌幅绝对值小于等于该值时作为噪声样本剔除，默认0.02即2%")
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


def is_extended_overheat(row: pd.Series, overheat_threshold: float) -> bool:
    if row["市场风险标签"] != "过热回落高":
        return False
    if float(row["预测上涨概率"]) >= overheat_threshold:
        return False

    large_cap_extended = row.get("沪深300_20日涨跌幅", 0) >= 0.08 and row.get("中证1000_20日涨跌幅", 0) >= 0.10
    all_size_at_high = (
        row.get("沪深300_20日位置", 0) >= 0.98
        and row.get("中证500_20日位置", 0) >= 0.98
        and row.get("中证1000_20日位置", 0) >= 0.98
    )
    return bool(large_cap_extended or all_size_at_high)


def is_extreme_full_position_overheat_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "过热回落高"
        and row["预测涨跌"] == "上涨"
        and row.get("连续上涨天数", 0) >= 4
        and row.get("上证指数_20日涨跌幅", 0) >= 0.07
        and row.get("沪深300_20日涨跌幅", 0) >= 0.09
        and row.get("中证500_20日涨跌幅", 0) >= 0.14
        and row.get("中证1000_20日涨跌幅", 0) >= 0.14
        and row.get("上证指数_20日位置", 0) >= 0.99
        and row.get("沪深300_20日位置", 0) >= 0.90
        and row.get("中证500_20日位置", 0) >= 0.99
        and row.get("中证1000_20日位置", 0) >= 0.99
    )


def is_breakdown_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row.get("当日上涨比例", 1) < 0.45
        and row.get("当日平均涨跌幅", 0) < 0
        and row.get("上证指数_10日涨跌幅", 0) < 0
        and row.get("上证指数_20日位置", 1) < 0.15
    )


def is_panic_weak_downtrend(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "恐慌释放高+弱势延续高"
        and row.get("沪深300_20日涨跌幅", 0) < 0
        and row.get("中证500_20日涨跌幅", 0) < 0
        and row.get("中证1000_20日涨跌幅", 0) < 0
    )


def is_weak_rebound_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row.get("当日上涨比例", 0) > 0.70
        and row.get("当日平均涨跌幅", 0) > 1.0
        and row.get("上证指数_10日涨跌幅", 0) < -0.03
        and row.get("中证500_20日涨跌幅", 0) < 0
        and row.get("中证1000_20日涨跌幅", 0) < 0
    )


def is_weak_continuation_downtrend(row: pd.Series) -> bool:
    return bool(
        row.get("弱势延续风险特征", 0) >= 3
        and row.get("当日上涨比例", 1) < 0.25
        and row.get("当日平均涨跌幅", 0) < -1.0
        and row.get("中证500_20日涨跌幅", 0) < 0
        and row.get("中证1000_20日涨跌幅", 0) < 0
    )


def is_weak_trend_second_rebound_failure(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "上涨"
        and row.get("弱势延续风险特征", 0) >= 3
        and row.get("过热回落风险特征", 0) >= 2
        and row.get("连续上涨天数", 0) >= 2
        and row.get("当日上涨比例", 0) >= 0.68
        and row.get("行业强涨比例_1pct", 0) >= 0.55
        and row.get("上证指数_20日涨跌幅", 0) < 0
        and row.get("沪深300_20日涨跌幅", 0) < 0
        and row.get("中证500_20日涨跌幅", 0) < 0
        and row.get("中证1000_20日涨跌幅", 0) < 0
        and 0.45 <= row.get("中证500_20日位置", 0) <= 0.65
        and 0.40 <= row.get("中证1000_20日位置", 0) <= 0.60
    )


def is_weak_false_rebound_risk(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "上涨"
        and row.get("弱势延续风险特征", 0) >= 3
        and 0.50 <= row.get("当日上涨比例", 0) <= 0.75
        and row.get("当日平均涨跌幅", 0) > 1.50
        and row.get("上证指数_20日涨跌幅", 0) < 0
        and row.get("沪深300_20日涨跌幅", 0) < 0
        and row.get("中证500_20日涨跌幅", 0) < 0
        and row.get("中证1000_20日涨跌幅", 0) < 0
        and row.get("中证500_20日位置", 1) < 0.20
        and row.get("中证1000_20日位置", 1) < 0.20
    )


def is_weak_down_day_low_confidence_risk(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "上涨"
        and row["市场风险标签"] == "弱势延续高"
        and 0.345 <= float(row["预测上涨概率"]) < 0.55
        and row.get("当日上涨比例", 1) < 0.25
        and row.get("当日平均涨跌幅", 0) < -1.0
        and row.get("行业强跌比例_1pct", 0) >= 0.50
        and row.get("连续弱势天数", 99) <= 1
    )


def is_weak_rebound_industry_lag_risk(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "上涨"
        and row.get("弱势延续风险特征", 0) >= 3
        and row.get("当日上涨比例", 0) > 0.85
        and row.get("中证500_20日涨跌幅", 0) < 0
        and row.get("个股强于行业", 0) < 0
        and float(row["预测上涨概率"]) < 0.62
    )


def is_high_level_weak_rise_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row["预测涨跌"] == "上涨"
        and float(row["预测上涨概率"]) < 0.50
        and row.get("上证指数_20日位置", 0) >= 0.98
        and row.get("沪深300_20日位置", 0) >= 0.98
        and row.get("中证500_20日位置", 0) >= 0.98
        and row.get("中证1000_20日位置", 0) >= 0.98
        and row.get("上证指数_10日涨跌幅", 0) > 0.04
        and 0.55 <= row.get("当日上涨比例", 0) <= 0.65
        and 0.30 <= row.get("当日平均涨跌幅", 0) <= 1.00
        and row.get("行业强涨比例_1pct", 1) < 0.45
        and row.get("连续上涨天数", 0) >= 3
    )


def is_high_level_distribution_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row["预测涨跌"] == "上涨"
        and float(row["预测上涨概率"]) < 0.75
        and row.get("连续上涨天数", 0) >= 3
        and row.get("上证指数_10日涨跌幅", 0) > 0.04
        and row.get("上证指数_20日涨跌幅", 0) > 0.05
        and row.get("沪深300_20日涨跌幅", 0) > 0.05
        and row.get("中证500_20日涨跌幅", 0) > 0.07
        and row.get("中证1000_20日涨跌幅", 0) > 0.08
        and row.get("上证指数_20日位置", 0) >= 0.90
        and row.get("沪深300_20日位置", 0) >= 0.90
        and row.get("中证500_20日位置", 0) >= 0.95
        and row.get("中证1000_20日位置", 0) >= 0.95
        and 0.45 <= row.get("当日上涨比例", 0) <= 0.60
        and -0.10 <= row.get("当日平均涨跌幅", 0) <= 0.60
        and row.get("行业强涨比例_1pct", 1) < 0.30
    )


def is_midlevel_overheat_reversal_risk(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "上涨"
        and row.get("恐慌释放特征", 0) == 0
        and row.get("弱势延续风险特征", 0) == 0
        and row.get("过热回落风险特征", 0) >= 4
        and row.get("当日上涨比例", 0) >= 0.80
        and row.get("当日平均涨跌幅", 0) >= 1.50
        and row.get("行业强涨比例_1pct", 0) >= 0.60
        and 0.00 <= row.get("上证指数_20日涨跌幅", 0) <= 0.04
        and 0.02 <= row.get("中证500_20日涨跌幅", 0) <= 0.07
        and 0.02 <= row.get("中证1000_20日涨跌幅", 0) <= 0.07
        and 0.40 <= row.get("中证500_20日位置", 0) <= 0.70
        and 0.40 <= row.get("中证1000_20日位置", 0) <= 0.70
    )


def is_moderate_rebound_failure_risk(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "上涨"
        and row.get("过热回落风险特征", 0) >= 2
        and row.get("弱势延续风险特征", 0) == 0
        and 0.65 <= row.get("当日上涨比例", 0) <= 0.75
        and 1.00 <= row.get("当日平均涨跌幅", 0) <= 1.60
        and 0.40 <= row.get("行业强涨比例_1pct", 0) <= 0.55
        and row.get("行业强跌比例_1pct", 1) <= 0.20
        and row.get("沪深300_20日涨跌幅", 0) < 0
        and -0.005 <= row.get("上证指数_20日涨跌幅", 0) <= 0.015
        and 0.000 <= row.get("中证500_20日涨跌幅", 0) <= 0.025
        and 0.000 <= row.get("中证1000_20日涨跌幅", 0) <= 0.020
        and 0.60 <= row.get("上证指数_20日位置", 0) <= 0.80
        and 0.55 <= row.get("中证500_20日位置", 0) <= 0.75
        and 0.55 <= row.get("中证1000_20日位置", 0) <= 0.75
    )


def is_post_holiday_weak_rebound_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row["预测涨跌"] == "上涨"
        and row.get("长假后第几个交易日", 0) == 2
        and 0.55 <= row.get("当日上涨比例", 0) <= 0.72
        and 0.30 <= row.get("当日平均涨跌幅", 0) <= 1.20
        and row.get("行业强涨比例_1pct", 1) < 0.35
        and row.get("行业强跌比例_1pct", 0) < 0.20
        and row.get("连续上涨天数", 0) <= 2
        and row.get("上证指数_20日位置", 0) >= 0.85
        and row.get("中证500_20日位置", 0) >= 0.80
        and row.get("中证1000_20日位置", 0) >= 0.85
        and -0.01 <= row.get("上证指数_20日涨跌幅", 0) <= 0.03
        and 0.00 <= row.get("中证500_20日涨跌幅", 0) <= 0.05
        and 0.00 <= row.get("中证1000_20日涨跌幅", 0) <= 0.05
    )


def is_high_level_moderate_rebound_exhaustion_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row["预测涨跌"] == "上涨"
        and float(row["预测上涨概率"]) < 0.75
        and 0.50 <= row.get("当日上涨比例", 0) <= 0.65
        and 0.50 <= row.get("当日平均涨跌幅", 0) <= 1.10
        and row.get("行业强涨比例_1pct", 1) < 0.42
        and row.get("连续上涨天数", 99) <= 2
        and row.get("过热回落风险特征", 0) >= 1
        and 0.00 <= row.get("上证指数_20日涨跌幅", 0) <= 0.06
        and row.get("上证指数_20日位置", 0) >= 0.95
        and row.get("沪深300_20日位置", 0) >= 0.95
        and row.get("中证500_20日涨跌幅", 0) >= 0.04
        and row.get("中证500_20日位置", 0) >= 0.95
        and row.get("中证1000_20日涨跌幅", 0) >= 0.05
        and row.get("中证1000_20日位置", 0) >= 0.95
    )


def is_mid_small_cap_weakening_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row["预测涨跌"] == "上涨"
        and float(row["预测上涨概率"]) < 0.75
        and row.get("当日上涨比例", 1) < 0.38
        and row.get("当日平均涨跌幅", 0) < -0.40
        and row.get("上证指数_20日涨跌幅", 0) > 0
        and row.get("中证500_20日涨跌幅", 0) < 0.01
        and row.get("中证1000_20日涨跌幅", 0) < 0.01
        and row.get("中证500_20日位置", 1) < 0.60
        and row.get("行业强涨比例_1pct", 1) < 0.25
    )


def is_index_downtrend_weak_bounce_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row["预测涨跌"] == "上涨"
        and float(row["预测上涨概率"]) < 0.75
        and row.get("上证指数_20日涨跌幅", 0) < 0
        and row.get("沪深300_20日涨跌幅", 0) < 0
        and row.get("中证500_20日涨跌幅", 0) < 0
        and row.get("中证1000_20日涨跌幅", 0) < 0
        and 0.45 <= row.get("当日上涨比例", 0) <= 0.65
        and -0.20 <= row.get("当日平均涨跌幅", 0) <= 0.50
        and row.get("行业强涨比例_1pct", 1) < 0.30
    )


def is_downtrend_mediocre_rebound_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row["预测涨跌"] == "上涨"
        and row.get("恐慌释放特征", 0) == 0
        and row.get("弱势延续风险特征", 0) == 0
        and row.get("过热回落风险特征", 0) >= 2
        and 0.45 <= row.get("当日上涨比例", 0) <= 0.65
        and 0.00 <= row.get("当日平均涨跌幅", 0) <= 0.80
        and row.get("行业强涨比例_1pct", 1) <= 0.35
        and row.get("行业强跌比例_1pct", 0) >= 0.20
        and row.get("上证指数_10日涨跌幅", 0) < -0.03
        and row.get("上证指数_20日涨跌幅", 0) < -0.04
        and row.get("沪深300_20日涨跌幅", 0) < -0.035
        and row.get("中证500_20日涨跌幅", 0) < -0.08
        and row.get("中证1000_20日涨跌幅", 0) < -0.06
        and 0.20 <= row.get("中证500_20日位置", 1) <= 0.45
        and 0.20 <= row.get("中证1000_20日位置", 1) <= 0.45
    )


def is_panic_not_oversold_continuation_risk(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "上涨"
        and row["市场风险标签"] == "恐慌释放高"
        and row.get("恐慌释放特征", 0) >= 3
        and row.get("弱势延续风险特征", 0) == 0
        and 0.18 <= row.get("当日上涨比例", 0) <= 0.30
        and -1.30 <= row.get("当日平均涨跌幅", 0) <= -0.40
        and row.get("行业强跌比例_1pct", 0) >= 0.45
        and row.get("上证指数_10日涨跌幅", 0) < 0
        and row.get("沪深300_20日涨跌幅", 0) < 0
        and row.get("上证指数_20日涨跌幅", 0) > 0
        and row.get("中证500_20日涨跌幅", 0) > 0
        and row.get("中证1000_20日涨跌幅", 0) > 0
        and row.get("上证指数_20日位置", 0) > 0.45
        and row.get("中证1000_20日位置", 0) > 0.45
    )


def is_regular_hidden_breadth_weakening_risk(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row["预测涨跌"] == "上涨"
        and row.get("当日上涨比例", 1) < 0.35
        and row.get("当日上涨比例_近5日变化", 0) <= -0.40
        and row.get("当日平均涨跌幅_近5日变化", 0) <= -1.80
        and row.get("行业强跌比例_1pct", 0) >= 0.45
        and row.get("行业强跌比例_1pct_近5日变化", 0) >= 0.30
        and row.get("连续弱势天数", 0) >= 2
    )


def is_divergent_weak_pullback_relative_strength_risk(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "上涨"
        and row.get("当日上涨比例", 1) < 0.30
        and row.get("当日平均涨跌幅", 0) < -0.80
        and row.get("上证指数_10日涨跌幅", 0) < 0
        and row.get("沪深300_20日涨跌幅", 0) > 0.05
        and row.get("中证500_20日涨跌幅", 0) > 0.05
        and row.get("行业平均涨跌幅", -99) > -0.60
        and row.get("个股强于行业", -99) > 0
    )


def is_short_term_spike_overheat_risk(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "上涨"
        and row.get("涨跌幅", 0) > 3.0
        and row.get("个股强于行业", 0) > 2.0
        and 0.45 <= row.get("当日上涨比例", 0) <= 0.65
        and row.get("当日平均涨跌幅", 0) > 1.0
        and row.get("连续上涨天数", 0) >= 3
        and row.get("中证500_20日位置", 0) > 0.95
        and row.get("中证1000_20日位置", 0) > 0.95
    )


def is_strong_rebound_low_confidence_risk(row: pd.Series) -> bool:
    base_condition = bool(
        row["预测涨跌"] == "上涨"
        and row.get("当日上涨比例", 0) >= 0.65
        and row.get("当日平均涨跌幅", 0) >= 1.0
        and row.get("过热回落风险特征", 0) >= 2
        and row.get("上证指数_20日涨跌幅", 0) > -0.005
        and row.get("中证1000_20日涨跌幅", 0) < 0.06
    )
    if not base_condition:
        return False

    up_prob = float(row["预测上涨概率"])
    if up_prob < 0.50:
        return True
    return bool(
        up_prob < 0.75
        and row.get("沪深300_20日涨跌幅", 0) > 0
    )


def is_strong_trend_pullback_opportunity(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "下跌"
        and float(row["预测上涨概率"]) >= 0.30
        and 0.30 <= row.get("当日上涨比例", 0) <= 0.45
        and -0.70 <= row.get("当日平均涨跌幅", 0) <= 0.10
        and row.get("上证指数_20日涨跌幅", 0) > 0.025
        and row.get("沪深300_20日涨跌幅", 0) > 0.025
        and row.get("中证500_20日涨跌幅", 0) > 0.04
        and row.get("中证1000_20日涨跌幅", 0) > 0.04
        and row.get("中证500_20日位置", 0) > 0.90
        and row.get("中证1000_20日位置", 0) > 0.90
    )


def is_divergent_weak_pullback_oversold_industry_opportunity(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "下跌"
        and row.get("当日上涨比例", 1) < 0.30
        and row.get("当日平均涨跌幅", 0) < -0.80
        and row.get("上证指数_10日涨跌幅", 0) < 0
        and row.get("沪深300_20日涨跌幅", 0) > 0.05
        and row.get("中证500_20日涨跌幅", 0) > 0.05
        and row.get("行业平均涨跌幅", 0) < -1.50
        and float(row["预测上涨概率"]) >= 0.20
    )


def is_strong_industry_catchup_opportunity(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "下跌"
        and row.get("行业平均涨跌幅", 0) > 3.0
        and row.get("个股强于行业", 0) < -2.0
        and 0.45 <= row.get("当日上涨比例", 0) <= 0.65
        and row.get("当日平均涨跌幅", 0) > 1.0
        and row.get("连续上涨天数", 0) >= 3
        and float(row["预测上涨概率"]) > 0.20
    )


def is_calm_high_level_sideways_opportunity(row: pd.Series) -> bool:
    return bool(
        row["市场风险标签"] == "常规环境"
        and row["预测涨跌"] == "下跌"
        and float(row["预测上涨概率"]) >= 0.30
        and row.get("恐慌释放特征", 0) == 0
        and row.get("过热回落风险特征", 0) == 0
        and row.get("弱势延续风险特征", 0) == 0
        and row.get("连续上涨天数", 0) >= 3
        and 0.42 <= row.get("当日上涨比例", 0) <= 0.55
        and 0 <= row.get("当日平均涨跌幅", 0) <= 0.60
        and row.get("上证指数_20日位置", 0) >= 0.98
        and row.get("沪深300_20日位置", 0) >= 0.98
        and row.get("中证500_20日位置", 0) >= 0.98
        and row.get("中证1000_20日位置", 0) >= 0.98
        and 0.03 <= row.get("上证指数_20日涨跌幅", 0) <= 0.06
        and 0.04 <= row.get("沪深300_20日涨跌幅", 0) <= 0.07
        and 0.05 <= row.get("中证500_20日涨跌幅", 0) <= 0.08
        and 0.04 <= row.get("中证1000_20日涨跌幅", 0) <= 0.08
    )


def is_trend_pullback_industry_strength_opportunity(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "下跌"
        and row.get("当日上涨比例", 1) < 0.45
        and row.get("当日平均涨跌幅", 0) < 0
        and row.get("上证指数_20日涨跌幅", 0) > 0.03
        and row.get("中证500_20日涨跌幅", 0) > 0.05
        and row.get("中证1000_20日涨跌幅", 0) > 0.05
        and row.get("个股强于行业", 0) > 0.25
        and row.get("行业上涨比例", 0) > 0.30
        and float(row["预测上涨概率"]) < 0.35
    )


def is_high_trend_industry_strength_opportunity(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "下跌"
        and row.get("当日上涨比例", 0) > 0.65
        and row.get("当日平均涨跌幅", 0) > 1.0
        and row.get("上证指数_20日位置", 0) > 0.95
        and row.get("中证500_20日位置", 0) > 0.95
        and row.get("中证1000_20日位置", 0) > 0.95
        and row.get("行业上涨比例", 0) > 0.70
        and row.get("行业平均涨跌幅", 0) > 1.20
        and float(row["预测上涨概率"]) < 0.35
    )


def is_panic_rebound_opportunity(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "下跌"
        and row["市场风险标签"] == "恐慌释放高"
        and float(row["预测上涨概率"]) >= 0.15
        and row.get("当日上涨比例", 1) < 0.35
        and row.get("当日平均涨跌幅", 0) < -1.0
        and row.get("沪深300_20日涨跌幅", 0) > 0.03
        and row.get("中证500_20日涨跌幅", 0) > 0.03
        and row.get("中证1000_20日涨跌幅", 0) > 0.03
        and row.get("上证指数_20日位置", 0) > 0.70
    )


def is_panic_without_weak_rebound_opportunity(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "下跌"
        and row.get("恐慌释放特征", 0) >= 2
        and row.get("弱势延续风险特征", 0) == 0
        and row.get("当日上涨比例", 1) < 0.30
        and row.get("当日平均涨跌幅", 0) < -0.60
        and row.get("中证500_20日涨跌幅", 0) < 0
        and row.get("中证1000_20日涨跌幅", 0) < 0
        and row.get("中证500_20日位置", 0) > 0.10
        and row.get("中证1000_20日位置", 0) > 0.10
    )


def is_oversold_panic_rebound_opportunity(row: pd.Series) -> bool:
    return bool(
        row["预测涨跌"] == "下跌"
        and row["市场风险标签"] == "常规环境"
        and row.get("恐慌释放特征", 0) >= 2
        and row.get("弱势延续风险特征", 0) == 0
        and 0.18 <= row.get("当日上涨比例", 0) <= 0.35
        and row.get("行业强跌比例_1pct", 0) >= 0.45
        and row.get("上证指数_20日涨跌幅", 0) < -0.035
        and row.get("沪深300_20日涨跌幅", 0) < -0.025
        and row.get("中证500_20日涨跌幅", 0) < -0.060
        and row.get("中证1000_20日涨跌幅", 0) < -0.050
        and row.get("上证指数_20日位置", 1) < 0.40
        and row.get("中证500_20日位置", 1) < 0.25
        and row.get("中证1000_20日位置", 1) < 0.35
    )


def correction_reason(row: pd.Series, overheat_threshold: float) -> str:
    original = row["预测涨跌"]
    risk = row["市场风险标签"]

    if is_oversold_panic_rebound_opportunity(row):
        return "指数超跌且恐慌未形成弱势延续，原始下跌改上涨"
    if is_panic_rebound_opportunity(row):
        return "上升趋势中恐慌洗盘，原始下跌改上涨"
    if is_panic_without_weak_rebound_opportunity(row):
        return "恐慌但弱势延续未形成，原始下跌改上涨"
    if is_trend_pullback_industry_strength_opportunity(row):
        return "趋势回调但行业相对强，原始下跌改上涨"
    if is_strong_trend_pullback_opportunity(row):
        return "强趋势回调且中小盘仍在高位，原始下跌改上涨"
    if is_divergent_weak_pullback_oversold_industry_opportunity(row):
        return "强分歧弱回调且行业超跌，原始下跌改上涨"
    if is_strong_industry_catchup_opportunity(row):
        return "强行业补涨环境，原始下跌改上涨"
    if is_calm_high_level_sideways_opportunity(row):
        return "平稳高位横盘，原始下跌改上涨"
    if is_high_trend_industry_strength_opportunity(row):
        return "高位强趋势且行业强，原始下跌改上涨"
    if original != "上涨":
        return "原始预测下跌，不修正"
    if is_panic_weak_downtrend(row):
        return "恐慌释放且弱势延续，并且大中小盘20日趋势转弱，原始上涨改下跌"
    if is_extreme_full_position_overheat_risk(row):
        return "极端满格过热且连续上涨，原始上涨改下跌"
    if is_extended_overheat(row, overheat_threshold):
        return f"过热回落高且指数高位延伸，上涨概率<{overheat_threshold:.0%}，原始上涨改下跌"
    if is_breakdown_risk(row):
        return "常规环境但短线破位，原始上涨改下跌"
    if is_weak_rebound_risk(row):
        return "常规环境但弱趋势强反弹，原始上涨改下跌"
    if is_weak_continuation_downtrend(row):
        return "弱势延续且当日继续大面积下跌，原始上涨改下跌"
    if is_weak_trend_second_rebound_failure(row):
        return "弱势趋势中的第二日反弹失败，原始上涨改下跌"
    if is_weak_false_rebound_risk(row):
        return "弱势延续中的假反弹，原始上涨改下跌"
    if is_weak_down_day_low_confidence_risk(row):
        return "弱势大跌日低置信上涨，原始上涨改下跌"
    if is_weak_rebound_industry_lag_risk(row):
        return "弱势反弹但个股弱于行业，原始上涨改下跌"
    if is_high_level_weak_rise_risk(row):
        return "常规环境但高位上涨乏力，原始上涨改下跌"
    if is_high_level_distribution_risk(row):
        return "高位横盘分化且强势行业不足，原始上涨改下跌"
    if is_midlevel_overheat_reversal_risk(row):
        return "中位过热反弹后回落风险，原始上涨改下跌"
    if is_moderate_rebound_failure_risk(row):
        return "趋势未修复的温和反弹失败，原始上涨改下跌"
    if is_post_holiday_weak_rebound_risk(row):
        return "长假后第二日弱反弹且行业强度不足，原始上涨改下跌"
    if is_high_level_moderate_rebound_exhaustion_risk(row):
        return "高位中等反弹但强势行业不足，原始上涨改下跌"
    if is_mid_small_cap_weakening_risk(row):
        return "指数尚稳但中小盘转弱，原始上涨改下跌"
    if is_index_downtrend_weak_bounce_risk(row):
        return "指数20日趋势转弱且弱反弹，原始上涨改下跌"
    if is_downtrend_mediocre_rebound_risk(row):
        return "下跌趋势中弱反抽，原始上涨改下跌"
    if is_panic_not_oversold_continuation_risk(row):
        return "恐慌但未充分超跌且趋势未修复，原始上涨改下跌"
    if is_regular_hidden_breadth_weakening_risk(row):
        return "常规环境但市场宽度隐性转弱，原始上涨改下跌"
    if is_divergent_weak_pullback_relative_strength_risk(row):
        return "强分歧弱回调但个股相对强，原始上涨改下跌"
    if is_short_term_spike_overheat_risk(row):
        return "短线冲高且个股显著强于行业，原始上涨改下跌"
    if is_strong_rebound_low_confidence_risk(row):
        return "强反弹但上涨置信度不足，原始上涨改下跌"
    return "不修正"


def corrected_direction(row: pd.Series) -> str:
    if "改上涨" in row["修正原因"]:
        return "上涨"
    if "改下跌" in row["修正原因"]:
        return "下跌"
    return row["预测涨跌"]


def high_confidence_reason(row: pd.Series, reason: str) -> str:
    """把完整规则收敛为高置信触发层。

    只使用锚点日已经可见的市场/行业/个股特征，不使用未来标签。
    """
    if reason in {"不修正", "原始预测下跌，不修正"}:
        return reason

    allowed = False

    # 明确破位/弱趋势环境，历史验证中大幅减少“实际下跌却预测上涨”。
    if reason in {
        "常规环境但短线破位，原始上涨改下跌",
        "常规环境但弱趋势强反弹，原始上涨改下跌",
        "弱势延续中的假反弹，原始上涨改下跌",
        "弱势反弹但个股弱于行业，原始上涨改下跌",
        "常规环境但高位上涨乏力，原始上涨改下跌",
        "常规环境但市场宽度隐性转弱，原始上涨改下跌",
        "高位中等反弹但强势行业不足，原始上涨改下跌",
        "下跌趋势中弱反抽，原始上涨改下跌",
        "弱势趋势中的第二日反弹失败，原始上涨改下跌",
        "中位过热反弹后回落风险，原始上涨改下跌",
        "趋势未修复的温和反弹失败，原始上涨改下跌",
        "长假后第二日弱反弹且行业强度不足，原始上涨改下跌",
        "极端满格过热且连续上涨，原始上涨改下跌",
        "弱势大跌日低置信上涨，原始上涨改下跌",
        "恐慌但未充分超跌且趋势未修复，原始上涨改下跌",
    }:
        allowed = True

    if reason == "弱势延续且当日继续大面积下跌，原始上涨改下跌":
        allowed = bool(
            (
                row.get("当日上涨比例", 1) < 0.25
                and row.get("当日平均涨跌幅", 0) < -1.20
                and row.get("上涨行业比例", 1) < 0.25
                and row.get("中证500_20日位置", 1) <= 0.05
                and row.get("中证1000_20日位置", 1) <= 0.05
            )
            or (
                0.345 <= float(row["预测上涨概率"]) < 0.55
                and row.get("当日上涨比例", 1) < 0.25
                and row.get("当日平均涨跌幅", 0) < -1.0
                and row.get("行业强跌比例_1pct", 0) >= 0.50
                and row.get("连续弱势天数", 99) <= 1
            )
        )

    # 恐慌+弱势延续在跨年回测中不稳定：2025-10-17 曾把高胜率上涨日误杀为下跌。
    # 这类环境不再在方向修正层强制翻空，先保留原始模型判断。
    if reason == "恐慌释放且弱势延续，并且大中小盘20日趋势转弱，原始上涨改下跌":
        allowed = False

    # 过热回落只在大中小盘都已经明显高位延伸时触发；避免4月中旬反弹延续期误杀。
    if reason.startswith("过热回落高且指数高位延伸"):
        allowed = bool(
            row.get("连续上涨天数", 0) >= 4
            and row.get("沪深300_20日涨跌幅", 0) >= 0.08
            and row.get("中证500_20日涨跌幅", 0) >= 0.12
            and row.get("中证1000_20日涨跌幅", 0) >= 0.12
            and row.get("中证500_20日位置", 0) >= 0.98
            and row.get("中证1000_20日位置", 0) >= 0.98
        )

    # 恐慌洗盘只在上升趋势还没过度加速、且中小盘位置未满格时触发；避免高位回撤日盲目改上涨。
    if reason == "上升趋势中恐慌洗盘，原始下跌改上涨":
        allowed = bool(
            row.get("上证指数_10日涨跌幅", 0) < 0.02
            and row.get("上证指数_20日涨跌幅", 0) > 0.02
            and row.get("沪深300_20日涨跌幅", 0) > 0.02
            and row.get("中证500_20日位置", 1) < 0.85
            and row.get("中证1000_20日位置", 1) < 0.85
        )

    # 常规趋势内的行业相对强可以小幅放开；恐慌/过热标签下不做这种反向乐观修正。
    if reason == "趋势回调但行业相对强，原始下跌改上涨":
        allowed = bool(
            row["市场风险标签"] == "常规环境"
            and 0.25 <= row.get("当日上涨比例", 1) < 0.45
            and row.get("当日平均涨跌幅", 0) > -0.50
            and row.get("上涨行业比例", 0) > 0.45
            and row.get("上证指数_20日涨跌幅", 0) > 0.02
            and row.get("中证500_20日涨跌幅", 0) > 0.05
            and row.get("中证1000_20日涨跌幅", 0) > 0.05
        )

    # 高位强趋势补涨只在常规环境且中小盘20日趋势足够强时触发。
    if reason == "高位强趋势且行业强，原始下跌改上涨":
        allowed = bool(
            row["市场风险标签"] == "常规环境"
            and row.get("中证500_20日涨跌幅", 0) >= 0.10
            and row.get("中证1000_20日涨跌幅", 0) >= 0.10
            and row.get("行业上涨比例", 0) > 0.70
        )

    if reason == "指数超跌且恐慌未形成弱势延续，原始下跌改上涨":
        allowed = True

    if allowed:
        return reason
    if row["原始预测涨跌"] == "下跌":
        return "原始预测下跌，不修正"
    return "不修正"


def summarize(df: pd.DataFrame, pred_col: str, correct_col: str, group_cols: list[str]) -> pd.DataFrame:
    stats = (
        df.groupby(group_cols, dropna=False)
        .agg(
            股票预测数=("代码", "count"),
            预测正确数=(correct_col, "sum"),
            预测上涨数=(pred_col, lambda s: (s == "上涨").sum()),
            预测下跌数=(pred_col, lambda s: (s == "下跌").sum()),
            实际上涨数=("实际涨跌", lambda s: (s == "上涨").sum()),
            实际下跌数=("实际涨跌", lambda s: (s == "下跌").sum()),
        )
        .reset_index()
    )
    stats["方向准确率"] = (stats["预测正确数"] / stats["股票预测数"]).map(lambda value: f"{value:.2%}")
    if "是否噪声样本" in df.columns:
        denoised = df.loc[~df["是否噪声样本"]]
        if len(denoised) > 0:
            denoised_stats = (
                denoised.groupby(group_cols, dropna=False)
                .agg(
                    降噪后股票预测数=("代码", "count"),
                    降噪后预测正确数=(correct_col, "sum"),
                )
                .reset_index()
            )
            stats = stats.merge(denoised_stats, on=group_cols, how="left")
            stats["降噪后股票预测数"] = stats["降噪后股票预测数"].fillna(0).astype(int)
            stats["降噪后预测正确数"] = stats["降噪后预测正确数"].fillna(0).astype(int)
            stats["降噪后方向准确率"] = stats.apply(
                lambda row: "" if row["降噪后股票预测数"] == 0 else f"{row['降噪后预测正确数'] / row['降噪后股票预测数']:.2%}",
                axis=1,
            )
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
        "当日上涨比例",
        "当日平均涨跌幅",
        "当日上涨比例_近5日变化",
        "当日平均涨跌幅_近5日变化",
        "上涨行业比例",
        "行业强涨比例_1pct",
        "行业强跌比例_1pct",
        "行业强跌比例_1pct_近5日变化",
        "连续上涨天数",
        "连续弱势天数",
    ]
    market = market[[col for col in market_cols if col in market.columns]].rename(
        columns={
            "未来5日上涨比例": "市场未来5日上涨比例",
            "未来5日市场方向": "实际市场方向",
            "未来5日市场状态": "实际市场状态",
        }
    )
    index_feature_path = output_dir / "00_核心指数特征.csv"
    if index_feature_path.exists():
        index_features = pd.read_csv(index_feature_path, encoding="utf-8-sig")
        index_cols = [
            "日期",
            "上证指数_10日涨跌幅",
            "上证指数_20日涨跌幅",
            "上证指数_20日位置",
            "沪深300_20日涨跌幅",
            "沪深300_20日位置",
            "中证500_20日涨跌幅",
            "中证500_20日位置",
            "中证1000_20日涨跌幅",
            "中证1000_20日位置",
        ]
        index_features = index_features[[col for col in index_cols if col in index_features.columns]]
    else:
        index_features = pd.DataFrame({"日期": []})
    label_path = output_dir / args.label_csv
    label_cols = ["日期", "代码", "5日后的实际涨跌幅"]
    labels = pd.read_csv(label_path, encoding="utf-8-sig", dtype={"代码": str}, usecols=label_cols)
    feature_path = output_dir / args.feature_csv
    feature_cols = [
        "日期",
        "代码",
        "行业平均涨跌幅",
        "行业上涨比例",
        "个股强于行业",
        "距上个交易日自然天数",
        "星期几",
        "是否周一",
        "是否长假后首日",
        "长假后第几个交易日",
        "是否长假后三日内",
        "是否长假后五日内",
    ]
    features = pd.read_csv(feature_path, encoding="utf-8-sig", dtype={"代码": str}, usecols=feature_cols)

    frames: list[pd.DataFrame] = []
    for date_tag in dates:
        path = output_dir / f"03_每只股票方向预测结果_核心特征{args.prediction_suffix}_{date_tag}.csv"
        if not path.exists():
            raise FileNotFoundError(f"缺少个股预测结果: {path}")
        frames.append(pd.read_csv(path, encoding="utf-8-sig", dtype={"代码": str}))
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.merge(market, left_on="锚点日期", right_on="日期", how="left").drop(columns=["日期_y"], errors="ignore")
    if "日期_x" in merged.columns:
        merged = merged.rename(columns={"日期_x": "日期"})
    if not index_features.empty:
        merged = merged.merge(index_features, left_on="锚点日期", right_on="日期", how="left", suffixes=("", "_指数"))
        merged = merged.drop(columns=["日期_指数"], errors="ignore")
    merged = merged.merge(labels, on=["日期", "代码"], how="left")
    merged = merged.merge(features, on=["日期", "代码"], how="left")

    merged["预测上涨概率"] = pd.to_numeric(merged["预测上涨概率"], errors="coerce")
    merged["5日后的实际涨跌幅"] = pd.to_numeric(merged["5日后的实际涨跌幅"], errors="coerce")
    merged["是否噪声样本"] = merged["5日后的实际涨跌幅"].abs() <= args.noise_threshold
    merged["市场风险标签"] = merged.apply(risk_label, axis=1)
    merged["原始预测涨跌"] = merged["预测涨跌"]
    merged["原始预测是否准确"] = merged["涨跌预测是否准确"].astype(int)
    merged["完整规则修正原因"] = merged.apply(lambda row: correction_reason(row, args.overheat_threshold), axis=1)
    if args.correction_policy in {"high_confidence", "v15"}:
        merged["修正原因"] = merged.apply(lambda row: high_confidence_reason(row, row["完整规则修正原因"]), axis=1)
    else:
        merged["修正原因"] = merged["完整规则修正原因"]
    merged["修正后预测涨跌"] = merged.apply(corrected_direction, axis=1)
    merged["修正后预测是否准确"] = (merged["修正后预测涨跌"] == merged["实际涨跌"]).astype(int)
    merged["是否发生修正"] = (merged["修正后预测涨跌"] != merged["原始预测涨跌"]).astype(int)

    start_tag = dates[0]
    end_tag = dates[-1]
    detail_path = output_dir / f"10_个股预测结果_市场风险修正{args.output_suffix}_{start_tag}_{end_tag}.csv"
    total_path = output_dir / f"10_市场风险修正总体对比{args.output_suffix}_{start_tag}_{end_tag}.csv"
    risk_path = output_dir / f"10_按市场风险标签对比修正效果{args.output_suffix}_{start_tag}_{end_tag}.csv"
    date_path = output_dir / f"10_按日期对比市场风险修正效果{args.output_suffix}_{start_tag}_{end_tag}.csv"

    total = pd.DataFrame(
        [
            {
                "股票预测数": len(merged),
                "噪声样本数": int(merged["是否噪声样本"].sum()),
                "降噪后股票预测数": int((~merged["是否噪声样本"]).sum()),
                "发生修正数": int(merged["是否发生修正"].sum()),
                "原始正确数": int(merged["原始预测是否准确"].sum()),
                "修正后正确数": int(merged["修正后预测是否准确"].sum()),
                "原始准确率": f"{merged['原始预测是否准确'].mean():.2%}",
                "修正后准确率": f"{merged['修正后预测是否准确'].mean():.2%}",
                "降噪后原始正确数": int(merged.loc[~merged["是否噪声样本"], "原始预测是否准确"].sum()),
                "降噪后修正正确数": int(merged.loc[~merged["是否噪声样本"], "修正后预测是否准确"].sum()),
                "降噪后原始准确率": f"{merged.loc[~merged['是否噪声样本'], '原始预测是否准确'].mean():.2%}",
                "降噪后修正准确率": f"{merged.loc[~merged['是否噪声样本'], '修正后预测是否准确'].mean():.2%}",
                "准确率变化百分点": round((merged["修正后预测是否准确"].mean() - merged["原始预测是否准确"].mean()) * 100, 2),
                "降噪后准确率变化百分点": round(
                    (
                        merged.loc[~merged["是否噪声样本"], "修正后预测是否准确"].mean()
                        - merged.loc[~merged["是否噪声样本"], "原始预测是否准确"].mean()
                    )
                    * 100,
                    2,
                ),
                "原始实际下跌却预测上涨数": int(((merged["原始预测涨跌"] == "上涨") & (merged["实际涨跌"] == "下跌")).sum()),
                "修正后实际下跌却预测上涨数": int(((merged["修正后预测涨跌"] == "上涨") & (merged["实际涨跌"] == "下跌")).sum()),
            }
        ]
    )

    by_risk_original = summarize(merged, "原始预测涨跌", "原始预测是否准确", ["市场风险标签"]).rename(
        columns={
            "预测正确数": "原始正确数",
            "预测上涨数": "原始预测上涨数",
            "预测下跌数": "原始预测下跌数",
            "方向准确率": "原始准确率",
            "降噪后预测正确数": "降噪后原始正确数",
            "降噪后方向准确率": "降噪后原始准确率",
        }
    )
    by_risk_corrected = summarize(merged, "修正后预测涨跌", "修正后预测是否准确", ["市场风险标签"]).rename(
        columns={
            "预测正确数": "修正后正确数",
            "预测上涨数": "修正后预测上涨数",
            "预测下跌数": "修正后预测下跌数",
            "方向准确率": "修正后准确率",
            "降噪后股票预测数": "降噪后修正股票预测数",
            "降噪后预测正确数": "降噪后修正正确数",
            "降噪后方向准确率": "降噪后修正准确率",
        }
    )
    by_risk = by_risk_original.merge(
        by_risk_corrected[
            [
                "市场风险标签",
                "修正后正确数",
                "修正后预测上涨数",
                "修正后预测下跌数",
                "修正后准确率",
                "降噪后修正股票预测数",
                "降噪后修正正确数",
                "降噪后修正准确率",
            ]
        ],
        on="市场风险标签",
        how="left",
    )
    by_risk = by_risk.drop(columns=["降噪后修正股票预测数"], errors="ignore")

    by_date_original = summarize(merged, "原始预测涨跌", "原始预测是否准确", ["锚点日期", "实际市场状态", "市场风险标签"]).rename(
        columns={
            "预测正确数": "原始正确数",
            "预测上涨数": "原始预测上涨数",
            "预测下跌数": "原始预测下跌数",
            "方向准确率": "原始准确率",
            "降噪后预测正确数": "降噪后原始正确数",
            "降噪后方向准确率": "降噪后原始准确率",
        }
    )
    by_date_corrected = summarize(merged, "修正后预测涨跌", "修正后预测是否准确", ["锚点日期", "实际市场状态", "市场风险标签"]).rename(
        columns={
            "预测正确数": "修正后正确数",
            "预测上涨数": "修正后预测上涨数",
            "预测下跌数": "修正后预测下跌数",
            "方向准确率": "修正后准确率",
            "降噪后股票预测数": "降噪后修正股票预测数",
            "降噪后预测正确数": "降噪后修正正确数",
            "降噪后方向准确率": "降噪后修正准确率",
        }
    )
    by_date = by_date_original.merge(
        by_date_corrected[
            [
                "锚点日期",
                "实际市场状态",
                "市场风险标签",
                "修正后正确数",
                "修正后预测上涨数",
                "修正后预测下跌数",
                "修正后准确率",
                "降噪后修正股票预测数",
                "降噪后修正正确数",
                "降噪后修正准确率",
            ]
        ],
        on=["锚点日期", "实际市场状态", "市场风险标签"],
        how="left",
    )
    by_date = by_date.drop(columns=["降噪后修正股票预测数"], errors="ignore")

    merged.to_csv(detail_path, index=False, encoding="utf-8-sig")
    total.to_csv(total_path, index=False, encoding="utf-8-sig")
    by_risk.to_csv(risk_path, index=False, encoding="utf-8-sig")
    by_date.to_csv(date_path, index=False, encoding="utf-8-sig")

    print(f"修正明细: {detail_path}")
    print(f"总体对比: {total_path}")
    print(total.to_string(index=False))
    print(f"按风险标签: {risk_path}")
    print(by_risk.to_string(index=False))
    print(f"按日期: {date_path}")
    print(by_date.to_string(index=False))


if __name__ == "__main__":
    main()
