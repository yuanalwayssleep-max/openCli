#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "skills" / "a-share-kline-return-modeling" / "outputs"
DEFAULT_INDEX_DAILY = DEFAULT_OUTPUT_DIR / "00_核心指数日K.csv"
DEFAULT_INDEX_FEATURES = DEFAULT_OUTPUT_DIR / "00_核心指数特征.csv"

INDEX_CODES = {
    "上证指数": "sh.000001",
    "深证成指": "sz.399001",
    "沪深300": "sh.000300",
    "中证500": "sh.000905",
    "中证1000": "sh.000852",
    "创业板指": "sz.399006",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取核心指数日K并生成建模特征")
    parser.add_argument("--start-date", default="2025-01-01", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default=pd.Timestamp.today().strftime("%Y-%m-%d"), help="结束日期 YYYY-MM-DD")
    parser.add_argument("--daily-output", default=str(DEFAULT_INDEX_DAILY), help="指数日K输出CSV")
    parser.add_argument("--feature-output", default=str(DEFAULT_INDEX_FEATURES), help="指数特征输出CSV")
    return parser.parse_args()


def safe_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def fetch_one_index(name: str, code: str, start_date: str, end_date: str) -> pd.DataFrame:
    fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg"
    rs = bs.query_history_k_data_plus(
        code,
        fields,
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="3",
    )
    rows: list[list[str]] = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(f"{name} {code} 抓取失败: {rs.error_code} {rs.error_msg}")
    df = pd.DataFrame(rows, columns=fields.split(","))
    if df.empty:
        raise RuntimeError(f"{name} {code} 无日K数据")
    df.insert(0, "指数名称", name)
    return df


def build_index_features(daily_df: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for name, group in daily_df.groupby("指数名称", sort=False):
        g = group.copy()
        g["日期"] = pd.to_datetime(g["date"], errors="coerce")
        for col in ["open", "high", "low", "close", "preclose", "volume", "amount", "pctChg"]:
            g[col] = safe_num(g[col])
        g = g.sort_values("日期").reset_index(drop=True)
        close = g["close"]
        amount = g["amount"]
        ret = close.pct_change()
        prefix = f"{name}_"

        feature = pd.DataFrame({"日期": g["日期"]})
        feature[f"{prefix}1日涨跌幅"] = g["pctChg"] / 100.0
        for n in [3, 5, 10, 20]:
            feature[f"{prefix}{n}日涨跌幅"] = close.pct_change(n)
        for n in [5, 10, 20]:
            ma = close.rolling(n).mean()
            feature[f"{prefix}收盘均线比_{n}"] = close / ma - 1
            feature[f"{prefix}成交额比_{n}"] = amount / amount.rolling(n).mean() - 1
            feature[f"{prefix}波动率_{n}"] = ret.rolling(n).std()
        feature[f"{prefix}20日位置"] = (close - close.rolling(20).min()) / (
            close.rolling(20).max() - close.rolling(20).min()
        ).replace(0, np.nan)
        frames.append(feature)

    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on="日期", how="outer")
    out = out.sort_values("日期").reset_index(drop=True)

    if {"沪深300_5日涨跌幅", "中证1000_5日涨跌幅"}.issubset(out.columns):
        out["中证1000强于沪深300_5日"] = out["中证1000_5日涨跌幅"] - out["沪深300_5日涨跌幅"]
    if {"中证500_5日涨跌幅", "沪深300_5日涨跌幅"}.issubset(out.columns):
        out["中证500强于沪深300_5日"] = out["中证500_5日涨跌幅"] - out["沪深300_5日涨跌幅"]
    if {"创业板指_5日涨跌幅", "沪深300_5日涨跌幅"}.issubset(out.columns):
        out["创业板强于沪深300_5日"] = out["创业板指_5日涨跌幅"] - out["沪深300_5日涨跌幅"]
    return out


def main() -> None:
    args = parse_args()
    daily_output = Path(args.daily_output).resolve()
    feature_output = Path(args.feature_output).resolve()
    daily_output.parent.mkdir(parents=True, exist_ok=True)
    feature_output.parent.mkdir(parents=True, exist_ok=True)

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {login.error_code} {login.error_msg}")
    try:
        daily_frames = [
            fetch_one_index(name, code, args.start_date, args.end_date)
            for name, code in INDEX_CODES.items()
        ]
    finally:
        bs.logout()

    daily_df = pd.concat(daily_frames, ignore_index=True)
    daily_df.to_csv(daily_output, index=False, encoding="utf-8-sig")

    feature_df = build_index_features(daily_df)
    feature_df["日期"] = pd.to_datetime(feature_df["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    feature_df.to_csv(feature_output, index=False, encoding="utf-8-sig")

    print(f"指数日K: {daily_output} rows={len(daily_df)}")
    print(f"指数特征: {feature_output} rows={len(feature_df)} cols={len(feature_df.columns)}")


if __name__ == "__main__":
    main()
