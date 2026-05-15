#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from train_5d_direction_model import CORE_FEATURE_COLUMNS, DEFAULT_SAMPLE_CSV
from train_5d_return_model import DEFAULT_OUTPUT_DIR


DEFAULT_BASE_OUTPUT = DEFAULT_OUTPUT_DIR / "00_A股日K基础行情与5日后标签表.csv"
DEFAULT_FEATURE_OUTPUT = DEFAULT_OUTPUT_DIR / "00_5日方向模型特征表.csv"

CALENDAR_CONTEXT_COLUMNS = [
    "距上个交易日自然天数",
    "星期几",
    "是否周一",
    "是否长假后首日",
    "长假后第几个交易日",
    "是否长假后三日内",
    "是否长假后五日内",
]


BASE_COLUMNS = [
    "日期",
    "代码",
    "名称",
    "行业",
    "板块",
    "交易所",
    "开盘",
    "收盘",
    "最高",
    "最低",
    "成交量",
    "成交额",
    "振幅",
    "涨跌幅",
    "涨跌额",
    "换手率",
    "5日后收盘",
    "卖出日",
    "5日后的实际涨跌幅",
    "5日后上涨标签",
    "5日后实际涨跌",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将5日方向建模主表拆成基础事实表和模型特征表")
    parser.add_argument("--input-file", default=str(DEFAULT_SAMPLE_CSV), help="当前5日方向建模主表")
    parser.add_argument("--base-output", default=str(DEFAULT_BASE_OUTPUT), help="A股日K基础行情与5日后标签表输出路径")
    parser.add_argument("--feature-output", default=str(DEFAULT_FEATURE_OUTPUT), help="5日方向模型特征表输出路径")
    return parser.parse_args()


def keep_existing_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [col for col in columns if col in df.columns]


def main() -> None:
    args = parse_args()
    input_file = Path(args.input_file).resolve()
    base_output = Path(args.base_output).resolve()
    feature_output = Path(args.feature_output).resolve()

    df = pd.read_csv(input_file, encoding="utf-8-sig", dtype={"代码": str})
    if df.empty:
        raise SystemExit(f"输入文件为空: {input_file}")

    df["代码"] = df["代码"].str.zfill(6)
    df = df.sort_values(["代码", "日期"]).reset_index(drop=True)

    base_cols = keep_existing_columns(df, BASE_COLUMNS)
    feature_cols = keep_existing_columns(df, ["日期", "代码"] + CORE_FEATURE_COLUMNS + CALENDAR_CONTEXT_COLUMNS)

    base_df = df[base_cols].copy()
    feature_df = df[feature_cols].copy()

    base_output.parent.mkdir(parents=True, exist_ok=True)
    feature_output.parent.mkdir(parents=True, exist_ok=True)
    base_df.to_csv(base_output, index=False, encoding="utf-8-sig")
    feature_df.to_csv(feature_output, index=False, encoding="utf-8-sig")

    print(f"基础事实表: {base_output}")
    print(f"基础事实表行数: {len(base_df)} 字段数: {len(base_df.columns)}")
    print(f"模型特征表: {feature_output}")
    print(f"模型特征表行数: {len(feature_df)} 字段数: {len(feature_df.columns)}")
    print("关联主键: 日期 + 代码")


if __name__ == "__main__":
    main()
