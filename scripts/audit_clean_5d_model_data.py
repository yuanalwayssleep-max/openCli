#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from train_5d_return_model import DEFAULT_OUTPUT_DIR


DEFAULT_BASE_CSV = DEFAULT_OUTPUT_DIR / "00_A股日K基础行情与5日后标签表.csv"
DEFAULT_FEATURE_CSV = DEFAULT_OUTPUT_DIR / "00_5日方向模型特征表.csv"
DEFAULT_SAMPLE_CSV = DEFAULT_OUTPUT_DIR / "00_5日涨跌方向预测样本明细.csv"

KEY_COLS = ["日期", "代码"]
BASE_NUMERIC_COLS = [
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
    "5日后的实际涨跌幅",
    "5日后上涨标签",
]
PRICE_COLS = ["开盘", "收盘", "最高", "最低"]
CORE_REQUIRED_COLS = ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]
HARD_ISSUES = {
    "主键缺失",
    "日期无效",
    "代码无效",
    "日期代码重复",
    "核心行情字段缺失",
    "价格非正",
    "高低开收逻辑错误",
    "成交量或成交额非正",
}


def limit_pct(row: pd.Series) -> float:
    board = str(row.get("板块", ""))
    exchange = str(row.get("交易所", ""))
    code = str(row.get("代码", ""))
    name = str(row.get("名称", "")).upper()
    if "ST" in name:
        return 5.0
    if "北交所" in board or "北交所" in exchange or code.startswith(("4", "8", "9")):
        return 30.0
    if "创业板" in board or "科创" in board or code.startswith(("300", "301", "688")):
        return 20.0
    return 10.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A股5日方向建模数据质量清洗与审计")
    parser.add_argument("--base-csv", default=str(DEFAULT_BASE_CSV), help="A股日K基础行情与5日后标签表")
    parser.add_argument("--feature-csv", default=str(DEFAULT_FEATURE_CSV), help="5日方向模型特征表")
    parser.add_argument("--sample-csv", default=str(DEFAULT_SAMPLE_CSV), help="5日涨跌方向预测样本明细")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--target-diff-tolerance", type=float, default=0.002, help="5日收益率复核容忍度")
    parser.add_argument("--pct-diff-tolerance", type=float, default=0.5, help="涨跌幅复核容忍度，单位百分点")
    parser.add_argument("--feature-missing-soft-threshold", type=float, default=0.35, help="单行特征缺失率软异常阈值")
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, encoding="utf-8-sig", dtype={"代码": str})


def normalize_base(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["代码"] = out["代码"].astype(str).str.extract(r"(\d+)", expand=False).fillna("").str.zfill(6)
    out["日期"] = pd.to_datetime(out["日期"], errors="coerce")
    if "卖出日" in out.columns:
        out["卖出日"] = pd.to_datetime(out["卖出日"], errors="coerce")
    for col in BASE_NUMERIC_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.sort_values(["代码", "日期"], na_position="last").reset_index(drop=True)


def normalize_feature(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["代码"] = out["代码"].astype(str).str.extract(r"(\d+)", expand=False).fillna("").str.zfill(6)
    out["日期"] = pd.to_datetime(out["日期"], errors="coerce")
    for col in out.columns:
        if col not in KEY_COLS:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.sort_values(["代码", "日期"], na_position="last").reset_index(drop=True)


def add_issue(issues: list[list[str]], mask: pd.Series, name: str) -> None:
    idx = np.flatnonzero(mask.fillna(False).to_numpy())
    for i in idx:
        issues[i].append(name)


def audit_base(base: pd.DataFrame, target_diff_tolerance: float, pct_diff_tolerance: float) -> pd.DataFrame:
    out = base.copy()
    issues: list[list[str]] = [[] for _ in range(len(out))]

    missing_key = out["日期"].isna() | out["代码"].isna() | (out["代码"] == "")
    add_issue(issues, missing_key, "主键缺失")
    add_issue(issues, out["日期"].isna(), "日期无效")
    add_issue(issues, ~out["代码"].astype(str).str.fullmatch(r"\d{6}"), "代码无效")
    add_issue(issues, out.duplicated(KEY_COLS, keep=False), "日期代码重复")

    required_existing = [col for col in CORE_REQUIRED_COLS if col in out.columns]
    if required_existing:
        add_issue(issues, out[required_existing].isna().any(axis=1), "核心行情字段缺失")

    price_existing = [col for col in PRICE_COLS if col in out.columns]
    if price_existing:
        add_issue(issues, (out[price_existing] <= 0).any(axis=1), "价格非正")
        high_logic = out["最高"] < out[["开盘", "收盘", "最低"]].max(axis=1)
        low_logic = out["最低"] > out[["开盘", "收盘", "最高"]].min(axis=1)
        add_issue(issues, high_logic | low_logic | (out["最高"] < out["最低"]), "高低开收逻辑错误")

    if {"成交量", "成交额"}.issubset(out.columns):
        add_issue(issues, (out["成交量"] <= 0) | (out["成交额"] <= 0), "成交量或成交额非正")

    if "卖出日" in out.columns:
        add_issue(issues, out["卖出日"].notna() & out["日期"].notna() & (out["卖出日"] <= out["日期"]), "卖出日不晚于锚点日")

    if {"收盘", "5日后收盘", "5日后的实际涨跌幅"}.issubset(out.columns):
        expected_target = out["5日后收盘"] / out["收盘"].replace(0, np.nan) - 1
        target_diff = (expected_target - out["5日后的实际涨跌幅"]).abs()
        add_issue(issues, target_diff > target_diff_tolerance, "5日收益率与5日后收盘不一致")
        out["5日收益率复核差值"] = target_diff

    if {"收盘", "涨跌幅"}.issubset(out.columns):
        prev_close = out.groupby("代码")["收盘"].shift(1)
        expected_pct = (out["收盘"] / prev_close.replace(0, np.nan) - 1) * 100
        pct_diff = (expected_pct - out["涨跌幅"]).abs()
        add_issue(issues, prev_close.notna() & (pct_diff > pct_diff_tolerance), "涨跌幅与前收盘复核不一致")
        out["涨跌幅复核差值"] = pct_diff

    if "涨跌幅" in out.columns:
        add_issue(issues, out["涨跌幅"].abs() > 30, "涨跌幅极端异常")
        limits = out.apply(limit_pct, axis=1)
        add_issue(issues, out["涨跌幅"] >= limits * 0.95, "接近涨停极端行情")
        add_issue(issues, out["涨跌幅"] <= -limits * 0.95, "接近跌停极端行情")
    if "振幅" in out.columns:
        add_issue(issues, (out["振幅"] < 0) | (out["振幅"] > 40), "振幅极端异常")
    if "换手率" in out.columns:
        add_issue(issues, (out["换手率"] < 0) | (out["换手率"] > 80), "换手率极端异常")

    out["数据质量问题"] = [";".join(item) for item in issues]
    out["数据质量问题数"] = [len(item) for item in issues]
    out["是否硬异常"] = [int(any(issue in HARD_ISSUES for issue in item)) for item in issues]
    out["是否软异常"] = ((out["数据质量问题数"] > 0) & (out["是否硬异常"] == 0)).astype(int)
    out["是否通过清洗"] = (out["是否硬异常"] == 0).astype(int)
    return out


def audit_feature(feature: pd.DataFrame, feature_missing_soft_threshold: float) -> pd.DataFrame:
    out = feature.copy()
    feature_cols = [col for col in out.columns if col not in KEY_COLS]
    if feature_cols:
        numeric = out[feature_cols]
        out["特征字段数"] = len(feature_cols)
        out["特征缺失字段数"] = numeric.isna().sum(axis=1)
        out["特征无穷字段数"] = np.isinf(numeric.to_numpy(dtype=float, copy=True)).sum(axis=1)
        out["特征缺失率"] = out["特征缺失字段数"] / len(feature_cols)
        out["是否特征缺失偏高"] = (out["特征缺失率"] > feature_missing_soft_threshold).astype(int)
    else:
        out["特征字段数"] = 0
        out["特征缺失字段数"] = 0
        out["特征无穷字段数"] = 0
        out["特征缺失率"] = 0.0
        out["是否特征缺失偏高"] = 0
    return out


def build_field_missing_report(base_marked: pd.DataFrame, feature_marked: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for table_name, df in [("基础行情表", base_marked), ("模型特征表", feature_marked)]:
        for col in df.columns:
            missing = int(df[col].isna().sum())
            rows.append(
                {
                    "表名": table_name,
                    "字段": col,
                    "总行数": len(df),
                    "缺失行数": missing,
                    "缺失率": f"{missing / len(df):.2%}" if len(df) else "",
                }
            )
    return pd.DataFrame(rows)


def aggregate_issue_detail(base_marked: pd.DataFrame) -> pd.DataFrame:
    problem = base_marked[base_marked["数据质量问题数"] > 0].copy()
    if problem.empty:
        return pd.DataFrame(columns=["日期", "代码", "名称", "数据质量问题", "是否硬异常", "是否软异常"])
    keep_cols = [
        col
        for col in [
            "日期",
            "代码",
            "名称",
            "行业",
            "板块",
            "开盘",
            "收盘",
            "最高",
            "最低",
            "成交量",
            "成交额",
            "涨跌幅",
            "振幅",
            "换手率",
            "卖出日",
            "5日后的实际涨跌幅",
            "数据质量问题",
            "是否硬异常",
            "是否软异常",
        ]
        if col in problem.columns
    ]
    return problem[keep_cols].sort_values(["是否硬异常", "日期", "代码"], ascending=[False, True, True])


def aggregate_by_date(base_marked: pd.DataFrame, feature_marked: pd.DataFrame) -> pd.DataFrame:
    base_stats = (
        base_marked.groupby("日期", dropna=False)
        .agg(
            样本数=("代码", "count"),
            硬异常数=("是否硬异常", "sum"),
            软异常数=("是否软异常", "sum"),
            通过清洗数=("是否通过清洗", "sum"),
        )
        .reset_index()
    )
    feature_stats = (
        feature_marked.groupby("日期", dropna=False)
        .agg(
            特征缺失偏高数=("是否特征缺失偏高", "sum"),
            平均特征缺失率=("特征缺失率", "mean"),
        )
        .reset_index()
    )
    out = base_stats.merge(feature_stats, on="日期", how="left")
    out["硬异常率"] = out["硬异常数"] / out["样本数"]
    out["软异常率"] = out["软异常数"] / out["样本数"]
    return out


def aggregate_by_stock(base_marked: pd.DataFrame, feature_marked: pd.DataFrame) -> pd.DataFrame:
    name_cols = [col for col in ["名称", "行业", "板块", "交易所"] if col in base_marked.columns]
    base_agg = {col: (col, "last") for col in name_cols}
    base_stats = (
        base_marked.groupby("代码", dropna=False)
        .agg(
            **base_agg,
            样本数=("日期", "count"),
            硬异常数=("是否硬异常", "sum"),
            软异常数=("是否软异常", "sum"),
            通过清洗数=("是否通过清洗", "sum"),
        )
        .reset_index()
    )
    feature_stats = (
        feature_marked.groupby("代码", dropna=False)
        .agg(
            特征缺失偏高数=("是否特征缺失偏高", "sum"),
            平均特征缺失率=("特征缺失率", "mean"),
        )
        .reset_index()
    )
    out = base_stats.merge(feature_stats, on="代码", how="left")
    out["硬异常率"] = out["硬异常数"] / out["样本数"]
    out["软异常率"] = out["软异常数"] / out["样本数"]
    return out.sort_values(["硬异常数", "软异常数", "平均特征缺失率"], ascending=False)


def issue_summary(base_marked: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for text in base_marked["数据质量问题"].fillna(""):
        for issue in [item for item in text.split(";") if item]:
            rows.append({"问题类型": issue})
    if not rows:
        return pd.DataFrame(columns=["问题类型", "问题行数", "是否硬异常类型"])
    out = pd.DataFrame(rows).value_counts("问题类型").reset_index(name="问题行数")
    out["是否硬异常类型"] = out["问题类型"].isin(HARD_ISSUES).astype(int)
    return out.sort_values(["是否硬异常类型", "问题行数"], ascending=False)


def fmt_pct(value: float) -> str:
    if pd.isna(value):
        return ""
    return f"{value:.2%}"


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    base = normalize_base(read_csv(Path(args.base_csv).resolve()))
    feature = normalize_feature(read_csv(Path(args.feature_csv).resolve()))
    base_marked = audit_base(base, args.target_diff_tolerance, args.pct_diff_tolerance)
    feature_marked = audit_feature(feature, args.feature_missing_soft_threshold)

    quality_flags = base_marked[KEY_COLS + ["是否硬异常", "是否软异常", "是否通过清洗"]].merge(
        feature_marked[KEY_COLS + ["是否特征缺失偏高", "特征缺失率"]],
        on=KEY_COLS,
        how="left",
    )
    quality_flags["是否特征缺失偏高"] = quality_flags["是否特征缺失偏高"].fillna(1).astype(int)
    quality_flags["是否建议纳入训练"] = (
        (quality_flags["是否硬异常"] == 0)
        & (quality_flags["是否软异常"] == 0)
        & (quality_flags["是否特征缺失偏高"] == 0)
    ).astype(int)

    clean_keys = base_marked.loc[base_marked["是否通过清洗"] == 1, KEY_COLS].drop_duplicates()
    train_keys = quality_flags.loc[quality_flags["是否建议纳入训练"] == 1, KEY_COLS].drop_duplicates()
    clean_base = base_marked.merge(clean_keys, on=KEY_COLS, how="inner")
    clean_feature = feature.merge(clean_keys, on=KEY_COLS, how="inner")
    train_base = base_marked.merge(train_keys, on=KEY_COLS, how="inner")
    train_feature = feature.merge(train_keys, on=KEY_COLS, how="inner")

    sample_path = Path(args.sample_csv).resolve()
    clean_sample = pd.DataFrame()
    if sample_path.exists():
        sample = read_csv(sample_path)
        sample["代码"] = sample["代码"].astype(str).str.extract(r"(\d+)", expand=False).fillna("").str.zfill(6)
        sample["日期"] = pd.to_datetime(sample["日期"], errors="coerce")
        clean_sample = sample.merge(clean_keys, on=KEY_COLS, how="inner")
        train_sample = sample.merge(train_keys, on=KEY_COLS, how="inner")
    else:
        train_sample = pd.DataFrame()

    total = pd.DataFrame(
        [
            {
                "基础表总行数": len(base_marked),
                "通过清洗行数": int(base_marked["是否通过清洗"].sum()),
                "剔除硬异常行数": int(base_marked["是否硬异常"].sum()),
                "软异常标记行数": int(base_marked["是否软异常"].sum()),
                "通过清洗率": fmt_pct(float(base_marked["是否通过清洗"].mean())),
                "硬异常率": fmt_pct(float(base_marked["是否硬异常"].mean())),
                "软异常率": fmt_pct(float(base_marked["是否软异常"].mean())),
                "特征表总行数": len(feature_marked),
                "特征缺失偏高行数": int(feature_marked["是否特征缺失偏高"].sum()),
                "平均特征缺失率": fmt_pct(float(feature_marked["特征缺失率"].mean())),
                "清洗后样本明细行数": len(clean_sample) if not clean_sample.empty else "",
                "建议纳入训练行数": int(quality_flags["是否建议纳入训练"].sum()),
                "建议纳入训练率": fmt_pct(float(quality_flags["是否建议纳入训练"].mean())),
                "严格建模样本明细行数": len(train_sample) if not train_sample.empty else "",
            }
        ]
    )

    output_paths = {
        "基础清洗标记表": output_dir / "11_A股日K基础行情数据质量清洗标记.csv",
        "清洗后基础表": output_dir / "11_A股日K基础行情与5日后标签表_清洗后.csv",
        "清洗后特征表": output_dir / "11_5日方向模型特征表_清洗后.csv",
        "清洗后样本明细": output_dir / "11_5日涨跌方向预测样本明细_清洗后.csv",
        "严格建模基础表": output_dir / "11_A股日K基础行情与5日后标签表_严格建模可用.csv",
        "严格建模特征表": output_dir / "11_5日方向模型特征表_严格建模可用.csv",
        "严格建模样本明细": output_dir / "11_5日涨跌方向预测样本明细_严格建模可用.csv",
        "训练建议标记": output_dir / "11_建模训练样本质量标记.csv",
        "总体汇总": output_dir / "11_数据质量审计总体汇总.csv",
        "问题类型汇总": output_dir / "11_数据质量问题类型汇总.csv",
        "问题明细": output_dir / "11_数据质量问题明细.csv",
        "按日期汇总": output_dir / "11_按日期数据质量汇总.csv",
        "按股票汇总": output_dir / "11_按股票数据质量汇总.csv",
        "字段缺失率": output_dir / "11_字段缺失率审计.csv",
    }

    base_marked.to_csv(output_paths["基础清洗标记表"], index=False, encoding="utf-8-sig")
    clean_base.to_csv(output_paths["清洗后基础表"], index=False, encoding="utf-8-sig")
    clean_feature.to_csv(output_paths["清洗后特征表"], index=False, encoding="utf-8-sig")
    train_base.to_csv(output_paths["严格建模基础表"], index=False, encoding="utf-8-sig")
    train_feature.to_csv(output_paths["严格建模特征表"], index=False, encoding="utf-8-sig")
    quality_flags.to_csv(output_paths["训练建议标记"], index=False, encoding="utf-8-sig")
    if not clean_sample.empty:
        clean_sample.to_csv(output_paths["清洗后样本明细"], index=False, encoding="utf-8-sig")
    if not train_sample.empty:
        train_sample.to_csv(output_paths["严格建模样本明细"], index=False, encoding="utf-8-sig")
    total.to_csv(output_paths["总体汇总"], index=False, encoding="utf-8-sig")
    issue_summary(base_marked).to_csv(output_paths["问题类型汇总"], index=False, encoding="utf-8-sig")
    aggregate_issue_detail(base_marked).to_csv(output_paths["问题明细"], index=False, encoding="utf-8-sig")
    aggregate_by_date(base_marked, feature_marked).to_csv(output_paths["按日期汇总"], index=False, encoding="utf-8-sig")
    aggregate_by_stock(base_marked, feature_marked).to_csv(output_paths["按股票汇总"], index=False, encoding="utf-8-sig")
    build_field_missing_report(base_marked, feature_marked).to_csv(output_paths["字段缺失率"], index=False, encoding="utf-8-sig")

    print("数据质量审计完成")
    for name, path in output_paths.items():
        if path.exists():
            print(f"{name}: {path}")
    print(total.to_string(index=False))
    print("\n问题类型汇总:")
    print(issue_summary(base_marked).to_string(index=False))


if __name__ == "__main__":
    main()
