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
    add_cross_sectional_features,
    add_market_and_industry_features,
    add_peer_history_features,
    enrich_one_stock,
    load_meta,
)
from train_5d_direction_model import CORE_FEATURE_COLUMNS


DEFAULT_OUTPUT_FILE = DEFAULT_OUTPUT_DIR / "00_5日涨跌方向预测样本明细.csv"
DEFAULT_INDEX_FEATURE_FILE = DEFAULT_OUTPUT_DIR / "00_核心指数特征.csv"

CALENDAR_CONTEXT_COLUMNS = [
    "距上个交易日自然天数",
    "星期几",
    "是否周一",
    "是否长假后首日",
    "长假后第几个交易日",
    "是否长假后三日内",
    "是否长假后五日内",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="合并目录下所有股票日K CSV，并写入5日方向预测建模样本")
    parser.add_argument("--input-dir", default=str(DEFAULT_DAILY_DIR), help="日K目录")
    parser.add_argument("--meta-csv", default=str(DEFAULT_META_CSV), help="股票元数据CSV")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_FILE), help="输出CSV文件")
    parser.add_argument("--index-feature-file", default=str(DEFAULT_INDEX_FEATURE_FILE), help="核心指数特征CSV")
    parser.add_argument(
        "--feature-set",
        choices=["core", "all"],
        default="core",
        help="输出字段集合：core=只保留核心关键字段，all=保留全部派生字段；默认core",
    )
    return parser.parse_args()


BASE_OUTPUT_COLUMNS = [
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
]

LABEL_OUTPUT_COLUMNS = [
    "5日后收盘",
    "卖出日",
    "5日后的实际涨跌幅",
    "5日后上涨标签",
    "5日后实际涨跌",
]


def keep_core_columns(df: pd.DataFrame) -> pd.DataFrame:
    keep_cols = []
    for col in BASE_OUTPUT_COLUMNS + CORE_FEATURE_COLUMNS + CALENDAR_CONTEXT_COLUMNS + LABEL_OUTPUT_COLUMNS:
        if col in df.columns and col not in keep_cols:
            keep_cols.append(col)
    return df[keep_cols].copy()


def split_name_from_file(file_path: Path) -> tuple[str, str]:
    stem = file_path.stem
    if stem.endswith("_daily_k"):
        stem = stem[:-8]
    parts = stem.split("_", 1)
    code = parts[0]
    name = parts[1] if len(parts) > 1 else ""
    return code, name


def add_index_features(merged: pd.DataFrame, index_feature_file: Path) -> pd.DataFrame:
    if not index_feature_file.exists():
        print(f"未找到指数特征文件，跳过指数特征合并: {index_feature_file}")
        return merged

    index_df = pd.read_csv(index_feature_file, encoding="utf-8-sig")
    if index_df.empty or "日期" not in index_df.columns:
        print(f"指数特征文件为空或缺少日期，跳过: {index_feature_file}")
        return merged

    out = merged.copy()
    out["日期"] = pd.to_datetime(out["日期"], errors="coerce")
    index_df["日期"] = pd.to_datetime(index_df["日期"], errors="coerce")
    out = out.merge(index_df, on="日期", how="left")

    index_return_cols = [
        "沪深300_1日涨跌幅",
        "沪深300_5日涨跌幅",
        "中证500_5日涨跌幅",
        "中证1000_5日涨跌幅",
        "创业板指_5日涨跌幅",
    ]
    for col in index_return_cols:
        if col in out.columns:
            safe_name = col.replace("涨跌幅", "相对强弱")
            out[f"个股强于{safe_name}"] = out["ret_5" if "5日" in col else "ret_1"] - pd.to_numeric(out[col], errors="coerce")

    return out


def add_calendar_gap_features(merged: pd.DataFrame) -> pd.DataFrame:
    out = merged.copy()
    out["日期"] = pd.to_datetime(out["日期"], errors="coerce")

    trading_days = pd.Series(out["日期"].dropna().unique()).sort_values().reset_index(drop=True)
    calendar = pd.DataFrame({"日期": trading_days})
    calendar["距上个交易日自然天数"] = calendar["日期"].diff().dt.days
    calendar["星期几"] = calendar["日期"].dt.weekday + 1
    calendar["是否周一"] = (calendar["星期几"] == 1).astype(int)
    calendar["是否长假后首日"] = (calendar["距上个交易日自然天数"] >= 5).astype(int)

    days_after_long_break: list[int] = []
    current_count = 0
    for gap in calendar["距上个交易日自然天数"]:
        if pd.isna(gap):
            current_count = 0
        elif gap >= 5:
            current_count = 1
        elif 0 < current_count < 5:
            current_count += 1
        else:
            current_count = 0
        days_after_long_break.append(current_count)
    calendar["长假后第几个交易日"] = days_after_long_break
    calendar["是否长假后三日内"] = calendar["长假后第几个交易日"].between(1, 3).astype(int)
    calendar["是否长假后五日内"] = calendar["长假后第几个交易日"].between(1, 5).astype(int)

    out = out.merge(calendar, on="日期", how="left")
    return out


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).resolve()
    output_file = Path(args.output_file).resolve()
    meta_map = load_meta(Path(args.meta_csv).resolve())
    files = sorted(input_dir.glob("*_daily_k.csv"))
    if not files:
        raise SystemExit(f"未找到日K文件: {input_dir}")

    frames: list[pd.DataFrame] = []
    for fp in files:
        code, fallback_name = split_name_from_file(fp)
        meta = meta_map.get(code, {"代码": code, "名称": fallback_name})
        df = pd.read_csv(fp, encoding="utf-8-sig")
        if df.empty:
            continue
        frames.append(enrich_one_stock(df, code, meta))

    if not frames:
        raise SystemExit("没有可合并的日K数据")

    merged = pd.concat(frames, ignore_index=True)
    merged = add_cross_sectional_features(merged)
    merged = add_market_and_industry_features(merged)
    merged = add_peer_history_features(merged)
    merged = add_index_features(merged, Path(args.index_feature_file).resolve())
    merged = add_calendar_gap_features(merged)
    merged = merged.rename(
        columns={
            "future_date_5": "卖出日",
            "future_close_5": "5日后收盘",
            "target_5d": "5日后的实际涨跌幅",
            "label_up_5d": "5日后上涨标签",
        }
    )
    merged["5日后实际涨跌"] = np.where(
        merged["5日后的实际涨跌幅"].notna(),
        np.where(merged["5日后的实际涨跌幅"] > 0, "上涨", "下跌"),
        "",
    )
    merged["日期"] = pd.to_datetime(merged["日期"], errors="coerce")
    merged["卖出日"] = pd.to_datetime(merged["卖出日"], errors="coerce")
    merged = merged.sort_values(["代码", "日期"]).reset_index(drop=True)
    merged["日期"] = merged["日期"].dt.strftime("%Y-%m-%d")
    merged["卖出日"] = merged["卖出日"].dt.strftime("%Y-%m-%d")

    if args.feature_set == "core":
        merged = keep_core_columns(merged)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_file, index=False, encoding="utf-8-sig")

    stock_cols = [col for col in ["代码", "名称", "交易所", "板块", "行业"] if col in merged.columns]
    stock_list = merged[stock_cols].drop_duplicates().sort_values(["代码", "名称"]).reset_index(drop=True)
    stock_list.to_csv(output_file.parent / "00_股票清单.csv", index=False, encoding="utf-8-sig")

    print(f"已合并 {len(files)} 个文件")
    print(f"输出文件: {output_file}")
    print(f"合并行数: {len(merged)}")
    print(f"字段数: {len(merged.columns)}")
    print(f"股票清单: {output_file.parent / '00_股票清单.csv'}")


if __name__ == "__main__":
    main()
