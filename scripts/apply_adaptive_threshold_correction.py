#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from apply_market_risk_correction import corrected_direction, correction_reason, risk_label, summarize
from train_5d_return_model import DEFAULT_OUTPUT_DIR


DEFAULT_DATES = ",".join(
    [
        "20250701",
        "20250715",
        "20250729",
        "20250812",
        "20250826",
        "20250909",
        "20250923",
        "20251015",
        "20251112",
        "20251210",
    ]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用历史相似环境自动选择方向阈值，并复用市场风险修正")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="skill输出目录")
    parser.add_argument("--dates", default=DEFAULT_DATES, help="预测结果日期标签，逗号分隔，格式YYYYMMDD")
    parser.add_argument("--history-date-tags", default="", help="可选：用于阈值学习的历史预测结果日期标签，逗号分隔")
    parser.add_argument("--noise-threshold", type=float, default=0.02, help="降噪阈值，默认2%")
    parser.add_argument("--min-similar-samples", type=int, default=80, help="相似市场环境最少历史股票样本数")
    parser.add_argument("--min-similar-dates", type=int, default=2, help="相似市场环境最少历史日期数")
    parser.add_argument("--min-history-samples", type=int, default=160, help="退化到全部历史时的最少股票样本数")
    parser.add_argument("--threshold-grid", default="0.20,0.25,0.28,0.30,0.335,0.345,0.40,0.45,0.50,0.55,0.615", help="候选阈值")
    parser.add_argument("--overheat-threshold", type=float, default=0.80, help="市场风险修正的过热阈值")
    return parser.parse_args()


def date_tag_to_date(value: str) -> pd.Timestamp:
    return pd.to_datetime(value, format="%Y%m%d")


def discover_prediction_tags(output_dir: Path) -> list[str]:
    tags: list[str] = []
    for path in output_dir.glob("03_每只股票方向预测结果_核心特征_*.csv"):
        tag = path.stem.rsplit("_", 1)[-1]
        if len(tag) == 8 and tag.isdigit():
            tags.append(tag)
    return sorted(set(tags))


def market_proxy(row: pd.Series) -> str:
    if row.get("恐慌释放特征", 0) >= 3 or row.get("弱势延续风险特征", 0) >= 3:
        return "恐慌弱势"
    if row.get("过热回落风险特征", 0) >= 3:
        return "过热回落"
    if (
        row.get("恐慌释放特征", 0) == 0
        and row.get("过热回落风险特征", 0) == 0
        and row.get("弱势延续风险特征", 0) == 0
        and row.get("连续上涨天数", 0) >= 3
        and 0.42 <= row.get("当日上涨比例", 0) <= 0.58
        and -0.20 <= row.get("当日平均涨跌幅", 0) <= 0.80
    ):
        return "平稳高位横盘"
    if row.get("当日上涨比例", 0) >= 0.65 and row.get("当日平均涨跌幅", 0) >= 1.0:
        return "强反弹"
    if row.get("当日上涨比例", 1) <= 0.30 and row.get("当日平均涨跌幅", 0) <= -0.80:
        return "弱回调"
    return "常规"


def load_market_context(output_dir: Path) -> pd.DataFrame:
    market = pd.read_csv(output_dir / "00_市场5日方向预测样本.csv", encoding="utf-8-sig")
    market["日期"] = pd.to_datetime(market["日期"], errors="coerce")
    keep_cols = [
        "日期",
        "未来5日上涨比例",
        "未来5日市场方向",
        "未来5日市场状态",
        "恐慌释放特征",
        "过热回落风险特征",
        "弱势延续风险特征",
        "当日上涨比例",
        "当日平均涨跌幅",
        "上涨行业比例",
        "行业强涨比例_1pct",
        "连续上涨天数",
    ]
    market = market[[col for col in keep_cols if col in market.columns]].rename(
        columns={
            "未来5日上涨比例": "市场未来5日上涨比例",
            "未来5日市场方向": "实际市场方向",
            "未来5日市场状态": "实际市场状态",
        }
    )

    index_path = output_dir / "00_核心指数特征.csv"
    if index_path.exists():
        index_features = pd.read_csv(index_path, encoding="utf-8-sig")
        index_features["日期"] = pd.to_datetime(index_features["日期"], errors="coerce")
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
        market = market.merge(index_features, on="日期", how="left")
    market["市场代理状态"] = market.apply(market_proxy, axis=1)
    return market


def load_predictions(output_dir: Path, tags: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for tag in tags:
        path = output_dir / f"03_每只股票方向预测结果_核心特征_{tag}.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path, encoding="utf-8-sig", dtype={"代码": str})
        frame["代码"] = frame["代码"].str.zfill(6)
        frame["锚点日期"] = pd.to_datetime(frame["锚点日期"], errors="coerce")
        frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce")
        frame["未来卖出日期"] = pd.to_datetime(frame["未来卖出日期"], errors="coerce")
        frame["预测上涨概率"] = pd.to_numeric(frame["预测上涨概率"], errors="coerce")
        frames.append(frame)
    if not frames:
        raise FileNotFoundError("没有找到可用的03_每只股票方向预测结果_核心特征文件")
    return pd.concat(frames, ignore_index=True)


def attach_context(output_dir: Path, pred: pd.DataFrame, market: pd.DataFrame, noise_threshold: float) -> pd.DataFrame:
    label_cols = ["日期", "代码", "5日后的实际涨跌幅"]
    labels = pd.read_csv(output_dir / "00_5日涨跌方向预测样本明细.csv", encoding="utf-8-sig", dtype={"代码": str}, usecols=label_cols)
    labels["代码"] = labels["代码"].str.zfill(6)
    labels["日期"] = pd.to_datetime(labels["日期"], errors="coerce")
    labels["5日后的实际涨跌幅"] = pd.to_numeric(labels["5日后的实际涨跌幅"], errors="coerce")

    feature_cols = ["日期", "代码", "行业平均涨跌幅", "行业上涨比例", "个股强于行业"]
    features = pd.read_csv(output_dir / "00_5日方向模型特征表.csv", encoding="utf-8-sig", dtype={"代码": str}, usecols=feature_cols)
    features["代码"] = features["代码"].str.zfill(6)
    features["日期"] = pd.to_datetime(features["日期"], errors="coerce")

    merged = pred.merge(market, left_on="锚点日期", right_on="日期", how="left", suffixes=("", "_市场"))
    merged = merged.drop(columns=["日期_市场"], errors="ignore")
    merged = merged.merge(labels, on=["日期", "代码"], how="left")
    merged = merged.merge(features, on=["日期", "代码"], how="left")
    merged["是否噪声样本"] = merged["5日后的实际涨跌幅"].abs() <= noise_threshold
    return merged


def best_threshold(history: pd.DataFrame, thresholds: list[float]) -> tuple[float | None, str, int, int, float | None]:
    if history.empty:
        return None, "无历史", 0, 0, None
    best_value = None
    best_acc = -1.0
    best_count = 0
    for threshold in thresholds:
        pred = np.where(history["预测上涨概率"] >= threshold, "上涨", "下跌")
        correct = (pred == history["实际涨跌"]).astype(float)
        acc = float(correct.mean()) if len(correct) else np.nan
        if pd.notna(acc) and acc > best_acc:
            best_acc = acc
            best_value = float(threshold)
            best_count = int(correct.sum())
    return best_value, "历史最优", len(history), best_count, best_acc


def choose_threshold(row: pd.Series, history: pd.DataFrame, thresholds: list[float], args: argparse.Namespace) -> tuple[float, str, int, int, float | None]:
    known_history = history[
        (history["锚点日期"] < row["锚点日期"])
        & (history["未来卖出日期"] <= row["锚点日期"])
        & history["实际涨跌"].notna()
        & history["预测上涨概率"].notna()
    ].copy()
    denoised = known_history.loc[~known_history["是否噪声样本"]].copy()
    similar = denoised.loc[denoised["市场代理状态"] == row["市场代理状态"]].copy()

    similar_dates = similar["锚点日期"].nunique()
    if len(similar) >= args.min_similar_samples and similar_dates >= args.min_similar_dates:
        threshold, _, sample_count, correct_count, acc = best_threshold(similar, thresholds)
        if threshold is not None:
            return threshold, f"相似环境:{row['市场代理状态']}", sample_count, correct_count, acc

    if len(denoised) >= args.min_history_samples:
        threshold, _, sample_count, correct_count, acc = best_threshold(denoised, thresholds)
        if threshold is not None:
            return threshold, "全部历史", sample_count, correct_count, acc

    return float(row["方向阈值"]), "沿用原阈值", 0, 0, None


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    target_tags = [item.strip() for item in args.dates.split(",") if item.strip()]
    history_tags = [item.strip() for item in args.history_date_tags.split(",") if item.strip()] or discover_prediction_tags(output_dir)
    all_tags = sorted(set(target_tags + history_tags))
    thresholds = [float(item) for item in args.threshold_grid.split(",") if item.strip()]

    market = load_market_context(output_dir)
    pred = load_predictions(output_dir, all_tags)
    merged = attach_context(output_dir, pred, market, args.noise_threshold)
    target_dates = {date_tag_to_date(tag) for tag in target_tags}

    rows: list[pd.DataFrame] = []
    threshold_rows: list[dict[str, object]] = []
    for anchor_date in sorted(target_dates):
        day = merged.loc[merged["锚点日期"] == anchor_date].copy()
        if day.empty:
            raise FileNotFoundError(f"缺少目标日期预测结果: {anchor_date:%Y%m%d}")
        threshold, source, sample_count, correct_count, hist_acc = choose_threshold(day.iloc[0], merged, thresholds, args)
        day["自适应方向阈值"] = threshold
        day["自适应阈值来源"] = source
        day["自适应阈值历史样本数"] = sample_count
        day["自适应阈值历史正确数"] = correct_count
        day["自适应阈值历史准确率"] = hist_acc
        day["原始方向阈值"] = day["方向阈值"]
        day["原始预测涨跌"] = day["预测涨跌"]
        day["预测涨跌"] = np.where(day["预测上涨概率"] >= threshold, "上涨", "下跌")
        day["涨跌预测是否准确"] = (day["预测涨跌"] == day["实际涨跌"]).astype(int)
        threshold_rows.append(
            {
                "锚点日期": anchor_date.strftime("%Y-%m-%d"),
                "市场代理状态": day.iloc[0].get("市场代理状态"),
                "原始方向阈值": float(day.iloc[0]["原始方向阈值"]),
                "自适应方向阈值": threshold,
                "自适应阈值来源": source,
                "历史样本数": sample_count,
                "历史正确数": correct_count,
                "历史准确率": "" if hist_acc is None else f"{hist_acc:.2%}",
            }
        )
        rows.append(day)

    result = pd.concat(rows, ignore_index=True)
    result["市场风险标签"] = result.apply(risk_label, axis=1)
    result["自适应阈值预测涨跌"] = result["预测涨跌"]
    result["自适应阈值预测是否准确"] = result["涨跌预测是否准确"].astype(int)
    result["修正原因"] = result.apply(lambda row: correction_reason(row, args.overheat_threshold), axis=1)
    result["修正后预测涨跌"] = result.apply(corrected_direction, axis=1)
    result["修正后预测是否准确"] = (result["修正后预测涨跌"] == result["实际涨跌"]).astype(int)
    result["是否发生修正"] = (result["修正后预测涨跌"] != result["自适应阈值预测涨跌"]).astype(int)

    start_tag = target_tags[0]
    end_tag = target_tags[-1]
    detail_path = output_dir / f"13_自适应阈值市场风险修正明细_{start_tag}_{end_tag}.csv"
    total_path = output_dir / f"13_自适应阈值总体对比_{start_tag}_{end_tag}.csv"
    threshold_path = output_dir / f"13_每日自适应阈值选择_{start_tag}_{end_tag}.csv"
    date_path = output_dir / f"13_按日期自适应阈值效果_{start_tag}_{end_tag}.csv"

    denoised = result.loc[~result["是否噪声样本"]]
    total = pd.DataFrame(
        [
            {
                "股票预测数": len(result),
                "噪声样本数": int(result["是否噪声样本"].sum()),
                "降噪后股票预测数": len(denoised),
                "原始正确数": int((result["原始预测涨跌"] == result["实际涨跌"]).sum()),
                "自适应阈值正确数": int(result["自适应阈值预测是否准确"].sum()),
                "修正后正确数": int(result["修正后预测是否准确"].sum()),
                "原始准确率": f"{((result['原始预测涨跌'] == result['实际涨跌']).mean()):.2%}",
                "自适应阈值准确率": f"{result['自适应阈值预测是否准确'].mean():.2%}",
                "修正后准确率": f"{result['修正后预测是否准确'].mean():.2%}",
                "降噪后原始正确数": int((denoised["原始预测涨跌"] == denoised["实际涨跌"]).sum()),
                "降噪后自适应阈值正确数": int(denoised["自适应阈值预测是否准确"].sum()),
                "降噪后修正后正确数": int(denoised["修正后预测是否准确"].sum()),
                "降噪后原始准确率": f"{((denoised['原始预测涨跌'] == denoised['实际涨跌']).mean()):.2%}",
                "降噪后自适应阈值准确率": f"{denoised['自适应阈值预测是否准确'].mean():.2%}",
                "降噪后修正后准确率": f"{denoised['修正后预测是否准确'].mean():.2%}",
            }
        ]
    )

    by_date_original = summarize(result, "原始预测涨跌", "涨跌预测是否准确", ["锚点日期", "实际市场状态", "市场代理状态"]).rename(
        columns={"预测正确数": "自适应阈值正确数", "方向准确率": "自适应阈值准确率", "降噪后预测正确数": "降噪后自适应阈值正确数", "降噪后方向准确率": "降噪后自适应阈值准确率"}
    )
    by_date_corrected = summarize(result, "修正后预测涨跌", "修正后预测是否准确", ["锚点日期", "实际市场状态", "市场代理状态"]).rename(
        columns={"预测正确数": "修正后正确数", "方向准确率": "修正后准确率", "降噪后预测正确数": "降噪后修正后正确数", "降噪后方向准确率": "降噪后修正后准确率"}
    )
    by_date = by_date_original.merge(
        by_date_corrected[["锚点日期", "实际市场状态", "市场代理状态", "修正后正确数", "修正后准确率", "降噪后修正后正确数", "降噪后修正后准确率"]],
        on=["锚点日期", "实际市场状态", "市场代理状态"],
        how="left",
    )

    for col in ["锚点日期", "日期", "未来卖出日期"]:
        if col in result.columns:
            result[col] = pd.to_datetime(result[col], errors="coerce").dt.strftime("%Y-%m-%d")
    result.to_csv(detail_path, index=False, encoding="utf-8-sig")
    total.to_csv(total_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(threshold_rows).to_csv(threshold_path, index=False, encoding="utf-8-sig")
    by_date.to_csv(date_path, index=False, encoding="utf-8-sig")

    print(f"明细: {detail_path}")
    print(f"总体: {total_path}")
    print(total.to_string(index=False))
    print(f"每日阈值: {threshold_path}")
    print(pd.DataFrame(threshold_rows).to_string(index=False))
    print(f"按日期: {date_path}")
    print(by_date.to_string(index=False))


if __name__ == "__main__":
    main()
