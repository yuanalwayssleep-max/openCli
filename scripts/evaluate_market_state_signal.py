#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from train_5d_market_direction_model import DEFAULT_MARKET_SAMPLE_CSV, market_state
from train_5d_return_model import DEFAULT_OUTPUT_DIR


DEFAULT_DATES = ",".join(
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

INDEX_NAMES = ["上证指数", "沪深300", "中证500", "中证1000"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按可解释市场状态做未来5日市场方向旁路验证")
    parser.add_argument("--market-sample-csv", default=str(DEFAULT_MARKET_SAMPLE_CSV), help="市场5日方向预测样本")
    parser.add_argument("--index-feature-csv", default=str(DEFAULT_OUTPUT_DIR / "00_核心指数特征.csv"), help="核心指数特征")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--test-dates", default=DEFAULT_DATES, help="测试日期，逗号分隔，格式YYYY-MM-DD")
    parser.add_argument("--min-train-days", type=int, default=60, help="最少训练日期数")
    parser.add_argument("--min-state-samples", type=int, default=5, help="精确状态最少历史样本数")
    parser.add_argument("--target-up-ratio", type=float, default=0.50, help="市场方向阈值")
    return parser.parse_args()


def load_data(market_path: Path, index_path: Path) -> pd.DataFrame:
    market = pd.read_csv(market_path, encoding="utf-8-sig")
    market["日期"] = pd.to_datetime(market["日期"], errors="coerce")
    market["卖出日"] = pd.to_datetime(market["卖出日"], errors="coerce")
    market["未来5日上涨比例"] = pd.to_numeric(market["未来5日上涨比例"], errors="coerce")

    if index_path.exists():
        index = pd.read_csv(index_path, encoding="utf-8-sig")
        index["日期"] = pd.to_datetime(index["日期"], errors="coerce")
        keep_cols = ["日期"]
        for name in INDEX_NAMES:
            keep_cols.extend([f"{name}_20日涨跌幅", f"{name}_20日位置", f"{name}_5日涨跌幅"])
        index = index[[col for col in keep_cols if col in index.columns]]
        market = market.merge(index, on="日期", how="left", suffixes=("", "_指数"))

    return market.sort_values("日期").reset_index(drop=True)


def parse_dates(value: str) -> list[pd.Timestamp]:
    return [pd.to_datetime(item.strip()) for item in value.split(",") if item.strip()]


def bucket_breadth(value: float) -> str:
    if pd.isna(value):
        return "宽度未知"
    if value >= 0.70:
        return "强宽度"
    if value >= 0.55:
        return "偏强宽度"
    if value >= 0.45:
        return "均衡宽度"
    if value >= 0.30:
        return "偏弱宽度"
    return "极弱宽度"


def bucket_avg_return(value: float) -> str:
    if pd.isna(value):
        return "涨跌未知"
    if value >= 1.0:
        return "强上涨日"
    if value >= 0.2:
        return "温和上涨日"
    if value > -0.2:
        return "平盘震荡日"
    if value > -1.0:
        return "温和下跌日"
    return "强下跌日"


def bucket_risk(row: pd.Series) -> str:
    flags: list[str] = []
    if row.get("恐慌释放特征", 0) >= 3:
        flags.append("恐慌")
    if row.get("过热回落风险特征", 0) >= 3:
        flags.append("过热")
    if row.get("弱势延续风险特征", 0) >= 3:
        flags.append("弱势")
    return "+".join(flags) if flags else "常规"


def bucket_index_trend(row: pd.Series) -> str:
    returns = [pd.to_numeric(row.get(f"{name}_20日涨跌幅"), errors="coerce") for name in INDEX_NAMES]
    positions = [pd.to_numeric(row.get(f"{name}_20日位置"), errors="coerce") for name in INDEX_NAMES]
    returns = [float(v) for v in returns if pd.notna(v)]
    positions = [float(v) for v in positions if pd.notna(v)]
    if not returns:
        return "指数趋势未知"
    avg_ret = float(np.mean(returns))
    min_pos = float(np.min(positions)) if positions else np.nan
    max_pos = float(np.max(positions)) if positions else np.nan
    if avg_ret >= 0.05 and pd.notna(min_pos) and min_pos >= 0.80:
        return "高位强趋势"
    if avg_ret >= 0.02:
        return "上升趋势"
    if avg_ret <= -0.03 and pd.notna(max_pos) and max_pos <= 0.35:
        return "低位弱趋势"
    if avg_ret <= -0.01:
        return "下行趋势"
    return "震荡趋势"


def bucket_size_style(row: pd.Series) -> str:
    large = pd.to_numeric(row.get("沪深300_20日涨跌幅"), errors="coerce")
    mid = pd.to_numeric(row.get("中证500_20日涨跌幅"), errors="coerce")
    small = pd.to_numeric(row.get("中证1000_20日涨跌幅"), errors="coerce")
    if pd.isna(large) or pd.isna(mid) or pd.isna(small):
        return "风格未知"
    small_vs_large = float(small - large)
    mid_vs_large = float(mid - large)
    if small_vs_large >= 0.03 and mid_vs_large >= 0.02:
        return "中小盘强"
    if small_vs_large <= -0.03 and mid_vs_large <= -0.02:
        return "权重强"
    return "风格均衡"


def add_state_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["宽度状态"] = df["当日上涨比例"].map(bucket_breadth)
    df["涨跌状态"] = df["当日平均涨跌幅"].map(bucket_avg_return)
    df["风险状态"] = df.apply(bucket_risk, axis=1)
    df["指数趋势状态"] = df.apply(bucket_index_trend, axis=1)
    df["风格状态"] = df.apply(bucket_size_style, axis=1)
    df["市场状态键_精确"] = (
        df["风险状态"] + "|" + df["指数趋势状态"] + "|" + df["宽度状态"] + "|" + df["涨跌状态"] + "|" + df["风格状态"]
    )
    df["市场状态键_宽松"] = df["风险状态"] + "|" + df["指数趋势状态"] + "|" + df["宽度状态"]
    df["市场状态键_基础"] = df["指数趋势状态"] + "|" + df["宽度状态"]
    return df


def completed_train(df: pd.DataFrame, as_of_date: pd.Timestamp) -> pd.DataFrame:
    return df[
        (df["日期"] < as_of_date)
        & (df["卖出日"] <= as_of_date)
        & df["未来5日上涨比例"].notna()
    ].copy()


def state_stats(train: pd.DataFrame, key_col: str, key: str, target_up_ratio: float) -> dict[str, object]:
    part = train[train[key_col] == key].copy()
    if part.empty:
        return {
            "匹配层级": key_col.replace("市场状态键_", ""),
            "历史匹配样本数": 0,
            "历史上涨样本数": 0,
            "历史下跌样本数": 0,
            "历史上涨占比": np.nan,
            "历史平均未来5日上涨比例": np.nan,
            "预测市场方向": "",
            "预测未来5日上涨比例": np.nan,
        }
    up = int((part["未来5日上涨比例"] >= target_up_ratio).sum())
    down = int(len(part) - up)
    up_share = up / len(part)
    pred_ratio = float(part["未来5日上涨比例"].mean())
    return {
        "匹配层级": key_col.replace("市场状态键_", ""),
        "历史匹配样本数": int(len(part)),
        "历史上涨样本数": up,
        "历史下跌样本数": down,
        "历史上涨占比": up_share,
        "历史平均未来5日上涨比例": pred_ratio,
        "预测市场方向": "上涨" if up_share >= 0.50 else "下跌",
        "预测未来5日上涨比例": pred_ratio,
    }


def predict_one(
    df: pd.DataFrame,
    as_of_date: pd.Timestamp,
    min_train_days: int,
    min_state_samples: int,
    target_up_ratio: float,
) -> dict[str, object]:
    train = completed_train(df, as_of_date)
    if len(train) < min_train_days:
        raise RuntimeError(f"{as_of_date.strftime('%Y-%m-%d')} 训练日期不足: {len(train)}")

    anchor = df[df["日期"] == as_of_date].copy()
    if anchor.empty:
        raise RuntimeError(f"未找到锚点日期: {as_of_date.strftime('%Y-%m-%d')}")
    row = anchor.iloc[0]

    selected: dict[str, object] | None = None
    selected_key_col = ""
    selected_key = ""
    for key_col in ["市场状态键_精确", "市场状态键_宽松", "市场状态键_基础"]:
        key = str(row[key_col])
        stats = state_stats(train, key_col, key, target_up_ratio)
        if int(stats["历史匹配样本数"]) >= min_state_samples:
            selected = stats
            selected_key_col = key_col
            selected_key = key
            break
    if selected is None:
        overall_up_share = float((train["未来5日上涨比例"] >= target_up_ratio).mean())
        selected = {
            "匹配层级": "全历史",
            "历史匹配样本数": int(len(train)),
            "历史上涨样本数": int((train["未来5日上涨比例"] >= target_up_ratio).sum()),
            "历史下跌样本数": int((train["未来5日上涨比例"] < target_up_ratio).sum()),
            "历史上涨占比": overall_up_share,
            "历史平均未来5日上涨比例": float(train["未来5日上涨比例"].mean()),
            "预测市场方向": "上涨" if overall_up_share >= 0.50 else "下跌",
            "预测未来5日上涨比例": float(train["未来5日上涨比例"].mean()),
        }
        selected_key_col = "全历史"
        selected_key = "全历史"

    actual_ratio = row["未来5日上涨比例"]
    actual_direction = ""
    if pd.notna(actual_ratio):
        actual_direction = "上涨" if float(actual_ratio) >= target_up_ratio else "下跌"
    pred_direction = str(selected["预测市场方向"])

    out = {
        "锚点日期": as_of_date.strftime("%Y-%m-%d"),
        "训练日期数": int(len(train)),
        "匹配键字段": selected_key_col,
        "匹配键": selected_key,
        "风险状态": row["风险状态"],
        "指数趋势状态": row["指数趋势状态"],
        "宽度状态": row["宽度状态"],
        "涨跌状态": row["涨跌状态"],
        "风格状态": row["风格状态"],
        **selected,
        "预测市场状态": market_state(float(selected["预测未来5日上涨比例"])),
        "实际未来5日上涨比例": float(actual_ratio) if pd.notna(actual_ratio) else np.nan,
        "实际市场方向": actual_direction,
        "实际市场状态": market_state(float(actual_ratio)) if pd.notna(actual_ratio) else "",
        "市场方向预测是否准确": int(pred_direction == actual_direction) if actual_direction else np.nan,
    }
    return out


def pct(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:.2%}"


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    df = add_state_columns(load_data(Path(args.market_sample_csv).resolve(), Path(args.index_feature_csv).resolve()))
    dates = parse_dates(args.test_dates)

    rows = [
        predict_one(df, date, args.min_train_days, args.min_state_samples, args.target_up_ratio)
        for date in dates
    ]
    result = pd.DataFrame(rows)
    scored = result[result["市场方向预测是否准确"].notna()].copy()
    summary = pd.DataFrame(
        [
            {
                "测试日期数": len(result),
                "可判卷日期数": len(scored),
                "预测正确日期数": int(scored["市场方向预测是否准确"].sum()) if len(scored) else 0,
                "市场状态信号准确率": pct(float(scored["市场方向预测是否准确"].mean())) if len(scored) else "",
                "平均历史匹配样本数": round(float(result["历史匹配样本数"].mean()), 2) if len(result) else np.nan,
                "精确匹配日期数": int((result["匹配层级"] == "精确").sum()) if len(result) else 0,
                "宽松匹配日期数": int((result["匹配层级"] == "宽松").sum()) if len(result) else 0,
                "基础匹配日期数": int((result["匹配层级"] == "基础").sum()) if len(result) else 0,
                "全历史兜底日期数": int((result["匹配层级"] == "全历史").sum()) if len(result) else 0,
            }
        ]
    )

    for col in ["历史上涨占比", "历史平均未来5日上涨比例", "预测未来5日上涨比例", "实际未来5日上涨比例"]:
        result[col] = result[col].map(pct)

    start = dates[0].strftime("%Y%m%d")
    end = dates[-1].strftime("%Y%m%d")
    result_path = output_dir / f"14_市场状态信号预测结果_{start}_{end}.csv"
    summary_path = output_dir / f"14_市场状态信号准确率统计_{start}_{end}.csv"
    result.to_csv(result_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    print(f"市场状态信号预测结果: {result_path}")
    print(result.to_string(index=False))
    print(f"市场状态信号准确率统计: {summary_path}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
